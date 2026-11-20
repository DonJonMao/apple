"""Readable daily body records, separate from canonical scientific results."""

from __future__ import annotations

import ast
import math
from collections import Counter, defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

try:
    import plotly.express as px
except ImportError:  # pragma: no cover - optional UI dependency
    px = None


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def source_name(value):
    """Read the declared name from a canonical stream key without showing IDs."""
    source = value
    if isinstance(value, str):
        try:
            source = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            source = value
    if isinstance(source, (tuple, list)):
        source = source[0] if source else None
    if not isinstance(source, str) or not source.strip():
        return "来源未注明"
    if source.startswith(("unknown_source:", "health_sample:", "body_measurement:")):
        return "来源未注明"
    return source.strip()


def _source_labels(keys):
    keys = list(dict.fromkeys(keys))
    names = {key: source_name(key) for key in keys}
    counts = Counter(names.values())
    positions = Counter()
    labels = {}
    for key in keys:
        name = names[key]
        positions[name] += 1
        labels[key] = name if counts[name] == 1 else f"{name}（来源 {positions[name]}）"
    return labels


def heart_rows(view):
    """Daily canonical values with only human-facing columns."""
    metrics = view.get("workspace_scope", {}).get("metrics", {})
    records = []
    for identity, title, unit in (("STATE-RHR", "静息心率", "次/分"),
                                  ("STATE-SDNN", "HRV（SDNN）", "毫秒")):
        for source, points in (metrics.get(identity, {}).get("value") or {}).items():
            for point in points:
                value, day = _number(point.get("value")), _day(point.get("date"))
                if value is not None and day:
                    records.append((day, title, value, unit, source))
    labels = _source_labels(row[4] for row in records)
    return [{"日期": day, "指标": title, "数值": value, "单位": unit, "来源": labels[source]}
            for day, title, value, unit, source in sorted(records)]


def sleep_rows(view):
    """Positive finite sleep observations for this page, without changing metrics."""
    records = []
    for point in view.get("sleep", {}).get("nights", []):
        value, day = _number(point.get("sleep_hours")), _day(point.get("date"))
        if value is not None and value > 0 and day:
            records.append((day, value, point.get("source")))
    labels = _source_labels(row[2] for row in records)
    return [{"日期": day, "睡眠时长（小时）": value, "来源": labels[source]}
            for day, value, source in sorted(records, key=lambda row: (row[0], str(row[2])))]


def sleep_summary(view):
    groups = defaultdict(list)
    for row in sleep_rows(view):
        groups[row["来源"]].append(row)
    return [{"来源": source, "有效记录日期": len({row["日期"] for row in rows}),
             "有效记录条数": len(rows),
             "平均时长（小时）": sum(row["睡眠时长（小时）"] for row in rows) / len(rows)}
            for source, rows in groups.items()]


def weight_rows(view):
    records = []
    for point in view.get("weight", {}).get("daily", []):
        value, day = _number(point.get("kg")), _day(point.get("date"))
        if value is not None and day:
            records.append((day, value, point.get("source")))
    labels = _source_labels(row[2] for row in records)
    return [{"日期": day, "体重（kg）": value, "来源": labels[source]}
            for day, value, source in sorted(records, key=lambda row: (row[0], str(row[2])))]


def latest_weight_rows(view):
    """Historical reference rows remain separate from the selected-window rows."""
    output = []
    for point in view.get("weight", {}).get("latest_observations", []):
        value, day = _number(point.get("value")), _day(point.get("date"))
        if value is not None and day:
            output.append({"日期": day, "体重（kg）": value, "来源": source_name(point.get("source"))})
    return output


def vo2_rows(view):
    records = []
    for point in view.get("vo2", {}).get("points", []):
        value, day = _number(point.get("normalized_value")), _day(point.get("local_date"))
        if value is not None and value > 0 and day:
            source = str(tuple(point.get(key) for key in
                               ("source_name", "device", "protocol_id", "source_version")))
            records.append((day, value, source))
    labels = _source_labels(row[2] for row in records)
    # The backend orders observations by actual event time. A stable day/source
    # sort preserves same-day order instead of accidentally sorting by value.
    return [{"日期": day, "VO₂ max（mL/kg/min）": value, "来源": labels[source]}
            for day, value, source in sorted(records, key=lambda row: (row[0], row[2]))]


