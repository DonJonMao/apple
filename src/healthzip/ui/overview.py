"""Calendar overview: current facts, one trend and a useful next action."""
from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import streamlit as st

from healthzip.analytics.workspace_summary import workspace_summary
from healthzip.analytics.workspaces import latest_observation_dates
from healthzip.ui.theme import open_workspace


def overview_data(repo, timezone_name="Asia/Shanghai"):
    """Small metadata reads; empty/draft sessions cannot become completion counts."""
    observed = [day for day in latest_observation_dates(repo, timezone_name).values() if day]
    batch = repo.one("SELECT imported_at,status FROM import_batch ORDER BY id DESC LIMIT 1")
    active = repo.one("SELECT id,name,started_at FROM strength_session WHERE deleted_at IS NULL "
                      "AND session_status IN ('draft','in_progress','paused') ORDER BY id DESC LIMIT 1")
    return {"latest_date": max(observed) if observed else None,
            "latest_import": dict(batch) if batch else None, "active": dict(active) if active else None}


def _select_cards(facts):
    groups = [
        ("完成训练", ("已完成训练次数", "已完成训练", "完成训练场次")),
        ("有效工作组", ("已完成工作组", "有效工作组")),
        ("睡眠中位数", ("已观察睡眠",)),
        ("静息心率", ("静息心率",)),
        ("体重", ("体重",)),
    ]
    selected = []
    for title, labels in groups:
        matches = [fact for fact in facts if fact.get("label") in labels and fact.get("value") is not None]
        if matches:
            selected.append((title, max(matches, key=lambda fact: fact.get("observed_days", 0))))
    return selected


def _trend(item):
    import plotly.graph_objects as go
    strength = item.get("strength_daily", [])
    if strength:
        values = [(row["date"], row.get("completed_work_sets", row.get("work_sets", 0))) for row in strength]
        fig = go.Figure(go.Bar(x=[p[0] for p in values], y=[p[1] for p in values], marker_color="#38BFA3", width=43200000))
        fig.update_xaxes(type="date", tickformat="%m/%d", tickmode="array", tickvals=[p[0] for p in values])
        title, unit = "本期已完成工作组", "组"
    else:
        series = []
        for identity, title, unit in (("STATE-RHR", "静息心率日值", "bpm"),
                                      ("BODY-MASS-DAILY", "体重日值", "kg")):
            metric = item.get("metrics", {}).get(identity, {})
            for points in (metric.get("value") or {}).values():
                valid = [point for point in points if point.get("value") is not None]
                if valid:
                    series.append((valid, title, unit))
            if series:
                break
        if not series:
            metric = item.get("metrics", {}).get("REPORT-STATE-SUMMARY", {})
            valid = [dict(point, value=point["value"] / 60) for point in metric.get("daily_facts", [])
                     if point.get("series_id") == "observed_sleep_by_wake_date" and (point.get("value") or 0) > 0]
            if valid:
                # Each source is still a separate series; never connect unlike watches.
                source = valid[0].get("source_id")
                series = [([point for point in valid if point.get("source_id") == source], "已观察睡眠", "小时")]
        if not series:
            return False
        points, title, unit = max(series, key=lambda value: len(value[0]))
        points = sorted(points, key=lambda point: point["date"])
        fig = go.Figure(go.Scatter(x=[p["date"] for p in points], y=[p["value"] for p in points],
                                  mode="markers", marker={"size": 8, "color": "#38BFA3"}))
    st.write(title)
    fig.update_layout(height=260, margin={"l": 12, "r": 12, "t": 16, "b": 44},
                      yaxis_title=unit, xaxis_title=None, showlegend=False)
    fig.update_traces(hovertemplate=f"%{{x}}<br>%{{y:.1f}} {unit}<extra></extra>")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key="overview_trend")
    st.caption("仅展示实际观测日期；缺失日期不填零。")
    return True


