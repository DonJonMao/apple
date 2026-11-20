"""Two-session exercise-order review, separate from the optional full analysis."""
from __future__ import annotations

import streamlit as st

from healthzip.training.service import TrainingService
from healthzip.ui.health_explanation import _digest, job_result, knowledge_clock, submit_job
from healthzip.ui.training_bridge import LOAD_LABELS


def _rows(result):
    rows = []
    for role in ("preceding", "target"):
        item = result[role]
        for period, label in (("previous", "比较训练"), ("current", "本次训练")):
            for row in item[period]:
                rows.append({"训练": label, "动作": item["name"], "组": row["set_number"],
                    "负荷": row.get("load_value"), "单位": row.get("load_unit"),
                    "负荷口径": LOAD_LABELS.get(row.get("load_basis"), "按原记录口径"),
                    "次数": row.get("reps"), "RIR": row.get("rir"),
                    "时长（秒）": row.get("duration_s"), "距离（米）": row.get("distance_m"),
                    "实际休息（秒）": row.get("rest_recorded_s")})
    return rows


def _render_result(result):
    st.markdown("**观察到什么**")
    for observation in result["observations"]:
        st.write(observation)
    if result["possible_explanations"]:
        st.markdown("**可能的解释**")
        for explanation in result["possible_explanations"]:
            st.write(explanation["text"])
    else:
        st.caption("当前记录与依据还不能确认变化原因；时间先后本身不证明因果。")
    st.markdown("**下一步**")
    for action in result["next_steps"][:2]:
        st.write(action)
    with st.expander("逐组对照与重要缺项", expanded=False):
        rows = _rows(result)
        if rows:
            st.dataframe(rows, hide_index=True, use_container_width=True)
        for missing in result["missing"]:
            st.caption(missing)
    with st.expander("来源与判断依据", expanded=False):
        evidence = result["evidence"]
        if not evidence.get("spans"):
            st.caption("当前没有可用于机制解释的已审核来源；上方数值来自所选两场的已完成实际工作组。")
        for source in evidence.get("spans", []):
            metadata = source.get("source_metadata") or {}
            title, url = metadata.get("title", "原始来源"), metadata.get("canonical_url")
            if url and str(url).startswith(("https://", "http://")):
                st.markdown(f"[{title}]({url})")
            else:
                st.write(title)
            st.caption(f"{source.get('section_path', '')} · {source.get('source_version', '')}")
        for explanation in result["possible_explanations"]:
            for statement in explanation.get("statements", []):
                st.write(statement)
        st.caption("按实际动作顺序、相同器械及负荷口径核对；逐组展示次数与 RIR，不把不同动作吨位视为等价刺激。")


def render_sequence_review(repo):
    st.markdown("**前置动作变化，后续表现是否不同**")
    svc = TrainingService(repo, initialize=False)
    sessions = [row for row in svc.list_sessions(limit=200) if row.get("started_at")]
    if len(sessions) < 2:
        st.caption("至少需要两场有实际开始时间的训练，才能核对前后动作与表现变化。")
        return
    labels = {row["session_uuid"]: f"{row['started_at'][:10]} · {row.get('name') or '训练'}" for row in sessions}
    current_id = st.selectbox("本次训练", list(labels), format_func=labels.get, key="sequence_current")
    current = svc.get_session(current_id)
    previous = [row for row in sessions if row["started_at"] < current["started_at"]]
    if not previous:
        st.caption("这场训练之前没有可比较的记录，请选择较晚的训练。")
        return
    prior_id = st.selectbox("比较训练", [row["session_uuid"] for row in previous],
                            format_func=labels.get, key="sequence_previous")
    prior = svc.get_session(prior_id)
    old_ids = {item["catalog_id"] for item in prior["exercises"] if not item.get("deleted_at")}
    common = {item["catalog_id"]: item["exercise"]["name"] for item in current["exercises"]
              if not item.get("deleted_at") and item["catalog_id"] in old_ids}
    if len(common) < 2:
        st.caption("两场至少需要两个相同动作，才能核对前置动作与后续动作。可以重新选择比较训练。")
        return
    preceding = st.selectbox("前置动作", list(common), format_func=common.get, key="sequence_preceding")
    target = st.selectbox("后续动作", [identity for identity in common if identity != preceding],
                          format_func=common.get, key="sequence_target")
    include_evidence = st.checkbox("同时核对当前已审核知识依据（可选）", key="sequence_evidence")
    from healthzip.analytics.cache import revision_identity
    from healthzip.workflows.storage import report_context
    path = str(repo.path.resolve())
    version = revision_identity(repo, dependencies=[("training", None), ("health_sample", "sleep_stage")])
    timezone_name = st.session_state.get("analysis_timezone", "Asia/Shanghai")
    context = st.session_state.get("analysis_contexts", {}).get(path)
    declaration = report_context(repo, context, None, "retrospective")
    identity = _digest([path, version, current_id, prior_id, preceding, target, include_evidence,
                        context, declaration, timezone_name])
    ui_key = "sequence_review_job:" + path
    selected = st.session_state.get(ui_key)
    pending = selected and selected["identity"] == identity and job_result(selected["key"])["status"] == "pending"

    @st.fragment(run_every=0.75 if pending else None)
    def panel():
        selected = st.session_state.get(ui_key)
        status = job_result(selected["key"]) if selected and selected["identity"] == identity else None
        if status and status["status"] == "ready":
            result = status["result"]
            if include_evidence and result.get("knowledge_clock") != knowledge_clock(".local/knowledge"):
                st.caption("知识依据已经更新，请重新核对后使用解释。")
            else:
                _render_result(result)
        elif status and status["status"] == "pending":
            st.caption("正在核对所选记录；训练录入和其他页面仍可使用。")
        elif status and status["status"] in {"failed", "expired"}:
            st.info("这次对照没有完成。请确认两场动作没有重复实例，或更换比较训练后重试。")
        elif selected:
            st.caption("训练记录或选择已改变，请重新核对当前内容。")
        if st.button("核对动作顺序与表现", key="sequence_run",
                     disabled=bool(status and status["status"] == "pending")):
            def compute():
                from healthzip.db.repository import Repository
                from healthzip.training.sequence_review import review_sequence
                worker = Repository(path)
                try:
                    result = review_sequence(TrainingService(worker, initialize=False), current_id,
                        prior_id, preceding, target, include_evidence=include_evidence, context_id=context,
                        timezone_name=timezone_name)
                    result["knowledge_clock"] = knowledge_clock(".local/knowledge")
                    return result
                finally:
                    worker.close()
            import time
            job_key = _digest([identity, knowledge_clock(".local/knowledge"), time.monotonic_ns()])
            try:
                submit_job(job_key, compute)
                st.session_state[ui_key] = {"identity": identity, "key": job_key}
                st.rerun()
            except RuntimeError:
                st.caption("分析任务较多，请稍后重试。")
        if pending and status and status["status"] != "pending":
            st.rerun()
    panel()
