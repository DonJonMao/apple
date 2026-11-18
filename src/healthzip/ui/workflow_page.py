"""Task-level UI over persisted workflow runs and existing candidate controls."""

import streamlit as st

from healthzip.training.service import TrainingService
from healthzip.workflows import (
    WorkflowRequest,
    check_current_use,
    load_analysis,
    load_run,
    resume_workflow,
    run_workflow,
    save_context,
)
from healthzip.workflows.contracts import FUNCTION_NAMES, WORKFLOWS

STATUS = {"completed": "已完成核对", "bounded": "已有结果，部分结论受限", "needs_data": "需要记录",
          "needs_review": "需要复核", "not_identifiable": "模型下不可唯一识别", "not_applicable": "不适用"}
FACTOR_STATUS = {"assessed_consistent": "有相容观察", "weakened": "有削弱观察", "conflicting": "观察方向不一致",
                 "unassessable": "尚不能评价", "unsupported": "缺少用途支持"}


def _points(metric):
    value = metric.get("value")
    if metric["metric_id"] in {"STATE-RHR", "STATE-SDNN", "BODY-MASS-DAILY"}:
        return [{"date": point["date"], "value": point["value"], "stream": stream,
                 "record_id": ", ".join(point["source_ids"])}
                for stream, rows in (value or {}).items() for point in rows]
    if metric["metric_id"] == "OBS-VO2-REPORTED":
        return [{"date": point["observed_at"], "value": point["value"],
                 "stream": " / ".join(str(stream.get(k) or "未知") for k in ("source_name", "device", "protocol_id", "source_version")),
                 "record_id": point["source_record_id"]}
                for stream in (value or {}).get("streams", []) for point in stream["observations"]]
    return []


def _plot(points, title, unit, key):
    if not points:
        return
    import plotly.graph_objects as go
    figure = go.Figure()
    for stream in dict.fromkeys(point["stream"] for point in points):
        group = [p for p in points if p["stream"] == stream]
        figure.add_trace(go.Scatter(x=[p["date"] for p in group], y=[p["value"] for p in group],
            mode="markers", name=str(stream), text=[p["record_id"] for p in group],
            hovertemplate="%{x}<br>%{y}<br>记录 %{text}<extra>%{fullData.name}</extra>"))
    figure.update_layout(title=title, xaxis_title="实际记录日期", yaxis_title=unit, showlegend=True)
    st.plotly_chart(figure, use_container_width=True, key=key)
    st.caption("只画已记录的点，缺失日期留空；来源或协议改变时分组，不插值。")


def _metric(metric, title):
    if metric.get("task_results"):
        from healthzip.science.contracts import task_metric_results
        for task in task_metric_results(metric):
            st.caption("独立任务：" + str(task.get("exercise_name") or task["task_id"]) + " · " + str(task.get("condition_key")))
            _metric(task["metric"], title)
        return
    value = metric["value"]
    st.write(title)
    if value is None:
        st.caption("尚无可用结果：" + "；".join(metric["reason_codes"]))
        return
    if metric["metric_id"] == "STATE-SLEEP-24H":
        st.write(f"截止前 24 小时已记录 {value['observed_minutes'] / 60:g} 小时睡眠；完整性未证实。")
    elif metric["metric_id"] == "STR-11":
        st.dataframe(value, hide_index=True)
    elif metric["metric_id"] == "STR-01":
        st.write(f"已记录完成工作组 {value['completed_work_parent_sets']} 组；分段 {value['segments']} 个。")
    elif _points(metric):
        points = _points(metric)
        _plot(points, title, metric["unit"], "workflow_plot_" + metric["metric_id"])
        with st.expander("查看实际日期与记录 · " + title):
            st.dataframe(points, hide_index=True)
    elif metric["metric_id"].startswith("LOAD-"):
        st.dataframe([{"训练": row["session_id"], "整场评分": row["session_rpe"],
            "量表": row["srpe_protocol"], "记录时长（分钟）": row["duration_minutes"],
            "计时方式": row["duration_protocol"], "采集距结束（分钟）": row["actual_collection_delay_minutes"],
            "评分×分钟（AU）": row["AU"]} for row in value], hide_index=True)
        st.caption("不同量表和计时方式分开保留；AU 不表示生理剂量。")
    elif isinstance(value, (int, float, str)):
        st.write(value, metric["unit"])
    else:
        if isinstance(value, list):
            st.dataframe(value, hide_index=True)
        else:
            st.write(value)
    st.caption(f"单位 {metric['unit']} · 数据 {metric['data_status']} · 依据身份 {metric['evidence_status']} · 有效/总数 {metric['valid_n']}/{metric['total_n']}")
    with st.expander("记录来源与限制 · " + title):
        st.write(metric["window"])
        st.write(metric["limitations"])
        st.write(metric["source_record_ids"])
        st.json(metric)


