"""Explicitly authorized local document import; optional PDF coordinate extraction."""

from __future__ import annotations

import io
from pathlib import Path

from .acquisition import identity_check, parse_jats
from .rights import PARSER_VERSION
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
            tables = page.find_tables()
            for order, line in enumerate(page.extract_text_lines()):
                text = line.get('text', '').strip()
                if not text:
                    continue
                table_indices = [index for index, table in enumerate(tables)
                                 if line['x0'] < table.bbox[2] and line['x1'] > table.bbox[0]
                                 and line['top'] < table.bbox[3] and line['bottom'] > table.bbox[1]]
                spans.append({'kind': 'paragraph', 'section_path': f'PDF page {page_index + 1}', 'text': text,
                              'locator': {'file_page_index': page_index, 'printed_page': None,
                                          'bounding_box': [line['x0'], line['top'], line['x1'], line['bottom']],
                                          'coordinate_system': 'pdf_points_top_left', 'reading_order': order,
                                          'start_offset': 0, 'end_offset': len(text), 'extraction_method': 'pdfplumber_text_layer',
                                          'language': 'und'}, 'structured': {'numeric_review_status': 'pending', 'ocr_used': False,
                                          'table_overlap_indices': table_indices}})
            for index, table in enumerate(tables):
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
        parser_version = 'pdfplumber-layout-1.4.1'
        try:
            metadata, spans = parse_pdf(raw)
        except PDFParserUnavailable as exc:
            metadata, spans = {'parse_quality': 'parser_unavailable'}, []
            rights['index_allowed'] = False
            reason = str(exc)
        if not spans:
            rights['index_allowed'] = False
    else:
        parser_version = PARSER_VERSION
        metadata, spans, document_rights = parse_jats(raw)
        status, conflicts = identity_check(source, metadata)
        metadata['embedded_rights'] = document_rights
    metadata['identity_review'] = identity_review
    metadata['identity_conflicts'] = conflicts
    version = workbench.lib.record_version(source_id, raw, 'fulltext', receipt, metadata, rights, status, spans, parser_version)
    workbench.lib.log(source_id, 'authorized_document_import', {'version_id': version, 'parser_version': parser_version, 'span_count': len(spans), 'reason': reason})
    return {'version_id': version, 'span_count': len(spans), 'identity_status': status,
            'status': 'parsed_pending_claim_review' if spans and status == 'matched' else 'pending_parser_or_identity_review', 'reason': reason}


def import_chapter(workbench, source_id, path, *, edition_id, chapter_id, page_indices,
                   expected_page_indices, license_id, rights_evidence_url, authorized_by,
                   identity_review, printed_page_labels=None, missing_footnote_ids=None):
    """Import an authorized chapter with explicit edition/page and gap accounting."""
    from .store import digest, dumps
    source = workbench.lib.source(source_id)
    manifest = source["manifest"]
    if manifest.get("edition_id") != edition_id:
        raise ValueError("chapter edition differs from exact source manifestation")
    if not page_indices or not expected_page_indices or not set(page_indices) <= set(expected_page_indices):
        raise ValueError("explicit selected and expected chapter pages required")
    if not license_id or not rights_evidence_url or not authorized_by or identity_review.get("decision") != "matched" or not identity_review.get("reviewer") or not identity_review.get("rationale"):
        raise ValueError("authorized copy and exact edition identity review required")
    raw = Path(path).read_bytes()
    metadata, parsed = parse_pdf(raw)
    if any(i < 0 or i >= metadata["page_count"] for i in page_indices):
        raise ValueError("chapter page out of bounds")
    missing = sorted(set(expected_page_indices) - set(page_indices))
    spans = []
    for span in parsed:
        page = span["locator"]["file_page_index"]
        if page not in page_indices:
            continue
        span["section_path"] = f"Chapter {chapter_id}"
        span["locator"].update(edition_id=edition_id, chapter_id=chapter_id,
            printed_page_label=(printed_page_labels or {}).get(str(page)), original_language=manifest.get("language", "und"))
        if span["kind"] == "table" or span["structured"].get("table_overlap_indices"):
            span["structured"].update(missing_pages=missing, missing_footnotes=missing_footnote_ids or [])
        spans.append(span)
    rights = {"status": "explicit_authorized_chapter", "license_id": license_id, "evidence_url": rights_evidence_url,
              "authorized_by": authorized_by, "index_allowed": True, "redistribution_allowed": False,
              "rights_scope": {"edition_id": edition_id, "chapter_id": chapter_id, "page_indices": page_indices}}
    metadata.update(edition_id=edition_id, chapter_id=chapter_id, missing_pages=missing, identity_review=identity_review,
                    completeness="partial_chapter" if missing else "chapter_pages_present")
    config = digest(dumps({"edition": edition_id, "chapter": chapter_id, "pages": page_indices}).encode())[:12]
    version = workbench.lib.record_version(source_id, raw, "fulltext", {"url": "authorized-local-chapter", "retrieved_at": now()},
        metadata, rights, "matched", spans, "pdf-chapter-1.4.1-" + config)
    coverage = {"status": "partial_chapter" if missing else "chapter_parsed_pending_claim_review", "missing_pages": missing,
                "span_ids": [version + f":s{i:05d}" for i in range(len(spans))], "table_review": "pending", "missing_footnote_ids": missing_footnote_ids or []}
    with workbench.lib.sources:
        workbench.lib.sources.execute("INSERT OR REPLACE INTO chapter_coverage VALUES(?,?,?,?)", (source["source_id"], edition_id, chapter_id, dumps(coverage)))
    return {"version_id": version, **coverage, "claim_approval_granted": False}
