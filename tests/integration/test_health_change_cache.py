"""Knowledge bookkeeping and explicit invalidation have separate identities."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from healthzip.analytics.cache import cached, clear, revision_identity
from healthzip.db.repository import Repository
from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.revisions import prepare_retrieval_revisions


def test_full_analysis_cache_ignores_audit_io_but_not_reviewed_input_changes(tmp_path):
    repo = Repository(tmp_path / "synthetic.sqlite3")
    kb = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    try:
        prepare_retrieval_revisions(kb)
        before = revision_identity(repo, kb.root)
        kb.lib.sources.execute("CREATE TABLE synthetic_audit(entry TEXT)")
        kb.lib.sources.execute("INSERT INTO synthetic_audit VALUES('retrieval completed')")
        kb.lib.sources.commit()
        assert revision_identity(repo, kb.root) == before
        kb.lib.sources.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert revision_identity(repo, kb.root) == before
        kb.lib.seed({"sources": [{"source_id": "synthetic-new", "title": "Synthetic",
                                  "canonical_url": "https://example.invalid/test"}]}, {"cards": []})
        assert revision_identity(repo, kb.root) != before
    finally:
        kb.close()
        repo.close()


def test_explicit_clear_during_compute_prevents_old_task_repopulating_cache(tmp_path):
    path = tmp_path / "synthetic.sqlite3"
    repo = Repository(path)
    repo.close()
    entered, release = threading.Event(), threading.Event()
    clear()

    def worker():
        local = Repository(path)
        try:
            def compute():
                entered.set()
                assert release.wait(10)
                return "old calculation"
            return cached(local, "clear-race", {}, compute, dependencies=[])
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(worker)
        assert entered.wait(5)
        clear()
        release.set()
        assert result.result(5) == "old calculation"
    repo = Repository(path)
    try:
        assert cached(repo, "clear-race", {}, lambda: "fresh", dependencies=[]) == "fresh"
    finally:
        repo.close()
        clear()


def test_knowledge_root_isolation_for_equal_private_workspaces(tmp_path):
    repo = Repository(tmp_path / "synthetic.sqlite3")
    try:
        a = cached(repo, "root-isolation", {}, lambda: "a", knowledge_root=tmp_path / "a")
        b = cached(repo, "root-isolation", {}, lambda: "b", knowledge_root=tmp_path / "b")
        assert (a, b) == ("a", "b")
    finally:
        repo.close()
        clear()


def test_range_and_source_switch_reuses_resolved_month_partitions(tmp_path, monkeypatch):
    import healthzip.analytics.workspaces as workspaces

    repo = Repository(tmp_path / "synthetic.sqlite3")
    calls = []
    original = workspaces.samples_as_of

    def query(*args, **kwargs):
        calls.append(kwargs.get("window_start"))
        return original(*args, **kwargs)

    monkeypatch.setattr(workspaces, "samples_as_of", query)
    try:
        cutoff = workspaces.instant("2026-11-22T00:00:00+08:00")
        types = ("resting_heart_rate_bpm", "hrv_sdnn_ms")
        workspaces._body_snapshot(repo, cutoff, workspaces.instant("2026-10-18T00:00:00+08:00"), types)
        count = len(calls)
        assert count == 2
        workspaces._body_snapshot(repo, cutoff, workspaces.instant("2026-10-22T00:00:00+08:00"), types,
                                  source_filter=["Synthetic Watch"])
        assert len(calls) == count, "Overlapping ranges must reuse resolved source partitions"
        # A different historical visibility boundary may not reuse those reads.
        workspaces._body_snapshot(repo, cutoff-workspaces.timedelta(days=1),
                                  workspaces.instant("2026-10-22T00:00:00+08:00"), types)
        assert len(calls) > count
    finally:
        repo.close()
        clear()


def test_future_record_endpoint_cannot_be_reported_as_latest_observation(tmp_path):
    from healthzip.analytics.workspaces import analyze_workspace

    repo = Repository(tmp_path / "synthetic.sqlite3")
    try:
        payload = {"id": 1, "canonical_type": "heart_rate_bpm", "normalized_value": 80,
            "normalized_unit": "bpm", "start_utc": "2026-11-18T10:00:00Z",
            "end_utc": "2026-11-19T10:00:00Z", "source_name": "Synthetic"}
        repo.conn.execute("INSERT INTO source_revision(table_name,record_id,available_at,payload_json,temporal_provenance) "
                          "VALUES('health_sample',1,'2026-11-18T10:00:00Z',?,'synthetic')", (json.dumps(payload),))
        repo.conn.commit()
        view = analyze_workspace(repo, "心率", cutoff_time="2026-11-18T12:00:00Z")
        assert view["heart"]["ordinary_sample_count"] == 0
        assert view["workspace_scope"]["latest_observed_at"] is None
    finally:
        repo.close()
        clear()


def test_report_content_signature_is_identical_cached_and_revocable(tmp_path, monkeypatch):
    import healthzip.training.current as current

    kb = KnowledgeWorkbench(tmp_path / "knowledge", environment_kind="synthetic_test")
    try:
        prepare_retrieval_revisions(kb)
        original = current._knowledge_signature_uncached
        calls = []

        def scan(root):
            calls.append(1)
            return original(root)

        monkeypatch.setattr(current, "_knowledge_signature_uncached", scan)
        first = current.knowledge_signature(kb.root)
        assert first == original(kb.root)
        assert current.knowledge_signature(kb.root) == first and len(calls) == 1
        kb.lib.seed({"sources": [{"source_id": "synthetic-revision", "title": "Revision",
            "canonical_url": "https://example.invalid/revision"}]}, {"cards": []})
        second = current.knowledge_signature(kb.root)
        assert second != first and second == original(kb.root) and len(calls) == 2
        # An incomplete revision tracker is not safe for memoization.
        kb.lib.sources.execute('DROP TRIGGER knowledge_authority_source_update')
        kb.lib.sources.commit()
        assert current.knowledge_signature(kb.root) == second
        kb.lib.sources.execute("UPDATE source SET manifest_json=json_set(manifest_json,'$.title','Changed source') WHERE source_id='synthetic-revision'")
        kb.lib.sources.commit()
        assert current.knowledge_signature(kb.root) != second and len(calls) == 4
    finally:
        kb.close()
