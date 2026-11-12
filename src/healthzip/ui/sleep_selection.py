"""Normal-page controls for user-declared sleep episodes and source selection."""

import json
from datetime import datetime, timezone

import streamlit as st

from healthzip.analytics.sleep_selection import declare_episode
from healthzip.science.contracts import canonical_hash, instant


def _now():
    return datetime.now(timezone.utc)


def _draft_window(analysis):
    """Automatic rolling time is not a new user-selected analysis window."""
    value = {"mode": analysis.get("cutoff_mode", "explicit"), "days": analysis.get("window_days", 30),
             "period": analysis.get("period"), "timezone": analysis["timezone"]}
    if value["period"] or value["mode"] != "auto":
        value.update(start=analysis["window_start"], end=analysis["window_end"])
    return value


def render_sleep_selection(repo, analysis):
    options = analysis.get("sleep_options", {})
    streams = {row["stream_id"]: row for row in options.get("streams", [])}
    with st.expander("声明睡眠片段与主睡眠"):
        st.caption("逐晚明确边界、归属日期和记录来源。不会把最长片段或多晚总和自动叫作主睡眠；未覆盖时段保持未知。")
        if not streams:
            if st.session_state.get("analysis_sleep_declarations"):
                st.warning("当前窗口已没有可用睡眠来源，原草稿已失效；请重新选择窗口和来源后声明。")
                st.session_state["analysis_sleep_declarations"] = []
                st.session_state["analysis_sleep_main"] = None
            st.info("当前窗口没有截止前可见的睡眠记录。inBed 不能代替实际睡眠。")
            return analysis
        if st.session_state.get("analysis_sleep_stream") not in streams:
            st.session_state["analysis_sleep_stream"] = None
        stream_id = st.selectbox("睡眠记录来源", list(streams), index=None, key="analysis_sleep_stream",
            placeholder="明确选择一个来源",
            format_func=lambda key: f"{streams[key]['source_name']} · 设备 {streams[key]['device'] or '未记录'} · {key[:8]}")
        binding = canonical_hash({"repository": str(repo.path.resolve()), "stream": stream_id,
                                  "adapter_version": options.get("adapter_version"), "window": _draft_window(analysis)})
        if st.session_state.get("analysis_sleep_draft_binding") != binding:
            if st.session_state.get("analysis_sleep_declarations"):
                st.warning("分析窗口、时区或睡眠来源已切换，原草稿已清除；请核对新的选择后重新声明。")
            st.session_state["analysis_sleep_draft_binding"] = binding
            st.session_state["analysis_sleep_declarations"] = []
            st.session_state["analysis_sleep_main"] = None
        episodes = st.session_state["analysis_sleep_declarations"]
        retained, removed = [], []
        for episode in episodes:
            reason = None
            if not instant(analysis["window_start"]) <= instant(episode["start"]) < instant(episode["end"]) <= instant(analysis["window_end"]):
                reason = "片段已离开当前窗口"
            else:
                try:
                    current = declare_episode(options, stream_id, start=episode["start"], end=episode["end"],
                        attribution_date=episode["attribution_date"], declared_at=episode["declared_at"])
                    if current != episode:
                        reason = "支持该片段的来源版本已变化"
                except ValueError:
                    reason = "支持该片段的来源已不可用或版本已变化"
            if reason:
                removed.append(f"{episode['attribution_date']}：{reason}")
            else:
                retained.append(episode)
        if removed:
            st.warning("以下声明已从当前草稿移除，请重新核对：" + "；".join(removed))
            episodes = retained
            st.session_state["analysis_sleep_declarations"] = retained
        source = streams.get(stream_id)
        if source:
            st.dataframe([{"来源记录": row["record_id"], "起点": row["start"], "终点": row["end"],
                "阶段": row["stage"], "可用时间": row["available_at"]} for row in source["observations"]], hide_index=True)
        start = st.text_input("睡眠片段起点（含时区）", key="analysis_sleep_start")
        end = st.text_input("睡眠片段终点（含时区）", key="analysis_sleep_end")
        attribution = st.text_input(f"该片段归属日期（{analysis['timezone']}，YYYY-MM-DD）", key="analysis_sleep_date")
        if st.button("添加本晚声明", key="analysis_sleep_add", disabled=source is None):
            try:
                declaration = declare_episode(options, stream_id, start=start, end=end,
                    attribution_date=attribution, declared_at=_now().isoformat())
                if not instant(analysis["window_start"]) <= instant(start) < instant(end) <= instant(analysis["window_end"]):
                    raise ValueError("片段须完整位于当前显示窗口内；请先选择包含该晚的分析窗口")
                if any(instant(start) < instant(item["end"]) and instant(end) > instant(item["start"]) for item in episodes):
                    raise ValueError("已有重叠片段；请清除声明后重新填写，不能把同一晚重复计数")
                st.session_state["analysis_sleep_declarations"] = [*episodes, declaration]
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if episodes:
            st.dataframe([{"归属日期": item["attribution_date"], "起点": item["start"], "终点": item["end"],
                "声明时间": item["declared_at"], "记录来源数": len(item["source_revisions"])} for item in episodes], hide_index=True)
        by_id = {item["id"]: item for item in episodes}
        if st.session_state.get("analysis_sleep_main") not in by_id:
            st.session_state["analysis_sleep_main"] = None
        main_id = st.selectbox("本次查看的主睡眠（可留空，只看逐晚中点）", list(by_id), index=None,
            key="analysis_sleep_main", placeholder="明确选择一晚",
            format_func=lambda key: f"{by_id[key]['attribution_date']} · {by_id[key]['start']} 至 {by_id[key]['end']}")
        if st.button("清除当前睡眠声明", key="analysis_sleep_clear", disabled=not episodes):
            st.session_state["analysis_sleep_declarations"] = []
            st.rerun()
        selection = {"stream_id": stream_id, "episodes": episodes, "main_episode_id": main_id}
        signature = canonical_hash({"base": analysis["data_hash"], "selection": selection})
        st.caption("保存会按当前声明时间生成一份新分析，原快照保留。截止时点更新可能改变滚动窗口及周/月边界；若新窗口不含所选片段，将保留原结果并提示。声明不会被回填成过去当时已知。")
        if st.button("保存声明并生成当前分析", key="analysis_sleep_submit", disabled=not episodes):
            from healthzip.analytics.v13 import analyze, persist
            cutoff = max(instant(analysis["cutoff_time"]), _now()).isoformat()
            result = analyze(repo, window_days=analysis.get("window_days", 30), cutoff_time=cutoff,
                timezone_name=analysis["timezone"], period=analysis.get("period"),
                context={**analysis.get("selection_context", {}), "sleep_selection": selection})
            if not result["sleep_selection"]["accepted"]:
                st.warning("本次声明尚不能生成新结果，原分析保留：" + "；".join(result["sleep_selection"]["reason_codes"]))
            else:
                persist(repo, result)
                st.session_state["analysis_sleep_result"] = result
                st.session_state["analysis_sleep_signature"] = signature
        selected = st.session_state.get("analysis_sleep_result")
        if not selected or st.session_state.get("analysis_sleep_signature") != signature:
            return analysis
        st.caption(f"本次睡眠声明分析截止：{selected['cutoff_time']} · 窗口 {selected['window_start']} 至 {selected['window_end']}")
        st.write("所选主睡眠的已观察时长", selected["metrics"]["STATE-SLEEP-MAIN"]["value"] or "尚未选择主睡眠")
        st.write("逐晚明确片段的中点", selected["metrics"]["STATE-SLEEP-TIMING"]["value"])
        st.caption("片段边界由用户声明，已观察睡眠仍是覆盖下界；不会据此认定整夜记录完整或估计恢复程度。")
        st.download_button("下载睡眠声明及完整结果", data=json.dumps(selected, ensure_ascii=False, indent=2),
            file_name="healthzip-sleep-selection.json", mime="application/json")
        return selected
