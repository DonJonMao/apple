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
    from .catalog_import import public_catalog, published_snapshot
    from .catalog_media import media_for

    svc = TrainingService(repo)
    sessions = svc.list_sessions()[:30]
    templates = svc.list_templates()
    definitions = {
        (item["exercise_id"], item["definition_version"]): item.get("exercise_snapshot")
        or svc.get_exercise(item["exercise_id"], item["definition_version"])
        for template in templates
        for item in template["items"]
    }
    catalog = svc.search_exercises()
    for item in catalog:
        item["media"] = [
            {k: v for k, v in media.items() if k not in {"local_path", "error"}}
            for media in media_for(repo.conn, item["exercise_id"])
        ]
    return {
        "schema_version": "1.3.0",
        "catalog": catalog,
        "catalog_snapshot_id": published_snapshot(repo.conn),
        "catalog_public_ids": [x["exercise_id"] for x in public_catalog(repo)["items"]],
        "catalog_definitions": list(definitions.values()),
        "equipment": svc.list_equipment(),
        "templates": templates,
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


def recorder_html(repo=None) -> bytes:
    """Embed installed public catalog; seed fallback only before any installation."""
    from .catalog_import import public_catalog
    from .catalog_media import media_for

    template = Path(__file__).parents[1] / "ui" / "offline_recorder.html"
    seed = json.loads(Path(__file__).with_name("exercise_catalog_seed.json").read_text())
    public_data = (
        public_catalog(repo)
        if repo is not None
        else {"items": seed["exercises"], "snapshot_id": seed["catalog_version"]}
    )
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
                "name_en",
                "source",
                "names",
                "description",
            )
        }
        for item in public_data["items"]
    ]
    if repo is not None:
        for item in public:
            item["media"] = [
                {
                    **{k: v for k, v in media.items() if k not in {"local_path", "error"}},
                    "package_path": "media/" + media["blob_hash"] if media["local_path"] else None,
                }
                for media in media_for(repo.conn, item["exercise_id"])
            ]
    payload = json.dumps(public, ensure_ascii=False).replace("<", "\\u003c")
    return (
        template.read_text()
        .replace("__PUBLIC_CATALOG_JSON__", payload)
        .replace("__CATALOG_SNAPSHOT_JSON__", json.dumps(public_data["snapshot_id"]))
        .encode("utf-8")
    )
