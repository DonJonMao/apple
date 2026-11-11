"""Versioned private training exchange, preview, idempotence and source revisions.

JSON preserves the complete canonical snapshots and source audit trail. CSV has
human-editable actual-value columns and explicit JSON columns for condition and
plan snapshots. Legacy CSV follows the original importer, retaining unknown load
semantics rather than guessing from a display name.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .semantics import TrainingError, json_text, timestamp
from .service import TrainingService

ACTUAL_FIELDS = (
    "completion_state",
    "set_type",
    "load_value",
    "load_unit",
    "reps",
    "rir",
    "rir_qualifier",
    "rpe",
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
    "relation_kind",
    "relation_group_id",
    "parent_set_uuid",
    "reference_set",
    "set_number",
)


def _id(*parts):
    return str(uuid5(NAMESPACE_URL, "healthzip-exchange:" + json_text(parts)))


def _payload(row):
    return {
        "actual": {key: row.get(key) for key in ACTUAL_FIELDS},
        "condition": row.get("condition") or json.loads(row.get("condition_json") or "{}"),
        "planned": row.get("planned") or json.loads(row.get("planned_json") or "{}"),
        "deleted_at": row.get("deleted_at"),
    }


def export_bundle(repo, session_ids=None, *, user_id="local") -> dict:
    svc = TrainingService(repo, user_id=user_id)
    chosen = (
        [svc.get_session(identity) for identity in session_ids]
        if session_ids
        else [svc.get_session(x["id"]) for x in svc.list_sessions(include_deleted=True)]
    )
    events = svc.audit_events()
    definitions, equipment = {}, {}
    canonical, legacy = [], []
    for session in chosen:
        if not session.get("session_uuid"):
            legacy.append({"session": session, "sets": session["sets"]})
            continue
        event = next(
            (
                x
                for x in events
                if x["action"] == "start_session" and x["entity_id"] == session["session_uuid"]
            ),
            None,
        )
        original = (event or {}).get("after") or {}
        frozen = original.get("plan_snapshot") or {}
        session["plan_slots"] = frozen.get("client_plan_slots") or [
            {
                "set_uuid": row["set_uuid"],
                "session_exercise_id": row["session_exercise_id"],
                "exercise_id": row["catalog_id"],
                "targets": row.get("planned") or {},
            }
            for row in original.get("sets", [])
        ]
        for instance in session["exercises"]:
            definition = svc.get_exercise(instance["catalog_id"], instance["definition_version"])
            definitions[(definition["exercise_id"], definition["definition_version"])] = definition
            machine = instance["condition"].get("equipment_instance_id")
            if machine:
                equipment[machine] = svc.get_equipment(machine)
        canonical.append(session)
    identities = {str(x["session_uuid"]) for x in canonical}
    identities.update(row["set_uuid"] for s in canonical for row in s["sets"])
    return {
        "schema_version": "1.3.0",
        "format": "healthzip.training.bundle",
        "exported_at": timestamp(),
        "contains_private_training_data": True,
        "exercise_definitions": list(definitions.values()),
        "equipment": list(equipment.values()),
        "sessions": canonical,
        "legacy_sessions": legacy,
        "legacy_unassigned_sets": [
            dict(row)
            for row in svc.conn.execute(
                "SELECT * FROM strength_set WHERE session_id IS NULL AND user_id=?", (svc.user_id,)
            )
        ]
        if not session_ids
        else [],
        "source_events": [x for x in events if x["entity_id"] in identities],
    }


def export_training(repo, path, *, session_ids=None, format=None) -> Path:
    path = Path(path)
    fmt = format or path.suffix.lstrip(".").lower()
    bundle = export_bundle(repo, session_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif fmt == "csv":
        fields = [
            "schema_version",
            "session_json",
            "instance_json",
            "exercise_definition_json",
            "equipment_json",
            "set_uuid",
            "source_revision",
            "planned_json",
            "deleted_at",
            "reference_declared_at",
            *ACTUAL_FIELDS,
        ]
        defs = {
            (x["exercise_id"], x["definition_version"]): x for x in bundle["exercise_definitions"]
        }
        machines = {x["id"]: x for x in bundle["equipment"]}
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for session in bundle["sessions"]:
                meta = {
                    k: v for k, v in session.items() if k not in {"sets", "exercises", "rest_timer"}
                }
                if not session["exercises"]:
                    writer.writerow({"schema_version": "1.3.0", "session_json": json_text(meta)})
                for instance in session["exercises"]:
                    ins = {k: v for k, v in instance.items() if k not in {"sets", "exercise"}}
                    definition = defs[(instance["catalog_id"], instance["definition_version"])]
                    machine = machines.get(instance["condition"].get("equipment_instance_id"))
                    for row in instance["sets"] or [{}]:
                        writer.writerow(
                            {
                                "schema_version": "1.3.0",
                                "session_json": json_text(meta),
                                "instance_json": json_text(ins),
                                "exercise_definition_json": json_text(definition),
                                "equipment_json": json_text(machine),
                                "set_uuid": row.get("set_uuid"),
                                "source_revision": row.get("revision"),
                                "planned_json": json_text(row.get("planned") or {}),
                                "deleted_at": row.get("deleted_at"),
                                "reference_declared_at": row.get("reference_declared_at"),
                                **{key: row.get(key) for key in ACTUAL_FIELDS},
                            }
                        )
        if bundle["legacy_sessions"] or bundle["legacy_unassigned_sets"]:
            # A sidecar retains legacy rows that have no v1.3 instance mapping.
            path.with_suffix(path.suffix + ".legacy.json").write_text(
                json.dumps(
                    {**bundle, "sessions": [], "source_events": []}, ensure_ascii=False, indent=2
                )
                + "\n"
            )
    else:
        raise TrainingError("支持 json 或 csv 导出")
    return path


def _read(path):
    try:
        data = _read_document(path)
        for key in (
            "sessions",
            "equipment",
            "exercise_definitions",
            "legacy_sessions",
            "legacy_unassigned_sets",
            "source_events",
        ):
            values = data.get(key, [])
            if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
                raise TrainingError(f"{key} 必须是对象列表")
        for session in data.get("sessions", []):
            if not session.get("session_uuid") or not isinstance(
                session.get("exercises", []), list
            ):
                raise TrainingError("训练会话缺少 UUID 或动作列表")
            for instance in session.get("exercises", []):
                if not isinstance(instance, dict) or not isinstance(instance.get("sets", []), list):
                    raise TrainingError("训练动作/组列表结构无效")
                if any(
                    not isinstance(row, dict) or not row.get("set_uuid")
                    for row in instance.get("sets", [])
                ):
                    raise TrainingError("训练组缺少稳定 UUID")
        return data
    except (
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
        json.JSONDecodeError,
        csv.Error,
    ) as exc:
        raise TrainingError("训练文件字段或结构无效: " + str(exc)) from exc


def _read_document(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if data.get("schema_version") != "1.3.0":
            raise TrainingError("不支持此训练交换 schema_version")
        if data.get("format") == "healthzip.training.bundle":
            return data
        if "session" in data:  # compatibility with the original v1.3 single-session export
            session = data["session"]
            return {
                "schema_version": "1.3.0",
                "sessions": [session],
                "exercise_definitions": [i["exercise"] for i in session.get("exercises", [])],
                "equipment": data.get("equipment", []),
                "legacy_sessions": [],
                "source_events": data.get("events", []),
            }
        raise TrainingError("不是 HealthZIP 训练交换文件")
    if path.suffix.lower() != ".csv":
        raise TrainingError("请选择 JSON 或 CSV 文件")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "schema_version" not in reader.fieldnames:
            return {"legacy_csv": True, "rows": list(reader), "columns": reader.fieldnames or []}
        sessions, definitions, machines = {}, {}, {}
        for index, record in enumerate(reader, 2):
            if record["schema_version"] != "1.3.0":
                raise TrainingError(f"第{index}行版本不受支持")
            meta = json.loads(record["session_json"])
            session = sessions.setdefault(
                meta["session_uuid"], {**meta, "exercises": [], "sets": []}
            )
            if not record["instance_json"]:
                continue
            instance = json.loads(record["instance_json"])
            definition = json.loads(record["exercise_definition_json"])
            machine = json.loads(record["equipment_json"] or "null")
            definitions[(definition["exercise_id"], definition["definition_version"])] = definition
            if machine:
                machines[machine["id"]] = machine
            current = next((x for x in session["exercises"] if x["id"] == instance["id"]), None)
            if current is None:
                current = {**instance, "exercise": definition, "sets": []}
                session["exercises"].append(current)
            if not record["set_uuid"]:
                continue
            actual = {key: record.get(key) or None for key in ACTUAL_FIELDS}
            for key in ("reference_set", "pain_flag"):
                if actual[key] is not None:
                    text = str(actual[key]).lower()
                    if text not in {"true", "false", "1", "0"}:
                        raise TrainingError(f"第{index}行 {key} 必须明确布尔或空")
                    actual[key] = text in {"true", "1"}
            row = {
                **actual,
                "set_uuid": record["set_uuid"],
                "revision": int(record["source_revision"]),
                "planned": json.loads(record["planned_json"] or "{}"),
                "condition": instance["condition"],
                "deleted_at": record.get("deleted_at") or None,
                "reference_declared_at": record.get("reference_declared_at") or None,
            }
            current["sets"].append(row)
            session["sets"].append(row)
        return {
            "schema_version": "1.3.0",
            "sessions": list(sessions.values()),
            "exercise_definitions": list(definitions.values()),
            "equipment": list(machines.values()),
            "legacy_sessions": [],
            "source_events": [],
        }


def preview_import(path) -> dict:
    data = _read(path)
    file_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if data.get("legacy_csv"):
        return {
            "format": "legacy_csv",
            "sha256": file_hash,
            "rows": len(data["rows"]),
            "columns": data["columns"],
            "load_basis": "unknown",
            "catalog_mapping": "unmapped",
            "limitations": ["旧格式保留原始动作名和 weight_kg；不猜单边/总重/器械实例。"],
        }
    records = [
        row
        for s in data.get("sessions", [])
        for i in s.get("exercises", [])
        for row in i.get("sets", [])
    ]
    return {
        "format": "healthzip.training.bundle",
        "schema_version": "1.3.0",
        "sha256": file_hash,
        "sample_rows": [
            {
                "set_uuid": r.get("set_uuid"),
                "load_value": r.get("load_value"),
                "load_unit": r.get("load_unit"),
                "load_basis": _payload(r)["condition"].get("load_basis", "unknown"),
                "reps": r.get("reps"),
                "completion_state": r.get("completion_state"),
            }
            for r in records[:20]
        ],
        "sessions": len(data.get("sessions", [])),
        "sets": len(records),
        "legacy_sessions": len(data.get("legacy_sessions", [])),
        "legacy_unassigned_sets": len(data.get("legacy_unassigned_sets", [])),
        "load_bases": sorted(
            {(_payload(r)["condition"].get("load_basis") or "unknown") for r in records}
        ),
        "unknown_conditions": sum(
            not _payload(r)["condition"].get("condition_key") for r in records
        ),
        "identity_policy": "UUID + source revision, never name-only merge",
        "columns": list(ACTUAL_FIELDS),
        "limitations": [
            "导入时刻是本机 available_at；源端时间及审计原文单独保留，不回填未来可用性。",
            "外部参考组声明保留原文；缺本机可验证预声明事件时不冒充已验证参考组。",
        ],
    }


def _catalog(svc, data):
    for definition in data.get("exercise_definitions", []):
        eid, version = definition["exercise_id"], int(definition["definition_version"])
        try:
            current = svc.get_exercise(eid, version)
            if any(
                current.get(k) != definition.get(k)
                for k in ("recording_mode", "equipment_type", "default_load_basis")
            ):
                raise TrainingError("动作身份/版本冲突，不能覆盖测量含义: " + eid)
        except TrainingError as exc:
            if str(exc) != "找不到此动作":
                raise
            if eid.startswith("psa.ex."):
                raise TrainingError("未知公共种子版本，需先核查目录升级: " + eid) from exc
            copied = {
                **definition,
                "owner_id": svc.user_id,
                "custom": True,
                "scientific_review": {"status": "unreviewed", "source_ids": []},
                "muscle_participation_proposals": [],
            }
            svc.conn.execute(
                "INSERT INTO exercise_catalog(exercise_id,definition_version,owner_id,name,definition_json,custom,active,created_at) VALUES(?,?,?,?,?,1,1,?)",
                (
                    eid,
                    version,
                    svc.user_id,
                    definition.get("name_zh") or definition.get("name") or eid,
                    json_text(copied),
                    timestamp(),
                ),
            )
    for machine in data.get("equipment", []):
        current = svc.conn.execute(
            "SELECT * FROM equipment_instance WHERE id=?", (machine["id"],)
        ).fetchone()
        config = machine.get("configuration") or json.loads(
            machine.get("configuration_json") or "{}"
        )
        if current:
            if (
                current["user_id"] != svc.user_id
                or current["equipment_type"] != machine["equipment_type"]
                or json.loads(current["configuration_json"]) != config
            ):
                raise TrainingError("器械实例身份冲突，需人工选择正确实例")
        else:
            svc.create_equipment(
                machine["label"],
                machine["equipment_type"],
                config,
                equipment_id=machine["id"],
                event_id=_id("equipment", machine["id"]),
            )


def _apply_source_revision(svc, source_uuid, payload, *, base_revision, event_id=None):
    """One conflict decision covers values, targets and the source tombstone."""
    local = svc.get_set(source_uuid)
    event_id = event_id or _id("source-revision", source_uuid, timestamp())

    def apply(old, eid, now):
        current = old
        if current.get("deleted_at"):
            deletion = next(
                (
                    e
                    for e in reversed(svc.audit_events(source_uuid))
                    if e["action"] == "delete_set" and e["status"] == "applied"
                ),
                None,
            )
            if deletion is None:
                raise TrainingError("缺少可核查的删除事件，不能自动恢复此组")
            current = svc.undo_event(
                deletion["event_id"],
                base_revision=current["revision"],
                event_id=_id(eid, "restore"),
            )
        incoming_condition = payload["condition"]
        if current["condition"] != incoming_condition:
            instance = svc.get_session_exercise(current["session_exercise_id"])
            svc.update_condition(
                instance["id"],
                incoming_condition,
                base_revision=instance["revision"],
                event_id=_id(eid, "condition"),
            )
            current = svc.get_set(source_uuid)
        if current.get("planned", {}) != payload.get("planned", {}):
            current = svc.update_set_target(
                source_uuid,
                payload.get("planned", {}),
                base_revision=current["revision"],
                event_id=_id(eid, "targets"),
            )
        current = svc.edit_set(
            source_uuid,
            payload["actual"],
            base_revision=current["revision"],
            event_id=_id(eid, "actual"),
        )
        if payload.get("deleted_at"):
            current = svc.delete_set(
                source_uuid,
                base_revision=current["revision"],
                event_id=_id(eid, "delete"),
            )
        return current

    return svc._mutate(
        "import_set_revision",
        "set",
        source_uuid,
        payload,
        apply,
        event_id=event_id,
        base_revision=base_revision,
        before=lambda: svc.get_set(local["set_uuid"]),
    )


def _import_legacy_rows(svc, rows, session_id, source_name):
    """Keep fingerprints and unknown semantics without inventing a session."""
    columns = {row[1] for row in svc.conn.execute("PRAGMA table_info(strength_set)")}
    inserted = 0
    for row in rows:
        values = {
            k: v for k, v in row.items() if k in columns - {"id", "session_id", "import_batch_id"}
        }
        values.update(session_id=session_id, import_batch_id=None, user_id=svc.user_id)
        if not values.get("fingerprint"):
            raise TrainingError("旧格式记录缺少来源指纹")
        cursor = svc.conn.execute(
            "INSERT OR IGNORE INTO strength_set("
            + ",".join(values)
            + ") VALUES("
            + ",".join("?" for _ in values)
            + ")",
            tuple(values.values()),
        )
        inserted += cursor.rowcount
        source_uuid = "legacy:" + values["fingerprint"]
        raw = json_text(row)
        svc.conn.execute(
            "INSERT OR IGNORE INTO training_import_record(source_name,source_uuid,source_revision,payload_hash,local_uuid,local_revision,raw_json,imported_at) VALUES(?,?,NULL,?,?,0,?,?)",
            (
                source_name,
                source_uuid,
                hashlib.sha256(raw.encode()).hexdigest(),
                source_uuid,
                raw,
                timestamp(),
            ),
        )
    return inserted


def import_training(repo, path, *, source_name="training_file") -> dict:
    data = _read(path)
    if data.get("legacy_csv"):
        from healthzip.importers.csv_importers import import_strength_csv

        return {"format": "legacy_csv", **import_strength_csv(path, repo), "load_basis": "unknown"}
    svc = TrainingService(repo)
    result = {
        "new": 0,
        "duplicate": 0,
        "updated": 0,
        "deleted": 0,
        "conflicted": 0,
        "invalid": 0,
        "errors": [],
    }
    with svc._transaction():
        _catalog(svc, data)
    for exported in data.get("sessions", []):
        before_counts = {
            key: result[key] for key in ("new", "duplicate", "updated", "deleted", "conflicted")
        }
        try:
            with svc._transaction():
                identity = exported["session_uuid"]
                existing = svc.conn.execute(
                    "SELECT id FROM strength_session WHERE session_uuid=? AND user_id=?",
                    (identity, svc.user_id),
                ).fetchone()
                if existing:
                    session = svc.get_session(identity)
                else:
                    template = exported.get("plan_snapshot") or json.loads(
                        exported.get("plan_snapshot_json") or "null"
                    )
                    template_id = None
                    if template:
                        template_id = template["id"]
                        version = int(template.get("version") or template["current_version"])
                        original = svc.conn.execute(
                            "SELECT items_json FROM training_template_version WHERE template_id=? AND version=?",
                            (template_id, version),
                        ).fetchone()
                        if original and json.loads(original[0]) != template["items"]:
                            raise TrainingError("模板版本内容冲突，不能覆盖原模板")
                        svc.conn.execute(
                            "INSERT OR IGNORE INTO training_template(id,user_id,name,current_version,created_at) VALUES(?,?,?,?,?)",
                            (template_id, svc.user_id, template["name"], version, timestamp()),
                        )
                        svc.conn.execute(
                            "INSERT OR IGNORE INTO training_template_version(template_id,version,name,items_json,created_at) VALUES(?,?,?,?,?)",
                            (
                                template_id,
                                version,
                                template["name"],
                                json_text(template["items"]),
                                timestamp(),
                            ),
                        )
                    slots = exported.get("plan_slots") or (template or {}).get("client_plan_slots")
                    session = svc.start_session(
                        exported.get("name") or "导入训练",
                        session_id=identity,
                        started_at=exported["started_at"],
                        template_id=template_id,
                        template_version=version if template_id else None,
                        populate_template=False,
                        client_plan_slots=slots,
                        event_id=_id(source_name, "session", identity),
                    )
                for instance in exported.get("exercises", []):
                    instance_id = instance["id"]
                    current = svc.conn.execute(
                        "SELECT id FROM training_session_exercise WHERE id=? AND user_id=?",
                        (instance_id, svc.user_id),
                    ).fetchone()
                    if not current:
                        # Import into an ended session is a historical correction,
                        # represented explicitly, rather than reopening the UI session.
                        svc._insert_exercise(
                            session["id"],
                            instance_id,
                            instance["catalog_id"],
                            instance.get("condition") or json.loads(instance["condition_json"]),
                            instance.get("planned")
                            or json.loads(instance.get("planned_json") or "{}"),
                            instance.get("position", 0),
                            instance["definition_version"],
                            instance.get("replaced_from_exercise_id"),
                            instance.get("replacement_reason"),
                        )
                    for row in instance.get("sets", []):
                        source_uuid = row["set_uuid"]
                        payload = _payload(row)
                        # Normalize CSV numbers only for stable source hashing.
                        payload["actual"] = svc._actual(
                            payload["actual"],
                            payload["condition"],
                            payload["planned"],
                        )
                        payload["actual"].pop("weight_kg", None)
                        digest = hashlib.sha256(json_text(payload).encode()).hexdigest()
                        mapping = svc.conn.execute(
                            "SELECT * FROM training_import_record WHERE source_name=? AND source_uuid=?",
                            (source_name, source_uuid),
                        ).fetchone()
                        if mapping and mapping["payload_hash"] == digest:
                            result["duplicate"] += 1
                            continue
                        local_row = svc.conn.execute(
                            "SELECT id FROM strength_set WHERE set_uuid=? AND user_id=?",
                            (source_uuid, svc.user_id),
                        ).fetchone()
                        event_id = _id(source_name, source_uuid, row.get("revision") or 1, digest)
                        actual = dict(payload["actual"])
                        actual.pop("reference_set", None)  # source declaration remains in raw_json
                        actual["source_method"] = "import"
                        actual["source_record_id"] = source_uuid
                        if local_row:
                            local = svc.get_set(source_uuid)
                            conflict = svc.conn.execute(
                                "SELECT * FROM training_conflict WHERE event_id=? AND user_id=?",
                                (event_id, svc.user_id),
                            ).fetchone()
                            equivalent = {
                                k: local.get(k)
                                for k in payload["actual"]
                                if k not in {"reference_set"}
                            }
                            if conflict:
                                if not conflict["resolved_by_event_id"]:
                                    result["conflicted"] += 1
                                    continue
                                # Keeping local values is also a final decision about
                                # this source revision. Do not reopen its old receipt.
                                changed = local
                                result["duplicate"] += 1
                            elif (
                                all(
                                    str(equivalent[k]) == str(v)
                                    or (equivalent[k] is None and v is None)
                                    for k, v in payload["actual"].items()
                                    if k in equivalent
                                )
                                and bool(local.get("deleted_at")) == bool(payload["deleted_at"])
                                and local.get("condition") == payload["condition"]
                                and local.get("planned", {}) == payload["planned"]
                            ):
                                changed = local
                                result["duplicate"] += 1
                            elif mapping and int(row.get("revision") or 1) < (
                                mapping["source_revision"] or 1
                            ):
                                result["duplicate"] += 1
                                continue
                            else:
                                base = mapping["local_revision"] if mapping else 0
                                changed = _apply_source_revision(
                                    svc,
                                    source_uuid,
                                    {**payload, "actual": actual},
                                    base_revision=base,
                                    event_id=event_id,
                                )
                                if changed.get("status") == "conflicted":
                                    result["conflicted"] += 1
                                    continue
                                result["updated"] += 1
                                if payload["deleted_at"] and not local.get("deleted_at"):
                                    result["deleted"] += 1
                        else:
                            changed = svc.add_set(
                                instance_id,
                                actual,
                                payload["planned"],
                                set_id=source_uuid,
                                event_id=event_id,
                                allow_completed_session=True,
                            )
                            result["new"] += 1
                        if (
                            not local_row
                            and payload["deleted_at"]
                            and not changed.get("deleted_at")
                        ):
                            changed = svc.delete_set(
                                source_uuid,
                                base_revision=changed["revision"],
                                event_id=_id(event_id, "delete"),
                            )
                            result["deleted"] += 1
                        svc.conn.execute(
                            "INSERT INTO training_import_record(source_name,source_uuid,source_revision,payload_hash,local_uuid,local_revision,raw_json,imported_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source_name,source_uuid) DO UPDATE SET source_revision=excluded.source_revision,payload_hash=excluded.payload_hash,local_revision=excluded.local_revision,raw_json=excluded.raw_json,imported_at=excluded.imported_at",
                            (
                                source_name,
                                source_uuid,
                                row.get("revision") or 1,
                                digest,
                                source_uuid,
                                changed["revision"],
                                json_text(
                                    {
                                        "record": row,
                                        "source_events": [
                                            event
                                            for event in data.get("source_events", [])
                                            if event.get("entity_id") in {source_uuid, identity}
                                        ],
                                    }
                                ),
                                timestamp(),
                            ),
                        )
                # Freeze source feedback as a new local revision, never overwrite
                # a subsequent local edit during an unrelated reimport.
                current = svc.get_session(identity)
                if not existing and exported.get("session_status") in {
                    "completed",
                    "aborted",
                    "paused",
                }:
                    changes = {
                        k: exported.get(k)
                        for k in (
                            "session_status",
                            "ended_at",
                            "session_rpe",
                            "session_rpe_scale",
                            "duration_seconds",
                            "duration_protocol",
                        )
                    }
                    changes["feedback"] = exported.get("feedback") or {}
                    svc.update_session(
                        identity,
                        changes,
                        base_revision=current["revision"],
                        event_id=_id(source_name, "session_end", identity),
                    )
                if exported.get("deleted_at") and not svc.get_session(identity).get("deleted_at"):
                    svc.delete_session(
                        identity,
                        base_revision=svc.get_session(identity)["revision"],
                        event_id=_id(source_name, "session_deleted", identity),
                    )
        except (TrainingError, ValueError, KeyError) as exc:
            result.update(before_counts)
            result["invalid"] += 1
            result["errors"].append(
                {"session_uuid": exported.get("session_uuid"), "reason": str(exc)}
            )
    for entry in data.get("legacy_sessions", []):
        session = entry["session"]
        allowed = {
            k: session.get(k)
            for k in ("session_date", "started_at", "name", "source", "notes", "fingerprint")
        }
        with svc._transaction():
            session_id, _ = repo.create_strength_session(**allowed, commit=False)
            saved = _import_legacy_rows(svc, entry.get("sets", []), session_id, source_name)
            result["new"] += saved
            result["duplicate"] += len(entry.get("sets", [])) - saved
    unassigned = data.get("legacy_unassigned_sets", [])
    with svc._transaction():
        saved = _import_legacy_rows(svc, unassigned, None, source_name)
        result["new"] += saved
        result["duplicate"] += len(unassigned) - saved
    return result
