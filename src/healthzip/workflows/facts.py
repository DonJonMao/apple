"""Finite factual summaries and predeclared factors over unchanged metric results."""
from healthzip.science import definitions
from healthzip.science.contracts import instant
from healthzip.science.state import local_date_domain


def missing_kind(metric):
    state, reasons = metric["data_status"], " ".join(metric["reason_codes"])
    if state == "not_identifiable":
        return "mathematically_not_identifiable"
    if state in {"conflicted", "incompatible"}:
        return "condition_conflict_or_incomparable"
    if any(word in reasons for word in ("calibration", "measurement_error")):
        return "calibration_missing"
    if any(word in reasons for word in ("authority", "rule", "reviewed_principle")):
        return "action_authority_missing"
    if metric["metric_id"] in {"STR-18", "STR-20", "STR-21", "STR-22", "STR-24"}:
        return "method_not_established"
    if state == "not_applicable":
        return "not_applicable"
    return "input_not_recorded"


def next_step(metric_id, category):
    if category in {"method_not_established", "calibration_missing", "mathematically_not_identifiable"}:
        return {"kind": "review_method_limits", "location": "为什么",
                "fields": [], "text": "查看方法限制；增加普通记录不能自动补足校准或识别条件。"}
    if category == "action_authority_missing":
        return {"kind": "review_authority", "location": "知识工作台", "fields": [],
                "text": "查看该行动是否具有当前有效的规则；用户可继续自主记录训练。"}
    if metric_id.startswith("STATE-SLEEP"):
        return {"kind": "select_sleep", "location": "分析 · 睡眠选择", "fields": ["sleep_selection"],
                "text": "选择实际睡眠来源和已记录片段，再返回此任务重新分析。"}
    if metric_id.startswith("STATE-") and metric_id in {"STATE-PAIN", "STATE-FATIGUE", "STATE-SORENESS"}:
        return {"kind": "record_state", "location": "状态记录", "fields": [metric_id.removeprefix("STATE-").lower()],
                "text": "只补记本次需要的感受、部位与动作影响，未知可留空。"}
    if metric_id.startswith("LOAD-"):
        return {"kind": "record_session", "location": "力量 · 结束训练", "fields": ["session_rpe", "session_rpe_scale", "session_rpe_collected_at", "duration_protocol"],
                "text": "补记整场评分、实际量表与采集时间，并确认计时方式。"}
    if metric_id.startswith("STR-"):
        return {"kind": "review_training", "location": "力量 · 训练记录", "fields": ["reference_set", "rir", "quality_status", "stop_reason", "condition"],
                "text": "查看所选动作的具体缺项；参考组需在执行前指定，事后选择保留回顾身份。"}
    return {"kind": "review_source", "location": "导入与历史记录", "fields": ["source", "device", "protocol"],
            "text": "核对导入记录、来源与协议；继续同来源观察，不填补缺日。"}


def describe(metrics):
    names = definitions(include_observations=True)
    facts, missing = [], []
    for metric_id, metric in metrics.items():
        ref = {"metric_id": metric_id, "title": names[metric_id]["title"], "unit": metric["unit"],
               "source_record_ids": metric["source_record_ids"], "reason_codes": metric["reason_codes"],
               "data_status": metric["data_status"], "evidence_status": metric["evidence_status"]}
        if metric["value"] is not None and metric["data_status"] in {"valid", "partial"}:
            kind = "bounded_research_output" if metric["evidence_status"] in {"research_only", "simulation_only", "model_conditional"} else "recorded_or_deterministic_description"
            facts.append({**ref, "kind": kind})
        else:
            category = missing_kind(metric)
            missing.append({**ref, "kind": category, "next_step": next_step(metric_id, category)})
    return facts, missing


