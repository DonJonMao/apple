"""Install version-pinned, explicitly read general method uses in the existing libraries."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from lxml import html

from healthzip.knowledge import KnowledgeWorkbench, domains, vector_index
from healthzip.knowledge.core import _claim
from healthzip.knowledge.store import digest, now


def _register_claim(w, entry, vid, hashes, review, domain):
    for sid, expected in hashes.items():
        span = w.lib.span(sid, include_metadata=False)
        if not span or span['version_id'] != vid or span['text_hash'] != expected:
            raise ValueError('reviewed_original_changed')
    if not w.lib.sources.execute('SELECT 1 FROM retrieval_unit u JOIN span s USING(span_id) WHERE s.version_id=? LIMIT 1', (vid,)).fetchone():
        vector_index.register_spans(w, vid, [domain])
    # Reuse existing checked assignments on any shared original passages.
    for sid in hashes:
        if not w.lib.sources.execute('SELECT 1 FROM retrieval_unit_domain_review WHERE span_id=? LIMIT 1', (sid,)).fetchone():
            vector_index.review_unit_domains(w, [sid], [domain], review)
    claim = {'claim_id': entry['claim_id'], 'version': entry.get('claim_version', '1'), 'statement': entry['statement'],
             'conditions': [], 'scope': {'explanation_purpose': 'measurement_context', 'population_and_design': entry['scope']},
             'limitations': [entry['limitation']], 'evidence_links': [
                 {'source_id': entry['source_id'], 'source_version_id': vid, 'span_ids': list(hashes)}]}
    w.review_claim(claim, review)


def apply(root, local, output):
    packet_path = Path(__file__).with_name('master_source_reviews.json')
    packet = json.loads(packet_path.read_text())
    review = {'reviewer': packet['reviewer'], 'reviewer_kind': 'ai_assisted', 'reviewed_at': packet['reviewed_at'],
              'rationale': 'Bounded general explanation, original text and scope checked. No personal numerical advice.',
              'content_checked': True, 'application_checked': True, 'independent_expert_validation': False}
    w = KnowledgeWorkbench(root)
    receipt = {'applied_at': now(), 'packet_sha256': digest(packet_path.read_bytes()), 'claims': [], 'edges': []}
    try:
        vector_index.ensure_schema(w)
        domains.ensure_schema(w)
        for entry in packet['new_claims']:
            raw = (Path(local) / entry['raw_sha256']).read_bytes()
            if digest(raw) != entry['raw_sha256']:
                raise ValueError('original_hash_mismatch')
            spans = []
            if entry.get('format') == 'pdf':
                import pdfplumber

                with pdfplumber.open(io.BytesIO(raw)) as doc:
                    for unit in entry['units']:
                        page = doc.pages[unit['file_page_index']]
                        text = ' '.join(page.crop(tuple(unit['bounding_box'])).extract_text().split())
                        if digest(text.encode()) != unit['text_sha256']:
                            raise ValueError('reviewed_pdf_passage_changed')
                        spans.append({'text': text, 'section_path': entry['section'], 'locator': unit})
            else:
                doc = html.fromstring(raw)
                for unit in entry['units']:
                    nodes = doc.xpath(unit['xpath'])
                    if len(nodes) != 1:
                        raise ValueError('reviewed_locator_changed')
                    text = ' '.join(' '.join(nodes[0].itertext()).split())
                    if digest(text.encode()) != unit['text_sha256']:
                        raise ValueError('reviewed_paragraph_changed')
                    spans.append({'text': text, 'section_path': entry['section'], 'locator': unit})
            source = {k: entry[k] for k in ['source_id', 'title', 'doi', 'authors', 'year']}
            source.update(canonical_url=entry['url'], corpus_roles=['research'])
            w.lib.seed({'sources': [source]}, {'cards': []})
            parser_version = entry.get('parser_version', 'reviewed-author-html-1')
            existing = w.lib.sources.execute(
                "SELECT version_id FROM version WHERE source_id=? AND sha256=? AND parser_version=?",
                (entry['source_id'], entry['raw_sha256'], parser_version)).fetchone()
            vid = existing[0] if existing else w.lib.record_version(entry['source_id'], raw, 'fulltext', {'url': entry['url'], 'sha256': entry['raw_sha256']},
                {**source, **entry.get('version_metadata', {})}, {'index_allowed': True, 'license_id': entry['license'], 'license_url': entry['license_url'],
                         'status': 'reviewed_original_author_text_only', 'rights_scope': 'only cited author paragraphs; no third-party content',
                         **entry.get('rights_details', {})},
                'matched', spans, parser_version)
            hashes = {vid + f':s{i:05d}': s['locator']['text_sha256'] for i, s in enumerate(spans)}
            _register_claim(w, entry, vid, hashes, review, entry.get('domain', 'wearable'))
            receipt['claims'].append({'claim_id': entry['claim_id'], 'version': vid, 'span_hashes': hashes})
        for entry in packet['reviewed_existing_spans']:
            _register_claim(w, entry, entry['version_id'], entry['hashes'], review, entry['domain'])
            receipt['claims'].append({'claim_id': entry['claim_id'], 'version': entry['version_id'], 'span_hashes': entry['hashes']})
        for use in packet['uses']:
            ref = {k: use[k] for k in ('claim_id', 'version')}
            _, _, spans = _claim(w, ref)
            for topic in use['targets']:
                edge = domains.link(w, origin={'type': 'claim', 'id': ref['claim_id'], 'version': ref['version']}, relation='limits',
                    target={'type': 'metric', 'id': topic, 'version': domains.profile_version(topic)},
                    span_ids=[s['span_id'] for s in spans], applicability={}, actor=review['reviewer'],
                    rationale=review['rationale'], evidence_types=use['purposes'], review=review)
                receipt['edges'].append({'topic': topic, 'claim_id': ref['claim_id'], 'edge': edge, 'purposes': use['purposes']})
        Path(output).write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    finally:
        w.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', default='.local/knowledge')
    p.add_argument('--local', default='.local/master-knowledge/fetched')
    p.add_argument('--output', default='artifacts/master_redesign/knowledge/reviewed-uses.json')
    args = p.parse_args()
    apply(args.root, args.local, args.output)