def _local_time(value, zone="Asia/Shanghai"):
    if not value:
        return "未注明"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, AttributeError):
        return "未注明"


def _window(view):
    scope = view.get("workspace_scope", {})
    zone = scope.get("timezone", "Asia/Shanghai")
    st.caption(f"所选范围：{_local_time(scope.get('window_start'), zone)} 至 "
               f"{_local_time(scope.get('window_end'), zone)} · {zone}")


def daily_statistics(rows, field):
    """Summaries keep each declared source/measurement stream separate."""
    grouped = defaultdict(list)
    for row in rows:
        numeric = _number(row.get(field))
        if numeric is not None:
            grouped[row["来源"]].append(row)
    output = []
    for source, items in grouped.items():
        items = sorted(items, key=lambda item: item["日期"])
        numbers = [item[field] for item in items]
        output.append({"source": source, "mean": sum(numbers) / len(numbers),
                       "latest": numbers[-1], "first": numbers[0],
                       "change": numbers[-1] - numbers[0] if len(items) > 1 else None,
                       "first_date": items[0]["日期"], "last_date": items[-1]["日期"],
                       "days": len({row["日期"] for row in items}), "count": len(items),
                       "minimum": min(numbers), "maximum": max(numbers),
                       "minimum_date": items[numbers.index(min(numbers))]["日期"],
                       "maximum_date": items[numbers.index(max(numbers))]["日期"]})
    return sorted(output, key=lambda item: (-item["count"], item["source"]))


def display_points(rows, field, *, limit=400):
    """A display-only envelope keeps actual endpoints and local extrema."""
    groups = defaultdict(list)
    for row in rows:
        groups[row["来源"]].append(row)
    selected = []
    for group in groups.values():
        ordered = sorted(group, key=lambda row: row["日期"])
        if len(ordered) <= limit:
            selected.extend(ordered)
            continue
        width = math.ceil((len(ordered) - 2) / max(1, (limit - 2) // 2))
        indices = {0, len(ordered) - 1}
        for begin in range(1, len(ordered) - 1, width):
            chunk = range(begin, min(begin + width, len(ordered) - 1))
            indices.add(min(chunk, key=lambda index: ordered[index][field]))
            indices.add(max(chunk, key=lambda index: ordered[index][field]))
        selected.extend(ordered[index] for index in sorted(indices))
    return selected


def _chart(rows, value, title, *, observations=False):
    if not rows:
        return
    if px is None:
        st.caption("图表组件暂不可用，仍可展开原始明细查看数值。")
        return
    # Sparse observations remain actual points. No zero-filled days or lines
    # spanning missing dates imply that an intermediate value was measured.
    groups = defaultdict(list)
    for row in rows:
        groups[row["来源"]].append(row)
    contiguous = all(all((date.fromisoformat(b) - date.fromisoformat(a)).days <= 1
                         for a, b in zip(days, days[1:]))
                     for days in [sorted({row["日期"] for row in group}) for group in groups.values()])
    chart_rows = display_points(rows, value)
    factory = px.scatter if observations or not contiguous or len(chart_rows) != len(rows) else px.line
    args = {} if factory is px.scatter else {"markers": True}
    figure = factory(chart_rows, x="日期", y=value, color="来源", **args,
                     color_discrete_sequence=["#38BFA3", "#94A7D6", "#D6B376", "#C79FCB"])
    figure.update_traces(marker={"size": 7}, hovertemplate="%{x|%Y-%m-%d}<br>" + title + "：%{y:.2f}<extra>%{fullData.name}</extra>")
    figure.update_layout(height=280, margin={"t": 12, "b": 32, "l": 12, "r": 12},
                         font={"family": "system-ui, sans-serif", "color": "#F1F5F9"},
                         paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                         legend={"title_text": "", "orientation": "h", "y": -0.22},
                         xaxis={"title": None, "showgrid": False, "type": "date", "tickformat": "%m/%d"},
                         yaxis={"title": title, "gridcolor": "#2B3543", "zeroline": False})
    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False})
    if len(chart_rows) < len(rows):
        st.caption(f"图表保留各段高低观测点（{len(chart_rows)} / {len(rows)}）；统计仍使用全部有效记录。")


