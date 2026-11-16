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


def scoped_inputs(kb, tmp_path):
    namespace = runpy.run_path(str(Path(__file__).parents[2] / 'tools/v15_run_retrieval_benchmark.py'))
    path = tmp_path / 'scoped.json'
    path.write_text(json.dumps({'schema': 'metric-retrieval-gold-1.5.0', 'created_at': '2026-11-17',
        'annotator': 'Synthetic software test', 'synthetic_context_only': True, 'cases': [{
            'case_id': 'scoped', 'metric_id': 'STR-12', 'synthetic_context': True,
            'context': {'population': 'adults', 'measurement_protocol': 'explicit_synthetic_protocol'},
            'required_domains': ['strength'],
            'gold_span_ids': [], 'expected_abstention': True}]}))
    freeze = {'gold_sha256': digest(path.read_bytes()),
        'production_profiles_sha256': digest(dumps(domains.configuration()).encode()),
        'query_forms_sha256': query_forms.identity(),
        'candidate_scopes': ['all', 'reviewed_metric'],
        'candidate_scope_version': metric_retrieval.CANDIDATE_SCOPE_VERSION}
    freeze_path = tmp_path / 'scoped-freeze.json'
    freeze_path.write_text(json.dumps(freeze))
    config = tmp_path / 'services.json'
    config.write_text('{"public_evidence_network_consent": false}')
    metric_retrieval.freeze_index(kb, 'scoped-release')
    return namespace, path, freeze, freeze_path, config


@pytest.mark.parametrize(('policy', 'scope', 'reason'), [
    ({'candidate_scopes': ['all']}, 'reviewed_metric', 'gold_freeze_must_pin_selected_candidate_scope'),
    ({'candidate_scopes': ['reviewed_metric']}, 'all', 'gold_freeze_must_pin_selected_candidate_scope'),
    ({'candidate_scope_version': 'changed'}, 'reviewed_metric', 'gold_freeze_must_pin_candidate_scope_version'),
    ({'candidate_scopes': ['all', 'all']}, 'all', 'invalid_frozen_candidate_scopes'),
    ({'candidate_scopes': ['all', {}]}, 'all', 'invalid_frozen_candidate_scopes'),
    ({}, 'private free text', 'unknown_metric_candidate_scope'),
])
def test_scope_policy_is_checked_before_loading_models(kb, tmp_path, monkeypatch, policy, scope, reason):
    ns, path, freeze, freeze_path, config = scoped_inputs(kb, tmp_path)
    freeze.update(policy)
    freeze_path.write_text(json.dumps(freeze))
    monkeypatch.setitem(ns['run'].__globals__, 'load_services', lambda *a, **kw: pytest.fail('invalid freeze'))
    with pytest.raises(ValueError, match=reason):
        ns['run'](kb.root, path, config, 'scoped-release', tmp_path / 'raw', tmp_path / 'public',
                  candidate_scope=scope)
    assert not (tmp_path / 'public').exists()


@pytest.mark.parametrize('release', [None, 'old-release'])
def test_scoped_evaluation_requires_release_policy_even_before_any_candidates(kb, tmp_path, monkeypatch, release):
    ns, path, _, _, config = scoped_inputs(kb, tmp_path)
    manifest = json.loads(kb.lib.sources.execute(
        "SELECT manifest_json FROM index_release WHERE release_id='scoped-release'").fetchone()[0])
    manifest.pop('candidate_scope_version')
    raw = dumps(manifest)
    with kb.lib.sources:
        kb.lib.sources.execute('INSERT INTO index_release VALUES(?,?,?,?)',
            ('old-release', raw, digest(raw.encode()), '2026-11-17'))
    monkeypatch.setitem(ns['run'].__globals__, 'load_services', lambda *a, **kw: pytest.fail('unpinned release'))
    with pytest.raises(ValueError, match='scoped_evaluation_requires_pinned_index_release'):
        ns['run'](kb.root, path, config, release, tmp_path / 'raw', tmp_path / 'public',
                  candidate_scope='reviewed_metric')


