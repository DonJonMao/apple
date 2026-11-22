"""An untouched workspace can be viewed while a writer owns the SQLite lock."""
from contextlib import closing

from healthzip.db.repository import Repository
from healthzip.ui.training_bridge import build_snapshot, handle_command


def test_empty_home_is_readonly_and_first_command_makes_catalog_available(tmp_path):
    path = tmp_path / "synthetic.sqlite3"
    with closing(Repository(path)) as writer, closing(Repository(path)) as reader:
        writer.conn.execute("BEGIN IMMEDIATE")
        reader.conn.execute("PRAGMA busy_timeout=50")
        before = reader.conn.total_changes
        state = {}
        home = build_snapshot(reader, state)
        assert reader.conn.total_changes == before
        assert home["active_sessions"] == [] and home["data_version"] == "0"
        assert home["regions"] == []
        writer.conn.rollback()
        result = handle_command(reader, {"id": "synthetic-first-start", "action": "start_session", "payload": {}}, state)
        assert result["status"] == "saved"
        started = build_snapshot(reader, state)
        assert started["session"]["session_status"] == "in_progress"
        assert started["regions"] and started["equipment_types"]
        selected = handle_command(reader, {"id": "synthetic-first-catalog", "action": "catalog", "payload": {}}, state)
        assert selected["status"] == "saved"
        assert build_snapshot(reader, state)["catalog"]
