"""Actual Repository and page paths consume explicit canonical observation extensions."""
import json
from contextlib import closing
from functools import partial

import pytest
from streamlit.testing.v1 import AppTest

from healthzip.analytics.v13 import analyze
from healthzip.db.repository import Repository
from healthzip.knowledge import KnowledgeWorkbench, domains, metric_retrieval, vector_index
from healthzip.science.observations import evaluate
from healthzip.ui import metric_evidence

BOUNDS = {'cutoff_time': '2026-11-17T00:00:00+00:00', 'window_start': '2026-11-01T00:00:00+00:00',
    'window_end': '2026-11-17T00:00:00+00:00'}
REVIEW = {'reviewer': 'Synthetic fixture', 'reviewer_kind': 'synthetic_fixture',
    'reviewed_at': '2026-11-17', 'rationale': 'Synthetic integration only',
    'content_checked': True, 'application_checked': True}


def insert_samples(repo):
    batch = repo.create_batch(file_sha256='synthetic-observations', file_name='synthetic', file_size=1, xml_member_path='synthetic.xml')
    for i, (raw_type, canonical, value, category) in enumerate([
        ('HKQuantityTypeIdentifierVO2Max', 'vo2_max_ml_kg_min', '42.125678', None),
        ('HKCategoryTypeIdentifierMenstrualFlow', 'menstrual_flow', None, 'UNINTERPRETED SOURCE CATEGORY')]):
        repo.insert_sample(batch, {'fingerprint': f'synthetic:{i}', 'raw_type': raw_type, 'canonical_type': canonical,
            'raw_value': value, 'raw_unit': 'mL/kg/min' if value else None, 'category_value': category,
            'start_utc': '2026-11-10T07:00:00+00:00', 'end_utc': '2026-11-10T08:00:00+00:00',
            'source_name': 'Synthetic source', 'device': 'SYNTHETIC PRIVATE DEVICE', 'source_version': '1',
            'metadata_json': '{}', 'quality_flags_json': '{}', 'created_at': '2026-11-10T09:00:00+00:00'})
    # Fixture visibility is explicit and independent of the wall clock running this test.
    repo.conn.execute("UPDATE source_revision SET available_at='2026-11-10T09:00:00+00:00' WHERE table_name='health_sample'")
    repo.conn.commit()


def seed_evidence(kb, mid):
    profile = domains.configuration(include_observations=True)['profiles'][mid]
    kb.lib.seed({'sources': [{'source_id': 'observation-fixture', 'canonical_url': 'https://example.invalid/observation',
        'title': 'Synthetic source', 'corpus_roles': ['research']}]}, {'cards': []})
    vid = kb.lib.record_version('observation-fixture', mid.encode(), 'fulltext', {}, {},
        {'index_allowed': True, 'license_id': 'CC0'}, 'matched',
        [{'text': profile['query'], 'locator': {'page': 1}}], 'synthetic')
    sid = vid + ':s00000'
    kb.review_claim({'claim_id': mid, 'version': '1', 'statement': 'Synthetic observation scope only.',
        'scope': {'population': 'adults'}, 'conditions': [], 'limitations': ['Synthetic only'],
        'evidence_links': [{'source_id': 'observation-fixture', 'source_version_id': vid, 'span_ids': [sid]}]}, REVIEW)
    vector_index.register_spans(kb, vid, profile['primary_domains'], assignment_status='content_checked')
    domains.link(kb, origin={'type': 'claim', 'id': mid, 'version': '1'}, relation='limits',
        target={'type': 'metric', 'id': mid, 'version': domains.profile_version(mid)}, span_ids=[sid],
        applicability={}, actor='Synthetic', rationale='Synthetic only',
        evidence_types=profile['required_evidence_types'], review=REVIEW)
    return sid


def test_real_source_ledger_feeds_observations_separately_and_revisions_invalidate_cache(tmp_path):
    with closing(Repository(tmp_path / 'synthetic.sqlite3')) as repo:
        insert_samples(repo)
        computed = analyze(repo, cutoff_time=BOUNDS['cutoff_time'], timezone_name='UTC')
        assert len(computed['metrics']) == 77 and len(computed['observations']) == 2
        vo2 = computed['observations']['OBS-VO2-REPORTED']
        assert vo2['value']['streams'][0]['observations'][0]['value'] == 42.125678
        assert vo2['source_record_ids'] == ['health_sample:1']
        cycle = computed['observations']['OBS-CYCLE-RECORDS']
        assert cycle['value']['streams'][0]['observations'][0]['recorded_category'] == 'UNINTERPRETED SOURCE CATEGORY'
        assert computed['observation_query_plan']['returned_records'] == 2
        repo.conn.execute("UPDATE health_sample SET record_status='deleted' WHERE id=1")
        repo.conn.execute("UPDATE source_revision SET available_at='2026-11-11T09:00:00+00:00' WHERE revision_id=(SELECT MAX(revision_id) FROM source_revision)")
        repo.conn.commit()
        current = analyze(repo, cutoff_time=BOUNDS['cutoff_time'], timezone_name='UTC')
        assert current['observations']['OBS-VO2-REPORTED']['value'] is None
        assert current['data_hash'] != computed['data_hash']


