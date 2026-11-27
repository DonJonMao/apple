"""Real ordinary training facts control narrow public RIR source eligibility."""

import json
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from healthzip.analytics.body_metrics import analyze_questions
from healthzip.db.repository import Repository
from healthzip.knowledge import metric_retrieval, vector_index
from healthzip.knowledge.store import digest, dumps
from healthzip.knowledge.topics import question_sources
from healthzip.science import evaluate
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService
from tests.integration.test_followup_report_evidence import claim
from tests.knowledge.test_v15_retrieval import CONTEXT, Embed, Rank, add

START = "2025-04-01T00:00:00+08:00"
END = "2025-04-20T00:00:00+08:00"
DIRECT = {"field": "metric_evidence.direct_rir_only", "op": "eq", "value": True,
          "origin": "measurement_contract"}


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Repository(tmp_path / "synthetic-w1.sqlite3")
    yield repo
    repo.close()


@pytest.fixture
def rir_library(kb):
    claim(kb, "direct-rir-definition", ["measurement", "comparison"], topic="W1",
          conditions=[DIRECT])
    claim(kb, "independent-training-method", ["mechanism_or_exception", "action_or_reassessment"],
          topic="W1")
    return kb


def completed_sets(repo, actuals, *, unknown_conditions=False):
    """Use service writes and event replay; no hand-built question or database rows."""
    service = TrainingService(repo)
    with patch("healthzip.training.service.timestamp", side_effect=lambda value=None:
               timestamp(value) if value else START):
        equipment = service.create_equipment("Synthetic RIR rack", "barbell")
    condition = {"equipment_instance_id": equipment["id"], "load_basis": "external_total_kg",
                 "load_basis_confirmed": True, "side": "bilateral", "settings": {},
                 "settings_confirmed": True, "rom_protocol": "synthetic-full",
                 "repetition_semantics": "full_repetitions"}
    if unknown_conditions:
        condition = {"load_basis": "external_total_kg", "load_basis_confirmed": True}
    saved = []
    for index, actual in enumerate(actuals):
        at = datetime.fromisoformat("2025-04-04T09:00:00+08:00") + timedelta(days=3 * index)
        recorded = (at + timedelta(hours=1)).isoformat()
        with patch("healthzip.training.service.timestamp", side_effect=lambda value=None:
                   timestamp(value) if value else recorded):
            session = service.start_session("Synthetic ordinary RIR", started_at=at.isoformat())
            exercise = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
            row = service.add_set(exercise["id"], actual={"completion_state": "completed",
                "set_type": "work", "load_value": 30, "load_unit": "kg", "reps": 10 + index,
                "ended_at": (at + timedelta(minutes=5)).isoformat(), "reference_set": False,
                **actual})
            saved.append(row)
            service.end_session(session["id"], ended_at=(at + timedelta(minutes=40)).isoformat())
    return service, saved


def computed(repo, *, cutoff=END):
    return analyze_questions(repo, question_ids=["W1"], window_start=START, window_end=END,
                             cutoff_time=cutoff, timezone_name="Asia/Shanghai")[0]


def retrieved(kb, question, *, context=None):
    result = question_sources(kb, "W1", computed_question=question, context=context,
                              include_evidence=True)
    return result, {item["claim_id"] for item in result["items"]}


@pytest.mark.parametrize("actuals, expected", [
    ([{"rir": 0}], True),
    ([{"rir": 0, "rpe": 8, "rpe_scale": "rir_rpe10"}], True),
    ([{"rir": 2}, {"rir": 1}, {"rir": 0}], True),
    ([{"rir": 2}, {"rir": None}], False),
    ([{"rir": 2}, {"rir": 3, "rir_qualifier": "at_least"}], False),
    ([{"rpe": 8, "rpe_scale": "rir_rpe10"}], False),
    ([{"rir": 2}, {"rpe": 8, "rpe_scale": "rir_rpe10"}], False),
    ([{"rpe": 8, "rpe_scale": "cr10"}], False),
    ([{}], False),
    ([], False),
], ids=["zero", "direct-with-rpe", "ordinary-multiple", "mixed-missing", "mixed-interval",
        "convertible-rpe-only", "mixed-converted", "other-rpe-scale", "unknown", "empty"])
