"""Exercise the real offline runner API without contacting any model service."""

import json
import runpy
from pathlib import Path

import pytest

from healthzip.knowledge import domains, metric_retrieval
from healthzip.knowledge.model_services import ModelClient
from healthzip.knowledge.store import digest, dumps


def test_runner_uses_explicit_config_and_keeps_ablations_out_of_application(kb, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A deterministic metric must not contact models, including during evaluation")

    monkeypatch.setattr(ModelClient, "post", forbidden)
    run = runpy.run_path(str(Path(__file__).parents[2] / "tools/v15_run_retrieval_benchmark.py"))["run"]
    case = {"case_id": "synthetic-count", "metric_id": "STR-01", "synthetic_context": True,
            "context": {}, "required_domains": [], "gold_span_ids": [], "required_claims": [],
            "expected_abstention": True}
    gold = {"schema": "metric-retrieval-gold-1.5.0", "created_at": "2026-11-17", "annotator": "Synthetic software test",
            "synthetic_context_only": True, "cases": [case]}
    path = tmp_path / "gold.json"
    path.write_text(json.dumps(gold))
    (tmp_path / "gold-freeze.json").write_text(json.dumps({"gold_sha256": digest(path.read_bytes()),
        "production_profiles_sha256": digest(dumps(domains.configuration()).encode())}))
    config = tmp_path / "services.json"
    config.write_text('{"public_evidence_network_consent": false}')
    before = metric_retrieval.context_match
    report = run(kb.root, path, config, "no-evidence-needed", tmp_path / "raw", tmp_path / "public")
    assert set(report["experiments"]) == {"A", "B", "C", "D", "E"}
    for experiment in report["experiments"].values():
        assert experiment["overall"]["evidence_recall_at_k"]["denominator"] == 0
        assert experiment["overall"]["abstention_accuracy"]["value"] == 1
    assert metric_retrieval.context_match is before
    published = (tmp_path / "public/evaluation.json").read_bytes()
    with pytest.raises(FileExistsError):
        run(kb.root, path, config, "no-evidence-needed", tmp_path / "raw", tmp_path / "public")
    assert (tmp_path / "public/evaluation.json").read_bytes() == published
    assert metric_retrieval.context_match is before
