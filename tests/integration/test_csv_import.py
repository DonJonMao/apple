from healthzip.db.repository import Repository
from healthzip.importers.csv_importers import import_nutrition_csv, import_strength_csv


def test_csv_import_deduplicates_and_preserves_partial_status(tmp_path):
    p = tmp_path / "nutrition.csv"
    p.write_text(
        "date,energy_kcal,protein_g,carbohydrates_g,fat_g,log_status,source,notes\n2026-11-01,2200,140,200,70,partial,manual,\n",
        encoding="utf-8",
    )
    repo = Repository(tmp_path / "db.sqlite3")
    assert import_nutrition_csv(p, repo)["inserted"] == 1
    assert import_nutrition_csv(p, repo)["inserted"] == 0
    row = repo.one("select log_status from nutrition_day")
    assert row["log_status"] == "partial"
    repo.close()


def test_strength_imports_units(tmp_path):
    p = tmp_path / "strength.csv"
    p.write_text(
        "date,exercise_name,equipment,weight,reps,weight_unit,warmup\n2026-11-01,Squat,barbell,220,5,lb,false\n",
        encoding="utf-8",
    )
    repo = Repository(tmp_path / "db.sqlite3")
    result = import_strength_csv(p, repo)
    assert result["inserted"] == 1
    assert round(repo.one("select weight_kg from strength_set")["weight_kg"], 2) == 99.79
    repo.close()


def test_repository_templates_are_accepted(tmp_path):
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    repo = Repository(tmp_path / "templates.sqlite3")
    strength = import_strength_csv(root / "templates/strength_sets_template.csv", repo)
    nutrition = import_nutrition_csv(root / "templates/nutrition_daily_template.csv", repo)
    from healthzip.importers.csv_importers import import_measurements_csv

    measurements = import_measurements_csv(root / "templates/body_measurements_template.csv", repo)
    assert strength["inserted"] == 2
    assert nutrition["inserted"] == 2
    assert measurements["inserted"] == 2
    repo.close()
