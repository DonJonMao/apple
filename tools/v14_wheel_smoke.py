"""Run from outside the checkout with a core-only installed wheel."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

import healthzip
from healthzip.advice import profile, save_profile
from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.knowledge import KnowledgeWorkbench
from healthzip.training.service import TrainingService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--wheel", required=True)
    args = parser.parse_args()
    assert "site-packages" in str(healthzip.__file__), healthzip.__file__
    assert version("health-zip-workbench") == "1.4.0"
    for name in ("catalog.schema.json", "catalog_terms.py", "catalog_legacy_mapping.json", "catalog_name_drafts.json"):
        assert files("healthzip.training").joinpath(name).is_file(), name
    for name in ("core_sources.json", "core_rules.json", "method_equivalence.json", "hhs_goal_scope.json", "source_explanations_1_4_6.json",
                 "regression_covariance_1_4_7.json", "activity_safety_scope_1_4_8.json", "refined_explanations_1_4_9.json",
                 "detailed_explanations_1_4_10.json", "boundary_explanations_1_4_11.json", "completion_explanations_1_4_12.json",
                 "practical_source_explanations_1_4_14.json"):
        assert files("healthzip.knowledge").joinpath("data", name).is_file(), name
    with tempfile.TemporaryDirectory(prefix="healthzip-v14-wheel-synthetic-") as folder:
        repo = Repository(Path(folder) / "synthetic.sqlite3")
        assert repo.one("SELECT value FROM schema_meta WHERE key='schema_version'")[0] == "4"
        service = TrainingService(repo)
        count = len(service.search_exercises())
        assert count == 46  # A fresh core install has seeds; public sync is explicit.
        assert profile(repo)["revision"] is None
        save_profile(repo, {"age": 32})
        assert profile(repo)["fields"]["age"] == 32
        result = analyze(repo)
        assert len(result["metrics"]) == 77
        knowledge = KnowledgeWorkbench(Path(folder) / "knowledge")
        knowledge.seed()
        knowledge.seed_core()
        assert knowledge.status()["effective_approved_theory_count"] == 0
        knowledge.close()
        repo.close()
    result = {"version": "1.4.0", "fresh_schema": 4, "seed_exercises": count,
              "metric_count": 77, "environment": "isolated_wheel_core_only",
              "new_catalog_and_core_resources": "included", "advice_profile": "passed",
              "empty_knowledge_does_not_activate_rules": True, "data_kind": "synthetic_only",
              "wheel_sha256": hashlib.sha256(Path(args.wheel).read_bytes()).hexdigest()}
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