def _cards(items):
    if not items:
        return
    columns = st.columns(min(len(items), 4))
    for column, item in zip(columns, items[:4]):
        with column:
            st.metric(item["label"], item["value"])
            if item.get("caption"):
                st.caption(item["caption"])


def _empty(message, key, view=None):
    scope = (view or {}).get("workspace_scope", {})
    old = scope.get("latest_historical_observation_at")
    if old:
        message += " 最近一次历史观测：" + _local_time(old, scope.get("timezone", "Asia/Shanghai")) + "。"
    st.info(message)
    st.button("前往设置导入记录", key=f"body_import_{key}", on_click=_go_settings)


def _go_settings():
    st.session_state["main_workspace"] = "设置"


def _facts(stats, name, unit):
    findings = []
    for item in stats[:2]:
        prefix = f"{item['source']}：" if len(stats) > 1 else ""
        if item["change"] is None:
            findings.append(f"{prefix}{item['last_date']} 有一次{name}记录 "
                            f"{item['latest']:.1f} {unit}；单个点尚不能判断变化。")
        else:
            findings.append(f"{prefix}{item['first_date']} → {item['last_date']}，{name}本期首末记录"
                            f"相差 {item['change']:+.1f} {unit}；共 {item['days']} 个有记录日期。")
    return findings


def next_step_for(stats, domain):
    """A record-checking action tied to this snapshot, without causal inference."""
    if not stats:
        return "先补充同一来源的记录，再查看变化。"
    item = stats[0]
    if item["count"] == 1:
        return (f"目前只有 {item['last_date']} 这一次观测。下一次沿用 {item['source']} 与相同测量方式，"
                "获得第二次记录后再比较方向。")
    if domain == "sleep":
        return (f"先核对 {item['minimum_date']} 的 {item['minimum']:.1f} 小时记录是否覆盖整段睡眠；"
                f"与 {item['maximum_date']}（{item['maximum']:.1f} 小时）的作息和记录完整性对照。")
    if domain == "weight":
        return (f"下一次沿用 {item['source']} 并保持相近称量条件，观察 {item['last_date']} 后的记录"
                "是否延续本期方向；不要用单次波动判断体成分变化。")
    if domain == "cardio":
        return (f"先核对 {item['first_date']} 与 {item['last_date']} 的设备和测量条件是否一致，"
                "下次复测沿用相同方法。对应的跑步、骑行等记录可在“运动”查看。")
    if item["minimum"] == item["maximum"]:
        return f"本期 {item['days']} 个日期的同来源日值相同。继续用同一测量方式记录，先核对来源是否仅保留固定或四舍五入值。"
    return (f"先核对 {item['minimum_date']} 与 {item['maximum_date']} 两个极值日期的测量条件，"
            "继续用同一来源观察，确认变化是否持续；这些数值本身不能确定原因。")


def _findings(findings, *, next_step, caveat=None):
    if findings:
        st.markdown("**本期关键变化**")
        for text in findings[:3]:
            st.write(text)
    if caveat:
        st.caption(caveat)
    st.markdown("**下一步**")
    st.write(next_step)


