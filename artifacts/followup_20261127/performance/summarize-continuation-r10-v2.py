"""Aggregate retained r10 receipts with each manifest's declared scope (v2).

Run only after run-continuation-r10.py terminates. Final outputs use exclusive
creation. Full audit exports are deliberately never opened by this script.
"""

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
VALIDATION = BASE.parent / "validation"
TIERS = ("personal", "100k", "1m")
LABELS = {"personal": "两年个人", "100k": "10 万压力", "1m": "100 万压力"}
PAGE_PHASES = ("new-process-week", "running-process-week", "running-process-month")
EXPECTED_JOBS = (
    [f"backend-{tier}" for tier in ("100k", "personal", "1m")]
    + [f"browser-report-{tier}" for tier in ("100k", "personal", "1m")]
    + [f"page-{page}-{tier}" for tier in ("100k", "personal", "1m") for page in ("detail", "preview")]
)
TIMINGS = ("first_fact_ms", "facts_and_trend_ms", "interactive_ms")
CONTROLLER_EXTRAS = {
    "pyproject.toml", "uv.lock",
    "tools/followup_report_benchmark.py", "tools/followup_page_benchmark.py",
    "tools/followup_report_browser_benchmark.py", "tools/followup_history_interaction.py",
    "tools/repair_preview_benchmark.py", "tools/repair_measure_run.py",
    "tests/training/strength_workbench_browser_check.py", "tests/training/strength_browser_fixture.py",
}


def relative(path):
    return str(path.relative_to(ROOT))


def p95(values):
    return sorted(values)[math.ceil(0.95 * len(values)) - 1] if values else None


def select(data, keys):
    return {key: data[key] for key in keys if key in data}


def sample_metadata(sample):
    keys = (
        "label", "seconds", "process_peak_rss_kib", "stages", "report_id",
        "markdown_utf8_bytes", "manifest_utf8_bytes", "storage_format",
        "content_ref", "reading_ref", "export_bytes", "object_counts",
        "current_full_analysis_returned", "full_analysis_returned",
        "full_analysis_read", "query_count", "reading_view_version",
        "render_identity", "markdown_sha256", "selected_period",
        "new_plot_dom_verified", "final_rerun_stale_nodes_removed", "one_reading_path",
    )
    result = select(sample, keys)
    result.update({key: value for key, value in sample.items() if key.endswith("_ms")})
    if "snapshot" in sample:
        result["snapshot_server_ms"] = sample["snapshot"].get("serverMs")
    return result


def runner_status(entries):
    labels = [entry.get("label") for entry in entries]
    if labels != EXPECTED_JOBS[:len(labels)]:
        raise ValueError("Runner task identities/order differ from the fixed r10 plan")
    finished = [entry for entry in entries if "finished_unix" in entry and "exit_code" in entry]
    failed = [entry for entry in finished if entry["exit_code"] != 0]
    terminal_failure = bool(entries and entries[-1] in failed and len(finished) == len(entries))
    terminal_success = len(finished) == len(EXPECTED_JOBS) and not failed
    return {
        "terminal": terminal_failure or terminal_success,
        "all_jobs_succeeded": terminal_success,
        "completed_jobs": len(finished),
        "expected_jobs": len(EXPECTED_JOBS),
        "failed_jobs": [entry["label"] for entry in failed],
        "unattempted_jobs": [label for label in EXPECTED_JOBS if label not in labels],
        "incomplete_jobs": [entry["label"] for entry in entries if entry not in finished],
    }


