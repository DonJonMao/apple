"""Fixed metric/task routing and permission-first hybrid public evidence retrieval."""
from __future__ import annotations

import json
import math
from collections import Counter

from . import domains, query_forms, table_projection, vector_index
from .applicability import context_match
from .model_services import ModelUnavailable, load_services, rerank_windows
from .retrieval import tokens
from .store import digest, dumps, now
from .transactions import atomic

MODES = {"lexical", "dense", "hybrid", "hybrid_rerank"}
RETRIEVAL_VERSION = "metric-hybrid-1.5.4"


def _lexical(query, candidates):
    query_terms = set(tokens(query))
    bags = {c["candidate_id"]: Counter(tokens(c["content"] + " " + c["section_path"])) for c in candidates}
    frequencies = Counter(token for bag in bags.values() for token in query_terms if token in bag)
    scores = {}
    for identity, bag in bags.items():
        scores[identity] = sum((1+math.log(bag[token])) * math.log(1+(len(candidates)+1)/(frequencies[token]+1))
                               for token in query_terms if bag[token])
    ranked = sorted((identity for identity in bags if scores[identity] > 0), key=lambda i: (-scores[i], i))
    return ranked


def reciprocal_rank_fusion(rankings, *, constant=60):
    """Ranks alone are fused; lexical/vector/relevance scores are never summed."""
    scores = Counter()
    if type(constant) is not int or constant <= 0:
        raise ValueError("positive_rrf_constant_required")
    for ranking in rankings:
        if len(ranking) != len(set(ranking)):
            raise ValueError("duplicate_rank_identity")
        for position, identity in enumerate(ranking, 1):
            scores[identity] += 1 / (constant + position)
    return sorted(scores, key=lambda key: (-scores[key], key))


def _release(w, release_id):
    if release_id is None:
        return None, None, {"release_id": None, "membership": "current"}, None
    row = w.lib.theories.execute("SELECT manifest_json,sha256 FROM core_release WHERE release_id=?", (release_id,)).fetchone()
    if row:
        refs = {(c["claim_id"], c["version"]) for c in json.loads(row[0])["claims"]}
        from .core import _claim
        span_ids = set()
        for identity, version in refs:
            try:
                _, _, evidence = _claim(w, {"claim_id": identity, "version": version})
                span_ids.update(e["span_id"] for e in evidence)
            except ValueError:
                continue
        return span_ids, refs, {"release_id": release_id, "sha256": row[1], "membership": "frozen_core_claim_spans_current_validity"}, None
    row = w.lib.sources.execute("SELECT manifest_json,sha256 FROM index_release WHERE release_id=?", (release_id,)).fetchone()
    if not row:
        raise ValueError("unknown_retrieval_release")
    manifest = json.loads(row[0])
    if manifest.get("schema") != "metric-index-release-1.5.0":
        raise ValueError("incompatible_index_release")
    if manifest.get("profile_sha256") != digest(dumps(domains.configuration()).encode()):
        raise ValueError("frozen_profile_configuration_changed")
    if (manifest.get('observation_profile_sha256') is not None
            and manifest['observation_profile_sha256'] != digest(dumps(domains.observation_configuration()).encode())):
        raise ValueError('frozen_observation_profile_configuration_changed')
    if (manifest.get('query_forms_sha256') is not None
            and manifest['query_forms_sha256'] != query_forms.identity()):
        raise ValueError('frozen_query_forms_configuration_changed')
    refs = {(c['claim_id'], c['version']) for c in manifest['claim_refs']}
    return set(manifest["span_ids"]), refs, {"release_id": release_id, "sha256": row[1],
        "membership": "frozen_index_and_bindings_current_validity", "edge_ids": manifest['edge_ids'],
        "query_forms_sha256": manifest.get('query_forms_sha256'),
        "projection_set_ids": manifest.get('projection_set_ids', {})}, manifest['unit_assignments']


