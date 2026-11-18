"""Automatic current training presentation; all calculations stay in services."""
import sqlite3

import streamlit as st

from healthzip.training.current import (
    current_advice,
    equipment_loads,
    objective_comparison,
    save_equipment_loads,
)
from healthzip.workflows import load_run
from healthzip.workflows.presentation import metric_lines

STATUS_LABELS = {"completed": "已完成", "aborted": "已中止", "failed": "失败",
                 "skipped": "已跳过", "draft": "草稿", "in_progress": "进行中",
                 "deleted": "已删除", "paused": "已暂停"}
HISTORY_LIMITS = {
    "recorded_sets_do_not_establish_complete_session_coverage": "已记录组不代表整场训练的完整覆盖。",
    "historical_performance_is_observation_not_current_capacity": "历史表现是当时的观察，不等于今天的能力。",
    "unknown_occurrence_time_cannot_order_all_history": "部分实际记录的发生时间未知，无法可靠排序全部历史。",
    "latest_session_time_tied_no_unique_latest": "多场训练的发生时间相同，暂不能唯一确定最近一次。",
    "legacy_inventory_does_not_establish_asof_history": "已有旧记录，但其可见时间或条件无法确认；不能据此宣称当时已知。",
    "deleted_actuals_excluded_history_retained": "已删除的实际记录不参与最近一次选择；历史身份仍保留。",
    "latest_session_not_completed": "最近一次训练尚未完成或已中止，不作为完整完成的训练。",
    "latest_session_contains_unfinished_records": "最近一次训练包含尚未完成的组。",
    "some_latest_records_not_physically_comparable": "最近一次的部分组与当前动作条件不能直接比较。",
}

REASON_LABELS = {
    "no_personal_exercise_observation": "暂无该动作的个人实际记录。",
    "comparable_reference_and_user_plan_required": "此计算需要可比实际记录及明确计划。",
    "completed_work_set_with_positive_observed_repetitions_required": "此计算只使用已完成且有正次数的工作组；其他组仍保留事实。",
    "source_record_deleted": "该实际组已删除，不用于计算。",
    "source_observation_time_unknown": "实际发生时间未知，不能用于这项数值计算。",
    "history_occurrence_order_unknown": "部分实际记录不能可靠排序，暂不给数值。",
    "equipment_step_unit_ambiguous_across_observations": "历史记录存在不同单位，器械档位不能直接混算。",
    "target_and_observation_load_units_differ": "本组目标与历史记录的重量单位不同。",
    "explicit_equipment_step_unit_required": "尚未明确器械档位的单位。",
    "equipment_and_observation_load_units_differ": "器械档位与历史实际的单位不一致。",
    "relevant_observation_conflicted": "相关记录存在尚未解决的修订冲突。",
    "plan_upper_target_or_effort_or_quality_not_met": "尚未满足该组的计划上沿、余力或质量条件。",
    "no_available_equipment_step": "没有符合这项安排的实际可用档位。",
    "reviewed_applicable_progression_principle_required": "缺少已审核且适用于当前条件的进阶规则。",
    "reviewed_principles_missing": "缺少适用的已审核行动规则。",
    "positive_integer_plan_repetition_upper_required": "此计算需要明确的正整数目标次数上限。",
    "positive_integer_next_repetition_target_required": "此计算需要明确的正整数目标次数。",
    "positive_integer_target_lower_than_reference_reps_required": "较难档位试验需要明确低于该历史组次数的目标。",
    "explicit_positive_integer_user_repetition_upper_target_required": "次数试验需要用户明确的正整数目标上限。",
    "target_rir_unspecified_not_effort_matched": "目标 RIR 未指定，不能声称余力匹配。",
    "latest_body_pain_report_requires_current_review": "相关部位最近一次明确疼痛自评需要当前复核。",
    "latest_body_pain_report_unknown": "相关部位最近一次疼痛自评不明确。",
    "pain_reported": "相关实际记录包含疼痛。",
    "quality_restricted": "相关实际记录包含动作质量限制。",
    "stop_reason_restricted": "相关实际记录因疼痛或技术等限制停止。",
}


def _reason_messages(reasons):
    return [REASON_LABELS.get(reason, reason) for reason in reasons]

LABELS = {"double_progression": "按原计划上沿核对进阶", "heavier_lower_reps": "更难档位与较低次数的可选方案",
          "repetition_progression": "同负荷的次数进阶选项"}


def _shown(value, missing="未记录"):
    return missing if value is None or value == "" else str(value)


