"""Versioned source claims and product rules with auditable, limited capabilities.

An AI-assisted content check remains AI-assisted. The personal trial policy
allows a bounded user-selected task; it never grants prediction or causality.
"""

from __future__ import annotations

import json
from pathlib import Path

from .applicability import check_conditions
from .store import digest, dumps, now

POLICY = {
    "version": "personal-trial-policy-1.4.0",
    "allowed_reviewers": ["ai_assisted", "qualified_human_review", "independent_human"],
    "capabilities": ["source_explanation", "plan_candidate", "trial_candidate"],
    "requirements": ["exact_eligible_fulltext", "content_review", "application_review", "implementation_tests", "explicit_context"],
    "requires_personal_causal_validation": False,
    "forbidden": ["individual_prediction", "causal_effect", "diagnosis", "automatic_clinical_prescription"],
    "limit": "Personal fitness trial policy, not an independent expert endorsement or proof of individual effect.",
}

RECORD_POLICY = {
    "version": "record-description-policy-1.4.0",
    "allowed_reviewers": POLICY["allowed_reviewers"],
    "capabilities": ["description", "task_followup", "report"],
    "requirements": ["explicit_record_contract", "implementation_tests", "application_review", "explicit_context"],
    "evidence_basis": "product_record_contract",
    "forbidden": ["scientific_source_authority", "numeric_training_candidate", "individual_prediction", "causal_effect", "diagnosis"],
    "limit": "Records may be compared, counted or linked under explicit software contracts; this supplies no scientific or candidate authority.",
}
POLICIES = {p["version"]: p for p in (POLICY, RECORD_POLICY)}