def test_paired_runner_applies_same_scope_to_every_variant_and_pins_resume(kb, tmp_path, monkeypatch):
    from test_v15_ranked_coverage import add_group
    from test_v15_retrieval import Embed, Rank, add

    from healthzip.knowledge import KnowledgeWorkbench, vector_index

    _, bound = add_group(kb)
    _, background = add(kb, 'unbound-background', bind=False)
    embed, rank = Embed(), Rank()
    vector_index.build_vectors(kb, embed)
    ns, path, _, _, config = scoped_inputs(kb, tmp_path)
    monkeypatch.setitem(ns['run'].__globals__, 'KnowledgeWorkbench',
                        lambda root: KnowledgeWorkbench(root, environment_kind='synthetic_test'))
    monkeypatch.setitem(ns['run'].__globals__, 'load_services', lambda *a, **kw: (embed, rank))
    report = ns['run_query_forms'](kb.root, path, config, 'scoped-release', tmp_path / 'raw', tmp_path / 'public',
                                  candidate_scope='reviewed_metric')
    assert report['candidate_scope'] == 'reviewed_metric'
    assert report['unique_knowledge_case_count'] == 1
    for form in query_forms.configuration()['forms']:
        for variant in ns['VARIANTS']:
            result = json.loads((tmp_path / f'raw/{form}/{variant}-scoped.json').read_text())['result']
            assert result['retrieval_audit']['candidate_scope'] == 'reviewed_metric'
            assert result['retrieval_audit']['eligible_candidate_count'] == len(bound)
            assert background not in {s['span_id'] for s in result['evidence_spans']}
        published = json.loads((tmp_path / f'public/{form}/evaluation.json').read_text())
        private = json.loads((tmp_path / f'raw/{form}/run-identity.json').read_text())
        identity = published['retrieval_config']['identity']
        assert identity['private_run_identity_sha256'] == digest(dumps(private).encode())
        assert 'endpoint' in private['models'][0]
        assert 'endpoint' not in json.dumps(published)
    ns['run'](kb.root, path, config, 'scoped-release', tmp_path / 'raw/en', tmp_path / 'public/en',
              query_form='en', candidate_scope='reviewed_metric', _resume_completed=True)
    with pytest.raises(ValueError, match='resume_requires_same_frozen_run_identity'):
        ns['run'](kb.root, path, config, 'scoped-release', tmp_path / 'raw/en', tmp_path / 'other-public',
                  query_form='en', candidate_scope='all', _resume_completed=True)


def test_public_identity_omits_nested_operational_secrets_and_keeps_private_identity_distinct():
    ns = runpy.run_path(str(Path(__file__).parents[2] / 'tools/v15_run_retrieval_benchmark.py'))
    identity = {'models': [{'endpoint': 'https://private.invalid/model', 'model_id': 'synthetic',
                            'tokenizer_endpoint': 'https://private.invalid/tokenize'}],
                'annotation_provenance': {'API_KEY': 'SYNTHETIC-SECRET',
                    'reviewers': [{'headers': {'Authorization': 'SYNTHETIC-HEADER'}, 'kind': 'AI'}]}}
    public = ns['public_run_identity'](identity)
    assert 'private.invalid' not in json.dumps(public) and 'SYNTHETIC-SECRET' not in json.dumps(public)
    assert 'SYNTHETIC-HEADER' not in json.dumps(public)
    assert public['annotation_provenance']['reviewers'] == [{'kind': 'AI'}]
    assert identity['models'][0]['endpoint'] == 'https://private.invalid/model'
    changed = json.loads(json.dumps(identity))
    changed['models'][0]['endpoint'] = 'https://other.invalid/model'
    another = ns['public_run_identity'](changed)
    assert public['models'][0]['service_identity_sha256'] != another['models'][0]['service_identity_sha256']
