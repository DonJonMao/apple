"""A small, readable landing page; private inventories stay behind the UI."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

BODY_TYPES = (
    ("心率", ("heart_rate_bpm", "resting_heart_rate_bpm")),
    ("HRV", ("hrv_sdnn_ms",)),
    ("睡眠", ("sleep_stage",)),
    ("体重", ("body_mass_kg",)),
    ("有氧适能", ("vo2_max_ml_kg_min",)),
)


def overview_data(repo):
    """Read latest dates with the existing type/date index, without raw rows."""
    updates = []
    for label, types in BODY_TYPES:
        found, dates = False, []
        for canonical in types:
            row = repo.one(
                "SELECT local_date FROM health_sample WHERE canonical_type=? "
                "AND record_status='active' ORDER BY local_date DESC LIMIT 1",
                (canonical,),
            )
            found = found or row is not None
            if row and row[0]:
                dates.append(row[0])
        if label == "体重":
            row = repo.one(
                "SELECT local_date FROM body_measurement WHERE canonical_type='body_mass_kg' "
                "ORDER BY local_date DESC LIMIT 1"
            )
            found = found or row is not None
            if row and row[0]:
                dates.append(row[0])
        updates.append({"项目": label, "最近记录": max(dates) if dates else
                        ("日期未知" if found else "暂无记录"),
                        "数据状态": "已有记录" if found else "暂无记录"})
    workouts = repo.one("SELECT COUNT(*),MAX(local_date) FROM workout WHERE record_status='active'")
    updates.append({"项目": "运动", "最近记录": workouts[1] or
                    ("日期未知" if workouts[0] else "暂无记录"),
                    "数据状态": "已有记录" if workouts[0] else "暂无记录"})
    latest_dates = [row["最近记录"] for row in updates if row["最近记录"][:4].isdigit()]
    sessions = repo.one("SELECT COUNT(*) FROM strength_session WHERE deleted_at IS NULL")[0]
    batch = repo.one("SELECT imported_at,status FROM import_batch ORDER BY id DESC LIMIT 1")
    return {"updates": updates, "latest_date": max(latest_dates) if latest_dates else None,
            "workout_count": workouts[0], "training_count": sessions,
            "latest_import": dict(batch) if batch else None}


def _open_workspace(workspace):
    st.session_state["main_workspace"] = workspace


def _import_summary(result, *, sync=False):
    batches = result.get("batches", []) if sync else [result]
    added = sum(int(row.get("new", row.get("records_inserted", 0)) or 0) for row in batches)
    duplicates = sum(int(row.get("duplicate", row.get("records_deduplicated", 0)) or 0) for row in batches)
    updated = sum(int(row.get("updated", 0) or 0) for row in batches)
    invalid = sum(int(row.get("invalid", row.get("errors_count", 0)) or 0) for row in batches)
    errors = len(result.get("errors") or []) if sync else 0
    message = f"新增 {added:,} 条，重复 {duplicates:,} 条"
    if sync:
        message += f"，更新 {updated:,} 条"
    if errors or invalid or result.get("status") in {"partial_failed", "failed"}:
        st.warning(f"本次导入部分未完成：{message}；{errors + invalid} 项需要检查。")
    else:
        st.success("本次同步完成：" + message if sync else "本次导入完成：" + message)


def render_overview(repo, *, timezone_name="Asia/Shanghai", last_import=None, last_sync=None):
    data = overview_data(repo)
    st.subheader("数据总览")
    st.caption("查看身体记录，或直接开始记录今天的力量训练。")
    columns = st.columns(3)
    columns[0].metric("最近身体／运动记录", data["latest_date"] or "暂无记录")
    columns[1].metric("运动记录", f"{data['workout_count']:,} 次")
    columns[2].metric("力量训练记录", f"{data['training_count']:,} 次")
    first, second = st.columns(2)
    first.button("记录力量训练", on_click=_open_workspace, args=("力量",),
                 key="overview_open_training", type="primary")
    second.button("查看心率与 HRV", on_click=_open_workspace, args=("心率 / HRV",),
                  key="overview_open_heart")
    st.subheader("数据更新概况")
    st.dataframe(data["updates"], hide_index=True, use_container_width=True)
    st.caption("这里显示实际记录的日期；没有记录不能确定是否佩戴手表。")
    latest = data["latest_import"]
    if latest:
        try:
            imported = datetime.fromisoformat(latest["imported_at"].replace("Z", "+00:00"))
            imported_text = imported.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError, AttributeError):
            imported_text = "时间未记录"
        statuses = {"completed": "已完成", "partial_failed": "部分未完成",
                    "failed": "未完成", "running": "导入中"}
        st.caption(f"最近一次导入：{imported_text} · {statuses.get(latest['status'], '状态待核对')}")
    if last_import:
        _import_summary(last_import)
    if last_sync:
        _import_summary(last_sync, sync=True)
    with st.expander("如何导入后续数据"):
        st.write("展开左侧“导入与存储设置”，填写新的 Apple Health ZIP 路径后点击“流式导入”。")
        st.write("手机增量文件放入配置的同步目录后，点击“扫描增量数据”；已经导入的重复记录会自动识别。")
        st.caption("导入与训练记录分别保存；还没有身体数据时也可以正常记录力量训练。")
