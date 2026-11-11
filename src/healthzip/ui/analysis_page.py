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
        period = st.selectbox("复盘周期", ["week", "month"], format_func=lambda x: "本周" if x == "week" else "本月")
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

