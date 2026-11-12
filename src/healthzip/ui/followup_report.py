"""Readable execution and observation facts from the shared report result."""

import streamlit as st

STATUS = {"not_planned": "未预先约定窗口", "pending": "观察窗口尚未完成", "observed": "已有同条件后续观察",
          "no_comparable_observation": "窗口已结束，尚无可比记录", "not_executed": "未执行",
          "execution_unconfirmed": "执行尚不完整或未确认", "unavailable": "缺少可比执行参考"}
ENDPOINTS = {"load_value": "负荷", "reps": "次数", "rir": "RIR", "duration_s": "持续秒数", "distance_m": "距离"}


def render_followup_report(value):
    if not value:
        st.info("尚无候选执行或后续观察记录。")
        return
    execution = (value.get("execution") or {}).get("value") or []
    if not execution:
        st.info("本周期尚无候选创建、反馈或预先约定的后续观察窗口。")
    for item in execution:
        st.write("候选", item["recommendation_id"], "策略", item.get("strategy"))
        st.caption(f"选择：{item.get('adoption') or '尚未记录'} · 执行：{item.get('execution_state') or '尚未记录'}")
        success = item.get("short_term_success")
        st.write("冻结任务复核", "满足目标与可比质量要求" if success is True else "未满足目标或可比质量要求" if success is False else "尚不能判断")
        if item.get("reason_codes"):
            st.caption("复核限制：" + "；".join(item["reason_codes"]))
        comparisons = [{"记录项": ENDPOINTS.get(row["endpoint"], row["endpoint"]),
            "冻结目标下界": row["target"]["min"], "冻结目标上界": row["target"]["max"],
            "目标单位": row["target_unit"], "实做": row["actual"], "实做区间": str(row.get("actual_interval") or ""),
            "目标负荷口径": row.get("target_load_basis"), "实做负荷口径": row.get("actual_load_basis"),
            "原录负荷": (row.get("load_normalization") or {}).get("raw_value"),
            "原录单位": (row.get("load_normalization") or {}).get("raw_unit"),
            "实做单位": row["actual_unit"], "与下界差": row["actual_minus_min"], "与上界差": row["actual_minus_max"], "质量可比": row["quality_comparable"],
            "缺项或限制": "；".join(row["reason_codes"])} for row in item.get("target_comparisons", [])]
        if comparisons:
            st.dataframe(comparisons, use_container_width=True)
        if item.get("actual_observations"):
            with st.expander("用于复核的实际记录与质量"):
                st.json(item["actual_observations"])
        changed = item.get("execution_change")
        if changed and changed["comparable"]:
            st.write("执行相对原参考的记录变化", changed.get("load_change"), changed["differences"])
            st.caption("负荷、次数与余力分别报告；变更任务后的次数差不等于能力增减。")
        followup = item.get("followup") or {}
        st.write("后续观察", STATUS.get(followup.get("status"), "尚未约定或资料不足"))
        if followup.get("window"):
            plan = followup["window"]
            st.caption(f"用户约定：{plan['start']} 至 {plan['end']}（不含终点） · {plan['timezone']}")
        facts = []
        for comparison in followup.get("observations", []):
            for endpoint, delta in comparison["differences"].items():
                if endpoint not in {"reps", "rir"} and delta["value"] is None:
                    continue
                facts.append({"后续记录": comparison["after"]["record_id"], "日期": comparison["after"]["observed_at"],
                    "比较项": ENDPOINTS[endpoint], "执行参考": comparison["before"]["values"][endpoint],
                    "后续观察": comparison["after"]["values"][endpoint], "观察差值": delta["value"], "单位": delta["unit"],
                    "缺项": delta["reason"]})
        if facts:
            st.dataframe(facts, use_container_width=True)
        if followup.get("reason_codes"):
            st.caption("观察限制：" + "；".join(followup["reason_codes"]))
        if followup.get("exclusions"):
            with st.expander("未进入比较的记录与原因"):
                st.json(followup["exclusions"])
    st.caption("后续差值是已记录的观察；未执行、缺反馈和缺随访单列，不表示策略导致了改变。")
