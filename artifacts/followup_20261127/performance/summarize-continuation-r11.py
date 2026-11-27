"""Aggregate retained r11 receipts with each manifest's declared scope (v2).

Run only after run-continuation-r11.py terminates. Final outputs use exclusive
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
    + ["browser-report-100k"]
    + [f"page-{page}-{tier}" for tier in ("100k", "personal", "1m") for page in ("detail",)]
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
        raise ValueError("Runner task identities/order differ from the fixed r11 plan")
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
                "full": "all files in the frozen r11 source manifest",
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
        folder = BASE / f"continuation-backend-{tier}-r11"
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
        folder = BASE / f"continuation-browser-report-{tier}-r11"
        summary = self.read(folder / "summary.json")
        result = {
            "evidence": relative(folder),
            "summary": {key: value for key, value in summary.items() if key != "phases"},
            "driver_identity": self.manifest(folder / "source-manifest.json"),
            "measured_source_identity": self.manifest(folder / "measured-source-manifest.json", scope="runtime"),
            "knowledge_authority_equal": self.knowledge_identity(summary, f"{tier}.browser_report"),
            "resources": self.resources(BASE / f"continuation-browser-report-{tier}-r11-resources.json", optional=True),
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
        folder = BASE / f"continuation-page-{page}-{tier}-r11"
        summary = self.read(folder / "summary.json")
        result = {
            "evidence": relative(folder),
            "summary": {key: value for key, value in summary.items() if key != "phases"},
            "source_identity": self.manifest(folder / "source-manifest.json"),
            "resources": self.resources(BASE / f"continuation-page-{page}-{tier}-r11-resources.json", optional=True),
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

def main():
    runner_path = BASE / 'continuation-r11-runner.json'
    entries = json.loads(runner_path.read_text())
    status = runner_status(entries)
    assert status['terminal'], 'Keep running or failed receipts; no partial final summary'
    output = BASE / 'continuation-performance-r11.json'
    assert not output.exists() and not output.with_suffix('.md').exists()
    manifest_path = VALIDATION / 'continuation-source-r11.json'
    manifest = json.loads(manifest_path.read_text())
    summary = Summary(manifest['files'])
    summary.read(manifest_path)
    summary.read(runner_path)
    regression_path = VALIDATION / 'continuation-full-r11/results.json'
    regression = summary.read(regression_path)
    summary.expect(regression, {'status': 'passed', 'discovery_count_matches': True, 'source_changes_during_run': []}, 'regression')
    summary.expect(regression['counts'], {'passed': regression['tests_executed'], 'failure': 0, 'error': 0, 'skipped': 0}, 'regression.counts')
    regression_identity = summary.manifest(regression_path.parent / 'source-manifest.json', scope='full')
    tiers = {tier: {'backend': summary.backend(tier), 'detail': summary.page(tier, 'detail')} for tier in TIERS}
    browser = summary.browser_report('100k')
    result = {'synthetic_only': True, 'base_commit': manifest['base_commit'], 'runner_status': status,
        'source_manifest': relative(manifest_path), 'source_manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'regression': regression, 'regression_source_identity': regression_identity,
        'tiers': tiers, 'browser_report_100k': browser,
        'budget_failures': summary.budget_failures, 'verification_failures': summary.failures,
        'missing_evidence': summary.missing, 'input_receipts': summary.inputs,
        'measurement_scope': 'Three original backend fixtures, three detail browser fixtures, one 100k report browser. Preview and other report browsers were not retested; prior r10 results retain their original identity.',
        'limitations': ['Shared 192 logical CPU aarch64 host, about 2 TiB RAM; external load uncontrolled, OS cache retained.',
            'Task-owned heavy jobs sequential; hot paths have 30 samples; cold samples are individual observations, not P95.',
            'Full audit exports stay outside Git. These receipts only contain synthetic counts, sizes, hashes and timings.',
            'No physical iPhone/Safari, ordinary hardware, target remote model, independent expert or human efficacy validation.',
            *summary.limitations]}
    with output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    lines = ['# r11 冷路径续修实测', '',
        '三个原夹具的后端完整报告、真实浏览器心率详情，以及 100k 浏览器完整报告顺序测量。新进程、运行中首次周/月、热返回、生成、重开和审计分别保存原样本；原 r10 冷预览失败未重测或改称通过。', '',
        '| 夹具 | 后端冷生成 s | 热生成 P95 s | 冷重开 s / 热 P95 s | 审计导出 s / MB |',
        '|---|---:|---:|---:|---:|']
    for tier, data in tiers.items():
        phases = data['backend']['phases']
        generation, reading, audit = (phases[name] for name in ('generation', 'read', 'audit'))
        exported = next(row for row in audit['samples'] if row['label'] == 'export')
        lines.append(f"| {LABELS[tier]} | {generation['cold_seconds']:.3f} | {generation['warm']['p95_s']:.3f} | {reading['cold_seconds']:.3f} / {reading['warm']['p95_s']:.3f} | {exported['seconds']:.3f} / {exported['export_bytes']/1e6:.2f} |")
    lines += ['', '| 夹具 | 新进程详情事实+趋势 s | 运行中冷周 s | 运行中冷月 s | 热事实+趋势 P95 s |', '|---|---:|---:|---:|---:|']
    for tier, data in tiers.items():
        phases = data['detail']['phases']
        values = [phases[p]['cold']['facts_and_trend_ms']/1000 for p in PAGE_PHASES]
        hot = phases['running-process-month']['warm']['recomputed_nearest_rank_p95']['facts_and_trend_ms']/1000
        lines.append(f"| {LABELS[tier]} | {values[0]:.3f} | {values[1]:.3f} | {values[2]:.3f} | {hot:.6f} |")
    lines += ['', '| 100k 真实报告页面 | 冷可交互 s | 热可交互 P95 s |', '|---|---:|---:|']
    for phase, item in browser['phases'].items():
        lines.append(f"| {phase} | {item['cold']['interactive_ms']/1000:.3f} | {item['warm']['recomputed_nearest_rank_p95']['interactive_ms']/1000:.3f} |")
    lines += ['', f"预算失败 {len(summary.budget_failures)} 项；验证失败 {len(summary.failures)} 项；缺少回执 {len(summary.missing)} 项。预算原值未改变。完整冷报告仍须 ≤15 秒，运行中首次详情仍须 ≤3 秒。", '',
        '每档八张原始表、77 项指标、独立未知条件任务、完整审计离线重建和冻结工作流均核对。各阶段峰值进程树 RSS、CPU/宿主负载样本、具体失败项与所有源码清单见 [JSON](continuation-performance-r11.json)。浏览器结束点等待新身份、真实图点、旧节点清除与可交互；历史菜单准备另计，不把打开按钮之后的时间冒充整个导航。', '',
        '共享大机器不能替代普通设备实测；AI 截图审阅、Chromium 实际交互、实体手机和人体效度分别记录。']
    with output.with_suffix('.md').open('x') as stream:
        stream.write('\n'.join(lines) + '\n')
    print(json.dumps({'jobs': status, 'budget_failures': len(summary.budget_failures), 'verification_failures': summary.failures, 'missing': summary.missing}, ensure_ascii=False))


if __name__ == '__main__':
    main()
