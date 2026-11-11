"""Optional original questionnaires with explicit observation/availability times."""

import json
from datetime import datetime, timezone
from uuid import uuid4

SCALE_VERSION = "healthzip_original_ordinal_5_v1"
ANCHORS = {"0": "无", "1": "轻微", "2": "中等", "3": "明显", "4": "很强"}


def save_state(repo, *, observed_at=None, fatigue=None, soreness=None, pain=None,
               muscle=None, side=None, location=None, movement_impact=None, event_id=None):
    now = datetime.now(timezone.utc).isoformat()
    observed = observed_at or now
    point = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    if point.tzinfo is None:
        raise ValueError("observation_timezone_required")
    for value in (fatigue, soreness):
        if value is not None and (isinstance(value, bool) or value not in range(5)):
            raise ValueError("ordinal_response_outside_anchors")
    if pain not in {None, "reported", "denied", "unknown"}:
        raise ValueError("pain_response_invalid")
    if fatigue is None and soreness is None and pain is None:
        raise ValueError("no_answer_recorded")
    identity = event_id or str(uuid4())
    data = {"fingerprint": "state-event:"+identity, "day": point.date().isoformat(),
            "observed_at": observed, "available_at": now, "temporal_provenance": "locally_observed",
            "fatigue": fatigue, "soreness": soreness, "pain": pain,
            "scale_version": SCALE_VERSION, "anchors": json.dumps(ANCHORS, ensure_ascii=False),
            "muscle": muscle, "side": side, "location": location, "movement_impact": movement_impact}
    old = repo.one("SELECT * FROM subjective_log WHERE fingerprint=?", (data["fingerprint"],))
    if old:
        if observed_at is not None and old["observed_at"] != observed_at:
            raise ValueError("event_id_reused_with_different_observation_time")
        if any(old[k] != value for k, value in data.items() if k not in {"available_at", "observed_at", "day"}):
            raise ValueError("event_id_reused_with_different_state")
        return int(old["id"])
    repo.insert_external("subjective_log", data, list(data))
    return int(repo.one("SELECT id FROM subjective_log WHERE fingerprint=?", (data["fingerprint"],))[0])
