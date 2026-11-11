"""Persistent training lifecycle using the existing Repository connection.

All public mutations are local and transactional. Events identify requests, UUIDs
identify real sessions/sets, and revisions expose competing edits. Public catalog
seeds and private user edits remain separate from any literature search index.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from uuid import NAMESPACE_URL, uuid4, uuid5

from .schema import migrate_training
from .semantics import (
    LOAD_BASES,
    MEASUREMENT_MODES,
    TrainingError,
    condition_snapshot,
    json_text,
    load_semantics,
    numeric,
    timestamp,
)

SET_STATES = {"draft", "in_progress", "completed", "aborted", "skipped"}
SET_TYPES = {"warmup", "work", "assessment", "other"}
STOP_REASONS = {
    "plan_target",
    "target_rir",
    "volitional_failure",
    "technical_limit",
    "pain",
    "other",
    "unknown",
}
SESSION_STATES = {"draft", "in_progress", "paused", "completed", "aborted"}
SCALES = {"cr10": (0, 10), "borg6_20": (6, 20), "rir_rpe10": (1, 10)}


def _decode(row) -> Optional[dict]:
    if row is None:
        return None
    result = dict(row)
    for key, value in list(result.items()):
        if key.endswith("_json"):
            result[key[:-5]] = json.loads(value) if value is not None else None
    return result


def _uuid(event_id: str, suffix: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"healthzip:{event_id}:{suffix}"))


class TrainingService:
    def __init__(self, repo, user_id: str = "local", device_id: str = "local"):
        if not user_id.strip() or not device_id.strip():
            raise TrainingError("user_id/device_id 不能为空")
        self.repo, self.conn = repo, repo.conn
        self.user_id, self.device_id = user_id, device_id
        migrate_training(self.conn)
        self._seed_catalog()

    @contextmanager
    def _transaction(self):
        token = "training_" + uuid4().hex
        self.conn.execute(f"SAVEPOINT {token}")
        try:
            yield
            self.conn.execute(f"RELEASE SAVEPOINT {token}")
        except BaseException:
            self.conn.execute(f"ROLLBACK TO SAVEPOINT {token}")
            self.conn.execute(f"RELEASE SAVEPOINT {token}")
            raise

    def _seed_catalog(self):
        seed = json.loads(Path(__file__).with_name("exercise_catalog_seed.json").read_text())
        with self._transaction():
            for item in seed["exercises"]:
                self.conn.execute(
                    "INSERT OR IGNORE INTO exercise_catalog(exercise_id,definition_version,owner_id,name,definition_json,custom,active,created_at) VALUES(?,?,?,?,?,0,1,?)",
                    (
                        item["exercise_id"],
                        item["definition_version"],
                        "public",
                        item["name_zh"],
                        json_text(item),
                        seed["created_date"],
                    ),
                )
            self.conn.execute(
                "INSERT OR IGNORE INTO schema_meta(key,value) VALUES('training_data_version','0')"
            )

    def data_version(self) -> str:
        return self.conn.execute(
            "SELECT value FROM schema_meta WHERE key='training_data_version'"
        ).fetchone()[0]

    def _invalidate(
        self,
        event_id: str,
        entity_type: str,
        entity_id: str,
        affected_from=None,
        *,
        mark_recommendations_stale=True,
    ):
        self.conn.execute(
            "UPDATE schema_meta SET value=CAST(value AS INTEGER)+1 WHERE key='training_data_version'"
        )
        self.conn.execute(
            "INSERT INTO training_invalidation(event_id,user_id,entity_type,entity_id,affected_from,created_at) VALUES(?,?,?,?,?,?)",
            (event_id, self.user_id, entity_type, entity_id, affected_from, timestamp()),
        )
        # Frozen inputs are never rewritten; current display may flag them stale.
        if mark_recommendations_stale:
            self.conn.execute(
                "UPDATE training_recommendation SET stale=1 WHERE user_id=?", (self.user_id,)
            )
        if self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='analysis_run'"
        ).fetchone():
            columns = {r[1] for r in self.conn.execute("PRAGMA table_info(analysis_run)")}
            if "invalidated_at" in columns:
                self.conn.execute(
                    "UPDATE analysis_run SET invalidated_at=? WHERE invalidated_at IS NULL",
                    (timestamp(),),
                )
        for table in ("daily_feature", "insight"):
            if self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                # These caches have no revision history; preserve source facts and
                # immutable recommendations, rebuild caches on the next analysis.
                self.conn.execute(f"DELETE FROM {table}")

    def pending_invalidations(self) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM training_invalidation WHERE user_id=? AND status='pending' ORDER BY id",
                (self.user_id,),
            )
        ]

    def mark_recomputed(self, analysis_version: str, through_id: int):
        with self._transaction():
            self.conn.execute(
                "UPDATE training_invalidation SET status='recomputed',analysis_version=? WHERE user_id=? AND id<=?",
                (analysis_version, self.user_id, through_id),
            )

    def _mutate(
        self,
        action: str,
        kind: str,
        identity: str,
        payload: dict,
        apply: Callable,
        *,
        event_id: Optional[str] = None,
        base_revision=None,
        before: Optional[Callable] = None,
        occurred_at=None,
        invalidates=True,
    ) -> dict:
        event_id = event_id or str(uuid4())
        request = {
            "action": action,
            "kind": kind,
            "identity": str(identity),
            "payload": payload,
            "base_revision": base_revision,
        }
        digest = hashlib.sha256(json_text(request).encode()).hexdigest()
        with self._transaction():
            saved = self.conn.execute(
                "SELECT * FROM training_event WHERE event_id=?", (event_id,)
            ).fetchone()
            if saved:
                if saved["user_id"] != self.user_id or saved["payload_hash"] != digest:
                    raise TrainingError("event_id 已用于其他请求；重试必须使用相同请求内容")
                result = json.loads(saved["result_json"])
                return {**result, "replayed": True}
            current = before() if before else None
            recorded = timestamp()
            occurred = timestamp(occurred_at) if occurred_at else recorded
            if base_revision is not None and (
                current is None or current.get("revision") != base_revision
            ):
                conflict_id = _uuid(event_id, "conflict")
                result = {
                    "status": "conflicted",
                    "conflict_id": conflict_id,
                    "event_id": event_id,
                    "current_revision": current.get("revision") if current else None,
                    "current": current,
                    "proposed": payload,
                }
                self.conn.execute(
                    "INSERT INTO training_conflict(id,user_id,event_id,entity_type,entity_id,base_revision,current_revision,current_json,proposed_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        conflict_id,
                        self.user_id,
                        event_id,
                        kind,
                        str(identity),
                        base_revision,
                        current.get("revision") if current else None,
                        json_text(current),
                        json_text(payload),
                        recorded,
                    ),
                )
                after, status = current, "conflicted"
            else:
                result = apply(current, event_id, recorded)
                if result is None:
                    result = {}
                if (
                    kind == "set"
                    and action in {"add_set", "edit_set", "delete_set", "undo_event"}
                    and result.get("set_uuid")
                ):
                    self._rederive_session_rest(
                        result["session_id"], event_id, recorded, result["id"]
                    )
                    result = {**result, **self.get_set(result["id"])}
                result = {"status": "saved", **result, "event_id": event_id}
                after, status = result, "applied"
                if invalidates:
                    self._invalidate(event_id, kind, str(identity), occurred)
            self.conn.execute(
                "INSERT INTO training_event(event_id,user_id,device_id,entity_type,entity_id,action,base_revision,payload_hash,payload_json,occurred_at,recorded_at,status,before_json,after_json,result_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    self.user_id,
                    self.device_id,
                    kind,
                    str(identity),
                    action,
                    base_revision,
                    digest,
                    json_text(payload),
                    occurred,
                    recorded,
                    status,
                    json_text(current) if current is not None else None,
                    json_text(after) if after is not None else None,
                    json_text(result),
                ),
            )
            return result

    def get_exercise(self, exercise_id: str, version: Optional[int] = None) -> dict:
        sql = "SELECT * FROM exercise_catalog WHERE exercise_id=? AND owner_id IN ('public',?)"
        args = [exercise_id, self.user_id]
        if version is not None:
            sql += " AND definition_version=?"
            args.append(version)
        row = self.conn.execute(sql + " ORDER BY definition_version DESC LIMIT 1", args).fetchone()
        if row is None:
            raise TrainingError("找不到此动作")
        result = json.loads(row["definition_json"])
        result.update(
            custom=bool(row["custom"]),
            owner_id=row["owner_id"],
            name=row["name"],
            revision=row["revision"],
        )
        return result

    def search_exercises(
        self,
        query: str = "",
        *,
        regions=None,
        equipment=None,
        patterns=None,
        load_bases=None,
        view: str = "all",
    ) -> list[dict]:
        if view not in {"all", "recent", "favorites", "custom"}:
            raise TrainingError("未知动作视图")
        rows = self.conn.execute(
            "SELECT c.* FROM exercise_catalog c WHERE owner_id IN ('public',?) AND active=1 "
            "AND definition_version=(SELECT MAX(definition_version) FROM exercise_catalog x WHERE x.exercise_id=c.exercise_id)",
            (self.user_id,),
        )
        prefs = {
            r["exercise_id"]: dict(r)
            for r in self.conn.execute(
                "SELECT * FROM exercise_preference WHERE user_id=?", (self.user_id,)
            )
        }
        aliases = {}
        for r in self.conn.execute("SELECT * FROM exercise_alias WHERE user_id=?", (self.user_id,)):
            aliases.setdefault(r["exercise_id"], []).append(r["alias"])
        result = []
        for row in rows:
            item = json.loads(row["definition_json"])
            key = item["exercise_id"]
            pref = prefs.get(key, {})
            item.update(
                name=row["name"],
                revision=row["revision"],
                custom=bool(row["custom"]),
                favorite=bool(pref.get("favorite")),
                last_used_at=pref.get("last_used_at"),
                user_aliases=aliases.get(key, []),
            )
            haystack = " ".join(
                [row["name"], key, *item.get("aliases_zh", []), *item["user_aliases"]]
            ).casefold()
            if query.casefold() not in haystack:
                continue
            if regions and not set(regions).intersection(item.get("display_regions", [])):
                continue
            if equipment and item["equipment_type"] not in equipment:
                continue
            if patterns and not set(patterns).intersection(item.get("movement_patterns", [])):
                continue
            if load_bases and item["default_load_basis"] not in load_bases:
                continue
            if view == "favorites" and not item["favorite"]:
                continue
            if view == "recent" and not item["last_used_at"]:
                continue
            if view == "custom" and not item["custom"]:
                continue
            result.append(item)
        return sorted(
            result, key=lambda x: (x.get("last_used_at") or "", x["name"]), reverse=view == "recent"
        )

    def create_exercise(
        self,
        name: str,
        recording_mode: str,
        equipment_type: str,
        load_basis: str,
        *,
        regions=None,
        aliases=None,
        exercise_id=None,
        event_id=None,
        movement_patterns=None,
    ) -> dict:
        if not name.strip() or not equipment_type.strip():
            raise TrainingError("动作名称和器械类型必填")
        if recording_mode not in MEASUREMENT_MODES or load_basis not in LOAD_BASES:
            raise TrainingError("请选择有效记录模式与负荷口径")
        event_id = event_id or str(uuid4())
        exercise_id = exercise_id or "custom." + _uuid(event_id, "exercise")
        definition = {
            "exercise_id": exercise_id,
            "definition_version": 1,
            "name_zh": name.strip(),
            "recording_mode": recording_mode,
            "equipment_type": equipment_type,
            "default_load_basis": load_basis,
            "display_regions": regions or [],
            "aliases_zh": aliases or [],
            "movement_patterns": movement_patterns or [],
            "scientific_review": {"status": "unreviewed", "source_ids": []},
            "muscle_participation_proposals": [],
            "status": "private_custom",
        }

        def apply(current, eid, now):
            self.conn.execute(
                "INSERT INTO exercise_catalog(exercise_id,definition_version,owner_id,name,definition_json,custom,active,created_at) VALUES(?,1,?,?,?,1,1,?)",
                (exercise_id, self.user_id, name.strip(), json_text(definition), now),
            )
            return self.get_exercise(exercise_id)

        return self._mutate(
            "create_exercise", "exercise", exercise_id, definition, apply, event_id=event_id
        )

    def update_exercise(
        self, exercise_id: str, changes: dict, *, base_revision: int, event_id=None
    ) -> dict:
        allowed = {
            "name_zh",
            "aliases_zh",
            "recording_mode",
            "equipment_type",
            "default_load_basis",
            "display_regions",
            "movement_patterns",
            "variant_of",
        }
        if set(changes) - allowed:
            raise TrainingError("只能修改明确的动作目录字段；科学审核须走证据审核流程")
        existing = self.get_exercise(exercise_id)
        if not existing["custom"] or existing["owner_id"] != self.user_id:
            raise TrainingError("公共动作请添加用户别名或复制为自定义变式")

        def before():
            item = self.get_exercise(exercise_id)
            return item

        def apply(old, eid, now):
            changed = {**old, **changes}
            if (
                changed["recording_mode"] not in MEASUREMENT_MODES
                or changed["default_load_basis"] not in LOAD_BASES
            ):
                raise TrainingError("无效记录模式或口径")
            # Label-only edits preserve semantic version and therefore comparison identity.
            semantic = any(
                key in changes and changes[key] != old.get(key)
                for key in ("recording_mode", "equipment_type", "default_load_basis", "variant_of")
            )
            if semantic:
                changed["definition_version"] += 1
                changed["revision"] = old["revision"] + 1
                self.conn.execute(
                    "INSERT INTO exercise_catalog(exercise_id,definition_version,owner_id,name,definition_json,custom,active,created_at,revision) VALUES(?,?,?,?,?,1,1,?,?)",
                    (
                        exercise_id,
                        changed["definition_version"],
                        self.user_id,
                        changed["name_zh"],
                        json_text(changed),
                        now,
                        changed["revision"],
                    ),
                )
            else:
                self.conn.execute(
                    "UPDATE exercise_catalog SET name=?,definition_json=?,revision=revision+1 WHERE exercise_id=? AND definition_version=?",
                    (
                        changed["name_zh"],
                        json_text(changed),
                        exercise_id,
                        old["definition_version"],
                    ),
                )
            return self.get_exercise(exercise_id)

        return self._mutate(
            "update_exercise",
            "exercise",
            exercise_id,
            changes,
            apply,
            event_id=event_id,
            base_revision=base_revision,
            before=before,
        )

    def add_alias(self, exercise_id: str, alias: str):
        self.get_exercise(exercise_id)
        if not alias.strip():
            raise TrainingError("别名不能为空")
        with self._transaction():
            self.conn.execute(
                "INSERT OR IGNORE INTO exercise_alias(user_id,exercise_id,alias) VALUES(?,?,?)",
                (self.user_id, exercise_id, alias.strip()),
            )

    def favorite(self, exercise_id: str, enabled: bool = True):
        self.get_exercise(exercise_id)
        with self._transaction():
            self.conn.execute(
                "INSERT INTO exercise_preference(user_id,exercise_id,favorite) VALUES(?,?,?) ON CONFLICT(user_id,exercise_id) DO UPDATE SET favorite=excluded.favorite",
                (self.user_id, exercise_id, int(enabled)),
            )

    def create_equipment(
        self,
        label: str,
        equipment_type: str,
        configuration=None,
        *,
        equipment_id=None,
        event_id=None,
    ) -> dict:
        if not label.strip() or not equipment_type.strip():
            raise TrainingError("器械标签和类型必填")
        event_id = event_id or str(uuid4())
        identity = equipment_id or _uuid(event_id, "equipment")
        config = configuration or {}
        if config.get("load_step") is not None:
            if numeric(config["load_step"], "load_step") == 0:
                raise TrainingError("器械步长必须大于0")
            if config.get("step_basis") not in LOAD_BASES or not config.get("step_source"):
                raise TrainingError("器械步长须记录口径和用户确认/厂家来源")
        if config.get("available_loads") is not None:
            if not isinstance(config["available_loads"], list):
                raise TrainingError("可用负荷档位须为列表")
            for value in config["available_loads"]:
                numeric(value, "available_loads")
            if not config.get("step_source") or config.get("step_basis") not in LOAD_BASES:
                raise TrainingError("可用档位须记录物理口径和确认来源")

        def apply(old, eid, now):
            self.conn.execute(
                "INSERT INTO equipment_instance(id,user_id,label,equipment_type,configuration_json,revision,created_at) VALUES(?,?,?,?,?,1,?)",
                (identity, self.user_id, label.strip(), equipment_type, json_text(config), now),
            )
            return self.get_equipment(identity)

        return self._mutate(
            "create_equipment",
            "equipment",
            identity,
            {"label": label, "equipment_type": equipment_type, "configuration": config},
            apply,
            event_id=event_id,
            invalidates=False,
        )

    def get_equipment(self, equipment_id: str) -> dict:
        item = _decode(
            self.conn.execute(
                "SELECT * FROM equipment_instance WHERE id=? AND user_id=?",
                (equipment_id, self.user_id),
            ).fetchone()
        )
        if not item:
            raise TrainingError("找不到此器械实例")
        return item

    def list_equipment(self) -> list[dict]:
        return [
            _decode(r)
            for r in self.conn.execute(
                "SELECT * FROM equipment_instance WHERE user_id=? ORDER BY label", (self.user_id,)
            )
        ]

    def _condition(self, exercise_id: str, condition: dict, version=None) -> dict:
        exercise = self.get_exercise(exercise_id, version)
        if condition.get("equipment_instance_id"):
            equipment = self.get_equipment(condition["equipment_instance_id"])
            if equipment["equipment_type"] != exercise["equipment_type"]:
                raise TrainingError("器械实例与所选动作器械类型不一致")
        return condition_snapshot(exercise, condition, self.user_id)

    def _items(self, items: list[dict]) -> list[dict]:
        if not isinstance(items, list):
            raise TrainingError("模板动作必须是列表")
        result = []
        for item in items:
            exercise = self.get_exercise(item["exercise_id"], item.get("definition_version"))
            condition = self._condition(
                item["exercise_id"], item.get("condition") or {}, item.get("definition_version")
            )
            targets = self._targets(item.get("targets") or {})
            result.append(
                {
                    "exercise_id": item["exercise_id"],
                    "definition_version": exercise["definition_version"],
                    "condition": condition,
                    "targets": targets,
                }
            )
        return result

    def _targets(self, targets: dict) -> dict:
        result = json.loads(json_text(targets))
        for entry in result.get("sets", []):
            if entry.get("set_type", "work") not in SET_TYPES:
                raise TrainingError("目标组类型无效")
            for key in (
                "reps_min",
                "reps_max",
                "rir",
                "rest_seconds",
                "load_value",
                "duration_s",
                "distance_m",
            ):
                if key in entry:
                    entry[key] = numeric(entry[key], key, integer=key.startswith("reps"))
            if (
                entry.get("reps_min") is not None
                and entry.get("reps_max") is not None
                and entry["reps_min"] > entry["reps_max"]
            ):
                raise TrainingError("目标次数下限不能超过上限")
        return result

    def create_template(
        self, name: str, items: list[dict], *, template_id=None, event_id=None
    ) -> dict:
        if not name.strip():
            raise TrainingError("模板名称不能为空")
        normalized = self._items(items)
        event_id = event_id or str(uuid4())
        identity = template_id or _uuid(event_id, "template")

        def apply(current, eid, now):
            self.conn.execute(
                "INSERT INTO training_template(id,user_id,name,current_version,created_at) VALUES(?,?,?,1,?)",
                (identity, self.user_id, name.strip(), now),
            )
            self.conn.execute(
                "INSERT INTO training_template_version(template_id,version,name,items_json,created_at) VALUES(?,1,?,?,?)",
                (identity, name.strip(), json_text(normalized), now),
            )
            return self.get_template(identity)

        return self._mutate(
            "create_template",
            "template",
            identity,
            {"name": name, "items": normalized},
            apply,
            event_id=event_id,
        )

    def get_template(self, template_id: str, version=None) -> dict:
        item = self.conn.execute(
            "SELECT * FROM training_template WHERE id=? AND user_id=?", (template_id, self.user_id)
        ).fetchone()
        if item is None:
            raise TrainingError("找不到此模板")
        rev = self.conn.execute(
            "SELECT * FROM training_template_version WHERE template_id=? AND version=?",
            (template_id, version or item["current_version"]),
        ).fetchone()
        if rev is None:
            raise TrainingError("找不到此模板版本")
        return {**dict(item), **_decode(rev), "id": template_id, "revision": rev["version"]}

    def list_templates(self) -> list[dict]:
        return [
            self.get_template(r["id"])
            for r in self.conn.execute(
                "SELECT id FROM training_template WHERE user_id=? AND deleted_at IS NULL ORDER BY name",
                (self.user_id,),
            )
        ]

    def update_template(
        self, template_id: str, name: str, items: list[dict], *, base_revision: int, event_id=None
    ) -> dict:
        if not name.strip():
            raise TrainingError("模板名称不能为空")
        normalized = self._items(items)

        def apply(current, eid, now):
            version = current["revision"] + 1
            self.conn.execute(
                "INSERT INTO training_template_version(template_id,version,name,items_json,created_at) VALUES(?,?,?,?,?)",
                (template_id, version, name, json_text(normalized), now),
            )
            self.conn.execute(
                "UPDATE training_template SET name=?,current_version=? WHERE id=?",
                (name, version, template_id),
            )
            return self.get_template(template_id)

        return self._mutate(
            "update_template",
            "template",
            template_id,
            {"name": name, "items": normalized},
            apply,
            event_id=event_id,
            base_revision=base_revision,
            before=lambda: self.get_template(template_id),
        )

    def copy_template(self, template_id: str, name: str, *, event_id=None) -> dict:
        source = self.get_template(template_id)
        return self.create_template(name, source["items"], event_id=event_id)

    def _session(self, session_id) -> dict:
        row = self.conn.execute(
            "SELECT * FROM strength_session WHERE (session_uuid=? OR id=?) AND user_id=?",
            (str(session_id), session_id, self.user_id),
        ).fetchone()
        if row is None:
            raise TrainingError("找不到此训练会话")
        return _decode(row)

    def start_session(
        self,
        name: str = "",
        *,
        template_id=None,
        started_at=None,
        session_id=None,
        event_id=None,
        template_version=None,
        populate_template=True,
        client_plan_slots=None,
    ) -> dict:
        event_id = event_id or str(uuid4())
        identity = session_id or _uuid(event_id, "session")
        started = timestamp(started_at)
        template = self.get_template(template_id, template_version) if template_id else None
        if client_plan_slots is not None:
            expected = [
                (item["exercise_id"], target)
                for item in (template or {}).get("items", [])
                for target in item.get("targets", {}).get("sets", [])
            ]
            if (
                populate_template
                or not isinstance(client_plan_slots, list)
                or len(client_plan_slots) != len(expected)
            ):
                raise TrainingError("离线计划槽必须与冻结模板逐组对应，不能重复自动生成")
            identities = set()
            for slot, (exercise_id, target) in zip(client_plan_slots, expected):
                if (
                    not slot.get("set_uuid")
                    or not slot.get("session_exercise_id")
                    or slot.get("exercise_id") != exercise_id
                    or slot.get("targets") != target
                    or slot["set_uuid"] in identities
                ):
                    raise TrainingError("离线计划槽身份、顺序或目标与模板不一致")
                identities.add(slot["set_uuid"])
            template = {**template, "client_plan_slots": client_plan_slots} if template else None
        # Hash caller input, not the generated current time, to permit retries.
        payload = {
            "name": name,
            "template_id": template_id,
            "template_version": template_version,
            "populate_template": populate_template,
            "client_plan_slots": client_plan_slots,
            "started_at": started_at,
            "session_id": identity,
        }

        def apply(current, eid, now):
            title = name or (template["name"] if template else "临时训练")
            cursor = self.conn.execute(
                "INSERT INTO strength_session(fingerprint,session_date,started_at,name,source,notes,session_uuid,user_id,revision,session_status,template_id,template_version,plan_snapshot_json,recorded_at,available_at) VALUES(?,?,?,?,?,?,?,?,1,'in_progress',?,?,?,?,?)",
                (
                    "v13:" + str(identity),
                    started[:10],
                    started,
                    title,
                    "manual_v13",
                    "",
                    str(identity),
                    self.user_id,
                    template_id,
                    template["version"] if template else None,
                    json_text(template) if template else None,
                    now,
                    now,
                ),
            )
            sid = cursor.lastrowid
            for position, item in enumerate(
                template["items"] if template and populate_template else []
            ):
                instance_id = _uuid(eid, f"exercise:{position}")
                self._insert_exercise(
                    sid,
                    instance_id,
                    item["exercise_id"],
                    item["condition"],
                    item["targets"],
                    position,
                    item["definition_version"],
                )
                for number, target in enumerate(item["targets"].get("sets", [])):
                    self._insert_set(
                        instance_id, _uuid(eid, f"set:{position}:{number}"), {}, target, now
                    )
            return self.get_session(sid)

        return self._mutate(
            "start_session",
            "session",
            str(identity),
            payload,
            apply,
            event_id=event_id,
            occurred_at=started_at,
        )

    def _insert_exercise(
        self,
        session_id: int,
        identity: str,
        exercise_id: str,
        condition: dict,
        targets: dict,
        position: int,
        version=None,
        replaced_from=None,
        reason=None,
    ):
        snapshot = self._condition(exercise_id, condition, version)
        self.conn.execute(
            "INSERT INTO training_session_exercise(id,session_id,user_id,position,catalog_id,definition_version,condition_json,condition_key,comparability_status,planned_json,replaced_from_exercise_id,replacement_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                identity,
                session_id,
                self.user_id,
                position,
                exercise_id,
                snapshot["definition_version"],
                json_text(snapshot),
                snapshot["condition_key"],
                snapshot["comparability_status"],
                json_text(targets),
                replaced_from,
                reason,
            ),
        )
        self.conn.execute(
            "INSERT INTO exercise_preference(user_id,exercise_id,last_used_at) VALUES(?,?,?) ON CONFLICT(user_id,exercise_id) DO UPDATE SET last_used_at=excluded.last_used_at",
            (self.user_id, exercise_id, timestamp()),
        )

    def add_exercise(
        self,
        session_id,
        exercise_id: str,
        condition: dict,
        targets=None,
        *,
        event_id=None,
        position=None,
        replaced_from_exercise_id=None,
        replacement_reason=None,
        session_exercise_id=None,
        populate_sets=True,
        definition_version=None,
    ) -> dict:
        session = self._session(session_id)
        event_id = event_id or str(uuid4())
        identity = session_exercise_id or _uuid(event_id, "session_exercise")
        snapshot, targets = (
            self._condition(exercise_id, condition, definition_version),
            self._targets(targets or {}),
        )
        payload = {
            "session_id": session["id"],
            "exercise_id": exercise_id,
            "condition": snapshot,
            "targets": targets,
            "position": position,
            "replaced_from_exercise_id": replaced_from_exercise_id,
            "replacement_reason": replacement_reason,
            "populate_sets": populate_sets,
            "definition_version": definition_version,
        }

        def apply(current, eid, now):
            if session.get("deleted_at") or session.get("session_status") not in {
                "draft",
                "in_progress",
                "paused",
            }:
                raise TrainingError("只有进行中的训练可添加动作")
            index = position
            if index is None:
                index = self.conn.execute(
                    "SELECT COALESCE(MAX(position),-1)+1 FROM training_session_exercise WHERE session_id=?",
                    (session["id"],),
                ).fetchone()[0]
            self._insert_exercise(
                session["id"],
                identity,
                exercise_id,
                snapshot,
                targets,
                index,
                version=definition_version,
                replaced_from=replaced_from_exercise_id,
                reason=replacement_reason,
            )
            for number, target in enumerate(targets.get("sets", []) if populate_sets else []):
                self._insert_set(identity, _uuid(eid, f"set:{number}"), {}, target, now)
            return self.get_session_exercise(identity)

        return self._mutate(
            "add_exercise", "session_exercise", identity, payload, apply, event_id=event_id
        )

    def get_session_exercise(self, identity: str) -> dict:
        item = _decode(
            self.conn.execute(
                "SELECT * FROM training_session_exercise WHERE id=? AND user_id=?",
                (identity, self.user_id),
            ).fetchone()
        )
        if item is None:
            raise TrainingError("找不到此训练动作")
        item["exercise"] = self.get_exercise(item["catalog_id"], item["definition_version"])
        item["sets"] = [
            _decode(r)
            for r in self.conn.execute(
                "SELECT * FROM strength_set WHERE session_exercise_id=? AND user_id=? ORDER BY set_number,id",
                (identity, self.user_id),
            )
        ]
        return item

    def get_session(self, session_id) -> dict:
        item = self._session(session_id)
        item["exercises"] = [
            self.get_session_exercise(r["id"])
            for r in self.conn.execute(
                "SELECT id FROM training_session_exercise WHERE session_id=? AND user_id=? ORDER BY position,id",
                (item["id"], self.user_id),
            )
        ]
        item["sets"] = [
            _decode(r)
            for r in self.conn.execute(
                "SELECT * FROM strength_set WHERE session_id=? AND user_id=? ORDER BY set_number,id",
                (item["id"], self.user_id),
            )
        ]
        item["completed_sets"] = (
            0
            if item.get("deleted_at")
            else sum(
                r.get("completion_state") == "completed" and not r.get("deleted_at")
                for r in item["sets"]
            )
        )
        item["rest_timer"] = self.timer_status(item["id"])
        return item

    def list_sessions(self, *, include_deleted=False, active_only=False) -> list[dict]:
        sql, args = "SELECT * FROM strength_session WHERE user_id=?", [self.user_id]
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        if active_only:
            sql += " AND session_status IN ('draft','in_progress','paused')"
        return [
            _decode(r) for r in self.conn.execute(sql + " ORDER BY session_date DESC,id DESC", args)
        ]

    def legacy_records(self, *, include_deleted=False) -> list[dict]:
        """Raw legacy observations for display and explicit analytical exclusions.

        This is a current inventory, not an as-of reconstruction. Callers must
        not infer availability, execution status, or measurement conditions.
        """
        sql = "SELECT * FROM strength_set WHERE user_id=? AND set_uuid IS NULL"
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        return [_decode(row) for row in self.conn.execute(sql + " ORDER BY id", (self.user_id,))]

    def edit_legacy_set(self, set_id, changes: dict, *, base_revision: int, event_id=None):
        """Correct explicitly supplied raw fields without inventing v1.3 meaning."""
        allowed = {
            "exercise_name",
            "equipment",
            "variation",
            "side",
            "range_of_motion",
            "weight_kg",
            "reps",
            "rir",
            "rpe",
            "set_number",
            "notes",
            "warmup",
        }
        if set(changes) - allowed:
            raise TrainingError("旧记录只支持原始字段更正；动作口径与完成状态保持未知")
        original = self.get_set(set_id)
        if original.get("set_uuid"):
            raise TrainingError("v1.3 记录请使用逐组更正")
        checked = dict(changes)
        if "exercise_name" in checked and not str(checked["exercise_name"] or "").strip():
            raise TrainingError("原始动作名称不能为空")
        for key in ("exercise_name", "equipment", "variation", "side", "range_of_motion", "notes"):
            if key in checked:
                checked[key] = str(checked[key] or "")
        for key in ("weight_kg", "reps", "rir", "rpe", "set_number"):
            if key in checked:
                checked[key] = numeric(checked[key], key, integer=key in {"reps", "set_number"})
        if "warmup" in checked and checked["warmup"] not in {True, False, None}:
            raise TrainingError("热身字段只能是真/假或未知")

        def apply(old, eid, now):
            if old.get("deleted_at"):
                raise TrainingError("请先撤销删除，再编辑此组")
            fields = {**checked, "revision": old["revision"] + 1, "available_at": now}
            if "weight_kg" in checked:
                fields["legacy_raw_value"] = (
                    None if checked["weight_kg"] is None else str(checked["weight_kg"])
                )
            self.conn.execute(
                "UPDATE strength_set SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                (*fields.values(), old["id"]),
            )
            return self.get_set(old["id"])

        return self._mutate(
            "edit_legacy_set",
            "set",
            str(original["id"]),
            changes,
            apply,
            event_id=event_id,
            base_revision=base_revision,
            before=lambda: self.get_set(original["id"]),
        )

    def _actual(self, actual: dict, condition: dict, planned=None) -> dict:
        allowed = {
            "completion_state",
            "set_type",
            "load_value",
            "load_unit",
            "reps",
            "rir",
            "rpe",
            "rir_qualifier",
            "rpe_scale",
            "duration_s",
            "distance_m",
            "body_mass_kg",
            "added_load_kg",
            "assistance_value",
            "stop_reason",
            "started_at",
            "ended_at",
            "pain_flag",
            "quality_note",
            "quality_status",
            "notes",
            "source_method",
            "source_record_id",
            "relation_kind",
            "relation_group_id",
            "parent_set_uuid",
            "reference_set",
            "set_number",
            "rest_recorded_s",
            "rest_recorded_method",
        }
        if set(actual) - allowed:
            raise TrainingError("未识别的实际记录字段: " + ",".join(sorted(set(actual) - allowed)))
        result = dict(actual)
        result["completion_state"] = result.get("completion_state", "draft")
        result["set_type"] = result.get("set_type", (planned or {}).get("set_type", "work"))
        if result["completion_state"] not in SET_STATES or result["set_type"] not in SET_TYPES:
            raise TrainingError("组状态或组类型无效")
        for field in (
            "reps",
            "rir",
            "rpe",
            "duration_s",
            "distance_m",
            "body_mass_kg",
            "added_load_kg",
            "assistance_value",
            "set_number",
            "rest_recorded_s",
        ):
            if field in result:
                result[field] = numeric(
                    result[field], field, integer=field in {"reps", "set_number"}
                )
        if result.get("set_number") is not None and result["set_number"] < 1:
            raise TrainingError("组序号必须大于0")
        if result.get("rir_qualifier") not in {None, "exact", "at_least"}:
            raise TrainingError("RIR 限定词必须是 exact/at_least")
        if result.get("rpe") is not None:
            scale = SCALES.get(result.get("rpe_scale"))
            if scale is None or not scale[0] <= result["rpe"] <= scale[1]:
                raise TrainingError("RPE 必须声明有效量表且在该量表范围内")
        if result.get("stop_reason") not in STOP_REASONS | {None}:
            raise TrainingError("停止原因无效")
        if result.get("quality_status") not in {None, "acceptable", "technique_limited", "unknown"}:
            raise TrainingError("动作质量须明确 acceptable/technique_limited/unknown")
        if result.get("rest_recorded_method") is not None and not isinstance(
            result["rest_recorded_method"], str
        ):
            raise TrainingError("主动记录休息的方法应为文字或未知")
        if result.get("pain_flag") not in {None, True, False}:
            raise TrainingError("疼痛标记必须是真/假或未知")
        for field in ("started_at", "ended_at"):
            if result.get(field):
                result[field] = timestamp(result[field])
        if (
            result.get("started_at")
            and result.get("ended_at")
            and datetime.fromisoformat(result["ended_at"])
            < datetime.fromisoformat(result["started_at"])
        ):
            raise TrainingError("组结束时间早于开始时间")
        if result.get("relation_kind") not in {None, "drop", "superset"}:
            raise TrainingError("组关系必须是 drop/superset")
        if result.get("relation_kind") and not result.get("relation_group_id"):
            raise TrainingError("递减/超级组必须记录关联组标识")
        if result["completion_state"] == "completed":
            field = {"repetitions": "reps", "duration": "duration_s", "distance": "distance_m"}[
                condition["measurement_mode"]
            ]
            if result.get(field) is None or result[field] <= 0:
                raise TrainingError(f"完成组的 {field} 必须大于0；零次失败请标记 aborted")
        semantics = load_semantics(
            result.get("load_value"),
            result.get("load_unit"),
            condition.get("load_basis"),
            **{k: v for k, v in condition.items() if k != "load_basis"},
        )
        result["load_value"] = semantics["raw_value"]
        result["weight_kg"] = semantics["normalized_recorded_kg"]
        # A draft's suggestions remain visibly present, but legacy aggregate
        # queries must not see an executed weight/repetition before completion.
        if result["completion_state"] in {"draft", "in_progress", "skipped"}:
            result["weight_kg"] = None
        return result

    def _insert_set(
        self, session_exercise_id: str, identity: str, actual: dict, planned: dict, now: str
    ) -> dict:
        exercise = self.get_session_exercise(session_exercise_id)
        session = self._session(exercise["session_id"])
        condition = exercise["condition"]
        fields = self._actual(actual, condition, planned)
        if fields.get("reference_set"):
            if fields["completion_state"] not in {"draft", "in_progress"}:
                raise TrainingError("参考组必须在完成或失败之前预先指定")
            fields["reference_declared_at"] = now
        if (
            fields["completion_state"] in {"completed", "aborted"}
            and not fields.get("ended_at")
            and "ended_at" not in actual
        ):
            fields["ended_at"] = now
        number = fields.pop("set_number", None)
        if number is None:
            number = self.conn.execute(
                "SELECT COALESCE(MAX(set_number),0)+1 FROM strength_set WHERE session_exercise_id=?",
                (session_exercise_id,),
            ).fetchone()[0]
        values = {
            "fingerprint": "v13:" + identity,
            "session_id": session["id"],
            "set_date": session["session_date"],
            "exercise_id": exercise["catalog_id"],
            "exercise_name": exercise["exercise"]["name_zh"],
            "equipment": exercise["exercise"]["equipment_type"],
            "variation": condition.get("variant_id"),
            "side": condition.get("side"),
            "set_number": number,
            "warmup": int(fields["set_type"] == "warmup"),
            "range_of_motion": condition.get("rom_protocol"),
            "set_uuid": identity,
            "user_id": self.user_id,
            "revision": 1,
            "catalog_id": exercise["catalog_id"],
            "definition_version": exercise["definition_version"],
            "catalog_mapping_status": "user_confirmed",
            "session_exercise_id": session_exercise_id,
            "condition_json": json_text(condition),
            "condition_key": condition["condition_key"],
            "comparability_status": condition["comparability_status"],
            "planned_json": json_text(planned),
            "load_basis": condition["load_basis"],
            "repetition_semantics": condition.get("repetition_semantics"),
            "recorded_at": now,
            "available_at": now,
            "source_method": "manual",
            **fields,
        }
        columns = list(values)
        self.conn.execute(
            f"INSERT INTO strength_set({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
            tuple(values.values()),
        )
        return self.get_set(identity)

    def add_set(
        self,
        session_exercise_id: str,
        actual=None,
        planned=None,
        *,
        event_id=None,
        set_id=None,
        allow_completed_session=False,
    ) -> dict:
        event_id = event_id or str(uuid4())
        identity = set_id or _uuid(event_id, "set")
        exercise = self.get_session_exercise(session_exercise_id)
        session = self._session(exercise["session_id"])
        payload = {
            "session_exercise_id": session_exercise_id,
            "actual": actual or {},
            "planned": planned or {},
            "allow_completed_session": allow_completed_session,
        }

        def apply(old, eid, now):
            allowed_states = {"draft", "in_progress", "paused"}
            if allow_completed_session:
                allowed_states |= {"completed", "aborted"}
            if session.get("deleted_at") or session.get("session_status") not in allowed_states:
                raise TrainingError("训练结束后请通过历史修订记录变更")
            if exercise.get("replaced_by_instance_id"):
                raise TrainingError("此动作已替换，请记录到新动作")
            return self._insert_set(
                session_exercise_id, str(identity), actual or {}, planned or {}, now
            )

        return self._mutate(
            "add_set",
            "set",
            str(identity),
            payload,
            apply,
            event_id=event_id,
            occurred_at=(actual or {}).get("ended_at") or (actual or {}).get("started_at"),
        )

    def get_set(self, set_id) -> dict:
        row = self.conn.execute(
            "SELECT * FROM strength_set WHERE (set_uuid=? OR id=?) AND user_id=?",
            (str(set_id), set_id, self.user_id),
        ).fetchone()
        if row is None:
            raise TrainingError("找不到此训练组")
        return _decode(row)

    def edit_set(self, set_id, changes: dict, *, base_revision: int, event_id=None) -> dict:
        original = self.get_set(set_id)
        identity = original["set_uuid"] or str(original["id"])
        allowed = {
            "completion_state",
            "set_type",
            "load_value",
            "load_unit",
            "reps",
            "rir",
            "rpe",
            "rir_qualifier",
            "rpe_scale",
            "duration_s",
            "distance_m",
            "body_mass_kg",
            "added_load_kg",
            "assistance_value",
            "stop_reason",
            "started_at",
            "ended_at",
            "pain_flag",
            "quality_note",
            "quality_status",
            "notes",
            "source_method",
            "source_record_id",
            "relation_kind",
            "relation_group_id",
            "parent_set_uuid",
            "reference_set",
            "set_number",
            "rest_recorded_s",
            "rest_recorded_method",
        }
        if set(changes) - allowed:
            raise TrainingError("组条件不能通过数值编辑改变；替换动作需另建条件快照")

        def apply(old, eid, now):
            if old.get("deleted_at"):
                raise TrainingError("请先撤销删除，再编辑此组")
            condition = old.get("condition")
            if condition is None:
                raise TrainingError("旧记录口径未知，请先显式关联并确认动作条件")
            actual = {k: old.get(k) for k in allowed if old.get(k) is not None}
            actual.update(changes)
            checked = self._actual(actual, condition, old.get("planned"))
            if checked.get("reference_set") and not old.get("reference_set"):
                if old.get("completion_state") not in {"draft", "in_progress"} or checked[
                    "completion_state"
                ] not in {"draft", "in_progress"}:
                    raise TrainingError("参考组必须在完成或失败之前预先指定")
                checked["reference_declared_at"] = now
            if (
                checked["completion_state"] in {"completed", "aborted"}
                and not checked.get("ended_at")
                and "ended_at" not in changes
                and old.get("completion_state") not in {"completed", "aborted"}
            ):
                checked["ended_at"] = now
            checked.update(
                revision=old["revision"] + 1,
                available_at=now,
                warmup=int(checked["set_type"] == "warmup"),
            )
            self.conn.execute(
                "UPDATE strength_set SET " + ",".join(f"{k}=?" for k in checked) + " WHERE id=?",
                (*checked.values(), old["id"]),
            )
            return self.get_set(old["id"])

        return self._mutate(
            "edit_set",
            "set",
            identity,
            changes,
            apply,
            event_id=event_id,
            base_revision=base_revision,
            before=lambda: self.get_set(identity),
            occurred_at=changes.get("ended_at") or changes.get("started_at"),
        )

    def _rederive_session_rest(self, session_id, source_event_id, now, edited_id):
        """Recompute dependent endpoints and audit each affected neighbour.

        Missing endpoints never become timer targets or user-entered rest. A
        previous unfinished/overlapping execution prevents using an older end.
        """
        rows = [
            self.get_set(row["id"])
            for row in self.conn.execute(
                "SELECT id FROM strength_set WHERE session_id=? AND user_id=? AND set_uuid IS NOT NULL",
                (session_id, self.user_id),
            )
        ]
        executed = [
            row
            for row in rows
            if not row.get("deleted_at")
            and row.get("completion_state") in {"in_progress", "completed", "aborted"}
        ]
        unlocated = [
            row for row in executed if not row.get("started_at") and not row.get("ended_at")
        ]
        for row in rows:
            seconds = None
            provenance = {
                "algorithm_version": "adjacent_endpoints_v2",
                "previous_set_uuid": None,
                "previous_ended_at": None,
                "current_started_at": row.get("started_at"),
                "reason": "missing_current_start",
            }
            if row.get("deleted_at") or row.get("completion_state") not in {
                "in_progress",
                "completed",
                "aborted",
            }:
                if row.get("rest_actual_s") is None and row.get("rest_derivation") is None:
                    continue
                provenance["reason"] = "not_executed"
            elif row.get("started_at"):
                start = datetime.fromisoformat(row["started_at"])
                prior = [
                    other
                    for other in executed
                    if other["id"] != row["id"]
                    and (other.get("started_at") or other.get("ended_at"))
                    and datetime.fromisoformat(other.get("started_at") or other["ended_at"]) < start
                ]
                predecessor = (
                    max(
                        prior,
                        key=lambda other: datetime.fromisoformat(
                            other.get("started_at") or other["ended_at"]
                        ),
                    )
                    if prior
                    else None
                )
                if any(other["id"] != row["id"] for other in unlocated):
                    provenance["reason"] = "unlocated_other_execution"
                elif predecessor is None:
                    provenance["reason"] = "previous_endpoint_unknown"
                else:
                    provenance.update(
                        previous_set_uuid=predecessor["set_uuid"],
                        previous_ended_at=predecessor.get("ended_at"),
                    )
                    if not predecessor.get("ended_at"):
                        provenance["reason"] = "missing_previous_end"
                    else:
                        difference = (
                            start - datetime.fromisoformat(predecessor["ended_at"])
                        ).total_seconds()
                        if difference < 0:
                            provenance["reason"] = "overlapping_endpoints"
                        else:
                            seconds = difference
                            provenance["reason"] = "derived_from_adjacent_endpoints"
            if row.get("rest_actual_s") == seconds and row.get("rest_derivation") == provenance:
                continue
            fields = {"rest_actual_s": seconds, "rest_derivation_json": json_text(provenance)}
            if row["id"] == edited_id:
                self.conn.execute(
                    "UPDATE strength_set SET rest_actual_s=?,rest_derivation_json=? WHERE id=?",
                    (seconds, json_text(provenance), edited_id),
                )
                continue

            def apply(old, eid, recorded, fields=fields, identity=row["id"]):
                self.conn.execute(
                    "UPDATE strength_set SET rest_actual_s=?,rest_derivation_json=?,revision=revision+1,available_at=? WHERE id=?",
                    (fields["rest_actual_s"], fields["rest_derivation_json"], recorded, identity),
                )
                return self.get_set(identity)

            self._mutate(
                "derive_rest",
                "set",
                row["set_uuid"],
                {"source_event_id": source_event_id, **fields},
                apply,
                event_id=_uuid(source_event_id, "rest:" + row["set_uuid"]),
                base_revision=row["revision"],
                before=lambda identity=row["id"]: self.get_set(identity),
            )

    def delete_set(self, set_id, *, base_revision: int, event_id=None) -> dict:
        original = self.get_set(set_id)
        identity = original["set_uuid"] or str(original["id"])

        def apply(old, eid, now):
            self.conn.execute(
                "UPDATE strength_set SET deleted_at=?,revision=revision+1,available_at=? WHERE id=?",
                (now, now, old["id"]),
            )
            return self.get_set(old["id"])

        return self._mutate(
            "delete_set",
            "set",
            identity,
            {},
            apply,
            event_id=event_id,
            base_revision=base_revision,
            before=lambda: self.get_set(identity),
        )

    def undo_event(self, original_event_id: str, *, base_revision: int, event_id=None) -> dict:
        event = self.conn.execute(
            "SELECT * FROM training_event WHERE event_id=? AND user_id=? AND status='applied'",
            (original_event_id, self.user_id),
        ).fetchone()
        if event is None or event["entity_type"] not in {"set", "session"}:
            raise TrainingError("此事件不可撤销")
        before = json.loads(event["before_json"]) if event["before_json"] else None
        kind, identity = event["entity_type"], event["entity_id"]
        fetch = self.get_set if kind == "set" else self._session
        table = "strength_set" if kind == "set" else "strength_session"

        def apply(current, eid, now):
            if before is None:
                changes = {"deleted_at": now}
            else:
                columns = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                changes = {
                    k: v
                    for k, v in before.items()
                    if k in columns and k not in {"id", "revision", "available_at"}
                }
            changes.update(revision=current["revision"] + 1, available_at=now)
            self.conn.execute(
                f"UPDATE {table} SET " + ",".join(f"{k}=?" for k in changes) + " WHERE id=?",
                (*changes.values(), current["id"]),
            )
            return fetch(identity)

        return self._mutate(
            "undo_event",
            kind,
            identity,
            {"original_event_id": original_event_id},
            apply,
            event_id=event_id,
            base_revision=base_revision,
            before=lambda: fetch(identity),
        )

    def last_values(self, session_exercise_id: str, *, cutoff_time=None) -> dict:
        instance = self.get_session_exercise(session_exercise_id)
        condition_key = instance.get("condition_key")
        if condition_key is None:
            return {
                "status": "incompatible",
                "reason": "comparability_unknown",
                "missing": instance["condition"]["missing_comparability_fields"],
                "suggested_actual": {},
                "completion_state": "draft",
            }
        cutoff = timestamp(cutoff_time)
        rows = self.history_as_of(cutoff_time=cutoff, condition_key=condition_key)
        eligible = [
            row
            for row in reversed(rows)
            if row["session_id"] != instance["session_id"] and not row.get("conflicted")
        ]
        if not eligible:
            return {
                "status": "insufficient",
                "reason": "no_comparable_history_available_before_cutoff",
                "suggested_actual": {},
                "completion_state": "draft",
            }
        row = eligible[0]
        suggested = {
            k: row[k]
            for k in ("load_value", "load_unit", "reps", "duration_s", "distance_m")
            if row[k] is not None
        }
        return {
            "status": "available",
            "source_set_id": row["set_uuid"] or row["id"],
            "source_event_time": row["ended_at"] or row["started_at"],
            "source_available_at": row["available_at"],
            "suggested_actual": {**suggested, "completion_state": "draft"},
            "completion_state": "draft",
            "limitations": ["历史完成值只是待确认草稿，不保证今天可完成；RIR和停止原因重新记录。"],
        }

    def update_session(
        self, session_id, changes: dict, *, base_revision: int, event_id=None
    ) -> dict:
        allowed = {
            "name",
            "notes",
            "session_status",
            "started_at",
            "ended_at",
            "session_rpe",
            "session_rpe_scale",
            "duration_seconds",
            "duration_protocol",
            "feedback",
        }
        if set(changes) - allowed:
            raise TrainingError("未知训练反馈字段")
        identity = self._session(session_id)["session_uuid"] or str(session_id)

        def apply(old, eid, now):
            values = dict(changes)
            if "session_status" in values and values["session_status"] not in SESSION_STATES:
                raise TrainingError("训练状态无效")
            for key in ("started_at", "ended_at"):
                if values.get(key):
                    values[key] = timestamp(values[key])
            if values.get("started_at"):
                values["session_date"] = values["started_at"][:10]
            start, end = (
                values.get("started_at", old.get("started_at")),
                values.get("ended_at", old.get("ended_at")),
            )
            if end and start and datetime.fromisoformat(end) < datetime.fromisoformat(start):
                raise TrainingError("训练结束不能早于开始")
            rpe = values.get("session_rpe", old.get("session_rpe"))
            if rpe is not None:
                rpe = numeric(rpe, "session_rpe")
                scale = SCALES.get(values.get("session_rpe_scale", old.get("session_rpe_scale")))
                if not scale or not scale[0] <= rpe <= scale[1]:
                    raise TrainingError("整次训练 RPE 必须独立填报并指定量表")
            if "duration_seconds" in values:
                values["duration_seconds"] = numeric(values["duration_seconds"], "duration_seconds")
                if values["duration_seconds"] is not None and not values.get(
                    "duration_protocol", old.get("duration_protocol")
                ):
                    raise TrainingError("训练时长须明确计算协议")
            if "feedback" in values:
                values["feedback_json"] = json_text(values.pop("feedback"))
            values.update(revision=old["revision"] + 1, available_at=now)
            self.conn.execute(
                "UPDATE strength_session SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?",
                (*values.values(), old["id"]),
            )
            return self.get_session(identity)

        return self._mutate(
            "update_session",
            "session",
            identity,
            changes,
            apply,
            event_id=event_id,
            base_revision=base_revision,
            before=lambda: self._session(identity),
            occurred_at=changes.get("ended_at"),
        )

    def end_session(
        self,
        session_id,
        *,
        feedback=None,
        ended_at=None,
        session_rpe=None,
        rpe_scale=None,
        duration_seconds=None,
        duration_protocol=None,
        base_revision=None,
        event_id=None,
    ) -> dict:
        current = self._session(session_id)
        if event_id:
            prior = self.conn.execute(
                "SELECT * FROM training_event WHERE event_id=?", (event_id,)
            ).fetchone()
            if prior:
                expected = {
                    "session_status": "completed",
                    "feedback": feedback or {},
                    "session_rpe": session_rpe,
                    "session_rpe_scale": rpe_scale,
                    "duration_seconds": duration_seconds,
                    "duration_protocol": duration_protocol,
                }
                payload = json.loads(prior["payload_json"])
                valid = (
                    prior["user_id"] == self.user_id
                    and prior["entity_id"] == (current["session_uuid"] or str(current["id"]))
                    and prior["action"] == "update_session"
                    and all(payload.get(key) == value for key, value in expected.items())
                )
                if ended_at is not None:
                    valid = valid and payload.get("ended_at") == ended_at
                if base_revision is not None:
                    valid = valid and prior["base_revision"] == base_revision
                if not valid:
                    raise TrainingError("event_id 已用于不同的结束训练请求")
                return {**json.loads(prior["result_json"]), "replayed": True}
        changes = {
            "session_status": "completed",
            "ended_at": ended_at or timestamp(),
            "feedback": feedback or {},
            "session_rpe": session_rpe,
            "session_rpe_scale": rpe_scale,
            "duration_seconds": duration_seconds,
            "duration_protocol": duration_protocol,
        }
        return self.update_session(
            session_id,
            changes,
            base_revision=base_revision if base_revision is not None else current["revision"],
            event_id=event_id,
        )

    def delete_session(self, session_id, *, base_revision: int, event_id=None) -> dict:
        current = self._session(session_id)
        identity = current["session_uuid"] or str(current["id"])

        def apply(old, eid, now):
            self.conn.execute(
                "UPDATE strength_session SET deleted_at=?,revision=revision+1,available_at=? WHERE id=?",
                (now, now, old["id"]),
            )
            return self._session(identity)

        return self._mutate(
            "delete_session",
            "session",
            identity,
            {},
            apply,
            event_id=event_id,
            base_revision=base_revision,
            before=lambda: self._session(identity),
        )

    def save_session_as_template(self, session_id, name: str, *, event_id=None) -> dict:
        session = self.get_session(session_id)
        items = [
            {
                "exercise_id": x["catalog_id"],
                "condition": x["condition"],
                "targets": self.current_targets(x["id"])["targets"],
            }
            for x in session["exercises"]
            if not x.get("deleted_at") and not x.get("replaced_by_instance_id")
        ]
        # Actual reps, failures, and RIR are deliberately not copied to targets.
        return self.create_template(name, items, event_id=event_id)

    def current_targets(self, session_exercise_id: str) -> dict:
        """Read explicitly edited targets without rewriting the original plan.

        ``revision`` identifies target content, while each row's ``revision`` is
        its optimistic record revision. Actual performance never fills targets.
        """
        instance = self.get_session_exercise(session_exercise_id)
        rows = [
            {
                "set_uuid": row["set_uuid"],
                "revision": row["revision"],
                "completion_state": row["completion_state"],
                "target": row.get("planned") or {},
            }
            for row in instance["sets"]
            if not row.get("deleted_at")
        ]
        content = [{"set_uuid": row["set_uuid"], "target": row["target"]} for row in rows]
        explicit = [row["target"] for row in rows if row["target"]]
        return {
            "session_exercise_id": session_exercise_id,
            "revision": hashlib.sha256(json_text(content).encode()).hexdigest(),
            "sets": rows,
            "targets": {"sets": explicit} if explicit else {},
            "original_targets": instance.get("planned") or {},
        }

    def reorder_exercises(
        self, session_id, ordered_ids: list[str], *, base_revision: int, event_id=None
    ) -> dict:
        session = self.get_session(session_id)
        original_ids = {x["id"] for x in session["exercises"] if not x.get("deleted_at")}
        if len(ordered_ids) != len(original_ids) or set(ordered_ids) != original_ids:
            raise TrainingError("排序必须恰好包含本会话的全部有效动作")
        identity = session["session_uuid"] or str(session["id"])

        def apply(old, eid, now):
            for position, instance_id in enumerate(ordered_ids):
                self.conn.execute(
                    "UPDATE training_session_exercise SET position=?,revision=revision+1 WHERE id=?",
                    (position, instance_id),
                )
            self.conn.execute(
                "UPDATE strength_session SET revision=revision+1,available_at=? WHERE id=?",
                (now, session["id"]),
            )
            return self.get_session(identity)

        return self._mutate(
            "reorder_exercises",
            "session",
            identity,
            {"ordered_ids": ordered_ids},
            apply,
            event_id=event_id,
            base_revision=base_revision,
            before=lambda: self._session(identity),
        )

    def timer_status(self, session_id, *, as_of=None) -> Optional[dict]:
        session = self._session(session_id)
        item = _decode(
            self.conn.execute(
                "SELECT * FROM training_rest_timer WHERE session_id=? AND user_id=?",
                (session["id"], self.user_id),
            ).fetchone()
        )
        if item is None:
            return None
        now = datetime.fromisoformat(timestamp(as_of))
        end = datetime.fromisoformat(item["paused_at"]) if item["paused_at"] else now
        delta = (end - datetime.fromisoformat(item["anchor_at"])).total_seconds()
        item["clock_anomaly"] = delta < 0
        item["elapsed_seconds"] = None if delta < 0 else item["accumulated_seconds"] + delta
        item["remaining_seconds"] = (
            max(0, item["target_seconds"] - item["elapsed_seconds"])
            if item["target_seconds"] is not None and item["elapsed_seconds"] is not None
            else None
        )
        item["actual_rest_s"] = None
        return item

    def rest_timer(self, session_id, action: str, *, target_seconds=None, at=None) -> dict:
        session = self._session(session_id)
        now = timestamp(at)
        if action not in {"start", "pause", "resume", "extend", "skip"}:
            raise TrainingError("未知计时动作")
        target = numeric(target_seconds, "target_seconds")
        with self._transaction():
            current = self.timer_status(session["id"], as_of=now)
            if action == "start":
                self.conn.execute(
                    "INSERT INTO training_rest_timer(session_id,user_id,anchor_at,target_seconds,state) VALUES(?,?,?,?,'running') ON CONFLICT(session_id) DO UPDATE SET anchor_at=excluded.anchor_at,target_seconds=excluded.target_seconds,paused_at=NULL,accumulated_seconds=0,state='running',revision=revision+1",
                    (session["id"], self.user_id, now, target),
                )
            elif current is None:
                raise TrainingError("尚未开始休息计时")
            elif current["clock_anomaly"]:
                raise TrainingError("系统时间倒退，请重新确认计时起点")
            elif action == "pause":
                if current["state"] == "running":
                    self.conn.execute(
                        "UPDATE training_rest_timer SET paused_at=?,state='paused',revision=revision+1 WHERE session_id=?",
                        (now, session["id"]),
                    )
            elif action == "resume":
                if current["state"] == "paused":
                    self.conn.execute(
                        "UPDATE training_rest_timer SET accumulated_seconds=?,anchor_at=?,paused_at=NULL,state='running',revision=revision+1 WHERE session_id=?",
                        (current["elapsed_seconds"], now, session["id"]),
                    )
            elif action == "extend":
                if target is None:
                    raise TrainingError("延长计时需要明确增加秒数")
                self.conn.execute(
                    "UPDATE training_rest_timer SET target_seconds=?,revision=revision+1 WHERE session_id=?",
                    ((current["target_seconds"] or 0) + target, session["id"]),
                )
            elif action == "skip":
                self.conn.execute(
                    "UPDATE training_rest_timer SET paused_at=?,state='skipped',revision=revision+1 WHERE session_id=?",
                    (now, session["id"]),
                )
            return self.timer_status(session["id"], as_of=now)

    def queue_event(self, operation: str, arguments: dict, *, event_id=None) -> dict:
        """Durably save a local draft event before attempting replay.

        The outbox is a local retry protocol; it does not imply a cloud sync or
        permission to send health records anywhere.
        """
        allowed = {
            "start_session",
            "add_exercise",
            "add_set",
            "edit_set",
            "delete_set",
            "update_session",
            "delete_session",
            "create_template",
            "update_template",
            "undo_event",
        }
        if operation not in allowed:
            raise TrainingError("此操作不能进入离线队列")
        identity = event_id or str(uuid4())
        args = dict(arguments)
        args["event_id"] = identity
        with self._transaction():
            old = self.conn.execute(
                "SELECT * FROM training_outbox WHERE event_id=?", (identity,)
            ).fetchone()
            if old:
                if (
                    old["user_id"] != self.user_id
                    or old["arguments_json"] != json_text(args)
                    or old["operation"] != operation
                ):
                    raise TrainingError("离线 event_id 的请求内容不一致")
                return _decode(old)
            self.conn.execute(
                "INSERT INTO training_outbox(event_id,user_id,operation,arguments_json,status,created_at) VALUES(?,?,?,?,'pending',?)",
                (identity, self.user_id, operation, json_text(args), timestamp()),
            )
        return {"event_id": identity, "status": "pending", "operation": operation}

    def replay_outbox(self) -> list[dict]:
        rows = list(
            self.conn.execute(
                "SELECT * FROM training_outbox WHERE user_id=? AND status IN ('pending','failed','conflicted') ORDER BY created_at,rowid",
                (self.user_id,),
            )
        )
        results = []
        for row in rows:
            if row["status"] == "conflicted":
                conflict = self.conn.execute(
                    "SELECT resolved_by_event_id FROM training_conflict WHERE event_id=? AND user_id=?",
                    (row["event_id"], self.user_id),
                ).fetchone()
                if conflict is None or conflict["resolved_by_event_id"] is None:
                    results.append(
                        {
                            "event_id": row["event_id"],
                            "status": "conflicted",
                            "result": json.loads(row["result_json"]),
                        }
                    )
                    break
                with self._transaction():
                    self.conn.execute(
                        "UPDATE training_outbox SET status='resolved' WHERE event_id=?",
                        (row["event_id"],),
                    )
                continue
            try:
                result = getattr(self, row["operation"])(**json.loads(row["arguments_json"]))
                state = "conflicted" if result.get("status") == "conflicted" else "applied"
                with self._transaction():
                    self.conn.execute(
                        "UPDATE training_outbox SET status=?,attempts=attempts+1,last_error=NULL,result_json=? WHERE event_id=?",
                        (state, json_text(result), row["event_id"]),
                    )
                results.append({"event_id": row["event_id"], "status": state, "result": result})
                if state == "conflicted":
                    break
            except (TrainingError, ValueError, KeyError) as exc:
                with self._transaction():
                    self.conn.execute(
                        "UPDATE training_outbox SET status='failed',attempts=attempts+1,last_error=? WHERE event_id=?",
                        (str(exc), row["event_id"]),
                    )
                results.append({"event_id": row["event_id"], "status": "failed", "error": str(exc)})
                break
        return results

    def list_outbox(self) -> list[dict]:
        return [
            _decode(row)
            for row in self.conn.execute(
                "SELECT * FROM training_outbox WHERE user_id=? ORDER BY created_at", (self.user_id,)
            )
        ]

    def list_conflicts(self, *, unresolved_only=True) -> list[dict]:
        sql = "SELECT * FROM training_conflict WHERE user_id=?"
        if unresolved_only:
            sql += " AND resolved_by_event_id IS NULL"
        return [
            _decode(r) for r in self.conn.execute(sql + " ORDER BY created_at", (self.user_id,))
        ]

    def resolve_conflict(
        self, conflict_id: str, *, choice: str, changes=None, event_id=None
    ) -> dict:
        conflict = _decode(
            self.conn.execute(
                "SELECT * FROM training_conflict WHERE id=? AND user_id=?",
                (conflict_id, self.user_id),
            ).fetchone()
        )
        if conflict is None:
            raise TrainingError("找不到此冲突")
        if conflict.get("resolved_by_event_id"):
            raise TrainingError("此冲突已解决")
        if choice not in {"keep_current", "apply_proposed", "merge_explicit"}:
            raise TrainingError("请明确选择冲突解决方式")
        identity = event_id or str(uuid4())
        with self._transaction():
            if choice == "keep_current":
                result = self._mutate(
                    "resolve_conflict",
                    "conflict",
                    conflict_id,
                    {"choice": choice},
                    lambda old, eid, now: {"resolution": choice},
                    event_id=identity,
                    invalidates=False,
                )
            else:
                if conflict["entity_type"] != "set":
                    raise TrainingError("此实体请按当前版本显式重新提交")
                current = self.get_set(conflict["entity_id"])
                selected = changes if choice == "merge_explicit" else conflict["proposed"]
                if not isinstance(selected, dict):
                    raise TrainingError("显式合并必须给出字段")
                event = self.conn.execute(
                    "SELECT action FROM training_event WHERE event_id=?", (conflict["event_id"],)
                ).fetchone()
                if event and event["action"] == "import_set_revision":
                    from .exchange import _apply_source_revision

                    result = _apply_source_revision(
                        self,
                        conflict["entity_id"],
                        selected,
                        base_revision=current["revision"],
                        event_id=identity,
                    )
                elif event and event["action"] == "delete_set":
                    result = self.delete_set(
                        conflict["entity_id"], base_revision=current["revision"], event_id=identity
                    )
                elif event and event["action"] == "undo_event":
                    result = self.undo_event(
                        selected["original_event_id"],
                        base_revision=current["revision"],
                        event_id=identity,
                    )
                elif event and event["action"] == "update_set_target":
                    result = self.update_set_target(
                        conflict["entity_id"],
                        selected["planned"],
                        base_revision=current["revision"],
                        event_id=identity,
                    )
                else:
                    operation = (
                        self.edit_legacy_set
                        if event and event["action"] == "edit_legacy_set"
                        else self.edit_set
                    )
                    result = operation(
                        conflict["entity_id"],
                        selected,
                        base_revision=current["revision"],
                        event_id=identity,
                    )
            self.conn.execute(
                "UPDATE training_conflict SET resolved_by_event_id=? WHERE id=?",
                (identity, conflict_id),
            )
            return result

    def audit_events(self, entity_id=None) -> list[dict]:
        sql, args = "SELECT * FROM training_event WHERE user_id=?", [self.user_id]
        if entity_id is not None:
            sql += " AND entity_id=?"
            args.append(str(entity_id))
        return [_decode(r) for r in self.conn.execute(sql + " ORDER BY recorded_at,rowid", args)]

    def history_as_of(
        self,
        *,
        cutoff_time: str,
        condition_key=None,
        include_incomplete: bool = False,
        include_deleted: bool = False,
    ) -> list[dict]:
        """Replay only facts and revisions available by the decision cutoff.

        Planned/draft/aborted records remain available when requested for metric
        denominators. Session tombstones hide all child facts until an undo event;
        future corrections, deletion, and conflicts never rewrite prior snapshots.
        """
        cutoff = datetime.fromisoformat(timestamp(cutoff_time))
        state, sessions, conflicts = {}, {}, {}
        resolutions = {}
        for conflict in self.list_conflicts(unresolved_only=False):
            if conflict.get("resolved_by_event_id"):
                resolutions.setdefault(conflict["resolved_by_event_id"], []).append(conflict["id"])
        for event in self.audit_events():
            if datetime.fromisoformat(event["recorded_at"]) > cutoff:
                continue
            row = event.get("after")
            if event["status"] == "conflicted":
                result = event.get("result") or {}
                conflicts[result.get("conflict_id")] = event["entity_id"]
                continue
            if event["status"] != "applied" or not isinstance(row, dict):
                continue
            if event["entity_type"] == "session" and row.get("id"):
                sessions[row["id"]] = row
                for child in row.get("sets", []):
                    if child.get("set_uuid"):
                        state.setdefault(child["set_uuid"], child)
            elif event["entity_type"] == "session_exercise":
                for child in row.get("sets", []):
                    if child.get("set_uuid"):
                        state[child["set_uuid"]] = child
            elif event["entity_type"] == "set" and row.get("set_uuid"):
                state[row["set_uuid"]] = row
                # An independent correction or derived-rest revision does not
                # resolve a saved user conflict. Only its explicit decision can.
                for conflict_id in resolutions.get(event["event_id"], []):
                    conflicts.pop(conflict_id, None)
            elif event["entity_type"] == "conflict" and event["action"] == "resolve_conflict":
                conflicts.pop(event["entity_id"], None)
        conflicting_ids = set(conflicts.values())
        result = []
        for row in state.values():
            session = sessions.get(row["session_id"], {})
            when = row.get("ended_at") or row.get("started_at")
            if not when and include_incomplete:
                when = session.get("started_at")
            if not when or datetime.fromisoformat(when) > cutoff:
                continue
            if not include_incomplete and row.get("completion_state") != "completed":
                continue
            session_deleted = session.get("deleted_at")
            if not include_deleted and (row.get("deleted_at") or session_deleted):
                continue
            if condition_key and row.get("condition_key") != condition_key:
                continue
            result.append(
                {
                    **row,
                    "session_deleted_at": session_deleted,
                    "session_status": session.get("session_status"),
                    "session_started_at": session.get("started_at"),
                    "conflicted": row["set_uuid"] in conflicting_ids,
                }
            )
        return sorted(
            result,
            key=lambda x: (
                x.get("ended_at") or x.get("started_at") or x.get("session_started_at") or "",
                x["set_uuid"],
            ),
        )

    def record_recommendation(
        self,
        candidate: dict,
        input_snapshot: dict,
        *,
        cutoff_time: str,
        theory_version: str,
        data_version=None,
    ) -> dict:
        required = {
            "candidate_id",
            "target_session",
            "action_kind",
            "proposed_change",
            "target_range",
            "reason_evidence_ids",
            "eligibility",
            "uncertainty",
            "verification_protocol",
            "followup_window",
            "rule_version",
            "user_choice",
        }
        missing = required - set(candidate)
        if missing:
            raise TrainingError("候选缺少字段: " + ",".join(sorted(missing)))
        cutoff = timestamp(cutoff_time)
        if not theory_version:
            raise TrainingError("必须记录理论版本或明确 none_reviewed")
        for identity in input_snapshot.get("source_record_ids", []):
            row = self.get_set(identity)
            actual_time = row.get("ended_at") or row.get("started_at")
            if not actual_time or not row.get("available_at"):
                raise TrainingError("来源记录缺少事件时间或可用时间")
            if max(
                datetime.fromisoformat(actual_time), datetime.fromisoformat(row["available_at"])
            ) > datetime.fromisoformat(cutoff):
                raise TrainingError("来源记录在建议截止时间之后发生或才可用")
        frozen = {
            "candidate": candidate,
            "input_snapshot": input_snapshot,
            "cutoff_time": cutoff,
            "theory_version": theory_version,
            "data_version": str(data_version if data_version is not None else self.data_version()),
        }
        identity = str(candidate["candidate_id"])
        with self._transaction():
            old = self.conn.execute(
                "SELECT * FROM training_recommendation WHERE candidate_id=?", (identity,)
            ).fetchone()
            if old:
                if (
                    old["user_id"] != self.user_id
                    or old["candidate_json"] != json_text(candidate)
                    or old["input_snapshot_json"] != json_text(input_snapshot)
                    or old["cutoff_time"] != cutoff
                    or old["theory_version"] != theory_version
                    or (data_version is not None and old["data_version"] != frozen["data_version"])
                ):
                    raise TrainingError("已冻结建议不得重写；请创建新 candidate_id")
                return _decode(old)
            self.conn.execute(
                "INSERT INTO training_recommendation(candidate_id,user_id,target_session,cutoff_time,data_version,theory_version,rule_version,input_snapshot_json,candidate_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    self.user_id,
                    candidate["target_session"],
                    cutoff,
                    frozen["data_version"],
                    theory_version,
                    candidate["rule_version"],
                    json_text(input_snapshot),
                    json_text(candidate),
                    timestamp(),
                ),
            )
            self._invalidate(
                "recommendation:" + identity,
                "recommendation",
                identity,
                timestamp(),
                mark_recommendations_stale=False,
            )
            return _decode(
                self.conn.execute(
                    "SELECT * FROM training_recommendation WHERE candidate_id=?", (identity,)
                ).fetchone()
            )

    def recommendation_feedback(
        self,
        candidate_id: str,
        *,
        user_choice=None,
        execution_state=None,
        nonexecution_reason=None,
        actual_record_ids=None,
        outcome=None,
        occurred_at=None,
        event_id=None,
    ) -> dict:
        candidate = self.conn.execute(
            "SELECT * FROM training_recommendation WHERE candidate_id=? AND user_id=?",
            (candidate_id, self.user_id),
        ).fetchone()
        if candidate is None:
            raise TrainingError("找不到此建议")
        if user_choice not in {None, "accepted", "declined", "modified", "deferred"}:
            raise TrainingError("用户选择无效")
        if execution_state not in {
            None,
            "executed",
            "partially_executed",
            "not_executed",
            "unknown",
        }:
            raise TrainingError("执行状态无效")
        if execution_state == "not_executed" and not nonexecution_reason:
            raise TrainingError("未执行须记录原因或明确 unknown")
        actual_record_ids = actual_record_ids or []
        for identity in actual_record_ids:
            self.get_set(identity)
        event_id = event_id or str(uuid4())
        payload = {
            "candidate_id": candidate_id,
            "user_choice": user_choice,
            "execution_state": execution_state,
            "nonexecution_reason": nonexecution_reason,
            "actual_record_ids": actual_record_ids,
            "outcome": outcome or {},
            "occurred_at": occurred_at,
        }

        def apply(old, eid, now):
            self.conn.execute(
                "INSERT INTO training_recommendation_feedback(event_id,candidate_id,user_id,user_choice,execution_state,nonexecution_reason,actual_record_ids_json,outcome_json,occurred_at,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    eid,
                    candidate_id,
                    self.user_id,
                    user_choice,
                    execution_state,
                    nonexecution_reason,
                    json_text(actual_record_ids),
                    json_text(outcome or {}),
                    timestamp(occurred_at) if occurred_at else now,
                    now,
                ),
            )
            self._invalidate(
                eid,
                "recommendation_feedback",
                candidate_id,
                now,
                mark_recommendations_stale=False,
            )
            return {**payload, "recorded_at": now}

        return self._mutate(
            "recommendation_feedback",
            "recommendation",
            candidate_id,
            payload,
            apply,
            event_id=event_id,
            occurred_at=occurred_at,
            invalidates=False,
        )

    def list_recommendations(self) -> list[dict]:
        rows = [
            _decode(r)
            for r in self.conn.execute(
                "SELECT * FROM training_recommendation WHERE user_id=? ORDER BY created_at DESC",
                (self.user_id,),
            )
        ]
        for row in rows:
            row["feedback"] = [
                _decode(r)
                for r in self.conn.execute(
                    "SELECT * FROM training_recommendation_feedback WHERE candidate_id=? AND user_id=? ORDER BY recorded_at",
                    (row["candidate_id"], self.user_id),
                )
            ]
        return rows

    def mapping_preview(self, from_exercise: str, to_exercise: str) -> dict:
        left, right = self.get_exercise(from_exercise), self.get_exercise(to_exercise)
        keys = {"recording_mode", "equipment_type", "default_load_basis", "definition_version"}
        differences = {
            k: {"from": left.get(k), "to": right.get(k)}
            for k in sorted(keys)
            if left.get(k) != right.get(k)
        }
        count = self.conn.execute(
            "SELECT COUNT(*) FROM strength_set WHERE user_id=? AND catalog_id=?",
            (self.user_id, from_exercise),
        ).fetchone()[0]
        return {
            "from_exercise": from_exercise,
            "to_exercise": to_exercise,
            "differences": differences,
            "affected_records": count,
            "automatic_comparison_merge": False,
            "limitations": ["关联仅保留人工声明；旧记录不改写，条件不同仍不合并趋势。"],
        }

    def declare_mapping(self, from_exercise: str, to_exercise: str, *, confirmed: bool) -> dict:
        preview = self.mapping_preview(from_exercise, to_exercise)
        if not confirmed:
            raise TrainingError("动作关联必须在查看差异后明确确认")
        identity = str(uuid4())
        with self._transaction():
            self.conn.execute(
                "INSERT INTO exercise_mapping(id,user_id,from_exercise,to_exercise,differences_json,confirmed,created_at) VALUES(?,?,?,?,?,1,?)",
                (
                    identity,
                    self.user_id,
                    from_exercise,
                    to_exercise,
                    json_text(preview["differences"]),
                    timestamp(),
                ),
            )
            self._invalidate(identity, "mapping", identity)
        return {"id": identity, **preview}

    def revoke_mapping(self, mapping_id: str):
        with self._transaction():
            result = self.conn.execute(
                "UPDATE exercise_mapping SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL",
                (timestamp(), mapping_id, self.user_id),
            )
            if not result.rowcount:
                raise TrainingError("动作关联不存在或已撤销")
            self._invalidate(str(uuid4()), "mapping", mapping_id)

    def export_session(self, session_id) -> dict:
        from .exchange import export_bundle

        bundle = export_bundle(self.repo, [session_id], user_id=self.user_id)
        session = (bundle["sessions"] or [x["session"] for x in bundle["legacy_sessions"]])[0]
        return {
            **bundle,
            "user_id": self.user_id,
            "session": session,
            "events": bundle["source_events"],
        }

    def start_timer(self, session_id, *, target_seconds=None, at=None) -> dict:
        """Convenience UI entry; timer never fills actual_rest_s."""
        return self.rest_timer(session_id, "start", target_seconds=target_seconds, at=at)

    def sessions_as_of(self, *, cutoff_time: str, include_deleted: bool = False) -> list[dict]:
        """Availability-safe session metadata, including independently recorded sRPE."""
        cutoff = datetime.fromisoformat(timestamp(cutoff_time))
        sessions = {}
        for event in self.audit_events():
            if event["entity_type"] != "session" or event["status"] != "applied":
                continue
            if datetime.fromisoformat(event["recorded_at"]) > cutoff:
                continue
            row = event.get("after")
            if isinstance(row, dict) and row.get("id"):
                sessions[row["id"]] = row
        return [
            row
            for row in sessions.values()
            if row.get("started_at")
            and datetime.fromisoformat(row["started_at"]) <= cutoff
            and (include_deleted or not row.get("deleted_at"))
        ]

    def update_set_target(
        self, set_id, planned: dict, *, base_revision: int, event_id=None
    ) -> dict:
        target = self._targets({"sets": [planned]})["sets"][0]
        original = self.get_set(set_id)
        identity = original["set_uuid"] or str(original["id"])

        def apply(old, eid, now):
            if old.get("completion_state") not in {"draft", "in_progress"}:
                raise TrainingError("已完成或中止组的当时目标不可事后重写")
            self.conn.execute(
                "UPDATE strength_set SET planned_json=?,revision=revision+1,available_at=? WHERE id=?",
                (json_text(target), now, old["id"]),
            )
            return self.get_set(identity)

        return self._mutate(
            "update_set_target",
            "set",
            identity,
            {"planned": target},
            apply,
            event_id=event_id,
            base_revision=base_revision,
            before=lambda: self.get_set(identity),
        )

    def update_condition(
        self, session_exercise_id: str, condition: dict, *, base_revision: int, event_id=None
    ) -> dict:
        instance = self.get_session_exercise(session_exercise_id)
        normalized = self._condition(
            instance["catalog_id"], condition, instance["definition_version"]
        )

        def apply(old, eid, now):
            if any(
                row.get("completion_state") in {"in_progress", "completed", "aborted"}
                for row in old["sets"]
                if not row.get("deleted_at")
            ):
                raise TrainingError("已有执行记录的测量条件不可覆盖；请使用替换动作建立新条件")
            self.conn.execute(
                "UPDATE training_session_exercise SET condition_json=?,condition_key=?,comparability_status=?,revision=revision+1 WHERE id=?",
                (
                    json_text(normalized),
                    normalized["condition_key"],
                    normalized["comparability_status"],
                    session_exercise_id,
                ),
            )
            self.conn.execute(
                "UPDATE strength_set SET condition_json=?,condition_key=?,comparability_status=?,load_basis=?,side=?,range_of_motion=?,repetition_semantics=?,revision=revision+1,available_at=? WHERE session_exercise_id=? AND deleted_at IS NULL",
                (
                    json_text(normalized),
                    normalized["condition_key"],
                    normalized["comparability_status"],
                    normalized["load_basis"],
                    normalized.get("side"),
                    normalized.get("rom_protocol"),
                    normalized.get("repetition_semantics"),
                    now,
                    session_exercise_id,
                ),
            )
            return self.get_session_exercise(session_exercise_id)

        return self._mutate(
            "update_condition",
            "session_exercise",
            session_exercise_id,
            {"condition": normalized},
            apply,
            event_id=event_id,
            base_revision=base_revision,
            before=lambda: self.get_session_exercise(session_exercise_id),
        )

    def replace_exercise(
        self,
        session_exercise_id: str,
        exercise_id: str,
        condition: dict,
        *,
        reason: str,
        targets=None,
        base_revision: int,
        event_id=None,
    ) -> dict:
        if not reason.strip():
            raise TrainingError("请记录替换原因")
        event_id = event_id or str(uuid4())
        identity = _uuid(event_id, "replacement")
        snapshot = self._condition(exercise_id, condition)
        normalized = self._targets(targets or {})

        def apply(old, eid, now):
            if old.get("replaced_by_instance_id"):
                raise TrainingError("此动作已经替换")
            session = self._session(old["session_id"])
            if session.get("session_status") not in {"draft", "in_progress", "paused"}:
                raise TrainingError("已结束训练不能替换动作")
            for row in old["sets"]:
                if row.get("completion_state") in {"draft", "in_progress"} and not row.get(
                    "deleted_at"
                ):
                    self.edit_set(
                        row["id"],
                        {
                            "completion_state": "skipped",
                            "stop_reason": "other",
                            "notes": "替换动作: " + reason,
                        },
                        base_revision=row["revision"],
                        event_id=_uuid(eid, "skip:" + str(row["id"])),
                    )
            self._insert_exercise(
                old["session_id"],
                identity,
                exercise_id,
                snapshot,
                normalized,
                old["position"] + 1,
                replaced_from=old["catalog_id"],
                reason=reason,
            )
            self.conn.execute(
                "UPDATE training_session_exercise SET replaced_by_instance_id=?,replacement_reason=?,revision=revision+1 WHERE id=?",
                (identity, reason, session_exercise_id),
            )
            for index, target in enumerate(normalized.get("sets", [])):
                self._insert_set(identity, _uuid(eid, "draft:" + str(index)), {}, target, now)
            return self.get_session_exercise(identity)

        return self._mutate(
            "replace_exercise",
            "session_exercise",
            session_exercise_id,
            {
                "exercise_id": exercise_id,
                "condition": snapshot,
                "reason": reason,
                "targets": normalized,
            },
            apply,
            event_id=event_id,
            base_revision=base_revision,
            before=lambda: self.get_session_exercise(session_exercise_id),
        )