def ensure_schema(w):
    w.lib.sources.executescript("""
    CREATE TABLE IF NOT EXISTS chapter_coverage(
      source_id TEXT NOT NULL, edition_id TEXT NOT NULL, chapter_id TEXT NOT NULL,
      payload_json TEXT NOT NULL, PRIMARY KEY(source_id,edition_id,chapter_id));
    """)
    w.lib.theories.executescript("""
    CREATE TABLE IF NOT EXISTS source_claim(
      claim_id TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL,
      payload_json TEXT NOT NULL, review_json TEXT NOT NULL, PRIMARY KEY(claim_id,version));
    CREATE TABLE IF NOT EXISTS application_rule(
      rule_id TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL,
      payload_json TEXT NOT NULL, review_json TEXT NOT NULL, PRIMARY KEY(rule_id,version));
    CREATE TABLE IF NOT EXISTS core_lifecycle(
      id INTEGER PRIMARY KEY, object_type TEXT NOT NULL, object_id TEXT NOT NULL,
      version TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL,
      rationale TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS core_release(
      release_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    w.lib.sources.commit()
    w.lib.theories.commit()


def seed_core(w):
    data = Path(__file__).parent / "data"
    sources = json.loads((data / "core_sources.json").read_text())
    for item in sources["sources"]:
        sid = item.get("canonical_source_id", item["source_id"])
        existing = w.lib.sources.execute("SELECT manifest_json FROM source WHERE source_id=?", (sid,)).fetchone()
        entry = {**(json.loads(existing[0]) if existing else {}), **item, **item.get("identifiers", {}), "source_id": sid,
                 "canonical_url": item["official_urls"][0], "corpus_roles": ["core"]}
        if item.get("reuse_existing_source"):
            canonical = next((s for s in json.loads((w.spec_dir / "sources.json").read_text())["sources"] if s["source_id"] == sid), None)
            if canonical:
                entry["title"] = canonical["title"]
        if item.get("edition"):
            entry.update(work_id=item["source_id"].rsplit("-", 1)[0], edition_id=f"{item['source_id']}:edition-{item['edition']}",
                         manifestation_id=item.get("identifiers", {}).get("isbn") or item.get("identifiers", {}).get("publisher_manifestation_isbn") or item["source_id"])
        w.lib.seed({"sources": [entry]}, {"cards": []})
        with w.lib.sources:
            w.lib.sources.execute("UPDATE source SET manifest_json=? WHERE source_id=?", (dumps(entry), sid))
            w.lib.sources.execute("INSERT OR IGNORE INTO alias VALUES(?,?)", (item["source_id"], sid))
            for index, chapter in enumerate(item["priority_sections"]):
                cid = str(chapter.get("chapter_number") or f"section-{index + 1}")
                w.lib.sources.execute("INSERT OR IGNORE INTO chapter_coverage VALUES(?,?,?,?)",
                    (sid, entry.get("edition_id", sid), cid, dumps({**chapter, "status": "missing_source_content", "missing_pages": "not_acquired", "span_ids": []})))
    # Classify old sources without copying their bytes or counting aliases twice.
    with w.lib.sources:
        for row in w.lib.sources.execute("SELECT source_id,manifest_json FROM source").fetchall():
            item = json.loads(row["manifest_json"])
            if not item.get("corpus_roles"):
                role = "interface" if row["source_id"].startswith(("APPLE", "KB", "UX")) else "research"
                item.update(corpus_roles=[role], source_kind=item.get("source_kind", "interface_documentation" if role == "interface" else "research_publication"))
                w.lib.sources.execute("UPDATE source SET manifest_json=? WHERE source_id=?", (dumps(item), row["source_id"]))
    inventory = json.loads((data / "core_rules.json").read_text())
    with w.lib.theories:
        for rule in inventory["rules"]:
            w.lib.theories.execute("INSERT OR IGNORE INTO application_rule VALUES(?,?,'draft',?,'{}')",
                                  (rule["rule_id"], rule["rule_version"], dumps(rule)))
    return core_status(w)


def _review(review, *, application=False):
    required = ["reviewer", "reviewer_kind", "rationale", "reviewed_at"]
    if any(not review.get(key) for key in required):
        raise ValueError("identified dated review and rationale required")
    if review["reviewer_kind"] not in POLICY["allowed_reviewers"] + ["synthetic_fixture"]:
        raise ValueError("unsupported truthful reviewer kind")
    if review.get("independent_expert_validation") and review["reviewer_kind"] == "ai_assisted":
        raise ValueError("AI cannot claim independent expert validation")
    if review.get("application_checked" if application else "content_checked") is not True:
        raise ValueError("explicit content/application check required")


def _spans(w, links, *, numeric=False):
    resolved = []
    if not links:
        raise ValueError("exact fulltext evidence required")
    for link in links:
        if not link.get("span_ids"):
            raise ValueError("exact spans required")
        for sid in link["span_ids"]:
            span = w.lib.span(sid)
            if not span or span["version_id"] != link["source_version_id"] or span["source_id"] != link["source_id"]:
                raise ValueError("evidence version/source mismatch")
            eligible, reason = w.lib.eligible(span, "fulltext")
            if not eligible:
                raise ValueError(reason)
            manifest = w.lib.source(span["source_id"])["manifest"]
            roles = manifest.get("corpus_roles", ["research"])
            if not set(roles) & {"core", "research"}:
                raise ValueError("catalog/interface cannot authorize a scientific claim")
            structured = json.loads(span["structured_json"])
            if numeric and (span["kind"] == "table" or structured.get("table_overlap_indices")) and (structured.get("numeric_review_status") != "verified"
                    or structured.get("missing_footnotes") or structured.get("missing_pages")):
                raise ValueError("table cells/units/footnotes require complete numeric review")
            resolved.append({"source_id": span["source_id"], "source_version_id": span["version_id"], "span_id": sid,
                             "text_hash": span["text_hash"], "locator": json.loads(span["locator_json"]), "corpus_roles": roles})
    return resolved


def _answer_relations(claim):
    from .support import RELATIONS
    task = claim.get("answer_task") or {}
    default = task.get("evidence_relation", "supports")
    relations = [default, *(part.get("evidence_relation", default) for part in task.get("answer_parts", []))]
    if not all(isinstance(relation, str) and relation in RELATIONS for relation in relations):
        raise ValueError("answer task and parts require a valid evidence relation")


def _answer_revision(w, claim):
    reference = claim.get("answer_revision_of")
    if reference is None:
        return None
    if (not isinstance(reference, dict) or reference.get("claim_id") != claim["claim_id"]
            or not isinstance(reference.get("version"), str) or reference["version"] == claim["version"]):
        raise ValueError("answer revision requires a different version of the same claim")
    old = w.lib.theories.execute("SELECT payload_json FROM source_claim WHERE claim_id=? AND version=?",
                                (reference["claim_id"], reference["version"])).fetchone()
    if old is None:
        raise ValueError("answer revision requires an existing predecessor")
    old_task, task = json.loads(old[0]).get("answer_task", {}), claim.get("answer_task", {})
    if not all(task.get(key) and task[key] == old_task.get(key) for key in ("subject", "outcome", "requested_relation")):
        raise ValueError("answer revision must retain the same answer target")
    return reference


def review_claim(w, claim, review):
    _review(review)
    if not all(claim.get(key) for key in ("claim_id", "version", "statement", "scope", "limitations", "evidence_links")):
        raise ValueError("claim identity, statement, scope, limits and exact evidence required")
    _spans(w, claim["evidence_links"], numeric=claim.get("numeric", False))
    _answer_relations(claim)
    _answer_revision(w, claim)
    if claim.get("answer_task"):
        task = claim["answer_task"]
        if not task.get("subject") or not task.get("outcome") or not task.get("requested_relation") or not task.get("answer_parts"):
            raise ValueError("answer task requires subject/outcome/relation and evidence-bound answer parts")
        allowed = {sid for link in claim["evidence_links"] for sid in link["span_ids"]}
        for part in task["answer_parts"]:
            if not part.get("text") or not part.get("span_ids") or not set(part["span_ids"]) <= allowed:
                raise ValueError("each answer part requires exact reviewed evidence")
    existing = w.lib.theories.execute("SELECT * FROM source_claim WHERE claim_id=? AND version=?", (claim["claim_id"], claim["version"])).fetchone()
    if existing:
        if existing["payload_json"] == dumps(claim) and existing["review_json"] == dumps(review):
            return dict(existing)
        raise ValueError("claim version immutable; create a new version")
    with w.lib.theories:
        w.lib.theories.execute("INSERT INTO source_claim VALUES(?,?,'verified',?,?)", (claim["claim_id"], claim["version"], dumps(claim), dumps(review)))
    return {"claim_id": claim["claim_id"], "version": claim["version"], "status": "verified", "reviewer_kind": review["reviewer_kind"]}


def _claim(w, reference):
    row = w.lib.theories.execute("SELECT * FROM source_claim WHERE claim_id=? AND version=?", (reference["claim_id"], reference["version"])).fetchone()
    if not row or row["status"] != "verified":
        raise ValueError("claim_missing_or_not_current")
    claim, review = json.loads(row["payload_json"]), json.loads(row["review_json"])
    _answer_relations(claim)
    _answer_revision(w, claim)
    spans = _spans(w, claim["evidence_links"], numeric=claim.get("numeric", False))
    if review["reviewer_kind"] == "synthetic_fixture" and w.environment_kind != "synthetic_test":
        raise ValueError("synthetic_claim_not_production_authority")
    return claim, review, spans


def review_rule(w, rule, review):
    _review(review, application=True)
    capability = rule.get("requested_capability")
    policy = POLICIES.get(rule.get("capability_policy_version"))
    if policy is None:
        raise ValueError("explicit capability policy required")
    if capability not in policy["capabilities"]:
        raise ValueError("unsupported capability; source authority cannot grant personal inference")
    record_only = policy["version"] == RECORD_POLICY["version"]
    if record_only and (rule.get("evidence_basis") != "product_record_contract" or not rule.get("record_contract") or rule.get("permitted_actions")):
        raise ValueError("record rule requires an explicit record contract and cannot grant candidate actions")
    if (not record_only and not rule.get("claim_refs")) or not rule.get("implementation_validation_refs") or not rule.get("conditions"):
        raise ValueError("claims, implementation references and applicability conditions required")
    if not rule.get("application_logic") or not rule.get("limits"):
        raise ValueError("product application logic and extrapolation limits required")
    if capability in {"plan_candidate", "trial_candidate"} and (not rule.get("exit_conditions") or not rule.get("followup") or not rule.get("numeric_provenance")):
        raise ValueError("candidate requires numerical provenance, exit and follow-up contracts")
    if capability in {"plan_candidate", "trial_candidate"} and not rule.get("permitted_actions"):
        raise ValueError("candidate requires explicit permitted_actions")
    check_conditions(rule["conditions"], {})  # validate condition syntax; unknown is expected here
    for reference in rule.get("claim_refs", []):
        _claim(w, reference)
    if review["reviewer_kind"] == "synthetic_fixture" and w.environment_kind != "synthetic_test":
        raise ValueError("synthetic_rule_not_production_authority")
    existing = w.lib.theories.execute("SELECT * FROM application_rule WHERE rule_id=? AND version=?", (rule["rule_id"], rule["rule_version"])).fetchone()
    if existing and existing["review_json"] != "{}":
        if existing["payload_json"] == dumps(rule) and existing["review_json"] == dumps(review):
            return {"rule_id": rule["rule_id"], "status": existing["status"]}
        raise ValueError("reviewed application rule immutable; create a new version")
    with w.lib.theories:
        if rule.get("supersedes"):
            w.lib.theories.execute("UPDATE application_rule SET status='superseded' WHERE rule_id=? AND version=?", (rule["rule_id"], rule["supersedes"]))
            w.lib.theories.execute("INSERT INTO core_lifecycle(object_type,object_id,version,action,actor,rationale,created_at) VALUES('rule',?,?,'superseded',?,?,?)",
                (rule["rule_id"], rule["supersedes"], review["reviewer"], "Explicit reviewed replacement: " + rule["rule_version"], now()))
        w.lib.theories.execute("INSERT OR REPLACE INTO application_rule VALUES(?,?,'active',?,?)", (rule["rule_id"], rule["rule_version"], dumps(rule), dumps(review)))
    return {"rule_id": rule["rule_id"], "version": rule["rule_version"], "status": "active", "policy": policy["version"]}


def core_principles(w, route, context, release_id=None):
    result, excluded = [], []
    frozen = None
    if release_id:
        release = w.lib.theories.execute("SELECT manifest_json FROM core_release WHERE release_id=?", (release_id,)).fetchone()
        frozen = {(r["rule_id"], r["version"]) for r in json.loads(release[0])["rules"]} if release else set()
    for row in w.lib.theories.execute("SELECT * FROM application_rule ORDER BY rule_id,version"):
        if frozen is not None and (row["rule_id"], row["version"]) not in frozen:
            continue
        rule, review = json.loads(row["payload_json"]), json.loads(row["review_json"])
        if route not in rule.get("routes", ["progression", "plateau"]):
            continue
        if rule.get("requested_capability") not in {"plan_candidate", "trial_candidate"}:
            continue
        reason, spans, claims = None, [], []
        if row["status"] != "active":
            reason = "rule_" + row["status"]
        elif not rule.get("permitted_actions"):
            reason = "rule_permitted_actions_missing"
        else:
            try:
                for reference in rule["claim_refs"]:
                    claim, claim_review, evidence = _claim(w, reference)
                    checked = check_conditions(claim.get("conditions", []), context)
                    if not checked["matches"]:
                        reason = "claim_scope:" + dumps(checked["issues"])
                    spans.extend(evidence)
                    claims.append({"claim_id": claim["claim_id"], "version": claim["version"], "reviewer_kind": claim_review["reviewer_kind"]})
            except ValueError as exc:
                reason = str(exc)
        checked = check_conditions(rule.get("conditions", []), context)
        if not reason and not checked["matches"]:
            reason = "applicability:" + dumps(checked["issues"])
        if reason:
            excluded.append({"theory_id": row["rule_id"], "version": row["version"], "reason": reason,
                             "required_context": rule.get("conditions", []), "issues": checked["issues"]})
            continue
        result.append({"theory_id": row["rule_id"], "rule_id": row["rule_id"], "version": row["version"], "rule_version": row["version"],
            "review_status": "approved", "capability": "progression_candidate" if rule["requested_capability"] == "plan_candidate" else "trial_candidate",
            "reviewer": review["reviewer"], "reviewer_kind": review["reviewer_kind"], "reviewed_at": review["reviewed_at"],
            "capability_policy_version": POLICY["version"], "independent_expert_validation": False,
            "evidence_spans": spans, "claim_refs": claims, "rights_verified": True, "scope_matches": True,
            "applicability": {"required": rule["conditions"]}, "implementation_tests": rule["implementation_validation_refs"],
            "numeric_provenance": rule["numeric_provenance"], "application_logic": rule["application_logic"],
            "permitted_actions": rule.get("permitted_actions", []),
            "exit_conditions": rule["exit_conditions"], "followup": rule["followup"], "limits": rule["limits"]})
    return result, excluded


def core_status(w):
    claims = [dict(r) for r in w.lib.theories.execute("SELECT claim_id,version,status FROM source_claim")]
    rules = []
    for row in w.lib.theories.execute("SELECT * FROM application_rule ORDER BY rule_id,version"):
        payload = json.loads(row["payload_json"])
        issues = []
        for reference in payload.get("claim_refs", []):
            try:
                _claim(w, reference)
            except ValueError as exc:
                issues.append(str(exc))
        effective = row["status"] == "active" and not issues
        rules.append({"rule_id": row["rule_id"], "version": row["version"], "status": row["status"], "effective": effective,
                      "capability": payload["requested_capability"], "dependency_issues": issues,
                      "source_gaps": payload.get("remaining_source_gaps", payload.get("claim_topics_to_verify", []) if not effective else []),
                      "coverage_scope": payload.get("coverage_scope", "declared_rule_scope"),
                      "capability_policy_version": payload.get("capability_policy_version")})
    return {"policy": POLICY, "policies": POLICIES, "claims": claims, "rules": rules,
            "distinct_rule_count": len({r["rule_id"] for r in rules}),
            "effective_rule_count": len({r["rule_id"] for r in rules if r["effective"]}),
            "effective_candidate_rule_count": len({r["rule_id"] for r in rules if r["effective"] and r["capability"] in {"plan_candidate", "trial_candidate"}}),
            "effective_explanation_rule_count": len({r["rule_id"] for r in rules if r["effective"] and r["capability"] == "source_explanation"}),
            "effective_record_rule_count": len({r["rule_id"] for r in rules if r["effective"] and r["capability"] in RECORD_POLICY["capabilities"]}),
            "chapter_coverage": [dict(r) for r in w.lib.sources.execute("SELECT * FROM chapter_coverage")],
            "independent_human_review_count": 0}


def release_core(w, release_id):
    rules = [dict(r) for r in w.lib.theories.execute("SELECT * FROM application_rule WHERE status='active' ORDER BY rule_id,version")]
    for row in rules:
        for reference in json.loads(row["payload_json"]).get("claim_refs", []):
            _claim(w, reference)
    used_policies = {json.loads(r["payload_json"])["capability_policy_version"] for r in rules}
    manifest = {"rules": rules, "claims": [dict(r) for r in w.lib.theories.execute("SELECT * FROM source_claim WHERE status='verified' ORDER BY claim_id,version")], "policy": POLICY}
    if used_policies - {POLICY["version"]}:
        manifest["additional_policies"] = {key: POLICIES[key] for key in sorted(used_policies - {POLICY["version"]})}
    encoded = dumps(manifest)
    old = w.lib.theories.execute("SELECT sha256 FROM core_release WHERE release_id=?", (release_id,)).fetchone()
    if old and old[0] != digest(encoded.encode()):
        raise ValueError("core release immutable")
    with w.lib.theories:
        w.lib.theories.execute("INSERT OR IGNORE INTO core_release VALUES(?,?,?,?)", (release_id, encoded, digest(encoded.encode()), now()))
    return {"release_id": release_id, "sha256": digest(encoded.encode()), **manifest}


def core_state(w, object_type, object_id, version, action, *, actor, rationale):
    if object_type not in {"claim", "rule"} or action not in {"disabled", "revoked", "needs_review"} or not actor or not rationale:
        raise ValueError("identified actor, rationale and supported lifecycle action required")
    table, key = ("source_claim", "claim_id") if object_type == "claim" else ("application_rule", "rule_id")
    if not w.lib.theories.execute(f"SELECT 1 FROM {table} WHERE {key}=? AND version=?", (object_id, version)).fetchone():
        raise ValueError("unknown knowledge object/version")
    with w.lib.theories:
        w.lib.theories.execute(f"UPDATE {table} SET status=? WHERE {key}=? AND version=?", (action, object_id, version))
        w.lib.theories.execute("INSERT INTO core_lifecycle(object_type,object_id,version,action,actor,rationale,created_at) VALUES(?,?,?,?,?,?,?)",
                              (object_type, object_id, version, action, actor, rationale, now()))
    return {"object_type": object_type, "object_id": object_id, "version": version, "status": action, "immutable_content_preserved": True}