class Summary:
    def __init__(self, expected):
        self.expected = expected
        self.inputs = {}
        self.missing = []
        self.failures = []
        self.budget_failures = []
        self.limitations = []

    def read(self, path, *, required=True):
        if not path.exists():
            if required:
                self.missing.append(relative(path))
            return {}
        raw = path.read_bytes()
        self.inputs[relative(path)] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        try:
            return json.loads(raw)
        except ValueError as exc:
            self.failures.append(f"{relative(path)}: invalid JSON: {exc}")
            return {}

    def expect(self, data, fields, prefix):
        if not data:
            return
        for field, expected in fields.items():
            if field not in data or data[field] != expected:
                self.failures.append(f"{prefix}.{field}: expected {expected!r}, got {data.get(field)!r}")
        if data.get("failure"):
            self.failures.append(f"{prefix}.failure: {data['failure']}")

    def budgets(self, data, prefix):
        for key, value in data.items():
            if isinstance(value, dict):
                self.budgets(value, f"{prefix}.{key}")
            elif value is False:
                self.budget_failures.append(f"{prefix}.{key}")
        return data

    def knowledge_identity(self, data, prefix):
        before = data.get("shared_knowledge_authority_before")
        after = data.get("shared_knowledge_authority_after")
        equal = before == after if before is not None and after is not None else None
        if data and equal is not True:
            self.failures.append(f"{prefix}: shared knowledge authority identities missing or changed")
        return equal

    def manifest(self, path, *, scope="controller", required=True):
        actual = self.read(path, required=required)
        if not actual:
            return {"evidence": relative(path), "available": False, "matches": None}
        runtime_names = {
            key for key in self.expected
            if key.startswith("src/") or key in ("app.py", ".streamlit/config.toml")
        }
        declared_scopes = {
            "runtime": runtime_names,
            "controller": runtime_names | CONTROLLER_EXTRAS,
            "full": set(self.expected),
        }
        required_names = declared_scopes[scope]
        mismatched = [key for key in actual if key in self.expected and actual[key] != self.expected[key]]
        extra = sorted(set(actual) - set(self.expected))
        outside_scope = sorted(set(actual) - required_names)
        missing = sorted(required_names - set(actual))
        result = {
            "evidence": relative(path), "available": True, "file_count": len(actual),
            "comparison_scope": scope, "expected_file_count": len(required_names),
            "scope_definition": {
                "runtime": "all src files plus app.py and .streamlit/config.toml; dependencies and measurement drivers are checked in the controller manifest",
                "controller": "complete runtime scope plus pyproject.toml, uv.lock and eight named measurement driver/fixture files",
                "full": "all files in the frozen r10 source manifest",
            }[scope],
            "mismatched": sorted(mismatched), "outside_frozen_manifest": extra,
            "outside_declared_scope": outside_scope,
            "missing_required_files": missing, "matches": not (mismatched or extra or missing or outside_scope),
        }
        if not result["matches"]:
            self.failures.append(f"{relative(path)}: source identity mismatch")
        return result

    def warm(self, data, samples, prefix, *, backend=False):
        result = {key: value for key, value in data.items() if key != "samples"}
        result["observed_n"] = len(samples)
        keys = ("seconds",) if backend else TIMINGS
        recomputed = {key: p95([row[key] for row in samples if key in row]) for key in keys}
        result["recomputed_nearest_rank_p95"] = recomputed
        if data:
            self.expect(data, {"n": len(samples)}, prefix)
            if len(samples) < 30:
                self.failures.append(f"{prefix}: only {len(samples)} warm samples; requires at least 30")
            for key in keys:
                stored = data.get("p95_s") if backend else data.get(key, {}).get("p95")
                actual = recomputed[key]
                if actual is None or stored is None or not math.isclose(stored, actual, rel_tol=1e-12, abs_tol=1e-9):
                    self.failures.append(f"{prefix}.{key}: stored P95 {stored!r} != recomputed {actual!r}")
        elif samples:
            self.failures.append(f"{prefix}: partial samples have no completed warm summary")
        return result

    def resources(self, path, *, optional=False):
        data = self.read(path, required=not optional)
        if not data:
            self.limitations.append(f"{relative(path)}: peak process-tree RSS not recorded")
            return {"evidence": relative(path), "available": False, "peak_tree_rss_kib": None}
        rows = data.get("samples", [])
        result = {key: value for key, value in data.items() if key != "samples"}
        result.update(evidence=relative(path), available=True, sample_count=len(rows))
        result["sampling_caveat"] = "Periodic live process-tree samples can miss short peaks; CPU values exclude exited children."
        result["first_sample"] = rows[0] if rows else None
        result["last_sample"] = rows[-1] if rows else None
        if rows:
            result["observed_peak_tree_rss_kib"] = max(row["rss_kib"] for row in rows)
            if result.get("peak_tree_rss_kib") != result["observed_peak_tree_rss_kib"]:
                self.failures.append(f"{relative(path)}: reported RSS peak differs from samples")
        if "complete" in data:
            self.expect(data, {"complete": True}, relative(path))
        self.expect(data, {"exit_code": 0}, relative(path))
        return result

    def backend(self, tier):
        folder = BASE / f"continuation-backend-{tier}-r10"
        receipt = self.read(folder / "receipt.json")
        result = {"evidence": relative(folder), "receipt": receipt, "phases": {}}
        result["source_identity"] = self.manifest(folder / "source-manifest.json")
        result["knowledge_authority_equal"] = self.knowledge_identity(receipt, f"{tier}.backend")
        self.expect(receipt, {
            "complete": True, "raw_source_tables_unchanged": True,
            "source_unchanged_across_all_phases": True, "shared_knowledge_authority_unchanged": True,
        }, f"{tier}.backend.receipt")
        for phase in ("generation", "read", "audit"):
            data = self.read(folder / f"{phase}.json")
            samples = data.get("samples", [])
            item = select(data, (
                "complete", "failure", "source_changed", "cutoff", "period", "timezone",
                "interface", "initial_host_load", "final_host_load", "concurrent_load",
                "instrumentation", "os_cache", "reading_payload_utf8_bytes", "cold_queries",
                "referenced_unique_bytes", "offline_reconstruction_exact",
                "offline_workflow_reconstruction_exact", "offline_workflow_verification", "integrity",
                "audit_path", "new_explicit_report_ids",
            ))
            item["samples"] = [sample_metadata(row) for row in samples]
            item["evidence"] = relative(folder / f"{phase}.json")
            item["source_identity"] = self.manifest(folder / data.get("source_manifest", f"{phase}-source.json"))
            item["resources"] = self.resources(folder / f"{phase}-resources.json")
            if phase != "audit":
                hot = [row for row in samples if row.get("label", "").startswith("warm-")]
                item["warm"] = self.warm(data.get("warm", {}), hot, f"{tier}.backend.{phase}.warm", backend=True)
                item["budgets"] = self.budgets(data.get("budgets", {}), f"{tier}.backend.{phase}.budgets")
                item["cold_seconds"] = next((row["seconds"] for row in samples if row.get("label") == "cold"), None)
            else:
                self.expect(data, {"offline_reconstruction_exact": True, "offline_workflow_reconstruction_exact": True}, f"{tier}.backend.audit")
                before = receipt.get("before_raw_tables")
                after = data.get("integrity", {}).get("all_raw_tables_after")
                item["raw_table_hashes_equal"] = before == after if before and after else None
                if item["raw_table_hashes_equal"] is False:
                    self.failures.append(f"{tier}.backend.audit: raw table counts/hashes changed")
            self.expect(data, {"complete": True, "source_changed": False}, f"{tier}.backend.{phase}")
            result["phases"][phase] = item
        return result

    def browser_report(self, tier):
        folder = BASE / f"continuation-browser-report-{tier}-r10"
        summary = self.read(folder / "summary.json")
        result = {
            "evidence": relative(folder),
            "summary": {key: value for key, value in summary.items() if key != "phases"},
            "driver_identity": self.manifest(folder / "source-manifest.json"),
            "measured_source_identity": self.manifest(folder / "measured-source-manifest.json", scope="runtime"),
            "knowledge_authority_equal": self.knowledge_identity(summary, f"{tier}.browser_report"),
            "resources": self.resources(BASE / f"continuation-browser-report-{tier}-r10-resources.json", optional=True),
            "phases": {},
        }
        self.expect(summary, {
            "complete": True, "source_changed": False, "measured_source_changed": False,
            "original_reports_unchanged": True, "shared_knowledge_authority_unchanged": True,
        }, f"{tier}.browser_report")
        for phase in ("generation", "reopen"):
            data = self.read(folder / f"{phase}.json")
            samples = data.get("samples", [])
            item = select(data, (
                "service_clock", "service_ready_ms", "complete", "failure", "distinct_new_report_ids",
                "download_frozen_markdown_exact", "layout_checks", "layout_pass",
                "reading_captures", "reading_captures_pass",
            ))
            item.update(
                evidence=relative(folder / f"{phase}.json"),
                samples=[sample_metadata(row) for row in samples],
                sample_count=len(samples), cold=sample_metadata(samples[0]) if samples else {},
                warm=self.warm(data.get("warm", {}), samples[1:], f"{tier}.browser_report.{phase}.warm"),
                budgets=self.budgets(data.get("budgets", {}), f"{tier}.browser_report.{phase}.budgets"),
            )
            self.expect(data, {
                "complete": True, "layout_pass": True, "reading_captures_pass": True,
                "download_frozen_markdown_exact": True,
            }, f"{tier}.browser_report.{phase}")
            for index, row in enumerate(samples):
                self.expect(row, {
                    "new_plot_dom_verified": True, "final_rerun_stale_nodes_removed": True,
                    "one_reading_path": True,
                }, f"{tier}.browser_report.{phase}.sample[{index}]")
            if phase == "reopen":
                selections = [row.get("preparation", {}) for row in data.get("history_selections", [])]
                compact = [select(row, ("preparation_ms", "attempts", "painted_menu_verified")) for row in selections]
                first_attempts = all(len(row.get("attempts", [])) == 1 and row["attempts"][0].get("complete") is True for row in selections) if selections else None
                item["history_preparation"] = {
                    "samples": compact, "cold_ms": selections[0].get("preparation_ms") if selections else None,
                    "warm_n": max(0, len(selections) - 1),
                    "warm_p95_ms": p95([row["preparation_ms"] for row in selections[1:] if "preparation_ms" in row]),
                    "all_first_attempt_success": first_attempts,
                    "painted_menu_verified": all(row.get("painted_menu_verified") is True for row in selections) if selections else None,
                    "scope": "Menu readiness, real input and option selection; separate from Open click. No combined navigation latency was measured.",
                }
                if data:
                    self.expect(item["history_preparation"], {"all_first_attempt_success": True, "painted_menu_verified": True, "warm_n": 30}, f"{tier}.browser_report.reopen.history_preparation")
            result["phases"][phase] = item
        return result

    def page(self, tier, page):
        folder = BASE / f"continuation-page-{page}-{tier}-r10"
        summary = self.read(folder / "summary.json")
        result = {
            "evidence": relative(folder),
            "summary": {key: value for key, value in summary.items() if key != "phases"},
            "source_identity": self.manifest(folder / "source-manifest.json"),
            "resources": self.resources(BASE / f"continuation-page-{page}-{tier}-r10-resources.json", optional=True),
            "phases": {},
        }
        self.expect(summary, {"complete": True, "source_changed": False}, f"{tier}.page.{page}")
        self.budgets(summary.get("budgets", {}), f"{tier}.page.{page}.budgets")
        for phase in PAGE_PHASES:
            data = self.read(folder / f"{phase}.json")
            hot = data.get("warm", {}).get("samples", data.get("warm_samples", []))
            item = select(data, (
                "complete", "failure", "mode", "period", "service_ready_ms", "browser",
                "health_sample_count", "training_set_count", "full_report_count_before",
                "original_database_bytes", "backup_database_bytes_before",
                "rendered_facts_and_trends_verified", "verified_plot_scope", "full_reports_generated",
            ))
            item.update(
                evidence=relative(folder / f"{phase}.json"), cold=sample_metadata(data.get("cold", {})),
                warm=self.warm(data.get("warm", {}), hot, f"{tier}.page.{page}.{phase}.warm"),
                warm_samples=[sample_metadata(row) for row in hot],
            )
            self.expect(data, {"complete": True, "rendered_facts_and_trends_verified": True, "full_reports_generated": 0}, f"{tier}.page.{page}.{phase}")
            result["phases"][phase] = item
        return result


