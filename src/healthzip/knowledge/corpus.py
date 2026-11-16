"""Hash-pinned local corpus ingestion with separate identity, rights and content review."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import domains, vector_index
from .store import digest, dumps, now
from .structured_pdf import PARSER_VERSION, parse_structured_pdf
from .transactions import atomic

RIGHTS_SCOPE_VERSION = 'document-component-scope-1.5.2'
IMPORT_VERSION = PARSER_VERSION + '-' + RIGHTS_SCOPE_VERSION


def component_rights(spans):
    """Caption typography cannot override third-party exclusions."""
    for span in spans:
        if span['kind'] in {'table', 'formula_context'}:
            span['locator']['bounding_box_scope'] = 'main_component_only'
            span['locator']['surrounding_context_scope'] = 'same_file_page; see structured context'
        caption = re.match(r'^(?:figure|fig\.|table|equation)\s*[\dIVX]', span['text'], re.I)
        notice = re.search(r'reproduced (?:with|from)|used (?:with|by) permission|all rights reserved|'
            r'photo(?:graph)? credit|image credit|adapted from|courtesy of|source:\s', span['text'], re.I)
        if caption or notice or span['kind'] == 'caption':
            span['rights'] = {'status': 'rights_pending_component_review', 'index_allowed': False,
                'redistribution_allowed': False, 'scope_policy_version': RIGHTS_SCOPE_VERSION,
                'reason': 'caption_or_third_party_attribution_needs_individual_review'}
    return spans


def import_manifest_document(w, entry, path, *, parse_cache=None, progress=None):
    """Only a reviewed manifest may enable indexing; presence on disk grants nothing."""
    path = Path(path)
    raw = path.read_bytes()
    if path.name != entry['file_name'] or digest(raw) != entry['sha256'] or len(raw) != entry['bytes']:
        raise ValueError('manifest_file_hash_or_size_mismatch')
    if entry.get('document_kind') == 'ai_recommendation_list':
        return {'file_name': path.name, 'status': 'excluded_not_scientific_evidence', 'span_count': 0}
    identity_review = entry.get('identity_review', {})
    if identity_review.get('decision') != 'matched' or not identity_review.get('reviewer') or not identity_review.get('pages_checked'):
        raise ValueError('exact_file_identity_review_required')
    decision = entry.get('rights_review', {})
    cleared = decision.get('decision') == 'local_index_cleared'
    if cleared and (not decision.get('evidence') or not decision.get('reviewer') or not decision.get('license_id')):
        raise ValueError('source_license_review_required')
    source_id = entry['source_id']
    manifest = {key: entry.get(key) for key in ('source_id', 'title', 'authors', 'year', 'edition_id',
        'canonical_url', 'doi', 'isbn', 'document_number', 'document_kind')}
    manifest = {key: value for key, value in manifest.items() if value is not None}
    manifest.update(language='en', corpus_roles=['core'], source_kind='textbook_or_official_guide')
    if entry.get('manifestation_id'):
        manifest['manifestation_id'] = entry['manifestation_id']
    w.lib.seed({'sources': [manifest]}, {'cards': []})
    canonical = w.lib.source(source_id)['source_id']
    # Exact manifestation identity must never be merged on a similar title.
    if canonical != source_id:
        raise ValueError('source_identity_collision_requires_explicit_resolution')
    cache_file = Path(parse_cache) / (entry['sha256'] + '-' + PARSER_VERSION + '.json') if parse_cache else None
    if cache_file and cache_file.is_file():
        cached = json.loads(cache_file.read_text())
        if cached.get('sha256') != entry['sha256'] or cached.get('parser_version') != PARSER_VERSION:
            raise ValueError('parse_cache_identity_mismatch')
        metadata, spans = cached['metadata'], cached['spans']
    else:
        metadata, spans = parse_structured_pdf(raw, progress=progress)
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(dumps({'sha256': entry['sha256'], 'parser_version': PARSER_VERSION,
                                        'metadata': metadata, 'spans': spans}))
    if metadata['page_count'] != entry['page_count']:
        raise ValueError('manifest_page_count_mismatch')
    component_rights(spans)
    rights = {'status': 'reviewed_local_document_scope' if cleared else 'rights_pending',
        'license_id': decision.get('license_id'), 'index_allowed': cleared,
        'redistribution_allowed': False, 'noncommercial_only': decision.get('noncommercial_only', True),
        'rights_scope': 'document_prose_except_unresolved_third_party_components',
        'scope_policy_version': RIGHTS_SCOPE_VERSION,
        'evidence': decision.get('evidence'), 'reviewer': decision.get('reviewer'), 'reviewed_at': decision.get('reviewed_at')}
    metadata.update(identity_review=identity_review, content_completeness=entry.get('content_completeness'),
                    identity_conflicts=entry.get('identity_conflicts', []))
    metadata['scope_policy_version'] = RIGHTS_SCOPE_VERSION
    receipt = {'url': 'user_supplied_local_document', 'filename': path.name, 'sha256': entry['sha256'],
               'official_original_download_url': entry.get('official_original_download_url'), 'imported_at': now(),
               'official_download_receipt_available': False}
    expected_id = f'{source_id}:fulltext:{entry["sha256"][:20]}:{IMPORT_VERSION}'
    prior = w.lib.sources.execute('SELECT rights_json FROM version WHERE version_id=?', (expected_id,)).fetchone()
    if prior and prior[0] != dumps(rights):
        raise ValueError('immutable_scope_review_changed_requires_explicit_policy_version')
    vid = w.lib.record_version(source_id, raw, 'fulltext', receipt, metadata, rights, 'matched', spans, IMPORT_VERSION)
    # Only this new importer's earlier same-byte scope pass is superseded.
    # Historical v1.4 parses/reviews and unrelated editions are never rewritten.
    with atomic(w.lib.sources) as conn:
        for old in conn.execute("SELECT version_id FROM version WHERE source_id=? AND sha256=? AND parser_version LIKE 'pdf-structure-1.5.%' AND version_id<>?",
                                (source_id, entry['sha256'], vid)).fetchall():
            conn.execute('INSERT OR IGNORE INTO parse_supersession VALUES(?,?,?,?)',
                (old[0], vid, 'Component scope review: caption typography and third-party attribution; prior bytes retained.', now()))
    domains.assign(w, object_type='source_version', object_id=source_id, object_version=vid,
        domains=entry['domains'], status='provisional', actor='AI-assisted corpus inventory',
        rationale='File-level routing proposal; does not approve individual claims or all sections.')
    vector_index.register_spans(w, vid, entry['domains'], assignment_status='provisional')
    eligible = sum(w.lib.eligible(w.lib.span(vid + f':s{i:05d}', include_metadata=False), 'fulltext')[0] for i in range(len(spans)))
    pages = metadata['page_reports']
    return {'source_id': source_id, 'version_id': vid, 'sha256': entry['sha256'], 'file_name': path.name,
        'status': 'parsed_pending_claim_review', 'page_count': len(pages), 'span_count': len(spans),
        'eligible_local_index_spans': eligible, 'rights_pending_component_spans': len(spans)-eligible,
        'outline_pages': metadata['outline_page_count'], 'table_units': sum(s['kind'] == 'table' for s in spans),
        'formula_context_units': sum(s['kind'] == 'formula_context' for s in spans),
        'no_text_or_blank_pages': [p['file_page_index'] for p in pages if p['quality'] == 'no_text_layer_or_blank_page'],
        'replacement_character_pages': [p['file_page_index'] for p in pages if p['replacement_characters']],
        'future_chapter_marker_pages': [p['file_page_index'] for p in pages if p['future_chapter_marker']],
        'parse_limitations': metadata['limitations'], 'scientific_claims_approved': 0,
        'private_health_data_used': False, 'raw_bytes_publication_allowed': False}
