"""Independent review of frozen report scope, first-use clocks and references."""
import json
import math
from copy import deepcopy

import pytest

from healthzip.analytics.cache import clear
from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.knowledge import KnowledgeWorkbench, domains, topics, vector_index
from healthzip.knowledge.revisions import prepare_retrieval_revisions
from healthzip.training.service import TrainingService
from healthzip.workflows.dependencies import input_version
from healthzip.workflows.period_report import create_report, load_report
from healthzip.workflows.report_objects import audit_bundle, reconstruct_report
from tests.integration.test_action_outcome_repairs import sample

CUTOFF = "2026-08-14T00:00:00Z"


def make_report(repo, tmp_path, **fields):
    return create_report(repo, {"cutoff_time": CUTOFF, "timezone": "UTC", **fields},
                         period="week", knowledge_root=tmp_path / "kb")


def test_initializing_empty_training_clock_does_not_mark_a_fresh_report_stale(tmp_path):
    repo = Repository(tmp_path / "clocks.sqlite")
    before = input_version(repo, None)
    report = make_report(repo, tmp_path)
    assert input_version(repo, None) == before == report["input_revision"]
    repo.close()


def test_none_selection_context_retains_normal_empty_context_contract(tmp_path):
    repo = Repository(tmp_path / "none.sqlite")
    report = make_report(repo, tmp_path, selection_context=None)
    assert report["period"] == "week"
    assert report["current"]["selection_context"] == {}
    repo.close()


def test_explicit_empty_source_filter_clears_a_prior_selected_source_everywhere(tmp_path):
    repo = Repository(tmp_path / "sources.sqlite")
    sample(repo, 1, 11, 60, source="A")
    sample(repo, 2, 11, 90, source="B")
    selected = make_report(repo, tmp_path, source_filter=["A"])
    all_sources = make_report(repo, tmp_path, source_filter=[], selection_context={"source_filter": ["A"]})
    for report, expected in ((selected, {"A"}), (all_sources, {"A", "B"})):
        current = report["current"]["metrics"]["STATE-RHR"]["value"]
        assert {point["protocol"][0] for points in current.values() for point in points} == expected
        w4 = next(q for q in report["questions"] if q["id"] == "W4")
        assert {r["source"] for r in w4["rows"] if r.get("metric") == "resting_heart_rate_bpm"} == expected
    assert all_sources["current"]["selection_context"].get("source_filter", []) == []
    assert all_sources["content_signature"] != selected["content_signature"]
    assert load_report(repo, selected["report_id"]) == selected
    repo.close()


def test_first_report_initializes_existing_knowledge_before_freezing_its_clock(tmp_path):
    repo = Repository(tmp_path / "first-use.sqlite")
    sample(repo, 1, 11, 60)
    KnowledgeWorkbench(tmp_path / "kb", environment_kind="synthetic_test").close()
    report = make_report(repo, tmp_path)
    assert load_report(repo, report["report_id"]) == report
    repo.close()


def _reviewed_method(root):
    kb = KnowledgeWorkbench(root, environment_kind="synthetic_test")
    identity = "independent-report-method"
    kb.lib.seed({"sources": [{"source_id": identity, "title": "Synthetic independent report method",
        "canonical_url": "https://example.invalid/independent-report-method", "corpus_roles": ["research"]}]}, {"cards": []})
    text = topics.profile("W4")["query"] + " Synthetic full text: compare the same observed measurement protocol."
    vid = kb.lib.record_version(identity, text.encode(), "fulltext", {}, {},
        {"index_allowed": True, "license_id": "CC0"}, "matched",
        [{"text": text, "section_path": "Synthetic methods", "locator": {"page": 8}}], "synthetic-report-review")
    sid = vid + ":s00000"
    review = {"reviewer": "Independent synthetic scenario", "reviewer_kind": "synthetic_fixture",
              "reviewed_at": "2026-08-01", "rationale": "Software test, not scientific authority",
              "content_checked": True, "application_checked": True}
    kb.review_claim({"claim_id": identity, "version": "1", "statement": text,
        "scope": {"explanation_purpose": "measurement_context"}, "conditions": [],
        "limitations": ["Synthetic scenario; no clinical interpretation."],
        "evidence_links": [{"source_id": identity, "source_version_id": vid, "span_ids": [sid]}]}, review)
    vector_index.register_spans(kb, vid, ["wearable"], assignment_status="content_checked")
    domains.link(kb, origin={"type": "claim", "id": identity, "version": "1"}, relation="applies_to",
        target={"type": "metric", "id": "W4", "version": domains.profile_version("W4")}, span_ids=[sid],
        applicability={}, actor="Synthetic", rationale="Known report method",
        evidence_types=["measurement", "comparison"], review=review)
    prepare_retrieval_revisions(kb)
    return kb, identity, sid


