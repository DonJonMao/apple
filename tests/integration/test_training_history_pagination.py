"""All history remains reachable through bounded normal training-page controls."""

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService


def populated(path):
    repo = Repository(path)
    svc = TrainingService(repo)
    old = []
    for index in range(53):
        row = svc.start_session(f"Synthetic old {index}", started_at="2020-01-01T12:00:00+00:00")
        svc.end_session(row["id"], base_revision=row["revision"])
        old.append(row["id"])
    current = svc.start_session("Synthetic current")
    return repo, svc, old, current


def test_paged_session_inventory_preserves_all_ids_and_filters(tmp_path):
    repo, svc, old, current = populated(tmp_path / "synthetic-pages.sqlite3")
    other = TrainingService(repo, user_id="synthetic-other")
    other.start_session("Other user")
    removed = svc.delete_session(old[0], base_revision=svc.get_session(old[0])["revision"])
    assert removed["event_id"]
    assert svc.count_sessions() == 53
    assert svc.count_sessions(include_deleted=True) == 54
    assert svc.count_sessions(active_only=True) == 1
    pages = [svc.list_sessions(include_deleted=True, limit=10, offset=offset)
             for offset in range(0, 60, 10)]
    assert [row["id"] for page in pages for row in page] == [current["id"], *reversed(old)]
    assert len(svc.list_sessions(include_deleted=True)) == 54
    assert [row["id"] for row in svc.list_sessions(active_only=True)] == [current["id"]]
    repo.close()


def test_normal_training_page_paginates_and_keeps_active_session(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    path = tmp_path / "synthetic-ui-pages.sqlite3"
    repo, _, old, current = populated(path)
    repo.close()
    monkeypatch.chdir(tmp_path)
    returned = []
    original = TrainingService.list_sessions

    def counted(self, **kwargs):
        rows = original(self, **kwargs)
        returned.append((kwargs, len(rows)))
        return rows

    monkeypatch.setattr(TrainingService, "list_sessions", counted)
    script = ("from healthzip.db.repository import Repository\n"
              "from healthzip.ui.training_page import render_training\n"
              f"repo=Repository({str(path)!r})\nrender_training(repo)\nrepo.close()")
    app = AppTest.from_string(script).run(timeout=30)
    assert not app.exception
    history = next(widget for widget in app.selectbox if widget.label == "训练历史")
    assert len(history.options) == 50
    assert app.selectbox(key="resume_training").value == current["id"]
    app.number_input(key="training_history_page").set_value(2).run(timeout=30)
    assert not app.exception
    history = app.selectbox(key="training_history_session")
    assert len(history.options) == 4
    history.set_value(old[0]).run(timeout=30)
    app.text_input(key=f"history_session_name_{old[0]}").set_value("Corrected oldest synthetic")
    next(widget for widget in app.button if widget.label == "保存训练信息").click().run(timeout=30)
    assert not app.exception and not app.error
    assert app.selectbox(key="resume_training").value == current["id"]
    assert app.selectbox(key="training_history_session").value == old[0]
    repo = Repository(path)
    svc = TrainingService(repo)
    assert svc.get_session(old[0])["name"] == "Corrected oldest synthetic"
    assert svc.get_session(current["id"])["session_status"] == "in_progress"
    assert len(svc.list_sessions(include_deleted=True)) == 54
    repo.close()
    assert all(size <= 50 for _, size in returned[:-1])
    assert all(args.get("active_only") or args.get("limit") == 50
               for args, _ in returned[:-1])
