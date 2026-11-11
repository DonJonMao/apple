"""Six functional views share the frozen MetricResult snapshot."""

from __future__ import annotations

import json

import streamlit as st

from healthzip.ai.client import explain_analysis

GROUPS = {"可比力量表现": ("STR-",), "每日训练候选": ("STR-25", "STR-26", "STR-27", "STR-28", "STR-29", "STR-30"),
          "停滞与调整试验": ("STR-18", "STR-19", "STR-20", "STR-21", "STR-22", "STR-23", "STR-24"),
          "身体状态": ("STATE-", "LOAD-"), "长期能量背景": ("BODY-", "ENERGY-"),
          "复盘与个体学习": ("REPORT-", "PRED-", "QAL-")}


def render_analysis(repo, value):
    from healthzip.science import definitions
    names = definitions()
    result = value.get("v13")
    if result is None:
        from healthzip.analytics.v13 import analyze, persist
        result = analyze(repo)
        persist(repo, result)
    st.subheader("训练分析")
    st.caption(f"数据截止 {result['cutoff_time']} · 版本 {result['algorithm_version']}。未知保留为空；模型有效性与数据可用性分别显示。")
    metrics = result["metrics"]
    if isinstance(metrics, list):
        metrics = {x["metric_id"]: x for x in metrics}
    tasks = result.get("strength_tasks", [])
    if tasks:
        st.write("各动作与测量协议分别分析")
        st.dataframe([{"动作": task["exercise_name"], "任务": task["task_id"][:12],
            "协议": str(task["protocol"]), "协议完整": task["protocol_complete"],
            "参考场次": task["metrics"]["STR-11"]["n_sessions"],
            "趋势": str(task["metrics"]["STR-19"]["value"]),
            "状态": task["metrics"]["STR-19"]["data_status"]} for task in tasks], use_container_width=True)
        with st.expander("登记并查看任务区间"):
            st.caption("每个共享分析家族分配总错误预算。重复查看同一任务、同一数据和指标复用登记；数据或指标变化会分配下一次预算。缺少真实校准仍不确认停滞。")
            cutoff_mode = result.get("cutoff_mode", "explicit")
            window_binding = (result["window_start"], result["window_end"], result["cutoff_time"]) if cutoff_mode == "explicit" else (
                result["window_start"][:10], result["window_end"][:10])
            signature = (str(result["data_version"]), result["timezone"], result.get("period"), cutoff_mode, window_binding,
                         tuple(sorted((task["task_id"], task["input_data_hash"]) for task in tasks)))
            if st.session_state.get("analysis_look_signature") != signature:
                st.session_state["analysis_look_signature"] = signature
                st.session_state["analysis_look_snapshot"] = result
            look_snapshot = st.session_state["analysis_look_snapshot"]
            st.caption(f"本次查看冻结截止：{look_snapshot['cutoff_time']}。相同记录与日历窗口下重绘页面复用此快照。")
            task_labels = {task["exercise_name"] + " · " + task["task_id"][:12]: task["task_id"] for task in tasks}
            task_label = st.selectbox("测量任务", list(task_labels), key="analysis_look_task")
            task_id = task_labels[task_label]
            family_id = st.text_input("共享分析家族标识", value="local_strength_monitoring", key="analysis_look_family")
            alpha = st.number_input("该家族总错误概率预算（统计设计）", min_value=0.001, max_value=0.5, value=0.05, step=0.005, key="analysis_look_alpha")
            metric_label = st.selectbox("查看内容", ["趋势变化区间", "停滞候选复核"], key="analysis_look_metric")
            metric_id = {"趋势变化区间": "STR-20", "停滞候选复核": "STR-22"}[metric_label]
            if st.button("登记本次查看并计算", key="analysis_look_submit"):
                from healthzip.analytics.v13 import view_task_interval
                try:
                    viewed = view_task_interval(repo, look_snapshot, task_id, family_id=family_id, alpha_total=alpha, metric_id=metric_id)
                    st.session_state["analysis_last_look"] = viewed
                except ValueError as exc:
                    st.error(str(exc))
            if st.session_state.get("analysis_last_look"):
                viewed = st.session_state["analysis_last_look"]
                receipt = viewed.get("look_allocation") or viewed.get("look_audit", {}).get("value") or {}
                frozen_task = next(task for task in look_snapshot["strength_tasks"] if task["task_id"] == task_id)
                look_number = receipt.get("look_number", 0)
                bound_alpha = receipt.get("alpha_look", 0) * look_number * (look_number + 1)
                matches = (receipt.get("data_version") == str(look_snapshot["data_version"])
                           and receipt.get("task_id") == task_id and receipt.get("metric_id") == metric_id
                           and receipt.get("family_id") == family_id and abs(bound_alpha - alpha) < 1e-15
                           and receipt.get("cutoff_time") == look_snapshot["cutoff_time"]
                           and receipt.get("data_hash") == frozen_task["data_snapshot_hash"])
                if matches:
                    st.write("实际区间与登记依据", viewed["value"])
                    st.caption("；".join(viewed["reason_codes"]))
                    st.json(viewed)
                else:
                    st.caption("已有查看结果与当前家族、预算、任务或窗口不一致；请为当前选择登记查看。")
    for tab, (title, prefixes) in zip(st.tabs(list(GROUPS)), GROUPS.items()):
        with tab:
            selected = [x for k, x in metrics.items() if any(k.startswith(p) for p in prefixes)]
            st.dataframe([{"指标": names[x["metric_id"]]["title"], "结果": str(x["value"]) if x["value"] is not None else "未知",
                           "单位": x["unit"], "数据状态": x["data_status"], "证据身份": x["evidence_status"],
                           "有效/总数": f"{x['valid_n']}/{x['total_n']}", "原因": "；".join(x["reason_codes"])} for x in selected], use_container_width=True)
            with st.expander("窗口、来源和计算依据"):
                for x in selected:
                    st.json(x)
            if title == "每日训练候选":
                st.caption("候选需要明确的用户计划、器械步长、可比记录与审核依据。身体信号不会自动换算成重量。")
            if title == "复盘与个体学习":
                st.caption("模拟评测只代表研究实现可运行；没有真实时间外验证时不声称个人预测有效。")
    with st.expander("本周 / 本月复盘"):
        from healthzip.analytics.v13 import analyze, persist
        period_label = st.selectbox("复盘周期", ["本周", "本月"])
        period = {"本周": "week", "本月": "month"}[period_label]
        if st.button("生成当前周期复盘"):
            period_result = value.get("period_snapshots", {}).get(period) or analyze(repo, cutoff_time=result["cutoff_time"], period=period)
            persist(repo, period_result)
            st.caption(f"{period_result['window_start']} 至 {period_result['window_end']}；只统计截止时刻已经发生且可知的资料。")
            for mid, metric in period_result["metrics"].items():
                if mid.startswith("REPORT-"):
                    st.write(names[mid]["title"], metric["value"])
                    st.caption(f"状态 {metric['data_status']} · {metric['valid_n']}/{metric['total_n']} · {'；'.join(metric['reason_codes'])}")
            st.download_button("下载本周期完整结果", data=json.dumps(period_result, ensure_ascii=False, indent=2),
                               file_name=f"healthzip-{period}.json", mime="application/json")
    with st.expander("AI 解释（可选）"):
        allow = st.checkbox("允许把当前结构化证据发送至已配置 AI 服务", value=False)
        question = st.text_input("解释问题", "请解释可用记录与仍缺少的信息。")
        if st.button("解释当前证据"):
            response = explain_analysis({"metrics": metrics}, question=question, allow_network=allow)
            st.write(response["summary"])
            st.caption(response["source"])

