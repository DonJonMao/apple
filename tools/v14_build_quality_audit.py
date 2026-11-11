"""Link the 12 QAL contracts to executed tests and actual independent traces."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from healthzip.science import evaluate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/v14/knowledge"


def main():
    matrix = json.loads((ROOT / "Apple_v1.4_Codex_Execution_Pack/metric_revision_matrix.json").read_text())
    suite = ET.parse(OUT / "knowledge-tests.xml").getroot()
    tests = list(suite.iter("testcase"))
    passed = {c.attrib["name"] for c in tests if not any(c.find(key) is not None for key in ("failure", "error", "skipped"))}
    assert len(passed) == len(tests)
    actual = json.loads((OUT / "independent_frozen_public.json").read_text())["quality_metrics"]
    by_id = {m["metric_id"]: m for m in actual["metrics"]}
    changes = {
        1: "Reviewed sufficient paths, actual retrieved source/version/span identities, unknown gold excluded.",
        2: "Unique span units, unjudged precision bounds and duplicate accounting; source family retained.",
        3: "Exact hashes/locators/current versions separate from independently labeled evidence-bundle support.",
        4: "Unjudged support remains lower/upper bounded; independent AI and human denominators separate.",
        5: "Observed applicability errors distinguished from unjudged scope and upper bound.",
        6: "Numeric/causal labels require explicit annotations; absent classifications do not establish zero error.",
        7: "Answerable and insufficient tasks separate; unscorable cases retain observed error bounds.",
        8: "Request-level fallback deduplication, reason counts and incomplete-trace lower/upper bounds.",
        9: "Source acquisition, content review, independent review, effective claims and unique application-rule coverage separated.",
        10: "Access trace and violation denominator; absent access traces are not release approval.",
        11: "External deterministic references compare identity/unit/formula/interval/rounding; absent references stay unknown.",
        12: "Exact current source versions, rights, withdrawal/correction and identity checked; superseded parses excluded.",
    }
    rows = []
    for metric in matrix["metrics"]:
        identity = metric["metric_id"]
        if not identity.startswith("QAL-"):
            continue
        refs = metric["existing_test_refs"]
        assert refs and all(ref.split("::")[-1] in passed for ref in refs), identity
        empty = evaluate(identity, [], cutoff_time="2026-11-11T12:00:00Z", window_start="2026-11-01T00:00:00Z", window_end="2026-11-12T00:00:00Z")
        assert "metric_execution_failed" not in empty["reason_codes"]
        rows.append({"metric_id": identity, "revision_action": metric["revision_action"],
            "planned_behavior_reviewed": metric["planned_behavior"], "targeted_acceptance_reviewed": metric["targeted_acceptance"],
            "review_result": "implementation_reviewed_and_bounded_software_cases_passed",
            "implemented_accounting": changes[int(identity.split("-")[1])], "runtime_unit": empty["unit"],
            "empty_input_data_status": empty["data_status"], "actual_trace_data_status": by_id[identity]["data_status"],
            "actual_trace_value": by_id[identity]["value"], "passed_test_refs": refs,
            "implementation_paths": ["src/healthzip/science/evaluation.py", "src/healthzip/knowledge/quality.py"],
            "actual_trace_artifact": "artifacts/v14/knowledge/independent_frozen_public.json#quality_metrics",
            "scientific_validation_boundary": metric["scientific_validation_boundary"],
            "coverage_limit": "18 purposively selected actual-source questions, independently authored and AI reviewed; not population accuracy or human/expert validation. Missing numerical/access references remain empty denominators."})
    assert len(rows) == 12
    value = {"review_baseline": matrix["review_head"], "metric_count": 12, "algorithm_version": empty["algorithm_version"],
        "verification_test_cases": len(tests), "all_verification_cases_passed": True,
        "new_human_or_expert_approvals_created": 0, "independent_ai_semantic_reviews": 18,
        "scope": "12 QAL unified executors plus actual source/annotation adapter; original 3/18 independent result retained.", "metrics": rows}
    (OUT / "metric_audit_12.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"metrics": len(rows), "passed_tests": len(tests)}))


if __name__ == "__main__":
    main()
