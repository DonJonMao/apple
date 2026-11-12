"""Explicit sleep declarations use the real import, page and analysis pipeline."""

import json
from copy import deepcopy
from zipfile import ZipFile

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip

CUTOFF = "2026-11-20T12:00:00+00:00"


def sleep_repo(tmp_path, *, month="11"):
    repo = Repository(tmp_path / "synthetic-sleep-selection.sqlite3")
    path = tmp_path / "synthetic-sleep.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("export.xml", '<HealthData>' + ''.join(
            f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysis{stage}" '
            f'sourceName="{source}" startDate="2026-{month}-{day} 23:00:00 +0000" '
            f'endDate="2026-{month}-{day+1} 06:00:00 +0000"/>'
            for day, source, stage in [(16, "Synthetic Watch A", "AsleepCore"),
                (17, "Synthetic Watch A", "AsleepDeep"), (17, "Synthetic Watch B", "AsleepCore"),
                (17, "Synthetic Phone", "InBed")]) + '</HealthData>')
    assert import_apple_zip(path, repo).status == "completed"
    repo.conn.execute("UPDATE source_revision SET available_at=?", (f"2026-{month}-18T08:00:00+00:00",))
    repo.conn.commit()
    return repo


def open_app(path, *, cutoff=CUTOFF, period=None):
    return AppTest.from_string(
        "from datetime import datetime\n"
        "from unittest.mock import patch\n"
        "from healthzip.db.repository import Repository\n"
        "from healthzip.analytics.v13 import analyze\n"
        "from healthzip.ui.analysis_page import render_analysis\n"
        f"repo=Repository({str(path)!r})\n"
        "with patch('healthzip.ui.sleep_selection._now',return_value=datetime.fromisoformat('2026-11-20T12:00:01+00:00')):\n"
        f"    render_analysis(repo, {{'v13':analyze(repo,cutoff_time={cutoff!r},timezone_name='UTC',period={period!r})}})\n"
        "repo.close()"
    ).run(timeout=30)


def test_normal_page_can_declare_two_nights_without_guessing_main_episode(tmp_path):
    repo = sleep_repo(tmp_path)
    default = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC")
    assert default["metrics"]["STATE-SLEEP-MAIN"]["value"] is None
    assert default["metrics"]["STATE-SLEEP-TIMING"]["value"] is None
    path = repo.path
    repo.close()
    app = open_app(path)
    assert any(box.key == "analysis_sleep_stream" for box in app.selectbox), "A normal input for explicit sleep source/episode declarations is required."
    stream = next(value["stream_id"] for value in default["sleep_options"]["streams"] if value["source_name"] == "Synthetic Watch A")
    app.selectbox(key="analysis_sleep_stream").select(stream).run(timeout=30)
    for day in (16, 17):
        app.text_input(key="analysis_sleep_start").set_value(f"2026-11-{day}T23:00:00+00:00")
        app.text_input(key="analysis_sleep_end").set_value(f"2026-11-{day+1}T06:00:00+00:00")
        app.text_input(key="analysis_sleep_date").set_value(f"2026-11-{day+1}")
        app.button(key="analysis_sleep_add").click().run(timeout=30)
        assert not app.exception and not app.error
    assert app.selectbox(key="analysis_sleep_main").value is None
    app.button(key="analysis_sleep_submit").click().run(timeout=30)
    output = app.session_state["analysis_sleep_result"]
    assert output["metrics"]["STATE-SLEEP-MAIN"]["value"] is None
    assert output["metrics"]["STATE-SLEEP-TIMING"]["valid_n"] == 2
    main_id = output["selection_context"]["sleep_selection"]["episodes"][1]["id"]
    app.selectbox(key="analysis_sleep_main").select(main_id).run(timeout=30)
    app.button(key="analysis_sleep_submit").click().run(timeout=30)
    result = app.session_state["analysis_sleep_result"]
    main = result["metrics"]["STATE-SLEEP-MAIN"]
    assert main["value"]["observed_minutes"] == 420
    assert main["value"]["attribution_date"] == "2026-11-18"
    assert main["data_status"] == "partial" and main["value"]["complete_episode"] is False
    assert set(main["source_record_ids"]) == set(result["sleep_selection"]["episodes"][1]["source_revisions"])
    assert result["metrics"]["STATE-SLEEP-STAGE"]["value"]["stage_minutes"] == {"deep": 420}
    assert result["metrics"]["STATE-SLEEP-TIMING"]["value"]["circular_midpoint_hour"] == pytest.approx(2.5)
    assert result["sleep_selection"]["source"]["source_name"] == "Synthetic Watch A"
    assert all(row["available_at"] == row["declared_at"] for row in result["sleep_selection"]["episodes"])
    assert not app.exception and not app.error
    repo = Repository(path)
    stored = [json.loads(row["result_json"]) for row in repo.rows("SELECT result_json FROM analysis_run")]
    assert any(item.get("sleep_selection", {}).get("main_episode_id") == main_id for item in stored)
    repo.close()
    other = next(value["stream_id"] for value in default["sleep_options"]["streams"] if value["source_name"] == "Synthetic Watch B")
    app.selectbox(key="analysis_sleep_stream").select(other).run(timeout=30)
    assert app.session_state["analysis_sleep_declarations"] == []
    assert app.selectbox(key="analysis_sleep_main").value is None
    assert app.button(key="analysis_sleep_submit").disabled
    assert not any(button.label == "下载睡眠声明及完整结果" for button in app.get("download_button"))


