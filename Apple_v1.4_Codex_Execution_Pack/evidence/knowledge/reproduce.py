"""Offline, synthetic-only review checks for commit 912aefc; no repository writes."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.sax.saxutils import escape

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.acquisition import Acquirer, parse_jats
from healthzip.knowledge.adjudication import score_frozen_annotations

REPO = Path('/workspace/scratch/a74a838d7f65/apple_review_912aefc')
OUT = Path('/workspace/scratch/a74a838d7f65/review912/knowledge')
QUESTION = '合成方案是否允许增加重复次数？'
TARGET = {'proposition': '合成方案允许增加重复次数',
          'scope': {'population': 'synthetic_adults', 'time_scale': 'study_protocol'}}


def approve(w, theory, relation='supports', version='0.1.0'):
    body = ('Synthetic protocol ' + ('permits' if relation == 'supports' else 'prohibits') + ' repetition progression.').encode()
    v = w.lib.record_version('S5', body, 'fulltext', {'url': 'https://example.test/synthetic'},
        {'title': 'Synthetic software test only'}, {'index_allowed': True, 'license_id': 'CC0'},
        'matched', [{'text': body.decode(), 'locator': {'synthetic_line': 1}}], 'review-synthetic')
    sid = v + ':s00000'
    text = '合成方案允许增加重复次数。' if relation == 'supports' else '合成方案不允许增加重复次数。'
    review = dict(reviewer='Independent offline review synthetic fixture', reviewer_kind='synthetic_fixture',
        rationale='Software regression only; no real science approval.',
        applicability={'scope': 'synthetic_only', 'required': {}},
        claims=[{'text': text, 'span_ids': [sid], 'support_rationale': 'Exact invented assertion.',
                 'answer_bindings': [{'question': QUESTION, 'target_claim': TARGET, 'relation': relation,
                                      'rationale': 'Synthetic target relation only.'}]}],
        evidence_links=[{'source_id': 'S5', 'source_version_id': v, 'span_ids': [sid]}])
    w.review_theory(theory, version, **review)
    return v, sid, review


def conflict_truncation():
    with TemporaryDirectory(dir=OUT) as t:
        w = KnowledgeWorkbench(t); w.seed()
        approve(w, 'TC-progression-load-repetition-options')
        approve(w, 'TC-measurement-load-comparability', 'refutes')
        result = {}
        for k in [1, 2]:
            a = w.query(QUESTION, 'progression', k=k)
            result['k' + str(k)] = {'status': a['status'], 'answer': a['answer'],
                'eligible_candidate_count': a['retrieval']['eligible_candidate_count'],
                'returned_theories': [c['theory_id'] for c in a['retrieval']['candidates']]}
        # The default budget also loses conflicts once a collection has > 6 cards.
        w.close()
    with TemporaryDirectory(dir=OUT) as t:
        w = KnowledgeWorkbench(t); w.seed()
        cards = [{'theory_id': 'SYNTHETIC-' + str(i), 'version': '0.1.0',
                  'title': QUESTION if i < 6 else 'Synthetic contrary evidence', 'domains': ['progression']}
                 for i in range(7)]
        w.lib.seed({'sources': []}, {'cards': cards})
        for i in range(7):
            approve(w, 'SYNTHETIC-' + str(i), 'supports' if i < 6 else 'refutes')
        for k in [6, 7]:
            a = w.query(QUESTION, 'progression', k=k)
            result['k' + str(k)] = {'status': a['status'], 'answer': a['answer'],
                'eligible_candidate_count': a['retrieval']['eligible_candidate_count'],
                'returned_theories': [c['theory_id'] for c in a['retrieval']['candidates']]}
        w.close()
    result['expected'] = 'A resource budget must not turn an existing same-target contradiction into evidence_supported; both budgets should flag conflict or an incomplete conflict screen.'
    return result


def nested_component_rights():
    raw = b'''<article><front><article-meta><title-group><article-title>Synthetic</article-title></title-group>
      <permissions><license>CC BY 4.0</license></permissions></article-meta></front>
      <body><p id="allowed-context">Allowed article context.
        <fig id="restricted-figure"><caption><p id="restricted-caption">RESTRICTED_FIGURE_MARKER</p></caption>
          <permissions><copyright-statement>All rights reserved. Permission required.</copyright-statement></permissions>
        </fig>Allowed article tail.</p></body></article>'''
    metadata, spans, rights = parse_jats(raw)
    with TemporaryDirectory(dir=OUT) as t:
        w = KnowledgeWorkbench(t); w.seed()
        v = w.lib.record_version('S5', raw, 'fulltext', {}, metadata, rights, 'matched', spans, 'jats-scoped-1.4.0')
        result = [{'xpath': s['locator']['xpath'], 'text': s['text'],
                   'owner_scope': s['rights']['scope_id'], 'index_allowed': s['rights']['index_allowed'],
                   'eligible': w.lib.eligible(w.lib.span(f'{v}:s{i:05d}'))}
                  for i, s in enumerate(spans)]
        w.close()
    return {'spans': result,
            'expected': 'RESTRICTED_FIGURE_MARKER must never appear in any eligible span, even when an enclosing paragraph is article-licensed.'}


def repeated_correction():
    with TemporaryDirectory(dir=OUT) as t:
        w = KnowledgeWorkbench(t); w.seed()
        v, sid, _ = approve(w, 'TC-progression-load-repetition-options')
        source = w.lib.source('S5')['manifest']
        raw = f'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>{source['pmid']}</PMID>
          <Article><ArticleTitle>{escape(source['title'])}</ArticleTitle>
          <Journal><JournalIssue><PubDate><Year>{source['year']}</Year></PubDate></JournalIssue></Journal></Article>
          <CommentsCorrectionsList><CommentsCorrections RefType="ErratumIn"><RefSource>Same synthetic correction</RefSource>
          <PMID>999999</PMID></CommentsCorrections></CommentsCorrectionsList></MedlineCitation>
          <PubmedData><ArticleIdList><ArticleId IdType="doi">{source['doi']}</ArticleId></ArticleIdList></PubmedData>
          </PubmedArticle></PubmedArticleSet>'''.encode()
        acquirer = Acquirer(w.lib)
        acquirer.request = lambda *args, **kwargs: (raw, {'url': 'https://example.test/same-synthetic-metadata', 'offline': True})
        first = acquirer.pubmed(source)
        w.review_source_state('S5', reviewer='Synthetic reviewer', rationale='Exact version reviewed for this exact synthetic correction', source_version_ids=[v])
        w.revise_theory('TC-progression-load-repetition-options', '0.1.0', '0.2.0', reviewer='Synthetic reviewer', rationale='Re-reviewed following this correction')
        approve(w, 'TC-progression-load-repetition-options', version='0.2.0')
        before = {'scientific_epoch': w.lib.source('S5')['scientific_epoch'], 'eligible': w.lib.eligible(w.lib.span(sid)),
                  'answer_status': w.query(QUESTION, 'progression')['status']}
        again = acquirer.pubmed(source)
        after = {'scientific_epoch': w.lib.source('S5')['scientific_epoch'], 'eligible': w.lib.eligible(w.lib.span(sid)),
                 'answer_status': w.query(QUESTION, 'progression')['status']}
        w.close()
    return {'same_metadata_version_id': first['version_id'] == again['version_id'],
            'before_identical_refetch': before, 'after_identical_refetch': after,
            'expected': 'Re-fetching byte-identical unchanged correction metadata must preserve the notice epoch and its exact-version clearance; a new or changed correction should invalidate it.'}


def status_recheck():
    upgrade = json.loads((REPO / 'artifacts/review/theory_scope_upgrade.json').read_text())
    reparse = json.loads((REPO / 'artifacts/review/source_scope_reparse.json').read_text())
    frozen = json.loads((REPO / 'artifacts/review/rag_semantics_frozen.json').read_text())
    annotations = json.loads((REPO / 'artifacts/review/rag_semantics_independent_ai_annotations.json').read_text())
    scored = score_frozen_annotations(frozen, annotations)
    return {'reparse_at': reparse['run_at'], 'reparse_theories': reparse['status_after']['theory_states'],
            'upgrade_at': upgrade['run_at'], 'current_theories': upgrade['status_after']['theory_states'],
            'current_fulltext_source_count': upgrade['status_after']['fulltext_source_count'],
            'reparse_distinct_sources': len({r['source_id'] for r in reparse['results']}),
            'reparse_version_count': len(reparse['results']),
            'annotation_recomputed_counts': scored['counts'], 'annotation_release_gate': scored['release_gate'],
            'limit': 'Checked committed artifacts, not an absent developer-local live DB. Counts of source versions/spans do not certify scientific suitability.'}


def original_regressions():
    out = {}
    with TemporaryDirectory(dir=OUT) as t:
        w = KnowledgeWorkbench(t); w.seed()
        _, _, request = approve(w, 'TC-progression-load-repetition-options')
        old_release = w.release('synthetic-original')
        w.review_theory('TC-progression-load-repetition-options', '0.1.0',
            **{**request, 'decision': 'needs_review', 'rationale': 'Synthetic revocation'})
        out['R05_revocation_current'] = w.query(QUESTION, 'progression')['status']
        out['R05_revocation_frozen_release'] = w.query(QUESTION, 'progression', release_id='synthetic-original')['status']
        out['R05_original_review_preserved'] = w.lib.released_theories('synthetic-original')[0]['review_json'] == old_release['theories'][0]['review_json']
        w.close()
    with TemporaryDirectory(dir=OUT) as t:
        w = KnowledgeWorkbench(t); w.seed()
        approve(w, 'TC-progression-load-repetition-options')
        w.revise_theory('TC-progression-load-repetition-options', '0.1.0', '0.2.0', reviewer='synthetic', rationale='Replacement test')
        v, sid, _ = approve(w, 'TC-progression-load-repetition-options', version='0.2.0')
        out['R05_effective_replacement_versions'] = [c['theory_version'] for c in w.query(QUESTION, 'progression')['retrieval']['candidates']]
        unrelated = w.query('合成方案增加重复次数能否证明个人寿命增长？', 'progression')
        out['RAG_unrelated_question'] = {'status': unrelated['status'], 'claims': len(unrelated['claims']), 'citations': len(unrelated['citations']), 'related_materials': len(unrelated['related_materials'])}
        w.lib.update_state('S5', 'corrected_pending_review', 'Synthetic correction')
        for material in ['metadata', 'abstract', 'fulltext']:
            w.lib.record_version('S5', material.encode(), material, {}, {}, {'index_allowed': True}, 'matched')
        out['R15_fetch_after_correction'] = {'scientific_state': w.lib.source('S5')['scientific_state'], 'eligible': w.lib.eligible(w.lib.span(sid))}
        w.close()
    raw = (REPO / 'tests/fixtures/synthetic_scoped_permissions.xml').read_bytes()
    _, spans, rights = parse_jats(raw)
    out['R06_original_component_fixture'] = {'article_index_allowed': rights['index_allowed'],
        'partially_indexable': rights['partially_indexable'],
        'by_native_id': {s['locator']['native_id']: s['rights']['index_allowed'] for s in spans if s['locator']['native_id']}}
    assert out['R05_revocation_current'] == out['R05_revocation_frozen_release'] == 'insufficient_evidence'
    assert out['R05_original_review_preserved'] and out['R05_effective_replacement_versions'] == ['0.2.0']
    assert out['RAG_unrelated_question']['status'] == 'related_material_only' and not out['RAG_unrelated_question']['citations']
    assert out['R15_fetch_after_correction']['eligible'] == (False, 'corrected_pending_review')
    assert out['R06_original_component_fixture']['article_index_allowed'] is False
    return out


if __name__ == '__main__':
    output = {'commit': '912aefc93b9bd9c1cebf297a10728c69c827e266',
              'scope': 'Offline synthetic software checks; no real data or scientific approval.',
              'remaining_K01': conflict_truncation(), 'remaining_K02': nested_component_rights(),
              'remaining_K03': repeated_correction(), 'report_consistency': status_recheck(),
              'original_regressions': original_regressions()}
    (OUT / 'results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output, ensure_ascii=False, indent=2))
