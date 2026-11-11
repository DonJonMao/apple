"""Independent SourceLibrary and TheoryLibrary, immutable content and review events."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS source (
 source_id TEXT PRIMARY KEY, canonical_identity TEXT UNIQUE NOT NULL, manifest_json TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'discovered', identity_status TEXT NOT NULL DEFAULT 'pending',
 updates_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alias (alias TEXT, source_id TEXT, PRIMARY KEY(alias,source_id));
CREATE TABLE IF NOT EXISTS version (
 version_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, material_type TEXT NOT NULL,
 sha256 TEXT NOT NULL, byte_length INTEGER NOT NULL, storage_uri TEXT NOT NULL,
 receipt_json TEXT NOT NULL, metadata_json TEXT NOT NULL, rights_json TEXT NOT NULL,
 parser_version TEXT NOT NULL, identity_status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS span (
 span_id TEXT PRIMARY KEY, version_id TEXT NOT NULL, kind TEXT NOT NULL, section_path TEXT,
 locator_json TEXT NOT NULL, text TEXT NOT NULL, text_hash TEXT NOT NULL,
 structured_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS span_version ON span(version_id);
CREATE TABLE IF NOT EXISTS acquisition_log (
 id INTEGER PRIMARY KEY, source_id TEXT, event TEXT NOT NULL, payload_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_review (
 id INTEGER PRIMARY KEY, source_id TEXT, version_id TEXT, reviewer TEXT NOT NULL,
 decision TEXT NOT NULL, rationale TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS index_release (
 release_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL, sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL
);
"""

THEORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS theory (
 theory_id TEXT NOT NULL, version TEXT NOT NULL, card_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft', review_json TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(theory_id,version)
);
CREATE TABLE IF NOT EXISTS theory_review (
 id INTEGER PRIMARY KEY, theory_id TEXT NOT NULL, version TEXT NOT NULL,
 decision TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS theory_release (
 release_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL, sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def identity(source: dict[str, Any]) -> str:
    if source.get("doi"):
        return "doi:" + source["doi"].lower().removeprefix("https://doi.org/")
    for key in ("pmid", "pmcid", "canonical_url"):
        if source.get(key):
            return key + ":" + str(source[key]).strip()
    raise ValueError("source has no stable identity")


class Libraries:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "blobs").mkdir(exist_ok=True)
        self.sources = sqlite3.connect(self.root / "sources.sqlite3")
        self.theories = sqlite3.connect(self.root / "theories.sqlite3")
        for db, schema in ((self.sources, SOURCE_SCHEMA), (self.theories, THEORY_SCHEMA)):
            db.row_factory = sqlite3.Row
            db.executescript(schema)
            db.commit()
        # Early local source libraries used raw hash as a unique parse identity. Preserve old
        # parses while allowing an explicit parser-version correction over the same raw bytes.
        sql = self.sources.execute("SELECT sql FROM sqlite_master WHERE name='version'").fetchone()[0]
        if "UNIQUE(source_id,material_type,sha256)" in sql:
            with self.sources:
                corrected = sql.replace("CREATE TABLE version", "CREATE TABLE version_parser_migration", 1)
                corrected = corrected.replace(",\n UNIQUE(source_id,material_type,sha256)", "")
                self.sources.execute(corrected)
                self.sources.execute("INSERT INTO version_parser_migration SELECT * FROM version")
                self.sources.execute("DROP TABLE version")
                self.sources.execute("ALTER TABLE version_parser_migration RENAME TO version")

    def close(self) -> None:
        self.sources.close()
        self.theories.close()

    def seed(self, manifest: dict, theories: dict) -> None:
        # Re-seeding cannot overwrite acquisition/review or turn draft seeds into active cards.
        with self.sources:
            for source in manifest["sources"]:
                key = identity(source)
                old = self.sources.execute(
                    "SELECT source_id FROM source WHERE canonical_identity=?", (key,)
                ).fetchone()
                canonical = old[0] if old else source["source_id"]
                self.sources.execute(
                    "INSERT OR IGNORE INTO source VALUES(?,?,?,'discovered','pending','{}',?)",
                    (canonical, key, dumps(source), now()),
                )
                self.sources.execute("INSERT OR IGNORE INTO alias VALUES(?,?)", (source["source_id"], canonical))
            for alias, source_ids in manifest.get("source_aliases", {}).items():
                for source_id in source_ids:
                    for canonical in self.resolve(source_id):
                        self.sources.execute("INSERT OR IGNORE INTO alias VALUES(?,?)", (alias, canonical))
        with self.theories:
            for card in theories["cards"]:
                self.theories.execute(
                    "INSERT OR IGNORE INTO theory VALUES(?,?,?,'draft','{}')",
                    (card["theory_id"], card["version"], dumps(card)),
                )

    def resolve(self, source_id: str) -> list[str]:
        return [r[0] for r in self.sources.execute("SELECT source_id FROM alias WHERE alias=? ORDER BY source_id", (source_id,))]

    def source(self, source_id: str) -> dict:
        ids = self.resolve(source_id)
        if len(ids) != 1:
            raise ValueError("one canonical source required; group aliases must be expanded")
        row = self.sources.execute("SELECT * FROM source WHERE source_id=?", (ids[0],)).fetchone()
        return {**dict(row), "manifest": json.loads(row["manifest_json"])}

    def log(self, source_id: str | None, event: str, payload: dict) -> None:
        with self.sources:
            self.sources.execute("INSERT INTO acquisition_log(source_id,event,payload_json,created_at) VALUES(?,?,?,?)", (source_id, event, dumps(payload), now()))

    def record_version(self, source_id: str, raw: bytes, material_type: str, receipt: dict,
                       metadata: dict, rights: dict, identity_status: str,
                       spans: list[dict] | None = None, parser_version: str = "jats-1.3.0") -> str:
        source_id = self.source(source_id)["source_id"]
        sha = digest(raw)
        version_id = f"{source_id}:{material_type}:{sha[:20]}"
        if parser_version != "jats-1.3.0":
            version_id += ":" + parser_version
        blob = self.root / "blobs" / sha
        if not blob.exists():
            blob.write_bytes(raw)
        with self.sources:
            self.sources.execute(
                "INSERT OR IGNORE INTO version VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (version_id, source_id, material_type, sha, len(raw), str(blob.relative_to(self.root)),
                 dumps(receipt), dumps(metadata), dumps(rights), parser_version, identity_status, now()),
            )
            for i, span in enumerate(spans or []):
                text = span["text"]
                self.sources.execute("INSERT OR IGNORE INTO span VALUES(?,?,?,?,?,?,?,?)", (
                    f"{version_id}:s{i:05d}", version_id, span.get("kind", "paragraph"),
                    span.get("section_path", ""), dumps(span.get("locator", {})), text,
                    digest(text.encode()), dumps(span.get("structured", {}))))
            self.sources.execute(
                "UPDATE source SET state=CASE WHEN state='withdrawn' THEN state ELSE 'acquired' END,identity_status=?,updated_at=? WHERE source_id=?",
                (identity_status, now(), source_id),
            )
        return version_id

    def span(self, span_id: str) -> dict | None:
        row = self.sources.execute("SELECT s.*,v.source_id,v.material_type,v.rights_json,v.identity_status,v.metadata_json,src.state source_state FROM span s JOIN version v ON v.version_id=s.version_id JOIN source src ON src.source_id=v.source_id WHERE span_id=?", (span_id,)).fetchone()
        return dict(row) if row else None

    def eligible(self, span: dict, material: str | None = None) -> tuple[bool, str]:
        if span["source_state"] in {"withdrawn", "corrected_pending_review"}:
            return False, span["source_state"]
        if span["identity_status"] != "matched":
            return False, "identity_not_matched"
        if not json.loads(span["rights_json"]).get("index_allowed"):
            return False, "rights_not_cleared"
        if material == "fulltext" and span["material_type"] != "fulltext":
            return False, "insufficient_material_depth"
        return True, "eligible"

    def update_state(self, source_id: str, state: str, reason: str, relation: dict | None = None) -> dict:
        if state not in {"withdrawn", "corrected_pending_review", "acquired"}:
            raise ValueError("unsupported lifecycle state")
        source_id = self.source(source_id)["source_id"]
        with self.sources:
            self.sources.execute("UPDATE source SET state=?,updates_json=?,updated_at=? WHERE source_id=?", (state, dumps({"reason": reason, "relation": relation, "checked_at": now()}), now(), source_id))
        affected = []
        if state != "acquired":
            with self.theories:
                for row in self.theories.execute("SELECT * FROM theory WHERE status='approved'").fetchall():
                    review = json.loads(row["review_json"])
                    if any(x.get("source_id") == source_id for x in review.get("evidence_links", [])):
                        self.theories.execute("UPDATE theory SET status='needs_review' WHERE theory_id=? AND version=?", (row["theory_id"], row["version"]))
                        affected.append(row["theory_id"])
        self.log(source_id, "lifecycle_change", {"state": state, "reason": reason, "affected_theories": affected})
        return {"source_id": source_id, "state": state, "affected_theories": affected, "cached_explanations": "revalidate_citations_before_use"}

    def review(self, theory_id: str, version: str, *, reviewer: str, rationale: str,
               evidence_links: list[dict], applicability: dict, claims: list[dict],
               decision: str = "approved", implementation_tests: list[str] | None = None,
               authority: str = "explanation_only", reviewer_kind: str = "human") -> dict:
        row = self.theories.execute("SELECT * FROM theory WHERE theory_id=? AND version=?", (theory_id, version)).fetchone()
        if not row:
            raise ValueError("unknown theory/version")
        if not reviewer.strip() or not rationale.strip():
            raise ValueError("identified reviewer and claim-specific rationale required")
        if decision not in {"approved", "rejected", "needs_review"}:
            raise ValueError("invalid review decision")
        if authority not in {"explanation_only", "progression_candidate"}:
            raise ValueError("unsupported review capability; exact prescriptions are not authorized")
        if authority == "progression_candidate":
            if reviewer_kind != "qualified_human_review" or not implementation_tests or not applicability.get("required"):
                raise ValueError("candidate capability requires qualified review, explicit applicability and implementation validation references")
        if decision == "approved":
            if not claims or not evidence_links or not applicability:
                raise ValueError("approval requires individual claims, applicability and real evidence")
            available = set()
            for link in evidence_links:
                if not link.get("span_ids"):
                    raise ValueError("empty evidence link")
                for span_id in link["span_ids"]:
                    span = self.span(span_id)
                    if not span or span["version_id"] != link["source_version_id"] or span["source_id"] != link["source_id"]:
                        raise ValueError("citation does not resolve to exact source version")
                    allowed, reason = self.eligible(span)
                    if not allowed:
                        raise ValueError(reason)
                    available.add(span_id)
            for claim in claims:
                if not claim.get("text") or not claim.get("span_ids") or not set(claim["span_ids"]) <= available or not claim.get("support_rationale"):
                    raise ValueError("each claim requires reviewed supporting spans and rationale")
                if claim.get("formula") and not implementation_tests:
                    raise ValueError("formula activation requires implementation validation references")
        payload = {"reviewer": reviewer, "reviewed_at": now(), "rationale": rationale, "decision": decision,
                   "evidence_links": evidence_links, "applicability": applicability, "claims": claims,
                   "implementation_tests": implementation_tests or [], "authority": authority,
                   "reviewer_kind": reviewer_kind, "independent_expert_validation": False}
        previous = json.loads(row["review_json"])
        if previous:
            unchanged = all(previous.get(k) == value for k, value in payload.items() if k != "reviewed_at")
            if unchanged and row["status"] == decision:
                return previous
            raise ValueError("reviewed theory version is immutable; create a new draft with revise_theory")
        with self.theories:
            self.theories.execute("UPDATE theory SET status=?,review_json=? WHERE theory_id=? AND version=?", (decision, dumps(payload), theory_id, version))
            self.theories.execute("INSERT INTO theory_review(theory_id,version,decision,payload_json,created_at) VALUES(?,?,?,?,?)", (theory_id, version, decision, dumps(payload), now()))
        return payload

    def revise_theory(self, theory_id: str, from_version: str, new_version: str, *,
                      reviewer: str, rationale: str, card_patch: dict | None = None) -> dict:
        """Create an unauthorised draft; never inherit an earlier approval."""
        if not reviewer.strip() or not rationale.strip() or not new_version.strip():
            raise ValueError("revision requires reviewer, rationale and a new version")
        row = self.theories.execute("SELECT * FROM theory WHERE theory_id=? AND version=?",
                                    (theory_id, from_version)).fetchone()
        if not row:
            raise ValueError("unknown theory/version")
        if self.theories.execute("SELECT 1 FROM theory WHERE theory_id=? AND version=?",
                                 (theory_id, new_version)).fetchone():
            raise ValueError("theory version already exists")
        patch = card_patch or {}
        if {"theory_id", "core_theory_id", "version", "review_status", "activation_status"} & patch.keys():
            raise ValueError("identity and approval cannot be changed through card_patch")
        provenance = {"from_version": from_version, "reviewer": reviewer,
                      "rationale": rationale, "created_at": now()}
        card = {**json.loads(row["card_json"]), **patch, "version": new_version,
                "review_status": "draft", "activation_status": "inactive_pending_review",
                "revision": provenance}
        with self.theories:
            self.theories.execute("INSERT INTO theory VALUES(?,?,?,'draft','{}')",
                                   (theory_id, new_version, dumps(card)))
            self.theories.execute("INSERT INTO theory_review(theory_id,version,decision,payload_json,created_at) VALUES(?,?,?,?,?)",
                                   (theory_id, new_version, "draft", dumps(provenance), now()))
        return {"theory_id": theory_id, "version": new_version, "status": "draft",
                "inherited_authority": None, "revision": provenance}

    def release(self, release_id: str) -> dict:
        theories = [dict(r) for r in self.theories.execute("SELECT theory_id,version,status,review_json FROM theory WHERE status='approved' ORDER BY theory_id,version")]
        linked = {link['source_version_id'] for t in theories for link in json.loads(t['review_json']).get('evidence_links', [])}
        sources = [dict(r) for r in self.sources.execute("SELECT v.version_id,v.source_id,v.sha256,v.material_type,v.rights_json FROM version v JOIN source s ON s.source_id=v.source_id WHERE v.identity_status='matched' AND s.state='acquired' ORDER BY version_id")
                   if r['version_id'] in linked and json.loads(r['rights_json']).get('index_allowed')]
        available = {s['version_id'] for s in sources}
        if not linked <= available:
            raise ValueError("release has unavailable or rights-blocked theory dependencies")
        output = {"release_id": release_id, "source_versions": sources, "theories": theories,
                  "retriever_version": "lexical-1.3.0", "created_at": now()}
        for db, table, key in ((self.sources, "index_release", "source_versions"), (self.theories, "theory_release", "theories")):
            manifest = dumps(output[key])
            previous = db.execute(f"SELECT sha256 FROM {table} WHERE release_id=?", (release_id,)).fetchone()
            sha = digest(manifest.encode())
            if previous and previous[0] != sha:
                raise ValueError("release is immutable; choose a new release_id")
            with db:
                db.execute(f"INSERT OR IGNORE INTO {table} VALUES(?,?,?,?)", (release_id, manifest, sha, now()))
        return output

    def released_theories(self, release_id: str) -> list[dict]:
        row = self.theories.execute("SELECT manifest_json FROM theory_release WHERE release_id=?", (release_id,)).fetchone()
        if not row:
            raise ValueError("unknown theory release")
        output = []
        for item in json.loads(row[0]):
            current = self.theories.execute("SELECT card_json,status FROM theory WHERE theory_id=? AND version=?", (item['theory_id'], item['version'])).fetchone()
            if not current:
                raise ValueError("missing frozen theory")
            output.append({**item, 'card_json': current['card_json'],
                           'status': item['status'] if current['status']=='approved' else current['status']})
        return output
