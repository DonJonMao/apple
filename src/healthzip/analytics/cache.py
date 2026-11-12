"""Bounded local computed-result cache with explicit input revision identities."""
from __future__ import annotations

import copy
import hashlib
import json
from collections import OrderedDict
from pathlib import Path
from threading import RLock

_RESULTS = OrderedDict()
_LOCK = RLock()
CACHE_LIMIT = 16  # product memory budget, unrelated to scientific eligibility
CACHE_VERSION = "analysis-cache-v1.4.2"


def revision_identity(repo, knowledge_root=".local/knowledge"):
    metadata = dict(repo.conn.execute("SELECT key,value FROM schema_meta"))
    metadata.setdefault("training_data_version", "0")
    files = []
    root = Path(knowledge_root).resolve()
    for pattern in ("*.sqlite3", "*.sqlite3-wal"):
        for path in sorted(root.glob(pattern)):
            stat = path.stat()
            files.append((path.name, stat.st_ino, stat.st_size, stat.st_mtime_ns))
    stat = repo.path.stat()
    return {"repository": str(repo.path.resolve()), "inode": stat.st_ino,
            "metadata": metadata, "knowledge_root": str(root), "knowledge_files": files,
            "cache_version": CACHE_VERSION}


def cached(repo, namespace, arguments, compute):
    """Return a copy so a UI cannot mutate another caller's frozen result."""
    identity = {"revision": revision_identity(repo), "namespace": namespace, "arguments": arguments}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
    with _LOCK:
        if key in _RESULTS:
            _RESULTS.move_to_end(key)
            return copy.deepcopy(_RESULTS[key])
    value = compute()
    with _LOCK:
        _RESULTS[key] = copy.deepcopy(value)
        _RESULTS.move_to_end(key)
        while len(_RESULTS) > CACHE_LIMIT:
            _RESULTS.popitem(last=False)
    return value


def clear():
    with _LOCK:
        _RESULTS.clear()
