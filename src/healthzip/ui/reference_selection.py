"""Explicit local choices for observed load/body mass and the same-task B0 baseline."""

import json

import streamlit as st

from healthzip.science.contracts import canonical_hash


def render_reference_selection(repo, analysis):
    options = analysis.get("reference_options", {})
    references = {row["record_id"]: row for row in options.get("references", [])}
    with st.expander("选择历史任务与体重参考"):
        st.caption("B0只复述相同动作、器械条件、协议和负荷的最近可见参考；不是下一次完成保证或已校准个人预测。负荷/体重只作所选记录的比值参考，不是测得1RM或跨动作力量等级。")
        st.caption("本入口只使用实录的完整外部负荷。e1RM另需明确公式与适用域，其研究代理值不会在这里自动替代实录分子。")
        if not references:
            st.info("当前窗口尚无截止前可见、协议完整且质量可用的参考组。先在训练中登记参考协议并记录参考组；不会填入默认次数或体重。")
            return analysis
        if st.session_state.get("analysis_reference_record") not in references:
            st.session_state["analysis_reference_record"] = None
        identity = st.selectbox("历史参考组（同时确定同条件同负荷目标）", list(references), index=None,
            key="analysis_reference_record", placeholder="明确选择一条参考记录",
            format_func=lambda key: (f"{references[key]['exercise_name']} · {references[key]['observed_at']} · "
                f"{references[key]['load']['entered_load']} {references[key]['load']['entered_unit']} · "
                f"{references[key]['reps']} 次 · {key[-8:]}"))
        reference = references.get(identity)
        binding = (analysis["data_hash"], identity)
        if st.session_state.get("analysis_reference_mass_binding") != binding:
            st.session_state["analysis_reference_mass_binding"] = binding
            st.session_state["analysis_reference_mass"] = None
            st.session_state["analysis_reference_mass_confirm"] = False
        masses = {row["record_id"]: row for row in options.get("body_mass", [])
                  if reference and row["local_date"] == reference["local_date"]}
        mass_id = st.selectbox("同日体重记录（可留空，只查看B0历史参考）", list(masses), index=None,
            key="analysis_reference_mass", placeholder="明确选择体重来源",
            format_func=lambda key: (f"{masses[key]['observed_at']} · {masses[key]['normalization']['value']:.3f} kg · "
                f"{masses[key]['source_name'] or '来源未记录'} · {key}"))
        confirmed = st.checkbox("已核对所选体重适合与该次负荷记录并列比较", key="analysis_reference_mass_confirm")
        st.caption("只列同一本地日且单位已验证的体重；这是一项时间对齐规则，不证明测量条件相同。不会自动选择最近记录或合并不同秤。")
        if reference:
            st.write("所选负荷口径", reference["load"]["load_basis"], "；完整外部负荷（kg）", reference["load"]["total_load_kg"])
            if not masses:
                st.info("该日没有可用体重记录；仍可查看B0，负荷/体重比保持未知。")
        selection = {"task_id": reference["task_id"] if reference else None, "reference_record_id": identity,
                     "body_mass_record_id": mass_id, "body_mass_matches_reference": confirmed}
        signature = canonical_hash({"analysis": analysis["data_hash"], "selection": selection})
        if st.button("计算并保存所选参考", key="analysis_reference_submit", disabled=reference is None):
            from healthzip.analytics.v13 import analyze, persist
            selected = analyze(repo, window_days=analysis.get("window_days", 30), cutoff_time=analysis["cutoff_time"],
                timezone_name=analysis["timezone"], retrospective=analysis.get("retrospective", False),
                period=analysis.get("period"), context={"reference_selection": selection})
            persist(repo, selected)
            st.session_state["analysis_reference_result"] = selected
            st.session_state["analysis_reference_signature"] = signature
        selected = st.session_state.get("analysis_reference_result")
        if not selected or st.session_state.get("analysis_reference_signature") != signature:
            return analysis
        ratio, baseline = selected["metrics"]["STR-30"], selected["metrics"]["PRED-B0"]
        st.write("所选观测负荷/体重（kg/kg）", ratio["value"]["ratio"] if ratio["value"] else "缺少匹配体重或完整外部负荷")
        st.write("B0同条件历史参考", baseline["value"] if baseline["value"] else "没有严格可比的已知历史")
        st.caption("；".join(dict.fromkeys(ratio["reason_codes"] + baseline["reason_codes"])))
        st.json({"选择与来源": selected["reference_selection"], "STR-30": ratio, "PRED-B0": baseline})
        st.download_button("下载所选参考完整结果", data=json.dumps(selected, ensure_ascii=False, indent=2),
                           file_name="healthzip-selected-reference.json", mime="application/json")
        return selected
