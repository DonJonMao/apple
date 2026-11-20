"""The real review UI consumes explicit sessions and preserves factual semantics."""
from streamlit.testing.v1 import AppTest

from healthzip.ui.health_explanation import _JOBS
from tests.training.test_sequence_review import sequence as sequence


def test_sequence_ui_shows_order_load_basis_rir_zero_and_changes_without_full_analysis(sequence):
    repo, svc, sessions, _, _ = sequence
    app = AppTest.from_string("from healthzip.db.repository import Repository\n"
        "from healthzip.ui.sequence_review import render_sequence_review\n"
        f"repo=Repository({str(repo.path)!r})\nrender_sequence_review(repo)\nrepo.close()\n").run()
    assert not app.exception
    assert app.selectbox(key="sequence_current").value == svc.get_session(sessions[1])["session_uuid"]
    app.button(key="sequence_run").click().run()
    assert not app.exception
    key = "sequence_review_job:" + str(repo.path.resolve())
    request = app.session_state[key]
    result = _JOBS[request["key"]][1].result(timeout=10)
    assert not result["possible_explanations"]
    app.run()
    assert not app.exception
    text = "\n".join(str(item.value) for item in [*app.markdown, *app.caption])
    assert "12 → 10 次" in text and "RIR 0.0 → 0.0" in text
    assert "时间先后本身不证明因果" in text
    details = app.dataframe[0].value
    assert set(details["负荷口径"]) == {"单边配重"}
    assert all(value == 0 for value in details["RIR"])
    assert all(not item.proto.expanded for item in app.expander)
    assert repo.one("SELECT count(*) FROM analysis_run")[0] == 0
    current = svc.get_session(sessions[1])
    row = current["sets"][0]
    svc.edit_set(row["set_uuid"], {"reps": 9}, base_revision=row["revision"])
    app.run()
    assert not app.exception
    assert any("训练记录或选择已改变" in item.value for item in app.caption)
    assert not app.dataframe


def test_sleep_import_and_declaration_retirement_invalidate_the_completed_review(sequence):
    from healthzip.workflows import save_context
    from healthzip.workflows.storage import withdraw_context

    repo, svc, sessions, _, _ = sequence
    app = AppTest.from_string("from healthzip.db.repository import Repository\n"
        "from healthzip.ui.sequence_review import render_sequence_review\n"
        f"repo=Repository({str(repo.path)!r})\nrender_sequence_review(repo)\nrepo.close()\n").run()
    key = "sequence_review_job:" + str(repo.path.resolve())

    def compute():
        app.button(key="sequence_run").click().run()
        _JOBS[app.session_state[key]["key"]][1].result(timeout=10)
        app.run()
        assert not app.exception and app.dataframe

    compute()
    version = svc.data_version()
    batch = repo.create_batch(file_sha256="synthetic-sleep-review", file_name="synthetic", file_size=0,
                              xml_member_path="")
    at = svc.get_session(sessions[1])["started_at"]
    repo.insert_sample(batch, {"fingerprint": "synthetic-sleep-review", "canonical_type": "sleep_stage",
        "raw_type": "HKCategoryTypeIdentifierSleepAnalysis", "category_value": "asleepcore",
        "start_utc": at, "end_utc": at, "created_at": at, "source_name": "Synthetic sleep"})
    repo.conn.commit()
    assert svc.data_version() == version
    app.run()
    assert any("训练记录或选择已改变" in item.value for item in app.caption)
    assert not app.dataframe
    context = save_context(repo, {"population": "adults"})
    app.session_state["analysis_contexts"] = {str(repo.path.resolve()): context}
    app.run()
    compute()
    withdraw_context(repo, context)
    assert svc.data_version() == version
    app.run()
    assert any("训练记录或选择已改变" in item.value for item in app.caption)
    assert not app.dataframe