def render_run(repo, result):
    snapshot = load_analysis(repo, result["run_id"])
    metrics = {**snapshot["metrics"], **snapshot["observations"]}
    st.write(result["title"] + " · " + STATUS.get(result["status"], result["status"]))
    st.caption(f"截止 {result['request']['cutoff_time']} · 时区 {result['request']['timezone']} · "
               + ("回顾分析" if result["request"]["mode"] == "retrospective" else "截止前可见记录"))
    source = result["supplements"].get("source_report")
    if source:
        st.caption(f"历史报告截止 {source['cutoff_time']}；历史比较范围 {source['window_start']} 至 {source['window_end']}。"
                   f"当前行动核对 {source['current_action_cutoff_time']}，原报告保持不变。")
    tabs = st.tabs(["发生了什么", "是否可比", "可能因素", "下一步", "为什么", "后来怎样"])
    with tabs[0]:
        _plot(result["supplements"].get("strength_points", []), "同负荷参考组记录", "次", "workflow_strength_points")
        review = result["supplements"].get("long_term_review")
        if review and review["start_long_term_review"]:
            st.info("所选周期出现未超过比较起点的同条件记录，已启动长期复核。这里没有判定生理或统计停滞。")
            for series in review["series"]:
                anchor = series["anchor"]
                st.write(f"参考 {anchor['recorded_load']} {anchor['load_unit']} × {anchor['value']} 次，RIR {anchor['rir'] if anchor['rir'] is not None else '非精确值或未知'}；"
                    f"本序列 {series['n']} 次记录，跨度 {series['span_days']:g} 天。")
                st.dataframe([{"记录": p["record_id"], "实际日期": p["observed_at"], "较起点次数差": p["repetitions_change"],
                               "较起点 RIR 差": p["rir_change"], "比较身份": p["identity"]} for p in series["comparisons"]], hide_index=True)
            st.caption("；".join(review["limitations"]))
        primary = {
            "W1": ("STR-11", "STR-12", "STR-13", "STR-14", "STR-19"),
            "W2": ("STR-01", "STR-05", "STR-06", "LOAD-DURATION", "LOAD-SRPE", "LOAD-SRPE-AU", "STATE-SLEEP-MAIN", "STATE-SLEEP-24H", "STATE-RHR", "STATE-SDNN", "STATE-REFERENCE-MEDIAN", "STATE-DEVIATION", "STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN", "STR-12"),
            "W3": ("OBS-VO2-REPORTED", "STATE-RHR", "STATE-SDNN"),
            "W4": ("STR-11", "STR-12", "STR-19", "BODY-MASS-DAILY", "BODY-MASS-TREND", "STR-09"),
            "W5": ("BODY-MASS-DAILY", "BODY-MASS-TREND", "ENERGY-BASAL", "ENERGY-ACTIVE", "ENERGY-DEVICE-TOTAL"),
        }[result["workflow_id"]]
        if result["workflow_id"] == "W4":
            outcome = result["request"]["result_metric_id"] or ("STR-11" if result["request"]["task_id"] else "BODY-MASS-DAILY")
            primary = (outcome,) + tuple(mid for mid in primary if mid != outcome and mid in metrics)
        from healthzip.science import definitions
        names = definitions(include_observations=True)
        for mid in primary[:3]:
            if mid in metrics:
                _metric(metrics[mid], names[mid]["title"])
        if len(primary) > 3:
            with st.expander("更多分项记录与限制"):
                for mid in primary[3:]:
                    if mid in metrics:
                        _metric(metrics[mid], names[mid]["title"])
        if result["supplements"].get("energy_coverage"):
            for row in result["supplements"]["energy_coverage"]:
                st.write(f"完整能量日 {row['complete_days']}/{row['window_days']}；这些完整日均值 "
                         f"{row['mean_kcal_per_complete_day']} kcal/日。")
                st.caption("缺日不填 0；设备 total=basal+active，不再加 workout 或 TEF。")
        comparison = result["supplements"].get("calendar_comparison")
        if comparison:
            st.write("前两个完整日历周期")
            for period in comparison["periods"]:
                st.write(period["start"] + " 至 " + period["end"] + "（不含终点）")
                if period["metric"]:
                    st.dataframe(_points(period["metric"]) or period["metric"]["value"] or [], hide_index=True)
                    st.caption(f"有效/总数 {period['metric']['valid_n']}/{period['metric']['total_n']}；{period['metric']['data_status']}")
                else:
                    st.caption("这一周期未记录所选任务；不填 0。")
            st.caption("；".join(comparison["limitations"]))
            partial = result["supplements"]["partial_current_period"]
            st.write("本期未结束部分（单列）", partial["start"], partial["cutoff_time"])
            if partial["metric"]:
                st.dataframe(_points(partial["metric"]) or partial["metric"]["value"] or [], hide_index=True)
    with tabs[1]:
        st.write(result["nodes"][2]["limitation"])
        if result["task_selection"]:
            st.write(result["task_selection"])
        if result["supplements"].get("vo2_segments"):
            st.dataframe(result["supplements"]["vo2_segments"], hide_index=True)
        if "STR-29" in metrics:
            st.write(metrics["STR-29"]["value"])
    with tabs[2]:
        if result["supplements"].get("pretraining_contexts"):
            with st.expander("核对当次训练前的背景记录"):
                for context in result["supplements"]["pretraining_contexts"]:
                    st.write("训练开始前：" + context["training_started_at"])
                    for mid, metric in context["metrics"].items():
                        st.write(mid, metric["value"] if metric["value"] is not None else "此前没有可用记录")
                    st.caption("每项只取训练开始之前的事件；可见时间按本次前瞻或回顾模式处理。")
        if result["hypotheses"]:
            for item in result["hypotheses"]:
                st.write(item["title"], FACTOR_STATUS[item["status"]])
                st.write({"支持观察": item["support"], "相反观察": item["counterevidence"]})
                st.write("尚未知", item.get("unknown", []))
                st.caption(item["next_step"] + " " + item["limitation"])
                if item.get("source_claim_refs"):
                    st.write("记录含义与方法的来源解释", item["source_claim_refs"])
                else:
                    st.caption("此项当前仅组织记录事实，尚无匹配的来源解释。")
        else:
            st.write("本流程分别显示记录和测量限制，不从时间先后推断个人原因。")
    with tabs[3]:
        if result["workflow_id"] == "W1":
            st.write("在力量记录中补充参考组、实际 RIR、质量和停止原因；确认目标与本台器械档位后，可在下方核对当前候选。")
        elif result["workflow_id"] in {"W2", "W4"}:
            st.write("缺少哪项就补哪项：训练页记录实际执行与不适；下方选择睡眠来源或继续同协议观察，再生成关联的新分析。")
        elif result["workflow_id"] == "W3":
            st.write("核对来源、设备版本和测量协议，继续记录同条件观测。来源不明时分开保留。")
        else:
            st.write("继续记录同来源体重和设备能量；核对完整日与设备切换。这里不生成热量缺口或饮食处方。")
        with st.expander("本次具体缺项"):
            for item in result["missing"]:
                st.write(item["title"] + "：" + item["next_step"]["text"])
                st.caption("入口：" + item["next_step"]["location"])
        if "main_workspace" in st.session_state:
            def navigate(page):
                st.session_state["main_workspace"] = page
            if any(step["kind"] in {"review_training", "record_state", "record_session"} for step in result["next_steps"]):
                st.button("去力量页补记训练或状态", key="workflow_open_training", on_click=navigate, args=("力量",))
            if any(step["kind"] == "review_source" for step in result["next_steps"]):
                st.button("去核对导入记录", key="workflow_open_import", on_click=navigate, args=("导入与总览",))
    with tabs[4]:
        st.write("事实与来源解释分别核对。资料查询使用固定公共任务，个人数值和备注留在本机。")
        for query in result["knowledge"]["queries"]:
            st.write(query["metric_id"], query["status"])
            for claim in query.get("claims", []):
                st.write("；".join(claim.get("statements", [])) or claim.get("claim_id"))
                st.caption(f"适用范围：{claim.get('scope')}；限制：{claim.get('limitations')}")
            with st.expander("对应版本与定位 · " + query["metric_id"]):
                st.json(query.get("spans", []))
                st.write(query.get("limitations", []))
        if result.get("linked_candidate_bases"):
            from healthzip.ui.recommendation_page import render_candidate_basis
            for basis in result["linked_candidate_bases"]:
                render_candidate_basis(basis)
        if result["knowledge"]["status"] != "checked":
            st.info("本次来源解释未完成：" + "；".join(result["knowledge"].get("reason_codes", [])))
        if "identifiability_model" in result["supplements"]:
            st.write(result["supplements"]["identifiability_model"])
    with tabs[5]:
        for mid in ("STR-27", "STR-28", "REPORT-RECOMMENDATION-FOLLOWUP"):
            if mid in metrics:
                _metric(metrics[mid], mid)
        partial = result["supplements"].get("partial_current_period")
        if partial:
            st.write("本期未结束部分的反馈（与前期分开）")
            st.write(partial.get("followup", {}).get("STR-27", {}).get("value") or "本期尚无反馈")
        st.caption("这些是同一冻结截止时点的反馈。新选择、执行或补录后重新分析；完成任务不证明干预有效。")
    with st.expander("运行审计与下载"):
        import json
        st.json({key: result[key] for key in ("run_id", "parent_run_id", "input_hash", "workflow_version", "analysis_run_id", "nodes")})
        st.download_button("下载本次本地结果", json.dumps({"workflow": result, "snapshot": snapshot}, ensure_ascii=False, indent=2),
                           file_name="healthzip-workflow.json", mime="application/json")


