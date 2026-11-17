"""Repository-derived applicability and bounded, fixed public knowledge tasks."""
from pathlib import Path

from healthzip.science.contracts import instant

from .contracts import WORKFLOWS

QUERY_FORM = "en"  # Owned source prose is predominantly English; UI stays Chinese.


def identity(knowledge):
    """Retrieval receipt IDs are audit events, not scientific dependencies."""
    return {**knowledge, "queries": [{key: value for key, value in query.items() if key != "audit"}
                                     for query in knowledge["queries"]]}


def background_inputs(contexts):
    return {mid: next((ctx["metrics"][mid] for ctx in reversed(contexts) if ctx["metrics"].get(mid, {}).get("value") is not None), contexts[-1]["metrics"].get(mid))
            for mid in contexts[-1]["metrics"]} if contexts else None


def local_context(metric_id, metric, sessions, declaration):
    """No caller-provided MetricResult or arbitrary condition flags cross here."""
    values = declaration["values"]
    context = {"user_id": "local", "population": values.get("population", "unknown"),
               "measurement_protocol": None, "usage_scope": "local_noncommercial"}
    if metric_id in {"LOAD-SRPE", "LOAD-SRPE-AU"}:
        ids = {str(item["session_id"]) for item in metric.get("value") or []}
        matched = [s for s in sessions if str(s["id"]) in ids]
        scales = {s.get("session_rpe_scale") for s in matched}
        context["srpe_scale"] = next(iter(scales)) if len(scales) == 1 else "unknown"
        context["measurement_protocol"] = context["srpe_scale"] if context["srpe_scale"] != "unknown" else None
        after = bool(matched)
        for session in matched:
            try:
                collected = instant(session.get("session_rpe_collected_at"))
                after = after and instant(session["ended_at"]) <= collected <= instant(metric["cutoff_time"])
            except (ValueError, TypeError, KeyError):
                after = False
        context["srpe_collection"] = "retrospective_after_session" if after else "unknown"
    else:
        # This is the name of an observed protocol, never a validation claim.
        protocols = set()
        value = metric.get("value")
        if isinstance(value, dict):
            for stream in value.get("streams", []):
                if isinstance(stream, dict) and stream.get("protocol_id"):
                    protocols.add(stream["protocol_id"])
            for stream in value.values():
                if isinstance(stream, list):
                    for point in stream:
                        protocol = point.get("protocol") if isinstance(point, dict) else None
                        if isinstance(protocol, list) and len(protocol) > 2 and protocol[2]:
                            protocols.add(protocol[2])
        if metric_id == "STR-10" and isinstance(value, list) and value:
            # The retrieval layer separately derives and validates direct RIR
            # from these repository-computed values; this only names the measure.
            if all(item.get("rir") is not None and not item.get("converted")
                   and item.get("rir_interval") is None for item in value):
                protocols.add("direct_RIR")
        context["measurement_protocol"] = next(iter(protocols)) if len(protocols) == 1 else None
    return context


def retrieve(workflow_id, metrics, sessions, declaration, *, root, release_id, background_metrics=None):
    """At most the registered primary and auxiliary query; lexical is intentional."""
    from healthzip.knowledge import KnowledgeWorkbench, metric_retrieval
    from healthzip.knowledge.domains import configuration

    spec = WORKFLOWS[workflow_id]
    if not all((Path(root) / name).is_file() for name in ("sources.sqlite3", "theories.sqlite3")):
        return {"status": "source_unavailable", "queries": [], "release_id": release_id,
                "reason_codes": ["local_knowledge_store_missing"]}
    workbench = KnowledgeWorkbench(root)
    try:
        if release_id is None:
            rows = workbench.lib.sources.execute("SELECT release_id,manifest_json FROM index_release ORDER BY created_at DESC")
            import json
            release_id = next((row[0] for row in rows if json.loads(row[1]).get("candidate_scope_version")), None)
        if release_id is None:
            return {"status": "source_unavailable", "queries": [], "release_id": None,
                    "reason_codes": ["compatible_frozen_metric_release_required"]}
        config = configuration(include_observations=True)
        answers = []
        tasks = [("S4", mid, metrics.get(mid)) for mid in spec["queries"]]
        if background_metrics:
            # A declared review node, not a free keyword expansion. The two
            # queried measurements are actual pre-training MetricResults.
            tasks.extend(("S3:" + mid, mid, background_metrics.get(mid)) for mid in (
                "STATE-SLEEP-24H", "STATE-RHR", "STATE-SDNN", "BODY-MASS-DAILY"))
            tasks.extend(("S3:performance", mid, metrics.get(mid)) for mid in ("STR-19", "STR-10")
                         if mid not in spec["queries"])
        for node_id, metric_id, metric in tasks:
            if metric is None or metric["value"] is None:
                continue
            # Some shared background metrics use a different registered function.
            # The choice is explicit metadata, not free-query route expansion.
            functions = config["profiles"][metric_id]["analysis_functions"]
            task = spec["task"] if spec["task"] in functions else "explain_metric"
            try:
                response = workbench.retrieve_for_metric(metric_id, task, metric,
                    local_context(metric_id, metric, sessions, declaration), release_id,
                    mode="lexical", candidate_scope="reviewed_metric", query_form=QUERY_FORM, k=6)
                # Full source prose remains in SourceLibrary, not private runs.
                spans = [{**{key: span.get(key) for key in ("source_id", "source_version", "span_id",
                    "section_path", "locator", "evidence_role", "rights_status", "source_metadata")},
                    "text_hash": span["input_content_hash"], "kind": workbench.lib.span(span["span_id"])["kind"]}
                    for span in response["evidence_spans"]]
                answers.append({"node_id": node_id, "metric_id": metric_id, "analysis_task": task, "status": response["status"],
                    "allowed_use": "source_explanation_only", "action_authority": "separate_application_rule_required",
                    "claims": response["matched_claims"], "spans": spans, "limitations": response["limitations"],
                    "conflicts": response["conflicts"], "permissions": response["capability_permissions"],
                    "audit": response["retrieval_audit"]})
            except ValueError as exc:
                answers.append({"node_id": node_id, "metric_id": metric_id,
                    "status": "incompatible_release" if "frozen" in str(exc) else "invalid_evidence_contract",
                    "reason_codes": [str(exc)]})
        return {"status": "checked", "queries": answers, "release_id": release_id,
                "query_policy": {"candidate_scope": "reviewed_metric", "query_form": QUERY_FORM, "mode": "lexical",
                                 "scope_version": metric_retrieval.CANDIDATE_SCOPE_VERSION,
                                 "context_version": metric_retrieval.METRIC_EVIDENCE_CONTEXT_VERSION,
                                 "nodes": list(dict.fromkeys(node for node, _, _ in tasks)), "max_queries_per_node": 2}}
    finally:
        workbench.close()
