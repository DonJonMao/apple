"""Evidence input changes invalidate explanations; retrieval bookkeeping does not."""
import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

from test_v15_source_observation_entry import seed_evidence

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.model_services import ServiceConfig
from healthzip.knowledge.revisions import ensure_knowledge_revisions, knowledge_authority_clock
from healthzip.knowledge.store import Libraries
from healthzip.knowledge.vector_index import ensure_schema, save_vectors
from healthzip.science.observations import evaluate


def _metric():
    return evaluate("OBS-VO2-REPORTED", [], cutoff_time="2026-11-17T00:00:00+00:00",
                    window_start="2026-11-01T00:00:00+00:00", window_end="2026-11-17T00:00:00+00:00")


def _lookup(kb):
    return kb.retrieve_for_metric("OBS-VO2-REPORTED", "explain_metric", _metric(),
        {"population": "adults", "measurement_protocol": "synthetic"},
        mode="lexical", candidate_scope="reviewed_metric")


def test_real_retrieval_audits_and_wal_checkpoint_leave_authority_unchanged(tmp_path):
    root = tmp_path / "knowledge"
    kb = KnowledgeWorkbench(root, environment_kind="synthetic_test")
    for conn in (kb.lib.sources, kb.lib.theories):
        conn.execute("PRAGMA journal_mode=WAL")
    seed_evidence(kb, "OBS-VO2-REPORTED")
    before = knowledge_authority_clock(root)
    response = _lookup(kb)
    assert response["capability_permissions"]["source_explanation"] is True
    assert kb.lib.sources.execute("SELECT count(*) FROM metric_retrieval_audit").fetchone()[0] > 0
    assert knowledge_authority_clock(root) == before
    kb.close()
    assert knowledge_authority_clock(root) == before
    other = KnowledgeWorkbench(root, environment_kind="synthetic_test")
    assert _lookup(other)["capability_permissions"]["source_explanation"] is True
    other.close()
    assert knowledge_authority_clock(root) == before


def test_source_change_in_another_process_invalidates_without_a_shared_connection(kb):
    seed_evidence(kb, "OBS-VO2-REPORTED")
    before = knowledge_authority_clock(kb.root)
    source = kb.lib.sources.execute("SELECT source_id FROM source LIMIT 1").fetchone()[0]
    subprocess.run([sys.executable, "-c", """
import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as db:
    db.execute("UPDATE source SET scientific_state='withdrawn' WHERE source_id=?", (sys.argv[2],))
""", str(kb.root / "sources.sqlite3"), source], check=True)
    assert knowledge_authority_clock(kb.root) != before
    assert _lookup(kb)["capability_permissions"]["source_explanation"] is False


def test_claim_update_and_delete_invalidate_and_rollback_does_not(kb):
    seed_evidence(kb, "OBS-VO2-REPORTED")
    before = knowledge_authority_clock(kb.root)
    with sqlite3.connect(kb.root / "theories.sqlite3") as writer:
        writer.execute("UPDATE source_claim SET status='revoked'")
    revoked = knowledge_authority_clock(kb.root)
    assert revoked != before
    assert _lookup(kb)["capability_permissions"]["source_explanation"] is False
    kb.lib.theories.execute("BEGIN")
    kb.lib.theories.execute("DELETE FROM source_claim")
    kb.lib.theories.rollback()
    assert knowledge_authority_clock(kb.root) == revoked
    with kb.lib.theories:
        kb.lib.theories.execute("DELETE FROM source_claim")
    assert knowledge_authority_clock(kb.root) != revoked


def test_query_vectors_are_outputs_but_document_vectors_change_the_index(kb):
    ensure_schema(kb)
    provider = SimpleNamespace(config=ServiceConfig("https://example.invalid/embeddings", "synthetic"))
    before = knowledge_authority_clock(kb.root)
    save_vectors(kb, provider, ["synthetic query"], [[1.0, 0.0]], "query")
    assert knowledge_authority_clock(kb.root) == before
    save_vectors(kb, provider, ["synthetic source"], [[1.0, 0.0]], "document")
    assert knowledge_authority_clock(kb.root) != before


def test_upgrade_preserves_existing_source_payload_and_reopening_is_read_only(tmp_path):
    root = tmp_path / "legacy"
    lib = Libraries(root)
    original = ("synthetic", "doi:synthetic", json.dumps({"title": "Synthetic original"}),
                "discovered", "pending", "{}", "2026-11-01")
    with lib.sources:
        lib.sources.execute("INSERT INTO source(source_id,canonical_identity,manifest_json,state,identity_status,updates_json,updated_at) VALUES(?,?,?,?,?,?,?)", original)
    saved = tuple(lib.sources.execute("SELECT * FROM source").fetchone())
    lib.close()
    uninitialized = knowledge_authority_clock(root)
    kb = KnowledgeWorkbench(root, environment_kind="synthetic_test")
    assert tuple(kb.lib.sources.execute("SELECT * FROM source").fetchone()) == saved
    initialized = knowledge_authority_clock(root)
    assert initialized != uninitialized
    before = (kb.lib.sources.total_changes, kb.lib.theories.total_changes)
    ensure_knowledge_revisions(kb)
    assert (kb.lib.sources.total_changes, kb.lib.theories.total_changes) == before
    kb.close()
    other = KnowledgeWorkbench(root, environment_kind="synthetic_test")
    assert knowledge_authority_clock(root) == initialized
    assert other.lib.sources.total_changes == other.lib.theories.total_changes == 0
    other.close()


def test_readonly_clock_does_not_create_missing_libraries(tmp_path):
    root = tmp_path / "absent"
    first = knowledge_authority_clock(root)
    assert first == knowledge_authority_clock(root)
    assert not root.exists()
