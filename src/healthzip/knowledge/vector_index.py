"""Incremental, model-isolated vectors inside SourceLibrary; no copied source prose."""
from __future__ import annotations

import array
import json
import math
import sys
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from .model_services import ModelUnavailable
from .store import digest, dumps, now
from .transactions import atomic


def ensure_schema(w):
    conn = w.lib.sources
    statements = [
        """CREATE TABLE IF NOT EXISTS retrieval_parent_section(
          parent_id TEXT PRIMARY KEY,version_id TEXT NOT NULL,section_path TEXT NOT NULL,
          locator_json TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS retrieval_unit(
          span_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,domains_json TEXT NOT NULL,
          assignment_status TEXT NOT NULL,created_at TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS retrieval_unit_parent ON retrieval_unit(parent_id)",
        """CREATE TABLE IF NOT EXISTS retrieval_unit_domain_review(
          span_id TEXT NOT NULL,review_id TEXT NOT NULL,domains_json TEXT NOT NULL,
          payload_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(span_id,review_id))""",
        """CREATE TABLE IF NOT EXISTS retrieval_vector(
          model_key TEXT NOT NULL,input_hash TEXT NOT NULL,purpose TEXT NOT NULL,
          dimension INTEGER NOT NULL,vector BLOB NOT NULL,model_json TEXT NOT NULL,
          created_at TEXT NOT NULL,PRIMARY KEY(model_key,input_hash,purpose))""",
        """CREATE TABLE IF NOT EXISTS retrieval_model_dimension(
          model_key TEXT PRIMARY KEY,dimension INTEGER NOT NULL)""",
    ]
    conn.execute("SAVEPOINT retrieval_v15")
    try:
        for statement in statements:
            conn.execute(statement)
        conn.execute("RELEASE retrieval_v15")
    except BaseException:
        conn.execute("ROLLBACK TO retrieval_v15")
        conn.execute("RELEASE retrieval_v15")
        raise


def register_spans(w, version_id, domains, *, assignment_status="provisional"):
    from .domains import DOMAIN_IDS
    if not set(domains) <= DOMAIN_IDS or not domains or assignment_status not in {"provisional", "content_checked"}:
        raise ValueError("invalid_retrieval_domains")
    ensure_schema(w)
    rows = list(w.lib.sources.execute("SELECT * FROM span WHERE version_id=? ORDER BY span_id", (version_id,)))
    with atomic(w.lib.sources):
        for row in rows:
            parent_id = digest(dumps([version_id, row["section_path"]]).encode())
            w.lib.sources.execute("INSERT OR IGNORE INTO retrieval_parent_section VALUES(?,?,?,?)",
                (parent_id, version_id, row["section_path"], row["locator_json"]))
            values = (parent_id, dumps(sorted(set(domains))), assignment_status)
            old = w.lib.sources.execute("SELECT parent_id,domains_json,assignment_status FROM retrieval_unit WHERE span_id=?", (row["span_id"],)).fetchone()
            if old and tuple(old) != values:
                raise ValueError("immutable_retrieval_unit_assignment")
            w.lib.sources.execute("INSERT OR IGNORE INTO retrieval_unit VALUES(?,?,?,?,?)", (row["span_id"], *values, now()))
    return len(rows)


def current_units(w, requested_domains=None):
    """Materialize IDs before per-span reads, releasing the SQLite read cursor.

    SQL removes superseded parses and irrelevant domains; existing eligibility
    still decides current source state, identity and exact component rights.
    """
    from .domains import DOMAIN_IDS
    parameters, scope = [], ''
    if requested_domains is not None:
        if not requested_domains or not set(requested_domains) <= DOMAIN_IDS:
            raise ValueError('known_retrieval_domains_required')
        ordered = sorted(set(requested_domains))
        clauses = ' OR '.join('instr(u.domains_json,?)>0' for _ in ordered)
        checked = ' OR '.join('instr(r.domains_json,?)>0' for _ in ordered)
        scope = f' AND (({clauses}) OR EXISTS(SELECT 1 FROM retrieval_unit_domain_review r WHERE r.span_id=u.span_id AND ({checked})))'
        parameters = [dumps(d) for d in ordered] * 2
    return list(w.lib.sources.execute("""SELECT u.* FROM retrieval_unit u
        JOIN span s ON s.span_id=u.span_id JOIN version v ON v.version_id=s.version_id
        WHERE v.material_type='fulltext' AND NOT EXISTS(
          SELECT 1 FROM parse_supersession p WHERE p.old_version_id=v.version_id)"""
        + scope + ' ORDER BY u.span_id', parameters))


def prefiltered_version_groups(w):
    return [dict(r) for r in w.lib.sources.execute("""SELECT s.version_id AS source_version,
        COUNT(*) AS excluded_unit_count,
        CASE WHEN v.material_type!='fulltext' THEN 'insufficient_material_depth'
             ELSE 'parser_superseded_requires_explicit_claim_review' END AS reason
        FROM retrieval_unit u JOIN span s ON s.span_id=u.span_id
        JOIN version v ON v.version_id=s.version_id
        WHERE v.material_type!='fulltext' OR EXISTS(
          SELECT 1 FROM parse_supersession p WHERE p.old_version_id=v.version_id)
        GROUP BY s.version_id ORDER BY s.version_id""")]


def review_unit_domains(w, span_ids, domains, review):
    """Append an exact-span routing review, preserving original provisional tags."""
    from .core import _review
    from .domains import DOMAIN_IDS
    _review(review)
    if not span_ids or not domains or not set(domains) <= DOMAIN_IDS:
        raise ValueError("exact_span_domain_review_required")
    if review["reviewer_kind"] == "synthetic_fixture" and w.environment_kind != "synthetic_test":
        raise ValueError("synthetic_domain_review_not_production_authority")
    ensure_schema(w)
    payload = {"review": review, "domains": sorted(set(domains)), "scientific_approval_granted": False}
    identity = digest(dumps(payload).encode())
    with atomic(w.lib.sources) as conn:
        for sid in span_ids:
            span = w.lib.span(sid, include_metadata=False)
            if not span or not w.lib.eligible(span, "fulltext")[0]:
                raise ValueError("domain_review_requires_current_eligible_span")
            if not conn.execute("SELECT 1 FROM retrieval_unit WHERE span_id=?", (sid,)).fetchone():
                raise ValueError("register_unit_before_domain_review")
            old = conn.execute("SELECT domains_json FROM retrieval_unit_domain_review WHERE span_id=?", (sid,)).fetchone()
            if old and json.loads(old[0]) != sorted(set(domains)):
                raise ValueError("domain_review_conflict_requires_explicit_new_index_version")
            conn.execute("INSERT OR IGNORE INTO retrieval_unit_domain_review VALUES(?,?,?,?,?)",
                         (sid, identity, dumps(payload["domains"]), dumps(payload), now()))
    return {"review_id": identity, "span_count": len(set(span_ids)), "scientific_approval_granted": False}


def unit_assignment(w, row):
    checked = w.lib.sources.execute(
        "SELECT domains_json,review_id FROM retrieval_unit_domain_review WHERE span_id=? ORDER BY review_id LIMIT 1",
        (row['span_id'],)).fetchone()
    if checked:
        return {"domains": json.loads(checked[0]), "status": "content_checked", "review_id": checked[1]}
    return {"domains": json.loads(row['domains_json']), "status": row['assignment_status'], "review_id": None}


def _pack(vector):
    if (not vector or len(vector) > 65536 or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector)
            or not math.isclose(sum(v*v for v in vector), 1.0, abs_tol=0.0001)):
        raise ModelUnavailable("cache_vector_not_finite_normalized")
    values = array.array("f", vector)
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def _unpack(raw):
    values = array.array("f")
    try:
        values.frombytes(raw)
    except (ValueError, TypeError):
        raise ModelUnavailable("cached_vector_encoding_invalid") from None
    if sys.byteorder != "little":
        values.byteswap()
    return list(values)


def cached(w, provider, text, purpose):
    row = w.lib.sources.execute("SELECT dimension,vector FROM retrieval_vector WHERE model_key=? AND input_hash=? AND purpose=?",
        (provider.config.model_key, digest(text.encode()), purpose)).fetchone()
    if not row:
        return None
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None:
        try:
            vector = np.frombuffer(row['vector'], dtype='<f4')
            valid = (len(vector) == row['dimension'] and bool(np.isfinite(vector).all())
                     and math.isclose(float(np.dot(vector, vector)), 1., abs_tol=.0001))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ModelUnavailable('cached_vector_encoding_or_normalization_invalid')
        return vector
    vector = _unpack(row["vector"])
    if len(vector) != row["dimension"]:
        raise ModelUnavailable("cached_vector_dimension_invalid")
    _pack(vector)
    return vector


def save_vectors(w, provider, texts, vectors, purpose):
    if not texts or len(texts) != len(vectors) or len({len(v) for v in vectors}) != 1:
        raise ModelUnavailable("cache_batch_dimension_mismatch")
    dimension = len(vectors[0])
    blobs = [_pack(v) for v in vectors]
    conn = w.lib.sources
    with atomic(conn):
        old = conn.execute("SELECT dimension FROM retrieval_model_dimension WHERE model_key=?", (provider.config.model_key,)).fetchone()
        if old and old[0] != dimension:
            raise ModelUnavailable("model_dimension_changed_requires_new_model_version")
        conn.execute("INSERT OR IGNORE INTO retrieval_model_dimension VALUES(?,?)", (provider.config.model_key, dimension))
        for text, blob in zip(texts, blobs):
            conn.execute("INSERT OR IGNORE INTO retrieval_vector VALUES(?,?,?,?,?,?,?)",
                (provider.config.model_key, digest(text.encode()), purpose, dimension, blob, dumps(provider.config.identity), now()))


def build_vectors(w, provider, *, batch_size=8, max_documents=None, version_ids=None, progress=None, workers=1):
    """Only explicit indexing embeds documents; ordinary queries never rebuild the corpus."""
    if not 1 <= batch_size <= 16:
        raise ValueError("invalid_embedding_batch")
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError("embedding_workers_must_be_1_to_4")
    if max_documents is not None and (type(max_documents) is not int or max_documents < 1):
        raise ValueError('positive_indexing_document_budget_required')
    ensure_schema(w)
    pending, excluded, reused, failures, token_admissions = {}, [], 0, [], []
    for row in current_units(w):
        span = w.lib.span(row['span_id'], include_metadata=False)
        if span and version_ids is not None and span['version_id'] not in version_ids:
            continue
        if not span or not w.lib.eligible(span, "fulltext")[0]:
            excluded.append({"span_id": row['span_id'], "reason": "ineligible_current_source"})
            continue
        if not span["text"].strip():
            excluded.append({"span_id": row['span_id'], "reason": "empty_structured_unit"})
            continue
        if cached(w, provider, span["text"], "document") is not None:
            reused += 1
            continue
        try:
            admission = provider.input_admission(span["text"])
        except ModelUnavailable as exc:
            failures.append({"span_id": row['span_id'], "stage": "input_admission", "error": str(exc)})
            continue
        if not admission['admitted']:
            excluded.append({"span_id": row['span_id'], "reason": admission['reason']})
            continue
        if admission['method'] == 'same_service_exact_tokens':
            token_admissions.append({"span_id": row['span_id'], "input_hash": span['text_hash'], **admission})
        pending[span["text_hash"]] = span["text"]
    texts = list(pending.values())
    deferred = max(0, len(texts) - max_documents) if max_documents is not None else 0
    if max_documents is not None:
        texts = texts[:max_documents]
    generated = 0
    starts = iter(range(0, len(texts), batch_size))
    # Only model requests run concurrently. SQLite reads, writes, and progress
    # callbacks stay on the caller thread, with at most `workers` live batches.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending_batches = deque()

        def submit_next():
            start = next(starts, None)
            if start is not None:
                batch = texts[start:start+batch_size]
                pending_batches.append((start, batch, pool.submit(provider.embed_documents, batch)))

        for _ in range(workers):
            submit_next()
        while pending_batches:
            start, batch, future = pending_batches.popleft()
            try:
                vectors = future.result()
                save_vectors(w, provider, batch, vectors, "document")
                generated += len(batch)
                if progress:
                    progress(generated, len(texts))
            except ModelUnavailable as exc:
                failures.append({"batch_start": start, "error": str(exc)})
                for _, _, queued in pending_batches:
                    queued.cancel()
                break  # Retain committed batches; resumption reuses them.
            submit_next()
    return {"model": provider.config.identity, "generated": generated, "reused_span_vectors": reused,
            "pending_unique_contents": len(texts)-generated, "failures": failures, "excluded": excluded,
            "deferred_by_explicit_budget": deferred, "index_scope_version_ids": sorted(version_ids) if version_ids is not None else 'all_registered_units',
            "prefiltered_versions": prefiltered_version_groups(w),
            "request_workers": workers,
            "whole_unit_token_admissions": token_admissions,
            "input_admission": {"conservative_byte_limit": 3500,
                "tokenizer_endpoint": provider.config.tokenizer_endpoint,
                "context_window_tokens": provider.config.context_window_tokens,
                "source_text_truncated": False},
            "raw_sources_modified": False, "retrieval_degraded": bool(failures)}
