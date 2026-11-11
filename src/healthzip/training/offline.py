"""Token endpoint adapter for the downloadable browser training recorder."""

from __future__ import annotations

import json
from pathlib import Path

from .semantics import TrainingError
from .service import TrainingService

OPERATIONS = {
    "create_exercise",
    "create_equipment",
    "create_template",
    "update_template",
    "start_session",
    "add_exercise",
    "add_set",
    "edit_set",
    "delete_set",
    "update_session",
    "end_session",
    "delete_session",
    "undo_event",
    "resolve_conflict",
    "recommendation_feedback",
    "reorder_exercises",
}


def browser_bootstrap(repo) -> dict:
    svc = TrainingService(repo)
    sessions = svc.list_sessions()[:30]
    return {
        "schema_version": "1.3.0",
        "catalog": svc.search_exercises(),
        "equipment": svc.list_equipment(),
        "templates": svc.list_templates(),
        "sessions": [svc.get_session(row["id"]) for row in sessions],
        "conflicts": svc.list_conflicts(),
        "private_data": True,
    }


def apply_event_batch(repo, events: list, *, device_id: str = "browser-local") -> dict:
    if not isinstance(events, list) or len(events) > 100:
        raise TrainingError("每批最多100个训练事件")
    if not isinstance(device_id, str) or not device_id or len(device_id) > 100:
        raise TrainingError("无效 device_id")
    svc = TrainingService(repo, device_id=device_id)
    results = []
    for event in events:
        if not isinstance(event, dict):
            raise TrainingError("事件必须是对象")
        identity, operation, arguments = (
            event.get("event_id"),
            event.get("operation"),
            event.get("arguments"),
        )
        if not isinstance(identity, str) or not identity or len(identity) > 150:
            raise TrainingError("每个事件必须具有稳定的客户端 event_id")
        if operation not in OPERATIONS or not isinstance(arguments, dict):
            raise TrainingError("未授权的训练操作或参数格式")
        if "user_id" in arguments or "device_id" in arguments:
            raise TrainingError("客户端不能扩展数据访问身份")
        if "event_id" in arguments and arguments["event_id"] != identity:
            raise TrainingError("事件ID不一致")
        try:
            result = getattr(svc, operation)(**{**arguments, "event_id": identity})
            state = "conflicted" if result.get("status") == "conflicted" else "applied"
            results.append({"event_id": identity, "status": state, "result": result})
            if state == "conflicted":
                break  # Dependent revisions must wait for a user's resolution.
        except (TrainingError, ValueError, TypeError, KeyError) as exc:
            results.append({"event_id": identity, "status": "failed", "error": str(exc)[:500]})
            break
    return {"results": results, "processed": len(results), "submitted": len(events)}


def recorder_html() -> bytes:
    """Embed only public seed navigation data; no credentials or personal data."""
    template = Path(__file__).parents[1] / "ui" / "offline_recorder.html"
    seed = json.loads(Path(__file__).with_name("exercise_catalog_seed.json").read_text())
    public = [
        {
            key: item.get(key)
            for key in (
                "exercise_id",
                "definition_version",
                "name_zh",
                "recording_mode",
                "equipment_type",
                "default_load_basis",
                "display_regions",
                "aliases_zh",
            )
        }
        for item in seed["exercises"]
    ]
    payload = json.dumps(public, ensure_ascii=False).replace("<", "\\u003c")
    return template.read_text().replace("__PUBLIC_CATALOG_JSON__", payload).encode("utf-8")