def _observation_text(row):
    condition = row.get("condition") or {}
    load = _shown(row.get("load_value"))
    unit = _shown(row.get("load_unit"), "单位未知")
    rir = row.get("rir_interval") if row.get("rir_interval") is not None else row.get("rir")
    status = "已删除" if row.get("deleted_at") else STATUS_LABELS.get(row.get("completion_state"), _shown(row.get("completion_state")))
    detail = (f"{load} {unit} × {_shown(row.get('reps'))} 次；RIR {_shown(rir)}；"
              f"{status}；组类型 {_shown(row.get('set_type'))}；"
              f"负荷口径 {_shown(row.get('load_basis') or condition.get('load_basis'))}")
    if row.get("quality_status") is not None:
        detail += f"；质量 {row['quality_status']}"
    if row.get("pain_flag") is not None:
        detail += "；疼痛 " + ("有" if row["pain_flag"] else "明确无")
    if row.get("stop_reason"):
        detail += f"；停止原因 {row['stop_reason']}"
    return detail


def _render_daily_history(result):
    history = result.get("daily_history")
    if history is None:
        return
    st.markdown("##### 最近一次这个动作的实际记录")
    session = history.get("latest_session") or {}
    records = history.get("records") or []
    if not session and not records:
        if history.get("status") in {"no_history", "no_personal_history", "none"}:
            st.info("暂无该动作的个人训练记录。可以正常开始并自由记录。")
        else:
            st.info("已有记录的时间或可比条件不足，暂不能确定最近一次可比较训练；仍可正常记录。")
    else:
        when = session.get("occurred_at") or session.get("started_at") or history.get("occurred_at")
        elapsed = history.get("elapsed_days", session.get("days_since"))
        status = session.get("status") or session.get("session_status")
        st.write(f"最近训练日期：{_shown(when, '时间未知')}；"
                 f"会话状态：{STATUS_LABELS.get(status, _shown(status))}。")
        if elapsed is not None:
            st.caption(f"距本次建议截止 {elapsed:g} 天。")
        st.caption("以下保留这场训练的全部已记录组；记录可能不完整，历史表现不等于今天的能力。")
        for index, record in enumerate(records, 1):
            row = record.get("observation", record)
            st.write(f"历史记录 {index}：{_observation_text(row)}。")
            st.caption(f"实际时间 {_shown(row.get('ended_at') or row.get('started_at'), '时间未知')}。")
    for limitation in history.get("limitations", []):
        st.info(HISTORY_LIMITS.get(str(limitation), str(limitation)))
    if history.get("unranked_records"):
        with st.expander("发生时间未知的实际记录"):
            for record in history["unranked_records"]:
                st.write(_observation_text(record))
            st.caption("这些事实保留原值，不能借用录入或导入时间排列训练先后。")
    if history.get("unresolved_inventory"):
        with st.expander("可见性或条件未知的旧记录"):
            for record in history["unresolved_inventory"]:
                st.write(_observation_text(record))
            st.caption("保留已有事实及缺项；这些记录不冒充可重放的练前依据。")
    if history.get("older_sessions"):
        with st.expander("更早的同动作训练记录"):
            for older in history["older_sessions"]:
                st.write(f"日期 {_shown(older.get('occurred_at'))}；"
                         f"状态 {STATUS_LABELS.get(older.get('status'), _shown(older.get('status')))}。")
                for record in older.get("records", []):
                    st.write(_observation_text(record))
            st.caption("更早记录仅用于有日期的表现回顾，不替代最近一次事实。")
    recent = result.get("recent_training") or history.get("recent_training") or []
    with st.expander("近期同部位训练背景"):
        if not recent:
            st.caption("近期没有可见的相关训练记录；没有记录不代表没有训练。")
        for entry in recent:
            st.write(f"{_shown(entry.get('occurred_at') or entry.get('started_at'), '时间未知')} · "
                     f"{_shown(entry.get('exercise_name') or entry.get('exercise_id'), '动作身份见记录')}。")
            for record in entry.get("records", [entry["record"]] if entry.get("record") else []):
                st.write(_observation_text(record))
        st.caption("相关部位的其他动作只作为背景，不换算成本动作的重量。")


def _render_daily_decisions(result):
    decisions = result.get("daily_decisions") or {}
    if not decisions:
        return
    with st.expander("每组记录的用途、适用性与缺项"):
        for record in decisions.get("records", []):
            st.write("历史组", record.get("set_uuid"), "用途", record.get("uses") or record.get("role") or record.get("status"))
            if record.get("applicability") is not None:
                st.write("适用性核对", record["applicability"])
            for evaluation in record.get("evaluations", []):
                metric = evaluation.get("metric") or {}
                st.write(LABELS.get(evaluation.get("strategy"), evaluation.get("strategy")),
                         _reason_messages(metric.get("reason_codes", evaluation.get("limitations", []))))
                if metric.get("candidate_applicability") is not None:
                    st.write("质量、疼痛及当前观察核对", metric["candidate_applicability"])
        for limitation in decisions.get("limitations", []):
            st.write(limitation)