def _claim_links(w, context, allowed_refs):
    from .core import _answer_revision, _claim
    rows = list(w.lib.theories.execute("SELECT * FROM source_claim ORDER BY claim_id,version"))
    if allowed_refs is not None:
        rows = [r for r in rows if (r["claim_id"], r["version"]) in allowed_refs]
    replaced = set()
    for row in rows:
        predecessor = _answer_revision(w, json.loads(row["payload_json"]))
        if predecessor:
            replaced.add((predecessor["claim_id"], predecessor["version"]))
    links, accepted, excluded = {}, {}, []
    roles = set(context.get("corpus_roles", ["core", "research"]))
    for row in rows:
        ref = (row["claim_id"], row["version"])
        try:
            if ref in replaced:
                raise ValueError("answer_version_replaced")
            claim, review, evidence = _claim(w, {"claim_id": ref[0], "version": ref[1]})
            matched, reason = context_match(claim.get("conditions", []), context)
            if not matched:
                raise ValueError(reason)
            if any(not set(s["corpus_roles"]) & roles for s in evidence):
                raise ValueError("corpus_partition_excluded")
        except ValueError as exc:
            excluded.append({"claim_id": ref[0], "claim_version": ref[1], "reason": str(exc)})
            continue
        accepted[ref] = {"review": {"reviewer_kind": review["reviewer_kind"],
            "claims": [{"text": claim["statement"]}]},
            "scope": claim['scope'], "limitations": claim['limitations'],
            "spans": [w.lib.span(e["span_id"], include_metadata=False) for e in evidence]}
        for span in evidence:
            links.setdefault(span["span_id"], []).append({"claim_id": ref[0], "claim_version": ref[1]})
    return links, accepted, excluded


def eligible_candidates(w, requested_domains, context, release_id):
    domains.ensure_schema(w)
    vector_index.ensure_schema(w)
    allowed_spans, allowed_refs, release, frozen_assignments = _release(w, release_id)
    links, claims, excluded = _claim_links(w, context, allowed_refs)
    # Ownership survives revocation. A rejected claim's exact evidence cannot
    # silently re-enter through the unreviewed-document path.
    owned = set()
    for row in w.lib.theories.execute("SELECT payload_json FROM source_claim"):
        for link in json.loads(row[0]).get("evidence_links", []):
            owned.update(link["span_ids"])
    roles = set(context.get("corpus_roles", ["core", "research"]))
    if not roles or not roles <= {"core", "research"}:
        raise ValueError("metric_retrieval_science_partitions_only")
    matches = vector_index.current_units(w, requested_domains)
    excluded.extend(vector_index.prefiltered_version_groups(w))
    candidates = []
    for row in matches:
        assignment = frozen_assignments.get(row['span_id']) if frozen_assignments is not None else vector_index.unit_assignment(w, row)
        if assignment is None:
            continue
        assigned = assignment['domains']
        if not set(assigned).intersection(requested_domains):
            continue
        sid = row["span_id"]
        if sid in owned and sid not in links:
            excluded.append({"span_id": sid, "reason": "claim_rejected_no_background_bypass"})
            continue
        if allowed_spans is not None and sid not in allowed_spans:
            excluded.append({"span_id": sid, "reason": "outside_frozen_release"})
            continue
        span = w.lib.span(sid, include_metadata=False)
        ok, why = w.lib.eligible(span, "fulltext") if span else (False, "missing_span")
        if not ok:
            excluded.append({"span_id": sid, "reason": why})
            continue
        if not span["text"].strip():
            excluded.append({"span_id": sid, "reason": "empty_structured_unit"})
            continue
        source = w.lib.source(span["source_id"])["manifest"]
        if not set(source.get("corpus_roles", ["research"])) & roles:
            excluded.append({"span_id": sid, "reason": "corpus_partition_excluded"})
            continue
        # Unknown claim applicability never becomes applicable because its raw
        # excerpt is present in an index; such excerpts are reading-only.
        rights = json.loads(span["rights_json"])
        if rights.get("noncommercial_only") and context.get("usage_scope", "local_noncommercial") != "local_noncommercial":
            excluded.append({"span_id": sid, "reason": "noncommercial_scope_required"})
            continue
        candidates.append({"candidate_id": sid, "source_id": span["source_id"], "source_version": span["version_id"],
            "claim_refs": links.get(sid, []), "span_id": sid, "domains": sorted(set(assigned) & set(requested_domains)),
            "domain_assignment_status": assignment['status'], "domain_review_id": assignment['review_id'],
            "locator": json.loads(span["locator_json"]),
            "section_path": span["section_path"], "parent_section_id": row["parent_id"],
            "applicability": {"status": "reviewed_claim_conditions_match" if sid in links else "unreviewed_source_reading_only"},
            "applicability_status": "matched" if sid in links else "not_reviewed_for_metric_inference",
            "rights_status": {key: rights.get(key) for key in ("status", "license_id", "index_allowed", "rights_scope", "noncommercial_only")},
            "review_status": "claim_checked" if sid in links else "source_only_claim_review_pending",
            "content": span["text"], "input_content_hash": span["text_hash"],
            "evidence_role": "reviewed_claim_evidence" if sid in links else "background_only",
            "source_metadata": {key: source.get(key) for key in ("title", "year", "authors", "edition_id", "canonical_url")}})
        if release_id is not None:
            # Old frozen releases have no structural children. They never silently
            # acquire a projection created after their membership was frozen.
            candidates[-1]['allowed_projection_set_id'] = release.get('projection_set_ids', {}).get(sid, '')
    return candidates, claims, excluded, release


