"""Read-only publication scan for the R05 public/synthetic delivery files.

Never opens a health database. E7 originals are read only from SourceLibrary;
matches are reported as IDs/hashes, without copying matched source prose.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ARTIFACTS = Path('artifacts/followup_20261127/knowledge-content-gaps')
DELIVERY_FILES = (
    'tools/followup_knowledge_content_gaps.py',
    'tools/followup_knowledge_content_probe.py',
    'tools/followup_knowledge_browser.py',
    'tools/followup_knowledge_publication_scan.py',
    'tools/followup_stream_browser.py',
    'tools/followup_w1_rir_install.py',
    'tools/followup_w1_rir_browser.py',
    'docs/followup_knowledge_content_gaps.md',
    'docs/followup_knowledge_six_questions.md',
    'docs/followup_knowledge_completion.md',
    'docs/followup_stream_labels.md',
    'docs/followup_w1_rir_context.md',
    'src/healthzip/analytics/body_questions.py',
    'src/healthzip/analytics/question_context.py',
    'src/healthzip/knowledge/metric_retrieval.py',
    'src/healthzip/knowledge/topics.py',
    'src/healthzip/analytics/health_context.py',
    'src/healthzip/ui/health_comparison.py',
    'src/healthzip/ui/question_page.py',
    'src/healthzip/ui/review_page.py',
    'src/healthzip/ui/topic_sources.py',
    'src/healthzip/workflows/period_report.py',
    'src/healthzip/workflows/report_objects.py',
    'src/healthzip/workflows/reports.py',
    'tests/knowledge/test_w1_computed_rir_scope.py',
    'tests/unit/test_question_page_empty_state.py',
    'tests/integration/test_followup_stream_labels.py',
)
RAW_KEYS = {'evidence_spans', 'parent_context'}
RAW_CONTAINER = re.compile(r'''["'](evidence_spans|parent_context)["']\s*:\s*([\[{])\s*([^\s\]}])''')
EXCLUDED_SUFFIXES = {'.pdf', '.sqlite', '.sqlite3', '.db', '.zip', '.gz', '.tar'}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def originals(knowledge):
    conn = sqlite3.connect((knowledge / 'sources.sqlite3').resolve().as_uri() + '?mode=ro', uri=True)
    try:
        rows = conn.execute("""SELECT span_id,text,text_hash,version_id FROM span
            WHERE version_id IN (SELECT version_id FROM version WHERE source_id='E7' AND material_type='fulltext')
            AND length(text)>100 ORDER BY span_id""").fetchall()
    finally:
        conn.close()
    if not rows:
        raise ValueError('retained_E7_original_paragraphs_required')
    patterns = []
    for sid, prose, text_hash, version in rows:
        prefix = prose[:100]
        variants = {prefix: 'literal_prefix'}
        for ascii_only in (False, True):
            variants.setdefault(json.dumps(prefix, ensure_ascii=ascii_only)[1:-1],
                                'json_escaped_ascii_prefix' if ascii_only else 'json_escaped_unicode_prefix')
        patterns.append({'span_id': sid, 'source_version': version, 'text_sha256': text_hash,
                         'fulltext': prose, 'variants': variants})
    return patterns


def source_hits(text, patterns):
    hits = []
    for row in patterns:
        kinds = [kind for needle, kind in row['variants'].items() if needle in text]
        if row['fulltext'] in text:
            kinds.append('complete_paragraph')
        if kinds:
            hits.append({key: row[key] for key in ('span_id', 'source_version', 'text_sha256')}
                        | {'matched_forms': kinds, 'prefix_characters': 100})
    return hits


def raw_payloads(value, path='$'):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = path + '[' + json.dumps(key, ensure_ascii=False) + ']'
            if key in RAW_KEYS and item:
                found.append({'json_path': child, 'type': type(item).__name__,
                              'length': len(item) if hasattr(item, '__len__') else None})
            found.extend(raw_payloads(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(raw_payloads(item, path + f'[{index}]'))
    elif isinstance(value, str) and value.lstrip().startswith(('{', '[')):
        try:
            nested = json.loads(value)
        except (ValueError, RecursionError):
            pass
        else:
            found.extend(raw_payloads(nested, path + '<decoded_json_string>'))
    return found


def json_payloads(text):
    """Inspect ordinary JSON plus JSON objects printed into diagnostic logs."""
    decoder, offset = json.JSONDecoder(), 0
    while offset < len(text):
        match = re.search(r'[\[{]', text[offset:])
        if not match:
            return
        offset += match.start()
        try:
            value, end = decoder.raw_decode(text, offset)
        except (ValueError, RecursionError):
            offset += 1
        else:
            yield offset, value
            offset = end


def scan(repo, knowledge, output, stage):
    patterns = originals(knowledge)
    paths = {p for p in (repo / ARTIFACTS).rglob('*') if p.is_file() or p.is_symlink()}
    paths.update(repo / p for p in DELIVERY_FILES)
    paths.discard(output.resolve())
    files, all_hits, all_raw = [], [], []
    for path in sorted(paths):
        relative = str(path.relative_to(repo))
        row = {'path': relative}
        if path.is_symlink():
            row.update(classification='exclude', reason='symlink_not_followed', sha256=None)
            files.append(row)
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            row.update(classification='exclude', reason='database_archive_or_original_PDF_not_opened_or_published',
                       sha256=None, bytes=path.stat().st_size)
            files.append(row)
            continue
        data = path.read_bytes()
        row.update(sha256=sha256(data), bytes=len(data))
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            synthetic_image = path.suffix.lower() == '.png' and path.is_relative_to(repo / ARTIFACTS)
            row.update(classification='publish' if synthetic_image else 'exclude',
                       reason='synthetic_browser_image_existing_visual_receipts' if synthetic_image else 'unknown_binary_not_text_scanned',
                       text_scan='not_applicable_binary', contains_fulltext_evidence_payload=False)
            files.append(row)
            continue
        hits = source_hits(text, patterns)
        raw = []
        for offset, value in json_payloads(text):
            raw.extend({'json_document_offset': offset, **item} for item in raw_payloads(value))
        # A Python-style diagnostic repr may not parse as JSON. Flag literal
        # nonempty containers too; code references to field names are not data.
        lexical_raw = [{'key': m.group(1), 'offset': m.start()} for m in RAW_CONTAINER.finditer(text)]
        invalid_json = None
        if path.suffix.lower() == '.json':
            try:
                json.loads(text)
            except (ValueError, RecursionError) as exc:
                invalid_json = type(exc).__name__
        row.update(text_scan='E7_paragraph_and_escaped_prefix_plus_recursive_raw_payloads',
                   E7_original_hits=hits, raw_evidence_payload_paths=raw,
                   raw_container_text_hits=lexical_raw, contains_fulltext_evidence_payload=bool(raw or lexical_raw),
                   invalid_json=invalid_json,
                   classification='exclude' if hits or raw or lexical_raw or invalid_json else 'publish',
                   reason='source_prose_raw_payload_or_unparseable_JSON_requires_exclusion' if hits or raw or lexical_raw or invalid_json
                          else 'own_code_or_bounded_claims_public_metadata_synthetic_evidence')
        all_hits.extend({'path': relative, **hit} for hit in hits)
        all_raw.extend({'path': relative, **item} for item in [*raw, *lexical_raw])
        files.append(row)
    changed = []
    for row in files:
        if row.get('sha256') is None:
            continue
        path = repo / row['path']
        if not path.is_file() or path.is_symlink() or sha256(path.read_bytes()) != row['sha256']:
            changed.append(row['path'])
            row.update(classification='exclude', reason='file_changed_during_scan')
    end_paths = {p for p in (repo / ARTIFACTS).rglob('*') if p.is_file() or p.is_symlink()}
    end_paths.update(repo / p for p in DELIVERY_FILES)
    end_paths.discard(output.resolve())
    membership_changes = sorted(str(p.relative_to(repo)) for p in paths.symmetric_difference(end_paths))
    result = {'schema': 'knowledge-publication-scan-1', 'stage': stage,
              'scanned_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'All current knowledge-content-gaps files plus the listed tools/docs; old failure files retained.',
              'reference_scan': str(ARTIFACTS / 'publication-scan-initial.json'),
              'original_scan_method': {'source': 'E7 retained fulltext spans only, read-only SourceLibrary',
                  'paragraphs_over_100_characters': len(patterns), 'prefix_characters': 100,
                  'forms': ['literal', 'JSON escaped Unicode', 'JSON escaped ASCII', 'complete paragraph'],
                  'source_versions': sorted({p['source_version'] for p in patterns}), 'matched_prose_written': False},
              'E7_original_paragraph_prefix_hits': all_hits, 'raw_evidence_payload_paths': all_raw,
              'files_checked': files,
              'files_changed_during_scan': changed, 'membership_changed_during_scan': membership_changes,
              'scan_snapshot_stable': not (changed or membership_changes),
              'counts': {'files': len(files), 'publish': sum(f['classification'] == 'publish' for f in files),
                         'exclude': sum(f['classification'] == 'exclude' for f in files)},
              'manifest_self_exclusion': str(output.relative_to(repo)),
              'public_artifacts_policy': 'Only own code/bounded claims, public source metadata/locators/hashes, and synthetic UI/report/checks. No original article text or databases.',
              'must_exclude': ['.local/knowledge/', '.local/knowledge-backups/',
                               'all original PDF files including retained untracked user PDFs',
                               'private health databases, exports, records and personal reports/logs',
                               'raw audit bundles with nonempty evidence_spans or parent_context'],
              'limitations': ['Exact original-prefix detection does not establish rights for arbitrary paraphrases or other sources.',
                             'PNG files are hashed and classified using their synthetic-browser provenance and separate visual reviews; this is not OCR.',
                             'This is a scoped delivery scan, not a general private-data discovery scan.'],
              'private_health_opened': False, 'source_library_open_mode': 'read_only', 'external_calls': 0,
              'original_or_failed_files_modified': False}
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    output.write_text(encoded)
    return {'output': str(output.relative_to(repo)), 'sha256': sha256(encoded.encode()),
            **result['counts'], 'E7_hits': len(all_hits), 'raw_payload_hits': len(all_raw)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--knowledge', type=Path, default=Path('.local/knowledge'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=('preflight', 'final'), required=True)
    args = parser.parse_args()
    print(json.dumps(scan(args.repo.resolve(), args.knowledge.resolve(), args.output.resolve(), args.stage)))