def test_revocation_updates_new_report_but_keeps_frozen_full_text_and_export(tmp_path, monkeypatch):
    original_factory = KnowledgeWorkbench
    monkeypatch.setattr("healthzip.knowledge.KnowledgeWorkbench", lambda *args, **kwargs:
        original_factory(*args, **{**kwargs, "environment_kind": "synthetic_test"}))
    repo = Repository(tmp_path / "revocation.sqlite")
    sample(repo, 1, 11, 60)
    kb, identity, sid = _reviewed_method(tmp_path / "kb")
    original = make_report(repo, tmp_path)
    question = next(q for q in original["questions"] if q["id"] == "W4")
    assert any(i["claim_id"] == identity for i in question["evidence"]["items"])
    assert any(s["span_id"] == sid for s in question["evidence"]["evidence_spans"])
    frozen = deepcopy(original)
    from healthzip.workflows.reports import current_report_source_status
    assert current_report_source_status(original, knowledge_root=tmp_path / "kb")["status"] == "current"
    kb.core_state("claim", identity, "1", "revoked", actor="Synthetic", rationale="Independent withdrawal scenario")
    annotation = current_report_source_status(original, knowledge_root=tmp_path / "kb")
    assert annotation["items"][0]["status"] == "revoked"
    assert "已撤销" in annotation["items"][0]["label"]
    updated = make_report(repo, tmp_path)
    current = next(q for q in updated["questions"] if q["id"] == "W4")
    assert not any(i["claim_id"] == identity for i in current["evidence"]["items"])
    assert updated["content_signature"] != original["content_signature"]
    clear()
    assert load_report(repo, original["report_id"]) == frozen
    exported = audit_bundle(repo, original["report_id"])
    assert reconstruct_report(exported) == frozen
    assert sid in json.dumps(exported)
    assert "compare the same observed measurement protocol" in json.dumps(exported)
    other = Repository(tmp_path / "other.sqlite")
    with pytest.raises(ValueError, match="not_found"):
        load_report(other, original["report_id"])
    other.close()
    kb.close()
    repo.close()


def test_question_evidence_store_open_failure_preserves_available_local_facts(tmp_path, monkeypatch):
    import sqlite3

    from healthzip.workflows.reports import period_questions
    repo = Repository(tmp_path / "service.sqlite")
    sample(repo, 1, 11, 60)
    TrainingService(repo)
    current = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", period="week")
    root = tmp_path / "kb"
    KnowledgeWorkbench(root, environment_kind="synthetic_test").close()

    def unavailable(*_args, **_kwargs):
        raise sqlite3.OperationalError("synthetic temporarily unreadable source store")

    monkeypatch.setattr("healthzip.knowledge.KnowledgeWorkbench", unavailable)
    questions = period_questions(repo, current, period="week", knowledge_root=root)
    w4 = next(q for q in questions if q["id"] == "W4")
    assert w4["report_status"] == "available"
    assert next(r for r in w4["rows"] if r.get("metric") == "resting_heart_rate_bpm")["value"] == 60
    assert w4["evidence"]["status"] == "service_failure"
    repo.close()


def _import_xml(repo, tmp_path, records):
    from zipfile import ZipFile

    from healthzip.importers.apple_xml import import_apple_zip
    path = tmp_path / "source-observations.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("export.xml", "<HealthData>" + "".join(records) + "</HealthData>")
    assert import_apple_zip(path, repo).status == "completed"