def _dense(w, provider, query, candidates):
    try:
        import numpy as np
    except ImportError:
        np = None
    vector = vector_index.cached(w, provider, query, "query")
    if vector is None:
        vector = provider.embed_queries([query])[0]
        vector_index.save_vectors(w, provider, [query], [vector], "query")
    similarities, missing = {}, 0

    def similarity(doc):
        if len(doc) != len(vector):
            raise ModelUnavailable("query_document_dimension_mismatch")
        return float(np.dot(doc, vector)) if np is not None else sum(a*b for a, b in zip(doc, vector))

    for candidate in candidates:
        doc = vector_index.cached(w, provider, candidate["content"], "document")
        if doc is not None:
            similarities[candidate['candidate_id']] = similarity(doc)
            continue
        span = w.lib.span(candidate['span_id'], include_metadata=False)
        if (not span or not w.lib.eligible(span, 'fulltext')[0]
                or span['text_hash'] != candidate['input_content_hash']):
            missing += 1
            continue
        try:
            projection = table_projection.current(w, span, allowed_id=candidate.get('allowed_projection_set_id'))
        except (ValueError, TypeError, KeyError):
            raise ModelUnavailable('table_projection_manifest_integrity_invalid') from None
        if projection is None:
            missing += 1
            continue
        scores = []
        for child in projection['children']:
            child_doc = vector_index.cached_hash(w, provider, child['input_hash'], 'document')
            if child_doc is not None:
                scores.append((similarity(child_doc), child))
        info = {"projection_set_id": projection['projection_set_id'], "projection_version": table_projection.VERSION,
            "parent_span_id": candidate['span_id'], "parent_text_hash": span['text_hash'],
            "expected_child_vectors": len(projection['children']), "available_child_vectors": len(scores),
            "complete": len(scores) == len(projection['children']),
            "aggregation": "max_child_cosine_complete_projection", "original_parent_returned": True}
        candidate['dense_projection'] = info
        if not info['complete']:
            missing += 1
            continue  # A subset of rows cannot masquerade as a complete searchable table.
        score, winner = sorted(scores, key=lambda item: (-item[0], item[1]['child_id']))[0]
        info['winning_child'] = winner
        info['winning_cosine'] = score
        similarities[candidate['candidate_id']] = score
    return sorted(similarities, key=lambda key: (-similarities[key], key)), missing


def _edge_current(w, payload):
    return all((span := w.lib.span(e["span_id"], include_metadata=False))
               and span["text_hash"] == e["text_hash"] and w.lib.eligible(span, "fulltext")[0]
               for e in payload["evidence"])


