"""Immutable JATS row-group search projections; the original Span remains evidence.

These are index inputs, never new Source/Span/Claim identities. Structural paths
resolve against the exact owned raw_xml snapshot, alongside its original locator.
No column semantics are inferred across sibling tables or row groups.
"""
from __future__ import annotations

import json

from lxml import etree

from .store import digest, dumps, now
from .transactions import atomic

VERSION = "jats-table-row-groups-1.5.0"


def _name(node):
    return etree.QName(node).localname if isinstance(node.tag, str) else ""


def _text(node):
    return " ".join(" ".join(node.itertext()).split())


def _path(node):
    parts = []
    while node.getparent() is not None:
        parent = node.getparent()
        parts.append(f"*[{list(parent).index(node) + 1}]")
        node = parent
    return "./" + "/".join(reversed(parts)) if parts else "."


def _extent(cell, key):
    raw = cell.get(key, "1")
    if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 10000:
        raise ValueError("table_projection_invalid_cell_extent")
    return int(raw)


def _grid(group):
    rows = [r for r in group if _name(r) == "tr"]
    if (len(rows) > 10000 or len(rows) != len(group)
            or group.text and group.text.strip() or any(r.tail and r.tail.strip() for r in rows)):
        raise ValueError("table_projection_unsupported_row_group")
    cells, occupied, boundaries = [], set(), []
    for r, row in enumerate(rows):
        column, current = 0, []
        for cell in row:
            if _name(cell) not in {"td", "th"}:
                raise ValueError("table_projection_unsupported_row_content")
            while (r, column) in occupied:
                column += 1
            height, width = _extent(cell, "rowspan"), _extent(cell, "colspan")
            if r + height > len(rows) or column + width > 512:
                raise ValueError("table_projection_cell_outside_row_group")
            if len(occupied) + height * width > 200000:
                raise ValueError("table_projection_excessive_grid")
            covered = {(i, j) for i in range(r, r + height) for j in range(column, column + width)}
            if occupied & covered:
                raise ValueError("table_projection_overlapping_cells")
            occupied.update(covered)
            current.append({"structured_subtree_xpath": _path(cell), "row": r,
                "column": column, "row_stop": r + height, "column_stop": column + width,
                "kind": _name(cell), "attributes": dict(cell.attrib), "text": _text(cell)})
            boundaries.append((r, r + height))
            column += width
        cells.append(current)
    if not rows or sum(map(len, cells)) > 50000:
        raise ValueError("table_projection_empty_or_excessive_row_group")
    return rows, cells, boundaries


def _render_row(row, cells):
    # Preserve explicit cell scopes, references and extents without guessing a grid's meaning.
    parts = []
    for cell in cells:
        attrs = " ".join(f"{key}={value}" for key, value in sorted(cell['attributes'].items()))
        parts.append(f"{cell['kind']} columns[{cell['column']}:{cell['column_stop']}] {attrs}: {cell['text']}")
    return f"Row {_path(row)} attributes {dumps(dict(row.attrib))}: " + " | ".join(parts)


