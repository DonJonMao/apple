"""Source selection and per-part scope must survive legacy metadata and compounds."""

import json

import pytest

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.tasks import parse_task, requested_material, resolve_named_sources


@pytest.fixture
def library(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    w.seed_core()
    yield w
    w.close()


def test_registered_document_type_is_available_after_upgrading_legacy_metadata(library):
    source = "CORE-US-HHS-PAG-2"
    with library.lib.sources:
        manifest = library.lib.source(source)["manifest"]
        manifest.pop("document_kind", None)
        library.lib.sources.execute("UPDATE source SET manifest_json=? WHERE source_id=?", (json.dumps(manifest), source))
    library.lib.record_version(source, b"Synthetic HHS guideline body", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": "Synthetic adult public health guidance.", "locator": {"chapter_id": "4"}}], "synthetic")
    question = "根据HHS指南，解释身体活动建议。"
    task = parse_task(question, resolve_named_sources(library, question, {}))
    assert requested_material(library, task, {"core"})["status"] == "available"
    # The GETP textbook remains a book even though its older source_kind said
    # professional_association_guideline. Do not infer medium from authority.
    from healthzip.knowledge.tasks import source_constraints_match
    book = library.lib.source("CORE-ACSM-GETP-12")["manifest"]
    book.pop("document_kind", None)
    with library.lib.sources:
        library.lib.sources.execute("UPDATE source SET manifest_json=? WHERE source_id='CORE-ACSM-GETP-12'", (json.dumps(book),))
    evidence = [{"source_id": "CORE-ACSM-GETP-12", "locator": {}}]
    assert source_constraints_match(library, evidence, {"document_kind": "textbook"})
    assert not source_constraints_match(library, evidence, {"document_kind": "guideline"})


def test_two_chapters_are_not_silently_reduced_to_the_first():
    task = parse_task("HHS第二版第4章说明成人年龄范围，第7章说明安全建议适用范围。")
    assert task["source_constraints"]["requested_chapter_numbers"] == ["4", "7"]
    assert "requested_chapter_number" not in task["source_constraints"]


@pytest.mark.parametrize("question", [
    "请直接用M2替我判定最近四周训练是不是停滞，并给出停滞的概率和个人等效界值。",
    "Use this equivalence method to decide whether my training has plateaued and give me a probability.",
    "为我的训练选择个人等效界值。",
])
def test_personal_statistical_decisions_are_not_satisfied_by_a_method_summary(question):
    task = parse_task(question)
    assert "statistical_calculation" in {part["part_id"] for part in task["required_answer_parts"]}


def test_public_health_minimum_is_not_retargeted_as_two_optimization_claims():
    task = parse_task("HHS要求每周至少两天肌力活动，是在讲健康收益，还是已经找到了力量和增肌的唯一最佳频次？")
    parts = task["required_answer_parts"]
    assert {part.get("requested_goal") for part in parts if part.get("outcome") == "frequency"} == {"public_health"}
    assert "goal_scope" in {part.get("outcome") for part in parts}


def test_compound_chapters_bind_to_their_own_targets():
    context = {"named_source_task_subjects": {
        "adult_guideline_scope": "physical_activity", "activity_safety_scope": "physical_activity"}}
    task = parse_task("HHS第二版第4章所说的成人到底是哪一年龄段？第7章的安全建议也只能用于这段年龄吗？", context)
    parts = {p["outcome"]: p for p in task["required_answer_parts"]}
    assert set(parts) == {"adult_guideline_scope", "activity_safety_scope"}
    assert parts["adult_guideline_scope"]["source_constraints"] == {"requested_chapter_number": "4"}
    assert parts["activity_safety_scope"]["source_constraints"] == {"requested_chapter_number": "7"}


def test_repeated_target_in_two_chapters_is_two_requests():
    task = parse_task("Explain resistance training frequency in chapter 4. Explain resistance training frequency in chapter 7.")
    parts = task["required_answer_parts"]
    assert len(parts) == 2
    assert len({p["part_id"] for p in parts}) == 2
    assert {p["source_constraints"]["requested_chapter_number"] for p in parts} == {"4", "7"}


def test_requested_material_reports_missing_chapter(library):
    source = "CORE-US-HHS-PAG-2"
    library.lib.record_version(source, b"Synthetic chapter four only", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": "Synthetic material.", "locator": {"chapter_id": "4"}}], "synthetic")
    question = "HHS第二版第4章说明成人年龄范围，第7章说明安全建议适用范围。"
    task = parse_task(question, resolve_named_sources(library, question, {}))
    result = requested_material(library, task, {"core"})
    assert result["status"] == "partially_available"
    assert result["missing_components"] == {"chapter": ["7"]}


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("default_relation", ["supports", "qualifies"])
def test_qualifying_reference_cannot_answer_another_chapter(library, confirmed, default_relation):
    source = "CORE-US-HHS-PAG-2"
    version = library.lib.record_version(source, b"Synthetic chapter binding", "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": "Synthetic frequency statement.", "locator": {"chapter_id": "4"}},
         {"text": "Synthetic qualification only.", "locator": {"chapter_id": "7"}}], "synthetic")
    spans = [version + f":s{i:05d}" for i in range(2)]
    library.review_claim({"claim_id": "SYNTH-CHAPTER-FREQUENCY", "version": "1", "statement": "Synthetic only",
        "scope": {"population": "synthetic"}, "limitations": ["No scientific authority"],
        "evidence_links": [{"source_id": source, "source_version_id": version, "span_ids": spans}],
        "answer_task": {"subject": "resistance_training", "outcome": "frequency", "requested_relation": "options",
            "evidence_relation": default_relation,
            "answer_parts": [{"text": "Synthetic frequency statement.", "span_ids": spans[:1], "evidence_relation": "supports"},
                             {"text": "Synthetic qualification only.", "span_ids": spans[1:], "evidence_relation": "qualifies"}]}},
        {"reviewer": "Synthetic fixture", "reviewer_kind": "synthetic_fixture", "reviewed_at": "2026-11-11T00:00:00Z",
         "content_checked": True, "rationale": "Tests only binding of source chapters."})
    context = {"corpus_roles": ["core"]}
    if confirmed:
        context["question_contract"] = {"subject": "resistance_training", "outcome": "frequency",
                                        "requested_relation": "options", "user_confirmed": True}
    question = "HHS第4章的训练频次怎样？第7章的训练频次怎样？"
    answer = library.query(question, route="strength", context=context)
    assert answer["answer_status"] == "partially_answered"
    assert answer["claims"]
    from healthzip.knowledge.tasks import core_candidates
    candidates, _ = core_candidates(library, question, resolve_named_sources(library, question, context), {"core"})
    bindings = candidates[0]["review"]["claims"][0]["answer_bindings"]
    assert bindings[0]["requested_part_ids"] == ["frequency:chapter:4"]
