"""Explicitly authorized local document import; optional PDF coordinate extraction."""

from __future__ import annotations

import io
from pathlib import Path

from .acquisition import identity_check, parse_jats
from .store import now


class PDFParserUnavailable(RuntimeError):
    pass


def parse_pdf(raw: bytes) -> tuple[dict, list[dict]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise PDFParserUnavailable("Install optional dependency: pip install -e '.[knowledge-pdf]'") from exc
    spans = []
    with pdfplumber.open(io.BytesIO(raw)) as document:
        metadata = {"pdf_metadata": document.metadata, "page_count": len(document.pages),
                    "identity_review": "manual_document_title_doi_and_version_check_required"}
        for page_index, page in enumerate(document.pages):
            for order, line in enumerate(page.extract_text_lines()):
                text = line.get('text', '').strip()
                if not text:
                    continue
                spans.append({'kind': 'paragraph', 'section_path': f'PDF page {page_index + 1}', 'text': text,
                              'locator': {'file_page_index': page_index, 'printed_page': None,
                                          'bounding_box': [line['x0'], line['top'], line['x1'], line['bottom']],
                                          'coordinate_system': 'pdf_points_top_left', 'reading_order': order,
                                          'start_offset': 0, 'end_offset': len(text), 'extraction_method': 'pdfplumber_text_layer',
                                          'language': 'und'}, 'structured': {'numeric_review_status': 'pending', 'ocr_used': False}})
            for index, table in enumerate(page.find_tables()):
                rows = table.extract()
                spans.append({'kind': 'table', 'section_path': f'PDF page {page_index + 1}',
                              'text': '\n'.join(' | '.join(c or '' for c in row) for row in rows),
                              'locator': {'file_page_index': page_index, 'printed_page': None,
                                          'bounding_box': list(table.bbox), 'coordinate_system': 'pdf_points_top_left',
                                          'table_index': index, 'extraction_method': 'pdfplumber_lines'},
                              'structured': {'cells': [{'row': r, 'column': c, 'text': value} for r, row in enumerate(rows) for c, value in enumerate(row)],
                                             'cell_boxes': [list(box) if box else None for box in table.cells],
                                             'row_headers': None, 'column_headers': None, 'caption': None,
                                             'footnotes': None, 'units': None, 'population': None,
                                             'numeric_review_status': 'manual_table_header_cell_footnote_verification_required'}})
        metadata['parse_quality'] = 'text_layer_extracted' if spans else 'no_text_layer_requires_authorized_ocr'
    return metadata, spans


def import_document(workbench, source_id: str, path, *, license_id: str, rights_evidence_url: str,
                    authorized_by: str, identity_review: dict, noncommercial_internal_only: bool = True):
    """Import a legitimate user-provided copy with an explicit rights and identity declaration.

    The permission declaration is a review record, not a licence inferred from file access.
    Unidentified PDFs are retained as pending; a parser never fabricates missing text/OCR.
    """
    if not license_id or not rights_evidence_url or not authorized_by:
        raise ValueError('explicit_license_evidence_and_authorizer_required')
    if identity_review.get('decision') != 'matched' or not identity_review.get('reviewer') or not identity_review.get('rationale'):
        raise ValueError('explicit_document_identity_review_required')
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) > 20_000_000:
        raise ValueError('document_size_limit')
    source = workbench.lib.source(source_id)['manifest']
    rights = {'status': 'explicit_authorized_local_copy', 'license_id': license_id,
              'evidence_url': rights_evidence_url, 'authorized_by': authorized_by,
              'declared_use': 'local_internal_noncommercial_research_and_retrieval' if noncommercial_internal_only else 'explicit_reviewed_use',
              'index_allowed': True, 'redistribution_allowed': False,
              'rights_scope': 'this_supplied_copy_only', 'reviewed_at': now()}
    receipt = {'url': 'authorized-local-file', 'filename': path.name, 'fetched_at': now(), 'identity_review': identity_review}
    status, conflicts, reason = 'matched', [], None
    if raw.startswith(b'%PDF'):
        parser_version = 'pdfplumber-layout-1.3.0'
        try:
            metadata, spans = parse_pdf(raw)
        except PDFParserUnavailable as exc:
            metadata, spans = {'parse_quality': 'parser_unavailable'}, []
            rights['index_allowed'] = False
            reason = str(exc)
        if not spans:
            rights['index_allowed'] = False
    else:
        parser_version = 'jats-1.3.0'
        metadata, spans, document_rights = parse_jats(raw)
        status, conflicts = identity_check(source, metadata)
        metadata['embedded_rights'] = document_rights
    metadata['identity_review'] = identity_review
    metadata['identity_conflicts'] = conflicts
    version = workbench.lib.record_version(source_id, raw, 'fulltext', receipt, metadata, rights, status, spans, parser_version)
    workbench.lib.log(source_id, 'authorized_document_import', {'version_id': version, 'parser_version': parser_version, 'span_count': len(spans), 'reason': reason})
    return {'version_id': version, 'span_count': len(spans), 'identity_status': status,
            'status': 'parsed_pending_claim_review' if spans and status == 'matched' else 'pending_parser_or_identity_review', 'reason': reason}