def factors(metrics):
    specs = (
        ("task_conditions", "任务条件改变", ("STR-11", "STR-29"), "按动作、器械、ROM、侧别和协议核对，分开不可比序列。"),
        ("unobserved_opportunity", "进阶机会与努力记录", ("STR-23", "STR-10"), "核对已记录的 RIR、停止原因及参考协议；仅缺失时补记，不要求做到力竭。"),
        ("plan_execution", "计划执行变化", ("STR-09",), "核对原计划与完成、跳过和未知组。"),
        ("within_session", "同场条件", ("STR-15",), "核对组位次、负荷、休息和实际质量。"),
        ("sleep_state", "睡眠与状态背景变化", ("STATE-SLEEP-24H", "STATE-RHR", "STATE-SDNN", "STATE-PAIN", "STATE-FATIGUE"), "补录或选择实际来源；单次或不完整睡眠不能证明变化，训练后状态不能解释训练前决策。"),
        ("body_mass", "体重背景", ("BODY-MASS-DAILY", "BODY-MASS-TREND"), "核对同来源体重和绝对表现，分子分母分别看。"),
    )
    result = []
    for identity, title, mids, next_step in specs:
        observed = [mid for mid in mids if mid in metrics and metrics[mid]["value"] is not None
                    and metrics[mid]["data_status"] in {"valid", "partial"}]
        support, against = [], []
        if identity == "task_conditions" and "STR-11" in observed:
            rows = metrics["STR-11"]["value"]
            keys = {row.get("condition_key") for row in rows}
            if len(keys - {None}) > 1:
                support.append("multiple_recorded_conditions")
            coverage = (metrics.get("STR-29", {}).get("value") or {})
            if len(rows) >= 2 and None not in keys and len(keys) == 1 and coverage.get("protocol_complete_references") == len(rows):
                against.append("same_complete_declared_task_conditions")
        if identity == "unobserved_opportunity" and "STR-23" in observed:
            for item in metrics["STR-23"]["value"]:
                if item["observation"] == "capacity_unobserved":
                    support.append(item["set_id"])
                elif item["observation"] == "volitional_failure":
                    against.append(item["set_id"])
                elif item["observation"] == "submaximal_reference":
                    against.append({"record_id": item["set_id"], "observation": "submaximal_reference",
                        "meaning": "known_RIR_and_effort_protocol_not_missing_effort"})
        if identity == "plan_execution" and "STR-09" in observed:
            value = metrics["STR-09"]["value"]
            if value["skipped"]:
                support.append("explicitly_skipped_plan_sets")
            if value["planned"] and value["completed"] == value["planned"]:
                against.append("all_original_plan_sets_completed")
        if identity == "within_session" and "STR-15" in observed:
            rows = metrics["STR-15"]["value"]
            for row in rows:
                if row["delta_reps"] != 0:
                    support.append(row["set_id"])
            groups = {}
            for row in rows:
                groups.setdefault(row["session_id"], []).append(row)
            for sid, group in groups.items():
                if len(group) > 1 and all(row["delta_reps"] == 0 for row in group):
                    against.append("unchanged_recorded_reps_in_session:" + str(sid))
        if identity in {"body_mass", "sleep_state"}:
            for mid in observed:
                if mid not in {"BODY-MASS-DAILY", "STATE-RHR", "STATE-SDNN"}:
                    continue
                for key, points in metrics[mid]["value"].items():
                    if len(points) < 2 or not all(points[0]["protocol"]):
                        continue
                    # Exact recorded difference, not a physiological threshold.
                    if points[-1]["value"] != points[0]["value"]:
                        support.append(mid + ":" + key)
                    else:
                        against.append(mid + ":unchanged_endpoints:" + key)
        status = "conflicting" if support and against else "assessed_consistent" if support else "weakened" if against else "unassessable"
        result.append({"hypothesis_id": identity, "version": "factual-factors-1.6.0", "title": title,
            "status": status, "metric_refs": observed, "support": support, "counterevidence": against,
            "unknown": [{"metric_id": mid, "reason_codes": metrics.get(mid, {}).get("reason_codes", ["metric_not_in_scope"])}
                        for mid in mids if mid not in observed] + ([{"reason_codes": ["submaximal_reference_does_not_directly_measure_capacity_limit"]}]
                            if identity == "unobserved_opportunity" and any(isinstance(row, dict) for row in against) else []),
            "predicate_identity": "exact_record_comparisons_not_causal_validation",
            "required_evidence": "record_identity_and_comparability_for_facts; separate_claim_for_mechanism",
            "allowed_statement": "当前观察与该因素相容或削弱；尚未确定其影响。",
            "forbidden_statement": "该因素导致表现变化、具体因果概率或自动负荷调整",
            "next_step": next_step, "limitation": "仅组织观察与待核对因素，不确认原因或分配概率。"})
    return result


def vo2_segments(metric):
    output = []
    for stream in (metric.get("value") or {}).get("streams", []):
        points = stream["observations"]
        identity_known = all(stream.get(key) for key in ("source_name", "device", "protocol_id", "source_version"))
        output.append({"source_name": stream["source_name"], "device": stream["device"],
            "protocol_id": stream["protocol_id"], "source_version": stream["source_version"],
            "record_ids": [p["source_record_id"] for p in points], "n": len(points),
            "first_at": points[0]["observed_at"], "last_at": points[-1]["observed_at"],
            "recorded_difference": points[-1]["value"] - points[0]["value"] if identity_known and len(points) > 1 else None,
            "unit": metric["unit"], "comparability": "same_declared_identity_only" if identity_known else "unknown",
            "limitation": "记录值差异不代表已验证的生理变化；同源分组不证明测量准确。"})
    return output


def energy_coverage(metric):
    window = metric["window"]
    denominator = len(local_date_domain(instant(window["start"]),
                      min(instant(window["end"]), instant(metric["cutoff_time"])), window["timezone"]))
    return [{"stream": value["stream"], "complete_days": value["complete_days"], "window_days": denominator,
             "mean_kcal_per_complete_day": value["valid_day_mean_kcal_day"],
             "definition": "mean_of_recorded_complete_days_only_not_full_window_expenditure"}
            for value in metric.get("value") or []]