def render_current_training(repo, instance, *, source_report_id=None):
    st.markdown("#### 本次训练建议与实际记录")
    settings = equipment_loads(repo, instance)
    with st.expander("本动作的器械档位（保存后复用）"):
        text = st.text_input("实际可用档位（逗号分隔，与记录口径一致）",
            value=",".join(str(v) for v in settings["available_loads"]), key="current_loads_" + instance["id"])
        planned_units = {(row.get("planned") or {}).get("load_unit") for row in instance.get("sets", [])
                         if (row.get("planned") or {}).get("load_unit")}
        known_unit = settings.get("load_unit") or (next(iter(planned_units)) if len(planned_units) == 1 else None)
        unit_options = [None, "kg", "lb", "level", "stack_level"]
        if known_unit not in unit_options:
            unit_options.append(known_unit)
        load_unit = st.selectbox("档位单位（未知可留空）", unit_options,
            index=unit_options.index(known_unit), format_func=lambda unit: "未知" if unit is None else unit,
            key="current_load_unit_" + instance["id"])
        st.caption("档位及单位是器械事实；数值建议还需要适用的行动规则和个人记录。")
        if st.button("保存本动作档位", key="current_loads_save_" + instance["id"]):
            try:
                save_equipment_loads(repo, instance["id"], [x.strip() for x in text.split(",") if x.strip()],
                                     load_unit=load_unit)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    try:
        result = current_advice(repo, instance["id"],
            context_id=st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve())),
            window_days=int(st.session_state.get("analysis_window_days", 30)),
            timezone_name=st.session_state.get("analysis_timezone", "Asia/Shanghai"), source_report_id=source_report_id)
        st.caption(f"本次建议的数据截止：{result['created_at']}。目标与实际记录分别保存。")
        _render_daily_history(result)
        _render_daily_decisions(result)
        for excluded in result.get("reference_exclusions", []) if "daily_history" not in result else []:
            observed = excluded["observation"]
            retained = excluded.get("retained_reference")
            st.info(f"{observed['ended_at']}：{excluded['reason']}。" + (
                f"本次保留的参考来自 {retained['ended_at']}：{retained['load_value']} {retained['load_unit']} × {retained['reps']} 次，RIR {retained['rir']}。"
                if retained else "尚无合规参考。"))
        if result.get("status") in {"session_ended", "ended", "unavailable"}:
            st.info("这场训练已结束，当前没有待开始建议；原建议可在历史中查看。")
            return
        review = load_run(repo, result["review_run_id"])
        body = result.get("body") or {}
        if restriction := review["supplements"].get("context_restriction"):
            st.warning(restriction["limitation"])
        with st.expander("当前身体背景：睡眠、心率、SDNN、体重与自评", expanded=True):
            for report in result.get("dated_symptom_observations", []):
                pain = {"reported": "有疼痛或不适，需按当前情况复核", "denied": "明确没有", "unknown": "不确定"}.get(report.get("pain"), "未知")
                st.write(f"最近可见的疼痛自评：{report['observed_at']}；{pain}；"
                         f"部位 {_shown(report.get('muscle') or report.get('location'), '未限定')}。")
            if result.get("dated_symptom_observations"):
                st.caption("自评保留其原日期与范围；不设自动失效天数，不把过去报告当成已经确认的今天状态。同刻记录并列保留。")
            for mid in ("STATE-SLEEP-24H", "STATE-RHR", "STATE-SDNN", "BODY-MASS-DAILY", "STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN"):
                metric = body.get("metrics", {}).get(mid)
                if metric:
                    st.markdown("\n".join(metric_lines(metric)))
        available = 0
        history_order = {record.get("set_uuid"): number for number, record in
                         enumerate((result.get("daily_history") or {}).get("records", []), 1)}
        for index, group in enumerate(result["groups"], 1):
            for option in group["options"]:
                if option["load"] is None:
                    continue
                available += 1
                source_id = option["basis"].get("source_set_id")
                source_label = f"根据历史记录 {history_order.get(source_id, '详情所列组')} 给出的单组可选试验；" if source_id else ""
                st.write(f"待开始目标组 {index}：{source_label}{LABELS[option['strategy']]}；"
                         f"{option['load']} {option['load_unit']} × {option['reps']} 次；"
                         f"目标 RIR {option['rir'] if option['rir'] is not None else '未指定'}。")
                st.caption(option["basis"]["weight_origin"] + "；" + option["basis"]["repetitions_origin"] + "；" + option["basis"]["rir_origin"])
                with st.expander(f"目标组 {index} · {LABELS[option['strategy']]}的依据" + (f" · {source_id}" if source_id else "")):
                    observed = option["basis"].get("source_observation")
                    if source_id:
                        st.write("这项单组选择所用的实际记录", source_id)
                        st.caption("此选项只适用于所列待开始组的一次可选安排；不能推导整场所有组都应加重。")
                    else:
                        st.write("历史专项参考记录", option["basis"].get("reference_set_id"))
                        observed = option["basis"].get("reference_observation")
                    if observed:
                        st.write(f"来源日期 {_shown(observed.get('ended_at') or observed.get('started_at'))}；"
                                 f"动作 {_shown(observed.get('exercise_name'))}；{_observation_text(observed)}。")
                    st.write("用户计划范围与 RIR", option["basis"]["plan"])
                    st.write("实际器械档位及来源", result["settings"])
                    for rule in option["basis"]["rules"]:
                        st.write("策略依据", rule.get("application_logic") or rule.get("permitted_actions"))
                        st.write("来源与版本", rule.get("rule_id", rule.get("theory_id")), rule["version"], rule["evidence_spans"])
                    st.write(option["limitations"])
        if not available:
            st.info("当前尚未形成获许可的数值选项。你可以继续原计划或自由记录实际训练；下方列出本次具体缺项。")
        for message in result["unknown"]:
            st.info(message)
        with st.expander("近期表现、长期复核与具体缺项"):
            from healthzip.workflows.reports import markdown
            st.markdown("\n".join(markdown([review], repo=repo)))
            for group in result["groups"]:
                for option in group["options"]:
                    if option["load"] is None:
                        st.write(LABELS[option["strategy"]], _reason_messages(option["metric"]["reason_codes"]))
                        st.write("规则适用缺项", option["excluded_rules"])
        with st.expander("建议版本与原计划详情"):
            st.json(result)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        if str(exc).startswith("current_training_session_ended"):
            st.info("这场训练已结束，当前没有待开始建议；原建议可在历史中查看。")
        else:
            st.warning(f"本次建议待更新：{exc}。仍可保存实际训练；再次打开本次训练时会重新核对。")
    render_objective_comparison(repo, instance["id"])


