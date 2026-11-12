"""Explicit source-bound sleep declarations; no automatic episode detection."""

from datetime import date
from zoneinfo import ZoneInfo

from healthzip.science import evaluate
from healthzip.science.contracts import canonical_hash, instant, select_as_of
from healthzip.science.state import ASLEEP, local_date_domain, stage, stream_key

VERSION = "user-declared-sleep-selection-1.4.0"
METRICS = ("STATE-SLEEP-MAIN", "STATE-SLEEP-24H", "STATE-SLEEP-COVERAGE", "STATE-SLEEP-STAGE", "STATE-SLEEP-TIMING")


def _observations(records, window):
    rows, _ = select_as_of([row for row in records if row.get("canonical_type") == "sleep_stage"], window, overlap=True)
    return [row for row in rows if stage(row) in ASLEEP | {"awake"}]


def sleep_options(records, window):
    groups = {}
    for row in _observations(records, window):
        key = stream_key(row)
        identity = canonical_hash(key)
        group = groups.setdefault(identity, {"stream_id": identity, "stream_key": list(key),
            "source_name": key[0], "device": key[1], "protocol_id": key[2], "source_version": key[3], "observations": []})
        group["observations"].append({"record_id": row["_source_id"], "stage": stage(row),
            "start": row.get("event_start") or row.get("start_utc"), "end": row["_event_end"],
            "available_at": row.get("available_at"), "revision_sha256": canonical_hash(row)})
    return {"adapter_version": VERSION, "streams": [group for group in groups.values()
            if any(item["stage"] in ASLEEP for item in group["observations"])], "timezone": window.timezone}


def declare_episode(options, stream_id, *, start, end, attribution_date, declared_at):
    """Bind a user-entered boundary to exactly the visible supporting revisions."""
    first, last, declared = instant(start), instant(end), instant(declared_at)
    if first >= last:
        raise ValueError("睡眠片段终点须晚于起点")
    if last > declared:
        raise ValueError("sleep_episode_not_ended_at_declaration")
    date.fromisoformat(attribution_date)
    zone = ZoneInfo(options["timezone"])
    if attribution_date not in local_date_domain(first, last, options["timezone"]) | {last.astimezone(zone).date().isoformat()}:
        raise ValueError("sleep_attribution_date_outside_declared_local_dates")
    source = next((row for row in options["streams"] if row["stream_id"] == stream_id), None)
    if source is None:
        raise ValueError("请明确选择当前可见的睡眠记录来源")
    overlapping = [row for row in source["observations"]
        if row["start"] and instant(row["start"]) < last and instant(row["end"]) > first]
    if not any(row["stage"] in ASLEEP for row in overlapping):
        raise ValueError("声明边界内没有所选来源的可见睡眠记录")
    if any(not row["available_at"] or instant(row["available_at"]) > declared for row in overlapping):
        raise ValueError("睡眠来源在声明时尚不可见，不能回填声明时间")
    value = {"start": start, "end": end, "attribution_date": attribution_date,
        "timezone": options["timezone"], "stream_id": stream_id, "origin": "user_declared",
        "declared_at": declared.isoformat(), "available_at": declared.isoformat(), "complete": False,
        "source_revisions": {row["record_id"]: row["revision_sha256"] for row in overlapping}}
    return {"id": "sleep-declaration:" + canonical_hash(value), **value}


def selected_sleep_metrics(records, window, selection):
    options = sleep_options(records, window)
    source = next((row for row in options["streams"] if row["stream_id"] == selection.get("stream_id")), None)
    audit = {"adapter_version": VERSION, "source": source, "episodes": [], "main_episode_id": selection.get("main_episode_id"),
        "reason_codes": [], "cutoff_time": window.cutoff_time, "origin": "user_declared", "accepted": True}
    candidates = selection.get("episodes", [])
    if source is None:
        audit["reason_codes"].append("selected_sleep_source_unavailable")
    if not candidates:
        audit["reason_codes"].append("sleep_episode_declaration_required")
    for item in candidates:
        try:
            if item.get("stream_id") != selection.get("stream_id") or item.get("origin") != "user_declared":
                raise ValueError("sleep_declaration_source_mismatch")
            if instant(item["declared_at"]) > instant(window.cutoff_time):
                raise ValueError("sleep_declaration_after_analysis_cutoff")
            if not instant(window.start) <= instant(item["start"]) < instant(item["end"]) <= instant(window.end):
                raise ValueError("sleep_declaration_outside_analysis_window")
            if instant(item["end"]) > instant(window.cutoff_time):
                raise ValueError("sleep_declaration_endpoint_after_cutoff")
            current = declare_episode(options, selection.get("stream_id"), start=item["start"], end=item["end"],
                attribution_date=item["attribution_date"], declared_at=item["declared_at"])
            if current["source_revisions"] != item.get("source_revisions") or current["id"] != item.get("id"):
                raise ValueError("sleep_source_revisions_changed_reconfirmation_required")
            if any(instant(current["start"]) < instant(old["end"]) and instant(current["end"]) > instant(old["start"])
                   for old in audit["episodes"]):
                raise ValueError("overlapping_sleep_declarations_not_independent_episodes")
            audit["episodes"].append(current)
        except (KeyError, TypeError, ValueError) as exc:
            audit["reason_codes"].append(str(exc))
    main = next((item for item in audit["episodes"] if item["id"] == selection.get("main_episode_id")), None)
    if selection.get("main_episode_id") and main is None:
        audit["reason_codes"].append("selected_main_episode_unavailable")
    # A partially stale declaration set needs explicit review, rather than a
    # silently reduced timing denominator or a substituted main episode.
    audit["accepted"] = not audit["reason_codes"]
    context = {"timezone": window.timezone}
    if audit["accepted"]:
        context.update(primary_sleep_stream=source["stream_key"], main_sleep_episode=main,
            sleep_episodes=[{**item, "source_record_id": item["id"]} for item in audit["episodes"]])
    else:
        audit["episodes"] = []
    metrics = {}
    for identity in METRICS:
        relevant = [row for row in _observations(records, window)
                    if audit["accepted"] and stream_key(row) == tuple(source["stream_key"])]
        if main and identity in {"STATE-SLEEP-MAIN", "STATE-SLEEP-STAGE"}:
            relevant = [row for row in relevant if row["_source_id"] in main["source_revisions"]]
        metric = evaluate(identity, relevant, cutoff_time=window.cutoff_time,
            window_start=window.start, window_end=window.end, context=context)
        metric["sleep_selection_binding"] = audit
        metric["limitations"] = list(dict.fromkeys(metric["limitations"] + [
            "Episode boundaries and attribution dates are explicit user declarations; recorded coverage does not establish a complete night."]))
        if not audit["accepted"]:
            metric.update(value=None, data_status="insufficient")
            metric["reason_codes"] = list(dict.fromkeys(metric["reason_codes"] + audit["reason_codes"]))
        metrics[identity] = metric
    return metrics, audit
