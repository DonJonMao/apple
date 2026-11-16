"""Synthetic structural fixtures verify preservation, coverage and authority boundaries."""
import json

import pytest
from lxml import etree

from healthzip.knowledge import domains, metric_retrieval, table_projection, vector_index
from healthzip.knowledge.model_services import EmbeddingProvider, ServiceConfig
from healthzip.knowledge.store import digest, dumps
from healthzip.science import evaluate

REVIEW = {"reviewer": "Synthetic fixture", "reviewer_kind": "synthetic_fixture",
    "reviewed_at": "2026-11-17", "rationale": "Software boundaries only",
    "content_checked": True, "application_checked": True}
CONTEXT = {"population": "adults", "measurement_protocol": "synthetic_protocol"}


class Embed(EmbeddingProvider):
    def __init__(self):
        super().__init__(ServiceConfig('https://example.invalid/embeddings', 'fixture', model_version='1'))
        self.calls = []

    def post(self, payload):
        self.calls.extend(payload['input'])
        return {"model": "fixture", "data": [{"index": i, "embedding":
            [1., 0., 0.] if 'unique final row target' in text or text.startswith('Instruct:') else [0., 1., 0.]}
            for i, text in enumerate(payload['input'])]}


def xml_text(raw):
    return ' '.join(' '.join(etree.fromstring(raw.encode()).itertext()).split())


def original(raw, sid='fixture:span'):
    text = xml_text(raw)
    return {"span_id": sid, "kind": "table", "text": text, "text_hash": digest(text.encode()),
        "locator_json": dumps({"xpath": "/article/body/table-wrap[1]", "native_id": "synthetic-table"}),
        "structured_json": dumps({"raw_xml": raw})}


def long_table(*, revised=False):
    rows = []
    for i in range(24):
        text = ('unique final row target' if i == 23 else f'synthetic study {i}')
        if revised and i == 10:
            text += ' explicit revision'
        rows.append(f'<tr><th scope="row">{text}</th><td>{"public synthetic measurements " * 8}</td></tr>')
    return ('<table-wrap><label>Table X</label><caption><p>Synthetic measurement reliability</p></caption>'
        '<table><thead><tr><th>Study</th><th>Results</th></tr></thead><tbody>' + ''.join(rows)
        + '</tbody></table><table-wrap-foot><fn id="note"><p>Important synthetic limitation.</p></fn>'
        '</table-wrap-foot></table-wrap>')


def add(kb, *, raw=None, bind=False):
    raw = raw or long_table()
    if not kb.lib.sources.execute("SELECT 1 FROM source WHERE source_id='table-fixture'").fetchone():
        kb.lib.seed({"sources": [{"source_id": "table-fixture", "title": "Public synthetic table",
            "canonical_url": "https://example.invalid/table", "corpus_roles": ["research"]}]}, {"cards": []})
    span = original(raw)
    vid = kb.lib.record_version('table-fixture', raw.encode(), 'fulltext', {}, {},
        {"index_allowed": True, "license_id": "CC0"}, 'matched',
        [{"kind": "table", "text": span['text'], "locator": json.loads(span['locator_json']),
          "structured": json.loads(span['structured_json'])}], 'synthetic-table-v1')
    sid = vid + ':s00000'
    vector_index.register_spans(kb, vid, ['strength'], assignment_status='content_checked')
    if bind:
        kb.review_claim({"claim_id": "table-claim", "version": "1", "statement": "Synthetic reliability only.",
            "scope": {"population": "adults"}, "conditions": [], "limitations": ["Synthetic only"],
            "evidence_links": [{"source_id": "table-fixture", "source_version_id": vid, "span_ids": [sid]}]}, REVIEW)
        domains.link(kb, origin={"type": "claim", "id": "table-claim", "version": "1"}, relation="defines",
            target={"type": "metric", "id": "STR-12", "version": "metric-domains-1.5.0"}, span_ids=[sid],
            applicability={"population": "adults"}, actor="Synthetic", rationale="Synthetic contract only",
            evidence_types=domains.configuration()['profiles']['STR-12']['required_evidence_types'], review=REVIEW)
    return sid