def number(value, *, divisor=1, digits=3, missing="未完成"):
    return f"{value / divisor:,.{digits}f}" if isinstance(value, (int, float)) else missing


def timing_pair(phase, key="interactive_ms"):
    return f"{number(phase.get('cold', {}).get(key), divisor=1000)} / {number(phase.get('warm', {}).get(key, {}).get('p95'), divisor=1000)}"


def markdown(result):
    status = result["runner_status"]
    regression = result["regression"]["results"]
    lines = [
        "# r10 性能与完整性实测汇总（v2）", "",
        "初版错误地要求运行时清单包含依赖锁文件，形成三项源码身份误报；原脚本与初版 JSON／Markdown 均保留。"
        "v2 按各自声明范围严格核对：运行时清单完整覆盖 232 个 src／入口／配置文件，"
        "控制器清单完整覆盖 242 个文件并另含依赖文件和测量驱动。所有文件内容仍逐个与同一冻结清单核对。"
        "本修订未重跑或改写性能样本。", "",
        f"运行器完成 {status['completed_jobs']}/{status['expected_jobs']} 项；全部进程成功：{status['all_jobs_succeeded']}。"
        "失败后的未运行项明确留空，已有失败和历史结果保留。",
        "冻结源码、逐文件哈希、命令、原始样本、预算及完整性核对见 [JSON](continuation-performance-r10-v2.json)。"
        "原压力夹具保持，统一截止 `2026-11-21T16:00:00+00:00`。",
        f"全量回归：发现 {regression.get('tests_discovered', '未完成')}，执行 {regression.get('tests_executed', '未完成')}，"
        f"通过 {regression.get('counts', {}).get('passed', '未完成')}；失败／错误／跳过分别为 "
        f"{regression.get('counts', {}).get('failure', '未完成')}／{regression.get('counts', {}).get('error', '未完成')}／{regression.get('counts', {}).get('skipped', '未完成')}。", "",
        "热值均列原始样本数并重新核算 nearest-rank P95；冷值是单次。服务就绪单列，不混入点击耗时。"
        "报告冷生成包含本地分析、知识核查和冻结，审计导出与离线还原另计。", "",
        "| 档位 | 后端冷生成 / 热 P95（s） | 浏览器冷生成 / 热 P95（s） | 浏览器冷重开 / 热 P95（s） | 正文 / 阅读载荷（B） |",
        "|---|---:|---:|---:|---:|",
    ]
    for tier, data in result["tiers"].items():
        backend = data["backend"]["phases"]
        browser = data["browser_report"]["phases"]
        generation = backend["generation"]
        first = generation["samples"][0] if generation["samples"] else {}
        lines.append(f"| {LABELS[tier]} | {number(generation.get('cold_seconds'))} / {number(generation['warm'].get('p95_s'), digits=4)}"
                     f" | {timing_pair(browser['generation'])} | {timing_pair(browser['reopen'])}"
                     f" | {number(first.get('markdown_utf8_bytes'), digits=0)} / {number(backend['read'].get('reading_payload_utf8_bytes'), digits=0)} |")
    lines += ["", "| 档位 | 后端冷读 / 热 P95（s） | 历史菜单准备首次 / 热 P95（s） | 菜单热样本 / 全部首试成功 |", "|---|---:|---:|---:|"]
    for tier, data in result["tiers"].items():
        read = data["backend"]["phases"]["read"]
        preparation = data["browser_report"]["phases"]["reopen"]["history_preparation"]
        lines.append(f"| {LABELS[tier]} | {number(read.get('cold_seconds'), digits=4)} / {number(read['warm'].get('p95_s'), digits=4)}"
                     f" | {number(preparation.get('cold_ms'), divisor=1000)} / {number(preparation.get('warm_p95_ms'), divisor=1000)}"
                     f" | {preparation['warm_n']} / {preparation['all_first_attempt_success']} |")
    lines += ["", "历史菜单准备包括就绪、真实输入和选项选择，与点击“打开”后的计时分开；未测完整导航总时钟，不能将 Open 延迟当作整个导航时间。", "",
              "详情冷预算按事实＋趋势，复盘预览冷预算按首批事实；两者热预算均按事实＋趋势。", "",
              "| 档位 / 页面 | 新进程周：首事实 / 趋势（s） | 运行冷周：首事实 / 趋势（s） | 运行冷月：首事实 / 趋势（s） | 热趋势 P95（s / n） |",
              "|---|---:|---:|---:|---:|"]
    for tier, data in result["tiers"].items():
        for page, label in (("detail", "详情"), ("preview", "复盘预览")):
            phases = data["pages"][page]["phases"]
            cells = [f"{number(phases[name]['cold'].get('first_fact_ms'), divisor=1000)} / {number(phases[name]['cold'].get('facts_and_trend_ms'), divisor=1000)}" for name in PAGE_PHASES]
            hot = phases["running-process-month"]["warm"]
            lines.append(f"| {LABELS[tier]} / {label} | " + " | ".join(cells) + f" | {number(hot.get('facts_and_trend_ms', {}).get('p95'), divisor=1000)} / {hot['observed_n']} |")
    lines += ["", "| 档位 | 审计导出（s / B） | 报告还原（s） | 工作流还原（s / 个） | 原始表哈希相同 / 两种还原准确 |", "|---|---:|---:|---:|---|"]
    for tier, data in result["tiers"].items():
        audit = data["backend"]["phases"]["audit"]
        samples = {row["label"]: row for row in audit["samples"]}
        export = samples.get("export", {})
        lines.append(f"| {LABELS[tier]} | {number(export.get('seconds'))} / {number(export.get('export_bytes'), digits=0)}"
                     f" | {number(samples.get('offline_reconstruction', {}).get('seconds'))}"
                     f" | {number(samples.get('offline_workflow_verification', {}).get('seconds'))} / {audit.get('offline_workflow_verification', {}).get('count', '未完成')}"
                     f" | {audit['raw_table_hashes_equal']} / {audit.get('offline_reconstruction_exact')}、{audit.get('offline_workflow_reconstruction_exact')} |")
    lines += ["", "| 档位 | 后端生成 / 读取 / 审计峰值树 RSS（KiB） | 报告浏览器峰值（KiB） | 详情 / 预览峰值（KiB） |", "|---|---:|---:|---:|"]
    for tier, data in result["tiers"].items():
        peaks = [number(data["backend"]["phases"][phase]["resources"].get("peak_tree_rss_kib"), digits=0, missing="未记录") for phase in ("generation", "read", "audit")]
        browser = number(data["browser_report"]["resources"].get("peak_tree_rss_kib"), digits=0, missing="未记录")
        pages = [number(data["pages"][page]["resources"].get("peak_tree_rss_kib"), digits=0, missing="未记录") for page in ("detail", "preview")]
        lines.append(f"| {LABELS[tier]} | {' / '.join(peaks)} | {browser} | {' / '.join(pages)} |")
    lines += ["", "峰值树 RSS 采用周期采样，短峰可能遗漏。浏览器／页面列包含该任务的隔离 Streamlit 与 Chromium，"
              "按整个任务汇总；后端列取各阶段自身回执，不与外层监控重复计数。CPU 与宿主负载原样保留在资源样本中。", "",
              "预算未达：", ""]
    lines.extend([f"- `{failure}`" for failure in result["budget_failures"]] or ["- 已有完成测量无预算失败；未完成项不能据此视为达标。"])
    lines += ["", "验证失败／未完成：", ""]
    issues = result["verification_failures"] + [f"缺少回执：{path}" for path in result["missing_evidence"]]
    issues += [f"运行器未执行：{job}" for job in status["unattempted_jobs"]]
    lines.extend([f"- {issue}" for issue in issues] or ["- 已执行回执未发现内容、来源或执行完整性失败。"])
    lines += ["", "验证边界：", ""]
    lines.extend(f"- {item}" for item in result["limitations"])
    return "\n".join(lines) + "\n"