def test_real_ordinary_facts_control_only_rir_source(repository, rir_library, actuals, expected):
    _, rows = completed_sets(repository, actuals)
    question = computed(repository)
    frozen = deepcopy(question)
    context = {"metric_evidence": {"direct_rir_only": not expected}}
    original_context = deepcopy(context)
    result, selected = retrieved(rir_library, question, context=context)
    assert ("direct-rir-definition" in selected) is expected
    assert "independent-training-method" in selected
    assert result["applicability_context"]["metric_evidence"]["direct_rir_only"] is expected
    assert context == original_context and question == frozen
    if actuals:
        ordinary = question["ordinary_training"]
        points = [point for series in ordinary["series"] for point in series["points"]]
        assert ordinary["record_count"] == len(actuals) == len(points)
        assert [point["reps"] for point in sorted(points, key=lambda point: point["date"])] == [
            10 + index for index in range(len(actuals))]
        assert {point["record_id"] for point in points} == {row["set_uuid"] for row in rows}
        assert not any(point["reference_set"] for point in points)


def test_unknown_physical_condition_keeps_direct_rir_definition_but_not_comparability(
        repository, rir_library):
    completed_sets(repository, [{"rir": 0}, {"rir": 2}], unknown_conditions=True)
    question = computed(repository)
    assert all(not series["condition_known"] for series in question["ordinary_training"]["series"])
    assert not any(series["comparisons"] for series in question["ordinary_training"]["series"])
    _, selected = retrieved(rir_library, question)
    assert {"direct-rir-definition", "independent-training-method"} <= selected


@pytest.mark.parametrize("original, correction", [(None, 2), (2, None)])
def test_future_correction_does_not_change_earlier_rir_source_scope(
        repository, rir_library, original, correction):
    service, rows = completed_sets(repository, [{"rir": original}])
    earlier = computed(repository)
    earlier_frozen = deepcopy(earlier)
    future = "2025-04-21T12:00:00+08:00"
    with patch("healthzip.training.service.timestamp", side_effect=lambda value=None:
               timestamp(value) if value else future):
        service.edit_set(rows[0]["set_uuid"], {"rir": correction}, base_revision=rows[0]["revision"])
    same_cutoff = computed(repository)
    later = computed(repository, cutoff="2025-04-22T00:00:00+08:00")
    assert same_cutoff == earlier_frozen
    assert later["fact_id"] != earlier["fact_id"]
    _, old_selected = retrieved(rir_library, same_cutoff)
    _, new_selected = retrieved(rir_library, later)
    assert ("direct-rir-definition" in old_selected) is (original is not None)
    assert ("direct-rir-definition" in new_selected) is (correction is not None)
    assert earlier == earlier_frozen


def test_unknown_population_does_not_gain_a_separate_adult_only_claim(repository, rir_library):
    claim(rir_library, "adult-only-rir-use", ["comparison"], topic="W1", conditions=[DIRECT,
        {"field": "population.age_group", "op": "eq", "value": "adult", "origin": "source_scope"}])
    completed_sets(repository, [{"rir": 2}])
    question = computed(repository)
    _, unknown = retrieved(rir_library, question)
    _, adult = retrieved(rir_library, question, context={"population": {"age_group": "adult"}})
    assert "direct-rir-definition" in unknown
    assert "adult-only-rir-use" not in unknown
    assert "adult-only-rir-use" in adult


def test_free_context_alone_never_certifies_observed_rir(rir_library):
    result = question_sources(rir_library, "W1", context={"metric_evidence": {"direct_rir_only": True}})
    selected = {item["claim_id"] for item in result["items"]}
    assert "direct-rir-definition" not in selected
    assert "independent-training-method" in selected


def test_damaged_unused_rpe_remains_a_local_source_restriction(repository, rir_library):
    completed_sets(repository, [{"rir": 2}])
    question = computed(repository)
    question['evidence_observations']['training_sets'][0]['rpe'] = float('nan')
    _, selected = retrieved(rir_library, question)
    assert 'direct-rir-definition' not in selected
    assert 'independent-training-method' in selected


