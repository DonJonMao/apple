"""Small calendar summaries of visible observations, without a full analysis run.

This presentation aggregation is not a new scientific metric, health score or
recommendation. Canonical evaluators retain their original identities below.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from zoneinfo import ZoneInfo

from healthzip.db.temporal_schema import samples_as_of
from healthzip.science import evaluate
from healthzip.science.contracts import finite, instant
from healthzip.science.observations import evaluate as evaluate_observation
from healthzip.science.state import local_date_domain, stream_key
from healthzip.training.service import TrainingService

from .cache import WORKSPACE_CACHE_SECONDS, cached, revision_identity
from .workouts import _nonnegative, _recorded_energy, _totals

SUMMARY_VERSION = "workspace-calendar-summary-1.0.0"
_DOMAINS = {
    "心率 / HRV": ("heart",), "睡眠": ("sleep",), "运动": ("workout",),
    "体重 / 有氧": ("body",), "力量": ("strength",), "周期": ("cycle",),
}
_ALL = ("heart", "sleep", "workout", "body", "strength", "cycle")
_COMPOSITE = {"导入与总览", "数据质量", "分析", "报告"}
_TYPES = {
    "heart": ("resting_heart_rate_bpm", "hrv_sdnn_ms"), "sleep": ("sleep_stage",),
    "body": ("body_mass_kg", "vo2_max_ml_kg_min"), "cycle": ("menstrual_flow",),
}
_MISSING = "缺少记录保持未知；有记录日期不代表完整采集覆盖。"


class _RevisionChanged(RuntimeError):
    pass


def _source(key, output):
    return output["_source_labels"].get(tuple(key), "来源未注明")


def _source_labels(rows):
    groups = defaultdict(set)
    for row in rows:
        key = stream_key(row)
        name = key[0] or "来源未注明"
        if str(name).startswith("unknown_source:"):
            name = "来源未注明"
        groups[name].add(key)
    return {key: str(name) if len(keys) == 1 else f"{name}（来源 {index}）"
            for name, keys in groups.items()
            for index, key in enumerate(sorted(keys, key=lambda value: tuple(str(part) for part in value)), 1)}


def _calendar(cutoff, zone):
    local = cutoff.astimezone(zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return [("week", "本周", midnight - timedelta(days=local.weekday())),
            ("month", "本月", midnight.replace(day=1))]


def _adapt(rows, table):
    output = []
    for original in rows:
        row = dict(original)
        row.update(record_kind=table, raw_id=row["id"], id=f"{table}:{row['id']}")
        row["source_name"] = row.get("source_name") or row.get("source_bundle_id") or row.get("source")
        row["event_end"] = row.get("end_utc") or row.get("measured_at") or row.get("observed_at")
        row["event_start"] = row.get("start_utc") or row["event_end"]
        output.append(row)
    return output


def _numeric_fact(label, items, unit, key, metric, *, value_key="value", id_key="source_ids", source_label):
    """Summarize equal-weight daily points (or explicitly labelled observations)."""
    points = sorted((point for point in items if finite(point.get(value_key)) is not None),
                    key=lambda point: (point["date"], point.get("observed_at") or point.get("event_end") or ""))
    numbers = [float(point[value_key]) for point in points]
    dates = sorted({point["date"] for point in points})
    ids = sorted({identifier for point in points for identifier in point.get(id_key, []) if identifier is not None})
    statistics = {"mean": mean(numbers), "minimum": min(numbers), "maximum": max(numbers),
                  "first": numbers[0], "last": numbers[-1],
                  "first_to_last_change": numbers[-1] - numbers[0] if len(numbers) > 1 else None,
                  "point_count": len(points)}
    return {"label": label, "value": statistics["mean"], "unit": unit,
            "source": source_label, "source_identity": list(key),
            "sample_count": sum(point.get("n", len(point.get(id_key, []))) for point in points),
            "observed_days": len(dates), "dates": dates, "source_record_ids": ids,
            "statistics": statistics, "metric_id": metric["metric_id"],
            "metric_algorithm_version": metric["algorithm_version"],
            "data_status": metric["data_status"], "evidence_status": metric["evidence_status"],
            "limitations": metric.get("limitations", []), "aggregation": "equal_weight_recorded_daily_values"}


def _number(value):
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _daily_summary(records, output, identity, label, unit, *, positive=False):
    metric = evaluate(identity, records, **output["_evaluation"])
    output["metrics"][identity] = metric
    for items in (metric["value"] or {}).values():
        points = [point for point in items if finite(point.get("value")) is not None
                  and (not positive or point["value"] > 0)]
        if not points:
            continue
        fact = _numeric_fact(label, points, unit, tuple(points[0]["protocol"]), metric,
                             source_label=_source(tuple(points[0]["protocol"]), output))
        output["facts"].append(fact)
        stats = fact["statistics"]
        text = (f"{fact['source']}：{fact['observed_days']} 个有效日期的{label}日值，"
                f"平均 {_number(stats['mean'])} {unit}，范围 {_number(stats['minimum'])}–{_number(stats['maximum'])} {unit}。")
        if identity == "BODY-MASS-DAILY" and len(points) > 1:
            text += f"本期末次与首次日值相差 {stats['first_to_last_change']:+.1f} kg。"
        output["conclusions"].append(text)


def _sleep_summary(records, output):
    bounds = output["_evaluation"]
    first, last = instant(bounds["window_start"]), instant(bounds["window_end"])
    positive = []
    for row in records:
        try:
            if max(instant(row["event_start"]), first) < min(instant(row["event_end"]), last):
                positive.append(row)
        except ValueError:
            continue
    records = positive
    metric = evaluate("REPORT-STATE-SUMMARY", records, **output["_evaluation"])
    output["metrics"][metric["metric_id"]] = metric
    identities = {row["id"]: stream_key(row) for row in records}
    grouped = defaultdict(list)
    for point in metric.get("daily_facts", []):
        if point.get("series_id") != "observed_sleep_by_wake_date" or not (finite(point.get("value")) or 0) > 0:
            continue
        key = next((identities[identifier] for identifier in point["source_record_ids"] if identifier in identities), None)
        if key is not None:
            grouped[key].append({**point, "value": point["value"] / 60})
    for key, points in grouped.items():
        fact = _numeric_fact("已观察睡眠", points, "小时", key, metric, id_key="source_record_ids",
                             source_label=_source(key, output))
        fact["limitations"] = ["按睡眠片段结束日期归属；窗口边界裁剪且同来源重叠时段只计一次。",
                               "已观察时长不证明完整主睡眠；零时长与缺失日期不纳入均值。"]
        output["facts"].append(fact)
        stats = fact["statistics"]
        output["conclusions"].append(
            f"{fact['source']}：{fact['observed_days']} 个有效结束日期的已观察睡眠，"
            f"平均 {_number(stats['mean'])} 小时，范围 {_number(stats['minimum'])}–{_number(stats['maximum'])} 小时；仅统计正时长记录。")
    output["limitations"].append("睡眠缺失与零时长不填为 0，不据此推断佩戴情况或没有睡眠。")


def _observation_summary(records, output, identity, zone):
    metric = evaluate_observation(identity, records, **output["_evaluation"])
    output["metrics"][identity] = metric
    for stream in (metric["value"] or {}).get("streams", []):
        key = (stream["source_name"], stream["device"], stream["protocol_id"], stream["source_version"])
        points = [{**point, "date": instant(point["observed_at"]).astimezone(zone).date().isoformat(),
                   "source_ids": [point["source_record_id"]]} for point in stream["observations"]]
        if identity == "OBS-VO2-REPORTED":
            fact = _numeric_fact("来源报告 VO₂max", points, metric["unit"], key, metric,
                                 source_label=_source(key, output))
            fact["aggregation"] = "equal_weight_source_observations"
            output["facts"].append(fact)
            stats = fact["statistics"]
            output["conclusions"].append(
                f"{fact['source']}：记录了 {len(points)} 次来源报告 VO₂max，"
                f"平均 {_number(stats['mean'])}、范围 {_number(stats['minimum'])}–{_number(stats['maximum'])} {fact['unit']}；测量方法与个人误差尚未核验。")
        else:
            dates = sorted({point["date"] for point in points})
            output["facts"].append({"label": "月经类别原始记录", "value": len(points), "unit": "条",
                "source": _source(key, output), "source_identity": list(key), "sample_count": len(points),
                "observed_days": len(dates), "dates": dates, "source_record_ids": [point["source_record_id"] for point in points],
                "observations": points, "metric_id": identity, "metric_algorithm_version": metric["algorithm_version"],
                "limitations": ["原始类别保持原值，记录条数不等于出血天数或周期数。"]})
            output["conclusions"].append(
                f"{_source(key, output)}：{len(dates)} 个日期有 {len(points)} 条月经类别原始记录；记录条数不代表出血天数或周期数。")


def _workout_summary(records, output, start, cutoff, zone):
    groups = defaultdict(list)
    for row in records:
        when = instant(row["start_utc"])
        if not start <= when < cutoff or instant(row["end_utc"]) > cutoff:
            continue
        energy, _, _ = _recorded_energy(row, [])
        groups[stream_key(row)].append({"date": when.astimezone(zone).date().isoformat(), "id": row["id"],
            "duration_seconds": _nonnegative(row.get("duration_seconds")), "energy_kcal": energy,
            "suspected_duplicate": bool(row.get("suspected_duplicate"))})
    for key, rows in groups.items():
        totals = _totals(rows)
        dates = sorted({row["date"] for row in rows})
        common = {"source": _source(key, output), "source_identity": list(key), "sample_count": len(rows),
                  "observed_days": len(dates), "dates": dates, "source_record_ids": sorted(row["id"] for row in rows),
                  "limitations": ["运动按开始日期归属；只累计已记录时长和 Workout 本身总能量字段，缺失不补值。"]}
        output["facts"].extend([{**common, "label": "运动记录", "value": len(rows), "unit": "次"},
            {**common, "label": "已记录运动时长", "value": totals["duration_seconds"] / 60 if totals["duration_seconds"] is not None else None, "unit": "分钟",
             "missing_count": totals["missing_duration_count"]},
            {**common, "label": "Workout 报告能量", "value": totals["energy_kcal"], "unit": "kcal",
             "missing_count": totals["missing_energy_count"]}])
        duration = f"已记录时长合计 {_number(totals['duration_seconds'] / 60)} 分钟" if totals["duration_seconds"] is not None else "时长未记录"
        energy = f"Workout 报告能量合计 {_number(totals['energy_kcal'])} kcal" if totals["energy_kcal"] is not None else "Workout 总能量未记录"
        output["conclusions"].append(f"{_source(key, output)}：{len(dates)} 个日期有 {len(rows)} 次运动记录，{duration}，{energy}。")
        if totals["missing_duration_count"] or totals["missing_energy_count"]:
            output["limitations"].append(f"{_source(key, output)}：{totals['missing_duration_count']} 次运动缺少时长，{totals['missing_energy_count']} 次缺少可用于此摘要的总能量；合计只覆盖已知字段。")
        if totals["suspected_duplicate_count"]:
            output["limitations"].append(f"{_source(key, output)}：有 {totals['suspected_duplicate_count']} 条疑似重复记录，未经确认未擅自删除。")
    output["limitations"].append("设备报告能量不等于真实代谢或全天总能量；未与日常活动能量重复相加。附属运动统计没有独立可见修订，不纳入此截止时点摘要。")


def _strength_summary(rows, output, start, cutoff, zone):
    valid = [row for row in rows if row.get("completion_state") == "completed" and not row.get("conflicted")
             and not row.get("deleted_at") and not row.get("session_deleted_at")
             and row.get("ended_at") and start <= instant(row["ended_at"]) < cutoff]
    if not valid:
        return
    dates = sorted({instant(row["ended_at"]).astimezone(zone).date().isoformat() for row in valid})
    sessions = {row["session_id"] for row in valid}
    exercises = {row.get("session_exercise_id") for row in valid} - {None}
    common = {"source": "本地力量训练记录", "sample_count": len(valid), "observed_days": len(dates),
              "dates": dates, "source_record_ids": sorted(f"strength_set:{row['set_uuid']}" for row in valid),
              "limitations": ["只统计有实际结束时间、无冲突且未删除的完成组；热身与工作组按原类型保留。",
                               "涉及场次不等于整场已完成或已完整记录；未按跨动作、单位或负荷口径计算容量。"]}
    output["facts"].extend([{**common, "label": "已完成实际组", "value": len(valid), "unit": "组"},
        {**common, "label": "有完成组的训练场次", "value": len(sessions), "unit": "场"},
        {**common, "label": "有完成组的动作实例", "value": len(exercises), "unit": "个"}])
    output["conclusions"].append(f"力量训练：{len(dates)} 个日期记录了 {len(valid)} 个完成组，涉及 {len(sessions)} 场训练、{len(exercises)} 个动作实例；草稿、跳过与删除记录未计入。")


def _compute(repo, service, domains, cutoff, zone):
    periods = _calendar(cutoff, zone)
    earliest = min(instant(item[2]) for item in periods)
    types = sorted({canonical for domain in domains for canonical in _TYPES.get(domain, ())})
    records, source_counts = [], {}
    if types and earliest < cutoff:
        for table in ("health_sample", "body_measurement"):
            if table == "body_measurement" and "body" not in domains:
                continue
            selected = samples_as_of(repo, cutoff.isoformat(), table, window_start=earliest.isoformat(),
                window_end=cutoff.isoformat(), canonical_types=types if table == "health_sample" else ["body_mass_kg"])
            records.extend(_adapt(selected, table))
            source_counts[table] = len(selected)
    workouts = (_adapt(samples_as_of(repo, cutoff.isoformat(), "workout", window_start=earliest.isoformat(),
                window_end=cutoff.isoformat()), "workout") if "workout" in domains and earliest < cutoff else [])
    strength = service.history_as_of(cutoff_time=cutoff.isoformat(), window_start=earliest.isoformat(),
               window_end=cutoff.isoformat()) if "strength" in domains and earliest < cutoff else []
    labels = _source_labels(records + workouts)
    output = []
    for period, label, local_start in periods:
        start = instant(local_start)
        item = {"period": period, "label": label,
                "window": {"start": start.isoformat(), "end": cutoff.isoformat(), "closure": "[start,end)", "partial": True},
                "conclusions": [], "facts": [], "metrics": {}, "limitations": [_MISSING],
                "_source_labels": labels,
                "coverage": {"observed_days": 0, "window_days": len(local_date_domain(start, cutoff, zone.key)), "record_count": 0}}
        if start < cutoff:
            item["_evaluation"] = {"cutoff_time": cutoff.isoformat(), "window_start": start.isoformat(),
                                   "window_end": cutoff.isoformat(), "context": {"timezone": zone.key}}
            if "heart" in domains:
                _daily_summary(records, item, "STATE-RHR", "静息心率", "bpm")
                _daily_summary(records, item, "STATE-SDNN", "HRV（SDNN）", "ms")
                item["limitations"].append("来源、设备、协议与版本分别统计；SDNN 不等于 RMSSD。日内优先原主记录，否则取日中位数，再对有效日等权汇总。")
            if "sleep" in domains:
                _sleep_summary([row for row in records if row.get("canonical_type") == "sleep_stage"], item)
            if "body" in domains:
                _daily_summary(records, item, "BODY-MASS-DAILY", "体重", "kg", positive=True)
                _observation_summary(records, item, "OBS-VO2-REPORTED", zone)
                item["limitations"].append("仅使用本期可见体重与 VO₂max 记录；窗口外历史体重不计作本期。来源分组不证明测量可比性。")
            if "cycle" in domains:
                _observation_summary(records, item, "OBS-CYCLE-RECORDS", zone)
                item["limitations"].append("不推断周期阶段、排卵、生理状态或训练处方；缺少类别记录不等于没有月经。")
            if "workout" in domains:
                _workout_summary(workouts, item, start, cutoff, zone)
            if "strength" in domains:
                _strength_summary(strength, item, start, cutoff, zone)
            item.pop("_evaluation")
        item.pop("_source_labels")
        if not item["conclusions"]:
            item["conclusions"] = [f"{label}截至当前暂无可用于此工作区摘要的有效记录；可继续查看历史或记录新的数据。"]
        dates = {day for fact in item["facts"] for day in fact.get("dates", [])}
        ids = {identifier for fact in item["facts"] for identifier in fact.get("source_record_ids", [])}
        item["coverage"].update(observed_days=len(dates), record_count=len(ids))
        item["limitations"] = list(dict.fromkeys(item["limitations"] + [text for fact in item["facts"] for text in fact.get("limitations", [])]))
        output.append(item)
    return output, {"source_rows_returned": source_counts, "workout_rows_returned": len(workouts),
                    "training_rows_returned": len(strength), "window_start": earliest.isoformat(),
                    "full_analysis": False, "bounded_by_current_calendar_windows": True}


def workspace_summary(repo, workspace, timezone_name="Asia/Shanghai", cutoff_time=None):
    """Return cached local week/month conclusions; never persist or freeze a run.

    Read the dependency baseline before business records and verify after both
    cache hits and computation. One bounded retry handles concurrent imports or
    edits. No long write transaction or private data leaves this process.
    """
    if workspace not in _DOMAINS and workspace not in _COMPOSITE:
        raise ValueError("unsupported_summary_workspace")
    zone = ZoneInfo(timezone_name)
    cutoff = instant(cutoff_time) if cutoff_time else datetime.now(timezone.utc)
    domains = _DOMAINS.get(workspace, _ALL)
    service = TrainingService(repo)  # cold initialization precedes cache identity
    arguments = {"workspace": workspace, "timezone": timezone_name,
                 "cutoff": cutoff.isoformat() if cutoff_time else cutoff.astimezone(zone).date().isoformat(),
                 "cutoff_mode": "explicit" if cutoff_time else "auto"}
    for _ in range(2):
        baseline = revision_identity(repo)

        def compute():
            periods, plan = _compute(repo, service, domains, cutoff, zone)
            if revision_identity(repo) != baseline:
                raise _RevisionChanged("summary_inputs_changed")
            return {"workspace": workspace, "algorithm_version": SUMMARY_VERSION,
                    "cutoff_time": cutoff.isoformat(), "timezone": timezone_name,
                    "periods": periods, "query_plan": plan,
                    "cache_policy": {"automatic_refresh_seconds": WORKSPACE_CACHE_SECONDS, "revision_invalidated": True,
                                     "storage": "bounded_process_memory", "persistent_writes": False}}

        try:
            value = cached(repo, SUMMARY_VERSION, arguments, compute,
                           max_age_seconds=None if cutoff_time else WORKSPACE_CACHE_SECONDS)
        except _RevisionChanged:
            continue
        if revision_identity(repo) == baseline:
            return value
    raise RuntimeError("workspace_summary_inputs_changed_retry_later")