def _claim_requirements(w, reference, claims, context, allowed_edges, path=()):
    """Close only explicit required_by claim edges; cycles never authorize inference."""
    from .core import _claim
    if reference in path or reference not in claims:
        return None
    try:
        claim, _, _ = _claim(w, {"claim_id": reference[0], "version": reference[1]})
        if not context_match(claim.get("conditions", []), context)[0]:
            return None
    except ValueError:
        return None
    span_ids = {s["span_id"] for s in claims[reference]["spans"]}
    dependencies = set()
    for row in w.lib.theories.execute("""SELECT * FROM knowledge_evidence_edge
            WHERE relation='required_by' AND to_type='claim' AND to_id=? AND to_version=? ORDER BY edge_id""", reference):
        if allowed_edges is not None and row["edge_id"] not in allowed_edges:
            continue
        payload = json.loads(row["payload_json"])
        matched, reason = context_match(payload["applicability"], context)
        if not matched:
            if reason.startswith("scope_mismatch:"):
                continue
            return None  # Unknown applicability is not proof that a prerequisite is unnecessary.
        if row["from_type"] != "claim" or not _edge_current(w, payload):
            return None
        ref = (row["from_id"], row["from_version"])
        required = _claim_requirements(w, ref, claims, context, allowed_edges, (*path, reference))
        if required is None:
            return None
        span_ids.update(required[0])
        dependencies.update({ref, *required[1]})
    return span_ids, dependencies


def _metric_claims(w, metric_id, claims, selected, context, allowed_edges=None):
    from .core import _claim
    matches, conflicts = [], []
    all_ids = {("claim", key[0], key[1]) for key in claims}
    for row in w.lib.theories.execute("SELECT * FROM knowledge_evidence_edge ORDER BY edge_id"):
        if allowed_edges is not None and row['edge_id'] not in allowed_edges and row['relation'] != 'conflicts_with':
            continue
        payload = json.loads(row["payload_json"])
        if not context_match(payload["applicability"], context)[0]:
            continue
        if not _edge_current(w, payload):
            continue
        if row["relation"] == "conflicts_with":
            endpoints = [(row["from_type"], row["from_id"], row["from_version"]), (row["to_type"], row["to_id"], row["to_version"])]
            related = w.lib.theories.execute(
                "SELECT from_id,from_version FROM knowledge_evidence_edge WHERE to_type='metric' AND to_id=?",
                (metric_id,)).fetchall()
            relevant = {("claim", r[0], r[1]) for r in related}
            if all(endpoint in all_ids for endpoint in endpoints) and any(e in relevant for e in endpoints):
                conflicts.append(payload)
        if (row["relation"] in {"applies_to", "limits", "defines", "required_by"} and row["from_type"] == "claim"
                and row["to_type"] == "metric" and row["to_id"] == metric_id
                and row["to_version"] == domains.profile_version(metric_id)
                and (row["from_id"], row["from_version"]) in claims):
            try:
                _claim(w, {'claim_id': row['from_id'], 'version': row['from_version']})
            except ValueError:
                continue
            candidate = claims[(row["from_id"], row["from_version"])]
            span_ids = {s["span_id"] for s in candidate["spans"]}
            required = _claim_requirements(w, (row["from_id"], row["from_version"]), claims, context, allowed_edges)
            if required is None:
                continue
            required_ids, dependencies = required
            edge_ids = {e["span_id"] for e in payload["evidence"]}
            checked = (payload.get("application_review", {}).get("application_checked") is True
                       and payload.get("evidence_types") and edge_ids <= span_ids)
            if span_ids and required_ids <= selected.keys() and checked and all(
                    selected[s]["domain_assignment_status"] == "content_checked" for s in required_ids):
                prerequisites = [{"claim_id": ref[0], "claim_version": ref[1], "scope": claims[ref]["scope"],
                    "limitations": claims[ref]["limitations"]} for ref in sorted(dependencies)]
                matches.append({"claim_id": row["from_id"], "claim_version": row["from_version"],
                    "statements": [c["text"] for c in candidate["review"]["claims"]], "evidence_span_ids": sorted(required_ids),
                    "direct_evidence_span_ids": sorted(span_ids),
                    "required_claim_refs": [{"claim_id": ref[0], "claim_version": ref[1]} for ref in sorted(dependencies)],
                    "required_claims": prerequisites,
                    "metric_relation": row["relation"], "reviewer_kind": candidate["review"].get("reviewer_kind"),
                    "evidence_types": payload["evidence_types"],
                    "scope": candidate['scope'], "limitations": list(dict.fromkeys([
                        *candidate['limitations'], *(limit for dep in prerequisites for limit in dep['limitations'])])),
                    "domains": sorted({d for sid in required_ids for d in selected[sid]["domains"]}),
                    "application_edge": payload})
    return matches, conflicts