def retrieve(kb, embed, release=None):
    result = evaluate('STR-12', [], cutoff_time='2026-11-15T00:00:00+00:00',
        window_start='2026-11-01T00:00:00+00:00', window_end='2026-11-15T00:00:00+00:00')
    return kb.retrieve_for_metric('STR-12', 'strength', result,
        {**CONTEXT, "notes": "PRIVATE NOTE NEVER SENT"}, release, mode='dense', services=(embed, None))


def test_merged_cells_multiple_tables_and_context_have_exact_scoped_locators():
    raw = ('<table-wrap xmlns="urn:synthetic"><caption><p>Exact caption</p></caption><table>'
        '<thead><tr><th>First column</th><th colspan="2">Result columns</th></tr></thead><tbody>'
        '<tr><th rowspan="2" scope="rowgroup">Merged group</th><td colspan="2">A</td></tr>'
        '<tr><td>B</td><td>C</td></tr><tr><th colspan="3">Section heading</th></tr>'
        '<tr><td>D</td><td>E</td><td>F</td></tr></tbody></table><table>'
        '<thead><tr><th colspan="3">Other section only</th></tr></thead>'
        '<tbody><tr><td>G</td><td>H</td><td>I</td></tr></tbody></table>'
        '<table-wrap-foot><fn id="f"><p>Exact footnote</p></fn></table-wrap-foot></table-wrap>')
    span = original(raw)
    projection = table_projection.project(span)
    children = projection['children']
    assert [c['locator']['body_rows'] for c in children] == [[0, 2], [2, 3], [3, 4], [0, 1]]
    assert [c['column'] for c in children[0]['locator']['cells']] == [0, 1, 1, 2]
    assert children[0]['locator']['cells'][0]['attributes'] == {'rowspan': '2', 'scope': 'rowgroup'}
    assert children[2]['locator']['preceding_structural_context_rows'] == [2]
    assert 'Section heading' in children[2]['text']
    assert children[0]['locator']['table_xpath'] != children[-1]['locator']['table_xpath']
    assert 'Header context of table ./*[2]' in children[-1]['text']
    assert 'Header context of table ./*[3]' in children[-1]['text']
    assert all('Exact caption' in c['text'] and 'Exact footnote' in c['text'] for c in children)
    root = etree.fromstring(raw.encode())
    for child in children:
        assert root.xpath(child['locator']['table_xpath'])[0].tag.endswith('table')
        for cell in child['locator']['cells']:
            assert root.xpath(cell['structured_subtree_xpath'])
    assert span == original(raw)


@pytest.mark.parametrize('body,reason', [
    ('<tr><td rowspan="0">A</td></tr>', 'invalid_cell_extent'),
    ('<tr><td rowspan="2">A</td></tr>', 'cell_outside_row_group'),
    ('<tr><td>A</td><td rowspan="2">B</td></tr><tr><td colspan="2">C</td></tr>', 'overlapping_cells'),
    ('<tr><td><table><tbody><tr><td>A</td></tr></tbody></table></td></tr>', 'flat_sibling_tables'),
])
def test_invalid_or_ambiguous_structure_is_not_silently_repaired(body, reason):
    raw = '<table-wrap><table><tbody>' + body + '</tbody></table></table-wrap>'
    with pytest.raises(ValueError, match=reason):
        table_projection.project(original(raw))


def test_missing_headers_stay_missing_and_snapshot_mismatch_fails():
    raw = '<table-wrap><table><tbody><tr><td>Observed</td></tr></tbody></table></table-wrap>'
    span = original(raw)
    assert 'Header context of table' not in table_projection.project(span)['children'][0]['text']
    span['text'] += ' fabricated text'
    with pytest.raises(ValueError, match='original_snapshot_mismatch'):
        table_projection.project(span)
    span = original(raw)
    structured = '<!DOCTYPE table-wrap [<!ENTITY bad SYSTEM "file:///etc/passwd">]>' + raw
    span['structured_json'] = dumps({'raw_xml': structured})
    with pytest.raises(ValueError, match='original_snapshot_mismatch'):
        table_projection.project(span)


