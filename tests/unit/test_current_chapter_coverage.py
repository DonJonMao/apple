"""Live material coverage must not reuse a seed's unacquired status or grant review."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.store import dumps, now


@pytest.fixture
def library(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    w.seed()
    w.seed_core()
    yield w
    w.close()


def content(w, source="S1", *, allowed=True, parser="synthetic-coverage-1", locator=None, material="fulltext"):
    text = "Synthetic source content; no scientific review has been performed."
    return w.lib.record_version(source, text.encode(), material, {}, {},
        {"index_allowed": allowed, "license_id": "CC0-synthetic"}, "matched",
        [{"text": text, "locator": locator or {"section_id": "synthetic"}}], parser)


def current(w, source="S1", chapter="section-1"):
    return next(r for r in w.core_status()["current_chapter_coverage"]
                if r["source_id"] == source and r["chapter_id"] == chapter)


def test_actual_knowledge_page_distinguishes_available_body_from_unmapped_seed_topic(library):
    old = library.lib.sources.execute("SELECT * FROM chapter_coverage").fetchall()
    content(library)
    app = AppTest.from_string(f'''from healthzip.knowledge import KnowledgeWorkbench
from healthzip.ui.knowledge_page import _render
w=KnowledgeWorkbench({str(library.root)!r}, environment_kind="synthetic_test")
try: _render(w)
finally: w.close()
''').run()
    assert not app.exception
    displayed = [json.loads(item.value) for item in app.json]
    assert any(isinstance(value, list) and any(isinstance(row, dict)
        and row.get("source_id") == "S1"
        and row.get("material_status") == "source_content_available_topic_mapping_pending"
        for row in value) for value in displayed)
    row = current(library)
    assert row["source_eligible_span_count"] == 1
    assert row["scope_eligible_span_ids"] == []  # A source is not a reviewed topic.
    assert row["claim_review_status"] == "separate_claim_and_rule_review_required"
    assert library.core_status()["effective_rule_count"] == 0
    assert [tuple(r) for r in old] == [tuple(r) for r in library.lib.sources.execute("SELECT * FROM chapter_coverage")]


@pytest.mark.parametrize("material,allowed,status", [
    ("metadata", True, "missing_source_content"),
    ("fulltext", False, "source_content_present_unavailable"),
    ("fulltext", True, "source_content_available_topic_mapping_pending"),
])
def test_current_coverage_uses_material_depth_and_actual_rights(library, material, allowed, status):
    content(library, material=material, allowed=allowed)
    assert current(library)["material_status"] == status
    if material == "fulltext" and allowed:
        library.lib.update_state("S1", "withdrawn", "Synthetic withdrawal")
        row = current(library)
        assert row["material_status"] == "source_content_present_unavailable"
        assert row["source_eligible_span_count"] == 0
        assert "withdrawn" in row["unavailable_reasons"]


def test_superseded_parse_never_counts_as_current_material(library):
    old = content(library)
    new = content(library, allowed=False, parser="synthetic-coverage-2")
    with library.lib.sources:
        library.lib.sources.execute("INSERT INTO parse_supersession VALUES(?,?,?,?)",
            (old, new, "Synthetic corrected parse", now()))
    row = current(library)
    assert row["source_eligible_span_count"] == 0
    assert row["material_status"] == "source_content_present_unavailable"


def test_authorized_chapter_import_keeps_exact_edition_gaps_and_current_state(library):
    source = "CORE-NSCA-ESTC-5"
    edition = source + ":edition-5"
    content(library, source, locator={"chapter_id": "2", "edition_id": "other-edition"})
    assert current(library, source, "2")["material_status"] == "missing_source_content"
    result = library.import_chapter(source, Path(__file__).parents[1] / "fixtures/synthetic_knowledge.pdf",
        edition_id=edition, chapter_id="2", page_indices=[0], expected_page_indices=[0, 1],
        license_id="CC0-synthetic", rights_evidence_url="https://example.test/synthetic", authorized_by="Synthetic fixture",
        identity_review={"decision": "matched", "reviewer": "Synthetic fixture", "rationale": "Invented chapter import"},
        missing_footnote_ids=["f1"])
    stored = dumps([dict(r) for r in library.lib.sources.execute("SELECT * FROM chapter_coverage")])
    row = current(library, source, "2")
    assert row["material_status"] == "partial_chapter_content_available"
    assert row["scope_eligible_span_ids"] == sorted(result["span_ids"])
    assert row["registered_missing_pages"] == [1]
    assert row["registered_missing_footnote_ids"] == ["f1"]
    assert current(library, source, "5")["material_status"] == "missing_source_content"
    library.lib.update_state(source, "corrected_pending_review", "Synthetic source correction")
    assert current(library, source, "2")["material_status"] == "chapter_content_present_unavailable"
    assert stored == dumps([dict(r) for r in library.lib.sources.execute("SELECT * FROM chapter_coverage")])
