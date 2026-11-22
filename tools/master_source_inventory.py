"""Verify public references against the existing SourceLibrary and official URLs.

Only public receipts are published. Copyrighted originals stay in the explicitly
selected local directory. A successful transfer is not a review or permission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from lxml import etree, html

from healthzip.knowledge.acquisition import XML_PARSER
from healthzip.knowledge.store import now


def reference_urls(urls):
    for url in urls:
        if url.startswith('https://developer.apple.com/documentation/'):
            yield url.replace('developer.apple.com/', 'developer.apple.com/tutorials/data/') + '.json'
        pmc = re.search(r'/articles/(PMC\d+)', url)
        if pmc:
            yield 'https://www.ebi.ac.uk/europepmc/webservices/rest/' + pmc[1] + '/fullTextXML'
        yield url


def fetch(url, dest):
    temporary = dest / (hashlib.sha256(url.encode()).hexdigest() + '.download')
    result = subprocess.run(['curl', '--silent', '--show-error', '--fail', '--location', '--proto', '=https',
                             '--proto-redir', '=https', '--connect-timeout', '5', '--max-time', '28',
                             '--max-filesize', '20000000', '--output', str(temporary), '--write-out',
                             '%{response_code}', url], capture_output=True, text=True)
    receipt = {'url': url, 'checked_at': now(), 'http_status': result.stdout, 'curl_exit': result.returncode}
    if result.returncode:
        temporary.unlink(missing_ok=True)
        return receipt
    raw = temporary.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        if raw.startswith(b'%PDF-'):
            material = 'pdf_received'
        elif raw.lstrip().startswith(b'{'):
            value = json.loads(raw)
            if not value.get('identifier') or not value.get('metadata', {}).get('title'):
                raise ValueError('not_docc')
            material = 'docc_received'
        elif b'<article' in raw[:4000] and b'<body' in raw:
            tree = etree.fromstring(raw, XML_PARSER)
            if tree.tag.split('}')[-1] != 'article':
                raise ValueError('not_article')
            material = 'jats_body_received'
        else:
            tree = html.fromstring(raw)
            title = ' '.join(tree.xpath('//title/text()')).strip()
            if not title or any(x in title.lower() for x in ('recaptcha', 'captcha', 'robot', 'just a moment', 'access denied', 'page not found', 'checking your browser')):
                raise ValueError('challenge_or_unidentified_page')
            material = 'html_received_content_depth_unreviewed'
            receipt['page_title'] = title[:220]
        final = dest / sha
        if final.exists():
            temporary.unlink()
        else:
            temporary.replace(final)
        receipt.update(sha256=sha, bytes=len(raw), material=material)
    except (ValueError, etree.Error):
        receipt['material'] = 'unexpected_response'
        temporary.unlink(missing_ok=True)
    return receipt


def inventory(root, local, output):
    refs = json.loads(Path(__file__).with_name('master_sources.json').read_text())
    root, local, output = map(Path, (root, local, output))
    local.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    sources = sqlite3.connect((root / 'sources.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    theories = sqlite3.connect((root / 'theories.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    claims = [json.loads(x[0]) for x in theories.execute("SELECT payload_json FROM source_claim WHERE status='verified'")]
    groups = {}
    for ref in refs:
        sid = ref['source_id']
        versions = sources.execute('SELECT version_id, material_type, parser_version, sha256, storage_uri, rights_json FROM version WHERE source_id=?', (sid,)).fetchall()
        ref['existing_versions'] = [{'version_id': v, 'material': m, 'parser': p, 'sha256': h,
                                     'bytes_present': (root / path).is_file(), 'index_allowed': json.loads(rights).get('index_allowed', False)}
                                    for v, m, p, h, path, rights in versions]
        ref['existing_claims'] = [c['claim_id'] for c in claims if any(e.get('source_id') == sid for e in c['evidence_links'])]
        if any(v['material'] == 'fulltext' and v['bytes_present'] for v in ref['existing_versions']):
            ref['reuse'] = 'existing_local_fulltext'
            continue
        for url in reference_urls(ref['urls']):
            groups.setdefault(urlsplit(url).netloc, {})[url] = None
    sources.close()
    theories.close()

    def host_group(urls):
        return [fetch(url, local) for url in urls]

    with ThreadPoolExecutor(max_workers=8) as pool:
        downloads = {r['url']: r for group in pool.map(host_group, groups.values()) for r in group}
    for ref in refs:
        ref['attempts'] = [downloads[u] for u in reference_urls(ref['urls']) if u in downloads and not ref.get('reuse')]
    report = {'checked_at': now(), 'references': refs, 'scope': 'transfer, current source presence and existing reviewed claim membership only'}
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    return report


if __name__ == '__main__':
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument('--root', default='.local/knowledge')
    arguments.add_argument('--local', default='.local/master-knowledge/fetched')
    arguments.add_argument('--output', default='artifacts/master_redesign/knowledge/source-inventory.json')
    args = arguments.parse_args()
    inventory(args.root, args.local, args.output)