def test_explicit_headers_references_preserve_outside_rows_and_refuse_missing_targets():
    raw = ('<table-wrap><table><tbody><tr><th id="measured">Measured quantity and units</th><td>Context</td></tr>'
        '<tr><td headers="measured">Reported value</td><td>Observation</td></tr></tbody></table></table-wrap>')
    children = table_projection.project(original(raw))['children']
    assert 'Explicit headers-reference context of table' in children[1]['text']
    assert 'Measured quantity and units' in children[1]['text']
    invalid = raw.replace('headers="measured"', 'headers="missing"')
    with pytest.raises(ValueError, match='unresolved_headers_reference'):
        table_projection.project(original(invalid))


def test_indexing_preserves_parent_reuses_children_and_only_updates_changed_inputs(kb):
    sid, embed = add(kb), Embed()
    before = kb.lib.span(sid)
    first = vector_index.build_vectors(kb, embed)
    assert first['generated'] == 24 and not first['failures']
    assert first['structural_projections'][0]['complete']
    assert before == kb.lib.span(sid)
    assert all(before['text'] != text for text in embed.calls)
    second = vector_index.build_vectors(kb, embed)
    assert second['generated'] == 0 and second['structural_projections'][0]['reused_child_vectors'] == 24
    revised = add(kb, raw=long_table(revised=True))
    third = vector_index.build_vectors(kb, embed)
    assert third['generated'] == 1
    assert third['structural_projections'][1]['reused_child_vectors'] in {23, 24}
    assert kb.lib.span(sid) == before and revised != sid
    assert kb.lib.sources.execute('SELECT COUNT(*) FROM source').fetchone()[0] == 1
    assert kb.lib.sources.execute('SELECT COUNT(*) FROM span').fetchone()[0] == 2
    assert kb.lib.theories.execute('SELECT COUNT(*) FROM source_claim').fetchone()[0] == 0
    manifest = kb.lib.sources.execute('SELECT manifest_json FROM retrieval_projection_set LIMIT 1').fetchone()[0]
    assert 'public synthetic measurements' not in manifest  # Metadata references, no second source text.


def test_dense_hit_returns_full_parent_and_winning_row_without_granting_claim_authority(kb, monkeypatch):
    sid, embed = add(kb), Embed()
    vector_index.build_vectors(kb, embed)
    count = len(embed.calls)

    def forbidden(*args):
        pytest.fail('Query retrieval must not rebuild document projections')

    monkeypatch.setattr(table_projection, 'project', forbidden)
    answer = retrieve(kb, embed)
    evidence = answer['evidence_spans'][0]
    assert evidence['span_id'] == sid and evidence['content'] == kb.lib.span(sid)['text']
    assert evidence['dense_projection']['winning_child']['locator']['body_rows'] == [23, 24]
    assert evidence['dense_rank'] == 1 and not answer['retrieval_audit']['retrieval_degraded']
    assert len(embed.calls) == count + 1 and 'PRIVATE NOTE NEVER SENT' not in str(embed.calls)
    assert answer['status'] == 'insufficient_evidence' and not answer['capability_permissions']['candidate']
    assert not answer['capability_permissions']['source_explanation']
    audit = json.loads(kb.lib.sources.execute('SELECT payload_json FROM metric_retrieval_audit').fetchone()[0])
    assert audit['dense_structural_projections'][0]['winning_child']['locator']['body_rows'] == [23, 24]
    assert 'public synthetic measurements' not in dumps(audit)


