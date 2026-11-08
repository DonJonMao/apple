"""Local daily-use Streamlit UI for the offline health and strength workbench."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import streamlit as st

try:
    import plotly.express as px
except ImportError:  # pragma: no cover - optional UI dependency
    px = None

from healthzip.ai.client import AIConfig, explain_analysis
from healthzip.analytics import (
    all_analysis,
    body_state_strength,
    period_report,
    persist_analysis,
    strength_quality,
    today_training_setup,
)
from healthzip.config import DEFAULT_DB_PATH
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.importers.apple_zip import inspect_zip
from healthzip.importers.incremental import sync_folder
from healthzip.quality import inventory
from healthzip.reporting import render_report
from healthzip.strength_log import (
    StrengthLogError,
    append_quick_strength_set,
    save_strength_log,
)


def render_evidence_card(card: dict) -> None:
    """Render a card with the metadata needed to reproduce its conclusion."""
    if not card:
        return
    window = card.get("window") or {}
    st.subheader(card.get("title", "Evidence Card"))
    st.write(f"状态：{card.get('status')} · {card.get('summary', '')}")
    st.caption(
        f"时间范围：{window.get('start') or '—'} 至 {window.get('end') or '—'} · "
        f"算法版本：{card.get('algorithm_version') or '—'}"
    )
    if card.get("facts"):
        st.dataframe(card["facts"], use_container_width=True, hide_index=True)
    with st.expander("限制与来源", expanded=False):
        if card.get("limitations"):
            st.write("限制：" + "；".join(card["limitations"]))
        st.write("允许行动：" + "、".join(card.get("allowed_actions") or []))
        source_ids = [str(source_id) for source_id in (card.get("source_feature_ids") or [])]
        source_preview = "、".join(source_ids[:20]) or "—"
        if len(source_ids) > 20:
            source_preview += f" ……（共 {len(source_ids)} 条）"
        st.write("来源特征：" + source_preview)


def render_strength_tab(repo: Repository, value: dict) -> None:
    """Render the strength dashboard and the local manual logging workflow."""
    st.subheader("力量记录")
    st.caption("手动记录按组保存到本地 SQLite；重量统一使用 kg。空字段会保留为未知。")
    if notice := st.session_state.pop("strength_notice", None):
        st.success(notice)
    with st.expander("手机快速记录一组", expanded=False):
        st.caption("在同一局域网打开本地 Streamlit 页面时，可用这个窄表单快速追加一组。")
        if "quick_strength_session_key" not in st.session_state:
            st.session_state["quick_strength_session_key"] = uuid4().hex
        if st.button("开始新的快速训练", key="quick_strength_new_session"):
            st.session_state["quick_strength_session_key"] = uuid4().hex
        with st.form("strength_quick_form", clear_on_submit=False):
            quick_date = st.date_input("训练日期", value=date.today(), key="quick_strength_date")
            quick_exercise = st.text_input("动作", key="quick_strength_exercise")
            quick_equipment = st.text_input("器械（可选）", key="quick_strength_equipment")
            quick_variation = st.text_input("变式（可选）", key="quick_strength_variation")
            quick_weight = st.number_input(
                "重量 kg", min_value=0.0, value=0.0, step=0.5, key="quick_strength_weight"
            )
            quick_reps = st.number_input(
                "次数", min_value=1, value=1, step=1, key="quick_strength_reps"
            )
            quick_rir = st.text_input("RIR（可选）", key="quick_strength_rir")
            quick_rpe = st.text_input("RPE（可选）", key="quick_strength_rpe")
            quick_warmup = st.checkbox("热身组", key="quick_strength_warmup")
            quick_submit = st.form_submit_button("保存这一组", type="primary")
        if quick_submit:
            try:
                result = append_quick_strength_set(
                    repo,
                    session_key=st.session_state["quick_strength_session_key"],
                    session_date=quick_date.isoformat(),
                    started_at="",
                    exercise_name=quick_exercise,
                    equipment=quick_equipment,
                    variation=quick_variation,
                    weight_kg=quick_weight,
                    reps=quick_reps,
                    rir=quick_rir,
                    rpe=quick_rpe,
                    warmup=quick_warmup,
                )
                st.success(f"已保存第 {result['set_number']} 组。")
            except StrengthLogError as exc:
                st.error(str(exc))
    with st.form("strength_log_form", clear_on_submit=False):
        meta = st.columns([1, 1, 2, 2])
        session_date = meta[0].date_input("训练日期", value=date.today())
        started_at = meta[1].text_input("开始时间（可选）", value="")
        session_name = meta[2].text_input("训练名称（可选）", value="")
        session_notes = meta[3].text_input("训练备注（可选）", value="")
        set_count = st.number_input("组数", min_value=1, max_value=30, value=1, step=1)
        st.caption("每行是一组；热身组不会进入正式训练趋势。")
        rows: list[dict] = []
        headers = st.columns([2, 1, 1, 1, 1, 0.8, 0.8, 0.8, 1.2, 2])
        for column, label in zip(
            headers,
            ["动作", "器械", "变式", "重量 kg", "次数", "RIR", "RPE", "热身", "活动范围", "备注"],
        ):
            column.caption(label)
        for index in range(int(set_count)):
            columns = st.columns([2, 1, 1, 1, 1, 0.8, 0.8, 0.8, 1.2, 2])
            rows.append(
                {
                    "exercise_name": columns[0].text_input(
                        "动作", key=f"strength_exercise_{index}", label_visibility="collapsed"
                    ),
                    "equipment": columns[1].text_input(
                        "器械", key=f"strength_equipment_{index}", label_visibility="collapsed"
                    ),
                    "variation": columns[2].text_input(
                        "变式", key=f"strength_variation_{index}", label_visibility="collapsed"
                    ),
                    "weight_kg": columns[3].number_input(
                        "重量",
                        min_value=0.0,
                        value=0.0,
                        step=0.5,
                        key=f"strength_weight_{index}",
                        label_visibility="collapsed",
                    ),
                    "reps": columns[4].number_input(
                        "次数",
                        min_value=0,
                        value=0,
                        step=1,
                        key=f"strength_reps_{index}",
                        label_visibility="collapsed",
                    ),
                    # Text inputs preserve an empty value as unknown. A
                    # number_input default of 0 would incorrectly turn an
                    # unrecorded RIR/RPE into a true failure score.
                    "rir": columns[5].text_input(
                        "RIR",
                        value="",
                        key=f"strength_rir_{index}",
                        label_visibility="collapsed",
                    ),
                    "rpe": columns[6].text_input(
                        "RPE",
                        value="",
                        key=f"strength_rpe_{index}",
                        label_visibility="collapsed",
                    ),
                    "warmup": columns[7].checkbox(
                        "热身", key=f"strength_warmup_{index}", label_visibility="collapsed"
                    ),
                    "range_of_motion": columns[8].text_input(
                        "活动范围", key=f"strength_rom_{index}", label_visibility="collapsed"
                    ),
                    "notes": columns[9].text_input(
                        "备注", key=f"strength_notes_{index}", label_visibility="collapsed"
                    ),
                    "set_number": index + 1,
                }
            )
        submitted = st.form_submit_button("保存训练记录", type="primary")
    if submitted:
        try:
            # Let users choose a larger group count without having to fill
            # every row. Completely untouched rows are ignored; a partially
            # filled row still reaches validation and gets a useful error.
            entered_rows = []
            for row in rows:
                has_text = any(
                    str(row.get(field) or "").strip()
                    for field in (
                        "exercise_name",
                        "equipment",
                        "variation",
                        "rir",
                        "rpe",
                        "range_of_motion",
                        "notes",
                    )
                )
                if not has_text and row.get("weight_kg") == 0.0 and row.get("reps") == 0:
                    continue
                entered_rows.append(row)
            result = save_strength_log(
                repo,
                session_date=session_date.isoformat(),
                started_at=started_at,
                name=session_name,
                notes=session_notes,
                sets=entered_rows,
            )
            st.success(
                f"已保存训练 #{result['session_id']}：新增 {result['sets_inserted']} 组。"
                "重复提交会自动去重。"
            )
        except StrengthLogError as exc:
            st.error(str(exc))
        except Exception as exc:  # surface database errors without killing the dashboard
            st.error(f"保存失败：{exc}")

    sessions = repo.list_strength_sessions()
    if sessions:
        st.subheader("最近训练")
        session_labels = {
            f"{row['session_date']} · {row['name'] or '未命名训练'} · {row['set_count']} 组": int(
                row["id"]
            )
            for row in sessions
        }
        selected_label = st.selectbox(
            "选择训练", list(session_labels), key="strength_session_selected"
        )
        selected_id = session_labels[selected_label]
        selected = next(row for row in sessions if int(row["id"]) == selected_id)
        details = [dict(row) for row in repo.list_strength_sets(selected_id)]
        st.dataframe(details, use_container_width=True, hide_index=True)
        with st.expander("编辑训练信息", expanded=False):
            with st.form("strength_edit_form"):
                edit_date = st.text_input("训练日期", value=selected["session_date"] or "")
                edit_started = st.text_input("开始时间", value=selected["started_at"] or "")
                edit_name = st.text_input("训练名称", value=selected["name"] or "")
                edit_notes = st.text_input("备注", value=selected["notes"] or "")
                edit_submit = st.form_submit_button("保存训练信息")
            if edit_submit:
                try:
                    repo.update_strength_session(
                        selected_id,
                        session_date=edit_date,
                        started_at=edit_started,
                        name=edit_name,
                        notes=edit_notes,
                    )
                    st.session_state["strength_notice"] = "训练信息已更新。"
                    st.rerun()
                except Exception as exc:
                    st.error(f"更新失败：{exc}")
        with st.form("strength_delete_form"):
            confirm = st.checkbox("确认删除这个训练及其所有组记录")
            delete_submit = st.form_submit_button("删除训练")
        if delete_submit:
            if not confirm:
                st.warning("请先勾选确认框。")
            else:
                repo.delete_strength_session(selected_id)
                st.session_state["strength_notice"] = "训练已删除。"
                st.rerun()
    else:
        st.info("还没有手动训练记录。可以从上面的表单开始。")

    # P1 analytics are computed from the same local rows that power the form.
    # Keeping this here means a newly saved session is visible on the next rerun
    # without changing the import or core analysis pipeline.
    quality = value.get("strength_quality") or strength_quality(repo)
    association = value.get("body_state_strength") or body_state_strength(repo)
    week_report = value.get("week_report") or period_report(repo, "week")
    month_report = value.get("month_report") or period_report(repo, "month")

    render_evidence_card(quality.get("card"))
    assoc_card = association["card"]
    render_evidence_card(assoc_card)
    joined = []
    for item in association.get("joins", []):
        row = {"date": item["date"], "alignment": item["alignment"]}
        row.update({f"session_{key}": val for key, val in item["session"].items() if key != "date"})
        if item.get("body_state"):
            row.update(
                {f"body_{key}": val for key, val in item["body_state"].items() if key != "date"}
            )
        joined.append(row)
    if joined:
        st.dataframe(joined, use_container_width=True, hide_index=True)
    else:
        st.info("还没有与身体状态日期对齐的力量训练记录。")
    if association.get("paired_metrics"):
        st.caption("以下是同一训练日配对数据的描述性中位数，用于比较上下文，不表示因果关系。")
        st.dataframe(association["paired_metrics"], use_container_width=True, hide_index=True)

    st.subheader("今日训练起始设定")
    p1_series = quality.get("series", [])
    today_exercise = st.text_input(
        "动作名称（用于今日建议）",
        value=p1_series[0]["exercise_name"] if p1_series else "",
        key="today_strength_exercise",
    )
    today_meta = st.columns([1, 1, 1, 1])
    today_equipment = today_meta[0].text_input("器械（可选）", key="today_strength_equipment")
    today_variation = today_meta[1].text_input("变式（可选）", key="today_strength_variation")
    planned_weight = today_meta[2].number_input(
        "计划重量 kg（可选）", min_value=0.0, value=0.0, step=0.5, key="today_strength_weight"
    )
    planned_reps = today_meta[3].number_input(
        "目标次数（可选）", min_value=0, value=0, step=1, key="today_strength_reps"
    )
    if today_exercise.strip():
        setup = today_training_setup(
            repo,
            today_exercise,
            equipment=today_equipment,
            variation=today_variation,
            planned_weight_kg=planned_weight or None,
            planned_reps=int(planned_reps) or None,
        )
        setup_card = setup["card"]
        render_evidence_card(setup_card)
    else:
        setup = {"card": None}
        st.info("填写动作名称后生成基于近期重量和身体状态的起始范围。")

    st.subheader("周 / 月力量状态")
    report_tabs = st.tabs(["本周", "本月"])
    for report_tab, report in zip(report_tabs, (week_report, month_report)):
        with report_tab:
            card = report["card"]
            st.write(f"状态：{card['status']} · {card['summary']}")
            st.caption(
                f"时间范围：{card['window'].get('start') or '—'} 至 "
                f"{card['window'].get('end') or '—'} · 算法版本：{card.get('algorithm_version', '—')}"
            )
            if card.get("facts"):
                st.dataframe(card["facts"], use_container_width=True, hide_index=True)
            if card.get("limitations"):
                st.caption("；".join(card["limitations"]))
            if report.get("recommendations"):
                st.info("下一周期建议：" + "；".join(report["recommendations"]))
            if report["strength"].get("sessions"):
                st.dataframe(
                    report["strength"]["sessions"], use_container_width=True, hide_index=True
                )

    st.subheader("AI 证据解释")
    st.caption("AI 只接收已汇总的 Evidence Cards；未配置 endpoint/API key 时使用本地确定性回退。")
    ai_config = AIConfig.from_env()
    if ai_config:
        st.caption(f"服务：{ai_config.base_url} · 模型：{ai_config.model}（token 不在页面显示）")
    else:
        st.caption(
            "服务：未配置完整的 HEALTHZIP_AI_BASE_URL / HEALTHZIP_AI_MODEL / HEALTHZIP_AI_API_KEY"
        )
    allow_ai_network = st.checkbox(
        "允许把当前结构化摘要发送到已配置的 AI 服务",
        value=False,
        key="strength_ai_network_consent",
        help="只发送 Evidence Cards，不发送原始 ZIP/XML、逐条健康样本或 API token。",
    )
    question = st.text_input(
        "想让 AI 解释什么？",
        value="请结合身体状态、做组质量和周期趋势，给出下一步训练建议。",
        key="strength_ai_question",
    )
    if st.button("生成 AI 解释", key="strength_ai_run"):
        cards = {
            "heart": value.get("heart", {}),
            "sleep": value.get("sleep", {}),
            "weight": value.get("weight", {}),
            "strength": {"card": quality["card"]},
            "association": {"card": association["card"]},
            "week": {"card": week_report["card"]},
            "month": {"card": month_report["card"]},
        }
        if setup.get("card"):
            cards["today"] = {"card": setup["card"]}
        result = explain_analysis(cards, question=question, allow_network=allow_ai_network)
        st.write(result.get("summary", ""))
        st.caption(
            f"来源：{result.get('source', 'unknown')}；证据：{', '.join(result.get('evidence_ids', []))}"
        )
        if result.get("limitations"):
            st.warning("；".join(result["limitations"]))
        if result.get("actions"):
            st.info("允许的下一步：" + "、".join(result["actions"]))

    st.subheader("力量表现趋势")
    series = quality.get("series", [])
    if not series:
        st.info("尚无可分析的力量组数据。")
        return
    labels = [
        f"{item['exercise_name']} · {item['equipment'] or '未注明器械'} · {item['variation'] or '标准变式'}"
        for item in series
    ]
    selected_series = st.selectbox("动作条件", labels, key="strength_series_selected")
    item = series[labels.index(selected_series)]
    st.write(f"正式训练暴露 {item['exposures']} 次，共 {item['records']} 组。")
    if px and item.get("points"):
        chart_rows = [point for point in item["points"] if point.get("top_e1rm_kg") is not None]
        if chart_rows:
            st.plotly_chart(
                px.line(
                    chart_rows,
                    x="date",
                    y="top_e1rm_kg",
                    markers=True,
                    title="估算 1RM 趋势（kg）",
                ),
                use_container_width=True,
            )
    st.dataframe(item.get("points", []), use_container_width=True, hide_index=True)
    source_sets = [
        row
        for row in quality.get("sets", [])
        if not row.get("warmup")
        and str(row.get("exercise_name") or "").strip().lower() == item["exercise_name"]
        and str(row.get("equipment") or "").strip().lower() == item["equipment"]
        and str(row.get("variation") or "").strip().lower() == item["variation"]
    ]
    with st.expander("查看该动作的原始组记录", expanded=False):
        st.caption("趋势点保留 source_set_ids / source_session_ids，可回到下面的原始组记录核对。")
        st.dataframe(source_sets, use_container_width=True, hide_index=True)


st.set_page_config(page_title="Health ZIP Workbench", layout="wide")
st.title("Health ZIP Workbench")
st.caption("本地 Apple Health ZIP 整理与分析；不上传原始健康数据，不是医疗诊断。")

db_path = st.sidebar.text_input("SQLite 路径", str(DEFAULT_DB_PATH))
zip_path = st.sidebar.text_input("Apple Health ZIP 路径", "")
sync_path = st.sidebar.text_input("手机增量同步目录（JSON/JSONL）", "")
sync_source = st.sidebar.text_input("同步来源名称", "phone_export")
include_cycle = st.sidebar.checkbox("启用周期数据导入（可选）", value=False)
window_days = st.sidebar.number_input("分析窗口（天）", min_value=7, max_value=3650, value=30)

if zip_path:
    try:
        info = inspect_zip(zip_path)
        st.sidebar.success(f"已检查：{info.member_count} 个成员，XML：{info.xml_member_path}")
        with st.expander("ZIP 预扫描", expanded=False):
            st.json(info.as_dict())
        if st.sidebar.button("流式导入", type="primary"):
            repo = Repository(db_path)
            try:
                result = import_apple_zip(zip_path, repo, include_cycle=include_cycle)
                st.session_state["last_import"] = result.as_dict()
            finally:
                repo.close()
    except Exception as exc:
        st.sidebar.error(f"ZIP 检查失败：{exc}")

if sync_path:
    if st.sidebar.button("扫描增量数据"):
        repo = Repository(db_path)
        try:
            st.session_state["last_sync"] = sync_folder(
                sync_path, repo, source_name=sync_source or "phone_export"
            )
        except Exception as exc:
            st.session_state["last_sync"] = {"errors": [str(exc)]}
        finally:
            repo.close()

repo = Repository(db_path)
try:
    inv = inventory(repo)
    analysis = all_analysis(repo, int(window_days))
    persist_analysis(repo, analysis)
    if st.session_state.get("last_import"):
        st.subheader("最近导入")
        st.json(st.session_state["last_import"])
    if st.session_state.get("last_sync"):
        st.subheader("最近增量同步")
        st.json(st.session_state["last_sync"])
    tabs = st.tabs(
        [
            "导入与总览",
            "数据质量",
            "心率 / HRV",
            "睡眠",
            "运动",
            "体重 / 有氧",
            "力量",
            "营养",
            "周期",
            "报告",
        ]
    )
    with tabs[0]:
        st.subheader("数据总览")
        st.dataframe(inv.get("sample_types", []), use_container_width=True)
        st.write("Workout 类型")
        st.json(inv.get("workouts", {}))
        with st.expander("同步来源与游标", expanded=False):
            st.json(repo.sync_status())
    with tabs[1]:
        st.caption("状态是产品数据质量门槛，不是医学阈值。")
        st.dataframe(
            [{"feature": k, **v} for k, v in analysis["readiness"].items()],
            use_container_width=True,
        )
    for tab, key in (
        (tabs[2], "heart"),
        (tabs[3], "sleep"),
        (tabs[4], "workouts"),
        (tabs[5], "weight"),
        (tabs[6], "strength"),
        (tabs[7], "nutrition"),
        (tabs[8], "cycle"),
    ):
        with tab:
            value = analysis[key]
            cards = value.get("cards", []) if key == "heart" else [value.get("card")]
            for card in cards:
                render_evidence_card(card)
            if key == "sleep":
                if value.get("nights") and px:
                    st.plotly_chart(
                        px.line(
                            value["nights"], x="date", y="sleep_hours", title="每晚睡眠时长（小时）"
                        ),
                        use_container_width=True,
                    )
                st.dataframe(value.get("nights", []), use_container_width=True)
            elif key == "workouts":
                if value.get("weeks") and px:
                    st.plotly_chart(
                        px.bar(
                            value["weeks"],
                            x="week",
                            y="duration_minutes",
                            title="每周训练时长（分钟）",
                        ),
                        use_container_width=True,
                    )
                st.dataframe(value.get("weeks", []), use_container_width=True)
            elif key == "weight":
                if value.get("daily") and px:
                    st.plotly_chart(
                        px.line(value["daily"], x="date", y="kg", title="体重趋势（kg）"),
                        use_container_width=True,
                    )
                st.dataframe(value.get("daily", []), use_container_width=True)
                vo2 = analysis["vo2"]
                if vo2.get("points"):
                    render_evidence_card(vo2["card"])
                    if px:
                        st.plotly_chart(
                            px.line(
                                vo2["points"],
                                x="local_date",
                                y="normalized_value",
                                title="VO₂ max 估计值",
                            ),
                            use_container_width=True,
                        )
            elif key == "strength":
                render_strength_tab(
                    repo,
                    {
                        "strength_quality": analysis["strength_quality"],
                        "body_state_strength": analysis["body_state_strength"],
                        "week_report": analysis["week_report"],
                        "month_report": analysis["month_report"],
                        "heart": analysis["heart"],
                        "sleep": analysis["sleep"],
                        "weight": analysis["weight"],
                    },
                )
            elif key == "nutrition":
                st.dataframe(value.get("days", []), use_container_width=True)
            elif key == "cycle":
                st.dataframe(value.get("events", []), use_container_width=True)
    with tabs[9]:
        report_path = st.text_input("报告输出路径", "reports/latest.md")
        if st.button("生成 Markdown 报告"):
            out = render_report(analysis, inv, report_path)
            st.success(f"已写入 {out}")
        st.write("报告会包含每个 Evidence Card 的窗口、事实、样本量和限制。")
finally:
    repo.close()