def test_saving_an_old_month_declaration_cannot_silently_move_it_to_the_current_month(tmp_path):
    repo = sleep_repo(tmp_path, month="10")
    cutoff = "2026-10-31T12:00:00+00:00"
    before = analyze(repo, cutoff_time=cutoff, timezone_name="UTC", period="month")
    source = next(item for item in before["sleep_options"]["streams"] if item["source_name"] == "Synthetic Watch A")
    path = repo.path
    repo.close()
    app = open_app(path, cutoff=cutoff, period="month")
    app.selectbox(key="analysis_sleep_stream").select(source["stream_id"]).run(timeout=30)
    app.text_input(key="analysis_sleep_start").set_value("2026-10-17T23:00:00Z")
    app.text_input(key="analysis_sleep_end").set_value("2026-10-18T06:00:00Z")
    app.text_input(key="analysis_sleep_date").set_value("2026-10-18")
    app.button(key="analysis_sleep_add").click().run(timeout=30)
    app.button(key="analysis_sleep_submit").click().run(timeout=30)
    assert any("原分析保留" in item.value for item in app.warning)
    assert not any(button.label == "下载睡眠声明及完整结果" for button in app.get("download_button"))
    assert any(cutoff in item.value for item in app.caption)
    assert not app.exception and not app.error
    app.button(key="analysis_sleep_clear").click().run(timeout=30)
    assert app.session_state["analysis_sleep_declarations"] == []
    assert not app.exception
    repo = Repository(path)
    assert repo.one("SELECT COUNT(*) AS n FROM analysis_run")["n"] == 0
    repo.close()


def declaration_selection(repo):
    from healthzip.analytics.sleep_selection import declare_episode

    output = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC")
    options = output["sleep_options"]
    source = next(item for item in options["streams"] if item["source_name"] == "Synthetic Watch A")
    episode = declare_episode(options, source["stream_id"], start="2026-11-17T23:00:00+00:00",
        end="2026-11-18T06:00:00+00:00", attribution_date="2026-11-18", declared_at="2026-11-20T12:00:01+00:00")
    return {"stream_id": source["stream_id"], "episodes": [episode], "main_episode_id": episode["id"]}


def test_sleep_submission_preserves_the_user_selected_strength_and_mass_context(tmp_path):
    from test_reference_target_selection import populated

    repo = sleep_repo(tmp_path)
    references, masses = populated(repo, tmp_path)
    before = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC")
    stream = next(item["stream_id"] for item in before["sleep_options"]["streams"] if item["source_name"] == "Synthetic Watch A")
    path = repo.path
    repo.close()
    app = open_app(path)
    reference_id = "strength_set:" + references[1]["set_uuid"]
    # The fixture also contains sleep records, so resolve a real same-day mass.
    mass = next(item for item in masses if item["source_name"] == "Synthetic Scale A" and item["end_utc"].startswith("2026-11-18"))
    app.selectbox(key="analysis_reference_record").select(reference_id).run(timeout=30)
    app.selectbox(key="analysis_reference_mass").select("health_sample:" + str(mass["id"])).run(timeout=30)
    app.checkbox(key="analysis_reference_mass_confirm").check().run(timeout=30)
    app.button(key="analysis_reference_submit").click().run(timeout=30)
    app.selectbox(key="analysis_sleep_stream").select(stream).run(timeout=30)
    app.text_input(key="analysis_sleep_start").set_value("2026-11-17T23:00:00Z")
    app.text_input(key="analysis_sleep_end").set_value("2026-11-18T06:00:00Z")
    app.text_input(key="analysis_sleep_date").set_value("2026-11-18")
    app.button(key="analysis_sleep_add").click().run(timeout=30)
    main_id = app.session_state["analysis_sleep_declarations"][0]["id"]
    app.selectbox(key="analysis_sleep_main").select(main_id).run(timeout=30)
    app.button(key="analysis_sleep_submit").click().run(timeout=30)
    result = app.session_state["analysis_sleep_result"]
    assert result["metrics"]["STR-30"]["value"]["ratio"] == pytest.approx(.75)
    assert result["metrics"]["STATE-SLEEP-MAIN"]["value"]["observed_minutes"] == 420
    assert result["selection_context"]["reference_selection"]["reference_record_id"] == reference_id
    assert result["selection_context"]["sleep_selection"]["main_episode_id"] == main_id
    assert not app.exception and not app.error


