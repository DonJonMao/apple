"""Five logical domains on the existing two libraries; immutable version bindings."""
from __future__ import annotations

import json
from pathlib import Path

from .store import digest, dumps, now
from .transactions import atomic

DOMAIN_IDS = {"physiology", "strength", "wearable", "recovery", "cardiometabolic"}
RELATIONS = {"supports", "defines", "limits", "applies_to", "conflicts_with", "supersedes", "required_by"}


def observation_configuration():
    return json.loads((Path(__file__).parent / "data/observation_domains_v15.json").read_text())


def configuration(*, include_observations=False):
    config = json.loads((Path(__file__).parent / "data/metric_domains_v15.json").read_text())
    if include_observations:
        extension = observation_configuration()
        config['profiles'].update(extension['profiles'])
        config['observation_extensions'] = {key: extension[key] for key in ('schema_version', 'registry', 'scope')}
        config['observation_extensions']['metric_ids'] = sorted(extension['profiles'])
    return config


def profile_version(metric_id):
    if metric_id in configuration()['profiles']:
        return configuration()['schema_version']
    if metric_id in observation_configuration()['profiles']:
        return observation_configuration()['schema_version']
    raise ValueError('unknown_metric_or_observation_profile')


def ensure_schema(w):
    statements = [
        """CREATE TABLE IF NOT EXISTS knowledge_domain_assignment(
          object_type TEXT NOT NULL,object_id TEXT NOT NULL,object_version TEXT NOT NULL,
          domain_id TEXT NOT NULL,status TEXT NOT NULL,payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL,PRIMARY KEY(object_type,object_id,object_version,domain_id))""",
        """CREATE TABLE IF NOT EXISTS knowledge_evidence_edge(
          edge_id TEXT PRIMARY KEY,from_type TEXT NOT NULL,from_id TEXT NOT NULL,from_version TEXT NOT NULL,
          relation TEXT NOT NULL,to_type TEXT NOT NULL,to_id TEXT NOT NULL,to_version TEXT NOT NULL,
          payload_json TEXT NOT NULL,created_at TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS knowledge_edge_target ON knowledge_evidence_edge(to_type,to_id,to_version)",
    ]
    # No executescript: it would commit an existing caller transaction.
    conn = w.lib.theories
    conn.execute("SAVEPOINT domains_v15")
    try:
        for statement in statements:
            conn.execute(statement)
        conn.execute("RELEASE domains_v15")
    except BaseException:
        conn.execute("ROLLBACK TO domains_v15")
        conn.execute("RELEASE domains_v15")
        raise


def _object(w, kind, identity, version):
    if kind == "source_version":
        return w.lib.sources.execute("SELECT 1 FROM version WHERE source_id=? AND version_id=?", (identity, version)).fetchone()
    if kind in {"claim", "rule"}:
        table, key = ("source_claim", "claim_id") if kind == "claim" else ("application_rule", "rule_id")
        return w.lib.theories.execute(f"SELECT 1 FROM {table} WHERE {key}=? AND version=?", (identity, version)).fetchone()
    if kind == "span":
        return w.lib.sources.execute("SELECT 1 FROM span WHERE span_id=? AND version_id=?", (identity, version)).fetchone()
    if kind == "metric":
        return identity in configuration(include_observations=True)["profiles"] and version == profile_version(identity)
    return False


def assign(w, *, object_type, object_id, object_version, domains, status, actor, rationale):
    ensure_schema(w)
    if not domains or not set(domains) <= DOMAIN_IDS or status not in {"provisional", "content_checked"} or not actor or not rationale:
        raise ValueError("invalid_domain_assignment")
    if not _object(w, object_type, object_id, object_version):
        raise ValueError("domain_object_missing_or_wrong_version")
    payload = {"actor": actor, "rationale": rationale, "scientific_or_candidate_approval": False}
    conn = w.lib.theories
    conn.execute("SAVEPOINT assign_domains")
    try:
        for domain in sorted(set(domains)):
            key = (object_type, object_id, object_version, domain)
            old = conn.execute("SELECT status,payload_json FROM knowledge_domain_assignment WHERE object_type=? AND object_id=? AND object_version=? AND domain_id=?", key).fetchone()
            if old and (old["status"] != status or old["payload_json"] != dumps(payload)):
                raise ValueError("immutable_domain_assignment_conflict")
            conn.execute("INSERT OR IGNORE INTO knowledge_domain_assignment VALUES(?,?,?,?,?,?,?)", (*key, status, dumps(payload), now()))
        conn.execute("RELEASE assign_domains")
    except BaseException:
        conn.execute("ROLLBACK TO assign_domains")
        conn.execute("RELEASE assign_domains")
        raise


def link(w, *, origin, relation, target, span_ids, applicability, actor, rationale,
         evidence_types=None, review=None):
    ensure_schema(w)
    if relation not in RELATIONS or not actor or not rationale or not isinstance(applicability, dict) or not span_ids:
        raise ValueError("traceable_evidence_edge_required")
    for endpoint in (origin, target):
        if not _object(w, endpoint["type"], endpoint["id"], endpoint["version"]):
            raise ValueError("edge_object_missing_or_wrong_version")
    from .applicability import context_match
    from .core import _claim, _review
    context_match(applicability, {})  # Validate typed conditions without recording private context.
    bound_claim_spans = []
    for endpoint in (origin, target):
        if endpoint["type"] == "claim":
            _, _, exact = _claim(w, {"claim_id": endpoint["id"], "version": endpoint["version"]})
            bound_claim_spans.append({s["span_id"] for s in exact})
    supplied = set(span_ids)
    if bound_claim_spans and (not supplied <= set.union(*bound_claim_spans)
                             or any(not supplied & s for s in bound_claim_spans)):
        raise ValueError("edge_evidence_must_bind_each_claim_endpoint")
    if target["type"] == "metric":
        if origin["type"] != "claim" or relation not in {"applies_to", "defines", "limits", "required_by"}:
            raise ValueError("metric_binding_requires_reviewed_claim")
        _review(review or {}, application=True)
        if review["reviewer_kind"] == "synthetic_fixture" and w.environment_kind != "synthetic_test":
            raise ValueError("synthetic_metric_binding_not_production_authority")
        allowed = configuration(include_observations=True)["profiles"][target["id"]]["required_evidence_types"]
        if not evidence_types or not set(evidence_types) <= set(allowed):
            raise ValueError("explicit_profile_evidence_types_required")
    evidence = []
    for sid in span_ids:
        span = w.lib.span(sid, include_metadata=False)
        if not span or not w.lib.eligible(span, "fulltext")[0]:
            raise ValueError("edge_requires_current_eligible_exact_span")
        evidence.append({"span_id": sid, "source_id": span["source_id"], "source_version": span["version_id"], "text_hash": span["text_hash"]})
    payload = {"origin": origin, "relation": relation, "target": target, "evidence": evidence,
               "applicability": applicability, "actor": actor, "rationale": rationale,
               "evidence_types": sorted(set(evidence_types or [])), "application_review": review,
               "grants_capability": False}
    identity = digest(dumps(payload).encode())
    with atomic(w.lib.theories):
        w.lib.theories.execute("INSERT OR IGNORE INTO knowledge_evidence_edge VALUES(?,?,?,?,?,?,?,?,?,?)",
            (identity, origin["type"], origin["id"], origin["version"], relation,
             target["type"], target["id"], target["version"], dumps(payload), now()))
    return identity


def object_domains(w, kind, identity, version):
    return [dict(r) for r in w.lib.theories.execute(
        "SELECT domain_id,status FROM knowledge_domain_assignment WHERE object_type=? AND object_id=? AND object_version=? ORDER BY domain_id",
        (kind, identity, version))]
