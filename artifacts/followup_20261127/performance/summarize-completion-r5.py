"""Summarize retained r5 synthetic measurements; never rerun or replace samples."""

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
VALIDATION = BASE.parent / "validation"


def read(path):
    return json.loads(path.read_text())


def relative(path):
    return str(path.relative_to(ROOT))


def milliseconds(sample):
    return {k: v for k, v in sample.items() if k.endswith("_ms")}


def warm(summary):
    return {k: v for k, v in summary.items() if k != "samples"}


def summarize_tier(tier):
    backend = BASE / f"completion-backend-{tier}-r5"
    receipt = read(backend / "receipt.json")
    generation = read(backend / "generation.json")
    reopening = read(backend / "read.json")
    audit = read(backend / "audit.json")
    report = BASE / f"completion-browser-report-{tier}-r5"
    driver2 = BASE / f"completion-browser-report-{tier}-r5-driver2"
    if driver2.exists():
        report = driver2
    browser = read(report / "summary.json")
    result = {
        "fixture": receipt["fixture"],
        "raw_table_counts": {k: v["rows"] for k, v in receipt["before_raw_tables"].items()},
        "original_database_bytes": receipt["original_database_bytes"],
        "backend": {
            "evidence": relative(backend),
            "complete": receipt["complete"],
            "cold_generation_s": generation["samples"][0]["seconds"],
            "generation_warm": generation["warm"],
            "generation_budgets": generation["budgets"],
            "cold_read_s": reopening["samples"][0]["seconds"],
            "read_warm": reopening["warm"],
            "read_budgets": reopening["budgets"],
            "markdown_utf8_bytes": generation["samples"][0]["markdown_utf8_bytes"],
            "reading_payload_utf8_bytes": reopening["reading_payload_utf8_bytes"],
            "phase_rss_and_wall": receipt["phases"],
            "audit_samples": audit["samples"],
            "audit_report_exact": audit["offline_reconstruction_exact"],
            "audit_workflows_exact": audit["offline_workflow_reconstruction_exact"],
            "audit_workflow_count": audit["offline_workflow_verification"]["count"],
            "integrity": audit["integrity"],
            "raw_source_tables_unchanged": receipt["raw_source_tables_unchanged"],
            "source_unchanged_across_all_phases": receipt["source_unchanged_across_all_phases"],
            "knowledge_unchanged": receipt["shared_knowledge_authority_unchanged"],
            "knowledge_identity": receipt["shared_knowledge_authority_before"],
            "host": {k: receipt[k] for k in ("platform", "cpu_count", "memory", "concurrent_load")},
        },
        "browser_report": {
            "evidence": relative(report),
            "complete": browser["complete"],
            "driver_workspace_changed": browser["source_changed"],
            "measured_source_changed": browser["measured_source_changed"],
            "original_reports_unchanged": browser["original_reports_unchanged"],
            "knowledge_unchanged": browser["shared_knowledge_authority_unchanged"],
            "host_load": {k: browser[k] for k in ("initial_host_load", "final_host_load")},
            "phases": {},
        },
        "pages": {},
        "budget_failures": [],
        "verification_failures": [],
    }
    for phase in ("generation", "reopen"):
        item = read(report / f"{phase}.json")
        result["browser_report"]["phases"][phase] = {
            "cold": milliseconds(item["samples"][0]),
            "warm": warm(item["warm"]),
            "sample_count": len(item["samples"]),
            "service_ready_ms": item["service_ready_ms"],
            "complete": item["complete"],
            "budgets": item["budgets"],
            "layout_pass": item["layout_pass"],
            "reading_captures_pass": item["reading_captures_pass"],
            "download_frozen_markdown_exact": item["download_frozen_markdown_exact"],
        }
        if phase == "reopen":
            selections = [row["preparation"] for row in item["history_selections"]]
            hot = sorted(row["preparation_ms"] for row in selections[1:])
            result["browser_report"]["history_selection_preparation"] = {
                "cold_ms": selections[0]["preparation_ms"],
                "warm_n": len(hot), "warm_p95_ms": hot[math.ceil(0.95 * len(hot)) - 1],
                "all_first_attempt_success": all(len(row["attempts"]) == 1 and row["attempts"][0]["complete"] for row in selections),
                "painted_menu_verified": all(row["painted_menu_verified"] for row in selections),
                "scope": "menu readiness, real input and option selection; separate from Open click timing, not a combined navigation latency",
            }
    for page in ("detail", "preview"):
        folder = BASE / f"completion-browser-{page}-{tier}-r5"
        summary = read(folder / "summary.json")
        phases = {}
        for name in ("new-process-week", "running-process-week", "running-process-month"):
            item = read(folder / f"{name}.json")
            phases[name] = {
                "cold": milliseconds(item["cold"]),
                "warm": warm(item.get("warm", {})),
                "service_ready_ms": item["service_ready_ms"],
                "complete": item["complete"],
                "rendered_facts_and_trends_verified": item["rendered_facts_and_trends_verified"],
                "full_reports_generated": item["full_reports_generated"],
            }
        result["pages"][page] = {
            "evidence": relative(folder), "complete": summary["complete"],
            "source_changed": summary["source_changed"], "budgets": summary["budgets"],
            "host_load": {k: summary[k] for k in ("initial_host_load", "final_host_load")},
            "phases": phases,
        }

    def check(node, trail=()):
        if isinstance(node, dict):
            for key, value in node.items():
                path = (*trail, key)
                if value is False:
                    if any("budget" in part for part in path):
                        result["budget_failures"].append(".".join(path))
                    elif key not in ("source_changed", "measured_source_changed", "driver_workspace_changed"):
                        result["verification_failures"].append(".".join(path))
                elif value is True and key in ("source_changed", "measured_source_changed"):
                    result["verification_failures"].append(".".join(path))
                else:
                    check(value, path)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                check(value, (*trail, str(i)))

    check(result)
    return result


