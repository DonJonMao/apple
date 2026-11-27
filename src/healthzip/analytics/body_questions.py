"""Local, question-specific timelines from the same visible records as the body detail."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from statistics import median
from zoneinfo import ZoneInfo

from healthzip.normalize import normalize_value
from healthzip.science.body_catalog import METRIC_CATALOG
from healthzip.science.calendar_trend import fit_daily
from healthzip.science.contracts import Window, canonical_hash, instant
from healthzip.science.semantics import flatten_record, load_components
from healthzip.science.state import comparison_windows, observed_sleep_episodes
from healthzip.training.daily_history import daily_identity
from healthzip.training.sequence_review import compare_work_sets
from healthzip.training.service import TrainingService

from .alternate_observations import alternate_dependencies, alternate_rows
from .body_metrics import _daily_summary, _metadata, _points, _rows
from .cache import cached
from .question_context import (
    EVIDENCE_CONTEXT_VERSION,
    action_metric_dependencies,
    action_observations,
    describe_subjective,
    event_training_context,
    evidence_observations,
    subjective_rows,
    visible_goal_actions,
)

VERSION = "body-questions-1.5"
GUIDANCE_VERSION = "question-guidance-1.2"

QUESTIONS = {
    "W1": ("同动作的完成表现怎样变化？", ("body_mass_kg", "sleep_stage")),
    "W2": (
        "哪些训练之后有睡眠或疲劳记录？",
        ("sleep_stage", "resting_heart_rate_bpm", "hrv_sdnn_ms"),
    ),
    "W3": (
        "同类运动与心肺估计是否一致？",
        (
            "walking_heart_rate_bpm",
            "heart_rate_recovery_1m",
            "vo2_max_ml_kg_min",
            "six_minute_walk_m",
        ),
    ),
    "W4": ("所选期间的可比表现和身体轨迹如何？", ("body_mass_kg", "resting_heart_rate_bpm")),
    "W5": (
        "体重与绝对表现如何变化？",
        (
            "body_mass_kg",
            "body_fat_fraction",
            "lean_body_mass_kg",
            "active_energy_kcal",
            "basal_energy_kcal",
            "dietary_energy_kcal",
        ),
    ),
    "W6": (
        "睡眠时长与随后同条件 SDNN 有怎样的关系？",
        ("sleep_stage", "hrv_sdnn_ms", "daylight_minutes"),
    ),
    "W7": (
        "走得少了，还是相近条件下走得慢了？",
        (
            "steps",
            "walking_speed_m_s",
            "walking_step_length_m",
            "walking_asymmetry_fraction",
            "six_minute_walk_m",
            "stair_ascent_m_s",
            "stair_descent_m_s",
        ),
    ),
    "W8": (
        "已记录的周期或症状与哪些训练相邻？",
        tuple(k for k, v in METRIC_CATALOG.items() if v["workflow"] == "W8"),
    ),
    "E": (
        "本期设备报告了哪些事件？",
        tuple(k for k, v in METRIC_CATALOG.items() if v["workflow"] == "E"),
    ),
}


for _qid, (_title, _fields) in tuple(QUESTIONS.items()):
    QUESTIONS[_qid] = (
        _title,
        tuple(
            dict.fromkeys(
                (
                    *_fields,
                    *(field for field, spec in METRIC_CATALOG.items() if spec["workflow"] == _qid),
                )
            )
        ),
    )


def relative_load_observations(sets, weights, timezone_name):
    """Same-date scale observations recorded no later than the actual work set."""
    zone = ZoneInfo(timezone_name)
    pairs = []
    indexed = defaultdict(list)
    for key, points in weights.items():
        for p in points:
            for obs in p["observations"]:
                indexed[p["date"]].append((key, obs))
    for s in sets:
        at = instant(s["ended_at"])
        total = load_components(s).get("total_load_kg")
        if total is None or s.get("set_type") != "work" or s.get("reps") is None:
            continue
        candidates = defaultdict(list)
        for source, obs in indexed[at.astimezone(zone).date().isoformat()]:
            if obs["value"] > 0 and instant(obs["end"]) <= at:
                candidates[source].append(obs)
        for source, items in candidates.items():
            m = max(items, key=lambda x: instant(x["end"]))
            pairs.append(
                {
                    "type": "relative_load",
                    "exercise": s.get("exercise_name") or s.get("exercise_id"),
                    "date": s["ended_at"],
                    "session_id": s["session_id"],
                    "set_id": s.get("set_uuid"),
                    "reps": s["reps"],
                    "position": s.get("set_number"),
                    "load_kg": total,
                    "mass_kg": m["value"],
                    "mass_measured_at": m["end"],
                    "scale_source": source[0],
                    "mass_source_record_id": m["source_record_id"],
                    "load_per_kg": total / m["value"],
                    "identity": "recorded_external_load_per_measured_body_mass",
                }
            )
    return pairs


def sleep_training_pairs(episodes, sessions, *, start, end):
    """Return both event orders independently. A 24 h display window is explicit."""
    delivered = {"before_training": [], "after_training": []}
    for s in sessions:
        if not s.get("started_at") or not start <= instant(s["started_at"]) < end:
            continue
        at = instant(s["started_at"])
        stop = instant(s["ended_at"]) if s.get("ended_at") else None
        entries = {
            "before_training": sorted(
                (e for e in episodes if at - timedelta(hours=24) <= instant(e["event_end"]) <= at),
                key=lambda e: e["event_end"],
            ),
            "after_training": sorted(
                (
                    e
                    for e in episodes
                    if stop and stop <= instant(e["event_start"]) < stop + timedelta(hours=24)
                ),
                key=lambda e: e["event_start"],
            ),
        }
        for direction, items in entries.items():
            delivered[direction].append(
                {
                    "session_id": s.get("id", s.get("session_id")),
                    "started_at": s["started_at"],
                    "ended_at": s.get("ended_at"),
                    "direction": direction,
                    "matches": [
                        {
                            k: e[k]
                            for k in ("episode_id", "event_start", "event_end", "value", "protocol")
                        }
                        for e in items
                    ],
                    "unmatched_reason": None
                    if items
                    else "训练结束时间未知"
                    if direction == "after_training" and not stop
                    else "前后 24 小时所选范围内未见该方向睡眠",
                }
            )
    return delivered


def sleep_sdnn_associations(episodes, points, *, timezone_name):
    zone = ZoneInfo(timezone_name)
    pairs, unmatched = defaultdict(list), []
    by_day = defaultdict(list)
    for e in episodes:
        by_day[e["date"]].append(e)
    for stream, days in points.items():
        if not stream[1] or not stream[2]:
            unmatched.extend({"date": p["date"], "reason": "设备或测量条件未知",
                              "source": stream[0], "device": stream[1], "protocol": stream[2],
                              "value": p["value"], "unit": "ms",
                              "source_record_ids": p.get("source_record_ids", p.get("source_ids", []))}
                             for p in days)
            continue
        for day in days:
            candidates = by_day.get(day["date"], [])
            by_series = defaultdict(list)
            for o in day["observations"]:
                observed = instant(o["start"])
                before = [
                    e for e in candidates if instant(e["event_end"]) <= observed and e["value"] > 0
                ]
                if not before:
                    unmatched.append(
                        {
                            "date": day["date"],
                            "source_record_id": o["source_record_id"],
                            "reason": "同日测量前未见睡眠结束记录",
                        }
                    )
                    continue
                same_source = [e for e in before if e["protocol"][0] == stream[0]]
                if same_source:
                    before = same_source
                elif len({tuple(e["protocol"]) for e in before}) > 1:
                    unmatched.append(
                        {
                            "date": day["date"],
                            "source_record_id": o["source_record_id"],
                            "reason": "可选睡眠来源不唯一",
                        }
                    )
                    continue
                for sleep_source in {tuple(e["protocol"]) for e in before}:
                    last = max(
                        (e for e in before if tuple(e["protocol"]) == sleep_source),
                        key=lambda e: instant(e["event_end"]),
                    )
                    by_series[(sleep_source, last["episode_id"])].append((last, o))
            for (sleep_source, eid), items in by_series.items():
                ep = items[0][0]
                # Same source plus time-of-day band, defined before fitting. Different
                # periods of waking activity should not silently enter a morning fit.
                slots = defaultdict(list)
                for _, o in items:
                    condition_signature = canonical_hash({name: definition.get("value")
                        for name, definition in o.get("conditions", {}).items()})
                    slots[(instant(o["start"]).astimezone(zone).hour // 6, condition_signature)].append(o)
                for (slot, condition_signature), obs in slots.items():
                    pairs[(stream, sleep_source, slot, condition_signature)].append(
                        {
                            "date": day["date"],
                            "value": median(o["value"] for o in obs),
                            "sleep_hours": ep["value"] / 60,
                            "sleep_end": ep["event_end"],
                            "sdnn_first": min(o["start"] for o in obs),
                            "sdnn_last": max(o["end"] for o in obs),
                            "episode_id": eid,
                            "source_record_ids": [o["source_record_id"] for o in obs],
                            "sampling_times": [
                                {"start": o["start"], "end": o["end"],
                                 "conditions": o.get("conditions", {})} for o in obs
                            ],
                        }
                    )
    fits = []
    for key, series in sorted(pairs.items(), key=lambda item: str(item[0])):
        model = fit_daily(series, "ms", factor="sleep_hours")
        stream, sleep_source, slot, condition_signature = key
        local_times = [instant(t[edge]).astimezone(zone)
                       for p in series for t in p["sampling_times"] for edge in ("start", "end")]
        conditions = defaultdict(list)
        for pair in series:
            for observation in pair["sampling_times"]:
                for name, definition in observation["conditions"].items():
                    value = definition.get("value")
                    if value is not None and value not in conditions[name]:
                        conditions[name].append(value)
        identity = {
            "source": stream[0], "device": stream[1], "protocol": stream[2],
            "source_version": stream[3],
            "measurement_signature": condition_signature,
            "sleep_source": {"source": sleep_source[0], "device": sleep_source[1],
                             "protocol": sleep_source[2], "source_version": sleep_source[3]},
            "known_conditions": dict(conditions), "timezone": timezone_name,
            "time_band": {"start_hour": slot * 6, "end_hour": (slot + 1) * 6,
                          "basis": "product_six_hour_start_time_bucket_not_equivalent_physiology"},
            "actual_local_time_range": [min(t.strftime("%H:%M:%S") for t in local_times),
                                        max(t.strftime("%H:%M:%S") for t in local_times)],
            "date_range": [min(p["date"] for p in series), max(p["date"] for p in series)],
            "paired_dates": len({p["date"] for p in series}), "paired_observations": len(series),
            "sdnn_sample_count": sum(len(p["source_record_ids"]) for p in series),
        }
        adjacent = []
        for left, right in zip(sorted(series, key=lambda p: p["date"]),
                               sorted(series, key=lambda p: p["date"])[1:]):
            adjacent.append({"from_date": left["date"], "to_date": right["date"],
                             "sleep_hours_change": right["sleep_hours"] - left["sleep_hours"],
                             "sdnn_ms_change": right["value"] - left["value"],
                             "identity": "adjacent_description_not_independent_hypothesis_evidence"})
        interval = model.get("interval")
        direction = ("positive" if interval[0] > 0 else "negative" if interval[1] < 0 else "uncertain") if interval else "not_estimable"
        fits.append({**model, "stream": str(key), "group_id": canonical_hash(identity),
                     "identity": identity, "pairs": series, "direction": direction,
                     "neutral_observations": adjacent,
                     "hypothesis": {"status": "exploratory_no_prespecified_direction"}})
    if len(fits) == 1:
        main = {**fits[0]}
    elif len(fits) > 1:
        main = {
            "status": "descriptive_only",
            "reason": "有多个测量条件，按条件分别展示，不挑选最大关联。",
        }
    else:
        main = {
            "status": "descriptive_only",
            "reason": "缺少同条件且先后时间明确的可比睡眠与 SDNN 记录。",
        }
    return {**main, "groups": fits, "unmatched": unmatched}


def _training(repo, start, end, cutoff):
    if not repo.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='training_event'"
    ).fetchone():
        return [], []
    service = TrainingService(repo, initialize=False)
    events = service.events_as_of(
        cutoff_time=cutoff, window_start=start.isoformat(), window_end=end.isoformat(),
        _share_report_readonly=True, _replay_only=True,
    )
    sessions = service.sessions_as_of(cutoff_time=cutoff, _events=events)
    sets = [
        flatten_record(r)
        for r in service.history_as_of(cutoff_time=cutoff, include_incomplete=False, _events=events)
    ]
    return [
        s for s in sessions if s.get("started_at") and start <= instant(s["started_at"]) < end
    ], [
        s
        for s in sets
        if s.get("status") == "completed"
        and s.get("ended_at")
        and start <= instant(s["ended_at"]) < end
    ]


def _strength_rows(sets):
    groups = defaultdict(list)
    for s in sets:
        if s.get("reps") is None or s.get("load_value") is None:
            continue
        identity = daily_identity(s)
        condition = identity["condition_key"] if not identity["reason_codes"] else s.get("set_uuid") or s.get("id")
        groups[
            (
                s.get("exercise_id"),
                condition,
                s.get("set_position"),
                s.get("load_value"),
                s.get("load_basis"),
                s.get("load_unit"),
                s.get("set_type"),
            )
        ].append(s)
    rows = []
    for key, items in groups.items():
        ordered = sorted(items, key=lambda i: instant(i["ended_at"]))
        first, last = ordered[0], ordered[-1]
        identity = daily_identity(last)
        limitations = list(identity["reason_codes"])
        if key[2] is None or not key[6]:
            limitations.append("set_position_or_type_unknown")
        if any(n > 1 for n in Counter(item["session_id"] for item in items).values()):
            limitations.append("duplicate_same_condition_position_in_session_no_unique_pair")
        rows.append(
            {
                "type": "strength",
                "exercise_id": last.get("exercise_id"),
                "condition_key": identity["condition_key"],
                "condition_known": not identity["reason_codes"],
                "condition_limitations": limitations,
                "load_basis": last.get("load_basis"),
                "set_type": last.get("set_type"),
                "exercise": last.get("exercise_name") or last.get("raw_exercise_name") or key[0],
                "position": key[2],
                "load": float(key[3]),
                "unit": last.get("load_unit"),
                "reps": float(last["reps"]),
                "rir": last.get("rir"),
                "date": last["ended_at"],
                "session_id": last["session_id"],
                "record_count": len(items),
                "first_date": first["ended_at"],
                "first_session_id": first["session_id"],
                "first_reps": float(first["reps"]),
                "difference": float(last["reps"]) - float(first["reps"])
                if first["session_id"] != last["session_id"] and not limitations
                else None,
                "comparison_identity": "explicit_first_last_recorded_repetitions_not_period_summary",
                "period_reps_median": median(float(item["reps"]) for item in items),
                "source_record_ids": [item.get("set_uuid") or item.get("id") for item in ordered],
                "rest_seconds": last.get("rest_seconds"),
                "first_rest_seconds": first.get("rest_seconds"),
                "stop_reason": last.get("stop_reason"),
            }
        )
    return sorted(rows, key=lambda x: (str(x["exercise"]), x["position"] or 0, x["date"]))


def _metric_rows(series, fields, *, window=None, comparison_series=None, bounds=None):
    rows = []
    for field in fields:
        for key, values in series.get(field, {}).items():
            if not values:
                continue
            ordered = sorted(values, key=lambda p: instant(p["observed_at"]))
            a, b = ordered[0], ordered[-1]
            item = {
                    "type": "metric",
                    "metric": field,
                    "title": METRIC_CATALOG[field]["title"],
                    "source": key[0],
                    "device": key[1],
                    "protocol": key[2],
                    "source_version": key[3],
                    "date": b["date"],
                    "first_date": a["date"],
                    "days": len({v["date"] for v in values}),
                    "value": b["value"],
                    "first_value": a["value"],
                    "difference": b["value"] - a["value"] if a["date"] != b["date"] else None,
                    "unit": METRIC_CATALOG[field]["unit"],
                    "source_record_ids": b["source_record_ids"],
                    **({
                        "estimate_support": b.get("estimate_support"),
                        "first_estimate_support": a.get("estimate_support"),
                        "estimate_observations": [{**p, "published_at": p["observations"][0].get("published_at")} for p in ordered],
                        "observation_count": len(ordered),
                        "publication_count": sum(p["observations"][0].get("published_at") is not None for p in ordered),
                        "independent_measurement_count": None,
                        "support_limitation": "这是来源发布的估计点；支持窗口重叠或重复发布不能视为独立测试，达到版本报告上限不能据此判定能力停滞。",
                    } if any(p.get("estimate_support") for p in ordered) else {}),
                }
            if window is not None:
                unit = METRIC_CATALOG[field]["unit"]
                all_points = (comparison_series or series).get(field, {}).get(key, values)
                periods = {name: _daily_summary(all_points, limits, window.cutoff_time,
                                               unit, METRIC_CATALOG[field]["kind"])
                           for name, limits in bounds.items() if name in {"current", "previous"}}
                current, previous = periods["current"], periods["previous"]
                item.update(trajectory_first_value=a["value"], trajectory_last_value=b["value"],
                            trajectory_difference=b["value"] - a["value"] if a["date"] != b["date"] else None,
                            trajectory_first_date=a["date"], trajectory_last_date=b["date"],
                            date=current["dates"][-1] if current["dates"] else None,
                            first_date=(previous["dates"][-1] if METRIC_CATALOG[field]["kind"] == "estimate" else previous["dates"][0]) if previous["dates"] else None,
                            current_period={"start": current["window"]["start"], "end": current["window"]["end"]},
                            previous_period={"start": previous["window"]["start"], "end": previous["window"]["end"]},
                            value=current["value"], first_value=previous["value"],
                            difference=current["value"] - previous["value"] if current["value"] is not None and previous["value"] is not None else None,
                            statistic_kind="source_estimate_points" if METRIC_CATALOG[field]["kind"] == "estimate" else "median_of_daily_representatives", comparison=periods,
                            days=current["recorded_days"],
                            source_record_ids=current["source_record_ids"],
                            previous_source_record_ids=previous["source_record_ids"],
                            comparison_identity="body-comparison:" + canonical_hash([field, list(key), unit]))
                if METRIC_CATALOG[field]["kind"] == "estimate":
                    old = previous["estimate_observations"]
                    item.update(estimate_observations=current["estimate_observations"],
                                previous_estimate_observations=old,
                                observation_count=current["record_count"], publication_count=current["publication_count"],
                                first_estimate_support=old[-1]["estimate_support"] if old else None,
                                estimate_support=current["estimate_observations"][-1]["estimate_support"] if current["estimate_observations"] else None)
                item["fact_id"] = "period-observation:" + canonical_hash(item)
            rows.append(item)
    return rows


def _describe_metric(row):
    if row.get("comparison"):
        from .display_format import format_measurement
        def display_number(value, *, signed=False):
            return format_measurement(value, row["unit"], kind=row["metric"], signed=signed)
        value = row["value"]
        statistic = "本期末次来源估计 " if row.get("statistic_kind") == "source_estimate_points" else "本期完整记录日中位数 "
        identity = " / ".join(str(row.get(k) or "未记录") for k in ("source", "device"))
        text = f"{row['title']}（{identity}）{statistic}" + (display_number(value) if value is not None else "尚无")
        if row["difference"] is not None:
            text += "，较前期 " + display_number(row["difference"], signed=True)
        elif row.get("trajectory_difference") is not None:
            text += f"；实际记录轨迹 {row['trajectory_first_date']} {display_number(row['trajectory_first_value'])} → {row['trajectory_last_date']} {display_number(row['trajectory_last_value'])}"
        elif value is None and row.get("trajectory_last_value") is not None:
            text += f"；{row['trajectory_last_date']} 已记录日内代表值 {display_number(row['trajectory_last_value'])}（该日范围不完整，不计入完整日比较）"
        if row.get("statistic_kind") == "source_estimate_points":
            text += f"；{row['observation_count']} 条来源记录，{row['publication_count']} 条明确提供发布时间；支持窗口不作为独立每日测量"
        return text
    return (
        f"{row['title']}，{row['first_date']} 至 {row['date']}从 {row['first_value']:g} 到 {row['value']:g} {row['unit']}"
        if row["difference"] is not None
        else f"{row['date']}记录{row['title']} {row['value']:g} {row['unit']}"
    )


def workout_performance(workouts, hr_series):
    """Actual equal-distance bouts; unknown route/effort remains explicit."""
    groups, output = defaultdict(list), []
    for w in workouts:
        distance, _, _ = normalize_value(
            "HKQuantityTypeIdentifierDistanceWalkingRunning",
            w.get("distance_value"),
            w.get("distance_unit"),
        )
        duration = w.get("duration_seconds")
        if distance is None or distance <= 0 or duration is None or duration <= 0:
            continue
        meta = _metadata(w)
        condition = (
            w.get("source_name"),
            w.get("device"),
            w.get("source_version"),
            w.get("activity_type"),
            meta.get("protocol_id"),
            meta.get("route"),
            distance,
        )
        heart = {}
        for stream, points in hr_series.items():
            values = [
                o["value"]
                for p in points
                for o in p["observations"]
                if w["id"] in (o.get("workout_ids") or ())
            ]
            if values:
                heart[stream] = {"value": median(values), "sample_count": len(values)}
        groups[condition].append({"workout": w, "duration": duration, "heart": heart})
    for key, entries in groups.items():
        entries.sort(key=lambda item: instant(item["workout"]["event_start"]))
        for previous, current in zip(entries, entries[1:]):
            a, b = previous["workout"], current["workout"]
            heart = [
                {
                    "source": s[0],
                    "protocol": s[2],
                    "first_value": previous["heart"][s]["value"],
                    "value": current["heart"][s]["value"],
                    "first_sample_count": previous["heart"][s]["sample_count"],
                    "sample_count": current["heart"][s]["sample_count"],
                }
                for s in previous["heart"].keys() & current["heart"].keys()
            ]
            output.append(
                {
                    "type": "workout_comparison",
                    "title": "同运动类型、同记录距离的实际时长",
                    "source": key[0],
                    "activity": key[3],
                    "distance_m": key[6],
                    "first_date": a["event_start"],
                    "date": b["event_start"],
                    "first_value": previous["duration"] / 60,
                    "value": current["duration"] / 60,
                    "difference": (current["duration"] - previous["duration"]) / 60,
                    "unit": "min",
                    "heart_rate_comparisons": heart,
                    "workout_ids": [a["id"], b["id"]],
                    "known_protocol": key[4],
                    "known_route": key[5],
                    "comparability": "同来源/设备/类型/距离，已知路线和协议分组；未知努力程度不可视为相同负荷。",
                }
            )
    return output


def _topic_status(qid, series, sessions, sets, contexts, workouts, goal, actions, cycle_enabled):
    """Eligibility belongs to the question, before background is attached.

    These are product content requirements, not scientific sample thresholds.
    A partial topic can describe its available dimensions without inventing the
    missing ones. Subjective logs have their own summary in W2.
    """
    present = {field for field in QUESTIONS[qid][1]
               if any(points for points in series.get(field, {}).values())}
    primary = set(present)
    if qid == "W1":
        primary.clear()  # Weight and sleep are context for actual work sets.
    elif qid == "W3":
        primary -= {"resting_heart_rate_bpm", "hrv_sdnn_ms", "heart_rate_bpm"}
    elif qid == "W6":
        primary -= {"daylight_minutes", "environmental_audio_dba", "headphone_audio_dba"}
    training = bool(sets or sessions) if qid in {"W1", "W2", "W4"} else bool(workouts) if qid == "W3" else False
    has_primary = bool(primary or training)
    has_goal = bool(goal and goal.get("goal"))
    state = "descriptive" if has_primary else "no_records"
    missing = []
    if qid == "W8" and not has_primary and not cycle_enabled:
        state = "disabled"
    elif qid == "W2":
        if not has_primary and contexts:
            state = "context_only"
        if not training:
            missing.append("同期实际训练")
        missing += [METRIC_CATALOG[k]["title"] for k in ("sleep_stage", "resting_heart_rate_bpm", "hrv_sdnn_ms") if k not in primary]
    elif qid == "W4" and (has_goal or actions):
        state = "descriptive" if has_primary else "partial"
    elif qid == "W6":
        missing += [METRIC_CATALOG[k]["title"] for k in ("sleep_stage", "hrv_sdnn_ms") if k not in primary]
    elif qid == "W7":
        missing += [METRIC_CATALOG[k]["title"] for k in ("steps", "walking_speed_m_s") if k not in primary]
    if has_primary and missing:
        state = "partial"
    refs = {str(identity) for field in primary for points in series.get(field, {}).values()
            for point in points for identity in point.get("source_record_ids", [])}
    return {"state": state, "has_primary_records": has_primary,
            "primary_metrics": sorted(primary), "primary_source_record_ids": sorted(refs),
            "has_training": training, "has_goal": has_goal if qid == "W4" else False,
            "action_count": len(actions or []) if qid == "W4" else 0,
            "background_record_count": len(contexts), "missing_dimensions": missing}


def _render_question(qid, series, sessions, sets, subjective, episodes, workouts, window,
                     *, event_sessions=None, event_sets=None, goal_context=None, action_reviews=None,
                     ordinary_training=None, comparison_series=None, comparison_bounds=None, strength_rows=None,
                     cycle_enabled=False):
    def local_day(at):
        return instant(at).astimezone(ZoneInfo(window.timezone)).date().isoformat()

    title, fields = QUESTIONS[qid]
    contexts = subjective_rows(subjective)
    topic = _topic_status(qid, series, sessions, sets, contexts, workouts, goal_context, action_reviews, cycle_enabled)
    if topic["state"] in {"disabled", "no_records", "context_only"}:
        empty = {
            "W1": "所选期间尚无可见的实际训练记录，可在训练入口记录动作与完成组。",
            "W2": "所选期间尚无训练、睡眠、心率或主观状态记录。",
            "W3": "所选期间尚无相关运动或心肺观测，一般心率背景不能代替运动表现。",
            "W4": "所选期间尚无目标、行动或相关表现记录。",
            "W5": "所选期间尚无体重、体组成或相关能量记录。",
            "W6": "所选期间尚无相关睡眠或生理记录，不能建立睡眠与 SDNN 对照。",
            "W7": "所选期间尚无活动量或步态记录，不能判断步数或步速的变化。",
            "W8": "周期功能已开启，所选期间尚无相关周期记录。" if cycle_enabled else "周期功能未开启，所选期间也没有相关周期记录。",
            "E": "当前导入数据在所选期间未提供相关设备事件；这不表示没有发生事件。",
        }
        observation = empty[qid]
        background = contexts if qid == "W2" else []
        steps = []
        if topic["state"] == "context_only":
            latest = max(contexts, key=lambda r: instant(r["date"]))
            observation = f"{local_day(latest['date'])} 已记录{describe_subjective(latest)}；尚无同期训练、睡眠或心率记录可作对照。"
            steps = ["在身体入口核对同期心率或睡眠是否已经导入；已记录的主观状态继续保留。"]
        return {"id": qid, "title": title, "topic_status": topic,
                "report_status": "not_requested" if topic["state"] == "disabled" else "background_only" if background else "no_records",
                "observation": observation, "rows": background, "steps": steps,
                "support": [], "counterevidence": [], "support_count": 0, "counterevidence_count": 0,
                "association": None, "limitations": [], "training_pairs": None,
                **({"goal_context": goal_context, "action_reviews": action_reviews or []} if qid == "W4" else {}),
                "source_workflow": qid, "window": window.as_dict()}
    rows = _metric_rows(series, fields, window=window if comparison_bounds else None,
                        comparison_series=comparison_series, bounds=comparison_bounds)
    facts = []
    next_step = []
    caveats = []
    association = None
    support, counter = [], []
    pair_rows = None
    strength = strength_rows if strength_rows is not None else _strength_rows(sets) if qid in {"W1", "W2", "W4", "W5"} else []
    if ordinary_training is None and qid in {"W1", "W2", "W4", "W5"}:
        from healthzip.workflows.longitudinal import ordinary_review
        ordinary_training = ordinary_review(sets, window.as_dict())
    if qid in {"W1", "W2"}:
        instances = defaultdict(lambda: defaultdict(list))
        for s in sets:
            if s.get("set_uuid") and s.get("exercise_id") and s.get("session_exercise_id"):
                instances[s["exercise_id"]][(s["session_id"], s["session_exercise_id"])].append(s)
        for exercise, group in instances.items():
            candidates = sorted(
                group.values(), key=lambda ss: min(instant(s["ended_at"]) for s in ss)
            )
            if (
                len(candidates) < 2
                or candidates[-2][0]["session_id"] == candidates[-1][0]["session_id"]
            ):
                continue
            ordered = [sorted(g, key=lambda s: s.get("set_number") or 0) for g in candidates[-2:]]
            pair = compare_work_sets(*ordered)
            facts += pair["observations"]
            for comparison in pair["comparisons"]:
                diff = comparison.get("reps_change")
                if diff is None:
                    continue
                observation = f"同动作第 {comparison['set_number']} 组由 {comparison['previous_reps']} 到 {comparison['current_reps']} 次"
                (support if diff > 0 else counter).append(observation)
            next_step += pair["next_steps"]
            rows.extend(
                {
                    "type": "set_pair",
                    "exercise": exercise,
                    "session_id": ordered[-1][0]["session_id"],
                    **r,
                }
                for r in pair["comparisons"]
            )
    if qid in {"W1", "W4", "W5", "W2"}:
        if qid == "W5":
            facts.extend(_describe_metric(r) for r in rows if r["metric"] == "body_mass_kg")
        facts.extend((ordinary_training or {}).get("summary", [])[:3])
        rows.extend(strength)
    if qid in {"W1", "W2", "W6"}:
        pair_rows = sleep_training_pairs(
            episodes, sessions, start=instant(window.start), end=instant(window.end)
        )
        direction = "after_training" if qid == "W2" else "before_training"
        matched = [p for p in pair_rows[direction] if p["matches"]]
        if matched:
            p = matched[-1]
            e = p["matches"][0]
            facts.append(
                f"{local_day(p['started_at'])}训练{'结束后' if qid == 'W2' else '开始前'}记录了 {e['value'] / 60:.1f} 小时睡眠"
            )
        if qid == "W2":
            checks = []
            if topic["has_training"]:
                checks.append("在训练历史中核对同动作、器械与组位的实际负荷和次数")
            if "sleep_stage" in topic["primary_metrics"]:
                checks.append("在睡眠明细核对已记录睡眠的日期、时长和来源")
            elif matched:
                checks.append("按已匹配的训练后睡眠记录核对实际日期、时长和来源")
            elif topic["has_training"]:
                checks.append("如需对照训练后的睡眠，可记录实际睡眠或核对是否已经导入")
            else:
                names = "、".join(METRIC_CATALOG[field]["title"] for field in topic["primary_metrics"])
                checks.append(f"在身体明细核对已记录的{names}来源和测量时段")
            if any(row.get("fatigue") is not None for row in contexts):
                checks.append("按实际日期对照已填写的疲劳，不将同期记录自动当作训练后的反应")
            else:
                checks.append("如需观察本人疲劳，可填写主观感受与实际时间")
            if not topic["has_training"]:
                checks.append("如需形成训练后对照，先记录实际训练场次")
            next_step.append("；".join(checks) + "。")
    if qid == "W6":
        association = sleep_sdnn_associations(
            episodes, series.get("hrv_sdnn_ms", {}), timezone_name=window.timezone
        )
        if association["status"] == "estimated":
            facts.insert(
                0,
                f"在 {association['n']} 个可比日期，控制时间趋势后，每增加一小时已记录睡眠，随后 SDNN 的模型条件均值相差 {association['coefficient']:+.2f} ms",
            )
        else:
            facts.extend(_describe_metric(r) for r in rows if r["metric"] == "sleep_stage")
        if len(association["groups"]) > 1:
            facts.insert(0, f"共有 {len(association['groups'])} 组不同来源、测量条件或采样时段的配对观察，分别查看各组结果")
        next_step.append("下次保持测量时段和姿势，复查看睡眠结束后相同条件下的 SDNN。")
        caveats.append("作息、呼吸和训练可共同影响两项记录；这里估计条件关联。")
        caveats.append("相邻变化只描述实际记录，不是独立支持票数；SDNN 升降不自动代表恢复好坏，睡眠更长不自动代表质量更好。")
    if qid == "W7":
        facts.extend(
            _describe_metric(r) for r in rows if r["metric"] in {"steps", "walking_speed_m_s"}
        )
        common = defaultdict(list)
        for m in ("steps", "walking_speed_m_s"):
            for source, points in series.get(m, {}).items():
                levels = defaultdict(list)
                for point in points:
                    levels[point["date"]].append(point["value"])
                common[m].append((source, {d: median(v) for d, v in levels.items()}))
        for ss, steps in common["steps"]:
            for vs, speeds in common["walking_speed_m_s"]:
                dates = sorted(steps.keys() & speeds.keys())
                if len(dates) < 2:
                    continue
                first, last = dates[0], dates[-1]
                ds, dv = steps[last] - steps[first], speeds[last] - speeds[first]
                rows.append(
                    {
                        "type": "aligned_activity_and_speed",
                        "first_date": first,
                        "date": last,
                        "common_days": len(dates),
                        "steps_source": ss[0],
                        "speed_source": vs[0],
                        "step_change": ds,
                        "speed_change_m_s": dv,
                    }
                )
                if ds < 0:
                    support.append(f"{first} 至 {last}，共同记录日的步数下降 {abs(ds):g} 步。")
                    if dv >= 0:
                        counter.append(
                            f"相同两天记录步速从 {speeds[first]:g} 到 {speeds[last]:g} m/s，未随步数降低。"
                        )
        if "walking_speed_m_s" in topic["primary_metrics"]:
            next_step.append("下次相同路线、携带位置与近似速度下，核对步态记录，并单独复查当天的活动量。")
        elif any(METRIC_CATALOG[k]["kind"] == "estimate" for k in topic["primary_metrics"]):
            next_step.append("核对已记录来源估计的方法版本、支持窗口和重复发布；如需观察行动后的变化，区分实际记录时点与支持区间。")
        else:
            next_step.append("先核对已有活动量记录的携带方式与覆盖；如需比较步速，可在相同路线另行记录速度。")
        caveats.append(
            "记录量随活动机会改变。舒适步速属于另一项观察；没有速度分层时只描述各自轨迹。"
        )
    if qid == "W3":
        facts.extend(_describe_metric(r) for r in rows[:3])
        comparisons = workout_performance(workouts, series.get("workout_heart_rate_bpm", {}))
        rows += comparisons
        for comparison in comparisons[-2:]:
            text = f"同类型 {comparison['distance_m']:g} 米记录，{local_day(comparison['first_date'])} 到 {local_day(comparison['date'])} 用时从 {comparison['first_value']:g} 到 {comparison['value']:g} 分钟"
            facts.insert(0, text)
            for heart in comparison["heart_rate_comparisons"]:
                (
                    support
                    if comparison["difference"] < 0 and heart["value"] <= heart["first_value"]
                    else counter
                ).append(
                    f"{text}；同期 {heart['source']} 已采样心率中位数从 {heart['first_value']:g} 到 {heart['value']:g} bpm。"
                )
        for w in workouts:
            rows.append(
                {
                    "type": "workout",
                    "date": w["event_start"],
                    "activity": w.get("activity_type"),
                    "duration_seconds": w.get("duration_seconds"),
                    "distance": w.get("distance_value"),
                    "unit": w.get("distance_unit"),
                    "id": w["id"],
                }
            )
        next_step.append("在相近路线、运动类型及负荷下复查实际时长、步行心率或恢复记录。")
        caveats.append("VO₂max、运动能量与部分估计可能共享心率输入，不能独立投票。")
        caveats.append(
            "同距离对照仍需核对路线、努力程度和测量协议；采样心率中位数不是整场时间加权心率。"
        )
    if qid in {"W3", "W7"} and any(r.get("estimate_support") for r in rows):
        caveats.append("低频估计保留每次发布的支持窗口与版本；重叠窗口不是独立测试，版本报告上限处的相同数值不能判断能力停滞。")
    if qid in {"W8", "E"}:
        rows = []
        for field in fields:
            for key, points in series.get(field, {}).items():
                for p in points:
                    for observation in p["observations"]:
                        row = {
                            "type": "event",
                            "title": METRIC_CATALOG[field]["title"],
                            "date": observation["event_end"],
                            "source": key[0],
                            "device": key[1],
                            "protocol": key[2],
                            "source_version": key[3],
                            "category": observation["category"],
                            "event_start": observation["event_start"],
                            "event_end": observation["event_end"],
                            "event_time_precision": observation.get("event_time_precision", "instant"),
                            "value": observation["value"] if METRIC_CATALOG[field]["kind"] != "event" else None,
                            "unit": METRIC_CATALOG[field]["unit"],
                            "source_record_ids": [observation["id"]],
                        }
                        if qid == "W8":
                            row["same_date_sessions"] = [
                                s["id"]
                                for s in sessions
                                if instant(s["started_at"])
                                .astimezone(ZoneInfo(window.timezone))
                                .date()
                                .isoformat()
                                == p["date"]
                            ]
                        rows.append(row)
        if rows:
            newest = max(rows, key=lambda r: instant(r["date"]))
            facts.append(
                f"本期已记录 {len(rows)} 条，最近一次是 {local_day(newest['date'])} 的{newest['title']}"
            )
        links, pairs, unmatched = event_training_context(
            rows + contexts, event_sessions or sessions, event_sets or sets,
            window.timezone, comparisons=qid == "W8")
        rows += links + pairs + unmatched
        if links:
            last = max(links, key=lambda r: instant(r["event_at"]))
            facts.append(f"{local_day(last['event_at'])}{last['event_title']}与{local_day(last['started_at'])}实际训练相邻：{last['temporal_relation']}；训练保留 {len(last['actual_sets'])} 个已完成组")
        for pair in pairs:
            if pair["difference"] is None:
                counter.append(f"{pair['exercise']}第 {pair['set_number']} 组有两次实际记录，但条件或负荷不具备可比性，保留原值。")
            else:
                description = f"{local_day(pair['first_date'])} 与 {local_day(pair['date'])}均有{pair['event_title']}及实际训练；{pair['exercise']}第 {pair['set_number']} 组同条件次数 {pair['first_value']:g} → {pair['value']:g}"
                support.append(description)
                if not any("同条件次数" in f for f in facts):
                    facts.append(description)
        if qid == "E":
            for event in rows:
                if event.get("type") == "event":
                    next_step.append(f"核对 {local_day(event['date'])} {event['source'] or '来源未记'} 的{event['title']}原记录及对应设备说明（记录 {'、'.join(map(str, event['source_record_ids']))}）。")
        else:
            next_step.append("回顾已记录周期事件当天的训练与症状，自主决定是否调整舒适度和安排。")
        caveats.append(
            "没有可见通知时，设备功能、开启状态及风险仍可能未知。"
            if qid == "E"
            else "仅关联实际日志，不按日历推测相位。"
        )
    if qid == "W4":
        facts.extend(_describe_metric(r) for r in rows if r["type"] == "metric")
        if goal_context and goal_context.get("goal"):
            facts.insert(0, f"本次截止时可见目标：{goal_context['title']}；未设独立数值目标时只能复查同口径轨迹")
        if action_reviews:
            last = max(action_reviews, key=lambda r: instant(r["selected_at"]))
            text = last.get("summary") or f"已选行动“{last['action_text']}”：{last['execution_label']}；结果定义未预先记录，保留原观察"
            facts.insert(1, text)
            caveats.append("执行状态来自本人反馈；冻结行动基线与后续记录的差值不能归因为该行动。")
        if action_reviews:
            definitions = {review.get("definition_status") for review in action_reviews}
            if "not_prespecified" in definitions:
                next_step.append("未预先记录主要结果的旧行动，先核对实际执行与原反馈；如需新的复评，先明确主要观察和时间窗，另存新行动定义。")
            if "historical_observation_unit" in definitions:
                next_step.append("观察单位尚未区分的旧行动，保留原基线和已保存复评；先创建关联的新行动定义，再按该指标的观察单位复评。")
            if "prespecified" in definitions:
                next_step.append("对已有预设结果定义的行动，沿用冻结的主要观察和时间窗复评，同时核对实际执行记录；未反馈保持未知。")
        elif goal_context and goal_context.get("goal"):
            next_step.append(f"围绕已选目标“{goal_context['title']}”复查相关记录，沿用相同来源和比较尺度；训练记录还需核对器械与组位。")
        else:
            names = list(dict.fromkeys(r["title"] for r in rows if r["type"] == "metric" and r.get("value") is not None))
            if not names and topic["has_training"]:
                next_step.append("在训练历史中核对已记录场次和完成组，按同动作、器械与组位分别查看负荷、次数和已填 RIR；缺失条件保持未知。如需行动复评，先明确要观察的结果与时间窗。")
            else:
                observed = "、".join(names) or "已有指标"
                next_step.append(f"在{observed}明细中核对本期与前期的来源、日期覆盖和测量条件；如需行动复评，先明确要观察的结果与时间窗。")
    if qid == "W1":
        next_step.append(
            "维持已能完成的同条件负荷，或按本人目标选择下一次次数，并复查同组位的实际完成量。"
        )
    if qid == "W5":
        relatives = relative_load_observations(
            sets, series.get("body_mass_kg", {}), window.timezone
        )
        rows += relatives
        if relatives:
            r = relatives[-1]
            facts.insert(
                1,
                f"实际外部重量 {r['load_kg']:g} kg × {r['reps']} 次，同时段此前称重 {r['mass_kg']:g} kg，记录负荷/体重 {r['load_per_kg']:.3f}",
            )
        for s in strength:
            if s["difference"] == 0:
                counter.append(
                    f"{s['exercise']}第 {s['position']} 组在 {local_day(s['first_date'])} 和 {local_day(s['date'])} 均完成 {s['load']:g} {s['unit']} × {s['reps']:g} 次。"
                )
        next_step.append("下次在相同条件称重，并对照同动作绝对重量与次数。")
        caveats.append("比值受体重这个分母影响；不完整的饮食日志不能推出全天能量缺口。")
    if contexts:
        rows += contexts
        context = max(contexts, key=lambda item: instant(item["date"]))
        state = describe_subjective(context)
        if state:
            facts.insert(1, f"{local_day(context['date'])} 已记录{state}")
    if topic["missing_dimensions"]:
        caveats.append("当前缺少" + "、".join(topic["missing_dimensions"]) + "，仅描述已有维度，不将缺项当作未发生或数值下降。")
    if association and any(g.get("status") == "estimated" for g in association.get("groups", [])):
        topic["state"] = "conditional_association"
    return {
        "id": qid,
        "title": title,
        "topic_status": topic,
        "report_status": "available",
        "observation": "。".join(facts[:4]) + "。"
        if facts
        else "所选期间尚无足以形成该项对照的可见记录。",
        "support": support[:3],
        "counterevidence": counter[:3],
        "support_count": len(support),
        "counterevidence_count": len(counter),
        "steps": list(dict.fromkeys(next_step))[:3],
        "rows": rows,
        "association": association,
        "limitations": caveats,
        "training_pairs": pair_rows,
        "source_workflow": qid,
        **({"ordinary_training": ordinary_training} if qid in {"W1", "W2", "W4", "W5"} else {}),
        **({"goal_context": goal_context, "action_reviews": action_reviews or []} if qid == "W4" else {}),
        "window": window.as_dict(),
    }


def question_views(
    repo, *, window_start, window_end, cutoff_time, timezone_name, source_filter, question_ids,
    period=None, previous=None, cycle_enabled=None,
):
    if cycle_enabled is None:
        from healthzip.ui.preferences import load_preferences
        cycle_enabled = bool(load_preferences(repo.path).get("cycle_enabled"))
    ids = tuple(QUESTIONS if question_ids is None else question_ids)
    fields = sorted({f for q in ids for f in QUESTIONS[q][1]})
    start, end, cutoff = (
        instant(window_start),
        min(instant(window_end), instant(cutoff_time)),
        instant(cutoff_time),
    )
    window = Window(start.isoformat(), end.isoformat(), cutoff.isoformat(), timezone_name)
    if previous is None and period in {"week", "month"}:
        local_start, local_end = start.astimezone(ZoneInfo(timezone_name)), end.astimezone(ZoneInfo(timezone_name))
        prior_start = local_start - timedelta(days=7) if period == "week" else (local_start - timedelta(days=1)).replace(day=1)
        prior_end = local_end - timedelta(days=7) if period == "week" else min(local_start, prior_start + (local_end - local_start))
        previous = {"start": prior_start.isoformat(), "end": prior_end.isoformat()}
    bounds = comparison_windows(window, previous=previous)
    lower = min(start, instant(bounds["previous"]["start"]))
    comparison_window = Window(lower.isoformat(), end.isoformat(), cutoff.isoformat(), timezone_name)
    sources = tuple(sorted(source_filter or ()))
    goal, actions, action_signature = visible_goal_actions(repo, start, end, cutoff) if "W4" in ids else (None, [], None)
    dependency_fields = set(fields) | action_metric_dependencies(actions)
    # Frozen actions can consume a field outside W4's usual body-mass/RHR view.
    # Include supporting sleep observations and all alternate representations.
    if actions:
        dependency_fields.add("sleep_stage")
    deps = [("health_sample", f) for f in dependency_fields] + [
        ("subjective_log", None),
        ("training", None),
        ("workout", None),
        ("body_measurement", "body_mass_kg"),
    ]
    deps += [dep for field in dependency_fields for dep in alternate_dependencies(field)]
    deps += [
        ("body_measurement", f)
        for f in dependency_fields
        if f in {"height_cm", "body_fat_fraction", "lean_body_mass_kg"}
    ]

    def compute():
        # Ordinary heart rate is high-frequency. W3 needs actual workout samples
        # only; use the indexed workout supports rather than loading the year of HR.
        scientific_fields = [
            f for f in fields if f not in {"heart_rate_bpm", "workout_heart_rate_bpm"}
        ]
        workouts = (
            _rows(repo, "workout", None, start, end, cutoff.isoformat(), sources)
            if "W3" in ids
            else []
        )
        health = (
            _rows(repo, "health_sample", scientific_fields, lower, end, cutoff.isoformat(), sources)
            if scientific_fields
            else []
        )
        workout_hrs = {}
        for w in workouts:
            a, b = max(start, instant(w["event_start"])), min(end, instant(w["event_end"]))
            if a >= b:
                continue
            for hr in _rows(
                repo, "health_sample", ["heart_rate_bpm"], a, b, cutoff.isoformat(), sources
            ):
                if a <= instant(hr["event_end"]) < b:
                    obs = workout_hrs.setdefault(hr["id"], {**hr, "workout_ids": []})
                    obs["workout_ids"].append(w["id"])
        health += list(workout_hrs.values())
        for field in set(fields) & {
            "body_mass_kg",
            "height_cm",
            "body_fat_fraction",
            "lean_body_mass_kg",
        }:
            health += _rows(
                repo, "body_measurement", [field], lower, end, cutoff.isoformat(), sources
            )
        for field in fields:
            health += alternate_rows(
                repo, field, lower, end, cutoff.isoformat(), timezone_name, sources, health
            )
        grouped = defaultdict(list)
        for r in health:
            grouped[r.get("canonical_type")].append(r)
        grouped["workout_heart_rate_bpm"] = list(workout_hrs.values())
        support_window = Window(
            (lower - timedelta(hours=24)).isoformat(),
            min(cutoff, end + timedelta(hours=48)).isoformat(),
            cutoff.isoformat(),
            timezone_name,
        )
        sleep_rows = (
            _rows(
                repo,
                "health_sample",
                ["sleep_stage"],
                instant(support_window.start),
                instant(support_window.end),
                cutoff.isoformat(),
                sources,
            )
            if "sleep_stage" in fields
            else []
        )
        episodes = observed_sleep_episodes(sleep_rows, support_window)
        intervals = [
            (instant(i["start"]), instant(i["end"]), e["episode_id"])
            for e in episodes
            for i in e["intervals"]
        ]
        for field in (
            "oxygen_saturation_fraction",
            "respiratory_rate_bpm",
            "sleeping_wrist_temperature_c",
        ):
            for row in grouped.get(field, []):
                row["sleep_episode_ids"] = [
                    eid for a, b, eid in intervals if a <= instant(row["event_end"]) < b
                ]
        comparison_series = {k: _points(k, grouped[k], comparison_window, [], episodes) for k in fields}
        series = {k: {stream: [p for p in values if start <= instant(p.get("allocation_at", p["observed_at"])) < end]
                      for stream, values in streams.items()} for k, streams in comparison_series.items()}
        sessions, sets = _training(repo, start, end, cutoff.isoformat())
        from healthzip.workflows.longitudinal import ordinary_review
        ordinary_training = ordinary_review(sets, window.as_dict()) if any(q in {"W1", "W2", "W4", "W5"} for q in ids) else None
        strength_rows = _strength_rows(sets) if ordinary_training is not None else []
        event_sessions, event_sets = (None, None)
        if any(i in {"E", "W8"} for i in ids):
            event_sessions, event_sets = _training(repo, start - timedelta(hours=24), min(end + timedelta(hours=24), cutoff), cutoff.isoformat())
        subjective = _rows(repo, "subjective_log", None, start, end, cutoff.isoformat(), ())
        goal_context, action_reviews = action_observations(repo, goal, actions, end=end,
            cutoff=cutoff, timezone_name=timezone_name, version=VERSION) if "W4" in ids else (None, [])
        views = [
            _render_question(q, series, sessions, sets, subjective, episodes, workouts, window,
                event_sessions=event_sessions, event_sets=event_sets, goal_context=goal_context,
                action_reviews=action_reviews, ordinary_training=ordinary_training,
                comparison_series=comparison_series, comparison_bounds=bounds, strength_rows=strength_rows,
                cycle_enabled=cycle_enabled)
            for q in ids
        ]
        for v in views:
            if v["id"] == "W1":
                v["evidence_observations"] = evidence_observations(sets, window.as_dict(),
                    cutoff_time=cutoff.isoformat(), source_filter=sources)
                v["cutoff_time"] = cutoff.isoformat()
                v["evidence_context_version"] = EVIDENCE_CONTEXT_VERSION
            v["analysis_version"] = VERSION
            v["guidance_version"] = GUIDANCE_VERSION
            v["source_filter"] = list(sources)
            v["comparison_bounds"] = bounds
            v["period"] = period
            v["sleep_definition"] = "observed_episode_duration_allocated_by_end_local_date"
            v["fact_id"] = "question:" + canonical_hash(
                [str(repo.path.resolve()), cutoff.isoformat(), v]
            )
        return views

    return cached(
        repo,
        VERSION,
        {"ids": ids, "window": window.as_dict(), "sources": sources, "cutoff": cutoff.isoformat(),
         "guidance_version": GUIDANCE_VERSION,
         "question_evidence_context_version": EVIDENCE_CONTEXT_VERSION,
         "visible_goal_actions": action_signature, "comparison_bounds": bounds, "period": period,
         "cycle_enabled": bool(cycle_enabled)},
        compute,
        dependencies=deps,
    )