def test_retrospective_snapshot_and_asof_question_explicitly_keep_different_visibility(tmp_path):
    repo = Repository(tmp_path / "retrospective.sqlite")
    _import_xml(repo, tmp_path, ['<Record type="HKQuantityTypeIdentifierRestingHeartRate" value="60" unit="count/min" '
        'sourceName="Synthetic late import" startDate="2026-08-11 08:00:00 +0000" endDate="2026-08-11 08:00:00 +0000"/>'])
    # This current imported record was not visible at the August analysis cutoff.
    assert repo.one("SELECT available_at FROM source_revision WHERE table_name='health_sample'")[0] > CUTOFF
    report = make_report(repo, tmp_path, retrospective=True)
    values = [p["value"] for series in report["current"]["metrics"]["STATE-RHR"]["value"].values() for p in series]
    assert values == [60]
    w4 = next(q for q in report["questions"] if q["id"] == "W4")
    assert not [r for r in w4["rows"] if r.get("metric") == "resting_heart_rate_bpm"]
    assert w4["report_comparison_context"]["canonical_retrospective"]
    assert w4["analysis_identity"]["visibility_mode"] == "as_of"
    assert all(text in report["markdown"] for text in
               ("当前修订回看历史", "截止后才导入", "不作为同一可见性口径比较"))
    clear()
    assert load_report(repo, report["report_id"]) == report
    repo.close()


def test_declared_sleep_keeps_300_minutes_and_period_450_minutes_with_explicit_identity(tmp_path):
    from healthzip.analytics.sleep_selection import declare_episode
    repo = Repository(tmp_path / "declared-sleep.sqlite")
    raw = [("A", "2026-08-10 22:00:00 +0000", "2026-08-11 03:00:00 +0000"),
           ("A", "2026-08-11 22:00:00 +0000", "2026-08-12 08:00:00 +0000"),
           ("B", "2026-08-11 22:00:00 +0000", "2026-08-12 05:00:00 +0000")]
    _import_xml(repo, tmp_path, [f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisAsleepCore" '
        f'sourceName="{source}" device="synthetic" sourceVersion="1" startDate="{start}" endDate="{end}">'
        '<MetadataEntry key="protocol_id" value="fixed"/></Record>' for source, start, end in raw])
    repo.conn.execute("UPDATE source_revision SET available_at='2026-08-12T09:00:00Z'")
    repo.conn.commit()
    original = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", period="week")
    options = original["sleep_options"]
    source = next(s for s in options["streams"] if s["source_name"] == "A")
    episode = declare_episode(options, source["stream_id"], start="2026-08-10T22:00:00Z", end="2026-08-11T03:00:00Z",
        attribution_date="2026-08-11", declared_at="2026-08-12T10:00:00Z")
    selection = {"stream_id": source["stream_id"], "episodes": [episode], "main_episode_id": episode["id"]}
    frozen_selection = deepcopy(selection)
    report = make_report(repo, tmp_path, selection_context={"sleep_selection": selection})
    assert report["current"]["sleep_selection"]["accepted"]
    assert report["current"]["metrics"]["STATE-SLEEP-MAIN"]["value"]["observed_minutes"] == 300
    w6 = next(q for q in report["questions"] if q["id"] == "W6")
    observed = {r["source"]: r["value"] for r in w6["rows"] if r.get("metric") == "sleep_stage"}
    assert observed == {"A": 450, "B": 420}
    assert w6["report_comparison_context"]["declared_sleep_present"]
    assert w6["report_comparison_context"]["difference_is_explicit"]
    assert "睡眠口径区别" in report["markdown"] and "人工声明" in report["markdown"]
    assert selection == frozen_selection  # Never redefine the user's main episode.
    clear()
    assert load_report(repo, report["report_id"]) == report
    repo.close()


