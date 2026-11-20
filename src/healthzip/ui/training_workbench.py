"""Local bidirectional strength workspace and lazily opened legacy tools.

The component has no network API or credentials. Commands cross Streamlit's
component channel and are validated by training_bridge before TrainingService
persists them. Only the selected secondary editor is evaluated.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import BoundedSemaphore

import streamlit as st
import streamlit.components.v1 as components

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

_component = components.declare_component(
    "healthzip_strength_workbench", path=str(Path(__file__).with_name("strength_component"))
)


# Optional advice has its own bounded queue and connection. No UI thread waits
# for knowledge retrieval, and a worker never reuses Streamlit's SQLite handle.
_ADVICE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="strength-advice")
_ADVICE_SLOTS = BoundedSemaphore(4)


def _advice_worker(database, command, context):
    from healthzip.ui.training_bridge import handle_command

    try:
        with closing(Repository(database)) as repo:
            receipt = handle_command(repo, command, context)
        return receipt, {key: context.get(key) for key in
            ("advice", "advice_dependencies", "advice_stale")}
    finally:
        _ADVICE_SLOTS.release()


def _collect_advice(state):
    job = state.get("advice_job")
    if not job:
        return
    future = job["future"]
    if future.done():
        try:
            receipt, result = future.result()
            state.update(result)
            public = {"status": "ready" if receipt["status"] == "saved" else "error",
                      "message": receipt.get("message")}
        except Exception:
            public = {"status": "error", "message": "建议暂不可用，实际记录仍可继续。"}
        state["advice_job_public"] = public
        state.pop("advice_job", None)
    elif time.monotonic() - job["started"] > 20:
        state["advice_job_public"] = {"status": "slow", "message": "建议核对耗时较长，可返回继续记录。"}


def _start_advice(repo, command, state):
    _collect_advice(state)
    target = (command.get("payload") or {}).get("instance_id")
    if state.get("advice_job") and state["advice_job"].get("instance_id") != target:
        return {"id": command["id"], "action": "advice", "status": "error",
                "message": "上一动作的建议仍在核对，可继续训练，稍后再读取本动作。"}
    if not state.get("advice_job"):
        if not _ADVICE_SLOTS.acquire(blocking=False):
            return {"id": command["id"], "action": "advice", "status": "error",
                    "message": "建议服务正在处理其他请求，请稍后再试；训练可继续。"}
        context = {key: state.get(key) for key in ("context_id", "window_days", "timezone_name")}
        context["window_days"] = context.get("window_days") or 30
        context["timezone_name"] = context.get("timezone_name") or "Asia/Shanghai"
        state["advice_job"] = {"started": time.monotonic(), "instance_id": target,
            "future": _ADVICE_EXECUTOR.submit(_advice_worker, str(repo.path.resolve()), command, context)}
        state["advice_job_public"] = {"status": "running"}
        state.pop("advice", None)
    return {"id": command["id"], "action": "advice", "status": "saved", "data": {"queued": True}}


def _scope(repo):
    # An opaque per-database namespace, never the private filesystem path.
    return hashlib.sha256(str(repo.path.resolve()).encode()).hexdigest()[:24]


def render_workbench(repo):
    from healthzip.ui.training_bridge import build_snapshot, handle_command

    scope = _scope(repo)
    state = st.session_state.setdefault("strength_workbench:" + scope, {})
    state["context_id"] = st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve()))
    state["window_days"] = int(st.session_state.get("analysis_window_days", 30))
    if state.get("legacy"):
        try:
            _secondary(repo, state)
        except (ValueError, KeyError, OSError, sqlite3.Error):
            st.error("这条训练记录暂时无法打开，请返回工作台重新选择；本地输入仍会保留。")
        return
    _collect_advice(state)
    try:
        snapshot = build_snapshot(
            repo, state, timezone_name=st.session_state.get("analysis_timezone", "Asia/Shanghai")
        )
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        st.error(f"训练页面暂时无法读取：{exc}")
        if st.button("重新读取训练", key="strength_retry_load"):
            st.rerun()
        return
    command = _component(
        snapshot=snapshot, receipt=state.get("receipt"), key="strength_component_" + scope,
        default=None,
    )
    if not isinstance(command, dict) or not command.get("id"):
        return
    # A component's last value is returned on unrelated reruns as well. A
    # delivery nonce permits deliberate retries with the SAME business ID.
    delivery = (command["id"], command.get("delivery"))
    if state.get("last_delivery") == delivery:
        return
    state["last_delivery"] = delivery
    if command.get("action") == "workspace":
        if (command.get("payload") or {}).get("workspace") == "导入与总览":
            st.session_state["strength_workspace_next"] = "导入与总览"
        state["receipt"] = {"id": command["id"], "status": "saved", "action": "workspace"}
    elif command.get("action") == "legacy":
        state["legacy"] = dict(command.get("payload") or {})
        state["receipt"] = {"id": command["id"], "status": "saved", "action": "legacy"}
    elif command.get("action") == "advice":
        state["receipt"] = _start_advice(repo, command, state)
    elif command.get("action") == "advice_status":
        _collect_advice(state)
        state["receipt"] = {"id": command["id"], "action": "advice_status", "status": "saved"}
    else:
        state["receipt"] = handle_command(repo, command, state)
    st.rerun()


def _secondary(repo, state):
    from healthzip.ui import training_page as old

    svc = TrainingService(repo)
    if st.button("← 返回训练工作台", key="strength_secondary_back"):
        state.pop("legacy", None)
        state.pop("history", None)
        state.pop("advice", None)
        state["calendar_dirty"] = True
        st.rerun()
    target = state["legacy"]
    view = target.get("view", "management")
    st.caption("力量训练 · 更多功能")
    if notice := st.session_state.pop("training_notice", None):
        st.warning(notice)
    if view == "set_details":
        row = svc.get_set(target.get("set_id") or target.get("id"))
        instance = svc.get_session_exercise(row["session_exercise_id"])
        st.subheader(instance["exercise"]["name"] + " · 组详情")
        old._set_editor(repo, svc, row, instance)
    elif view == "instance_settings":
        instance = svc.get_session_exercise(target.get("instance_id") or target.get("id"))
        st.subheader(instance["exercise"]["name"] + " · 动作设置")
        old._instance_controls(svc, instance)
        _instance_order(svc, instance)
        from healthzip.training.current import equipment_loads, save_equipment_loads

        settings = equipment_loads(repo, instance)
        with st.form("strength_equipment_loads"):
            text = st.text_input("实际可用档位（逗号分隔）", ",".join(map(str, settings["available_loads"])))
            options = [None, "kg", "lb", "level", "stack_level"]
            unit = settings.get("load_unit")
            if unit not in options:
                options.append(unit)
            chosen = st.selectbox("档位单位", options, index=options.index(unit),
                                  format_func=lambda value: value or "未知")
            st.caption("器械档位是事实，不会单独授予加重建议。")
            if st.form_submit_button("保存本动作档位"):
                if old._act(save_equipment_loads, repo, instance["id"],
                            [x.strip() for x in text.split(",") if x.strip()], load_unit=chosen):
                    st.success("档位已保存。")
    elif view == "pre_state":
        _pre_state(repo)
    elif view == "catalog_detail":
        item = svc.get_exercise(target.get("exercise_id") or target.get("id"))
        st.subheader(item["name"])
        old._exercise_detail(svc, item, "strength_catalog_detail_" + item["exercise_id"])
    elif view in {"recommendations", "comparison"}:
        instance = svc.get_session_exercise(target.get("instance_id") or target.get("id"))
        from healthzip.ui.current_training import (
            render_current_training,
            render_objective_comparison,
        )

        if view == "comparison":
            render_objective_comparison(repo, instance["id"])
        else:
            render_current_training(repo, instance)
            if st.checkbox("查看旧建议与可选手工反馈", key="strength_old_recommendations"):
                from healthzip.ui.recommendation_page import render_candidates

                session = svc.get_session(instance["session_id"])
                render_candidates(repo, svc, session, instance,
                                  allow_create=session["session_status"] in {"draft", "in_progress", "paused"})
    elif view == "session_details":
        _session_details(svc, target.get("session_id") or target.get("id"))
    else:
        options = ["请选择", "模板", "动作与器械", "历史记录与撤销", "历史冲突", "导入导出", "离线记录器", "表现分析与复盘"]
        selected = st.selectbox("训练管理", options, key="strength_management_view")
        if selected == "模板":
            old._templates(svc)
        elif selected == "动作与器械":
            old._catalog(svc)
        elif selected == "历史记录与撤销":
            old._history(svc)
        elif selected == "历史冲突":
            old._conflicts(svc)
        elif selected == "导入导出":
            old._exchange(svc)
            old._legacy_history(svc)
        elif selected == "离线记录器":
            from healthzip.training.offline import recorder_html

            st.download_button("下载可离线打开的记录器", recorder_html(repo),
                               file_name="HealthZIP_离线记录器.html", mime="text/html")
            st.caption("浏览器本地草稿、连接设置和原有鉴权保持有效。请在清理浏览器数据前导出未同步记录。")
        elif selected == "表现分析与复盘":
            from healthzip.analytics import all_analysis
            from healthzip.ui.analysis_page import render_analysis

            value = all_analysis(repo, int(st.session_state.get("analysis_window_days", 30)),
                                 timezone_name=st.session_state.get("analysis_timezone", "Asia/Shanghai"),
                                 context_id=state.get("context_id"))
            render_analysis(repo, value)


def _instance_order(svc, instance):
    from healthzip.ui.training_page import _act

    session = svc.get_session(instance["session_id"])
    ids = [item["id"] for item in session["exercises"] if not item.get("deleted_at")]
    index = ids.index(instance["id"])
    for label, delta in (("将此动作上移", -1), ("将此动作下移", 1)):
        if 0 <= index + delta < len(ids) and st.button(label):
            ids[index], ids[index + delta] = ids[index + delta], ids[index]
            if _act(svc.reorder_exercises, session["id"], ids, base_revision=session["revision"]):
                st.rerun()


def _pre_state(repo):
    from healthzip.state_log import ANCHORS, save_state
    from healthzip.ui.training_page import _act

    st.subheader("训练前状态（可选）")
    st.caption("这是本产品的记录问卷。留空表示未记录，不是临床诊断或恢复总分。")
    fatigue = st.selectbox("当前总体疲劳", [None, 0, 1, 2, 3, 4],
                           format_func=lambda x: "未回答" if x is None else ANCHORS[str(x)])
    soreness = st.selectbox("当前酸痛", [None, 0, 1, 2, 3, 4],
                            format_func=lambda x: "未回答" if x is None else ANCHORS[str(x)])
    muscle = st.text_input("酸痛部位 / 侧别")
    pain = st.selectbox("疼痛或不适", [None, "reported", "denied", "unknown"],
                        format_func=lambda x: {None: "未回答", "reported": "有", "denied": "明确没有", "unknown": "不确定"}[x])
    impact = st.text_input("不适对动作的影响")
    if st.button("保存当前状态"):
        if _act(save_state, repo, fatigue=fatigue, soreness=soreness, pain=pain,
                muscle=muscle or None, movement_impact=impact or None):
            st.success("已保存。")


def _session_details(svc, identity):
    """Explicit historical metadata editor; never part of the recording view."""
    from healthzip.ui.training_page import _act

    session = svc.get_session(identity)
    st.subheader("训练信息与历史版本")
    name = st.text_input("训练名称", value=session["name"])
    started = st.text_input("真实开始时间（含时区）", value=session.get("started_at") or "")
    if st.button("保存训练信息"):
        if _act(svc.update_session, identity, {"name": name, "started_at": started or None},
                base_revision=session["revision"]):
            st.rerun()
    if session["session_status"] in {"draft", "in_progress", "paused"}:
        status = "in_progress" if session["session_status"] == "paused" else "paused"
        if st.button("继续训练" if status == "in_progress" else "暂停训练"):
            if _act(svc.update_session, identity, {"session_status": status},
                    base_revision=session["revision"]):
                st.rerun()
    title = st.text_input("另存为模板名称")
    if st.button("按本次目标另存模板"):
        if _act(svc.save_session_as_template, identity, title):
            st.success("模板已保存，实际记录不会变成处方。")
    with st.expander("冻结建议和客观对照"):
        if st.checkbox("读取这场训练的冻结结果"):
            from healthzip.ui.current_training import render_objective_comparison

            for instance in session["exercises"]:
                st.write(instance["exercise"]["name"])
                render_objective_comparison(svc.repo, instance["id"])
