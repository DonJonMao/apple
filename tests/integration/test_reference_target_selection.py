"""Select real persisted reference tasks and dated mass through the analysis UI."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService

CUTOFF = "2026-11-20T12:00:00+00:00"


def populated(repo, folder, *, basis="external_total_kg", unit="kg", load=60):
    service = TrainingService(repo)
    equipment = service.create_equipment("Synthetic task bar", "barbell")
    condition = {"equipment_instance_id": equipment["id"], "load_basis": basis,
                 "load_basis_confirmed": True, "side": "both", "repetition_semantics": "simultaneous",
                 "rom_protocol": "declared_full", "settings": {"grip": "declared"}, "settings_confirmed": True,
                 "reference_protocol": {"protocol_id": "synthetic-reference", "version": "1",
                     "reference_policy_id": "first_work_set", "effort_protocol": "target_rir_2",
                     "tempo": "2-0-1", "rest_protocol": "120_seconds_before_reference"}}
    saved = []
    for day, reps in ((17, 8), (18, 10)):
        start = datetime.fromisoformat(f"2026-11-{day}T09:00:00+00:00")
        clock = [start]
        with patch("healthzip.training.service.timestamp", lambda value=None: timestamp(value or clock[0].isoformat())):
            session = service.start_session("Synthetic task", started_at=start.isoformat())
            exercise = service.add_exercise(session["id"], "psa.ex.barbell_bench_press", condition)
            draft = service.add_set(exercise["id"], {"reference_set": True, "set_number": 1})
            clock[0] = start + timedelta(minutes=2)
            saved.append(service.edit_set(draft["set_uuid"], {"completion_state": "completed", "reps": reps,
                "load_value": load, "load_unit": unit, "rir": 2, "quality_status": "acceptable",
                "pain_flag": False, "stop_reason": "target_rir", "started_at": (start+timedelta(minutes=1)).isoformat(),
                "ended_at": clock[0].isoformat()}, base_revision=draft["revision"]))
            clock[0] = start + timedelta(hours=1)
            service.end_session(session["id"], ended_at=clock[0].isoformat())
    path = folder / "synthetic-mass.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("export.xml", '<HealthData>' + ''.join(
            f'<Record type="HKQuantityTypeIdentifierBodyMass" unit="{mass_unit}" value="{mass}" '
            f'sourceName="{source}" startDate="2026-11-{day} 08:00:00 +0000" '
            f'endDate="2026-11-{day} 08:00:00 +0000"/>'
            for day, mass, mass_unit, source in [(17, 80, "kg", "Synthetic Scale A"),
                (18, 176.36980974790205, "lb", "Synthetic Scale A"), (18, 90, "kg", "Synthetic Scale B")]) + '</HealthData>')
    assert import_apple_zip(path, repo).status == "completed"
    # Test-only controlled import visibility; the product still reads the actual
    # immutable revision payload through Repository/samples_as_of.
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-18T08:30:00+00:00' WHERE table_name='health_sample'")
    repo.conn.commit()
    masses = [dict(row) for row in repo.rows("SELECT id,source_name,end_utc FROM health_sample ORDER BY id")]
    return saved, masses


def selection(output, saved, mass, **extra):
    return {"task_id": output["strength_tasks"][0]["task_id"],
            "reference_record_id": "strength_set:"+saved["set_uuid"],
            "body_mass_record_id": "health_sample:"+str(mass["id"]),
            "body_mass_matches_reference": True, **extra}


def test_repository_selection_populates_ratio_and_same_load_b0_with_provenance(tmp_path):
    repo = Repository(tmp_path / "selection.sqlite3")
    try:
        saved, mass = populated(repo, tmp_path)
        before = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", use_cache=False)
        chosen = selection(before, saved[1], mass[1])
        output = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", context={"reference_selection": chosen}, use_cache=False)
        ratio, b0 = output["metrics"]["STR-30"], output["metrics"]["PRED-B0"]
        assert ratio["value"] is not None, "A visible matched reference and mass must reach STR-30 without raw context injection."
        assert ratio["value"]["ratio"] == pytest.approx(.75)
        assert ratio["value"]["numerator_identity"] == "observed_complete_external_load"
        assert ratio["value"]["body_mass_normalization"]["raw_unit"] == "lb"
        assert set(ratio["source_record_ids"]) == {chosen["reference_record_id"], chosen["body_mass_record_id"]}
        assert b0["value"]["predicted_reps"] == 10 and b0["value"]["previous_rir"] == 2
        assert b0["value"]["reference_id"] == chosen["reference_record_id"]
        assert ratio["evidence_status"] == b0["evidence_status"] == "descriptive"
        assert ratio["coverage"][0]["numerator"] == ratio["coverage"][0]["denominator"] == 1
        assert ratio["excluded_n"] == 0
        assert not b0["calibration_artifact_id"]
        assert output["reference_selection"]["selection"] == chosen
        task = next(task for task in output["strength_tasks"] if task["task_id"] == chosen["task_id"])
        assert task["metrics"]["PRED-B0"] == b0
    finally:
        repo.close()


def test_normal_analysis_offers_explicit_choices_without_selecting_mass_or_target(tmp_path):
    repo = Repository(tmp_path / "options.sqlite3")
    try:
        saved, _ = populated(repo, tmp_path)
        output = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", use_cache=False)
        assert {row["record_id"] for row in output["reference_options"]["references"]} == {"strength_set:"+row["set_uuid"] for row in saved}
        assert len(output["reference_options"]["body_mass"]) == 3
        assert output["metrics"]["STR-30"]["value"] is None
        assert output["metrics"]["PRED-B0"]["value"] is None
    finally:
        repo.close()


def test_mismatched_day_and_unconfirmed_mass_do_not_silently_become_a_ratio(tmp_path):
    repo = Repository(tmp_path / "dates.sqlite3")
    try:
        saved, mass = populated(repo, tmp_path)
        before = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", use_cache=False)
        for chosen, reason in [(selection(before, saved[1], mass[0]), "body_mass_local_date_mismatch"),
                               (selection(before, saved[1], mass[1], body_mass_matches_reference=False), "body_mass_match_not_confirmed")]:
            output = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", context={"reference_selection": chosen}, use_cache=False)
            assert output["metrics"]["STR-30"]["value"] is None
            ratio = output["metrics"]["STR-30"]
            assert ratio["valid_n"] == ratio["coverage"][0]["numerator"] == 0
            assert ratio["total_n"] == ratio["coverage"][0]["denominator"] == ratio["excluded_n"] == 1
            assert reason in output["reference_selection"]["reason_codes"]
            assert output["metrics"]["PRED-B0"]["value"]["predicted_reps"] == 10
    finally:
        repo.close()


def test_actual_analysis_ui_selects_repository_inputs_and_persists_result(tmp_path):
    from streamlit.testing.v1 import AppTest

    path = tmp_path / "selection-ui.sqlite3"
    repo = Repository(path)
    saved, mass = populated(repo, tmp_path)
    repo.close()
    app = AppTest.from_string(
        "from healthzip.db.repository import Repository\nfrom healthzip.analytics.v13 import analyze\n"
        "from healthzip.ui.analysis_page import render_analysis\n"
        f"repo=Repository({str(path)!r})\n"
        f"render_analysis(repo, {{'v13':analyze(repo,cutoff_time={CUTOFF!r},timezone_name='UTC')}})\nrepo.close()"
    ).run(timeout=30)
    assert not app.exception
    app.selectbox(key="analysis_reference_record").select("strength_set:"+saved[1]["set_uuid"]).run(timeout=30)
    app.selectbox(key="analysis_reference_mass").select("health_sample:"+str(mass[1]["id"])).run(timeout=30)
    app.checkbox(key="analysis_reference_mass_confirm").check().run(timeout=30)
    app.button(key="analysis_reference_submit").click().run(timeout=30)
    assert not app.exception and not app.error
    result = app.session_state["analysis_reference_result"]
    assert result["metrics"]["STR-30"]["value"]["ratio"] == pytest.approx(.75)
    assert result["metrics"]["PRED-B0"]["value"]["predicted_reps"] == 10
    assert any(button.label == "下载所选参考完整结果" for button in app.get("download_button"))
    # Changing the task clears its mass/confirmation and hides the old result.
    app.selectbox(key="analysis_reference_record").select("strength_set:"+saved[0]["set_uuid"]).run(timeout=30)
    assert app.selectbox(key="analysis_reference_mass").value is None
    assert app.checkbox(key="analysis_reference_mass_confirm").value is False
    assert not any(button.label == "下载所选参考完整结果" for button in app.get("download_button"))
    assert not app.exception
    repo = Repository(path)
    try:
        stored = [json.loads(row["result_json"]) for row in repo.rows("SELECT result_json FROM analysis_run")]
        assert any(item.get("reference_selection", {}).get("selection", {}).get("reference_record_id") == "strength_set:"+saved[1]["set_uuid"] for item in stored)
    finally:
        repo.close()


@pytest.mark.parametrize("change", ["late", "deleted", "unknown_protocol"])
def test_selected_reference_must_still_be_visible_and_protocol_eligible(tmp_path, change):
    repo = Repository(tmp_path / "excluded-reference.sqlite3")
    try:
        saved, mass = populated(repo, tmp_path)
        base = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", use_cache=False)
        chosen = selection(base, saved[1], mass[1])
        if change == "late":
            # A session snapshot also contains its sets; make the whole second
            # session unavailable instead of hiding only individual set events.
            repo.conn.execute("UPDATE training_event SET recorded_at='2026-11-21T10:00:00Z' WHERE recorded_at >= '2026-11-18'")
            repo.conn.commit()
        elif change == "deleted":
            with patch("healthzip.training.service.timestamp", lambda value=None: timestamp(value or "2026-11-19T10:00:00+00:00")):
                TrainingService(repo).delete_set(saved[1]["set_uuid"], base_revision=saved[1]["revision"])
        else:
            # The adapter must reject a current source with no protocol, even
            # when a caller passes a formerly eligible task/record identifier.
            from healthzip.analytics.reference_selection import selected_reference_metrics
            from healthzip.analytics.v13 import snapshot
            from healthzip.science.contracts import Window

            records, _ = snapshot(repo, CUTOFF)
            selected_row = next(row for row in records if row["id"] == chosen["reference_record_id"])
            condition = json.loads(selected_row["condition_json"])
            condition["reference_protocol"] = None
            selected_row["condition_json"] = json.dumps(condition)
            selected_row["condition"] = condition
            metrics, audit = selected_reference_metrics(records, Window(base["window_start"], CUTOFF, CUTOFF, "UTC"), chosen, data_version=base["data_version"])
            assert metrics["STR-30"]["value"] is metrics["PRED-B0"]["value"] is None
            assert "reference_record_unavailable_or_ineligible" in audit["reason_codes"]
            return
        output = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", use_cache=False, context={"reference_selection": chosen})
        assert output["metrics"]["STR-30"]["value"] is output["metrics"]["PRED-B0"]["value"] is None
        assert "reference_record_unavailable_or_ineligible" in output["reference_selection"]["reason_codes"]
    finally:
        repo.close()


@pytest.mark.parametrize("basis,unit,load,expected", [
    ("external_total_kg", "lb", 176.36980974790205, 1.0),
    ("plates_per_side_kg", "kg", 30, None),
    ("per_dumbbell_kg", "kg", 30, None),
])
def test_ratio_normalizes_complete_load_without_inventing_bar_or_implement_mass(tmp_path, basis, unit, load, expected):
    repo = Repository(tmp_path / "loads.sqlite3")
    try:
        saved, mass = populated(repo, tmp_path, basis=basis, unit=unit, load=load)
        base = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", use_cache=False)
        output = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", use_cache=False,
                         context={"reference_selection": selection(base, saved[1], mass[1])})
        ratio = output["metrics"]["STR-30"]
        if expected is None:
            assert ratio["value"] is None and ratio["valid_n"] == 0
            assert "complete_external_load_unknown" in ratio["reason_codes"]
        else:
            assert ratio["value"]["ratio"] == pytest.approx(expected)
        assert output["metrics"]["PRED-B0"]["value"]["predicted_reps"] == 10
    finally:
        repo.close()


def test_changed_load_never_reuses_the_most_recent_different_load_outcome(tmp_path):
    repo = Repository(tmp_path / "different-load.sqlite3")
    try:
        saved, mass = populated(repo, tmp_path)
        with patch("healthzip.training.service.timestamp", lambda value=None: timestamp(value or "2026-11-19T10:00:00+00:00")):
            TrainingService(repo).edit_set(saved[1]["set_uuid"], {"load_value": 65}, base_revision=saved[1]["revision"])
        base = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", use_cache=False)
        for index, reps in [(0, 8), (1, 10)]:
            output = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", use_cache=False,
                             context={"reference_selection": selection(base, saved[index], mass[index])})
            b0 = output["metrics"]["PRED-B0"]
            assert b0["value"]["predicted_reps"] == reps
            assert b0["source_record_ids"] == ["strength_set:"+saved[index]["set_uuid"]]
            assert b0["valid_n"] == b0["total_n"] == 1
    finally:
        repo.close()


@pytest.mark.parametrize("change,expected_reason", [
    ("late", "body_mass_record_unavailable_or_unverified"),
    ("future", "body_mass_record_unavailable_or_unverified"),
    ("bad_unit", "body_mass_record_unavailable_or_unverified"),
])
def test_requested_mass_cannot_bypass_cutoff_revision_or_unit_validation(tmp_path, change, expected_reason):
    repo = Repository(tmp_path / "excluded-mass.sqlite3")
    try:
        saved, mass = populated(repo, tmp_path)
        base = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", use_cache=False)
        chosen = selection(base, saved[1], mass[1])
        identifier = mass[1]["id"]
        if change == "late":
            repo.conn.execute("UPDATE source_revision SET available_at='2026-11-21T10:00:00Z' WHERE table_name='health_sample' AND record_id=?", (identifier,))
        else:
            if change == "future":
                repo.conn.execute("UPDATE health_sample SET end_utc='2026-11-21T08:00:00Z',start_utc='2026-11-21T08:00:00Z' WHERE id=?", (identifier,))
            else:
                repo.conn.execute("UPDATE health_sample SET raw_unit='unknown',normalized_unit='kg' WHERE id=?", (identifier,))
            repo.conn.execute("UPDATE source_revision SET available_at='2026-11-19T10:00:00Z' WHERE revision_id=(SELECT MAX(revision_id) FROM source_revision WHERE table_name='health_sample' AND record_id=?)", (identifier,))
        repo.conn.commit()
        output = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", use_cache=False,
                         context={"reference_selection": chosen, "strength_numerator": 99999, "body_mass_kg": 80})
        assert output["metrics"]["STR-30"]["value"] is None
        assert expected_reason in output["reference_selection"]["reason_codes"]
        assert chosen["body_mass_record_id"] not in {row["record_id"] for row in output["reference_options"]["body_mass"]}
    finally:
        repo.close()


def test_body_mass_day_is_compared_in_the_selected_analysis_timezone(tmp_path):
    repo = Repository(tmp_path / "local-day.sqlite3")
    try:
        saved, mass = populated(repo, tmp_path)
        repo.conn.execute("UPDATE health_sample SET end_utc='2026-11-17T23:30:00Z',start_utc='2026-11-17T23:30:00Z' WHERE id=?", (mass[0]["id"],))
        repo.conn.execute("UPDATE source_revision SET available_at='2026-11-18T08:30:00Z' WHERE table_name='health_sample'")
        repo.conn.commit()
        base = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", use_cache=False)
        chosen = selection(base, saved[1], mass[0])
        utc = analyze(repo, cutoff_time=CUTOFF, timezone_name="UTC", context={"reference_selection": chosen}, use_cache=False)
        local = analyze(repo, cutoff_time=CUTOFF, timezone_name="Asia/Shanghai", context={"reference_selection": chosen}, use_cache=False)
        assert utc["metrics"]["STR-30"]["value"] is None
        assert local["metrics"]["STR-30"]["value"]["ratio"] == pytest.approx(.75)
        assert local["reference_selection"]["body_mass"]["local_date"] == "2026-11-18"
    finally:
        repo.close()


def test_formula_research_numerator_remains_a_research_proxy_when_divided_by_mass():
    from healthzip.science import evaluate
    from healthzip.science.formulas import e1rm

    proxy = e1rm(60, 10, load_basis="external_total_kg", domain={"min_reps": 1, "max_reps": 10, "scope_id": "synthetic_formula_scope"})
    mass = {"id": "synthetic-scale", "canonical_type": "body_mass_kg", "raw_value": "80", "raw_unit": "kg",
            "event_end": "2026-11-18T08:00:00Z", "available_at": "2026-11-18T08:01:00Z", "source_name": "synthetic"}
    result = evaluate("STR-30", cutoff_time=CUTOFF, window_start="2026-11-01T00:00:00Z", window_end=CUTOFF,
        context={"strength_numerator": proxy["value"], "strength_numerator_unit": proxy["unit"],
                 "strength_numerator_identity": proxy["formula_id"], "numerator_evidence_status": proxy["evidence_status"],
                 "complete_load_known": True, "body_mass_observation": mass})
    assert result["value"]["ratio"] == pytest.approx(1)
    assert result["evidence_status"] == "research_only"
    assert result["value"]["numerator_identity"] == proxy["formula_id"]
    assert result["calibration_artifact_id"] is None