def main():
    runner_path = BASE / "continuation-r10-runner.json"
    entries = json.loads(runner_path.read_text())
    status = runner_status(entries)
    if not status["terminal"]:
        raise SystemExit("r10 runner is not terminal; refusing to publish a partial final summary")
    output = BASE / "continuation-performance-r10-v2.json"
    if output.exists() or output.with_suffix(".md").exists():
        raise SystemExit("Final r10 output already exists; preserve it and use a separately named revision")
    manifest_path = VALIDATION / "continuation-source-r10.json"
    manifest = json.loads(manifest_path.read_text())
    summary = Summary(manifest["files"])
    summary.read(manifest_path)
    summary.read(runner_path)
    regression_folder = VALIDATION / "continuation-full-r10"
    regression = summary.read(regression_folder / "results.json")
    summary.expect(regression, {"status": "passed", "discovery_count_matches": True, "source_changes_during_run": []}, "regression")
    if regression:
        counts = regression.get("counts", {})
        summary.expect(regression, {"tests_executed": regression.get("tests_discovered")}, "regression")
        summary.expect(counts, {"passed": regression.get("tests_executed"), "failure": 0, "error": 0, "skipped": 0}, "regression.counts")
    for shard in regression.get("shards", []):
        summary.expect(shard, {"exit_code": 0}, f"regression.shard[{shard.get('shard')}]")
    result = {
        "synthetic_only": True, "cutoff": "2026-11-21T16:00:00+00:00",
        "source_manifest": relative(manifest_path), "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "base_commit": manifest.get("base_commit"), "source_root": manifest.get("source_root"),
        "runner_evidence": relative(runner_path), "runner_status": status, "runner_entries": entries,
        "summary_revision": {
            "version": 2,
            "reason": "Correct initial aggregation's manifest-scope mismatch; no source, measurements or budgets changed",
            "script": relative(Path(__file__).resolve()),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "retained_initial_evidence": {
                name: hashlib.sha256((BASE / name).read_bytes()).hexdigest()
                for name in ("summarize-continuation-r10.py", "continuation-performance-r10.json", "continuation-performance-r10.md")
            },
        },
        "regression": {"evidence": relative(regression_folder), "results": regression, "source_identity": summary.manifest(regression_folder / "source-manifest.json", scope="full")},
        "tiers": {tier: {"backend": summary.backend(tier), "browser_report": summary.browser_report(tier), "pages": {page: summary.page(tier, page) for page in ("detail", "preview")}} for tier in TIERS},
        "budget_failures": summary.budget_failures, "verification_failures": summary.failures,
        "missing_evidence": summary.missing, "input_receipts": summary.inputs,
        "limitations": [
            "共享 aarch64 主机有 192 个逻辑 CPU、约 2 TiB RAM；其他宿主负载不受控，不能替代普通设备性能实测。",
            "本任务重测量顺序执行，OS 缓存未清；新进程、服务就绪、运行中新范围、热返回分开计时。",
            "真实 Chromium 交互验证使用新渲染身份、实际数值和图点；实体 iPhone、Safari 与软键盘尚未验证。",
            "隔离测量未配置目标远程模型；远程模型质量、独立专家审定与人体效度未由这些软件测量证明。",
            "完整审计文件仅保留在合成临时工作区；本汇总只读取计量元数据，不打开或复制完整审计包。",
            "原有失败、历史性能和原始样本全部保留；本汇总不覆盖历史证据。",
            *summary.limitations,
        ],
    }
    report = markdown(result)
    with output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    with output.with_suffix(".md").open("x") as stream:
        stream.write(report)
    print(relative(output))


if __name__ == "__main__":
    main()