def project(span):
    """Preserve all headers, captions/notes and minimal indivisible rowspan groups.

    Sibling header rows are explicitly labeled context, not inherited column names.
    Missing headers stay missing. Ambiguous/invalid layouts fail closed.
    """
    if span['kind'] != 'table':
        raise ValueError("table_projection_requires_jats_table")
    try:
        raw = json.loads(span['structured_json'])['raw_xml']
        if not isinstance(raw, str) or len(raw.encode()) > 20_000_000:
            raise ValueError
        root = etree.fromstring(raw.encode(), parser=etree.XMLParser(
            resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False))
    except (KeyError, TypeError, ValueError, etree.XMLSyntaxError):
        raise ValueError("table_projection_requires_readable_owned_xml") from None
    if (root.getroottree().docinfo.doctype or any(isinstance(n, etree._Entity) for n in root.iter())
            or _name(root) != 'table-wrap' or _text(root) != span['text']
            or digest(span['text'].encode()) != span['text_hash']):
        raise ValueError("table_projection_original_snapshot_mismatch")
    tables = [n for n in root if _name(n) == 'table']
    if (not tables or len(tables) > 128
            or len(root.xpath('.//*[local-name()="table"]')) != len(tables)):
        raise ValueError("table_projection_requires_flat_sibling_tables")
    context, headers, layouts, reference_rows, references = [], [], [], {}, set()
    if root.text and root.text.strip():
        context.append('Parent inline context: ' + root.text.strip())
    for node in root:
        if node not in tables and _text(node):
            context.append(f"Parent context {_path(node)} ({_name(node)}): {_text(node)}")
        if node.tail and node.tail.strip():
            context.append(f"Parent inline context after {_path(node)}: {node.tail.strip()}")
    for table in tables:
        if any(_name(n) not in {'thead', 'tbody', 'tfoot', 'col', 'colgroup', 'tr'} for n in table):
            raise ValueError("table_projection_unsupported_table_content")
        if any(_name(n) == 'tr' for n in table):
            raise ValueError("table_projection_explicit_row_groups_required")
        if table.text and table.text.strip() or any(n.tail and n.tail.strip() for n in table):
            raise ValueError("table_projection_unsupported_table_inline_content")
        if table.attrib:
            context.append(f"Table {_path(table)} attributes: {dumps(dict(table.attrib))}")
        bodies = []
        for group in table:
            if _name(group) in {'thead', 'tfoot', 'tbody'}:
                rows, cells, boundaries = _grid(group)
                for row, row_cells in zip(rows, cells):
                    for cell in row_cells:
                        if identity := cell['attributes'].get('id'):
                            if identity in reference_rows:
                                raise ValueError("table_projection_duplicate_cell_id")
                            reference_rows[identity] = (table, row, row_cells)
                        references.update(cell['attributes'].get('headers', '').split())
                if _name(group) == 'tbody':
                    bodies.append((group, rows, cells, boundaries))
                else:
                    label = 'Header' if _name(group) == 'thead' else 'Footer'
                    headers.extend(f"{label} context of table {_path(table)}: {_render_row(r, c)}"
                                   for r, c in zip(rows, cells))
        if not bodies:
            raise ValueError("table_projection_body_required")
        layouts.append((table, bodies))
    if references - set(reference_rows):
        raise ValueError("table_projection_unresolved_headers_reference")
    # Explicit HTML/JATS headers references may point outside the selected row group.
    # Preserve each complete referenced row with its own scope, including chained refs.
    seen_rows = set()
    for identity in sorted(references):
        table, row, cells = reference_rows[identity]
        if _path(row) not in seen_rows:
            headers.append(f"Explicit headers-reference context of table {_path(table)}: {_render_row(row, cells)}")
            seen_rows.add(_path(row))
    # All sibling headers remain separately located. We never infer that a section-only
    # header inherits the first table's column schema (common in continuation tables).
    common = ["Source table context; sibling headers retain their own table scope.", *context, *headers]
    children = []
    for table, bodies in layouts:
        for group, rows, cells, boundaries in bodies:
            start, context_rows = 0, []
            while start < len(rows):
                end, cursor = start + 1, start
                while cursor < end:
                    end = max([end, *(stop for begin, stop in boundaries if begin == cursor)])
                    cursor += 1
                preceding = [i for i in context_rows if i < start]
                selected = [*preceding, *range(start, end)]
                locator = {"coordinate_system": "owned_raw_xml_zero_based_half_open_grid",
                    "parent_locator": json.loads(span['locator_json']),
                    "table_xpath": _path(table), "row_group_xpath": _path(group),
                    "body_rows": [start, end], "preceding_structural_context_rows": preceding,
                    "cells": [{key: value for key, value in cell.items() if key != 'text'}
                              for i in selected for cell in cells[i]]}
                text = "\n".join([*common, f"Selected table {_path(table)} body {_path(group)} rows[{start}:{end}]",
                    f"Row group attributes: {dumps(dict(group.attrib))}",
                    *(_render_row(rows[i], cells[i]) for i in selected)])
                input_hash = digest(text.encode())
                child_id = digest(dumps([VERSION, span['span_id'], span['text_hash'], locator, input_hash]).encode())
                children.append({"child_id": child_id, "input_hash": input_hash, "locator": locator, "text": text})
                for i in range(start, end):
                    if cells[i] and (all(c['kind'] == 'th' for c in cells[i])
                                     or len(cells[i]) == 1 and cells[i][0]['column_stop'] > 1):
                        context_rows.append(i)
                start = end
    manifest = {"projection_version": VERSION, "parent_span_id": span['span_id'],
        "parent_text_hash": span['text_hash'], "parent_structure_hash": digest(span['structured_json'].encode()),
        "children": [{key: value for key, value in child.items() if key != 'text'} for child in children]}
    return {"projection_set_id": digest(dumps(manifest).encode()), "manifest": manifest, "children": children}


def register(w, projection):
    manifest = projection['manifest']
    values = (projection['projection_set_id'], manifest['parent_span_id'], manifest['parent_text_hash'],
              manifest['parent_structure_hash'], VERSION, dumps(manifest))
    with atomic(w.lib.sources) as conn:
        old = conn.execute("SELECT projection_set_id,span_id,parent_text_hash,parent_structure_hash,projection_version,manifest_json FROM retrieval_projection_set WHERE projection_set_id=?", (values[0],)).fetchone()
        if old and tuple(old) != values:
            raise ValueError("immutable_table_projection_conflict")
        conn.execute("INSERT OR IGNORE INTO retrieval_projection_set VALUES(?,?,?,?,?,?,?)", (*values, now()))


def current(w, span, *, allowed_id=None):
    """Read metadata only; query-time retrieval never constructs or embeds children."""
    rows = list(w.lib.sources.execute("""SELECT projection_set_id,manifest_json FROM retrieval_projection_set
        WHERE span_id=? AND parent_text_hash=? AND parent_structure_hash=? AND projection_version=?""",
        (span['span_id'], span['text_hash'], digest(span['structured_json'].encode()), VERSION)))
    if len(rows) > 1:
        raise ValueError("ambiguous_table_projection_set")
    if not rows or allowed_id is not None and rows[0]['projection_set_id'] != allowed_id:
        return None
    manifest = json.loads(rows[0]['manifest_json'])
    if (digest(dumps(manifest).encode()) != rows[0]['projection_set_id']
            or manifest['parent_span_id'] != span['span_id'] or manifest['parent_text_hash'] != span['text_hash']
            or manifest['parent_structure_hash'] != digest(span['structured_json'].encode())
            or manifest['projection_version'] != VERSION or not manifest['children']):
        raise ValueError("table_projection_manifest_integrity_invalid")
    return {"projection_set_id": rows[0]['projection_set_id'], **manifest}
