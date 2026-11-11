"""Run frozen regressions and publish only evidence metadata, never source prose."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.adjudication import annotation_identity, score_frozen_annotations
from healthzip.knowledge.evaluation import evaluate
from healthzip.knowledge.quality import run_quality
from healthzip.knowledge.store import digest, now
from healthzip.science.rag_fixtures import metric_provider

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "artifacts/v14/knowledge"
PRIVATE = ROOT / ".local/v14-knowledge-evaluation"


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


projection = module(ROOT / "tools/prepare_public_artifacts.py", "artifact_projection")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def publish(name, value):
    private = PRIVATE / name
    write(private, value)
    projected, _ = projection.project_evaluation(deepcopy(value), digest(private.read_bytes()))
    # Some independent packets contain a parallel evidence-reading packet.
    for case in projected["cases"]:
        case.pop("review_packet", None)
    projected = json.loads(projection.redact_local_paths(json.dumps(projected, ensure_ascii=False)))
    for case in projected["cases"]:
        case["public_output_sha256"] = digest(projection.canonical(case["output"]).encode())
    write(PUBLIC / name, projected)
    return projected


class Partition:
    def __init__(self, w, roles):
        self.w, self.roles = w, roles

    def __getattr__(self, key):
        return getattr(self.w, key)

    def query(self, question, **kwargs):
        kwargs["context"] = {**kwargs.get("context", {}), "corpus_roles": self.roles}
        return self.w.query(question, **kwargs)


def fixed_evaluations(w):
    results = []
    for name, roles in (("core", ["core"]), ("core_research", ["core", "research"])):
        for dataset, split in (("rag_eval_cases", "visible_development"), ("rag_holdout", "unchanged_fixed_holdout_no_tuning")):
            value = evaluate(Partition(w, roles), ROOT / "src/healthzip/knowledge/data" / (dataset + ".json"),
                             split=split, metric_provider=metric_provider)
            value["corpus_partitions"] = roles
            value["metrics_data_kind"] = "explicit synthetic development metric fixtures; source claims use the actual local corpus"
            publish(f"{dataset}_{name}.json", value)
            results.append({"dataset": dataset, "partitions": roles, "dataset_sha256": value["dataset_sha256"], "counts": value["counts"]})
    return results


def old_failures_replay():
    old_path = ROOT / "artifacts/review/rag_semantics_frozen.json"
    annotations_path = ROOT / "artifacts/review/rag_semantics_independent_ai_annotations.json"
    old = json.loads(old_path.read_text())
    annotations = {a["case_id"]: a for a in json.loads(annotations_path.read_text())["annotations"]}
    original = module(ROOT / "tests/review_rag_freeze.py", "old_synthetic_fixture")
    result = {"data_kind": "synthetic_software_regression_only", "original_packet_sha256": digest(old_path.read_bytes()),
        "original_annotations_sha256": digest(annotations_path.read_bytes()), "original_independent_ai_score_unchanged": "7/10",
        "reviewer_kind": "implementation_self_review", "independent_human_denominator": 0,
        "change": "Compositional task contracts plus explicit new content review. NEW-06 relation is corrected by a new review, not automatically inferred from keywords.", "counts": {}, "cases": []}
    for case in old["cases"]:
        cid = case["case_id"]
        if cid not in {"NEW-02", "NEW-05", "NEW-06"}:
            continue
        device = cid == "NEW-05"
        text = ("在这项虚构温度计试验中，四周组均偏差不构成每个人每天的误差界限；没有测量明日个人体温。" if device
                else "在这项虚构成人方案中，增加重复次数是允许的选项；未测量寿命，不提供个人效果保证。")
        statement = ("该温度计试验未测量明日个人体温，因此不能据此确定你明日的绝对体温。" if device
                     else "该方案未测量寿命，不能据此证明个人寿命增长；这也不证明没有效应。" if cid == "NEW-02"
                     else "该虚构成人方案允许增加重复次数，但没有个人效果保证。")
        with tempfile.TemporaryDirectory() as folder:
            w = KnowledgeWorkbench(folder, environment_kind="synthetic_test")
            w.seed()
            source = "E8" if device else "S5"
            raw = text.encode()
            version = w.lib.record_version(source, raw, "fulltext", {}, {}, {"license_id": "CC0", "index_allowed": True}, "matched",
                [{"text": text, "locator": {"synthetic_line": 1}}], "synthetic-review-1")
            span = version + ":s00000"
            outcome = "personal_temperature" if device else "longevity" if cid == "NEW-02" else "progression_options"
            claim = {"claim_id": "V14-REGRESSION-" + cid, "version": "2", "statement": statement,
                "scope": {"population": "synthetic_only", "time_scale": "source_protocol_only"}, "limitations": ["虚构软件回归，不是真实研究。"],
                "evidence_links": [{"source_id": source, "source_version_id": version, "span_ids": [span]}],
                "answer_task": {"subject": "device_measurement" if device else "resistance_training", "outcome": outcome,
                    "requested_relation": "options" if cid == "NEW-06" else "individual_inference", "answer_complete": True,
                    "evidence_relation": "supports" if cid == "NEW-06" else "refutes", "routes": ["energy" if device else "progression"],
                    "answer_parts": [{"text": statement, "span_ids": [span]}]}}
            w.review_claim(claim, {"reviewer": "Codex implementing agent; synthetic fixture content re-review", "reviewer_kind": "synthetic_fixture",
                "reviewed_at": now(), "content_checked": True, "rationale": "Read preserved invented source; explicitly states the option or unmeasured-outcome limitation."})
            question = next(x[1] for x in original.CASES if x[0] == cid)
            output = w.query(question, "energy" if device else "progression")
            result["cases"].append({"case_id": cid, "question": question, "before_status": case["output"]["status"],
                "before_independent_judgment": annotations[cid]["answer_judgment"], "source_text_sha256": digest(raw),
                "annotation_identity": annotation_identity(cid, question, output), "output": output,
                "regression_contract": {"complete_answer": output["answer_status"] == "answered_with_support",
                    "reviewed_relation": output["claims"][0]["evidence_relation"] if output["claims"] else None},
                "new_independent_semantic_review": "not_performed; do not replace old labels with software checks"})
            w.close()
    result["counts"] = {"cases": 3, "software_contract_complete_answers": sum(c["regression_contract"]["complete_answer"] for c in result["cases"])}
    publish("old_three_failures_replay.json", result)
    return result["counts"]


def independent_results(w, frozen_path, annotations_path, cases_path):
    frozen = json.loads(Path(frozen_path).read_text())
    annotations = json.loads(Path(annotations_path).read_text())
    original_cases = json.loads(Path(cases_path).read_text())
    by_id = {c["case_id"]: c for c in original_cases["cases"]}
    frozen["data_kind"] = "actual_source_claims_independent_ai_authored_new_expressions_no_private_health_data"
    frozen["cases"] = [{**by_id[c["case_id"]], **c,
        "gold_review_status": "approved" if by_id[c["case_id"]].get("author_kind") == "independent_ai" else "unreviewed",
        "gold_review_kind": "independent_ai_source_packet_reading_not_human_gold"} for c in frozen["cases"]]
    scored = score_frozen_annotations(frozen, annotations)
    scored["scientific_validation"] = "Actual licensed source claims, independently authored expressions and independent AI adjudication; no independent human or individual effectiveness validation."
    scored["input_file_hashes"] = {"frozen": digest(Path(frozen_path).read_bytes()), "annotations": digest(Path(annotations_path).read_bytes())}
    scored["frozen_packet_hash_scope"] = "Canonical joined questions/gold/output evaluation packet; original unchanged output-file bytes are separately bound in input_file_hashes."
    write(PUBLIC / "independent_results.json", scored)
    frozen["counts"] = scored["counts"]
    frozen["quality_metrics"] = run_quality(w, frozen["cases"], {a["case_id"]: a for a in annotations["annotations"]})
    publish("independent_frozen_public.json", frozen)
    write(PUBLIC / "independent_annotations.json", annotations)
    return scored


def task_guard_replay(w, frozen_path, cases_path):
    frozen = json.loads(Path(frozen_path).read_text())
    definitions = {c["case_id"]: c for c in json.loads(Path(cases_path).read_text())["cases"]}
    value = {"data_kind": "same_frozen_questions_post_general_task_guard_software_replay",
        "original_outputs_sha256": digest(Path(frozen_path).read_bytes()),
        "original_cases_sha256": digest(Path(cases_path).read_bytes()),
        "original_independent_ai_score_unchanged": "3/18", "new_semantic_score": None,
        "limit": "No old annotation is rebound to a changed output; this replay checks statuses and constraints, not a new independent accuracy estimate.",
        "counts": {}, "cases": []}
    for case in frozen["cases"]:
        definition = definitions[case["case_id"]]
        output = w.query(case["question"], route=definition["route"], context=definition["context"])
        value["cases"].append({"case_id": case["case_id"], "question": case["question"],
            "before_status": case["output"]["answer_status"], "after_status": output["answer_status"],
            "annotation_identity": annotation_identity(case["case_id"], case["question"], output), "output": output})
    value["counts"] = {"cases": len(value["cases"]), "changed_statuses": sum(c["before_status"] != c["after_status"] for c in value["cases"])}
    publish("independent_task_guard_replay.json", value)
    return value


def audit_public(w):
    """Scrub only this workstream's JUnit and verify all published projections."""
    for path in PUBLIC.glob("*.xml"):
        tree = ET.fromstring(path.read_bytes())
        changed = False
        for node in tree.iter():
            if "hostname" in node.attrib:
                del node.attrib["hostname"]
                changed = True
            for key, value in list(node.attrib.items()):
                clean = projection.redact_local_paths(value)
                if clean != value:
                    node.set(key, clean)
                    changed = True
            for field in ("text", "tail"):
                value = getattr(node, field)
                if value:
                    clean = projection.redact_local_paths(value)
                    if clean != value:
                        setattr(node, field, clean)
                        changed = True
        # Already projected diagnostics are immutable evidence, including their
        # serialization. Re-encoding clean XML would invalidate recorded hashes.
        if changed:
            path.write_bytes(ET.tostring(tree, encoding="utf-8", xml_declaration=True) + b"\n")
    span_count, projected_files = 0, []
    files = [p for p in PUBLIC.iterdir() if p.suffix in {".json", ".jsonl", ".xml", ".csv"} and p.name != "publication_audit.json"]
    for path in files:
        text = path.read_text()
        assert str(ROOT) not in text and 'hostname=' not in text, path.name
        if path.suffix != ".json":
            continue
        value = json.loads(text)
        if not isinstance(value, dict) or not value.get("publication_projection"):
            continue
        for case in value["cases"]:
            assert case["public_output_sha256"] == digest(projection.canonical(case["output"]).encode())
            assert "review_packet" not in case
            for candidate in case["output"].get("retrieval", {}).get("candidates", []):
                for span in candidate.get("spans", []):
                    assert set(span) <= projection.SPAN_FIELDS
                    assert set(json.loads(span["rights_json"])) <= projection.RIGHTS_FIELDS
                    span_count += 1
        projected_files.append(path.name)
    # A concrete exact-substring check complements the structural allowlist.
    # Only currently held source prose is compared; no raw bytes are exported.
    prose = [row[0] for row in w.lib.sources.execute("SELECT s.text FROM span s JOIN version v ON s.version_id=v.version_id WHERE v.source_id='S1'") if len(row[0]) >= 120]
    for path in files:
        text = path.read_text()
        assert not any(paragraph in text for paragraph in prose), path.name
    result = {"projection_version": "v14-source-metadata-and-paths-1", "checked_at": now(),
        "public_files_checked": len(files), "projected_evaluations": sorted(projected_files), "projected_span_occurrences": span_count,
        "source_span_allowlist": sorted(projection.SPAN_FIELDS), "long_S1_prose_match_count": 0,
        "hostnames_or_absolute_repo_paths": 0, "private_corpus_modified": False,
        "scope": "Knowledge artifacts only; original local source bytes and independent reading packets remain in .local.",
        "files": {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in files}}
    write(PUBLIC / "publication_audit.json", result)
    return result


def main():
    with_workbench = KnowledgeWorkbench(ROOT / ".local/knowledge")
    try:
        summary = {"fixed_sets": fixed_evaluations(with_workbench), "old_failed_cases": old_failures_replay()}
        raw = ROOT / ".local/v14-knowledge-independent-packet/independent_new_outputs.raw.json"
        annotations = PUBLIC / "independent_new_annotations.json"
        cases = PUBLIC / "independent_new_cases.json"
        if all(path.exists() for path in (raw, annotations, cases)):
            summary["independent_original_labels_new_validator"] = independent_results(with_workbench, raw, annotations, cases)["counts"]
            summary["general_task_guard_replay"] = task_guard_replay(with_workbench, raw, cases)["counts"]
        write(PUBLIC / "evaluation_summary.json", summary)
        audit_public(with_workbench)
        print(json.dumps(summary, ensure_ascii=False))
    finally:
        with_workbench.close()


if __name__ == "__main__":
    main()