def test_declaration_cannot_appear_at_an_earlier_cutoff(tmp_path):
    repo = sleep_repo(tmp_path)
    selected = declaration_selection(repo)
    result = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", context={"sleep_selection": selected})
    assert result["sleep_selection"]["accepted"] is False
    assert "sleep_declaration_after_analysis_cutoff" in result["sleep_selection"]["reason_codes"]
    for identity, metric in result["metrics"].items():
        if identity.startswith("STATE-SLEEP-"):
            assert metric["value"] is None and metric["data_status"] == "insufficient"
    repo.close()


@pytest.mark.parametrize("change", ["revision", "deleted"])
def test_source_change_requires_reconfirmation_without_substituting_another_watch(tmp_path, change):
    repo = sleep_repo(tmp_path)
    selected = declaration_selection(repo)
    before = analyze(repo, cutoff_time="2026-11-21T00:00:00Z", timezone_name="UTC", context={"sleep_selection": selected})
    assert before["metrics"]["STATE-SLEEP-MAIN"]["value"]["observed_minutes"] == 420
    original_revision = repo.one("SELECT MAX(revision_id) AS n FROM source_revision")["n"]
    if change == "revision":
        repo.conn.execute("UPDATE health_sample SET end_utc='2026-11-18T05:00:00Z' WHERE source_name='Synthetic Watch A' AND end_utc LIKE '2026-11-18%'")
    else:
        repo.conn.execute("UPDATE health_sample SET record_status='deleted' WHERE source_name='Synthetic Watch A'")
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-21T01:00:00Z' WHERE revision_id>?", (original_revision,))
    repo.conn.commit()
    old = analyze(repo, cutoff_time="2026-11-21T00:00:00Z", timezone_name="UTC", context={"sleep_selection": selected})
    assert old["metrics"]["STATE-SLEEP-MAIN"]["value"] == before["metrics"]["STATE-SLEEP-MAIN"]["value"]
    current = analyze(repo, cutoff_time="2026-11-22T00:00:00Z", timezone_name="UTC", context={"sleep_selection": selected})
    assert current["sleep_selection"]["accepted"] is False
    assert all(current["metrics"][identity]["value"] is None for identity in
        ("STATE-SLEEP-MAIN", "STATE-SLEEP-STAGE", "STATE-SLEEP-24H", "STATE-SLEEP-TIMING"))
    repo.close()


def test_duplicate_episodes_and_invalid_attribution_cannot_gain_extra_nights(tmp_path):
    from healthzip.analytics.sleep_selection import declare_episode

    repo = sleep_repo(tmp_path)
    selected = declaration_selection(repo)
    selected["episodes"].append(deepcopy(selected["episodes"][0]))
    result = analyze(repo, cutoff_time="2026-11-21T00:00:00Z", timezone_name="UTC", context={"sleep_selection": selected})
    assert "overlapping_sleep_declarations_not_independent_episodes" in result["sleep_selection"]["reason_codes"]
    assert result["metrics"]["STATE-SLEEP-TIMING"]["value"] is None
    options = result["sleep_options"]
    with pytest.raises(ValueError, match="attribution_date"):
        declare_episode(options, selected["stream_id"], start="2026-11-17T23:00:00Z", end="2026-11-18T06:00:00Z",
            attribution_date="2026-11-15", declared_at="2026-11-21T00:00:00Z")
    with pytest.raises(ValueError, match="not_ended"):
        declare_episode(options, selected["stream_id"], start="2026-11-17T23:00:00Z", end="2026-11-18T06:00:00Z",
            attribution_date="2026-11-18", declared_at="2026-11-18T05:59:59Z")
    repo.close()


@pytest.mark.parametrize("end,accepted,minutes", [
    ("2026-11-18T05:59:59.999999Z", True, 420 - 1 / 60_000_000),
    ("2026-11-18T06:00:00Z", True, 420),
    ("2026-11-18T06:00:00.000001Z", False, None),
])
def test_main_sleep_support_allows_exact_window_end_without_future_support(tmp_path, end, accepted, minutes):
    from healthzip.analytics.sleep_selection import (
        declare_episode,
        selected_sleep_metrics,
        sleep_options,
    )
    from healthzip.analytics.v13 import snapshot
    from healthzip.science.contracts import Window

    repo = sleep_repo(tmp_path)
    rows, _ = snapshot(repo, CUTOFF)
    window = Window("2026-11-17T23:00:00Z", "2026-11-18T06:00:00Z", CUTOFF, "UTC")
    options = sleep_options(rows, window)
    source = next(item for item in options["streams"] if item["source_name"] == "Synthetic Watch A")
    episode = declare_episode(options, source["stream_id"], start=window.start, end=end,
        attribution_date="2026-11-18", declared_at=CUTOFF)
    metrics, audit = selected_sleep_metrics(rows, window, {"stream_id": source["stream_id"],
        "episodes": [episode], "main_episode_id": episode["id"]})
    assert audit["accepted"] is accepted
    if accepted:
        assert metrics["STATE-SLEEP-MAIN"]["value"]["observed_minutes"] == pytest.approx(minutes)
    else:
        assert metrics["STATE-SLEEP-MAIN"]["value"] is None
    repo.close()