def test_partial_projection_never_scores_a_subset_and_is_incrementally_resumable(kb):
    add(kb)
    embed = Embed()
    report = vector_index.build_vectors(kb, embed, max_documents=1)
    assert report['generated'] == 1 and not report['structural_projections'][0]['complete']
    answer = retrieve(kb, embed)
    info = answer['retrieval_audit']['dense_structural_projections'][0]
    assert info['available_child_vectors'] == 1 and not info['complete'] and 'winning_child' not in info
    assert answer['retrieval_audit']['dense_candidates'] == 0
    assert 'dense_index_incomplete:1' in answer['retrieval_audit']['degradation_reasons']
    report = vector_index.build_vectors(kb, embed)
    assert report['generated'] == 23 and report['structural_projections'][0]['reused_child_vectors'] == 1
    assert not retrieve(kb, embed)['retrieval_audit']['retrieval_degraded']


def test_old_frozen_release_never_acquires_new_children_but_new_release_pins_them(kb):
    sid, embed = add(kb), Embed()
    metric_retrieval.freeze_index(kb, 'before')
    frozen = kb.lib.sources.execute("SELECT manifest_json FROM index_release WHERE release_id='before'").fetchone()[0]
    vector_index.build_vectors(kb, embed)
    old = retrieve(kb, embed, 'before')
    assert old['retrieval_audit']['dense_candidates'] == 0
    assert not old['retrieval_audit']['dense_structural_projections']
    assert kb.lib.sources.execute("SELECT manifest_json FROM index_release WHERE release_id='before'").fetchone()[0] == frozen
    metric_retrieval.freeze_index(kb, 'after')
    current = retrieve(kb, embed, 'after')
    assert current['evidence_spans'][0]['span_id'] == sid
    assert current['retrieval_audit']['dense_candidates'] == 1
    manifest = json.loads(kb.lib.sources.execute("SELECT manifest_json FROM index_release WHERE release_id='after'").fetchone()[0])
    assert manifest['projection_set_ids'][sid] == current['evidence_spans'][0]['dense_projection']['projection_set_id']


@pytest.mark.parametrize('action', ['withdrawn', 'rights', 'claim'])
def test_cached_children_cannot_bypass_current_source_rights_or_claim_revocation(kb, action):
    sid, embed = add(kb, bind=True), Embed()
    vector_index.build_vectors(kb, embed)
    metric_retrieval.freeze_index(kb, 'frozen')
    assert retrieve(kb, embed, 'frozen')['status'] == 'evidence_context_supported'
    if action == 'withdrawn':
        kb.lib.update_state('table-fixture', action, 'Synthetic withdrawal')
    elif action == 'rights':
        with kb.lib.sources:
            kb.lib.sources.execute('UPDATE span SET scope_rights_json=? WHERE span_id=?',
                (dumps({'index_allowed': False}), sid))
    else:
        kb.core_state('claim', 'table-claim', '1', 'revoked', actor='Synthetic', rationale='Synthetic')
    answer = retrieve(kb, embed, 'frozen')
    assert not answer['evidence_spans'] and not answer['capability_permissions']['source_explanation']
    assert kb.lib.sources.execute('SELECT COUNT(*) FROM retrieval_vector WHERE purpose="document"').fetchone()[0] == 24


def test_manifest_tampering_degrades_and_changed_structure_cannot_reuse_mapping(kb):
    sid, embed = add(kb), Embed()
    vector_index.build_vectors(kb, embed)
    with kb.lib.sources:
        kb.lib.sources.execute("UPDATE retrieval_projection_set SET manifest_json='{}'")
    answer = retrieve(kb, embed)
    assert answer['retrieval_audit']['dense_candidates'] == 0
    assert 'table_projection_manifest_integrity_invalid' in answer['retrieval_audit']['degradation_reasons']
    with kb.lib.sources:
        kb.lib.sources.execute('UPDATE span SET structured_json=? WHERE span_id=?', (dumps({'raw_xml': '<changed/>'}), sid))
    answer = retrieve(kb, embed)
    assert answer['retrieval_audit']['dense_candidates'] == 0
    assert 'dense_index_incomplete:1' in answer['retrieval_audit']['degradation_reasons']