def test_extension_configuration_never_changes_original_profiles_or_frozen_base_hash(kb):
    original = domains.configuration()
    extended = domains.configuration(include_observations=True)
    assert len(original['profiles']) == 77 and len(extended['profiles']) == 79
    assert all(extended['profiles'][mid] == profile for mid, profile in original['profiles'].items())
    assert extended['observation_extensions']['metric_ids'] == ['OBS-CYCLE-RECORDS', 'OBS-VO2-REPORTED']
    metric_retrieval.freeze_index(kb, 'before-extension-bindings')
    before = kb.lib.sources.execute('SELECT manifest_json FROM index_release').fetchone()[0]
    assert 'observation_profile_sha256' not in json.loads(before)
    # Appending extension evidence cannot change the earlier frozen manifest.
    seed_evidence(kb, 'OBS-CYCLE-RECORDS')
    metric = evaluate('OBS-CYCLE-RECORDS', [], **BOUNDS)
    answer = kb.retrieve_for_metric('OBS-CYCLE-RECORDS', 'cycle', metric,
        {'population': 'adults', 'measurement_protocol': 'synthetic'}, 'before-extension-bindings', mode='lexical')
    assert answer['status'] == 'insufficient_evidence' and not answer['matched_claims']
    assert kb.lib.sources.execute("SELECT manifest_json FROM index_release WHERE release_id='before-extension-bindings'").fetchone()[0] == before


def test_new_frozen_release_refuses_changed_observation_profile(kb, monkeypatch):
    seed_evidence(kb, 'OBS-CYCLE-RECORDS')
    metric_retrieval.freeze_index(kb, 'with-extension')
    changed = domains.observation_configuration()
    changed['profiles']['OBS-CYCLE-RECORDS']['query'] = 'Changed fixed task'
    monkeypatch.setattr(domains, 'observation_configuration', lambda: changed)
    metric = evaluate('OBS-CYCLE-RECORDS', [], **BOUNDS)
    with pytest.raises(ValueError, match='frozen_observation_profile_configuration_changed'):
        kb.retrieve_for_metric('OBS-CYCLE-RECORDS', 'cycle', metric, {}, 'with-extension', mode='lexical')


@pytest.mark.parametrize('mid,task', [('OBS-VO2-REPORTED', 'cardiorespiratory'), ('OBS-CYCLE-RECORDS', 'cycle')])
def test_unified_service_requires_extension_binding_and_honors_revocation(kb, mid, task):
    metric = evaluate(mid, [], **BOUNDS)
    before = kb.explain_metric(mid, task, metric, {'population': 'adults', 'measurement_protocol': 'synthetic'})
    assert before['evidence_context']['status'] == 'insufficient_evidence'
    seed_evidence(kb, mid)
    metric_retrieval.freeze_index(kb, 'with-observations')
    manifest = json.loads(kb.lib.sources.execute("SELECT manifest_json FROM index_release").fetchone()[0])
    assert manifest['observation_profile_sha256']
    answer = kb.explain_metric(mid, task, metric, {'population': 'adults', 'measurement_protocol': 'synthetic'}, 'with-observations')
    assert answer['evidence_context']['status'] == 'evidence_context_supported'
    assert not answer['evidence_context']['capability_permissions']['candidate']
    kb.core_state('claim', mid, '1', 'revoked', actor='Synthetic', rationale='Synthetic')
    answer = kb.explain_metric(mid, task, metric, {'population': 'adults', 'measurement_protocol': 'synthetic'}, 'with-observations')
    assert answer['evidence_context']['status'] == 'insufficient_evidence'


@pytest.mark.parametrize('task', ['cardiorespiratory', 'cycle'])
def test_actual_analysis_page_reaches_new_entry_without_missing_metric_placeholder(kb, tmp_path, monkeypatch, task):
    path = tmp_path / 'page.sqlite3'
    with closing(Repository(path)) as repo:
        insert_samples(repo)
    from healthzip.ui import health_explanation
    monkeypatch.setattr(metric_evidence, 'render_metric_request',
        partial(health_explanation.render_metric_request, root=str(kb.root)))
    monkeypatch.setattr('healthzip.knowledge.KnowledgeWorkbench',
        lambda root: KnowledgeWorkbench(root, environment_kind='synthetic_test'))
    app = AppTest.from_string('from healthzip.db.repository import Repository\n'
        'from healthzip.analytics.v13 import analyze\nfrom healthzip.ui.analysis_page import render_analysis\n'
        f'repo=Repository({str(path)!r})\n'
        'render_analysis(repo, {"v13": analyze(repo, cutoff_time="2026-11-17T00:00:00+00:00", timezone_name="UTC")})\n'
        'repo.close()\n').run(timeout=30)
    app.selectbox(key='metric_evidence_function').select(task).run()
    assert not app.exception
    expected = 'OBS-CYCLE-RECORDS' if task == 'cycle' else 'OBS-VO2-REPORTED'
    assert app.selectbox(key='metric_evidence_metric').value == expected
    app.button(key='metric_evidence_run').click().run()
    assert not app.exception
    # The request runs on its own knowledge connections. Complete the worker,
    # then rerender the local explanation fragment; factual UI stayed usable.
    request = app.session_state['metric_evidence_job']
    response = health_explanation._JOBS[request['key']][1].result(timeout=10)
    assert response['items'][0]['evidence_context']['capability_permissions']['source_explanation'] is False
    app.run(timeout=30)
    assert not app.exception
    assert any('缺少通过审核且适用的完整依据' in str(item.value) for item in app.caption)
    assert not any('没有此功能对应' in str(item.value) for item in app.info)
