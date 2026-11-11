"""Independent SourceLibrary and TheoryLibrary, immutable content and review events."""

from __future__ import annotations

import hashlib
import json
import re
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
CREATE TABLE IF NOT EXISTS source_version_clearance (
 source_id TEXT NOT NULL, version_id TEXT NOT NULL, scientific_epoch INTEGER NOT NULL,
 reviewer TEXT NOT NULL, rationale TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(source_id,version_id,scientific_epoch)
);
CREATE TABLE IF NOT EXISTS scientific_notice (
 notice_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, state TEXT NOT NULL,
 payload_json TEXT NOT NULL, first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parse_supersession (
 old_version_id TEXT PRIMARY KEY, new_version_id TEXT NOT NULL,
 reason TEXT NOT NULL, created_at TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS theory_lifecycle (
 id INTEGER PRIMARY KEY, theory_id TEXT NOT NULL, version TEXT NOT NULL,
 action TEXT NOT NULL, actor TEXT NOT NULL, rationale TEXT NOT NULL,
 previous_status TEXT NOT NULL, status TEXT NOT NULL, superseded_by TEXT,
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
    if source.get("manifestation_id"):
        return "manifestation:" + source["manifestation_id"]
    if source.get("isbn"):
        return "isbn:" + re.sub(r"[^0-9X]", "", str(source["isbn"]).upper())
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
        columns = {r[1] for r in self.sources.execute("PRAGMA table_info(source)")}
        if "acquisition_state" not in columns:
            with self.sources:
                self.sources.execute("ALTER TABLE source ADD COLUMN acquisition_state TEXT NOT NULL DEFAULT 'discovered'")
                self.sources.execute("ALTER TABLE source ADD COLUMN scientific_state TEXT NOT NULL DEFAULT 'current'")
                self.sources.execute("UPDATE source SET acquisition_state=CASE WHEN EXISTS(SELECT 1 FROM version WHERE version.source_id=source.source_id) THEN 'acquired' ELSE 'discovered' END,scientific_state=CASE WHEN state IN ('withdrawn','corrected_pending_review') THEN state ELSE 'current' END")
        if "scope_rights_json" not in {r[1] for r in self.sources.execute("PRAGMA table_info(span)")}:
            with self.sources:
                self.sources.execute("ALTER TABLE span ADD COLUMN scope_rights_json TEXT NOT NULL DEFAULT '{}'")
        if "scientific_epoch" not in {r[1] for r in self.sources.execute("PRAGMA table_info(source)")}:
            with self.sources:
                self.sources.execute("ALTER TABLE source ADD COLUMN scientific_epoch INTEGER NOT NULL DEFAULT 0")
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
                    "INSERT OR IGNORE INTO source(source_id,canonical_identity,manifest_json,state,identity_status,updates_json,updated_at) VALUES(?,?,?,'discovered','pending','{}',?)",
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
                self.sources.execute("INSERT OR IGNORE INTO span(span_id,version_id,kind,section_path,locator_json,text,text_hash,structured_json,scope_rights_json) VALUES(?,?,?,?,?,?,?,?,?)", (
                    f"{version_id}:s{i:05d}", version_id, span.get("kind", "paragraph"),
                    span.get("section_path", ""), dumps(span.get("locator", {})), text,
                    digest(text.encode()), dumps(span.get("structured", {})), dumps(span.get("rights", {}))))
            self.sources.execute(
                "UPDATE source SET acquisition_state='acquired',state=CASE WHEN scientific_state='current' THEN 'acquired' ELSE scientific_state END,identity_status=?,updated_at=? WHERE source_id=?",
                (identity_status, now(), source_id),
            )
        return version_id

    def span(self, span_id: str) -> dict | None:
        row = self.sources.execute("SELECT s.*,v.source_id,v.material_type,v.rights_json,v.parser_version,v.identity_status,v.metadata_json,src.state source_state,src.scientific_state source_scientific_state,src.scientific_epoch,src.acquisition_state source_acquisition_state FROM span s JOIN version v ON v.version_id=s.version_id JOIN source src ON src.source_id=v.source_id WHERE span_id=?", (span_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        if json.loads(result["scope_rights_json"]):
            result["rights_json"] = result["scope_rights_json"]
        return result

    def eligible(self, span: dict, material: str | None = None) -> tuple[bool, str]:
        if self.sources.execute("SELECT 1 FROM parse_supersession WHERE old_version_id=?", (span["version_id"],)).fetchone():
            return False, "parser_superseded_requires_explicit_claim_review"
        current = self.sources.execute("SELECT scientific_state,scientific_epoch FROM source WHERE source_id=?", (span["source_id"],)).fetchone()
        if not current:
            return False, "source_missing"
        scientific = current["scientific_state"]
        cleared = self.sources.execute("SELECT 1 FROM source_version_clearance WHERE source_id=? AND version_id=? AND scientific_epoch=?",
                                        (span["source_id"], span["version_id"], current["scientific_epoch"])).fetchone()
        if scientific == "withdrawn" or scientific == "corrected_pending_review" and not cleared:
            return False, scientific
        identity_review = self.sources.execute("SELECT 1 FROM source_review WHERE source_id=? AND version_id=? AND decision='identity_matched'",
            (span["source_id"], span["version_id"])).fetchone()
        if span["identity_status"] != "matched" and not identity_review:
            return False, "identity_not_matched"
        rights = json.loads(span["rights_json"])
        if rights.get("status") == "license_identified" and not rights.get("scope_policy_version"):
            return False, "legacy_jats_scope_review_required"
        if not rights.get("index_allowed"):
            return False, "rights_not_cleared"
        if material == "fulltext" and span["material_type"] != "fulltext":
            return False, "insufficient_material_depth"
        return True, "eligible"

    def update_state(self, source_id: str, state: str, reason: str, relation: dict | None = None) -> dict:
        if state not in {"withdrawn", "corrected_pending_review", "acquired"}:
            raise ValueError("unsupported lifecycle state")
        current = self.source(source_id)
        source_id = current["source_id"]
        scientific = current["scientific_state"] if state == "acquired" else state
        if current["scientific_state"] == "withdrawn":
            scientific = "withdrawn"  # fetches and correction notices cannot undo withdrawal
        effective = scientific if scientific != "current" else state
        notice = {"canonical_identity": current["canonical_identity"], "state": state,
                  "reason": reason, "relation": relation or {}}
        notice_id = digest(dumps(notice).encode())
        if state != "acquired" and self.sources.execute("SELECT 1 FROM scientific_notice WHERE notice_id=?", (notice_id,)).fetchone():
            self.log(source_id, "scientific_notice_seen_again", {"notice_id": notice_id, "notice": notice})
            return {"source_id": source_id, "state": current["state"], "scientific_state": current["scientific_state"],
                    "affected_theories": [], "duplicate_notice": True, "scientific_epoch": current["scientific_epoch"]}
        with self.sources:
            if state != "acquired":
                self.sources.execute("INSERT INTO scientific_notice VALUES(?,?,?,?,?)", (notice_id, source_id, state, dumps(notice), now()))
            self.sources.execute("UPDATE source SET state=?,scientific_state=?,scientific_epoch=scientific_epoch+?,acquisition_state=CASE WHEN ?='acquired' THEN 'acquired' ELSE acquisition_state END,updates_json=?,updated_at=? WHERE source_id=?", (effective, scientific, int(state != "acquired"), state, dumps({"reason": reason, "relation": relation, "checked_at": now()}), now(), source_id))
        affected = []
        if scientific != "current":
            with self.theories:
                for row in self.theories.execute("SELECT * FROM theory WHERE status='approved'").fetchall():
                    review = json.loads(row["review_json"])
                    if any(x.get("source_id") == source_id for x in review.get("evidence_links", [])):
                        self.theory_state(row["theory_id"], row["version"], "needs_review", actor="source_lifecycle", rationale=f"{source_id}: {reason}")
                        affected.append(row["theory_id"])
        self.log(source_id, "lifecycle_change", {"state": state, "reason": reason, "affected_theories": affected})
        return {"source_id": source_id, "state": effective, "scientific_state": scientific, "affected_theories": affected, "cached_explanations": "revalidate_citations_before_use"}

    def review_source_state(self, source_id: str, *, reviewer: str, rationale: str,
                            source_version_ids: list[str]) -> dict:
        """Explicit clearance is distinct from fetching or source metadata updates."""
        source = self.source(source_id)
        source_id = source["source_id"]
        if source["scientific_state"] == "withdrawn":
            raise ValueError("withdrawn source cannot be restored by ordinary version clearance")
        if not reviewer.strip() or not rationale.strip() or not source_version_ids:
            raise ValueError("source clearance requires identified review, rationale and exact versions")
        for version in source_version_ids:
            if not self.sources.execute("SELECT 1 FROM version WHERE source_id=? AND version_id=?", (source_id, version)).fetchone():
                raise ValueError("source review version mismatch")
        with self.sources:
            for version in source_version_ids:
                self.sources.execute("INSERT INTO source_review(source_id,version_id,reviewer,decision,rationale,created_at) VALUES(?,?,?,?,?,?)",
                                     (source_id, version, reviewer, "version_scientific_clearance", rationale, now()))
                self.sources.execute("INSERT OR REPLACE INTO source_version_clearance VALUES(?,?,?,?,?,?)",
                                     (source_id, version, source["scientific_epoch"], reviewer, rationale, now()))
        self.log(source_id, "scientific_state_reviewed", {"reviewer": reviewer, "rationale": rationale, "source_version_ids": source_version_ids})
        return {"source_id": source_id, "scientific_state": source["scientific_state"],
                "cleared_source_version_ids": source_version_ids, "scientific_epoch": source["scientific_epoch"],
                "unreviewed_versions_remain_blocked": True, "theories_reactivated": False}

    def theory_state(self, theory_id: str, version: str, action: str, *, actor: str, rationale: str) -> dict:
        if action not in {"disabled", "revoked", "needs_review", "activate"} or not actor.strip() or not rationale.strip():
            raise ValueError("identified actor, rationale and supported theory lifecycle action required")
        row = self.theories.execute("SELECT * FROM theory WHERE theory_id=? AND version=?", (theory_id, version)).fetchone()
        if not row:
            raise ValueError("unknown theory/version")
        status = "approved" if action == "activate" else action
        if action == "disabled" and row["status"] not in {"approved", "disabled"}:
            raise ValueError("revoked, superseded or review-pending content cannot be reset to a reactivatable state")
        if action == "activate":
            review = json.loads(row["review_json"])
            if row["status"] != "disabled" or review.get("decision") != "approved":
                raise ValueError("only a disabled unchanged approval may be reactivated; otherwise create a reviewed revision")
            if self.theories.execute("SELECT 1 FROM theory WHERE theory_id=? AND status='approved' AND version!=?", (theory_id, version)).fetchone():
                raise ValueError("another effective theory version already exists")
            for link in review["evidence_links"]:
                if any(not self.span(sid) or not self.eligible(self.span(sid))[0] for sid in link["span_ids"]):
                    raise ValueError("theory dependencies no longer eligible")
        with self.theories:
            self.theories.execute("UPDATE theory SET status=? WHERE theory_id=? AND version=?", (status, theory_id, version))
            self.theories.execute("INSERT INTO theory_lifecycle(theory_id,version,action,actor,rationale,previous_status,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                  (theory_id, version, action, actor, rationale, row["status"], status, now()))
        return {"theory_id": theory_id, "version": version, "effective_status": status, "review_unchanged": True}

    def review(self, theory_id: str, version: str, *, reviewer: str, rationale: str,
               evidence_links: list[dict], applicability: dict, claims: list[dict],
               decision: str = "approved", implementation_tests: list[str] | None = None,
               authority: str = "explanation_only", reviewer_kind: str = "human",
               permitted_actions: list[str] | None = None) -> dict:
        row = self.theories.execute("SELECT * FROM theory WHERE theory_id=? AND version=?", (theory_id, version)).fetchone()
        if not row:
            raise ValueError("unknown theory/version")
        if not reviewer.strip() or not rationale.strip():
            raise ValueError("identified reviewer and claim-specific rationale required")
        if decision not in {"approved", "rejected", "needs_review"}:
            raise ValueError("invalid review decision")
        previous = json.loads(row["review_json"])
        if previous and decision in {"needs_review", "rejected"}:
            return self.theory_state(theory_id, version, "revoked" if decision == "rejected" else "needs_review",
                                     actor=reviewer, rationale=rationale)
        if authority not in {"explanation_only", "progression_candidate", "trial_candidate"}:
            raise ValueError("unsupported review capability; exact prescriptions are not authorized")
        if authority in {"progression_candidate", "trial_candidate"}:
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
                from .support import validate_bindings
                validate_bindings(claim)
        payload = {"reviewer": reviewer, "reviewed_at": now(), "rationale": rationale, "decision": decision,
                   "evidence_links": evidence_links, "applicability": applicability, "claims": claims,
                   "implementation_tests": implementation_tests or [], "authority": authority,
                   "reviewer_kind": reviewer_kind, "independent_expert_validation": False}
        if permitted_actions is not None:
            if not isinstance(permitted_actions, list) or any(not isinstance(x, str) for x in permitted_actions):
                raise ValueError("permitted_actions must be an explicit list")
            payload["permitted_actions"] = sorted(set(permitted_actions))
        if previous:
            unchanged = all(previous.get(k) == value for k, value in payload.items() if k != "reviewed_at")
            if unchanged and row["status"] == decision:
                return previous
            raise ValueError("reviewed theory version is immutable; create a new draft with revise_theory")
        supersedes = json.loads(row["card_json"]).get("revision", {}).get("from_version")
        active = self.theories.execute("SELECT version FROM theory WHERE theory_id=? AND status='approved' AND version!=?", (theory_id, version)).fetchall()
        if decision == "approved" and any(item[0] != supersedes for item in active):
            raise ValueError("approval must explicitly revise the currently effective theory version")
        with self.theories:
            if decision == "approved" and supersedes:
                old = self.theories.execute("SELECT status FROM theory WHERE theory_id=? AND version=?", (theory_id, supersedes)).fetchone()
                if old:
                    self.theories.execute("UPDATE theory SET status='superseded' WHERE theory_id=? AND version=?", (theory_id, supersedes))
                    self.theories.execute("INSERT INTO theory_lifecycle(theory_id,version,action,actor,rationale,previous_status,status,superseded_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                          (theory_id, supersedes, "superseded", reviewer, rationale, old[0], "superseded", version, now()))
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
        for theory in theories:
            for link in json.loads(theory["review_json"])["evidence_links"]:
                for sid in link["span_ids"]:
                    span = self.span(sid)
                    if (not span or span["version_id"] != link["source_version_id"]
                            or not self.eligible(span)[0]):
                        raise ValueError("release has unavailable or rights-blocked theory dependencies")
        # Eligibility is scoped to each cited span and exact scientific clearance,
        # not the article-wide grant or source-wide compatibility state.
        sources = [dict(r) for r in self.sources.execute("SELECT version_id,source_id,sha256,material_type,rights_json FROM version WHERE identity_status='matched' ORDER BY version_id")
                   if r['version_id'] in linked]
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
