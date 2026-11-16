import copy
from pathlib import Path

import pytest

from healthzip.knowledge.corpus import import_manifest_document
from healthzip.knowledge.store import digest
from healthzip.knowledge.structured_pdf import parse_structured_pdf

PDF = Path(__file__).parents[1] / 'fixtures/synthetic_knowledge.pdf'


def entry():
    raw = PDF.read_bytes()
    return {'file_name': PDF.name, 'sha256': digest(raw), 'bytes': len(raw), 'page_count': 1,
        'source_id': 'synthetic-pdf', 'title': 'Synthetic test PDF', 'authors': 'Synthetic', 'year': 2026,
        'canonical_url': 'https://example.invalid/synthetic', 'domains': ['strength'],
        'document_kind': 'synthetic_fixture',
        'identity_review': {'decision': 'matched', 'reviewer': 'Synthetic', 'pages_checked': [0]},
        'rights_review': {'decision': 'local_index_cleared', 'reviewer': 'Synthetic', 'license_id': 'CC0',
                         'noncommercial_only': False, 'evidence': ['Synthetic fixture declaration']}}


def test_structured_table_keeps_cells_headers_and_prose_together():
    meta, spans = parse_structured_pdf(PDF.read_bytes())
    assert meta['page_count'] == 1
    table = next(s for s in spans if s['kind'] == 'table')
    assert [c['text'] for c in table['structured']['cells']] == ['Load', 'Reps', '10', '8']
    assert 'Synthetic evidence only' in table['text'] and 'Load | Reps' in table['text']
    assert table['structured']['numeric_review_status'] == 'pending'
    assert table['locator']['file_page_index'] == 0
    assert table['locator']['bounding_box'] == [30., 80., 180., 120.]
    assert not any(s['text'] in {'10', '8', 'Load', 'Reps'} for s in spans)


def test_manifest_ingestion_is_repeatable_and_never_approves_claims(kb, tmp_path):
    first = import_manifest_document(kb, entry(), PDF, parse_cache=tmp_path / 'parses')
    second = import_manifest_document(kb, entry(), PDF, parse_cache=tmp_path / 'parses')
    assert first['version_id'] == second['version_id']
    assert kb.lib.sources.execute('SELECT COUNT(*) FROM version').fetchone()[0] == 1
    assert first['scientific_claims_approved'] == 0
    assert kb.lib.theories.execute('SELECT COUNT(*) FROM source_claim').fetchone()[0] == 0
    assert kb.lib.sources.execute('SELECT DISTINCT assignment_status FROM retrieval_unit').fetchone()[0] == 'provisional'


def test_unknown_rights_are_preserved_without_index_permission(kb):
    e = copy.deepcopy(entry())
    e['rights_review'] = {'decision': 'rights_pending'}
    report = import_manifest_document(kb, e, PDF)
    assert report['span_count'] > 0 and report['eligible_local_index_spans'] == 0
    assert kb.lib.sources.execute('SELECT COUNT(*) FROM version').fetchone()[0] == 1


def test_manifest_hash_mismatch_does_not_write_source(kb):
    e = entry()
    e['sha256'] = '0'*64
    with pytest.raises(ValueError, match='hash_or_size'):
        import_manifest_document(kb, e, PDF)
    assert kb.lib.sources.execute('SELECT COUNT(*) FROM source').fetchone()[0] == 0


def test_caption_styled_as_heading_and_attributed_table_stay_rights_pending():
    from healthzip.knowledge.corpus import component_rights
    spans = [{'kind': 'heading', 'text': 'Figure 2. A third-party figure', 'structured': {}, 'locator': {'file_page_index': 0}},
             {'kind': 'table', 'text': 'Load | Reps\n10 | 8\nSource: external owner', 'structured': {}, 'locator': {'file_page_index': 0}},
             {'kind': 'paragraph', 'text': 'Synthetic original prose', 'structured': {}, 'locator': {'file_page_index': 0}}]
    component_rights(spans)
    assert spans[0]['rights']['index_allowed'] is False
    assert spans[1]['rights']['index_allowed'] is False
    assert 'rights' not in spans[2]


def test_paragraphs_preserve_inline_font_superscript_and_blank_line_boundary():
    pdf = Path(__file__).parents[1] / 'fixtures/synthetic_structure_v15.pdf'
    _, spans = parse_structured_pdf(pdf.read_bytes())
    paragraphs = [s for s in spans if s['kind'] == 'paragraph']
    assert len(paragraphs) == 2
    assert 'A synthetic protocol' in paragraphs[0]['text']
    assert 'The continuation belongs to the same paragraph' in paragraphs[0]['text']
    assert 'symbolic label X 2 stays with its surrounding explanation.' in paragraphs[0]['text']
    assert 'A new paragraph starts' in paragraphs[1]['text']
    assert 'Its second line must remain attached' in paragraphs[1]['text']
    assert not any(s['text'] == '2' for s in spans)
