"""Local Markdown report renderer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Union


def _card(card: dict[str, Any]) -> str:
    w = card.get("window", {})
    lines = [
        f"### {card.get('title', '')}",
        f"状态：`{card.get('status')}`",
        f"时间范围：{w.get('start') or '—'} 至 {w.get('end') or '—'}",
        "",
        card.get("summary", ""),
    ]
    if card.get("facts"):
        lines += ["", "事实："]
        for f in card["facts"]:
            lines.append(
                f"- `{f.get('metric')}`：{f.get('value')} {f.get('unit', '')}（样本/日期 {f.get('n_days', f.get('n', '—'))}）"
            )
    if card.get("limitations"):
        lines += ["", "限制："]
        lines += [f"- {x}" for x in card["limitations"]]
    if card.get("allowed_actions"):
        lines += ["", "允许的下一步：" + "、".join(card["allowed_actions"])]
    return "\n".join(lines)


def render_report(
    analysis: dict[str, Any], inventory: dict[str, Any], output: Union[str, Path]
) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Health ZIP Workbench 本地分析报告",
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat()}",
        "",
        "> 本报告仅整理和解释导入数据，不是医疗诊断，也不把缺失记录解释为没有佩戴、没有睡眠或没有进食。",
        "",
        "## 数据盘点",
        "",
        "|规范化类型|原始类型|样本数|有效日期|起始|结束|来源数|",
        "|---|---|---:|---:|---|---|---:|",
    ]
    for row in inventory.get("sample_types", []):
        lines.append(
            f"|{row.get('canonical_type') or '未知'}|{row.get('raw_type')}|{row.get('n')}|{row.get('observed_days')}|{row.get('first_date') or '—'}|{row.get('last_date') or '—'}|{row.get('source_count')}|"
        )
    lines += ["", "## Evidence Cards", ""]

    def walk(obj):
        if isinstance(obj, dict):
            if "id" in obj and "title" in obj and "status" in obj:
                yield obj
            else:
                for value in obj.values():
                    yield from walk(value)
        elif isinstance(obj, list):
            for value in obj:
                yield from walk(value)

    seen = set()
    card_source = ({key: analysis[key] for key in ("workouts", "vo2", "nutrition", "cycle") if key in analysis}
                   if analysis.get("v13") else analysis)
    for card in walk(card_source):
        if card["id"] in seen:
            continue
        seen.add(card["id"])
        lines.append(_card(card))
        lines.append("")
    strength_quality = analysis.get("strength_quality") or {}
    if not analysis.get("v13") and (strength_quality.get("series") or strength_quality.get("sessions")):
        lines += ["## P1 力量与身体状态", ""]
        lines.append("### 可比动作条件")
        lines.append("")
        lines.append("|动作|器械|变式|训练暴露|组数|e1RM 变化（kg）|e1RM 斜率（kg/次）|")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        for item in strength_quality.get("series", []):
            lines.append(
                f"|{item.get('exercise_name') or '—'}|{item.get('equipment') or '—'}|"
                f"{item.get('variation') or '—'}|{item.get('exposures', '—')}|{item.get('records', '—')}|"
                f"{item.get('e1rm_change_kg') if item.get('e1rm_change_kg') is not None else '—'}|"
                f"{item.get('e1rm_slope_kg_per_exposure') if item.get('e1rm_slope_kg_per_exposure') is not None else '—'}|"
            )
        lines += ["", "### 逐场训练记录", ""]
        lines.append("|日期|正式组|同条件负荷×次数（kg·次）|最高 e1RM（kg）|中位 RPE|中位 RIR|负荷算法|")
        lines.append("|---|---:|---:|---:|---:|---:|---|")
        for item in strength_quality.get("sessions", []):
            lines.append(
                f"|{item.get('date')}|{item.get('sets', '—')}|"
                f"{item.get('volume_kg') if item.get('volume_kg') is not None else '—'}|"
                f"{item.get('top_e1rm_kg') if item.get('top_e1rm_kg') is not None else '—'}|"
                f"{item.get('median_rpe') if item.get('median_rpe') is not None else '—'}|"
                f"{item.get('median_rir') if item.get('median_rir') is not None else '—'}|"
                f"{item.get('load_method', '—')}|"
            )
        association = analysis.get("body_state_strength") or {}
        joins = association.get("joins") or []
        lines += ["", "### 身体状态对齐", ""]
        lines.append(
            f"已对齐 {sum(1 for row in joins if row.get('body_state'))} / {len(joins)} 次力量训练（训练前已发生且当时已知）。"
        )
        lines.append(
            "该表是时间邻近的描述性关联，不证明身体状态导致训练表现变化；缺失记录保持未知。"
        )
        if association.get("paired_metrics"):
            lines += ["", "配对状态与做组质量的描述统计：", ""]
            lines.append(
                "|身体指标|配对样本|身体中位数|同条件负荷×次数中位数（kg·次）|最高 e1RM 中位数（kg）|中位 RPE|中位 RIR|"
            )
            lines.append("|---|---:|---:|---:|---:|---:|---:|")
            for item in association["paired_metrics"]:
                lines.append(
                    f"|{item.get('body_metric')}|{item.get('n')}|{item.get('body_median')}|"
                    f"{item.get('volume_median_kg') if item.get('volume_median_kg') is not None else '—'}|"
                    f"{item.get('top_e1rm_median_kg') if item.get('top_e1rm_median_kg') is not None else '—'}|"
                    f"{item.get('median_rpe') if item.get('median_rpe') is not None else '—'}|"
                    f"{item.get('median_rir') if item.get('median_rir') is not None else '—'}|"
                )
        for label, key in (("本周", "week_report"), ("本月", "month_report")):
            report = analysis.get(key) or {}
            card = report.get("card") or {}
            if not card:
                continue
            lines += ["", f"### {label}力量报告", "", card.get("summary", "")]
            comparison = report.get("comparison") or {}
            lines.append(
                f"周期：{report.get('start', '—')} 至 {report.get('end', '—')}；"
                f"同条件负荷×次数变化：{comparison.get('volume_delta_kg') if comparison.get('volume_delta_kg') is not None else '无法比较'} kg·次。"
            )
            if report.get("recommendations"):
                lines.append("下一周期建议：")
                lines.extend(f"- {item}" for item in report["recommendations"])
    snapshots = [("v1.3 统一指标", analysis.get("v13"))]
    snapshots.extend(("本周完整指标" if period == "week" else "本月完整指标", value)
                     for period, value in analysis.get("period_snapshots", {}).items())
    for title, v13 in snapshots:
        if not v13:
            continue
        import json
        lines += [f"## {title}", "", f"数据截止：{v13['cutoff_time']}；算法：{v13['algorithm_version']}；窗口：{v13['window_start']} 至 {v13['window_end']}", "",
                  "|指标|数值|单位|数据状态|证据身份|有效/总数|原因|", "|---|---|---|---|---|---|---|"]
        metrics = v13["metrics"].values() if isinstance(v13["metrics"], dict) else v13["metrics"]
        for metric in metrics:
            value = "未知" if metric["value"] is None else json.dumps(metric["value"], ensure_ascii=False)
            lines.append(f"|{metric['metric_id']}|{value.replace('|', '/')}|{metric['unit'] or '—'}|{metric['data_status']}|{metric['evidence_status']}|{metric['valid_n']}/{metric['total_n']}|{'；'.join(metric['reason_codes'])}|")
        lines += ["", "完整合同（含窗口、记录ID、参数、区间、证据和算法版本）：", "", "```json",
                  json.dumps(v13, ensure_ascii=False, indent=2, default=str), "```", ""]
    lines += ["## 质量与缺口", ""]
    for key, value in analysis.get("readiness", {}).items():
        lines.append(
            f"- **{key}**：`{value.get('status')}`；{value.get('missing') or '当前门槛已满足或可初步展示'}"
        )
    lines += [
        "",
        "## 实施限制",
        "",
        "- 所有计算在本机完成，未调用 AI API。",
        "- 原始 Apple 健康数据保留来源、单位、时间和导入批次；派生结论带算法版本。",
        "- 需要更多数据时只展示缺口，不生成强行结论。",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    return output
