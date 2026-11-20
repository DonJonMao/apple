"""Committed knowledge inputs, independent of audit writes and WAL checkpoints.

These tokens describe source/review/index authority. They never contain source
prose or personal context and can be read without opening a writable library.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from .transactions import atomic

VERSION = "knowledge-authority-revision-1"
TABLES = {
    "sources": (
        "source", "alias", "version", "span", "source_review",
        "source_version_clearance", "scientific_notice", "parse_supersession",
        "index_release", "chapter_coverage", "retrieval_parent_section",
        "retrieval_unit", "retrieval_unit_domain_review", "retrieval_projection_set",
        "retrieval_vector", "retrieval_model_dimension",
    ),
    "theories": (
        "theory", "theory_review", "theory_lifecycle", "theory_release",
        "source_claim", "application_rule", "core_lifecycle", "core_release",
        "knowledge_domain_assignment", "knowledge_evidence_edge",
    ),
}
_META = "knowledge_authority_revision"
_PREFIX = "knowledge_authority_"


def _schema(conn, kind):
    names = TABLES[kind]
    rows = conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' "
                        "AND name IN (" + ",".join("?" for _ in names) + ") ORDER BY name", names).fetchall()
    schema = [(row[0], row[1]) for row in rows]
    return schema, hashlib.sha256(json.dumps(schema, ensure_ascii=False).encode()).hexdigest()


def _trigger_sql(table, operation):
    condition = ""
    # Query embeddings are reusable outputs. Document index changes affect
    # future retrieval; a query cache fill cannot invalidate its own answer.
    if table == "retrieval_vector":
        refs = ("OLD", "NEW") if operation == "UPDATE" else ("OLD" if operation == "DELETE" else "NEW",)
        condition = " WHEN " + " OR ".join(f"{ref}.purpose='document'" for ref in refs)
    elif table == "retrieval_model_dimension" and operation == "INSERT":
        condition = " WHEN EXISTS(SELECT 1 FROM retrieval_vector WHERE model_key=NEW.model_key AND purpose='document')"
    name = _PREFIX + table + "_" + operation.lower()
    sql = (f'CREATE TRIGGER IF NOT EXISTS "{name}" AFTER {operation} ON "{table}"'
           + condition + f" BEGIN UPDATE {_META} SET revision=revision+1 WHERE singleton=1; END")
    return name, sql


def ensure_authority_revision(conn, kind):
    """Install/update tracking within the caller's transaction, once per schema.

    Schema-specific initializers call this after adding their tables. The fast
    path reads only metadata and never takes a write transaction.
    """
    schema, fingerprint = _schema(conn, kind)
    expected = {_trigger_sql(table, op)[0] for table, _ in schema
                for op in ("INSERT", "UPDATE", "DELETE")}
    present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE ?",
                                            (_PREFIX + "%",))}
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_META,)).fetchone()
    row = conn.execute(f"SELECT tracking_version,schema_fingerprint FROM {_META} WHERE singleton=1").fetchone() if exists else None
    if row and tuple(row) == (VERSION, fingerprint) and expected <= present:
        return
    with atomic(conn):
        conn.execute(f"CREATE TABLE IF NOT EXISTS {_META}("
                     "singleton INTEGER PRIMARY KEY CHECK(singleton=1),database_id TEXT NOT NULL,"
                     "revision INTEGER NOT NULL,tracking_version TEXT NOT NULL,schema_fingerprint TEXT NOT NULL)")
        conn.execute(f"INSERT OR IGNORE INTO {_META} VALUES(1,?,0,?,?)", (uuid4().hex, VERSION, ""))
        for table, _ in schema:
            for operation in ("INSERT", "UPDATE", "DELETE"):
                conn.execute(_trigger_sql(table, operation)[1])
        conn.execute(f"UPDATE {_META} SET revision=revision+1,tracking_version=?,schema_fingerprint=? WHERE singleton=1",
                     (VERSION, fingerprint))


def ensure_knowledge_revisions(workbench):
    ensure_authority_revision(workbench.lib.sources, "sources")
    ensure_authority_revision(workbench.lib.theories, "theories")


def prepare_retrieval_revisions(workbench):
    """Finish this task's lazy retrieval schema before freezing its input token.

    Ordinary Workbench construction leaves these schemas lazy so existing
    import/index callers keep their outer transaction's rollback semantics.
    """
    from . import domains, vector_index
    domains.ensure_schema(workbench)
    vector_index.ensure_schema(workbench)
    ensure_knowledge_revisions(workbench)


def knowledge_authority_clock(root):
    """Cheap read-only token; audit/schema-log changes and checkpoints are inert.

    Uninitialized libraries are not modified here. The worker's Workbench
    installs tracking before checking its input token or retrieving evidence.
    """
    root = Path(root).resolve()
    result = [VERSION, str(root)]
    for kind in TABLES:
        path = root / (kind + ".sqlite3")
        try:
            stat = path.stat()
        except FileNotFoundError:
            result.append((kind, "missing"))
            continue
        file_id = (stat.st_dev, stat.st_ino)
        try:
            conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.25)
            try:
                _, fingerprint = _schema(conn, kind)
                exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_META,)).fetchone()
                row = conn.execute(f"SELECT database_id,revision,tracking_version,schema_fingerprint FROM {_META} WHERE singleton=1").fetchone() if exists else None
                trigger_names = tuple(r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE ? ORDER BY name", (_PREFIX + "%",)))
                triggers = hashlib.sha256(json.dumps(trigger_names).encode()).hexdigest()
                result.append((kind, file_id, tuple(row) if row else "uninitialized", fingerprint, triggers))
            finally:
                conn.close()
        except sqlite3.Error:
            # A temporarily unreadable store cannot validate an existing answer.
            result.append((kind, file_id, "unavailable"))
    return result