def _select_evidence(w, metric_id, profile, claims, by_id, ranking, context, k, allowed_edges):
    """Allocate the same K spans to complete reviewed metric evidence groups.

    A group needs a direct evidence anchor in the retrieval candidate pool.
    Dependencies may expand from that anchor only through exact reviewed links.
    Prefer groups filling an unmet contract requirement, then their best rank.
    No relevance scores or physiological weights are combined here.
    """
    groups, _ = _metric_claims(w, metric_id, claims, by_id, context, allowed_edges)
    ranks = {identity: rank for rank, identity in enumerate(ranking)}
    groups = [g for g in groups if set(g["direct_evidence_span_ids"]) & ranks.keys()]
    chosen, allocations, rejected = [], [], []
    required_types = set(profile["required_evidence_types"])
    required_domains = set(profile.get("required_domains", profile["primary_domains"]))
    types, covered_domains = set(), set()
    while groups:
        groups.sort(key=lambda g: (
            not (set(g["evidence_types"]) & (required_types - types)
                 or set(g["domains"]) & (required_domains - covered_domains)),
            min(ranks[s] for s in g["direct_evidence_span_ids"] if s in ranks),
            g["claim_id"], g["claim_version"]))
        group = groups.pop(0)
        missing = [s for s in group["evidence_span_ids"] if s not in chosen]
        if len(chosen) + len(missing) > k:
            rejected.append({"claim_id": group["claim_id"], "claim_version": group["claim_version"],
                             "reason": "complete_group_exceeds_remaining_span_budget"})
            continue
        if not all(_still_current(w, by_id[s], context) for s in group["evidence_span_ids"]):
            continue
        missing.sort(key=lambda s: (ranks.get(s, len(ranking)), s))
        chosen.extend(missing)
        types.update(group["evidence_types"])
        covered_domains.update(group["domains"])
        allocations.append({key: group[key] for key in ("claim_id", "claim_version", "evidence_span_ids", "required_claim_refs")})
    for identity in ranking:
        if len(chosen) >= k:
            break
        if identity not in chosen:
            chosen.append(identity)
    return chosen, {"strategy": "rank_anchored_complete_reviewed_groups", "span_budget": k,
        "selected_span_count": len(chosen), "groups": allocations, "rejected_groups": rejected,
        "dependency_expansion_ids": [s for s in chosen if s not in ranks]}


def _still_current(w, candidate, context):
    """A remote ranking call may outlive a concurrent source/claim revocation."""
    from .core import _claim
    span = w.lib.span(candidate['span_id'], include_metadata=False)
    if not span or not w.lib.eligible(span, 'fulltext')[0]:
        return False
    if json.loads(span['rights_json']).get('noncommercial_only') and context.get('usage_scope', 'local_noncommercial') != 'local_noncommercial':
        return False
    if not candidate['claim_refs']:
        return True
    for reference in candidate['claim_refs']:
        try:
            claim, _, _ = _claim(w, {'claim_id': reference['claim_id'], 'version': reference['claim_version']})
            if context_match(claim.get('conditions', []), context)[0]:
                return True
        except ValueError:
            pass
    return False