def main():
    manifest = VALIDATION / "completion-source-r5.json"
    result = {
        "source_manifest": relative(manifest),
        "source_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "source_root": "/home/sn_maozhifang/healthzip-followup-validation-tmp/source-r5",
        "cutoff": "2026-11-21T16:00:00+00:00",
        "plan": relative(VALIDATION / "completion-run-plan-r5.json"),
        "browser_driver_changes": {
            "diagnosis": relative(BASE / "completion-browser-report-100k-r5-driver-diagnosis.json"),
            "retained_failed_attempt": relative(BASE / "completion-browser-report-100k-r5"),
            "personal_original": "original r5 driver results retained; repeated under driver2 for final strict completion boundary",
            "all_three_tiers": "driver2 from working tree, frozen r5 product; exact chart and stale-node cleanup required before interactive completion",
            "command_receipts": [relative(BASE / f"completion-browser-report-{tier}-r5-driver2-command.json") for tier in ("personal", "100k", "1m")],
        },
        "synthetic_only": True,
        "limitations": [
            "Shared 192 logical CPU host; other host load uncontrolled and recorded.",
            "OS caches were not cleared; process-cold and running-new-range are separate.",
            "Chromium actual DOM identities/values/plots; no physical iPhone/Safari/keyboard validation.",
            "No target remote model or ordinary-device performance claim.",
            "r5 excludes later question-page empty-state changes, validated separately.",
            "All old failed evidence retained; this summary does not supersede those samples.",
            "100k original browser attempt stopped at stale preview assertion without a completed timing sample; separately documented driver2 rerun does not rewrite it.",
            "Full audits retained only in synthetic workspace; public files contain measurement metadata.",
        ],
        "tiers": {tier: summarize_tier(tier) for tier in ("personal", "100k", "1m")},
    }
    output = BASE / "completion-performance-r5.json"
    with output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    lines = [
        "# r5 最终性能测量", "",
        "三档原合成夹具顺序实测，固定截止为 `2026-11-21T16:00:00+00:00`。"
        "全部热测为 30 次 nearest-rank P95，冷值均为单次。"
        "源码冻结身份、原始样本路径、实际数据量、预算及内容核验见 [JSON](completion-performance-r5.json)。", "",
        "共享 aarch64 宿主有 192 个逻辑 CPU、约 2 TiB RAM；其他宿主负载不受控并逐阶段记录，"
        "本团队重任务顺序运行，OS 缓存保留。以下不是普通设备、实体 iPhone/Safari、软键盘或目标远程模型验收。"
        "后续问题页空状态补修另有验证，不属于 r5 性能源码。", "",
        "报告计时包括必要本地分析、核查与冻结；浏览器从实际点击到新报告 ID、真实发现、图表和可交互完成。"
        "服务就绪时间单独保存在 JSON，未混入点击计时。完整审计另计，不用日常可读正文的时间代替。", "",
        "10 万首次页面验收在最终 rerun 尚未清理旧预览时失败，未取得完整计时样本；"
        "[失败与驱动诊断](completion-browser-report-100k-r5-driver-diagnosis.json)保留。"
        "三档正式报告表统一使用单独留有哈希的 driver2 等待真实冻结图点与全部 stale 节点清理，"
        "个人旧驱动样本另保留，产品仍为原 r5。", "",
        "| 档位 | 后端冷生成 / 热 P95（s） | 浏览器冷生成 / 热 P95（s） | 浏览器冷重开 / 热 P95（s） | 正文（B） |",
        "|---|---:|---:|---:|---:|",
    ]
    labels = {"personal": "两年个人", "100k": "10 万压力", "1m": "100 万压力"}
    for name, tier in result["tiers"].items():
        backend = tier["backend"]
        phases = tier["browser_report"]["phases"]
        generation, reopen = phases["generation"], phases["reopen"]
        lines.append(
            f"| {labels[name]} | {backend['cold_generation_s']:.3f} / {backend['generation_warm']['p95_s']:.4f}"
            f" | {generation['cold']['interactive_ms']/1000:.3f} / {generation['warm']['interactive_ms']['p95']/1000:.3f}"
            f" | {reopen['cold']['interactive_ms']/1000:.3f} / {reopen['warm']['interactive_ms']['p95']/1000:.3f}"
            f" | {backend['markdown_utf8_bytes']:,} |")
    lines.extend(["", "历史菜单准备、真实输入及选择与点击“打开”后的读取计时分开：", ""])
    for name, tier in result["tiers"].items():
        selection = tier["browser_report"]["history_selection_preparation"]
        lines.append(f"- {labels[name]}：首次准备 {selection['cold_ms']/1000:.3f} 秒，"
            f"30 热准备 P95 {selection['warm_p95_ms']/1000:.3f} 秒；"
            f"31 次均首试成功：{selection['all_first_attempt_success']}。")
    lines.extend(["", "上述各阶段不能冒充从展开菜单到报告完成的整个导航时钟；没有用失败后重试的成功值替代首试。"])
    lines.extend(["", "详情冷完成以事实＋趋势计；复盘预览冷预算以首批事实计，同时保留趋势时间。新进程直开与运行中冷范围分开。", "",
        "| 档位 / 页面 | 新进程周：首事实 / 趋势（s） | 运行冷周：首事实 / 趋势（s） | 运行冷月：首事实 / 趋势（s） | 30 热趋势 P95（s） |",
        "|---|---:|---:|---:|---:|"])
    for name, tier in result["tiers"].items():
        for page in ("detail", "preview"):
            phases = tier["pages"][page]["phases"]
            cells = []
            for phase in ("new-process-week", "running-process-week", "running-process-month"):
                cold = phases[phase]["cold"]
                cells.append(f"{cold['first_fact_ms']/1000:.3f} / {cold['facts_and_trend_ms']/1000:.3f}")
            hot = phases["running-process-month"]["warm"]["facts_and_trend_ms"]["p95"] / 1000
            page_label = "详情" if page == "detail" else "复盘预览"
            lines.append(f"| {labels[name]} / {page_label} | " + " | ".join(cells) + f" | {hot:.3f} |")
    lines.extend(["", "| 档位 | 审计导出（s / B） | 报告还原（s） | 全部工作流核对（s / 个） | 生成 / 审计峰值树 RSS（KiB） |",
        "|---|---:|---:|---:|---:|"])
    for name, tier in result["tiers"].items():
        backend = tier["backend"]
        samples = {sample["label"]: sample for sample in backend["audit_samples"]}
        peaks = {phase["phase"]: phase["peak_tree_rss_kib"] for phase in backend["phase_rss_and_wall"]}
        lines.append(f"| {labels[name]} | {samples['export']['seconds']:.3f} / {samples['export']['export_bytes']:,}"
            f" | {samples['offline_reconstruction']['seconds']:.3f}"
            f" | {samples['offline_workflow_verification']['seconds']:.3f} / {backend['audit_workflow_count']}"
            f" | {peaks['generation']:,.0f} / {peaks['audit']:,.0f} |")
    lines.extend(["", "峰值树 RSS 为后端阶段的周期采样；各进程自身峰值另随原样本保留。"
        "全审计文件仅留在合成临时工作区，公开工件只含计量元数据。", "", "预算未达：", ""])
    for name, tier in result["tiers"].items():
        for failure in tier["budget_failures"]:
            lines.append(f"- {labels[name]}：`{failure}`。")
        for failure in tier["verification_failures"]:
            lines.append(f"- 内容或执行验证失败，{labels[name]}：`{failure}`。")
    lines.extend(["", "原样本、早轮失败、600 秒页面超时和旧性能回执均保留，"
        "本轮成功不覆盖或改写它们。源码与公共知识权威身份、八张原始表不变及实际文件逐报告/逐工作流还原分别核对。", ""])
    with output.with_suffix(".md").open("x") as stream:
        stream.write("\n".join(lines))
    print(relative(output))


if __name__ == "__main__":
    main()
