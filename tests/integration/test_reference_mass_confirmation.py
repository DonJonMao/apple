"""The normal analysis page must bind confirmation to the selected mass source."""

import pytest
from streamlit.testing.v1 import AppTest
from test_reference_target_selection import CUTOFF, populated

from healthzip.db.repository import Repository


def test_switching_body_mass_source_requires_new_confirmation(tmp_path):
    path = tmp_path / "mass-confirmation.sqlite3"
    repo = Repository(path)
    references, masses = populated(repo, tmp_path)
    repo.close()
    app = AppTest.from_string(
        "from healthzip.db.repository import Repository\n"
        "from healthzip.analytics.v13 import analyze\n"
        "from healthzip.ui.analysis_page import render_analysis\n"
        f"repo=Repository({str(path)!r})\n"
        f"render_analysis(repo, {{'v13':analyze(repo,cutoff_time={CUTOFF!r},timezone_name='UTC')}})\n"
        "repo.close()"
    ).run(timeout=30)
    app.selectbox(key="analysis_reference_record").select("strength_set:" + references[1]["set_uuid"]).run(timeout=30)
    app.selectbox(key="analysis_reference_mass").select("health_sample:" + str(masses[1]["id"])).run(timeout=30)
    app.checkbox(key="analysis_reference_mass_confirm").check().run(timeout=30)
    app.button(key="analysis_reference_submit").click().run(timeout=30)
    assert app.session_state["analysis_reference_result"]["metrics"]["STR-30"]["value"]["ratio"] == pytest.approx(.75)

    # A different scale is a different observation even on the same local day.
    app.selectbox(key="analysis_reference_mass").select("health_sample:" + str(masses[2]["id"])).run(timeout=30)
    assert app.checkbox(key="analysis_reference_mass_confirm").value is False
    assert not any(button.label == "下载所选参考完整结果" for button in app.get("download_button"))
    app.button(key="analysis_reference_submit").click().run(timeout=30)
    pending = app.session_state["analysis_reference_result"]
    assert pending["metrics"]["STR-30"]["value"] is None
    assert "body_mass_match_not_confirmed" in pending["reference_selection"]["reason_codes"]
    assert pending["metrics"]["PRED-B0"]["value"]["predicted_reps"] == 10

    app.checkbox(key="analysis_reference_mass_confirm").check().run(timeout=30)
    app.button(key="analysis_reference_submit").click().run(timeout=30)
    confirmed = app.session_state["analysis_reference_result"]
    assert confirmed["metrics"]["STR-30"]["value"]["ratio"] == pytest.approx(60 / 90)
    assert confirmed["reference_selection"]["body_mass"]["source_name"] == "Synthetic Scale B"
    assert not app.exception and not app.error