def test_history_page_marks_current_revocation_without_rewriting_old_text(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    root = tmp_path / ".local/knowledge"
    repo = Repository(tmp_path / "history.sqlite")
    sample(repo, 1, 11, 60)
    kb, identity, _ = _reviewed_method(root)
    original_factory = KnowledgeWorkbench
    monkeypatch.setattr("healthzip.knowledge.KnowledgeWorkbench", lambda *args, **kwargs:
        original_factory(*args, **{**kwargs, "environment_kind": "synthetic_test"}))
    report = create_report(repo, {"cutoff_time": CUTOFF, "timezone": "UTC"}, period="week", knowledge_root=root)
    before = json.dumps(report, sort_keys=True)
    kb.core_state("claim", identity, "1", "revoked", actor="Synthetic", rationale="Known withdrawal")
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_string(
        "from healthzip.db.repository import Repository\n"
        "from healthzip.workflows.period_report import load_report\n"
        "from healthzip.ui.review_page import _render_report_source_status, _render_frozen_details\n"
        f"repo = Repository({str(repo.path)!r})\n"
        f"report = load_report(repo, {report['report_id']!r})\n"
        "status = _render_report_source_status(report, repo=repo)\n"
        "_render_frozen_details(repo, report, 'review-test', current_sources=status)\n"
        "repo.close()\n").run(timeout=30)
    assert not app.exception
    assert any("当前不可直接用于新建议" in warning.value and "冻结正文未改写" in warning.value
               for warning in app.warning)
    assert any("已撤销" in caption.value for caption in app.caption)
    assert json.dumps(load_report(repo, report["report_id"]), sort_keys=True) == before
    kb.close()
    repo.close()


def _small_frozen_report(repo, boundary, location):
    """Exercise real referenced bytes with no analysis or benchmark workload."""
    from healthzip.workflows.report_objects import save_content

    payload = {"version": "decoder-synthetic-1", "period": "week", "analysis_run_id": "decoder-analysis",
        "current": {"marker": "analysis"}, "unknown_metadata": {"marker": "content"},
        "questions": [{"id": "W4", "ordinary_training": {"marker": "ordinary"},
                       "evidence": {"evidence_spans": [{"marker": "evidence"}]}}],
        "workflow_run_ids": [], "historical_run_ids": []}
    targets = {"current": payload["current"], "content": payload["unknown_metadata"],
               "ordinary": payload["questions"][0]["ordinary_training"],
               "evidence": payload["questions"][0]["evidence"]["evidence_spans"][0]}
    targets[location]["boundary"] = boundary
    repo.conn.execute("INSERT INTO analysis_run(run_id,cutoff_time,computed_at,algorithm_version,data_hash,result_json) "
        "VALUES(?,?,?,?,?,?)", ("decoder-analysis", CUTOFF, CUTOFF, "synthetic-decoder", "synthetic",
                              json.dumps(payload["current"], ensure_ascii=False, sort_keys=True)))
    manifest = save_content(repo, payload)
    return payload, manifest


@pytest.mark.parametrize("location", ["current", "content", "ordinary", "evidence"])
@pytest.mark.parametrize("boundary", [
    {"positive": 2**100, "negative": -(2**100)},
    {"nan": float("nan"), "positive": float("inf"), "negative": -float("inf")},
], ids=["unbounded-integers", "nonfinite-floats"])
def test_referenced_decoder_preserves_stdlib_edges_in_each_object(tmp_path, monkeypatch, location, boundary):
    from healthzip.workflows import period_report
    from healthzip.workflows.report_objects import read_content

    repo = Repository(tmp_path / "decoder-edges.sqlite")
    payload, manifest = _small_frozen_report(repo, boundary, location)
    assert manifest["content_decoder"] == "stdlib"
    calls, original = [], period_report._decode_content

    def decode(encoded, fast_compatible):
        calls.append(fast_compatible)
        return original(encoded, fast_compatible)

    monkeypatch.setattr(period_report, "_decode_content", decode)
    actual = read_content(repo, manifest)
    assert len(calls) == 4 and calls == [False] * 4
    assert json.dumps(actual, sort_keys=True) == json.dumps(payload, sort_keys=True)
    targets = {"current": actual["current"], "content": actual["unknown_metadata"],
               "ordinary": actual["questions"][0]["ordinary_training"],
               "evidence": actual["questions"][0]["evidence"]["evidence_spans"][0]}
    observed = targets[location]["boundary"]
    if "nan" in boundary:
        assert math.isnan(observed["nan"])
        assert observed["positive"] == float("inf") and observed["negative"] == -float("inf")
    else:
        assert type(observed["positive"]) is type(observed["negative"]) is int
        assert observed["positive"] == 2**100 and observed["negative"] == -(2**100)
    # Pre-optimization manifests have no decoder hint and retain the same parser.
    legacy = {key: value for key, value in manifest.items() if key != "content_decoder"}
    calls.clear()
    assert json.dumps(read_content(repo, legacy), sort_keys=True) == json.dumps(payload, sort_keys=True)
    assert calls == [False] * 4
    repo.close()


def test_safe_referenced_decoder_covers_all_objects_and_keeps_hint_internal(tmp_path, monkeypatch):
    from healthzip.workflows import period_report
    from healthzip.workflows.report_objects import read_content

    repo = Repository(tmp_path / "decoder-safe.sqlite")
    boundary = {"unicode": "合成🧪", "values": [-2**63, 2**64-1, 5e-324, 1.7976931348623157e308, -0.0, None, True]}
    payload, manifest = _small_frozen_report(repo, boundary, "current")
    assert manifest["content_decoder"] == "orjson-compatible-1"
    calls, original = [], period_report._decode_content

    def decode(encoded, fast_compatible):
        calls.append(fast_compatible)
        return original(encoded, fast_compatible)

    monkeypatch.setattr(period_report, "_decode_content", decode)
    actual = read_content(repo, manifest)
    assert calls == [True] * 4
    assert actual == payload
    assert math.copysign(1, actual["current"]["boundary"]["values"][4]) == -1
    actual["current"]["boundary"]["values"].clear()
    assert read_content(repo, manifest) == payload
    saved = {**manifest, "report_id": "decoder-report"}
    repo.conn.execute("INSERT INTO joint_period_report VALUES(?,?,?,?,?)",
                      ("decoder-report", "local", CUTOFF, json.dumps(saved), "Synthetic frozen report"))
    repo.conn.commit()
    expected = {**payload, "report_id": "decoder-report", "markdown": "Synthetic frozen report"}
    assert load_report(repo, "decoder-report") == expected
    assert reconstruct_report(json.loads(json.dumps(audit_bundle(repo, "decoder-report")))) == expected
    assert "content_decoder" not in expected
    monkeypatch.setattr(period_report, "orjson", None)
    assert read_content(repo, manifest) == payload
    repo.close()


def test_cycle_preference_changes_empty_report_without_changing_records_or_history(tmp_path):
    from healthzip.ui.preferences import save_preferences

    repo = Repository(tmp_path / "cycle-preference.sqlite")
    assert not repo.one("SELECT 1 FROM cycle_event LIMIT 1")
    save_preferences(repo.path, cycle_enabled=False)
    original = make_report(repo, tmp_path)
    before = json.dumps(original, sort_keys=True)
    revision = input_version(repo, None)
    assert next(q for q in original["questions"] if q["id"] == "W8")["report_status"] == "not_requested"
    save_preferences(repo.path, cycle_enabled=True)
    assert input_version(repo, None) == revision  # Only the separate workspace preference changed.
    enabled = make_report(repo, tmp_path)
    w8 = next(q for q in enabled["questions"] if q["id"] == "W8")
    assert w8["report_status"] == "no_records" and not w8["rows"]
    assert enabled["content_signature"] != original["content_signature"]
    assert json.dumps(load_report(repo, original["report_id"]), sort_keys=True) == before
    assert not repo.one("SELECT 1 FROM cycle_event LIMIT 1")
    repo.close()


def test_cycle_preference_change_during_freeze_rejects_stale_report_and_retry_updates(tmp_path):
    from healthzip.ui.preferences import save_preferences

    repo = Repository(tmp_path / "cycle-preference-race.sqlite")
    save_preferences(repo.path, cycle_enabled=False)
    original = make_report(repo, tmp_path)
    count = repo.one("SELECT COUNT(*) FROM joint_period_report")[0]
    stages = []

    def change_before_freeze(stage):
        stages.append(stage)
        if stage == "保存冻结版本":
            save_preferences(repo.path, cycle_enabled=True)

    with pytest.raises(ValueError, match="concurrent_joint_report_inputs_changed_retry_required"):
        create_report(repo, {"cutoff_time": CUTOFF, "timezone": "UTC"}, period="week",
                      knowledge_root=tmp_path / "kb", progress=change_before_freeze)
    assert "复用已核对的报告内容" in stages and "保存冻结版本" in stages
    assert not repo.conn.in_transaction
    assert repo.one("SELECT COUNT(*) FROM joint_period_report")[0] == count
    assert load_report(repo, original["report_id"]) == original
    retried = make_report(repo, tmp_path)
    assert next(q for q in retried["questions"] if q["id"] == "W8")["report_status"] == "no_records"
    assert retried["content_signature"] != original["content_signature"]
    repo.close()


def test_t05_actual_cycle_symptoms_and_training_are_identical_in_frozen_month_report(tmp_path):
    from healthzip.analytics.body_metrics import analyze_questions
    from healthzip.ui.preferences import save_preferences
    from tests.science.test_question_context import add_record, add_training

    repo = Repository(tmp_path / "actual-cycle-report.sqlite")
    sessions = add_training(repo)
    for identity, day, pain in ((701, 10, 2), (702, 20, 3)):
        add_record(repo, "health_sample", identity, f"2026-11-{day}T16:00:00+08:00",
                   canonical_type="menstrual_flow", category_value="light")
        add_record(repo, "subjective_log", identity, f"2026-11-{day}T16:10:00+08:00",
                   symptoms="本人记录腹部不适", pain_level=pain)
    # Real records make W8 applicable even when its empty-state preference is off.
    save_preferences(repo.path, cycle_enabled=False)
    cutoff = "2026-11-22T00:00:00+08:00"
    direct = analyze_questions(repo, question_ids=["W8"], period="month",
        window_start="2026-11-01T00:00:00+08:00", window_end=cutoff,
        cutoff_time=cutoff, timezone_name="Asia/Shanghai")[0]
    # Frozen JSON naturally represents internal identity tuples as arrays.
    expected = json.loads(json.dumps(direct, ensure_ascii=False))
    report = create_report(repo, {"cutoff_time": cutoff, "timezone": "Asia/Shanghai"},
                           period="month", knowledge_root=tmp_path / "missing")
    frozen = next(q for q in report["questions"] if q["id"] == "W8")
    assert frozen["report_status"] == "available"
    assert frozen["fact_id"] == expected["fact_id"]
    assert frozen["rows"] == expected["rows"]
    for field in ("source_filter", "period", "comparison_bounds", "analysis_version", "observation", "limitations"):
        assert frozen[field] == expected[field]
    sources = {identity for row in frozen["rows"] for key in ("source_record_ids", "event_source_record_ids")
               for identity in row.get(key, [])}
    assert sources == {"health_sample:701", "health_sample:702", "subjective_log:701", "subjective_log:702"}
    symptoms = [row for row in frozen["rows"] if row["type"] == "subjective"]
    assert [(row["symptoms"], row["pain_level"]) for row in symptoms] == [
        ("本人记录腹部不适", 2), ("本人记录腹部不适", 3)]
    pairs = [row for row in frozen["rows"] if row["type"] == "event_set_pair"]
    assert len(pairs) == 2  # Independently recorded menstrual events and subjective symptoms.
    actual_sets = {row[0] for row in repo.rows("SELECT set_uuid FROM strength_set")}
    for pair in pairs:
        assert pair["first_session_id"] == sessions[0] and pair["session_id"] == sessions[1]
        assert (pair["first_value"], pair["value"], pair["difference"]) == (8, 10, 2)
        assert pair["comparable"]
        assert {pair["previous_set_id"], pair["current_set_id"]} == actual_sets
    assert any(pair["event_title"] == "已记录的主观状态" for pair in pairs)
    assert all("phase" not in row for row in frozen["rows"])
    clear()
    assert load_report(repo, report["report_id"]) == report
    assert reconstruct_report(audit_bundle(repo, report["report_id"])) == report
    repo.close()