def render_overview(repo, *, timezone_name="Asia/Shanghai", **_unused):
    st.subheader("总览")
    with st.container(key="overview_period"):
        label = st.radio("总结范围", ["本周", "本月"], horizontal=True, key="overview_period_choice", label_visibility="collapsed")
    period = "week" if label == "本周" else "month"
    result = workspace_summary(repo, "总览", timezone_name=timezone_name, period=period)
    item = next(row for row in result["periods"] if row["period"] == period)
    zone = ZoneInfo(timezone_name)
    first = datetime.fromisoformat(item["window"]["start"]).astimezone(zone)
    end = datetime.fromisoformat(item["window"]["end"]).astimezone(zone)
    st.caption(f"{first:%Y-%m-%d} — {end:%Y-%m-%d %H:%M} · {timezone_name}")
    if repo.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='advice_profile_revision'"):
        from healthzip.advice import profile
        from healthzip.ui.basic_profile import GOALS
        goal = profile(repo)["fields"].get("training_goal")
        if goal:
            st.write("当前目标 · " + GOALS.get(goal, str(goal)))
    data = overview_data(repo, timezone_name)
    cards = _select_cards(item["facts"])
    if cards:
        columns = st.columns(len(cards))
        for column, (title, fact) in zip(columns, cards):
            value = fact["value"]
            number = f"{value:,.0f}" if fact.get("unit") in {"次", "场", "组"} else f"{value:,.1f}"
            comparison = item.get("comparison", {})
            previous = next((row for row in comparison.get("facts", [])
                             if row["label"] == fact["label"]
                             and row.get("source_identity") == fact.get("source_identity")
                             and row.get("value") is not None), None)
            comparable_days = comparison.get("coverage", {}).get("window_days") == item["coverage"]["window_days"]
            delta = (f"{value - previous['value']:+.1f} {fact.get('unit', '')} · "
                     + comparison.get("label", "上期同期")) if previous and comparable_days else None
            column.metric(title, f"{number} {fact.get('unit', '')}", delta=delta, delta_color="off")
            if fact.get("source") and title not in {"完成训练", "有效工作组"}:
                column.caption(fact["source"])
            destination = {"睡眠中位数": "睡眠", "静息心率": "心率", "体重": "体重"}.get(title, "训练")
            column.button("查看" + title, key="overview_fact:" + title, on_click=_open_fact, args=(destination, label))
        _trend(item)
        st.write("本期发现")
        # The same period's deterministic statements; no full-period comparison.
        allowed = {fact["label"] for _, fact in cards}
        findings = [text for text in item["conclusions"] if any(label in text for label in allowed)]
        for text in (findings or item["conclusions"])[:3]:
            st.markdown("- " + text)
        comparison = item.get("comparison", {})
        if comparison:
            bounds = comparison["window"]
            prior_start = datetime.fromisoformat(bounds["start"]).astimezone(zone)
            prior_end = datetime.fromisoformat(bounds["end"]).astimezone(zone)
            st.caption(f"卡片比较{comparison['label']}：{prior_start:%m-%d %H:%M} — {prior_end:%m-%d %H:%M}；只比较相同来源的已记录值。")
            if comparison["coverage"]["window_days"] != item["coverage"]["window_days"]:
                st.caption("上一周期较短；范围长度不同时不显示差值，避免把不同天数的记录直接相比。")
        st.caption("本期尚未结束，变化不代表完整周期或因果关系。")
    else:
        last = data["latest_date"]
        message = f"本期没有可用于总结的记录。最近一次健康或运动观测在 {last}。" if last else "本期还没有健康与训练记录。"
        st.markdown(f'<div class="hz-empty">{escape(message)}<br>可以直接开始力量训练，或在设置中导入健康数据。</div>', unsafe_allow_html=True)
    with st.container(border=True):
        active = data["active"]
        st.write("继续本次训练" if active else "下一次训练，从一组开始")
        if active:
            st.caption(active["name"] or "进行中的训练")
        else:
            st.caption("直接添加动作并记录；无需先创建计划。")
        st.button("继续本次训练" if active else "开始训练", key="overview_open_training",
                  type="primary", on_click=open_workspace, args=("力量",))
    if cards:
        st.caption("下次记录尽量沿用同一来源和测量条件，让前后变化更容易比较。")
    from healthzip.workflows.actions import list_actions
    active_actions = [action for action in list_actions(repo) if action.get("status") not in {"executed", "stopped"}]
    if active_actions:
        action = active_actions[0]
        with st.container(border=True):
            st.write("当前行动 · " + action["action_text"])
            st.caption("计划复评 " + datetime.fromisoformat(action["review_due"]).astimezone(zone).date().isoformat())
            st.button("查看执行与后续观察", on_click=_open_action, args=(action["action_id"],))
    left, right = st.columns(2)
    left.button("查看身体主题", on_click=open_workspace, args=("身体",), use_container_width=True)
    right.button("导入与同步", on_click=open_workspace, args=("导入与同步",), use_container_width=True)
    recent = repo.rows("SELECT name,started_at,session_uuid FROM strength_session WHERE deleted_at IS NULL AND session_status='completed' ORDER BY started_at DESC LIMIT 3")
    if recent:
        st.write("最近训练")
        for row in recent:
            if st.button(f"{(row['started_at'] or '')[:10]} · {row['name'] or '训练'}", key="recent_training:" + row["session_uuid"]):
                from healthzip.ui.training_workbench import open_recorded_session
                open_recorded_session(repo, row["session_uuid"])
                st.rerun()
        st.button("查看训练历史", on_click=open_workspace, args=("训练",), key="overview_history")
    st.button("周月复盘与行动复评", on_click=open_workspace, args=("复盘",), key="overview_review")
    with st.expander("分析依据与范围"):
        for note in item.get("limitations", []):
            st.caption(note)
        st.caption(f"本期 {item['coverage']['observed_days']} 个观测日期；同类指标按来源分别统计，卡片优先显示观测日期最多的来源。")
    last = data["latest_date"] or "暂无健康或运动观测"
    imported = data["latest_import"]
    updated = imported["imported_at"] if imported else "尚未导入"
    st.caption(f"最近观测日期：{last} · 数据导入时间：{updated}")


def _open_action(action_id):
    st.session_state["review_action_id"] = action_id
    st.session_state["review_section"] = "行动复评"
    open_workspace("复盘")


def _open_fact(destination, period_label):
    st.session_state["body_period"] = period_label
    if destination in {"睡眠", "心率", "体重"}:
        from healthzip.ui.body_workspace import _SUMMARIES
        st.session_state["body_metric:" + destination] = _SUMMARIES[destination]
    open_workspace(destination)