def retrieve_for_metric(w, metric_id, analysis_task, metric_result, context=None, release_id=None, *,
                        mode="hybrid_rerank", k=6, services=None, query_form=None):
    from healthzip.science.contracts import validate_result
    config = domains.configuration(include_observations=True)
    if metric_id not in config["profiles"] or analysis_task not in {"explain_metric", *config["functions"]}:
        raise ValueError("unknown_fixed_metric_or_analysis_task")
    if not isinstance(metric_result, dict) or metric_result.get("metric_id") != metric_id:
        raise ValueError("matching_computed_metric_result_required")
    validate_result(metric_result)
    if mode not in MODES or type(k) is not int or not 1 <= k <= 20:
        raise ValueError("invalid_retrieval_mode_or_budget")
    profile = config["profiles"][metric_id]
    profile_version = domains.profile_version(metric_id)
    if analysis_task != "explain_metric" and analysis_task not in profile["analysis_functions"]:
        raise ValueError("metric_not_declared_for_analysis_function")
    context = dict(context or {})  # Kept local, never interpolated into a model query.
    requested = list(dict.fromkeys(profile["primary_domains"] + profile["secondary_domains"]))
    query, query_identity = query_forms.select(metric_id, analysis_task, config, form=query_form)
    query_key = [metric_id, analysis_task, profile_version, release_id]
    if query_form is not None:
        query_key.append(query_identity)
    result = {"query_id": digest(dumps(query_key).encode()),
        "task_id": analysis_task, "metric_id": metric_id, "requested_domains": requested, "retrieved_domains": [],
        "matched_claims": [], "evidence_spans": [], "applicability": [], "source_metadata": [], "limitations": [],
        "conflicts": [], "capability_permissions": {"source_explanation": False, "candidate": False,
            "candidate_authority": "existing_application_rule_service_only"},
        "retrieval_audit": {"version": RETRIEVAL_VERSION, "profile_version": profile_version,
            "query_form": query_identity,
            "requested_mode": mode, "requested_k": k, "network_payload": "static_metric_task_and_eligible_public_evidence_only",
            "personal_metric_values_sent": False, "private_context_sent": False, "retrieval_degraded": False}}
    audit = result["retrieval_audit"]
    if profile["retrieval_profile"] == "deterministic_no_rag":
        result["status"] = "not_required_deterministic_computation"
        return _record_audit(w, result)
    if context.get("requested_other_user") and context.get("requested_other_user") != context.get("user_id"):
        result.update(status="insufficient_evidence", limitations=["tenant_isolation_required"])
        return _record_audit(w, result)
    if query_form is not None and release_id is not None:
        if _release(w, release_id)[2].get('query_forms_sha256') != query_identity['registry_sha256']:
            raise ValueError('frozen_release_does_not_pin_query_forms')
    candidates, claims, excluded, release = eligible_candidates(w, requested, context, release_id)
    audit.update(excluded=excluded, release=release, eligible_candidate_count=len(candidates))
    audit['candidate_ids_sha256'] = digest(dumps([c['candidate_id'] for c in candidates]).encode())
    if not candidates:
        result.update(status="insufficient_evidence", limitations=["no_current_eligible_domain_evidence"])
        return _record_audit(w, result)
    lexical = _lexical(query, candidates)
    dense, reasons = [], []
    embedding = reranker = None
    if mode != 'lexical':
        try:
            embedding, reranker = services or load_services(w.root)
        except (ValueError, OSError, TypeError):
            reasons.append("model_configuration_invalid")
    if mode != "lexical":
        try:
            if embedding is None:
                raise ModelUnavailable("embedding_unavailable")
            dense, missing = _dense(w, embedding, query, candidates)
            audit['dense_structural_projections'] = [c['dense_projection'] for c in candidates if 'dense_projection' in c]
            if missing:
                reasons.append("dense_index_incomplete:" + str(missing))
        except ModelUnavailable as exc:
            reasons.append(str(exc))
    if mode == "lexical":
        fused = lexical
    elif mode == "dense" and dense:
        fused = dense
    else:
        fused = reciprocal_rank_fusion([lexical, dense], constant=config["fusion"]["rrf_constant"])
    by_id = {c["candidate_id"]: c for c in candidates}
    budget = config["fusion"]["candidate_budget"]
    final = fused[:budget]
    reranked_ids = []
    if mode == "hybrid_rerank" and final:
        try:
            if reranker is None:
                raise ModelUnavailable("reranker_unavailable")
            budget_audit = {}
            audit['reranker_context_budget'] = budget_audit
            ordered, budget_audit = rerank_windows(reranker, query, [by_id[i] for i in final],
                is_current=lambda candidate: _still_current(w, candidate, context), audit=budget_audit)
            unranked = set(budget_audit['unranked_ids'])
            reranked_ids = [i for i in ordered if i not in unranked]
            final = ordered
            if unranked:
                reasons.append('reranker_input_budget:' + str(len(unranked)))
        except ModelUnavailable as exc:
            reasons.append(str(exc))
    ranks = [{identity: rank for rank, identity in enumerate(ranking, 1)} for ranking in (lexical, dense, fused, reranked_ids)]
    selected_ids, audit['evidence_selection'] = _select_evidence(w, metric_id, profile, claims, by_id, final,
        context, k, release.get('edge_ids'))
    chosen = []
    for identity in selected_ids:
        candidate = dict(by_id[identity])
        if not _still_current(w, candidate, context):
            excluded.append({'span_id': identity, 'reason': 'invalidated_after_candidate_filter'})
            continue
        candidate.update({key: ranking.get(identity) for key, ranking in zip(("lexical_rank", "dense_rank", "fusion_rank", "reranker_rank"), ranks)})
        candidate["retrieval_method"] = mode if not reasons else "degraded_" + mode
        candidate["exclusion_reason"] = None
        siblings = [c for c in candidates if c['parent_section_id'] == candidate['parent_section_id']]
        offset = next(i for i, c in enumerate(siblings) if c['span_id'] == identity)
        candidate['parent_context'] = [{key: c[key] for key in ('span_id', 'locator', 'content')}
            for c in siblings[max(0, offset-1):offset+2]
            if c['span_id'] != identity and _still_current(w, c, context)]
        candidate['parent_context_authority'] = 'reading_context_only_not_additional_reviewed_claims'
        chosen.append(candidate)
    matched, conflicts = _metric_claims(w, metric_id, claims, {c["span_id"]: c for c in chosen}, context, release.get('edge_ids'))
    result.update(matched_claims=matched, evidence_spans=chosen, conflicts=conflicts,
        retrieved_domains=sorted({d for c in chosen for d in c["domains"]}),
        applicability=[{"span_id": c["span_id"], **c["applicability"]} for c in chosen],
        source_metadata=[{"source_id": c["source_id"], "source_version": c["source_version"], **c["source_metadata"]} for c in chosen])
    if not matched:
        result["limitations"].append("retrieved_original_text_does_not_replace_reviewed_metric_claim_binding")
    if conflicts:
        result["limitations"].append("explicit_conflicting_claims_require_resolution")
    reviewed_domains = {d for claim in matched for d in claim["domains"]}
    missing_domains = sorted(set(profile.get("required_domains", profile["primary_domains"])) - reviewed_domains)
    covered_types = {t for claim in matched for t in claim["evidence_types"]}
    missing_types = sorted(set(profile["required_evidence_types"]) - covered_types)
    missing_context = [key for key in profile["applicability_context"]
                       if not context_match([{ "field": key, "op": "present", "origin": "product_scope"}], context)[0]]
    result["limitations"] += (["missing_required_domain:" + d for d in missing_domains]
                              + ["missing_evidence_type:" + t for t in missing_types]
                              + ["missing_applicability_context:" + key for key in missing_context])
    supported = bool(matched) and not (conflicts or missing_domains or missing_types or missing_context)
    result["status"] = "evidence_context_supported" if supported else "insufficient_evidence"
    result["capability_permissions"]["source_explanation"] = supported
    audit.update(retrieval_degraded=bool(reasons), degradation_reasons=reasons,
        lexical_candidates=len(lexical), dense_candidates=len(dense), fusion_candidates=len(fused),
        reranked_candidates=len(reranked_ids),
        models={"embedding": embedding.config.identity if embedding else None,
                "reranker": reranker.config.identity if reranker else None},
        conflict_screen_scope="explicit_reviewed_edges_across_all_eligible_claims_before_display_budget",
        automatic_source_prose_contradiction_detection=False)
    # An audit contains hashes and ranks only, never raw health context or source prose.
    audit["ranking_sha256"] = digest(dumps([{key: c.get(key) for key in ("span_id", "lexical_rank", "dense_rank", "fusion_rank", "reranker_rank")} for c in chosen]).encode())
    return _record_audit(w, result)


