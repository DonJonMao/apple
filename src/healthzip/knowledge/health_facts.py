"""Local, program-bound comparison facts and narrowly reviewed measurement context.

These are projections of MetricResult, never a second calculator. Public source
retrieval sees method needs only; personal observations stay in this local layer
and enter optional model requests only through the existing consent boundary.
"""
from __future__ import annotations

from .store import digest, dumps

VERSION = "health-fact-bindings-1"
HEALTH_METRICS = {"STATE-RHR", "STATE-SDNN", "STATE-SLEEP-24H", "STATE-SLEEP-MAIN"}


def comparison_cards(metric):
    comparison = metric.get("comparison") or {}
    cards = []
    for stream in comparison.get("streams", []):
        for period in ("current", "previous", "reference"):
            summary = stream.get(period) or {}
            if summary.get("value") is None:
                continue
            window = summary.get("complete_window") or summary.get("window") or comparison.get("windows", {}).get(period)
            fact = {"metric": metric["metric_id"], "value": summary["value"],
                    "unit": summary.get("unit", metric.get("unit")), "window": window,
                    "statistic_kind": summary.get("statistic_kind"),
                    "recorded_days": summary.get("recorded_days"),
                    "window_days": summary.get("window_days"), "dates": summary.get("dates", []),
                    "algorithm_version": comparison.get("version", metric["algorithm_version"])}
            fact_id = "health-fact:" + digest(dumps([VERSION, stream.get("fact_id"), period, fact]).encode())[:24]
            fact["fact_id"] = fact_id
            labels = {"current": "本期", "previous": "前期", "reference": "此前个人参考"}
            start, end = (window or {}).get("start"), (window or {}).get("end")
            text = (f"{labels[period]}日代表值中位数 {fact['value']:g} {fact['unit']}；"
                    f"范围 {start} 至 {end}（结束不含）；"
                    f"记录 {fact['recorded_days']}/{fact['window_days']} 天。")
            cards.append({"id": fact_id, "title": labels[period] + "具体观察", "status": "computed_observation",
                          "summary": text, "facts": [fact], "window": window,
                          "limitations": list(stream.get("limitations", [])),
                          "allowed_actions": ["核对本期与对照期的记录日期、来源和测量条件"],
                          "source_feature_ids": summary.get("source_record_ids", [])})
        for period, key in (("previous", "previous_change"), ("reference", "reference_change")):
            change = stream.get(key) or {}
            if change.get("absolute") is None:
                continue
            current, prior = stream.get("current", {}), stream.get(period, {})
            fact = {"metric": metric["metric_id"] + ":" + key, "value": change["absolute"],
                    "unit": current.get("unit", metric.get("unit")),
                    "window": {"current": current.get("complete_window") or current.get("window"),
                               period: prior.get("complete_window") or prior.get("window")},
                    "direction": "increase" if change["absolute"] > 0 else "decrease" if change["absolute"] < 0 else "unchanged",
                    "algorithm_version": comparison.get("version", metric["algorithm_version"])}
            fact_id = "health-fact:" + digest(dumps([VERSION, stream.get("fact_id"), key, fact]).encode())[:24]
            fact["fact_id"] = fact_id
            label = "前期" if period == "previous" else "此前个人参考"
            text = f"本期记录较{label}{'高' if fact['value'] > 0 else '低' if fact['value'] < 0 else '相差'} {abs(fact['value']):g} {fact['unit']}。"
            cards.append({"id": fact_id, "title": "具体变化", "status": "computed_observation", "summary": text,
                          "facts": [fact], "window": fact["window"],
                          "limitations": list(stream.get("limitations", [])),
                          "allowed_actions": ["在相近测量条件下继续观察并核对对应记录"]})
    return cards


def measurement_explanations(evidence):
    """Only explicit reviewed use grants can explain measurement with unknown age.

    This does not change the stricter individual/source-explanation permission,
    accept unreviewed text, or let an old frozen release acquire new claims.
    """
    from .metric_retrieval import claim_conflicts

    spans = {s["span_id"]: s for s in evidence.get("evidence_spans", [])}
    output = []
    for claim in evidence.get("matched_claims", []):
        if claim_conflicts(claim, evidence.get('conflicts', [])):
            continue
        if claim.get("scope", {}).get("explanation_purpose") != "measurement_context":
            continue
        selected = [spans[sid] for sid in claim["evidence_span_ids"] if sid in spans]
        if len(selected) != len(claim["evidence_span_ids"]):
            continue
        output.append({"claim_id": claim["claim_id"], "claim_version": claim["claim_version"],
                       "statement": " ".join(claim["statements"]), "scope": claim["scope"],
                       "limitations": claim["limitations"], "evidence_span_ids": claim["evidence_span_ids"],
                       "source_ids": sorted({s["source_id"] for s in selected}),
                       "sources": [{"source_id": s["source_id"], **s["source_metadata"]} for s in selected],
                       "allowed_use": "measurement_context_only", "individual_cause_authority": False})
    return output


def public_method_needs(metric):
    """Bounded generic needs; no dates, values, device names or free text escape."""
    if metric.get("metric_id") not in HEALTH_METRICS or not metric.get("comparison"):
        return []
    streams = metric["comparison"].get("streams", [])
    needs = ["within-person comparison of daily representative values"]
    if len(streams) > 1:
        needs.append("device and recording protocol differences")
    if any((s.get(p) or {}).get("missing_dates") for s in streams for p in ("current", "previous")):
        needs.append("missing days and unequal observation coverage")
    if metric["metric_id"] == "STATE-SDNN":
        needs.append("SDNN is distinct from RMSSD; opportunistic versus standardized sampling")
    return needs


def next_steps(metric):
    comparison = metric.get("comparison") or {}
    streams = comparison.get("streams", [])
    steps = []
    if len(streams) > 1:
        steps.append("分别查看设备、来源与测量情境，比较相似条件下的记录。")
    if any((stream.get(period) or {}).get("missing_dates") for stream in streams for period in ("current", "previous")):
        steps.append("打开记录明细核对缺测日期的跟踪设置和记录覆盖；缺测不补成零。")
    if metric.get("metric_id") == "STATE-SDNN":
        steps.append("核对测量时段与已记录的主动呼吸情境，并结合对应日期的疲劳和训练表现。")
    elif metric.get("metric_id", "").startswith("STATE-SLEEP"):
        steps.append("核对每晚观测起止、所选来源和分期覆盖；区分短记录与已经确认的短睡眠。")
    else:
        steps.append("在相近记录条件下继续观察，并核对变化日期对应的训练与主观记录。")
    return steps[:3]