def render_workflows(repo, analysis=None):
    st.subheader("按问题分析")
    wid = st.selectbox("我想查看", list(WORKFLOWS),
        format_func=lambda key: FUNCTION_NAMES[WORKFLOWS[key]["task"]], key="workflow_kind")
    key = "workflow_run_" + str(repo.path.resolve()) + "_" + wid
    service = TrainingService(repo)
    session = instance = selected = None
    if wid == "W1" or wid == "W2" and st.checkbox("与一项训练任务并列查看", key="workflow_recovery_task"):
        page = st.number_input("训练历史页码（每页 50 场）", min_value=1, value=1, key="workflow_session_page")
        sessions = service.list_sessions(limit=50, offset=(int(page)-1)*50)
        by_session = {row["id"]: row for row in sessions}
        if st.session_state.get("workflow_session") not in by_session:
            st.session_state.pop("workflow_session", None)
        sid = st.selectbox("选择训练", list(by_session), index=0 if by_session else None,
            format_func=lambda identity: f"{by_session[identity]['session_date']} · {by_session[identity].get('name') or '训练'}",
            key="workflow_session")
        if sid:
            session = service.get_session(sid)
            by_instance = {row["id"]: row for row in session["exercises"] if not row.get("deleted_at")}
            # Equal display names can preserve Streamlit's widget identity when
            # switching sessions. The old instance UUID is never a new option.
            if st.session_state.get("workflow_exercise") not in by_instance:
                st.session_state.pop("workflow_exercise", None)
            iid = st.selectbox("选择动作", list(by_instance), index=0 if by_instance else None,
                format_func=lambda identity: by_instance[identity]["exercise"].get("name", identity), key="workflow_exercise")
            if iid:
                instance = by_instance[iid]
                targets = service.current_targets(iid)["sets"]
                if st.session_state.get("workflow_set") not in {row["set_uuid"] for row in targets}:
                    st.session_state.pop("workflow_set", None)
                selected = st.selectbox("要复核的目标组", [row["set_uuid"] for row in targets],
                    index=0 if targets else None, key="workflow_set")
    with st.expander("查看范围与已确认信息"):
        days = st.number_input("查看天数", min_value=1, value=int(st.session_state.get("analysis_window_days", 30)), key="workflow_days")
        baseline_days = st.number_input("描述基线/练前背景回看天数（仅限定范围）", min_value=1, value=28, key="workflow_baseline_days")
        period = st.selectbox("时间范围", [None, "week", "month"],
            format_func=lambda value: {None: "按查看天数", "week": "本地日历周", "month": "本地日历月"}[value], key="workflow_period")
        population = st.selectbox("适用人群自报（可留未知）", ["unknown", "adults", "healthy_adults", "trained_adults", "adult_athletes"], key="workflow_population")
        mode = st.selectbox("资料可见时间", ["prospective", "retrospective"],
            format_func=lambda value: {"prospective": "只用截止前已知记录", "retrospective": "回顾：允许后来补入的资料"}[value], key="workflow_mode")
        cutoff = st.text_input("分析截止时刻（留空为当前时间；填写时包含时区）", key="workflow_cutoff")
    task_id = None
    result_metric_id = None
    if wid == "W4":
        outcomes = {"BODY-MASS-DAILY": "体重", "STR-11": "同条件训练表现", "STATE-RHR": "静息心率", "STATE-SDNN": "设备 SDNN"}
        result_metric_id = st.selectbox("本次重点观察", list(outcomes), format_func=outcomes.get, key="workflow_outcome")
        if result_metric_id == "STR-11":
            from healthzip.analytics.v13 import analyze
            try:
                if period:
                    from datetime import datetime, timezone

                    from healthzip.workflows.calendar import completed_periods
                    cut = cutoff or datetime.now(timezone.utc).isoformat()
                    bounds = completed_periods(cut, st.session_state.get("analysis_timezone", "Asia/Shanghai"), period)
                    selection = analyze(repo, cutoff_time=cut, window_start=bounds[0][0], window_end=bounds[-1][1],
                        timezone_name=st.session_state.get("analysis_timezone", "Asia/Shanghai"), retrospective=mode == "retrospective")
                    current = analyze(repo, cutoff_time=cut, period=period,
                        timezone_name=st.session_state.get("analysis_timezone", "Asia/Shanghai"), retrospective=mode == "retrospective")
                    selection["strength_tasks"] = list({task["task_id"]: task for task in
                        selection["strength_tasks"] + current["strength_tasks"]}.values())
                else:
                    selection = analyze(repo, int(days), cutoff_time=cutoff or None,
                        timezone_name=st.session_state.get("analysis_timezone", "Asia/Shanghai"), retrospective=mode == "retrospective")
                options = selection["strength_tasks"]
            except ValueError:
                options = []
            tasks = {task["task_id"]: task for task in options}
            task_id = st.selectbox("同条件训练任务", list(tasks), index=0 if tasks else None,
                format_func=lambda identity: tasks[identity].get("exercise_name", identity), key="workflow_long_task")
            if not tasks:
                st.info("当前窗口未记录可选择的参考任务；可先在力量页记录参考组。")
    declarations = {"population": population} if population != "unknown" else {}

    def requested():
        from dataclasses import replace
        from datetime import datetime, timezone

        from healthzip.science.contracts import instant
        request = WorkflowRequest(wid, window_days=int(days), baseline_days=int(baseline_days), period=period,
            cutoff_time=cutoff or None, mode=mode, result_metric_id=result_metric_id, task_id=task_id,
            timezone=st.session_state.get("analysis_timezone", "Asia/Shanghai"),
            session_id=session["id"] if session else None, session_exercise_id=instance["id"] if instance else None,
            selected_set_uuid=selected)
        request.normalized()  # Validate before saving or superseding any declaration.
        if (analysis or {}).get("selection_context"):
            if (analysis["timezone"] != request.timezone
                    or bool(analysis.get("retrospective")) != (mode == "retrospective")
                    or cutoff and instant(analysis["cutoff_time"]) > instant(cutoff)):
                raise ValueError("selected_analysis_time_or_mode_mismatch")
        prior_context = st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve()))
        if cutoff and mode == "prospective" and (declarations or prior_context):
            from healthzip.workflows.storage import context_as_of, current_context_problem
            # A newly confirmed declaration cannot be backdated. An unchanged,
            # still valid version may be reused at its actual historical time.
            prior = context_as_of(repo, prior_context, cutoff, mode)
            problem = current_context_problem(repo, prior_context)
            if problem:
                raise ValueError(problem)
            if prior["values"] != declarations or prior_context is None:
                if instant(cutoff) < datetime.now(timezone.utc):
                    raise ValueError("context_not_available_at_cutoff")
        context_id = save_context(repo, declarations, replaces_context_id=prior_context) if declarations or prior_context else None
        # Saving is an explicit user action. If subsequent analysis fails, the
        # page must point to the version that was actually committed.
        contexts = dict(st.session_state.get("analysis_contexts", {}))
        contexts[str(repo.path.resolve())] = context_id
        st.session_state["analysis_contexts"] = contexts
        selection_id = None
        if (analysis or {}).get("selection_context"):
            from healthzip.analytics.v13 import persist
            selection_id = persist(repo, analysis)
        return replace(request, context_id=context_id, selection_analysis_id=selection_id)

    saved = repo.rows("SELECT run_id,created_at FROM workflow_run WHERE user_id='local' AND workflow_id=? ORDER BY created_at DESC LIMIT 50", (wid,))
    if saved:
        history = {row["run_id"]: row["created_at"] for row in saved}
        chosen = st.selectbox("已保存的分析", list(history), index=None,
            format_func=lambda identity: history[identity], key="workflow_history_" + wid)
        if st.button("打开所选分析", key="workflow_open_run", disabled=chosen is None):
            st.session_state[key] = chosen
    if st.button("分析这次表现" if wid == "W1" else "运行分析", key="workflow_run"):
        try:
            request = requested()
            result = run_workflow(repo, request, parent_run_id=st.session_state.get(key))
            st.session_state[key] = result["run_id"]
        except ValueError as exc:
            st.error(str(exc))
    if key not in st.session_state:
        st.caption("选择问题后运行。记录不足时仍会显示可核对的事实和具体缺项。")
        return
    result = load_run(repo, st.session_state[key])
    render_run(repo, result)
    if st.button("核对本次结果的当前适用性", key="workflow_check_current"):
        try:
            decision = check_current_use(repo, result["run_id"])
            if decision["status"] == "current":
                st.success("相关输入与来源用途未发现变化；这不把历史分析改成当前行动承诺。")
            elif decision["status"] == "check_failed":
                st.error("当前核对服务未完成，请稍后重试；此前事实和历史结果仍保留。")
            else:
                st.warning("相关输入或权限已变化，请重新分析；原结果仍保留。")
                with st.expander("变化记录"):
                    st.json(decision)
        except (OSError, RuntimeError) as exc:
            st.error("当前核对服务未完成，请重试：" + type(exc).__name__)
    use_new_selection = bool((analysis or {}).get("selection_context")) and st.checkbox(
        "本次续算采用分析页新选择的记录（须与原任务时区和模式一致）", key="workflow_resume_selection")
    st.caption("补录后续算保留本次任务、范围与已确认信息并更新截止时刻；修改上方设置后点击运行分析可建立新任务。")
    if st.button("补录后重新分析", key="workflow_resume"):
        try:
            selection_id = None
            if use_new_selection:
                from healthzip.analytics.v13 import persist
                # The service validates cutoff, timezone and mode against the
                # saved task before accepting a newly selected sleep source.
                selection_id = persist(repo, analysis)
            refreshed = resume_workflow(repo, result["run_id"], selection_analysis_id=selection_id)
            st.session_state[key] = refreshed["run_id"]
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    request = result["request"]
    if wid == "W4" and result.get("task_selection"):
        task = result["task_selection"]
        matches = []
        page = st.number_input("复核任务的训练历史页码（每页 50 场）", min_value=1, value=1, key="workflow_action_page")
        for row in service.list_sessions(limit=50, offset=(int(page)-1)*50):
            saved_session = service.get_session(row["id"])
            for saved_instance in saved_session["exercises"]:
                if (not saved_instance.get("deleted_at") and saved_instance["catalog_id"] == task["exercise_id"]
                        and saved_instance.get("condition_key") == task["condition_key"]):
                    matches.append((saved_session, saved_instance))
        if matches:
            choices = {i["id"]: (s, i) for s, i in matches}
            chosen = st.selectbox("为同一任务选择训练并核对调整候选", list(choices), key="workflow_action_target",
                format_func=lambda key: choices[key][0]["session_date"] + " · " + str(choices[key][0].get("name") or "训练"))
            selected_session, selected_instance = choices[chosen]
            from healthzip.ui.current_training import render_current_training
            from healthzip.ui.recommendation_page import render_candidates
            if selected_session["session_status"] in {"draft", "in_progress", "paused"}:
                render_current_training(repo, selected_instance, source_report_id=result["run_id"])

            def long_changed(record):
                # Feedback resumes the candidate's W1 review. Keep the selected
                # historical W4 report and its calendar bounds unchanged.
                saved_candidate = next(r for r in service.list_recommendations() if r["candidate_id"] == record["candidate_id"])
                review_id = record.get("current_analysis_review", {}).get("run_id") or saved_candidate["input_snapshot"]["analysis_review"]["run_id"]
                latest = repo.one("SELECT run_id FROM workflow_run WHERE user_id='local' AND workflow_id='W1' "
                    "AND json_extract(request_json,'$.source_run_id')=? AND json_extract(request_json,'$.candidate_id')=? "
                    "ORDER BY created_at DESC LIMIT 1", (result["run_id"], record["candidate_id"]))
                if latest:
                    review_id = latest["run_id"]
                resume_workflow(repo, review_id, candidate_id=record["candidate_id"])

            render_candidates(repo, service, selected_session, selected_instance, key_prefix="workflow_long_", on_created=long_changed,
                review_request=WorkflowRequest("W1", source_run_id=result["run_id"],
                    window_days=int(st.session_state.get("analysis_window_days", 30)),
                    timezone=st.session_state.get("analysis_timezone", "Asia/Shanghai"),
                    context_id=st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve()))),
                allow_create=request["mode"] == "prospective" and selected_session["session_status"] in {"draft", "in_progress", "paused"})
            st.caption("调整候选使用同一练前规则核对。结束的训练仍可补记选择、执行与结果；新任务请先在力量页开始训练。")
        else:
            st.info("此页没有同条件训练。可翻页查找历史，或在力量页开始同一任务后返回核对候选。")
    if wid == "W1" and request["session_exercise_id"]:
        instance = service.get_session_exercise(request["session_exercise_id"])
        session = service.get_session(instance["session_id"])
        st.write("当前行动与反馈")
        st.caption("这里重新核对现在的条件；新候选和反馈生成关联的新运行，历史分析保持原样。")

        def changed(record):
            saved_candidate = next(r for r in service.list_recommendations() if r["candidate_id"] == record["candidate_id"])
            review_id = record.get("current_analysis_review", {}).get("run_id") or saved_candidate["input_snapshot"]["analysis_review"]["run_id"]
            latest = repo.one("SELECT run_id FROM workflow_run WHERE user_id='local' AND workflow_id='W1' "
                "AND json_extract(request_json,'$.source_run_id')=? AND json_extract(request_json,'$.candidate_id')=? "
                "ORDER BY created_at DESC LIMIT 1", (result["run_id"], record["candidate_id"]))
            resume_workflow(repo, latest["run_id"] if latest else review_id, candidate_id=record["candidate_id"])

        from healthzip.ui.recommendation_page import render_candidates
        render_candidates(repo, service, session, instance, key_prefix="workflow_", on_created=changed,
                          review_request=WorkflowRequest("W1", source_run_id=result["run_id"],
                              window_days=int(st.session_state.get("analysis_window_days", 30)),
                              timezone=st.session_state.get("analysis_timezone", "Asia/Shanghai"),
                              context_id=st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve()))),
                          allow_create=request["mode"] == "prospective" and not session.get("deleted_at")
                          and session["session_status"] in {"draft", "in_progress", "paused"})
