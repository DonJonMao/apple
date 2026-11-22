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


def render_exercise_progress(repo, catalog_id=None):
    """Read two selected actual instances from the same local exercise catalog."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from healthzip.training.sequence_review import compare_work_sets
    from healthzip.ui.training_page import STOP_LABELS
    from healthzip.ui.training_workbench import open_recorded_session

    st.subheader("动作进展")
    svc = TrainingService(repo, initialize=False)
    timezone = ZoneInfo(st.session_state.get("analysis_timezone", "Asia/Shanghai"))
    # One query to the recorded instances. A repeated movement within a session
    # stays separately selectable. Public catalog defaults cannot assign conditions.
    records = repo.conn.execute(
        "SELECT e.id,e.session_id,e.catalog_id,e.position,s.name,s.started_at,s.session_date,"
        "s.session_uuid,julianday(s.started_at) AS start_jd,COALESCE(json_extract(e.definition_snapshot_json,'$.name_zh'),"
        "json_extract(e.definition_snapshot_json,'$.name'),e.catalog_id) AS exercise_name "
        "FROM training_session_exercise e JOIN strength_session s ON s.id=e.session_id "
        "WHERE s.deleted_at IS NULL AND e.deleted_at IS NULL AND s.user_id=? AND e.user_id=? "
        "AND EXISTS (SELECT 1 FROM strength_set g WHERE g.session_exercise_id=e.id AND "
        "g.deleted_at IS NULL AND g.completion_state='completed' AND g.set_type='work') "
        "ORDER BY COALESCE(julianday(s.started_at),julianday(s.session_date)) DESC,"
        "s.id DESC,e.position", (svc.user_id, svc.user_id)).fetchall()
    if not records:
        st.info("还没有可比较的已完成工作组。记录一组后可以在这里查看。")
        return
    names = {row["catalog_id"]: row["exercise_name"] for row in records}
    scope = str(repo.path.resolve())
    saved = st.session_state.setdefault("exercise_progress_selection", {}).setdefault(scope, {})

    def choose(label, options, labels, key):
        default = saved.get(key)
        value = st.selectbox(label, options, index=options.index(default) if default in options else 0,
                             format_func=labels.get, key="progress_" + key + str(hash(scope)))
        saved[key] = value
        return value

    if catalog_id is None:
        catalog_id = choose("动作", list(names), names, "exercise")
    elif catalog_id not in names:
        st.info("该动作尚无已完成工作组，可以先记录本次训练。")
        return
    else:
        st.write(names[catalog_id])
    rows = [row for row in records if row["catalog_id"] == catalog_id]
    labels = {}
    for row in rows:
        at = datetime.fromisoformat(row["started_at"]) if row["started_at"] else None
        local = at.astimezone(timezone).strftime("%Y-%m-%d %H:%M") if at and at.tzinfo else row["session_date"]
        labels[row["id"]] = f"{local or '日期未知'} · {row['name'] or '训练'} · 第 {row['position'] + 1} 个动作"
    current = choose("查看场次", list(labels), labels, "current_" + catalog_id)
    entry = next(row for row in rows if row["id"] == current)
    previous_choices = [row["id"] for row in rows if row["session_id"] != entry["session_id"] and
                        row["start_jd"] is not None and entry["start_jd"] is not None and
                        row["start_jd"] < entry["start_jd"]]
    previous = choose("比较场次", previous_choices, labels, "previous_" + catalog_id) if previous_choices else None
    sources = [("本次", svc.get_session_exercise(current))]
    if previous:
        sources.insert(0, ("比较场次", svc.get_session_exercise(previous)))
    values = []
    for label, inst in sources:
        for row in inst["sets"]:
            if row.get("deleted_at") or row.get("completion_state") != "completed" or row.get("set_type") != "work":
                continue
            values.append({"场次": label, "组": row["set_number"], "负荷": row.get("load_value"),
                           "单位": row.get("load_unit"), "口径": LOAD_LABELS.get(row.get("load_basis"), "未知"),
                           "次数": row.get("reps"), "秒数": row.get("duration_s"), "米数": row.get("distance_m"),
                           "RIR": row.get("rir"), "RIR限定": "至少" if row.get("rir_qualifier") == "at_least" else None,
                           "停止原因": STOP_LABELS.get(row.get("stop_reason")), "组前休息（秒）": row.get("rest_recorded_s")})
    if previous:
        comparison = compare_work_sets(sources[0][1]["sets"], sources[1][1]["sets"])
        for fact in comparison["observations"]:
            st.write(fact)
        for pair in comparison["comparisons"]:
            if pair["reps_change"] is not None:
                st.write(f"第 {pair['set_number']} 组同口径负荷，"
                         f"{pair['previous_reps']} → {pair['current_reps']} 次。")
            elif pair["same_reps_load_change"] is not None:
                st.write(f"第 {pair['set_number']} 组均为 {pair['current_reps']} 次，"
                         f"{pair['previous_load_value']} {pair['previous_load_unit']} → "
                         f"{pair['load_value']} {pair['load_unit']}。")
        if not comparison["comparisons"] or any(not pair["comparable"] for pair in comparison["comparisons"]):
            st.caption("部分组缺少可比条件，或两次负荷不同。下方保留各次实际记录。")
        if comparison["unmatched_previous"] or comparison["unmatched_current"]:
            st.caption("两场部分工作组的原组序不一致，已单独列出。")
        for step in comparison["next_steps"]:
            st.write(step)
    else:
        st.caption("此场之前尚无可定位的同动作训练。")
    if values:
        visible = [key for key in values[0] if any(row[key] is not None for row in values)
                   or key in {"RIR", "次数"}]
        st.dataframe([{key: row[key] for key in visible} for row in values],
                     hide_index=True, width="stretch")
    for label, inst in sources:
        record = next(row for row in rows if row["id"] == inst["id"])
        st.button(f"打开{label}原始训练", key="progress_record_" + inst["id"],
                  on_click=open_recorded_session, args=(repo, record["session_uuid"]))
