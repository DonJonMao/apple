"""Explicit management actions; normal navigation never imports or writes analysis."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

from healthzip.ai.client import AIConfig
from healthzip.config import DEFAULT_DB_PATH
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.importers.apple_zip import inspect_zip
from healthzip.importers.incremental import sync_folder


def _save_network_consent():
    from healthzip.ui.health_explanation import set_network_consent

    set_network_consent(st.session_state["_setting_network_consent"])


def import_summary(result, *, sync=False):
    batches = result.get("batches", []) if sync else [result]
    added = sum(int(row.get("new", row.get("records_inserted", 0)) or 0) for row in batches)
    duplicate = sum(int(row.get("duplicate", row.get("records_deduplicated", 0)) or 0) for row in batches)
    updated = sum(int(row.get("updated", 0) or 0) for row in batches)
    deleted = sum(int(row.get("deleted", 0) or 0) for row in batches)
    invalid = sum(int(row.get("invalid", row.get("errors_count", 0)) or 0) for row in batches)
    errors = list(result.get("errors") or [])
    details = errors + [message for row in batches for message in row.get("error_samples", [])]
    if sync:
        details += [message for row in batches for message in row.get("errors", [])]
    message = f"新增 {added:,} 条，重复 {duplicate:,} 条，更新 {updated:,} 条，删除 {deleted:,} 条"
    if errors or invalid or result.get("status") in {"partial_failed", "failed"}:
        st.warning(f"本次导入部分未完成：{message}；{len(errors) + invalid} 项需要检查。")
        with st.expander("查看本次导入问题"):
            for error in dict.fromkeys(details):
                st.write(str(error))
    else:
        st.success("本次同步完成：" + message if sync else "本次导入完成：" + message)


def render_settings():
    st.subheader("设置")
    st.caption("管理当前数据工作区、导入来源和可选解释服务。")
    section = st.radio("设置内容", ["基础资料", "导入与同步", "模型与资料库", "数据诊断"], horizontal=True, key="settings_section")
    if section == "基础资料":
        from healthzip.ui.basic_profile import render_basic_profile
        repo = Repository(st.session_state["database_path"])
        try:
            render_basic_profile(repo, st.session_state.get("analysis_timezone", "Asia/Shanghai"))
        finally:
            repo.close()
        from healthzip.ui.preferences import load_preferences, persist_widget
        workspace = st.session_state["database_path"]
        key = "cycle_enabled:" + str(Path(workspace).resolve())
        st.checkbox("在身体中显示周期与症状", value=bool(load_preferences(workspace).get("cycle_enabled")), key=key,
                    on_change=persist_widget, args=(workspace, key, "cycle_enabled"))
        return
    if section == "数据诊断":
        from healthzip.quality.coverage import inventory
        repo = Repository(st.session_state["database_path"])
        try:
            st.json(inventory(repo))
        finally:
            repo.close()
        return
    if section == "模型与资料库":
        _render_model_settings()
        if st.toggle("打开本地资料库管理", key="settings_library"):
            from healthzip.ui.knowledge_page import render_knowledge
            render_knowledge()
        return
    with st.form("workspace_settings"):
        database = st.text_input("SQLite 路径", st.session_state.get("database_path", str(DEFAULT_DB_PATH)))
        zone = st.text_input("分析时区", st.session_state.get("analysis_timezone", "Asia/Shanghai"))
        if st.form_submit_button("保存工作区设置", type="primary"):
            try:
                ZoneInfo(zone)
                with_repository = Repository(database)
                with_repository.close()
            except (ZoneInfoNotFoundError, ValueError, OSError, sqlite3.Error) as exc:
                st.error(f"设置未保存：{exc}")
            else:
                st.session_state["database_path"] = database
                st.session_state["analysis_timezone"] = zone
                st.success("工作区与时区已保存；浏览器训练草稿按工作区隔离。")
    st.write("导入与同步")
    scope = str(Path(st.session_state["database_path"]).resolve())
    results = st.session_state.setdefault("workspace_import_results", {}).setdefault(scope, {})
    with st.form("apple_import"):
        archive = st.text_input("Apple Health ZIP 路径", "")
        include_cycle = st.checkbox("保留周期数据导入（可选）", value=False)
        submitted = st.form_submit_button("流式导入")
    if submitted:
        results.pop("import", None)
        try:
            inspect_zip(archive)
            repo = Repository(st.session_state["database_path"])
            try:
                with st.spinner("正在导入；保留原始来源与时间…"):
                    results["import"] = import_apple_zip(archive, repo, include_cycle=include_cycle).as_dict()
            finally:
                repo.close()
        except Exception as exc:
            results["import"] = {"status": "failed", "errors": [str(exc)]}
    if results.get("import"):
        import_summary(results["import"])
    with st.form("incremental_sync"):
        folder = st.text_input("手机增量同步目录（JSON/JSONL）", "")
        source = st.text_input("同步来源名称", "phone_export")
        sync = st.form_submit_button("扫描增量数据")
    if sync:
        results.pop("sync", None)
        repo = None
        try:
            repo = Repository(st.session_state["database_path"])
            with st.spinner("正在检查增量文件…"):
                results["sync"] = sync_folder(folder, repo, source_name=source or "phone_export")
        except Exception as exc:
            results["sync"] = {"status": "failed", "errors": [str(exc)]}
        finally:
            if repo is not None:
                repo.close()
    if results.get("sync"):
        import_summary(results["sync"], sync=True)


def _render_model_settings():
    st.write("模型解释")
    config = AIConfig.from_env()
    st.caption("已配置模型服务。" if config else "尚未配置模型服务；事实、图表与训练记录均可正常使用。")
    st.checkbox("允许将解释所需的最小结构化摘要发送到已配置模型服务",
                value=st.session_state.get("health_explanation_network_consent", False),
                key="_setting_network_consent", on_change=_save_network_consent)
    with st.expander("配置说明"):
        st.write("服务使用环境变量 HEALTHZIP_AI_BASE_URL、HEALTHZIP_AI_MODEL、HEALTHZIP_AI_API_KEY。修改后重启本地服务。密钥不在页面回显或写入报告。")
        st.caption("授权在当前浏览会话内持续有效，可随时取消。知识审核与来源使用范围仍逐次检查。")
