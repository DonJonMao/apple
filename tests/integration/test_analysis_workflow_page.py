"""Normal controls create persisted task runs, not static demonstration cards."""
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from healthzip.db.repository import Repository


def open_workflow(path):
    return AppTest.from_string(f'''from healthzip.db.repository import Repository
from healthzip.ui.workflow_page import render_workflows
repo = Repository({str(path)!r})
try:
    render_workflows(repo)
finally:
    repo.close()
''').run(timeout=30)


def test_five_page_choices_persist_and_reopen_real_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = Path(tmp_path) / "page.sqlite3"
    app = open_workflow(path)
    for wid in ["W1", "W2", "W3", "W4", "W5"]:
        app.selectbox(key="workflow_kind").select(wid).run()
        app.button(key="workflow_run").click().run(timeout=30)
        assert not app.exception and not app.error
        assert [t.label for t in app.tabs] == ["发生了什么", "是否可比", "可能因素", "下一步", "为什么", "后来怎样"]
        repo = Repository(path)
        row = repo.one("SELECT result_json FROM workflow_run WHERE workflow_id=?", (wid,))
        result = json.loads(row[0])
        assert result["user_scope"] == "local" and result["nodes"][4]["truth"] is None
        count = repo.one("SELECT count(*) FROM workflow_run")[0]
        repo.close()
        app.run(timeout=30)
        repo = Repository(path)
        assert repo.one("SELECT count(*) FROM workflow_run")[0] == count
        repo.close()
