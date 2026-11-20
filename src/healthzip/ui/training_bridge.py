"""Local, receipt-based commands for the strength-only Streamlit component.

The browser owns display and unsent input. This adapter owns validation and
calls the existing event/revision service. Commands are durably deduplicated in
that service's event log, including multi-item operations and timer actions.
No REST token, private path, scientific permission or new database is involved.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import sqlite3
from copy import deepcopy
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from healthzip.training.catalog_media import local_media, media_for
from healthzip.training.catalog_terms import EQUIPMENT_LABELS
from healthzip.training.daily_history import select_daily_history
from healthzip.training.semantics import TrainingError, numeric, timestamp
from healthzip.training.service import TrainingService

REGIONS = {
    "chest": "胸", "back": "背", "shoulders": "肩", "arms": "上臂/前臂",
    "glutes": "臀", "legs": "腿", "calves": "小腿", "core": "躯干/核心",
    "whole_body": "全身/搬运",
}
LOAD_LABELS = {
    "unknown": "口径待确认", "external_total_kg": "外部总重",
    "plates_per_side_kg": "单边配重", "per_dumbbell_kg": "每只哑铃",
    "dumbbells_total_kg": "哑铃合计", "single_implement_kg": "单件器械",
    "machine_setting": "器械刻度", "bodyweight_no_external": "自重",
    "added_load_kg": "额外负重", "assistance_setting": "助力大小",
    "band_configuration": "弹力带设置",
}
COPY_FIELDS = ("load_value", "load_unit", "reps", "duration_s", "distance_m")
MAIN_FIELDS = {*COPY_FIELDS, "body_mass_kg", "added_load_kg", "assistance_value", "rir"}


def _event(command_id, purpose):
    return str(uuid5(NAMESPACE_URL, f"healthzip:workbench:{command_id}:{purpose}"))


def _scope(repo, user_id):
    # Opaque local identity for browser recovery; paths never enter the component.
    return hashlib.sha256(f"{repo.path.resolve()}\0{user_id}".encode()).hexdigest()[:24]


@lru_cache(maxsize=128)
def _thumbnail(path, digest):
    try:
        from PIL import Image

        with Image.open(path) as original:
            thumb = original.convert("RGB")
            thumb.thumbnail((128, 128))
            output = io.BytesIO()
            thumb.save(output, format="JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    except Exception:
        # Optional image codecs can raise errors outside OSError/ValueError
        # (for example Pillow's decompression-bomb guard). A failed preview
        # must never prevent editing or saving a real training record.
        return None


def _media(svc, exercise_id):
    """Only verified, currently permitted local assets; never download on render."""
    result = []
    thumbnail = None
    try:
        media = media_for(svc.conn, exercise_id)
    except Exception:
        # Catalog metadata is an optional presentation dependency. A corrupt
        # object or unavailable media query becomes the neutral placeholder;
        # training reads and mutations retain their normal error boundaries.
        return None, []
    for item in media:
        if not isinstance(item, dict):
            continue
        public = {key: item.get(key) for key in (
            "media_id", "media_type", "fetch_status", "attribution_text", "author",
            "license", "original_work_url", "changes",
        )}
        public["available"] = False
        if item.get("local_path") and item.get("blob_hash"):
            try:
                path, mime = local_media(svc.conn, item["blob_hash"])
                if item["media_type"] == "image":
                    url = _thumbnail(str(path), item["blob_hash"])
                    public["image"] = url
                    public["available"] = bool(url)
                    if url:
                        public["changes"] = "界面缩略图：调整尺寸并转为 JPEG；原图保留"
                    thumbnail = thumbnail or url
                else:
                    public["available"] = True
                # Video remains available through the original local media detail
                # view; do not base64-embed potentially huge files in each rerun.
                public["mime"] = mime
            except Exception:
                public["available"] = False
        result.append(public)
    return thumbnail, result


def _catalog_item(svc, item, *, include_media=True):
    thumbnail, media = _media(svc, item["exercise_id"]) if include_media else (None, [])
    return {
        "id": item["exercise_id"], "exercise_id": item["exercise_id"],
        "name": item.get("name") or item.get("name_zh"),
        "name_en": item.get("name_en"), "definition_version": item["definition_version"],
        "recording_mode": item["recording_mode"],
        "default_load_basis": item.get("default_load_basis", "unknown"),
        "equipment_type": item.get("equipment_type"),
        "equipment_label": EQUIPMENT_LABELS.get(item.get("equipment_type"), "其他／待确认"),
        "regions": item.get("display_regions", []), "favorite": bool(item.get("favorite")),
        "last_used_at": item.get("last_used_at"), "custom": bool(item.get("custom")),
        "search_terms": [str(name).casefold() for name in [item.get("name", ""),
            item.get("name_en", ""), item["exercise_id"], *item.get("aliases_zh", []),
            *item.get("user_aliases", [])] if name],
        "thumbnail": thumbnail, "media": media,
    }


def _session(svc, identity):
    session = svc.get_session(identity)
    for item in session["exercises"]:
        item["thumbnail"], item["media"] = _media(svc, item["catalog_id"])
        item["load_label"] = LOAD_LABELS.get(item["condition"].get("load_basis"), "口径待确认")
        item["equipment_label"] = EQUIPMENT_LABELS.get(item["exercise"].get("equipment_type"), "其他／待确认")
        item["completed_sets"] = 0 if session.get("deleted_at") else sum(
            row.get("completion_state") == "completed" and not row.get("deleted_at")
            for row in item["sets"]
        )
    return session


def _summary(svc, row, zone):
    actual_date = None
    if row.get("started_at"):
        try:
            actual_date = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00")).astimezone(zone).date().isoformat()
        except ValueError:
            pass
    # session_date is an existing recorded date, not an import timestamp.
    actual_date = actual_date or row.get("session_date")
    exercises = svc.conn.execute(
        "SELECT definition_snapshot_json,condition_json FROM training_session_exercise "
        "WHERE session_id=? AND user_id=? ORDER BY position,id", (row["id"], svc.user_id),
    ).fetchall()
    names, regions = [], []
    for item in exercises:
        definition = json.loads(item["definition_snapshot_json"] or "{}")
        names.append(definition.get("name") or definition.get("name_zh") or "动作")
        regions.extend(definition.get("display_regions", []))
    count = svc.conn.execute(
        "SELECT COUNT(*) FROM strength_set WHERE session_id=? AND user_id=? "
        "AND deleted_at IS NULL AND completion_state='completed'", (row["id"], svc.user_id),
    ).fetchone()[0]
    return {**{key: row.get(key) for key in (
        "id", "session_uuid", "name", "started_at", "ended_at", "session_status", "revision", "deleted_at",
    )}, "date": actual_date, "completed_sets": 0 if row.get("deleted_at") else count,
        "exercise_count": len(exercises), "exercise_names": names,
        "regions": list(dict.fromkeys(regions))}


def _calendar_rows(svc, month, timezone_name):
    """Read the complete local calendar month, independent of history pagination.

    Existing timestamps retain their offsets, so UTC text comparisons would
    misclassify boundary records. SQLite julianday compares actual instants.
    Date-only legacy sessions use only their explicitly stored session_date.
    """
    first = date.fromisoformat(month + "-01")
    end = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    zone = ZoneInfo(timezone_name)
    start_at = datetime.combine(first, datetime.min.time(), zone).isoformat()
    end_at = datetime.combine(end, datetime.min.time(), zone).isoformat()
    rows = svc.conn.execute(
        "SELECT * FROM strength_session WHERE user_id=? AND deleted_at IS NULL AND "
        "((started_at IS NOT NULL AND julianday(started_at)>=julianday(?) "
        "AND julianday(started_at)<julianday(?)) OR "
        "(started_at IS NULL AND session_date>=? AND session_date<?)) "
        "ORDER BY julianday(started_at),id",
        (svc.user_id, start_at, end_at, first.isoformat(), end.isoformat()),
    ).fetchall()
    return [_summary(svc, dict(row), zone) for row in rows]


def _calendar_snapshot(svc, month, timezone_name):
    """A short WAL read snapshot; this never obtains a private-db write lock."""
    owns_transaction = not svc.conn.in_transaction
    if owns_transaction:
        svc.conn.execute("BEGIN")
    try:
        version = svc.data_version()
        rows = _calendar_rows(svc, month, timezone_name)
        if owns_transaction:
            svc.conn.commit()
        return rows, version
    except BaseException:
        if owns_transaction:
            svc.conn.rollback()
        raise


def calendar_sessions(svc, month, timezone_name="Asia/Shanghai"):
    """Complete month with internally consistent session and set counts."""
    return _calendar_snapshot(svc, month, timezone_name)[0]


def _knowledge_clock(root=".local/knowledge"):
    """Conservative UI invalidation only; scientific authority stays in core.

    File generations are cheap to inspect and include committed WAL changes.
    An unrelated public-library audit may also mark the panel stale. Reopening
    explicitly invokes current_advice and its full authoritative checks.
    """
    result = []
    for name in ("sources.sqlite3", "theories.sqlite3"):
        for suffix in ("", "-wal"):
            path = Path(root) / (name + suffix)
            try:
                stat = path.stat()
                result.append((name + suffix, stat.st_mtime_ns, stat.st_size, stat.st_ino))
            except OSError:
                result.append((name + suffix, None))
    return result


def _advice_dependencies(svc, state, instance_id):
    from healthzip.training.current import equipment_loads
    from healthzip.workflows.dependencies import input_version

    instance = svc.get_session_exercise(instance_id)
    return {"inputs": input_version(svc.repo, state.get("context_id")),
        "settings": equipment_loads(svc.repo, instance), "knowledge": _knowledge_clock(),
        "timezone": state.get("timezone_name", "Asia/Shanghai"),
        "window_days": int(state.get("window_days", 30))}


def _catalog(svc, payload):
    equipment = payload.get("equipment_type")
    result = svc.search_catalog(
        str(payload.get("query", "")), regions=payload.get("regions") or None,
        equipment=[equipment] if equipment else None, view=payload.get("view", "all"),
        offset=int(payload.get("offset", 0)), limit=int(payload.get("limit", 30)),
    )
    definitions = svc.search_exercises()
    # A bounded metadata index supports local names/aliases and filters. Media
    # stays on the requested page; unusually large catalogs keep server paging.
    search_index = ([_catalog_item(svc, item, include_media=False) for item in definitions]
        if len(definitions) <= 5000 else None)
    return {**result, "items": [_catalog_item(svc, item) for item in result["items"]],
            "query": payload.get("query", ""), "filters": payload,
            "search_index": search_index, "data_version": svc.data_version(),
            "catalog_version": _catalog_version(svc)}


def _catalog_version(svc):
    row = svc.conn.execute("SELECT value FROM schema_meta WHERE key='catalog_data_version'").fetchone()
    # Aliases/favorites are user preferences, without training-event revisions.
    # Include their actual committed values so another process cannot leave the
    # component's metadata snapshot valid after editing them.
    aliases = [tuple(value) for value in svc.conn.execute(
        "SELECT exercise_id,alias FROM exercise_alias WHERE user_id=? ORDER BY exercise_id,alias",
        (svc.user_id,))]
    preferences = [tuple(value) for value in svc.conn.execute(
        "SELECT exercise_id,favorite,last_used_at FROM exercise_preference WHERE user_id=? ORDER BY exercise_id",
        (svc.user_id,))]
    return hashlib.sha256(json.dumps([row[0] if row else "0", aliases, preferences],
        ensure_ascii=False).encode()).hexdigest()


def build_snapshot(repo, state, timezone_name="Asia/Shanghai"):
    """Build only the current requested inventory; advice/history are explicit."""
    svc = TrainingService(repo)
    zone = ZoneInfo(timezone_name)
    now = datetime.now(timezone.utc)
    today = now.astimezone(zone).date().isoformat()
    month = state.setdefault("month", today[:7])
    state.setdefault("selected_date", today)
    state["timezone_name"] = timezone_name
    version = svc.data_version()
    cached_catalog = state.get("catalog")
    if cached_catalog and (cached_catalog.get("data_version") != version
            or cached_catalog.get("catalog_version") != _catalog_version(svc)):
        state.pop("catalog", None)
    if (state.get("calendar_dirty", True) or state.get("calendar_month") != month
            or state.get("calendar_version") != version):
        state["calendar"], state["calendar_version"] = _calendar_snapshot(svc, month, timezone_name)
        state["calendar_month"] = month
        state["calendar_dirty"] = False
    if "regions" not in state:
        # Metadata only, without generating hundreds of media thumbnails/widgets.
        definitions = svc.search_exercises()
        region_ids = {region for item in definitions for region in item.get("display_regions", [])}
        state["regions"] = [{"id": key, "name": label} for key, label in REGIONS.items() if key in region_ids]
        state["equipment_types"] = [{"id": key, "name": EQUIPMENT_LABELS.get(key, "其他／待确认")}
            for key in sorted({item["equipment_type"] for item in definitions})]
    identity = state.get("session_id")
    session = None
    if identity:
        try:
            session = _session(svc, identity)
        except TrainingError:
            state.pop("session_id", None)
    # Frozen detail results are never silently reused after a dependency change.
    if state.get("history_version") != version:
        state.pop("history", None)
    advice = state.get("advice")
    if advice:
        try:
            state["advice_stale"] = state.get("advice_stale", False) or (
                state.get("advice_dependencies") != _advice_dependencies(svc, state, advice["instance_id"]))
        except (ValueError, KeyError, OSError, sqlite3.Error):
            state["advice_stale"] = True
        advice = {**advice, "stale": bool(state.get("advice_stale")),
            "stale_message": "记录或依据已更新，请重新核对；以下保留原冻结时点" if state.get("advice_stale") else None}
    return {
        "db_scope": _scope(repo, svc.user_id), "user_id": svc.user_id,
        "timezone": timezone_name, "timezone_name": timezone_name, "now": now.isoformat(),
        "today": today, "month": month, "selected_date": state["selected_date"],
        "calendar": state.get("calendar", []),
        "active_sessions": [_summary(svc, row, zone) for row in svc.list_sessions(active_only=True)],
        "session": session, "templates": [{"id": item["id"], "name": item["name"]} for item in svc.list_templates()],
        "regions": state["regions"], "equipment_types": state["equipment_types"],
        "catalog": state.get("catalog"), "history": state.get("history"),
        "advice": advice, "advice_job": state.get("advice_job_public"),
        "receipt": state.get("receipt"), "data_version": version,
    }


def _revision(payload):
    revision = payload.get("base_revision")
    if type(revision) is not int or revision < 1:
        raise TrainingError("缺少当前记录版本，请刷新记录后重试；本地输入仍会保留")
    return revision


def _require_active(svc, session_id):
    session = svc._session(session_id)
    if session.get("deleted_at") or session["session_status"] not in {"draft", "in_progress", "paused"}:
        raise TrainingError("这场训练已结束或删除，请通过历史更正修改已有记录")
    return session


def _add_exercises(svc, payload, event_id):
    session = svc._session(payload["session_id"])
    items = payload.get("exercises")
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise TrainingError("请选择 1–50 个动作")
    identity = session["session_uuid"]

    def apply(current, eid, now):
        _require_active(svc, identity)
        existing = {item["catalog_id"] for item in svc.get_session(identity)["exercises"]}
        added = []
        position = svc.conn.execute(
            "SELECT COALESCE(MAX(position),-1)+1 FROM training_session_exercise WHERE session_id=?",
            (current["id"],),
        ).fetchone()[0]
        for index, item in enumerate(items):
            exercise_id = item["exercise_id"] if isinstance(item, dict) else item
            repeat = isinstance(item, dict) and item.get("allow_repeat") is True
            if exercise_id in existing and not repeat:
                raise TrainingError("所选动作已在本场训练中，请明确选择“再次添加此动作”")
            exercise = svc.get_exercise(exercise_id)
            # A catalog default is not a user's confirmation. Only reuse an
            # explicitly confirmed, unchanged definition from prior instances.
            condition = {}
            previous = svc.conn.execute(
                "SELECT condition_json FROM training_session_exercise WHERE user_id=? "
                "AND catalog_id=? AND definition_version=? ORDER BY rowid DESC LIMIT 1",
                (svc.user_id, exercise_id, exercise["definition_version"]),
            ).fetchone()
            if previous:
                candidate = json.loads(previous[0])
                if candidate.get("load_basis_confirmed") is True:
                    condition = candidate
            instance_id = _event(eid, f"exercise:{index}")
            # As in TrainingService.start_session, all rows of this single
            # atomic operation share its visibility timestamp. Nested public
            # mutations would have later timestamps than the parent snapshot.
            svc._insert_exercise(current["id"], instance_id, exercise_id, condition,
                {}, position + index, exercise["definition_version"], bound_at=now)
            svc._insert_set(instance_id, _event(eid, f"blank:{index}"), {}, {}, now)
            existing.add(exercise_id)
            added.append(instance_id)
        svc.conn.execute("UPDATE strength_session SET revision=revision+1,available_at=? WHERE id=?", (now, current["id"]))
        return {**svc.get_session(identity), "added_instance_ids": added}

    return svc._mutate("add_exercises", "session", identity, {"exercises": items}, apply,
        event_id=event_id, base_revision=_revision(payload), before=lambda: svc._session(identity))


def _copy_values(source):
    # Actual effort, quality, pain, occurrence/finish time, reference/adoption
    # identities deliberately do not transfer into a new observation.
    return {key: source.get(key) for key in COPY_FIELDS if source.get(key) is not None}


def _save_set(svc, payload, event_id):
    current = svc.get_set(payload["set_id"])
    if svc._session(current["session_id"]).get("deleted_at"):
        raise TrainingError("所属训练已删除，请先撤销删除再更正记录")
    changes = deepcopy(payload.get("changes") or {})
    if set(changes) - MAIN_FIELDS:
        raise TrainingError("主行仅保存重量、次数/时长/距离和 RIR；高级字段请打开组详情")
    if current.get("completion_state") == "completed":
        if not payload.get("correction"):
            # A second completion is read-only, including after a lost receipt.
            if payload.get("complete"):
                equivalent = all(
                    (current.get(key) or None) == (value or None) if key == "load_unit"
                    else numeric(current.get(key), key, integer=key == "reps") == numeric(value, key, integer=key == "reps")
                    for key, value in changes.items()
                )
                if not equivalent:
                    return {"status": "conflicted", "current_revision": current["revision"],
                        "current": current, "proposed": changes,
                        "message": "此组已完成且数值不同；输入已保留，请核对后使用更正"}
                return {**current, "status": "saved", "already_completed": True}
            raise TrainingError("已完成组请使用“更正”保存修改")
    elif not payload.get("correction"):
        _require_active(svc, current["session_id"])
    if payload.get("complete"):
        changes["completion_state"] = "completed"
    elif current.get("completion_state") != "completed":
        changes["completion_state"] = "draft"
    # Service merges only supplied fields into the current actual record,
    # preserving hidden quality/pain/relations/times and planned targets.
    return svc.edit_set(current["set_uuid"], changes, base_revision=_revision(payload), event_id=event_id)


def _dispatch(svc, action, p, state, event_id):
    if action == "start_session":
        # Never accept a selected calendar date as today's occurrence time.
        title = str(p.get("name") or "")
        if not title and not p.get("template_id"):
            title = datetime.now(ZoneInfo(state.get("timezone_name", "Asia/Shanghai"))).strftime("%m月%d日 %H:%M 训练")
        result = svc.start_session(title, template_id=p.get("template_id") or None,
            event_id=event_id)
        state["session_id"] = result["session_uuid"]
        return result
    if action == "add_exercises":
        return _add_exercises(svc, p, event_id)
    if action in {"add_set", "copy_history"}:
        instance = svc.get_session_exercise(p["instance_id"])
        _require_active(svc, instance["session_id"])
        if instance["revision"] != _revision(p):
            return {"status": "conflicted", "current_revision": instance["revision"],
                    "message": "动作条件已变化，请保留输入并重新核对"}
        source = p.get("source_set_id") if action == "copy_history" else p.get("copy_from_set_id")
        actual = {}
        if source:
            row = svc.get_set(source)
            if row.get("deleted_at") or row["catalog_id"] != instance["catalog_id"]:
                raise TrainingError("不能复制已删除或不同动作的记录")
            if action == "copy_history":
                history = select_daily_history(svc, instance, cutoff_time=timestamp())
                candidates = {item["set_uuid"] for item in history["records"]}
                if row["set_uuid"] not in candidates:
                    raise TrainingError("这条记录已不属于最近一次动作历史，请重新打开历史")
            elif row["session_exercise_id"] != instance["id"]:
                raise TrainingError("复制上一组只能使用本动作实例的记录")
            actual = _copy_values(row)
        return svc.add_set(instance["id"], actual, event_id=event_id)
    if action == "reorder_exercises":
        _require_active(svc, p["session_id"])
        return svc.reorder_exercises(p["session_id"], p["instance_ids"],
            base_revision=_revision(p), event_id=event_id)
    if action == "save_set":
        return _save_set(svc, p, event_id)
    if action == "abort_session":
        current = _require_active(svc, p["session_id"])
        return svc.update_session(current["session_uuid"],
            {"session_status": "aborted", "ended_at": timestamp()},
            base_revision=_revision(p), event_id=event_id)
    if action == "update_session":
        current = svc._session(p["session_id"])
        changes = deepcopy(p.get("changes") or {})
        if set(changes) - {"name", "notes", "session_status", "ended_at"}:
            raise TrainingError("此入口仅编辑训练名称、备注或中断状态")
        if current.get("deleted_at"):
            raise TrainingError("请先撤销删除")
        if "notes" in changes:
            changes["feedback"] = {**(current.get("feedback") or {}), "notes": changes["notes"]}
        if "session_status" in changes:
            _require_active(svc, p["session_id"])
            if changes["session_status"] not in {"paused", "in_progress", "aborted"}:
                raise TrainingError("结束训练请使用结束摘要确认入口")
            if changes["session_status"] == "aborted":
                changes.setdefault("ended_at", timestamp())
        if "ended_at" in changes and changes.get("session_status") != "aborted":
            raise TrainingError("更正训练时间请打开训练详情")
        return svc.update_session(p["session_id"], changes, base_revision=_revision(p), event_id=event_id)
    if action == "end_session":
        current = svc._session(p["session_id"])
        if current.get("session_status") == "completed" and not current.get("deleted_at"):
            return {**svc.get_session(p["session_id"]), "status": "saved", "already_completed": True}
        _require_active(svc, p["session_id"])
        minutes = numeric(p.get("duration_minutes"), "训练时长分钟")
        score = numeric(p.get("session_rpe", current.get("session_rpe")), "整场主观用力")
        feedback = deepcopy(current.get("feedback") or {})
        if "notes" in p:
            feedback["notes"] = p["notes"]
        duration_seconds = minutes * 60 if minutes is not None else None
        duration_protocol = "user_elapsed_including_rest" if minutes is not None else None
        if "duration_minutes" not in p:
            duration_seconds = current.get("duration_seconds")
            duration_protocol = current.get("duration_protocol")
        scale = p.get("rpe_scale", current.get("session_rpe_scale")) or "cr10"
        collected_at = (timestamp() if "session_rpe" in p else current.get("session_rpe_collected_at")) if score is not None else None
        return svc.end_session(p["session_id"], base_revision=_revision(p), event_id=event_id,
            feedback=feedback, notes=p.get("notes"),
            session_rpe=score, rpe_scale=scale if score is not None else None,
            rpe_collected_at=collected_at, duration_seconds=duration_seconds,
            duration_protocol=duration_protocol)
    if action == "delete_set":
        return svc.delete_set(p["set_id"], base_revision=_revision(p), event_id=event_id)
    if action == "delete_session":
        return svc.delete_session(p["session_id"], base_revision=_revision(p), event_id=event_id)
    if action == "undo":
        return svc.undo_event(p["event_id"], base_revision=_revision(p), event_id=event_id)
    if action == "favorite":
        svc.favorite(p["exercise_id"], bool(p.get("enabled")))
        return {"status": "saved", "exercise_id": p["exercise_id"]}
    if action == "timer":
        current = _require_active(svc, p["session_id"])
        if current["revision"] != _revision(p):
            return {"status": "conflicted", "current_revision": current["revision"]}
        return svc.rest_timer(p["session_id"], p["action"], target_seconds=p.get("target_seconds"))
    raise TrainingError("未知训练操作")


def handle_command(repo, command, state):
    """Execute one explicit command and return its real durable acknowledgement."""
    if not isinstance(command, dict) or not isinstance(command.get("payload", {}), dict):
        return {"status": "error", "message": "操作格式无效"}
    identity, action, p = command.get("id"), command.get("action"), command.get("payload", {})
    if not isinstance(identity, str) or not 1 <= len(identity) <= 128:
        return {"status": "error", "message": "缺少稳定请求身份"}
    svc = TrainingService(repo)
    try:
        if action == "calendar":
            month = str(p.get("month", state.get("month", "")))
            date.fromisoformat(month + "-01")
            state.update(month=month, calendar_dirty=True)
            if p.get("selected_date"):
                state["selected_date"] = date.fromisoformat(p["selected_date"]).isoformat()
            data = {"month": month}
        elif action == "session":
            data = svc.get_session(p["session_id"])
            state["session_id"] = data["session_uuid"]
        elif action == "catalog":
            data = state["catalog"] = _catalog(svc, p)
        elif action == "history":
            instance = svc.get_session_exercise(p["instance_id"])
            data = state["history"] = {**select_daily_history(svc, instance, cutoff_time=timestamp()),
                "instance_id": instance["id"]}
            state["history_version"] = svc.data_version()
        elif action == "advice":
            from healthzip.training.current import current_advice

            dependencies = _advice_dependencies(svc, state, p["instance_id"])
            data = state["advice"] = {**current_advice(repo, p["instance_id"],
                context_id=state.get("context_id"), window_days=int(state.get("window_days", 30)),
                timezone_name=state.get("timezone_name", "Asia/Shanghai")), "instance_id": p["instance_id"]}
            state["advice_dependencies"] = dependencies
            state["advice_stale"] = dependencies != _advice_dependencies(svc, state, p["instance_id"])
        else:
            # One wrapper ledger entry makes retrying the whole batch or timer
            # safe even after the browser/Streamlit session was recreated.
            def apply(old, eid, now):
                result = _dispatch(svc, action, p, state, _event(eid, "operation"))
                return {"status": result.get("status", "saved"), "data": result}

            saved = svc._mutate("workbench_command", "ui_command", identity,
                {"action": action, "payload": p}, apply, event_id=identity, invalidates=False)
            data = saved.get("data", {})
            if data.get("session_uuid"):
                state["session_id"] = data["session_uuid"]
            elif data.get("session_id"):
                state["session_id"] = svc._session(data["session_id"])["session_uuid"]
            state["calendar_dirty"] = True
            if action == "favorite" and state.get("catalog"):
                state["catalog"] = _catalog(svc, state["catalog"].get("filters") or {})
            receipt = {"id": identity, "action": action, "status": saved["status"],
                "data": data, "replayed": saved.get("replayed", False),
                "event_id": data.get("event_id")}
            if saved["status"] == "conflicted":
                receipt["message"] = "记录已在另一处修改；你的输入已保留，请核对最新记录后重新保存"
            state["receipt"] = receipt
            return receipt
        receipt = {"id": identity, "action": action, "status": "saved", "data": data}
    except TrainingError as exc:
        message = str(exc)
        for raw, friendly in {"load_value": "重量/刻度", "load_unit": "负荷单位",
            "duration_s": "时长秒数", "distance_m": "距离米数", "reps": "次数",
            "rir": "RIR", "event_id": "请求身份", "base_revision": "记录版本",
            "stack_level": "配重刻度", "level": "器械刻度"}.items():
            message = message.replace(raw, friendly)
        receipt = {"id": identity, "action": action, "status": "error", "message": message + "；输入已保留"}
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, sqlite3.Error):
        # Do not expose SQL, UUIDs, filesystem paths or knowledge internals in
        # the normal product flow. Input values remain on the client for retry.
        receipt = {"id": identity, "action": action, "status": "error",
            "message": "保存未成功，请检查数值、单位和记录状态后重试；输入已保留"}
        if action == "advice":
            receipt["message"] = "本次建议暂不可用，仍可正常保存实际训练"
            state["advice_stale"] = True
    if action == "advice" and receipt["status"] == "error":
        state["advice_stale"] = True
    state["receipt"] = receipt
    return receipt
