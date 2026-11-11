"""Freeze fresh synthetic questions/answers for a separate implementation-independent reviewer."""

import json
import tempfile
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.adjudication import annotation_identity
from healthzip.knowledge.store import digest, now

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/review/rag_semantics_frozen.json"
QUESTION = "合成方案是否允许增加重复次数？"
TARGET = {"proposition": "合成方案允许增加重复次数", "scope": {"population": "synthetic_adults", "time_scale": "study_protocol"}}
DEVICE_QUESTION = "合成温度计试验的四周组均偏差可以当作每个人每天的误差界限吗？"
DEVICE_TARGET = {"proposition": "四周组均偏差规定每个人每天的误差界限", "scope": {"population": "synthetic_device_participants", "time_scale": "four_weeks_to_daily", "aggregation": "group_to_individual"}}
CASES = [
    ("NEW-01", QUESTION, "progression", {}, "ordinary"),
    ("NEW-02", "合成方案增加重复次数能否证明个人寿命增长？", "progression", {}, "ordinary"),
    ("NEW-03", QUESTION, "progression", {"target_claims": [{**TARGET, "scope": {"population": "children", "time_scale": "lifelong"}}]}, "ordinary"),
    ("NEW-04", DEVICE_QUESTION, "energy", {}, "ordinary"),
    ("NEW-05", "合成温度计试验能确定我明天的绝对体温吗？", "energy", {}, "ordinary"),
    ("NEW-06", QUESTION, "progression", {}, "qualified"),
    ("NEW-07", QUESTION, "progression", {}, "conflict"),
    ("NEW-08", QUESTION, "progression", {"target_claims": [TARGET, {"proposition": "增加次数改善个人寿命", "scope": {"population": "synthetic_adults", "time_scale": "lifelong"}}]}, "ordinary"),
    ("NEW-09", QUESTION, "progression", {}, "withdrawn"),
    ("NEW-10", QUESTION, "progression", {}, "disabled"),
]


def approve(workbench, theory, source, text, question, target, relation="supports"):
    raw = text.encode()
    version = workbench.lib.record_version(source, raw, "fulltext", {"url": "https://example.test/synthetic-only"},
        {"title": "Synthetic source for review fixture"}, {"license_id": "CC0", "index_allowed": True}, "matched",
        [{"text": text, "locator": {"synthetic_line": 1}}], "synthetic-review-1")
    span = version + ":s00000"
    workbench.review_theory(theory, "0.1.0", reviewer="Implementing agent authored synthetic source fixture",
        reviewer_kind="synthetic_fixture", rationale="Test construction only; no actual study or expert approval.",
        applicability={"scope": "synthetic_only"}, evidence_links=[{"source_id": source, "source_version_id": version, "span_ids": [span]}],
        claims=[{"text": text, "span_ids": [span], "support_rationale": "Exact invented fixture assertion.",
                 "answer_bindings": [{"question": question, "target_claim": target, "relation": relation,
                                      "rationale": "Declared synthetic relation to be independently checked in the frozen output."}]}])


def main():
    if OUTPUT.exists():
        raise SystemExit("Frozen packet already exists; do not overwrite it or tune from its labels.")
    frozen = {"data_kind": "synthetic_only_no_real_health_data_or_scientific_approval", "frozen_at": now(),
              "review_scope": "Fresh cases separate from the fixed source-family holdout; author is the implementing agent, reviewer must be separate and explicitly AI/human identified.",
              "cases": []}
    for identity, question, route, context, variant in CASES:
        with tempfile.TemporaryDirectory() as folder:
            w = KnowledgeWorkbench(folder)
            w.seed()
            approve(w, "TC-progression-load-repetition-options", "S5",
                    "在这项虚构成人方案中，增加重复次数是允许的选项；未测量寿命，不提供个人效果保证。", QUESTION, TARGET,
                    "qualifies" if variant == "qualified" else "supports")
            approve(w, "TC-energy-device-reporting", "E8",
                    "在这项虚构温度计试验中，四周组均偏差不构成每个人每天的误差界限；没有测量明日个人体温。",
                    DEVICE_QUESTION, DEVICE_TARGET, "refutes")
            if variant == "conflict":
                approve(w, "TC-measurement-load-comparability", "S6",
                        "另一条虚构方案声明说该成人方案不允许增加重复次数；两份声明互相冲突。", QUESTION, TARGET, "refutes")
            if variant == "withdrawn":
                w.lib.update_state("S5", "withdrawn", "Synthetic withdrawal for regression")
            if variant == "disabled":
                w.theory_state("TC-progression-load-repetition-options", "0.1.0", "disabled",
                               actor="synthetic fixture", rationale="Suspend only this theory, not the source")
            output = w.query(question, route, context=context)
            evidence = {span["span_id"]: {key: span[key] for key in ("span_id", "source_id", "version_id", "text", "text_hash", "locator_json")}
                        for candidate in output["retrieval"]["candidates"] for span in candidate["spans"]}
            frozen["cases"].append({"case_id": identity, "question": question, "context": context,
                "annotation_identity": annotation_identity(identity, question, output),
                "review_packet": {"answer": output["answer"], "status": output["status"],
                    "target_assessment": output["support_assessment"], "claims": output["claims"],
                    "citations": output["citations"], "evidence": list(evidence.values())}, "output": output})
            w.close()
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"path": str(OUTPUT.relative_to(ROOT)), "sha256": digest(OUTPUT.read_bytes()), "cases": len(frozen["cases"])}, indent=2))


if __name__ == "__main__":
    main()