def pretraining_factors(contexts):
    """Temporal record comparisons; source explanations are attached separately.

    The most recent recorded daily value before each training is selected without
    a hidden freshness threshold. Its actual date and unknown currency stay visible.
    Sleep compares only observed minutes from the same known source/protocol.
    """
    results = []
    for mid, identity, title in (
        ("STATE-SLEEP-24H", "sleep_state", "训练前已观察睡眠"),
        ("STATE-RHR", "rhr_state", "训练前静息心率记录"),
        ("STATE-SDNN", "sdnn_state", "训练前 SDNN 记录"),
        ("BODY-MASS-DAILY", "body_mass", "训练前体重记录"),
    ):
        observations, unknown = [], []
        for ctx in contexts:
            metric = ctx["metrics"][mid]
            value = metric["value"]
            base = {"reference_record_id": ctx["reference_record_id"], "training_started_at": ctx["training_started_at"],
                    "metric_id": mid, "window": metric["window"], "unit": metric["unit"]}
            if value is None:
                unknown.append({**base, "reason_codes": metric["reason_codes"]})
                continue
            if mid == "STATE-SLEEP-24H":
                streams = ctx.get("sleep_streams", [])
                protocol = streams[0] if len(streams) == 1 else []
                observations.append({**base, "value": value["observed_minutes"], "protocol": protocol,
                    "source_record_ids": metric["source_record_ids"], "observed_at": ctx["training_started_at"],
                    "complete": value["complete_episode"]})
                unknown.append({**base, "reason_codes": ["actual_sleep_completeness_and_quality_unknown"]})
            else:
                for points in value.values():
                    if points:
                        last = points[-1]
                        observations.append({**base, "value": last["value"], "protocol": last["protocol"],
                            "source_record_ids": last["source_ids"], "observed_at": last["date"],
                            "current_at_training": "unknown"})
                unknown.append({**base, "reason_codes": ["latest_record_is_not_a_measurement_at_training_start"]})
        comparisons, support, against = [], [], []
        anchors = {}
        for item in observations:
            protocol = tuple(item["protocol"])
            if not protocol or not all(protocol):
                unknown.append({"reference_record_id": item["reference_record_id"], "reason_codes": ["source_or_protocol_unknown"]})
                continue
            if protocol not in anchors:
                anchors[protocol] = item
                continue
            first = anchors[protocol]
            # Reuse of one old observation does not prove stable physiology.
            if item["source_record_ids"] == first["source_record_ids"]:
                unknown.append({"reference_record_id": item["reference_record_id"], "reason_codes": ["no_new_background_observation"]})
                continue
            delta = item["value"] - first["value"]
            comparison = {"from_reference_id": first["reference_record_id"], "to_reference_id": item["reference_record_id"],
                "first_observed_at": first["observed_at"], "later_observed_at": item["observed_at"],
                "difference": delta, "unit": item["unit"], "protocol": list(protocol),
                "source_record_ids": list(dict.fromkeys(first["source_record_ids"] + item["source_record_ids"]))}
            comparisons.append(comparison)
            (support if delta != 0 else against).append(comparison)
        results.append({"hypothesis_id": identity, "version": "pretraining-factors-1.6.1", "title": title,
            "status": "conflicting" if support and against else "assessed_consistent" if support else "weakened" if against else "unassessable",
            "metric_refs": [mid], "support": support, "counterevidence": against, "unknown": unknown,
            "observations": observations, "comparisons": comparisons,
            "fact_scope": "each_actual_training_start", "predicate_identity": "exact_record_comparisons_not_causal_validation",
            "required_evidence": "record_comparability; separate_reviewed_claim_for_explanation",
            "allowed_statement": "训练前已记录分量发生变化或未变；影响尚未确认。",
            "forbidden_statement": "该因素导致停滞或可换算为训练重量",
            "next_step": "核对所列日期、来源与协议；仅补影响本次判断的缺项。",
            "limitation": "变化与未变均仅指记录；睡眠完整性、测量误差、未测生活因素及因果影响仍未知。"})
    return results


def attach_evidence(hypotheses, knowledge):
    """Bind the exact reviewed metric relation, never turn a citation into a cause."""
    for hypothesis in hypotheses:
        relevant = [q for q in knowledge["queries"] if q["metric_id"] in hypothesis["metric_refs"]]
        hypothesis["source_claim_refs"] = [{"claim_id": c["claim_id"], "version": c["claim_version"],
            "metric_id": q["metric_id"], "relation": c["metric_relation"], "statements": c["statements"],
            "evidence_span_ids": c["evidence_span_ids"], "scope": c["scope"], "limitations": c["limitations"],
            "use": "measurement_or_method_explanation_not_personal_cause"}
            for q in relevant if q.get("permissions", {}).get("source_explanation") for c in q.get("claims", [])]
        hypothesis["source_explanation_available"] = bool(hypothesis["source_claim_refs"])
        hypothesis["evidence_conflicts"] = [c for q in relevant for c in q.get("conflicts", [])]
        hypothesis.setdefault("unknown", [])
        if not hypothesis["source_explanation_available"]:
            hypothesis["unknown"].append({"reason_codes": ["no_applicable_reviewed_explanation_for_this_factor"]})
    return hypotheses