def _record_audit(w, result):
    """Persist only public IDs, ranks and fixed codes, including abstentions."""
    from uuid import uuid4
    audit = result["retrieval_audit"]
    audit["audit_id"] = uuid4().hex
    audit["status"] = result["status"]
    audit["rankings"] = [{key: c.get(key) for key in (
        "span_id", "source_id", "source_version", "lexical_rank", "dense_rank", "fusion_rank", "reranker_rank")}
        for c in result["evidence_spans"]]
    with atomic(w.lib.sources) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS metric_retrieval_audit(
          audit_id TEXT PRIMARY KEY,query_id TEXT NOT NULL,metric_id TEXT NOT NULL,
          task_id TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL)""")
        conn.execute("INSERT INTO metric_retrieval_audit VALUES(?,?,?,?,?,?)", (
            audit["audit_id"], result["query_id"], result["metric_id"], result["task_id"], dumps(audit), now()))
    return result


def freeze_index(w, release_id):
    domains.ensure_schema(w)
    vector_index.ensure_schema(w)
    units = [r for r in vector_index.current_units(w)
             if (span := w.lib.span(r['span_id'], include_metadata=False)) and w.lib.eligible(span, 'fulltext')[0]]
    span_ids = [row['span_id'] for row in units]
    manifest = {"schema": "metric-index-release-1.5.0", "span_ids": span_ids,
        "profile_version": domains.configuration()["schema_version"],
        "profile_sha256": digest(dumps(domains.configuration()).encode()),
        "query_forms_sha256": query_forms.identity(),
        "claim_refs": [dict(r) for r in w.lib.theories.execute("SELECT claim_id,version FROM source_claim WHERE status='verified' ORDER BY claim_id,version")],
        "edge_ids": [r[0] for r in w.lib.theories.execute("SELECT edge_id FROM knowledge_evidence_edge ORDER BY edge_id")],
        "unit_assignments": {r['span_id']: vector_index.unit_assignment(w, r) for r in units}}
    projections = {}
    for identity in span_ids:
        span = w.lib.span(identity, include_metadata=False)
        if span['kind'] == 'table' and (projection := table_projection.current(w, span)):
            projections[identity] = projection['projection_set_id']
    if projections:
        manifest['projection_set_ids'] = projections
    observations = set(domains.observation_configuration()['profiles'])
    if any(r[0] in observations for r in w.lib.theories.execute("SELECT to_id FROM knowledge_evidence_edge WHERE to_type='metric'")):
        manifest['observation_profile_sha256'] = digest(dumps(domains.observation_configuration()).encode())
    serialized = dumps(manifest)
    old = w.lib.sources.execute("SELECT manifest_json FROM index_release WHERE release_id=?", (release_id,)).fetchone()
    if old and old[0] != serialized:
        raise ValueError("immutable_index_release_conflict")
    with atomic(w.lib.sources):
        w.lib.sources.execute("INSERT OR IGNORE INTO index_release VALUES(?,?,?,?)", (release_id, serialized, digest(serialized.encode()), now()))
    return {"release_id": release_id, "sha256": digest(serialized.encode()), "span_count": len(span_ids)}
