"""Exercise the real offline runner API without contacting any model service."""

import json
import runpy
from pathlib import Path

import pytest

from healthzip.knowledge import domains, metric_retrieval, query_forms
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
    # The offline comparison pins a real corpus identity even when every metric
    # skips RAG. An empty frozen release requires no documents or model calls.
    metric_retrieval.freeze_index(kb, 'no-evidence-needed')
    before = metric_retrieval.context_match
    with pytest.raises(ValueError, match='unknown_retrieval_release'):
        run(kb.root, path, config, 'unpublished', tmp_path / 'invalid-raw', tmp_path / 'invalid-public')
    assert not (tmp_path / 'invalid-public').exists()
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
    identity = json.loads((tmp_path / "raw/run-identity.json").read_text())
    assert identity["evaluation_purpose"] == "development_replay"
    assert "metric_retrieval.py" in identity["implementation_sha256"]
    assert {'data/query_forms_v15.json', 'data/observation_domains_v15.json'} <= set(identity['implementation_sha256'])
    monkeypatch.setitem(run.__globals__, "implementation_identity", lambda: {"metric_retrieval.py": "changed"})
    with pytest.raises(ValueError, match="resume_requires_same_frozen_run_identity"):
        run(kb.root, path, config, "no-evidence-needed", tmp_path / "raw", tmp_path / "another-public")
    assert not (tmp_path / "another-public").exists()


def test_paired_forms_keep_same_gold_and_count_variants_as_correlated_queries(kb, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('No evidence candidates means no network calls')

    monkeypatch.setattr(ModelClient, 'post', forbidden)
    namespace = runpy.run_path(str(Path(__file__).parents[2] / 'tools/v15_run_retrieval_benchmark.py'))
    cases = [{'case_id': mid, 'metric_id': mid, 'synthetic_context': True, 'context': {},
        'required_domains': [], 'gold_span_ids': [], 'expected_abstention': True}
        for mid in ['STR-01', 'OBS-VO2-REPORTED', 'OBS-CYCLE-RECORDS']]
    gold = {'schema': 'metric-retrieval-gold-1.5.0', 'created_at': '2026-11-17',
            'annotator': 'Synthetic software test', 'synthetic_context_only': True, 'cases': cases}
    path = tmp_path / 'paired.json'
    path.write_text(json.dumps(gold))
    freeze = {'gold_sha256': digest(path.read_bytes()),
              'production_profiles_sha256': digest(dumps(domains.configuration()).encode()),
              'observation_profiles_sha256': digest(dumps(domains.observation_configuration()).encode()),
              'query_forms_sha256': query_forms.identity()}
    (tmp_path / 'paired-freeze.json').write_text(json.dumps(freeze))
    config = tmp_path / 'services.json'
    config.write_text('{"public_evidence_network_consent": false}')
    report = namespace['run_query_forms'](kb.root, path, config, None, tmp_path / 'raw', tmp_path / 'public')
    assert report['unique_knowledge_case_count'] == 3
    assert report['query_instance_count_per_experiment'] == 9
    for experiment in report['experiments'].values():
        assert experiment['by_language']['zh']['case_count'] == 6
        assert experiment['by_language']['en']['case_count'] == 3
        for form in query_forms.configuration()['forms']:
            assert experiment['by_form'][form]['abstention_accuracy'] == {'value': 1., 'denominator': 3}
            assert experiment['by_form'][form]['evidence_recall_at_k']['denominator'] == 0
    # Observation cases really reach their registered engine, rather than the original 77-only engine.
    saved = json.loads((tmp_path / 'raw/en/E-OBS-VO2-REPORTED.json').read_text())
    assert saved['result']['metric_id'] == 'OBS-VO2-REPORTED'
    assert saved['result']['retrieval_audit']['query_form']['language'] == 'en'
    with pytest.raises(FileExistsError, match='immutable_query_forms_evaluation'):
        namespace['run_query_forms'](kb.root, path, config, None, tmp_path / 'raw', tmp_path / 'public')
    # A completed form may be resumed only when its report bytes and all inputs are unchanged.
    namespace['run'](kb.root, path, config, None, tmp_path / 'raw/en', tmp_path / 'public/en',
                     query_form='en', _resume_completed=True)
    with (tmp_path / 'public/en/evaluation.json').open('a') as stream:
        stream.write(' ')
    with pytest.raises(ValueError, match='completed_public_report_changed'):
        namespace['run'](kb.root, path, config, None, tmp_path / 'raw/en', tmp_path / 'public/en',
                         query_form='en', _resume_completed=True)
    freeze.pop('query_forms_sha256')
    (tmp_path / 'paired-freeze.json').write_text(json.dumps(freeze))
    with pytest.raises(ValueError, match='gold_freeze_must_pin_selected_query_forms'):
        namespace['run'](kb.root, path, config, None, tmp_path / 'different', tmp_path / 'different-public', query_form='en')
