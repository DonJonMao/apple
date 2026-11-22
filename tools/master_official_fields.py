"""Append official DocC originals as field-definition references, preserving their terms."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.store import digest


def install(root, local, receipts, output):
    rows = json.loads(Path(receipts).read_text())
    w = KnowledgeWorkbench(root)
    registered = {}
    try:
        for key, r in rows.items():
            if not key.startswith('HK-') or r.get('material') != 'docc_received':
                continue
            field = key.removeprefix('HK-')
            byte_file = Path(local) / r['sha256']
            if not byte_file.exists() and r.get('local_storage'):
                byte_file = Path(root) / r['local_storage']
            raw = byte_file.read_bytes()
            if digest(raw) != r['sha256']:
                raise ValueError('official_source_bytes_changed')
            page = json.loads(raw)
            symbol = page.get('identifier', {}).get('url', '').split('/')[-1]
            if not symbol or symbol.lower() + '.json' != r['url'].split('/')[-1].lower():
                raise ValueError('official_symbol_identity_mismatch:' + field)
            url = r['url'].replace('/tutorials/data/', '/').removesuffix('.json')
            # A known field can already have an immutable official DocC parse.
            old = w.lib.sources.execute("SELECT source_id,version_id FROM version WHERE sha256=? AND material_type='fulltext' ORDER BY created_at LIMIT 1", (r['sha256'],)).fetchone()
            if old:
                sid, vid = old
            else:
                source = {'source_id': 'HK-FIELD-' + field, 'title': symbol, 'canonical_url': url,
                          'authors': ['Apple'], 'corpus_roles': ['interface']}
                w.lib.seed({'sources': [source]}, {'cards': []})
                sid = w.lib.source(source['source_id'])['source_id']
                vid = w.lib.record_version(sid, raw, 'fulltext', {'url': r['url'], 'sha256': r['sha256']},
                    {'title': symbol, 'abstract_available': bool(page.get('abstract')), 'platforms': page['metadata'].get('platforms', [])},
                    {'index_allowed': False, 'status': 'official_document_terms_review_required'},
                    'matched', [], 'apple-docc-reference-1')
            registered[field] = {'source_id': sid, 'version': vid, 'sha256': r['sha256'], 'url': url, 'symbol': symbol}
        Path(output).write_text(json.dumps(registered, ensure_ascii=False, indent=2) + '\n')
    finally:
        w.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', default='.local/knowledge')
    p.add_argument('--local', default='.local/master-knowledge/fetched')
    p.add_argument('--receipts', default='artifacts/master_redesign/knowledge/official-fields-and-retries.json')
    p.add_argument('--output', default='src/healthzip/knowledge/data/field_originals.json')
    args = p.parse_args()
    install(args.root, args.local, args.receipts, args.output)
