"""Page/paragraph/outline PDF extraction; never fixed-character textbook slicing.

Layout and table extraction are proposals, not scientific or numerical review.
Unresolved cells, OCR and printed-page labels stay explicitly unresolved.
"""
from __future__ import annotations

import io
import re
from collections import Counter
from statistics import median

from .documents import PDFParserUnavailable

PARSER_VERSION = "pdf-structure-1.5.1"
_THIRD_PARTY = re.compile(r"reproduced (?:with|from)|used (?:with|by) permission|all rights reserved|photo(?:graph)? credit|image credit", re.I)
_CAPTION = re.compile(r"^(?:figure|fig\.|table|equation)\s*[\dIVX]", re.I)


def _box(items):
    return [min(i['x0'] for i in items), min(i['top'] for i in items),
            max(i['x1'] for i in items), max(i['bottom'] for i in items)]


def _lines(page):
    """Respect text-flow order and column resets, then group by geometric lines."""
    words = page.extract_words(use_text_flow=True, extra_attrs=['size', 'fontname'])
    lines, current = [], []
    for word in words:
        if current and (word['top'] > max(w['bottom'] for w in current)-2 or word['bottom'] < min(w['top'] for w in current)+2 or word['x0'] < current[-1]['x0'] - 2
                        or word['x0'] - current[-1]['x1'] > 40):
            lines.append(current)
            current = []
        current.append(word)
    if current:
        lines.append(current)
    return [{'text': ' '.join(w['text'] for w in group), 'x0': _box(group)[0], 'top': _box(group)[1],
             'x1': _box(group)[2], 'bottom': _box(group)[3],
             'size': median(w['size'] for w in group),
             'bold': sum(len(w['text']) for w in group if 'bold' in w['fontname'].lower()) > .75*sum(len(w['text']) for w in group)} for group in lines]


def _outline(document):
    page_ids = {p.page_obj.pageid: i for i, p in enumerate(document.pages)}
    result = {}
    try:
        for level, title, dest, action, _ in document.doc.get_outlines():
            if dest is None and action:
                dest = action.get('D')
            if isinstance(dest, (str, bytes)):
                dest = document.doc.get_dest(dest)
                if isinstance(dest, dict):
                    dest = dest.get('D')
            if not isinstance(dest, (list, tuple)) or not dest:
                continue
            pid = getattr(dest[0], 'objid', None)
            if pid in page_ids:
                result.setdefault(page_ids[pid], []).append((level, str(title)))
    except (KeyError, TypeError, AttributeError, ValueError):
        pass
    # PDFNoOutlines is a PDFException (not ValueError); handled by caller.
    return result


