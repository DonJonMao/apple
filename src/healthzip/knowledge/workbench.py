"""Public knowledge application service. No private database is opened by this service."""

from __future__ import annotations

import json
from pathlib import Path

from .acquisition import Acquirer
from .store import Libraries, digest


def default_spec_dir() -> Path:
    bundled = Path(__file__).parent / "data"
    if bundled.is_dir():
        return bundled
    return Path(__file__).resolve().parents[3] / "specs/v1.3/Codex_Execution_Pack_v1.3"


class KnowledgeWorkbench:
    def __init__(self, root, spec_dir=None):
        self.root = Path(root)
        self.spec_dir = Path(spec_dir) if spec_dir else default_spec_dir()
        self.lib = Libraries(self.root)
        self.routes = json.loads((self.spec_dir / "knowledge_routes.json").read_text())

    def close(self):
        self.lib.close()

    def seed(self):
        self.lib.seed(json.loads((self.spec_dir / "sources.json").read_text()),
                      json.loads((self.spec_dir / "theory_seed_cards.json").read_text()))
        return self.status()

    def acquire(self, source_ids=None, fulltext=False, contact="", timeout=18, smoke=True):
        acquirer = Acquirer(self.lib, contact=contact, timeout=timeout)
        providers = acquirer.smoke_test() if smoke else []
        ids = source_ids or [r[0] for r in self.lib.sources.execute("SELECT source_id FROM source ORDER BY source_id")]
        canonical = sorted({sid for alias in ids for sid in self.lib.resolve(alias)})
        if source_ids and not canonical:
            raise ValueError("no recognized source IDs")
        results = [acquirer.acquire_one(sid, fulltext=fulltext) for sid in canonical]
        return {"provider_smoke_tests": providers, "sources": results, "status": self.status()}

    def status(self):
        counts = {}
        for name, db, table, field in (("source_states", self.lib.sources, "source", "state"),
                                      ("materials", self.lib.sources, "version", "material_type"),
                                      ("theory_states", self.lib.theories, "theory", "status")):
            counts[name] = {r[0]: r[1] for r in db.execute(f"SELECT {field},COUNT(*) FROM {table} GROUP BY {field}")}
        counts["spans"] = self.lib.sources.execute("SELECT COUNT(*) FROM span").fetchone()[0]
        counts["fulltext_source_count"] = self.lib.sources.execute("SELECT COUNT(DISTINCT source_id) FROM version WHERE material_type='fulltext'").fetchone()[0]
        counts["retrievable_span_count"] = sum(self.lib.eligible(self.lib.span(r[0]))[0] for r in self.lib.sources.execute("SELECT span_id FROM span"))
        counts["review_queue"] = [dict(r) for r in self.lib.sources.execute("SELECT source_id,identity_status,state FROM source WHERE identity_status!='matched' OR state IN ('withdrawn','corrected_pending_review') ORDER BY source_id")]
        counts["theory_review_queue"] = []
        counts["effective_approved_theory_count"] = 0
        for row in self.lib.theories.execute("SELECT theory_id,version,status,review_json FROM theory ORDER BY theory_id,version"):
            review = json.loads(row["review_json"])
            reasons = set()
            for link in review.get("evidence_links", []):
                for sid in link["span_ids"]:
                    span = self.lib.span(sid)
                    allowed, reason = self.lib.eligible(span) if span else (False, "missing_span")
                    if not allowed:
                        reasons.add(reason)
            if row["status"] == "approved" and not reasons:
                counts["effective_approved_theory_count"] += 1
            elif row["status"] in {"draft", "needs_review", "revoked", "disabled"} or reasons:
                counts["theory_review_queue"].append({"theory_id": row["theory_id"], "version": row["version"],
                    "status": row["status"], "dependency_blocks": sorted(reasons),
                    "authority": review.get("authority"), "independent_expert_validation": False})
        counts["scientific_validation"] = "not_established_by_software_or_retrieval_checks"
        for field in ("acquisition_state", "scientific_state"):
            counts[field + "s"] = {r[0]: r[1] for r in self.lib.sources.execute(f"SELECT {field},COUNT(*) FROM source GROUP BY {field}")}
        return counts

    def query(self, question, route=None, context=None, personal_metrics=None, **kwargs):
        from .retrieval import query
        return query(self, question, route=route, context=context or {}, personal_metrics=personal_metrics or [], **kwargs)

    def review_theory(self, theory_id, version, **kwargs):
        return self.lib.review(theory_id, version, **kwargs)

    def revise_theory(self, theory_id, from_version, new_version, **kwargs):
        return self.lib.revise_theory(theory_id, from_version, new_version, **kwargs)

    def theory_state(self, theory_id, version, action, **kwargs):
        return self.lib.theory_state(theory_id, version, action, **kwargs)

    def review_source_state(self, source_id, **kwargs):
        return self.lib.review_source_state(source_id, **kwargs)

    def import_document(self, source_id, path, **kwargs):
        from .documents import import_document
        return import_document(self, source_id, path, **kwargs)

    def reparse_source_version(self, source_version_id):
        """Reparse already-held JATS bytes into a new version, without changing reviews."""
        from .acquisition import identity_check, parse_jats
        row = self.lib.sources.execute("SELECT * FROM version WHERE version_id=?", (source_version_id,)).fetchone()
        if not row or row["material_type"] != "fulltext":
            raise ValueError("existing JATS fulltext version required")
        raw = (self.root / row["storage_uri"]).read_bytes()
        if digest(raw) != row["sha256"] or raw.startswith(b"%PDF"):
            raise ValueError("valid preserved JATS bytes required")
        metadata, spans, rights = parse_jats(raw)
        identity, conflicts = identity_check(self.lib.source(row["source_id"])["manifest"], metadata)
        version = self.lib.record_version(row["source_id"], raw, "fulltext", json.loads(row["receipt_json"]),
                                           metadata, rights, identity, spans, "jats-scoped-1.4.0")
        result = {"source_id": row["source_id"], "previous_version_id": source_version_id,
                  "version_id": version, "raw_sha256": row["sha256"], "identity_status": identity,
                  "identity_conflicts": conflicts, "article_index_allowed": rights["index_allowed"],
                  "scope_count": len(rights["component_scopes"]), "span_count": len(spans),
                  "eligible_spans": sum(self.lib.eligible(self.lib.span(f"{version}:s{i:05d}"))[0] for i in range(len(spans))),
                  "theory_reviews_changed": False, "review": "automated_scope_reparse_not_expert_validation"}
        self.lib.log(row["source_id"], "local_scope_reparse", result)
        return result

    def evaluate(self, cases_path, split="visible_development", **kwargs):
        from .evaluation import evaluate
        return evaluate(self, cases_path, split=split, **kwargs)

    def release(self, release_id):
        return self.lib.release(release_id)

    def reviewed_principles(self, route, context, release_id=None):
        """Resolve current candidate capabilities from actual reviewed, usable dependencies.

        Generic explanation reviews never acquire action authority from their status alone.
        The returned capability licenses a deterministic *candidate*, not guaranteed success,
        an optimal prescription, or conversion of state signals into physiological percentages.
        """
        from .retrieval import _context_match
        if route not in {r['route_id'] for r in self.routes['routes']}:
            raise ValueError('unknown knowledge route')
        rows = self.lib.released_theories(release_id) if release_id else self.lib.theories.execute("SELECT * FROM theory ORDER BY theory_id,version")
        principles, excluded = [], []
        for row in rows:
            card, review = json.loads(row['card_json']), json.loads(row['review_json'])
            if route not in card.get('domains', []):
                continue
            reason = None
            if row['status'] != 'approved':
                reason = 'theory_' + row['status']
            elif review.get('authority') not in {'progression_candidate', 'trial_candidate'}:
                reason = 'explanation_only_no_candidate_authority'
            elif review.get('reviewer_kind') != 'qualified_human_review':
                reason = 'candidate_review_qualification_missing'
            matched, scope_reason = _context_match(review.get('applicability', {}).get('required', {}), context)
            if not reason and not matched:
                reason = scope_reason
            spans = []
            for link in review.get('evidence_links', []):
                for sid in link.get('span_ids', []):
                    span = self.lib.span(sid)
                    if not span or not self.lib.eligible(span)[0]:
                        reason = reason or 'unavailable_withdrawn_or_rights_blocked_evidence'
                    else:
                        spans.append({'source_id': link['source_id'], 'source_version_id': link['source_version_id'], 'span_id': sid})
            if not reason and not spans:
                reason = 'no_real_evidence_spans'
            if reason:
                excluded.append({'theory_id': row['theory_id'], 'version': row['version'], 'reason': reason,
                                 'required_context': review.get('applicability', {}).get('required', {})})
                continue
            principles.append({'theory_id': row['theory_id'], 'review_status': 'approved', 'version': row['version'],
                               'reviewer': review['reviewer'], 'reviewed_at': review['reviewed_at'],
                               'capability': review['authority'], 'evidence_spans': spans,
                               'rights_verified': True, 'scope_matches': True, 'applicability': review['applicability'],
                               'implementation_tests': review.get('implementation_tests', []),
                               'limits': ['Candidate is a user-selectable experiment; no guaranteed individual effect or automatic execution.']})
        return {'principles': principles, 'excluded': excluded, 'source_release': release_id,
                'review_snapshot_sha256': digest(json.dumps(principles, sort_keys=True).encode())}

    def verify(self):
        """Verify raw receipts and evidence text hashes without network or scientific inference."""
        versions, failures = 0, []
        for row in self.lib.sources.execute("SELECT * FROM version"):
            versions += 1
            path = self.root / row['storage_uri']
            if not path.is_file():
                failures.append({'version_id': row['version_id'], 'reason': 'missing_raw_bytes'})
                continue
            raw = path.read_bytes()
            if digest(raw) != row['sha256'] or len(raw) != row['byte_length']:
                failures.append({'version_id': row['version_id'], 'reason': 'raw_hash_or_length_mismatch'})
        spans = 0
        for row in self.lib.sources.execute("SELECT * FROM span"):
            spans += 1
            if digest(row['text'].encode()) != row['text_hash']:
                failures.append({'span_id': row['span_id'], 'reason': 'text_hash_mismatch'})
            if not json.loads(row['locator_json']):
                failures.append({'span_id': row['span_id'], 'reason': 'missing_locator'})
        return {'versions_checked': versions, 'spans_checked': spans, 'failures': failures,
                'status': 'verified' if not failures else 'failed',
                'scope': 'byte integrity and locator presence; does not certify scientific interpretation or OCR/table semantics'}