def render_objective_comparison(repo, instance_id):
    try:
        comparison = objective_comparison(repo, instance_id)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        st.warning(f"客观对照待更新：{exc}。实际训练记录不受影响。")
        return
    labels = {"record_removed": "记录已删除，保留历史版本", "no_actual_record": "尚无实际记录",
              "linked_objectively": "已按本次任务和组关联", "ambiguous": "对应建议存在歧义",
              "no_prior_applicable_advice": "没有可唯一关联的练前建议"}
    st.caption("实际记录自动对照；这不表示采纳、拒绝、执行或效果。")
    if (comparison.get("session_state") or {}).get("deleted_at"):
        st.warning("所属训练已删除，当前对照及统计排除此训练；以下保留记录身份。")
    for index, row in enumerate(comparison["rows"], 1):
        actual = row["actual"]
        st.write(f"组 {index}：{labels[row['status']]}")
        if row["status"] not in {"no_actual_record", "record_removed"}:
            st.write(f"实际 {actual['load_value']} {actual['load_unit']} × {actual['reps']} 次；"
                     f"RIR {actual['rir'] if actual['rir'] is not None else '未记录'}；时间 {actual['ended_at'] or actual['started_at']}。")
            if row["frozen_group"]:
                for option in row["frozen_group"]["options"]:
                    if option["load"] is not None:
                        st.caption(f"此前可选方案：{option['load']} {option['load_unit']} × {option['reps']} 次；"
                                   "实际不同只表示记录不同，不推断你的选择或训练效果。")
            comparisons = row.get("daily_comparisons")
            if comparisons is not None:
                for historical_index, historical in enumerate(comparisons, 1):
                    observed = historical.get("observation") or {}
                    st.write(f"冻结的历史记录 {historical_index}：{_observation_text(observed)}。")
                    _render_comparison_metrics(historical.get("metrics", {}))
                    for limitation in historical.get("limitations", []):
                        st.caption(str(limitation))
                if len(comparisons) > 1:
                    st.caption("历史组分别并列展示；没有按表现接近程度选择代表组。")
            else:
                _render_comparison_metrics(row.get("reference_comparison", {}))
    with st.expander("客观对照的版本与身份详情"):
        st.json(comparison)


def _render_comparison_metrics(metrics):
    for mid, metric in metrics.items():
        value = metric.get("value") or {}
        if mid == "STR-12" and value.get("delta_reps") is not None:
            st.write(f"与这条同条件、同负荷历史记录相比，次数变化 {value['delta_reps']:+g} 次；"
                     f"历史 RIR {value.get('rir_before')}，本次 RIR {value.get('rir_after')}。")
        elif mid == "STR-14" and value.get("delta_rir") is not None:
            st.write(f"同负荷、同次数的记录 RIR 变化 {value['delta_rir']:+g}；自报变化不等于确定的能力提升。")
