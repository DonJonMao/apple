"""Bounded local computed-result cache with explicit input revision identities."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import OrderedDict
from pathlib import Path
from threading import Event, RLock
from time import monotonic

_RESULTS = OrderedDict()
_LOCK = RLock()
_INFLIGHT = {}
_GENERATION = 0
CACHE_LIMIT = 16  # product memory budget, unrelated to scientific eligibility
CACHE_VERSION = "analysis-cache-v1.8.0"
WORKSPACE_CACHE_SECONDS = 300  # Safety expiry; committed relevant edits invalidate immediately.


def revision_identity(repo, knowledge_root=".local/knowledge", *, dependencies=None):
    if dependencies is not None:
        # Trigger-maintained tokens are shared by every importing process. Include
        # every historical type of a revised record, so a type correction also
        # invalidates the page from which the record disappeared.
        keys = {"schema_version", "repository_migration_revision", "temporal_query_projection"}
        for table, canonical in dependencies:
            keys.add("training_data_version" if table == "training" else f"source_domain:{table}:{canonical or '*'}")
        rows = dict(repo.conn.execute("SELECT key,value FROM schema_meta WHERE key IN ("
                                     + ",".join("?" for _ in keys) + ")", tuple(keys)))
        metadata = {key: rows.get(key, "0") for key in sorted(keys)}
    else:
        metadata = dict(repo.conn.execute("SELECT key,value FROM schema_meta"))
        metadata.setdefault("training_data_version", "0")
    root = Path(knowledge_root).resolve()
    authority = None
    if dependencies is None:
        from healthzip.knowledge.revisions import knowledge_authority_clock

        # Retrieval audit writes and WAL checkpoints are outputs, not scientific
        # inputs. Reviewed claims, revocations and document index edits are inputs.
        authority = knowledge_authority_clock(root)
    stat = repo.path.stat()
    return {"repository": str(repo.path.resolve()), "inode": stat.st_ino,
            "metadata": metadata, "knowledge_root": str(root), "knowledge_authority": authority,
            "cache_version": CACHE_VERSION}


def cached(repo, namespace, arguments, compute, *, max_age_seconds=None, dependencies=None,
           knowledge_root=".local/knowledge"):
    """Isolated bounded results, revision validation and same-key single flight.

    A caller's uncommitted state never enters the process cache. Connections are
    used only by their owning thread; waiters compute with their own connection.
    """
    if repo.conn.in_transaction:
        return compute()
    revision = revision_identity(repo, knowledge_root, dependencies=dependencies)
    identity = {"revision": revision, "namespace": namespace, "arguments": arguments}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
    while True:
        with _LOCK:
            if key in _RESULTS:
                created, result = _RESULTS[key]
                if max_age_seconds is None or monotonic() - created < max_age_seconds:
                    _RESULTS.move_to_end(key)
                    return copy.deepcopy(result)
                del _RESULTS[key]
            pending = _INFLIGHT.get(key)
            if pending is None:
                pending = _INFLIGHT[key] = Event()
                generation = _GENERATION
                break
        pending.wait()
        if revision_identity(repo, knowledge_root, dependencies=dependencies) != revision:
            return cached(repo, namespace, arguments, compute, max_age_seconds=max_age_seconds,
                          dependencies=dependencies, knowledge_root=knowledge_root)
    try:
        value = compute()
        if not repo.conn.in_transaction and revision_identity(repo, knowledge_root, dependencies=dependencies) == revision:
            with _LOCK:
                if generation == _GENERATION:
                    _RESULTS[key] = (monotonic(), copy.deepcopy(value))
                    _RESULTS.move_to_end(key)
                    while len(_RESULTS) > CACHE_LIMIT:
                        _RESULTS.popitem(last=False)
        return value
    finally:
        with _LOCK:
            _INFLIGHT.pop(key, None)
            pending.set()


def clear():
    global _GENERATION
    with _LOCK:
        _GENERATION += 1
        _RESULTS.clear()
