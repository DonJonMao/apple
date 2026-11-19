"""Rebuildable analysis caches prepare outside their SQLite write lock."""

import json
import sqlite3

import pytest

from healthzip.analytics.core import evidence_card, persist_analysis
from healthzip.analytics.v13 import persist
from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService


def canonical_result(repo):
    return {"cutoff_time": "2026-11-19T08:00:00+00:00",
            "algorithm_version": "synthetic-persistence-check",
            "data_hash": "synthetic-input-hash", "data_version": TrainingService(repo).data_version()}


def cache_analysis(repo):
    return {"v13": canonical_result(repo),
            "heart": {"cards": [evidence_card("synthetic-one", "Synthetic one", "provisional", "Observed"),
                                  evidence_card("synthetic-two", "Synthetic two", "provisional", "Observed")]},
            "sleep": {"nights": [{"date": "2026-11-18", "sleep_hours": 7.0,
                                    "source_ids": ["health_sample:synthetic"]}]},
            "weight": {"daily": [{"date": "2026-11-18", "kg": 70.0,
                                    "source_ids": ["body_measurement:synthetic"]}]}}


def reserve_writer(path):
    other = sqlite3.connect(path, timeout=0)
    try:
        other.execute("BEGIN IMMEDIATE")
        other.rollback()
    finally:
        other.close()


def test_card_and_feature_preparation_leave_second_connection_writeable(tmp_path):
    repo = Repository(tmp_path / "synthetic.sqlite3")
    calls = []

    class CheckedSources(list):
        def __iter__(self):
            reserve_writer(repo.path)
            calls.append("prepared_without_write_lock")
            return super().__iter__()

    try:
        analysis = cache_analysis(repo)
        analysis["heart"]["cards"][1]["source_feature_ids"] = CheckedSources(["synthetic-feature"])
        analysis["sleep"]["nights"][0]["source_ids"] = CheckedSources(["health_sample:synthetic"])
        persist_analysis(repo, analysis)
        assert len(calls) >= 2
        assert repo.one("SELECT COUNT(*) FROM insight")[0] == 2 and repo.one("SELECT COUNT(*) FROM daily_feature")[0] == 2
        assert json.loads(repo.one("SELECT source_feature_ids_json FROM insight WHERE id='synthetic-two'")[0]) == ["synthetic-feature"]
        assert json.loads(repo.one("SELECT source_ids_json FROM daily_feature WHERE metric='sleep_hours'")[0]) == ["health_sample:synthetic"]
        assert repo.one("SELECT COUNT(*) FROM analysis_run")[0] == 1
        assert not repo.conn.in_transaction
        reserve_writer(repo.path)
    finally:
        repo.close()


def test_failed_cache_batch_rolls_back_together_and_keeps_frozen_analysis(tmp_path):
    repo = Repository(tmp_path / "synthetic.sqlite3")
    try:
        analysis = cache_analysis(repo)
        repo.conn.execute("""CREATE TEMP TRIGGER synthetic_cache_failure BEFORE INSERT ON daily_feature
            WHEN NEW.metric='body_mass' BEGIN SELECT RAISE(ABORT,'synthetic feature failure'); END""")
        with pytest.raises(sqlite3.IntegrityError, match="synthetic feature failure"):
            persist_analysis(repo, analysis)
        assert repo.one("SELECT COUNT(*) FROM insight")[0] == 0 and repo.one("SELECT COUNT(*) FROM daily_feature")[0] == 0
        assert repo.one("SELECT COUNT(*) FROM analysis_run")[0] == 1
        assert not repo.conn.in_transaction
        reserve_writer(repo.path)
    finally:
        repo.close()


def test_cancelled_cache_batch_releases_its_write_lock(tmp_path):
    class Cancelled(BaseException):
        pass

    class CancellingConnection(sqlite3.Connection):
        def executemany(self, sql, rows):
            if "INSERT OR REPLACE INTO daily_feature" in sql:
                super().executemany(sql, rows[:1])
                raise Cancelled("synthetic rerun interruption")
            return super().executemany(sql, rows)

    repo = Repository(tmp_path / "synthetic.sqlite3")
    try:
        analysis = cache_analysis(repo)
        repo.conn.close()
        repo.conn = sqlite3.connect(repo.path, factory=CancellingConnection)
        repo.conn.row_factory = sqlite3.Row
        with pytest.raises(Cancelled):
            persist_analysis(repo, analysis)
        assert repo.one("SELECT COUNT(*) FROM insight")[0] == 0 and repo.one("SELECT COUNT(*) FROM daily_feature")[0] == 0
        assert repo.one("SELECT COUNT(*) FROM analysis_run")[0] == 1
        assert not repo.conn.in_transaction
        reserve_writer(repo.path)
    finally:
        repo.close()


def test_canonical_service_initialization_precedes_analysis_write(tmp_path, monkeypatch):
    repo = Repository(tmp_path / "synthetic.sqlite3")
    checked = []

    class CheckedService(TrainingService):
        def __init__(self, repository):
            reserve_writer(repository.path)
            checked.append(True)
            super().__init__(repository)

    try:
        result = canonical_result(repo)
        monkeypatch.setattr("healthzip.analytics.v13.TrainingService", CheckedService)
        run_id = persist(repo, result)
        assert checked == [True]
        assert repo.one("SELECT run_id FROM analysis_run")[0] == run_id
        assert not repo.conn.in_transaction
    finally:
        repo.close()


@pytest.mark.parametrize("kind", ["cache", "canonical"])
@pytest.mark.parametrize("outer_transaction", [False, True])
def test_commit_cancellation_rolls_back_batch_and_preserves_caller_edits(tmp_path, kind, outer_transaction):
    class CommitCancelled(BaseException):
        pass

    class CommitFailureConnection(sqlite3.Connection):
        fail_commits = False

        def commit(self):
            if self.fail_commits:
                raise CommitCancelled("synthetic cancellation at commit")
            return super().commit()

    repo = Repository(tmp_path / "synthetic.sqlite3")
    try:
        result = canonical_result(repo)
        repo.conn.close()
        repo.conn = sqlite3.connect(repo.path, factory=CommitFailureConnection)
        repo.conn.row_factory = sqlite3.Row
        if outer_transaction:
            repo.conn.execute("INSERT INTO schema_meta VALUES('synthetic_pending_edit','preserved')")
        repo.conn.fail_commits = True
        with pytest.raises(CommitCancelled):
            if kind == "canonical":
                persist(repo, result)
            else:
                persist_analysis(repo, {"heart": {"cards": [evidence_card(
                    "synthetic-cache", "Synthetic", "provisional", "Observed")]}})
        assert repo.one("SELECT COUNT(*) FROM analysis_run")[0] == 0
        assert repo.one("SELECT COUNT(*) FROM insight")[0] == 0
        assert repo.conn.in_transaction is outer_transaction
        if outer_transaction:
            assert repo.one("SELECT value FROM schema_meta WHERE key='synthetic_pending_edit'")[0] == "preserved"
            other = sqlite3.connect(repo.path)
            try:
                assert other.execute("SELECT value FROM schema_meta WHERE key='synthetic_pending_edit'").fetchone() is None
            finally:
                other.close()
            repo.conn.fail_commits = False
            repo.conn.commit()
        reserve_writer(repo.path)
    finally:
        repo.close()