def parse_structured_pdf(raw, *, progress=None):
    try:
        import pdfplumber
        from pdfminer.pdfdocument import PDFNoOutlines
    except ImportError as exc:
        raise PDFParserUnavailable("Install optional dependency: pip install -e '.[knowledge-pdf]'") from exc
    if not isinstance(raw, bytes) or not raw.startswith(b'%PDF') or len(raw) > 300_000_000:
        raise ValueError('pdf_format_or_size_limit')
    spans, page_reports, section = [], [], []
    with pdfplumber.open(io.BytesIO(raw), unicode_norm='NFKC') as doc:
        if len(doc.pages) > 5000:
            raise ValueError('pdf_page_limit')
        try:
            outline = _outline(doc)
        except PDFNoOutlines:
            outline = {}
        for page_index, page in enumerate(doc.pages):
            for level, title in outline.get(page_index, []):
                section = section[:max(0, level-1)] + [title]
            lines = _lines(page)
            sizes = Counter(round(line['size'], 1) for line in lines if len(line['text']) > 30)
            body_size = sizes.most_common(1)[0][0] if sizes else 12
            gaps = [b['top']-a['bottom'] for a,b in zip(lines,lines[1:])
                    if 0 < b['top']-a['bottom'] < body_size*2 and abs(b['x0']-a['x0']) < 30]
            paragraph_gap = max(3, median(gaps)*1.65+1) if gaps else body_size*.7
            # Ruling-line tables only. Borderless/multi-page tables remain pending.
            tables = page.find_tables() if len(page.edges) >= 4 else []
            tables = [t for t in tables if len(t.rows) > 1 and len(t.columns) > 1]
            units, current = [], []

            def flush():
                if not current:
                    return
                text = '\n'.join(line['text'] for line in current)
                box = _box(current)
                heading = (len(current) <= 2 and len(text) < 180 and
                           (current[0]['size'] >= body_size * 1.3 or (current[0]['bold'] and len(text)<90)))
                kind = 'heading' if heading else 'caption' if _CAPTION.match(text) else 'formula_context' if re.search(r'[=∑∫√]|VO[₂2]|\be1RM\b', text) else 'paragraph'
                units.append({'kind': kind, 'text': text, 'box': box, 'table_overlap_indices': sorted({i for line in current for i, t in enumerate(tables)
                    if line['x0'] < t.bbox[2] and line['x1'] > t.bbox[0] and line['top'] < t.bbox[3] and line['bottom'] > t.bbox[1]})})
                current.clear()

            for line in lines:
                if current and (line['top'] < current[-1]['top'] - 3
                    or line['top'] - current[-1]['bottom'] > paragraph_gap
                    or line['x0']-current[-1]['x0'] > max(10,body_size) or current[-1]['x0']-line['x0'] > 80
                    or abs(line['size'] - current[-1]['size']) > 1
                    or re.match(r'^(?:[•▪●]|\d+[.)])\s', line['text'])):
                    flush()
                current.append(line)
            flush()
            # Keep the original table rows/cells and their surrounding prose together.
            for table_index, table in enumerate(tables):
                rows = table.extract()
                before = [u['text'] for u in units if u['box'][3] <= table.bbox[1]]
                after = [u['text'] for u in units if u['box'][1] >= table.bbox[3]]
                context = {'before': before[-1] if before else None, 'after': after[0] if after else None}
                table_text = '\n'.join(' | '.join(c or '' for c in row) for row in rows)
                units.append({'kind': 'table', 'text': '\n'.join(t for t in [context['before'], table_text, context['after']] if t),
                    'box': list(table.bbox), 'table_index': table_index,
                    'cells': [{'row': r, 'column': c, 'text': value} for r, row in enumerate(rows) for c, value in enumerate(row)],
                    'cell_boxes': [list(b) if b else None for b in table.cells], 'context': context})
            margin_lines = [line['text'] for line in lines if line['top'] < page.height*.06 or line['bottom'] > page.height*.94]
            labels = [t for t in margin_lines if re.fullmatch(r'(?:[ivxlcdm]+|\d+|\d+-\d+)', t.strip(), re.I)]
            label = labels[-1] if labels else None
            page_text = '\n'.join(line['text'] for line in lines)
            page_start = len(spans)
            inferred_heading = None
            for order, unit in enumerate(units):
                if not unit['text'].strip():
                    continue
                if unit.get('table_overlap_indices'):
                    continue  # Cells travel with their table and surrounding context.
                if unit['kind'] == 'heading':
                    inferred_heading = unit['text']
                section_status = 'pdf_outline' if section else 'page_fallback_heading_unverified'
                structured = {key: value for key, value in unit.items() if key not in {'text', 'box', 'kind'}}
                structured.update(numeric_review_status='pending', ocr_used=False,
                    section_path_status=section_status, formula_semantics_verified=False)
                if unit['kind'] in {'caption', 'formula_context'}:
                    structured['context_before'] = units[order-1]['text'] if order else None
                    structured['context_after'] = units[order+1]['text'] if order+1 < len(units) else None
                text = unit['text']
                if unit['kind'] == 'formula_context':
                    text = '\n'.join(t for t in [structured['context_before'], text, structured['context_after']] if t)
                third_party = bool(_THIRD_PARTY.search(unit['text'])) or unit['kind'] == 'caption'
                span = {'kind': unit['kind'], 'text': text,
                    'section_path': ' / '.join((section or [f'PDF page {page_index+1}'])
                        + ([inferred_heading] if inferred_heading else [])),
                    'locator': {'file_page_index': page_index, 'printed_page_label': label,
                        'printed_page_status': 'margin_candidate_unverified' if label else 'unknown',
                        'bounding_box': unit['box'], 'coordinate_system': 'pdf_points_top_left',
                        'reading_order': order, 'extraction_method': PARSER_VERSION, 'language': 'en'},
                    'structured': structured}
                # Never infer third-party permission from the document's open license.
                if third_party:
                    span['rights'] = {'status': 'rights_pending_component_review', 'index_allowed': False,
                                      'redistribution_allowed': False, 'reason': 'third_party_or_caption_scope_unresolved'}
                spans.append(span)
            page_reports.append({'file_page_index': page_index, 'characters': len(page_text),
                'span_count': len(spans)-page_start, 'line_table_count': len(tables),
                'quality': 'no_text_layer_or_blank_page' if not page_text.strip() else 'text_layer_layout_not_manually_verified',
                'replacement_characters': page_text.count('\ufffd'),
                'complex_layout_review_required': bool(len(page.images) or tables),
                'future_chapter_marker': bool(re.search(r'future chapters?|chapter (?:is |to be )?forthcoming|not yet (?:available|written)', page_text, re.I))})
            page.close()  # Release cached chars/images for large textbooks.
            if progress:
                progress(page_index+1, len(doc.pages))
        metadata = {'pdf_metadata': doc.metadata, 'page_count': len(doc.pages),
            'parser_version': PARSER_VERSION, 'outline_page_count': len(outline), 'page_reports': page_reports,
            'parse_quality': 'text_layer_structured_pending_layout_review' if spans else 'no_text_layer_requires_authorized_ocr',
            'limitations': ['No OCR performed.', 'Printed page labels and heading layout are unverified.',
                'Borderless and multi-page tables and equation symbols require manual verification.',
                'Body-file completeness does not establish chapter-topic completeness.',
                'Captions and detected third-party notices remain rights_pending.']}
    return metadata, spans