def _details(view, rows, *, notes=(), summaries=None):
    with st.expander("原始明细", expanded=False):
        if rows:
            page_size = 50
            count = max(1, (len(rows) + page_size - 1) // page_size)
            page = (st.number_input("明细页", 1, count, 1, key="body_details_page")
                    if count > 1 else 1)
            st.dataframe(rows[(page - 1) * page_size:page * page_size], hide_index=True,
                         use_container_width=True)
            st.caption(f"共 {len(rows)} 条本期日值 / 观察值；每页最多 {page_size} 条。")
        else:
            st.caption("本期没有可显示的有效记录。")
    with st.expander("分析依据与范围", expanded=False):
        _window(view)
        scope = view.get("workspace_scope", {})
        st.caption(f"快照计算于 {_local_time(scope.get('cutoff_time'), scope.get('timezone', 'Asia/Shanghai'))}。"
                   "同一页面的卡片、图表、变化与明细使用这份快照。")
        for note in notes:
            st.caption(note)
        for extra in scope.get("extra_metric_windows", {}).values():
            st.caption(extra.get("label", "独立指标窗口"))
        if summaries:
            st.dataframe(summaries, hide_index=True, use_container_width=True)
        versions = sorted({metric.get("algorithm_version", "未注明") for metric in
                           scope.get("metrics", {}).values()})
        if versions:
            st.caption("计算版本：" + "、".join(versions))
        st.caption("缺少记录保持未知；有记录日期不证明完整采集覆盖。首末差描述本期记录，不代表因果或同期变化。")


def _explanation(view, repo):
    from healthzip.ui.health_explanation import render_health_explanation
    context = {}
    workspace = str(repo.path.resolve()) if repo else "standalone"
    if repo:
        from healthzip.workflows.evidence import local_context
        from healthzip.workflows.storage import report_context
        scope = view.get("workspace_scope", {})
        reference = st.session_state.get("analysis_contexts", {}).get(workspace)
        declaration = report_context(repo, reference, scope.get("cutoff_time"), "retrospective")
        context = {"_metric_contexts": {identity: local_context(identity, metric, [], declaration)
                   for identity, metric in scope.get("metrics", {}).items()},
                   "_workspace_path": workspace, "_declaration_reference": reference,
                   "_declaration_values": declaration.get("values", {})}
        if declaration.get("status") == "restricted_requires_reconfirmation":
            st.caption("已选适用信息已撤回或替换；事实保留，相关来源解释请到复盘重新确认。")
    render_health_explanation(view, workspace=workspace, context=context,
                              allow_network=st.session_state.get("health_explanation_network_consent", False))


def render_heart(view, *, repo=None, show_title=True):
    if show_title:
        st.subheader("心率")
    _window(view)
    rows = heart_rows(view)
    cards, sections, findings, primary_stats = [], [], [], []
    for name, unit in (("静息心率", "次/分"), ("HRV（SDNN）", "毫秒")):
        selected = [row for row in rows if row["指标"] == name]
        stats = daily_statistics(selected, "数值")
        if not primary_stats:
            primary_stats = stats
        for item in stats[:2]:
            cards.append({"label": name, "value": f"{item['mean']:.1f} {unit}",
                          "caption": f"日值均值 · {item['days']} 个日期 · {item['source']}"})
        sections.append((name, unit, selected))
        findings.extend(_facts(stats, name, unit))
    _cards(cards)
    for name, unit, selected in sections:
        if selected:
            st.markdown(f"**{name}趋势**")
            _chart(selected, "数值", f"{name}（{unit}）")
        else:
            _empty(f"所选范围内没有{name}记录。可切换上方范围，或在设置导入记录。", name, view if not rows else None)
    if rows:
        _findings(findings, next_step=next_step_for(primary_stats, "heart"),
                  caveat="这里的 HRV 为 SDNN；它与 RMSSD 不可互换，不同设备或协议不会合成一个改善结论。")
        _explanation(view, repo)
    _details(view, rows, notes=("静息心率与 SDNN 按来源、设备、协议和版本分开计算。",
                               "日内优先既有主记录，否则使用日中位数；均值仅包含有记录的日值。"))


def render_sleep(view, *, repo=None, show_title=True):
    if show_title:
        st.subheader("睡眠")
    _window(view)
    rows = sleep_rows(view)
    stats = daily_statistics(rows, "睡眠时长（小时）")
    cards = [{"label": "平均已观察睡眠", "value": f"{item['mean']:.1f} 小时",
              "caption": f"{item['source']} · {item['days']} 个日期"} for item in stats[:2]]
    if len(stats) == 1:
        cards.append({"label": "有记录日期", "value": f"{stats[0]['days']} 天",
                      "caption": f"最近观测 {stats[0]['last_date']}"})
    _cards(cards)
    if rows:
        _chart(rows, "睡眠时长（小时）", "已观察睡眠（小时）")
        _findings(_facts(stats, "已观察睡眠", "小时"),
                  next_step=next_step_for(stats, "sleep"),
                  caveat="按睡眠结束日期展示已观察时长；这些记录尚不能证明整夜完整，也不能仅凭时长判断睡眠质量。")
        _explanation(view, repo)
    else:
        _empty("所选范围内没有有效睡眠时长。缺少记录不代表没有睡眠或未佩戴设备。", "sleep", view)
    omitted = len(view.get("sleep", {}).get("nights", [])) - len(sleep_rows(view))
    notes = ["只统计正时长的睡眠片段；同来源重叠时段按规范计算去重，卧床不自动算作睡眠。"]
    if omitted:
        notes.append(f"另有 {omitted} 条零时长或无效记录，未计入本页有效统计；原始记录保留。")
    _details(view, rows, notes=notes, summaries=sleep_summary(view))


def _expand_weight_window(days):
    st.session_state["analysis_window_days"] = max(int(st.session_state.get("analysis_window_days", 30)), days)
    st.session_state["body_period"] = "自定义"


def _history(view, key):
    history = (latest_weight_rows(view) if key == "weight" else
               _vo2_history_rows(view))
    if not history:
        return False
    latest_day = max(row["日期"] for row in history)
    label = "称重" if key == "weight" else "VO₂max"
    st.info(f"所选范围内无{label}记录，最近一次为 {latest_day}。历史参考不计入当前范围。")
    with st.expander(f"历史参考 · {latest_day}", expanded=False):
        st.dataframe(history, hide_index=True, use_container_width=True)
    if key == "weight":
        scope = view.get("workspace_scope", {})
        cutoff = scope.get("cutoff_time")
        if cutoff:
            cutoff_day = datetime.fromisoformat(cutoff.replace("Z", "+00:00")).astimezone(
                ZoneInfo(scope.get("timezone", "Asia/Shanghai"))).date()
            days = (cutoff_day - date.fromisoformat(latest_day)).days + 1
            if 7 <= days <= 3650:
                st.button(f"查看包含该记录的 {days} 天", key="body_weight_expand_window",
                          on_click=_expand_weight_window, args=(days,))
    return True


def render_weight(view, *, repo=None, show_title=True):
    if show_title:
        st.subheader("体重")
    _window(view)
    rows = weight_rows(view)
    stats = daily_statistics(rows, "体重（kg）")
    cards = [{"label": "最近一次体重", "value": f"{item['latest']:.1f} kg",
              "caption": f"{item['source']} · {item['last_date']}"} for item in stats[:2]]
    if len(stats) == 1 and stats[0]["change"] is not None:
        item = stats[0]
        cards.append({"label": "本期首末差", "value": f"{item['change']:+.1f} kg",
                      "caption": f"{item['first_date']} → {item['last_date']}"})
    _cards(cards)
    if rows:
        _chart(rows, "体重（kg）", "体重（kg）")
        _findings(_facts(stats, "体重", "kg"),
                  next_step=next_step_for(stats, "weight"),
                  caveat="体重记录本身不能区分脂肪、肌肉与其他体成分的变化。")
        _explanation(view, repo)
    elif not _history(view, "weight"):
        _empty("所选范围内无称重记录，尚未找到可显示的历史称重。可切换上方范围或导入记录。", "weight")
    _details(view, rows, notes=("规范体重日值按来源分别汇总；历史参考不进入本期均值和图表。",))


def _vo2_history_rows(view):
    points = view.get("vo2", {}).get("latest_observations", [])
    return vo2_rows({"vo2": {"points": points}})


def render_cardio(view, *, repo=None, show_title=True):
    if show_title:
        st.subheader("有氧")
    _window(view)
    rows = vo2_rows(view)
    field = "VO₂ max（mL/kg/min）"
    stats = daily_statistics(rows, field)
    cards = [{"label": "最近一次 VO₂max", "value": f"{item['latest']:.1f}",
              "caption": f"mL/kg/min · {item['source']} · {item['last_date']}"} for item in stats[:2]]
    if len(stats) == 1:
        cards.append({"label": "本期有效观测", "value": f"{stats[0]['count']} 次",
                      "caption": f"覆盖 {stats[0]['days']} 个日期"})
    _cards(cards)
    if rows:
        _chart(rows, field, "VO₂max（mL/kg/min）", observations=True)
        _findings(_facts(stats, "来源报告 VO₂max", "mL/kg/min"),
                  next_step=next_step_for(stats, "cardio"),
                  caveat="这是来源报告的有氧适能估计；仅凭这些点不能确认真实能力变化或推算训练效率。")
        _explanation(view, repo)
    elif not _history(view, "cardio"):
        _empty("所选范围内没有有效 VO₂max 记录。可切换上方范围，或导入包含有氧适能的记录。", "cardio")
    _details(view, rows, notes=("来源、设备、协议分别展示；图上只显示本期真实观测点。",
                               "若未记录可比较的运动条件，暂不计算有氧效率。"))
