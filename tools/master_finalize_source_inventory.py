"""Record acquired reference originals without granting indexing or scientific authority."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pdfplumber
from lxml import html

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.store import digest, now

BASE = Path('artifacts/master_redesign/knowledge')
LOCAL = Path('.local/master-knowledge/fetched')
FPP3_SECTIONS = {
    'graphics.html': ['time-plots', 'sec-acf', 'trend-and-seasonality-in-acf-plots'],
    'regression.html': ['acf-plot-of-residuals'],
    'dynamic-regression.html': ['lagged-predictors'],
    'practical.html': ['sec-long-short-ts', 'forecasting-very-short-time-series',
                       'sec-missing-outliers', 'missing-values'],
}


def run():
    report = json.loads((BASE / 'source-inventory.json').read_text())
    refs = report['references']
    retry = json.loads((BASE / 'official-fields-and-retries.json').read_text())
    extra = json.loads((BASE / 'specialist-followup.json').read_text())
    lawful = json.loads((BASE / 'lawful-alternative-routes.json').read_text())['sources']
    additions = {'M3': [retry['M3-publisher']], 'H1': [extra['H1-PMC']],
                 'U1': [retry['U1-author']], 'C2-6': [lawful['wrist-official']['attempts'][0]],
                 'C1-6': lawful['C1-6']['attempts'], 'C3-NOISE': [retry['C3-noise-formula']]}
    refs.append({'key': 'C3-BIA-CAMPA', 'source_id': 'MSTR-BIA-CAMPA-2021',
                 'urls': [extra['BIA-PMC']['url']], 'attempts': [extra['BIA-PMC'], extra['BIA-JATS']]})
    w = KnowledgeWorkbench('.local/knowledge')
    registered = []
    try:
        packet = json.loads(Path('tools/master_source_reviews.json').read_text())
        known_sources = {r['source_id'] for r in refs}
        for entry in [*packet['new_claims'], *packet['reviewed_existing_spans']]:
            sid = entry['source_id']
            if sid in known_sources:
                continue
            known_sources.add(sid)
            manifest = w.lib.source(sid)['manifest']
            url = entry.get('url') or manifest['canonical_url']
            refs.append({'key': 'SUPP-' + sid, 'source_id': sid, 'urls': [url], 'attempts': []})
        for ref in refs:
            sid = ref['source_id']
            attempts = [*ref.get('attempts', []), *additions.get(ref['key'], [])]
            versions = []
            for attempt in attempts:
                sha = attempt.get('sha256')
                if not sha:
                    continue
                raw = (LOCAL / sha).read_bytes()
                if digest(raw) != sha:
                    raise ValueError('source_bytes_changed')
                existing = w.lib.sources.execute('SELECT version_id,source_id,parser_version FROM version WHERE sha256=?', (sha,)).fetchall()
                if existing:
                    versions.extend({'version_id': row[0], 'canonical_source_id': row[1], 'reused': True} for row in existing)
                    # Preserve the original receipt while correcting the earlier
                    # mistaken chapter-entry classification of Quarto's inline chapters.
                    if ref['key'] != 'M5' or any(row[2] == 'master-reference-quarto-2' for row in existing):
                        continue
                material = 'reference_page'
                parser_version = 'master-reference-original-1'
                metadata = {'attachment_reference': ref['key'], 'url': attempt['url'],
                            'content_review': 'reference_receipt_only_not_scientific_claim'}
                if raw.startswith(b'%PDF-'):
                    doc = pdfplumber.open(io.BytesIO(raw))
                    metadata.update(page_count=len(doc.pages), pdf_metadata=doc.metadata)
                    title = doc.metadata.get('Title') or ref['key'] + ' source original'
                    material = 'preview' if ref['key'] == 'M6' else 'toc' if ref['key'] == 'M1' else 'fulltext'
                    doc.close()
                elif attempt['material'] == 'docc_received':
                    page = json.loads(raw)
                    title = page['metadata']['title']
                    material = 'official_definition'
                    metadata['symbol'] = page['identifier']['url']
                else:
                    page = html.fromstring(raw)
                    title = ' '.join(page.xpath('//title/text()')).strip() or ref['key'] + ' source original'
                    if ref['key'] in {'M4', 'H1', 'S1', 'S2', 'S3', 'S4', 'C1-9'}:
                        material = 'fulltext'
                    elif ref['key'] == 'M5':
                        material = 'fulltext'
                        parser_version = 'master-reference-quarto-2'
                        sections = []
                        for section_id in FPP3_SECTIONS[attempt['url'].rsplit('/', 1)[-1]]:
                            node = page.xpath('//*[@id=$section]', section=section_id)
                            if len(node) != 1:
                                raise ValueError('fpp3_section_locator_not_unique: ' + section_id)
                            section_text = ' '.join(' '.join(node[0].itertext()).split())
                            sections.append({'anchor': section_id, 'text_sha256': digest(section_text.encode()),
                                             'characters': len(section_text)})
                        metadata.update(content_review='selected_sections_read_not_scientific_claim_or_index_license',
                                        sections_read=sections,
                                        correction='Complete chapter body is inline in current Quarto HTML; earlier chapter_entry receipt is retained')
                source = {'source_id': sid, 'title': title, 'canonical_url': ref['urls'][0], 'corpus_roles': ['research']}
                if not w.lib.resolve(sid):
                    w.lib.seed({'sources': [source]}, {'cards': []})
                canonical = w.lib.source(sid)['source_id']
                rights = {'index_allowed': False, 'status': 'reference_original_only_rights_not_granted',
                          'redistribution_allowed': False}
                if ref['key'] == 'C1-6' and raw.startswith(b'%PDF-'):
                    metadata.update(publication_status='author_accepted_manuscript',
                                    citation_version_note='Institutional accepted manuscript, not version of record',
                                    title='Contextualizing parasympathetic hyperactivity in functionally overreached athletes with perceptions of training tolerance',
                                    doi='10.1123/ijspp.2015-0495')
                    rights.update(noncommercial_only=True, rights_scope='private study and research; original repository terms retained')
                vid = w.lib.record_version(canonical, raw, material, attempt, metadata, rights,
                                           'reference_identity_pending_scientific_review', [], parser_version)
                versions.append({'version_id': vid, 'canonical_source_id': canonical, 'reused': False})
            current = [dict(r) for r in w.lib.sources.execute(
                'SELECT version_id,material_type,sha256,parser_version,rights_json FROM version WHERE source_id=?',
                (w.lib.source(sid)['source_id'],)).fetchall()] if w.lib.resolve(sid) else []
            for row in current:
                row['index_allowed'] = json.loads(row.pop('rights_json')).get('index_allowed', False)
            registered.append({'key': ref['key'], 'source_id': sid, 'urls': ref['urls'],
                               'attempts': attempts, 'reference_registration': versions, 'current_versions': current})
        claims = [json.loads(r[0]) for r in w.lib.theories.execute("SELECT payload_json FROM source_claim WHERE status='verified'")]
        coverage = json.loads((BASE / 'topic-coverage-final.json').read_text())['rows']
        for row in registered:
            ids = {v.get('canonical_source_id', row['source_id']) for v in row['reference_registration']} | {row['source_id']}
            row['reviewed_claims'] = [c['claim_id'] for c in claims if any(e['source_id'] in ids for e in c['evidence_links'])]
            row['retrieved_topics'] = [r['topic'] for r in coverage if set(r['claims']) & set(row['reviewed_claims'])]
        out = {'checked_at': now(), 'scope': 'Receipt, immutable registration, current claim/use and actual topic retrieval; not blanket content review', 'references': registered}
        (BASE / 'source-final-audit.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
        print({'references': len(registered), 'new_reference_versions': sum(not v['reused'] for r in registered for v in r['reference_registration'])})
    finally:
        w.close()


if __name__ == '__main__':
    run()
