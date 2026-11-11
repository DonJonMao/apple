"""Freeze explicitly supplied anatomy review records without promoting source tags."""

import json
from datetime import datetime

from .semantics import TrainingError, json_text, timestamp


def freeze_mapping(mapping, exercise_id, definition_version, bound_at, *, preserve_time=False):
    if mapping is None:
        return None
    if not isinstance(mapping, dict):
        raise TrainingError("肌肉关系须提供完整审核快照")
    result = json.loads(json_text(mapping))
    required = ("mapping_id", "version", "reviewer", "reviewed_at")
    if result.get("review_status") != "approved" or any(not result.get(k) for k in required):
        raise TrainingError("肌肉关系缺少批准状态、版本或审阅记录；可不采用映射继续记录")
    if any(
        not isinstance(result[k], str) or not result[k].strip() for k in ("mapping_id", "reviewer")
    ) or isinstance(result["version"], bool):
        raise TrainingError("肌肉关系审阅者、身份和版本格式不完整")
    if result.get("exercise_id") != exercise_id or str(result.get("definition_version")) != str(
        definition_version
    ):
        raise TrainingError("肌肉关系适用动作身份或定义版本不符")
    if any(
        not isinstance(result.get(role), list)
        or any(not isinstance(x, str) or not x.strip() for x in result[role])
        for role in ("direct", "indirect")
    ):
        raise TrainingError("直接与间接肌肉关系须分别保存明确标识列表")
    refs = result.get("evidence_refs")
    if (
        not isinstance(refs, list)
        or not refs
        or not all(isinstance(x, (str, dict)) and bool(x) for x in refs)
    ):
        raise TrainingError("肌肉关系缺少实际来源定位引用")
    reviewed = timestamp(result["reviewed_at"])
    frozen = timestamp(result.get("frozen_at")) if preserve_time else timestamp(bound_at)
    if preserve_time and not result.get("frozen_at"):
        raise TrainingError("历史肌肉关系缺少原冻结时间")
    if (
        not datetime.fromisoformat(reviewed)
        <= datetime.fromisoformat(frozen)
        <= datetime.fromisoformat(timestamp(bound_at))
    ):
        raise TrainingError("肌肉关系审核或冻结时间晚于记录可用时间")
    result.update(reviewed_at=reviewed, frozen_at=frozen)
    return result


def assert_mapping_version(conn, user_id, mapping):
    if mapping is None:
        return
    identity = mapping["mapping_id"], str(mapping["version"])
    content = {k: v for k, v in mapping.items() if k != "frozen_at"}
    for row in conn.execute(
        "SELECT condition_json FROM training_session_exercise WHERE user_id=?", (user_id,)
    ):
        old = json.loads(row["condition_json"]).get("reviewed_anatomy_snapshot")
        if not old or (old.get("mapping_id"), str(old.get("version"))) != identity:
            continue
        if {k: v for k, v in old.items() if k != "frozen_at"} != content:
            raise TrainingError("已有肌肉关系版本不可重写；修改内容必须采用新版本")
