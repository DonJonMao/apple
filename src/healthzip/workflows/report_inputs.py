"""Request-local inputs shared by the existing calendar report workflow runs."""
from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from inspect import signature

from healthzip.analytics.v13 import analyze, snapshot
from healthzip.training.service import TrainingService, report_event_reads

_INPUTS = ContextVar("healthzip_period_report_inputs", default=None)
_ANALYSIS_ARGUMENTS = signature(analyze)


@contextmanager
def shared_report_inputs(repo):
    token = _INPUTS.set((repo, {}, {}, {}))
    try:
        with report_event_reads(repo):
            yield
    finally:
        _INPUTS.reset(token)


def period_facts(repo, *args, **kwargs):
    inputs = _INPUTS.get()
    if not inputs or inputs[0] is not repo:
        return analyze(repo, *args, **kwargs)
    # Calendar reports consume the complete global metrics and every actual
    # task identity. Ordinary tasks have no designated reference; their unused
    # specialist predictions need not be expanded for every recorded set.
    kwargs = {**kwargs, "ordinary_task_metrics": ("STR-11",)}
    arguments = _ANALYSIS_ARGUMENTS.bind(repo, *args, **kwargs)
    arguments.apply_defaults()
    fields = {k: v for k, v in arguments.arguments.items() if k != "repo"}
    # None and {} both use the canonical unselected context in v13.
    fields["context"] = fields["context"] or {}
    from healthzip.science.contracts import instant
    for name in ("cutoff_time", "window_start", "window_end"):
        if fields[name] is not None:
            fields[name] = instant(fields[name]).isoformat()
    key = json.dumps(fields, sort_keys=True)
    cache = inputs[1]
    if key not in cache:
        # This scope lives for only one frozen request. Validation of private
        # inputs and current knowledge is repeated before the report is saved.
        context = fields["context"]
        if context.get("baseline_window") and context.get("baseline_completed_days") and "baseline_daily" not in context:
            cache[key] = _baseline_variant(repo, args, kwargs, context)
        else:
            cache[key] = analyze(repo, *args, **{**kwargs, "use_cache": False})
    value = cache[key]
    # Individual workflows annotate the returned top level and may append a
    # selected task. Scientific results and source observations are read-only.
    return {**value, "strength_tasks": list(value["strength_tasks"])}


def _baseline_variant(repo, args, kwargs, context):
    """W2's explicit reference window changes exactly these three metrics."""
    from healthzip.science.contracts import canonical_hash, instant
    from healthzip.science.engine import evaluate_subset

    from .contracts import scientific_identity

    base_context = {key: value for key, value in context.items() if key not in {"baseline_window", "baseline_completed_days"}}
    base = period_facts(repo, *args, **{**kwargs, "context": base_context})
    start = min(base["query_plan"]["window_start"], context["baseline_window"]["start"], key=instant)
    records, inherited = source_snapshot(repo, base["cutoff_time"], window_start=start, window_end=base["window_end"],
        canonical_types=["hrv_sdnn_ms", "resting_heart_rate_bpm"], retrospective=base["retrospective"], include_training=False,
        source_filter=context.get("source_filter", ()))
    mids = ("STATE-REFERENCE-MEDIAN", "STATE-REFERENCE-MAD", "STATE-DEVIATION")
    metrics = evaluate_subset(mids, records, cutoff_time=base["cutoff_time"], window_start=base["window_start"],
        window_end=base["window_end"], context={**context, "timezone": base["timezone"], "retrospective": base["retrospective"]})
    for mid, metric in metrics.items():
        # The unchanged non-baseline optional contexts retain their original
        # visibility exclusions, even though they are not fetched a second time.
        metric["exclusions"] += [entry for entry in base["metrics"][mid]["exclusions"] if "context" in entry]
    return {**base, "metrics": {**base["metrics"], **metrics},
        "data_hash": canonical_hash(["report-baseline-variant-1", base["data_hash"], context, scientific_identity(metrics)]),
        "baseline_query_plan": inherited["query_plan"],
        "analysis_derivation": {"version": "report-baseline-variant-1", "base_data_hash": base["data_hash"],
            "recomputed_metric_ids": list(mids), "baseline_window": context["baseline_window"]}}


def visible_sessions(repo, cutoff):
    inputs = _INPUTS.get()
    if not inputs or inputs[0] is not repo:
        return TrainingService(repo).sessions_as_of(cutoff_time=cutoff)
    sessions = inputs[2]
    from healthzip.science.contracts import instant
    key = instant(cutoff).isoformat()
    if key not in sessions:
        sessions[key] = TrainingService(repo).sessions_as_of(cutoff_time=cutoff)
    return sessions[key]


def report_value(repo, namespace, key, compute):
    """Reuse read-only work only while committed private revisions are equal."""
    inputs = _INPUTS.get()
    if not inputs or inputs[0] is not repo:
        return compute()
    from .dependencies import input_version
    identity = json.dumps([namespace, input_version(repo, None), key], sort_keys=True)
    values = inputs[3]
    if identity not in values:
        values[identity] = compute()
    return values[identity]


def source_snapshot(repo, *args, **kwargs):
    if kwargs.get("include_training") is False:
        # Each training start has a distinct as-of boundary. The surrounding
        # body-context result is shared, while these large temporary raw rows
        # must not accumulate once per session for the lifetime of the report.
        return snapshot(repo, *args, **kwargs)
    from healthzip.science.contracts import instant
    fields = signature(snapshot).bind(repo, *args, **kwargs)
    fields.apply_defaults()
    key = {name: value for name, value in fields.arguments.items() if name != "repo"}
    for name in ("cutoff_time", "window_start", "window_end"):
        if key[name] is not None:
            key[name] = instant(key[name]).isoformat()
    records, context = report_value(repo, "source_snapshot", key,
        lambda: snapshot(repo, *args, **kwargs))
    # The list of observations is consumed read-only. A workflow may bind its
    # own plan or outcome selection at the top level of inherited context.
    return records, dict(context)