@pytest.mark.parametrize("alteration", [
    "missing-provenance", "projection-subset", "duplicated-record", "mismatched-rir",
    "mismatched-revision", "mismatched-date", "mismatched-window", "different-question",
    "converted-effort", "unknown-qualifier", "interval-with-number", "missing-fact-identity",
    "mismatched-sources", "mismatched-cutoff",
])
def test_inconsistent_provenance_restricts_only_rir_explanation(repository, rir_library, alteration):
    completed_sets(repository, [{"rir": 2}, {"rir": 0}])
    question = computed(repository)
    assert "direct-rir-definition" in retrieved(rir_library, question)[1]
    changed = deepcopy(question)
    packet = changed["evidence_observations"]
    record = packet["training_sets"][0]
    if alteration == "missing-provenance":
        changed.pop("evidence_observations")
    elif alteration == "projection-subset":
        packet["training_sets"].pop()
    elif alteration == "duplicated-record":
        packet["training_sets"][1] = deepcopy(record)
    elif alteration == "mismatched-rir":
        record["rir"] = 5
    elif alteration == "mismatched-revision":
        record["revision"] += 1
    elif alteration == "mismatched-date":
        record["ended_at"] = "2025-04-05T09:05:00+08:00"
    elif alteration == "mismatched-window":
        packet["window"]["start"] = "2025-04-02T00:00:00+08:00"
    elif alteration == "different-question":
        changed["id"] = "W2"
    elif alteration == "converted-effort":
        record["converted"] = True
    elif alteration == "unknown-qualifier":
        record["rir_qualifier"] = "unverified_interval"
    elif alteration == "interval-with-number":
        record["rir_interval"] = {"lower": 2, "upper": 5}
    elif alteration == "missing-fact-identity":
        changed.pop("fact_id")
    elif alteration == "mismatched-sources":
        changed["source_filter"] = ["other-synthetic-source"]
    elif alteration == "mismatched-cutoff":
        changed["cutoff_time"] = "2025-04-22T00:00:00+08:00"
    result, selected = retrieved(rir_library, changed, context={"metric_evidence": {"direct_rir_only": True}})
    assert "direct-rir-definition" not in selected
    assert "independent-training-method" in selected
    assert result["applicability_context"]["metric_evidence"]["direct_rir_only"] is False
    assert question["ordinary_training"] == changed["ordinary_training"]


def test_w1_facts_do_not_grant_direct_rir_scope_to_a_different_topic(repository, rir_library):
    claim(rir_library, "unrelated-topic-rir", ["measurement"], topic="W2", conditions=[DIRECT])
    completed_sets(repository, [{"rir": 0}])
    question = computed(repository)
    result = question_sources(rir_library, "W2", computed_question=question,
                              context={"metric_evidence": {"direct_rir_only": True}}, include_evidence=True)
    assert "unrelated-topic-rir" not in {item["claim_id"] for item in result["items"]}
    assert result["applicability_context"]["metric_evidence"]["direct_rir_only"] is False


@pytest.mark.parametrize("invalid", [True, -1, float("inf"), float("nan")],
                         ids=["boolean", "negative", "infinite", "nan"])
def test_invalid_effort_numbers_do_not_pass_even_when_projection_and_display_agree(
        repository, rir_library, invalid):
    completed_sets(repository, [{"rir": 0}])
    question = computed(repository)
    question["evidence_observations"]["training_sets"][0]["rir"] = invalid
    question["ordinary_training"]["series"][0]["points"][0]["rir"] = invalid
    _, selected = retrieved(rir_library, question)
    assert "direct-rir-definition" not in selected
    assert "independent-training-method" in selected


@pytest.mark.parametrize("malformation", ["non-object-packet", "non-object-ordinary", "non-list-points"])
def test_malformed_provenance_is_a_local_restriction_not_a_question_failure(
        repository, rir_library, malformation):
    completed_sets(repository, [{"rir": 1}])
    question = computed(repository)
    if malformation == "non-object-packet":
        question["evidence_observations"] = ["invalid"]
    elif malformation == "non-object-ordinary":
        question["ordinary_training"] = ["invalid"]
    else:
        question["ordinary_training"]["series"][0]["points"] = None
    _, selected = retrieved(rir_library, question)
    assert "direct-rir-definition" not in selected
    assert "independent-training-method" in selected


