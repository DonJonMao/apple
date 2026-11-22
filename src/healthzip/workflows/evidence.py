"""Repository-derived applicability and bounded, fixed public knowledge tasks."""
from contextlib import closing, contextmanager, nullcontext
from contextvars import ContextVar
from pathlib import Path

from healthzip.science.contracts import instant

from .contracts import WORKFLOWS

QUERY_FORM = "en"  # Owned source prose is predominantly English; UI stays Chinese.


_REPORT_EVIDENCE = ContextVar("healthzip_report_evidence", default=None)


@contextmanager
def report_evidence(root):
    """Share a local public connection and a release identity for this report."""
    root = Path(root).resolve()
    state = {"root": root}
    token = _REPORT_EVIDENCE.set(state)
    try:
        yield
    finally:
        _REPORT_EVIDENCE.reset(token)
        if "library" in state:
            state["library"].close()


def _release_id(workbench):
    row = workbench.lib.sources.execute(
        "SELECT release_id FROM index_release WHERE "
        "json_extract(manifest_json,'$.candidate_scope_version') IS NOT NULL "
        "AND json_extract(manifest_json,'$.candidate_scope_version') != '' "
        "ORDER BY created_at DESC LIMIT 1").fetchone()
    return row[0] if row else None


def identity(knowledge):
    """Retrieval receipt IDs are audit events, not scientific dependencies."""
    return {**knowledge, "queries": [{key: value for key, value in query.items() if key != "audit"}
                                     for query in knowledge["queries"]]}


def background_inputs(contexts):
    return {mid: next((ctx["metrics"][mid] for ctx in reversed(contexts) if ctx["metrics"].get(mid, {}).get("value") is not None), contexts[-1]["metrics"].get(mid))
            for mid in contexts[-1]["metrics"]} if contexts else None


def _observed_protocol(value):
    """Grouping by known context does not establish an acquisition protocol."""
    if not isinstance(value, str):
        return None
    value = value.split(";context:", 1)[0].strip()
    return value if value not in ("", "unknown") and not value.startswith("context:") else None


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
                if isinstance(stream, dict) and (known := _observed_protocol(stream.get("protocol_id"))):
                    protocols.add(known)
            for stream in value.values():
                if isinstance(stream, list):
                    for point in stream:
                        protocol = point.get("protocol") if isinstance(point, dict) else None
                        if isinstance(protocol, (list, tuple)) and len(protocol) > 2:
                            if known := _observed_protocol(protocol[2]):
                                protocols.add(known)
        if metric_id == "STR-10" and isinstance(value, list) and value:
            # The retrieval layer separately derives and validates direct RIR
            # from these repository-computed values; this only names the measure.
            if all(item.get("rir") is not None and not item.get("converted")
                   and item.get("rir_interval") is None for item in value):
                protocols.add("direct_RIR")
        context["measurement_protocol"] = next(iter(protocols)) if len(protocols) == 1 else None
    comparison = metric.get("comparison") or {}
    if comparison:
        # Retain the measured dates/conditions locally. The public retriever
        # derives generic method needs and never serializes this fact packet.
        streams = comparison.get("streams", [])
        context["comparison_windows"] = comparison.get("windows", {})
        context["observed_dates"] = sorted({date for stream in streams
            for period in ("current", "previous", "reference")
            for date in (stream.get(period) or {}).get("dates", [])})
        context["fact_ids"] = [stream["fact_id"] for stream in streams if stream.get("fact_id")]
        context["known_measurement_conditions"] = [
            {"date": point.get("date"), "conditions": observation.get("conditions", {})}
            for stream in streams for period in ("current", "previous")
            for point in (stream.get(period) or {}).get("daily_points", [])
            for observation in point.get("observations", [])]
        protocol_names = [_observed_protocol(stream["protocol"][2])
                          if isinstance(stream.get("protocol"), (list, tuple)) and len(stream["protocol"]) > 2
                          else None for stream in streams]
        explicit = set(protocol_names)
        context["measurement_protocol"] = next(iter(explicit)) if len(explicit) == 1 and None not in explicit else None
    if values.get("age") is not None:
        context["age"] = values["age"]
    return context


def retrieve(workflow_id, metrics, sessions, declaration, *, root, release_id, background_metrics=None, result_metric_id=None):
    """At most the registered primary and auxiliary query; lexical is intentional."""
    from healthzip.knowledge import KnowledgeWorkbench, metric_retrieval
    from healthzip.knowledge.domains import configuration

    spec = WORKFLOWS[workflow_id]
    if not all((Path(root) / name).is_file() for name in ("sources.sqlite3", "theories.sqlite3")):
        return {"status": "source_unavailable", "queries": [], "release_id": release_id,
                "reason_codes": ["local_knowledge_store_missing"]}
    state = _REPORT_EVIDENCE.get()
    if state is not None and state["root"] == Path(root).resolve():
        if "library" not in state:
            state["library"] = KnowledgeWorkbench(root)
        library = nullcontext(state["library"])
    else:
        library = closing(KnowledgeWorkbench(root))
        state = None
    with library as workbench:
        if release_id is None:
            if state is None:
                release_id = _release_id(workbench)
            else:
                if "release_id" not in state:
                    state["release_id"] = _release_id(workbench)
                release_id = state["release_id"]
        if release_id is None:
            return {"status": "source_unavailable", "queries": [], "release_id": None,
                    "reason_codes": ["compatible_frozen_metric_release_required"]}
        config = configuration(include_observations=True)
        answers = []
        queries = (result_metric_id,) if workflow_id == "W4" and result_metric_id and result_metric_id != "STR-11" else spec["queries"]
        tasks = [("S4", mid, metrics.get(mid)) for mid in queries]
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