def test_old_index_cannot_silently_gain_question_semantics_but_keeps_legacy_metric_use(
        repository, rir_library):
    add(rir_library, "legacy-str10", mid="STR-10", conditions=[DIRECT])
    metric_retrieval.freeze_index(rir_library, "synthetic-old-release")
    manifest = json.loads(rir_library.lib.sources.execute(
        "SELECT manifest_json FROM index_release WHERE release_id='synthetic-old-release'").fetchone()[0])
    manifest.pop("question_evidence_context_version")
    serialized = dumps(manifest)
    with rir_library.lib.sources:
        rir_library.lib.sources.execute("UPDATE index_release SET manifest_json=?,sha256=? WHERE release_id=?",
            (serialized, digest(serialized.encode()), "synthetic-old-release"))
    completed_sets(repository, [{"rir": 0}])
    question = computed(repository)
    with pytest.raises(ValueError, match="frozen_question_evidence_context_changed"):
        question_sources(rir_library, "W1", computed_question=question, release_id="synthetic-old-release")
    old_general = question_sources(rir_library, "W1", release_id="synthetic-old-release")
    assert {item["claim_id"] for item in old_general["items"]} == {"independent-training-method"}
    result = evaluate("STR-10", [{"id": "legacy-synthetic-set", "rir": 0,
        "event_end": "2025-04-04T09:05:00+08:00", "available_at": "2025-04-04T10:00:00+08:00"}],
        window_start=START, window_end=END, cutoff_time=END)
    legacy = rir_library.retrieve_for_metric("STR-10", "strength", result, CONTEXT,
        release_id="synthetic-old-release", mode="lexical", candidate_scope="reviewed_metric")
    assert legacy["capability_permissions"]["source_explanation"] is True
    assert legacy["capability_permissions"]["candidate"] is False
    assert rir_library.lib.sources.execute(
        "SELECT manifest_json FROM index_release WHERE release_id='synthetic-old-release'").fetchone()[0] == serialized
    metric_retrieval.freeze_index(rir_library, "synthetic-new-release")
    current = question_sources(rir_library, "W1", computed_question=question, release_id="synthetic-new-release")
    assert "direct-rir-definition" in {item["claim_id"] for item in current["items"]}


def test_bounded_second_pass_keeps_computed_scope_and_complete_rir_evidence(repository, kb):
    from test_repair_question_evidence import add_claim

    method_spans = add_claim(kb, "method-heavy", "W1", ["measurement", "comparison", "mechanism_or_exception"],
        text="strength training effort repetitions comparison conditions method " * 12, count=6)
    rir_spans = add_claim(kb, "direct-rir-followup-limit", "W1", ["action_or_reassessment"],
        text="Record the reported effort and preserve its limitations before another comparison.",
        count=2, conditions=[DIRECT])
    completed_sets(repository, [{"rir": 0}])
    result = question_sources(kb, "W1", computed_question=computed(repository), include_evidence=True)
    assert {item["claim_id"] for item in result["items"]} == {"method-heavy", "direct-rir-followup-limit"}
    assert {span["span_id"] for span in result["evidence_spans"]} == set(method_spans + rir_spans)
    assert result["retrieval"]["initial_missing_purposes"] == ["action_or_reassessment"]
    assert result["retrieval"]["supplemental_pass"]["requested_mode"] == "lexical"
    assert result["retrieval"]["supplemental_remote_calls"] == 0
    assert result["applicability_context"]["metric_evidence"]["direct_rir_only"] is True


def test_actual_rir_projection_stays_out_of_public_model_payloads_and_audits(repository, rir_library):
    secret = "PRIVATE-SYNTHETIC-RIR-NOTE-83721"
    _, rows = completed_sets(repository, [{"rir": 3.81234567, "notes": secret}])
    question = computed(repository)
    embed, rank = Embed(), Rank()
    vector_index.build_vectors(rir_library, embed)
    result = question_sources(rir_library, "W1", computed_question=question,
        context={"notes": secret}, mode="hybrid_rerank", services=(embed, rank))
    assert "direct-rir-definition" in {item["claim_id"] for item in result["items"]}
    assert embed.calls and rank.calls
    payloads = json.dumps(embed.calls + rank.calls)
    audits = str([tuple(row) for row in rir_library.lib.sources.execute(
        "SELECT payload_json FROM metric_retrieval_audit")])
    for private_value in (secret, "3.81234567", rows[0]["set_uuid"], question["fact_id"], "2025-04-04"):
        assert private_value not in payloads
        assert private_value not in audits
