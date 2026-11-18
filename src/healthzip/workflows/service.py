"""Deterministic local workflow runs over repository-owned analysis snapshots."""
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from healthzip.advice import build_advice_context
from healthzip.analytics.v13 import analyze
from healthzip.science.contracts import canonical_hash, instant, task_metric_results
from healthzip.training.service import TrainingService

from . import evidence
from .contracts import FUNCTION_NAMES, VERSION, WORKFLOWS, WorkflowRequest, scientific_identity
from .dependencies import input_version
from .dependencies import inputs as dependency_inputs
from .facts import (
    attach_evidence,
    describe,
    energy_coverage,
    factors,
    pretraining_factors,
    vo2_segments,
)
from .selection import scoped_metrics
from .storage import context_as_of, load_analysis, load_run


def _select_metrics(analysis, request, partial_period=None):
    metrics = {**analysis["metrics"], **analysis["observations"]}
    selected_task = None
    if request["task_id"]:
        selected_task = next((task for task in analysis["strength_tasks"] if task["task_id"] == request["task_id"]), None)
        if selected_task is None and partial_period is not None:
            current = next((task for task in partial_period["strength_tasks"] if task["task_id"] == request["task_id"]), None)
            if current is not None:
                from healthzip.science import evaluate
                selected_task = {**current, "metrics": {mid: evaluate(mid, [], cutoff_time=request["cutoff_time"],
                    window_start=analysis["window_start"], window_end=analysis["window_end"],
                    context={"timezone": request["timezone"], "retrospective": request["mode"] == "retrospective"})
                    for mid in current["metrics"]}}
        if selected_task is None:
            raise ValueError("selected_task_not_visible_in_workflow_window")
        metrics.update(selected_task["metrics"])
    selected = {mid: metrics[mid] for mid in WORKFLOWS[request["workflow_id"]]["metrics"]}
    if request["workflow_id"] == "W4":
        outcome = request["result_metric_id"] or ("STR-11" if request["task_id"] else "BODY-MASS-DAILY")
        if outcome != "STR-11":
            # A selected non-strength outcome cannot inherit unrelated strength
            # comparisons, factors, follow-up counts or source permissions.
            selected = {mid: selected[mid] for mid in (outcome,)}
            selected_task = None
    if request["outcome_series_id"]:
        found = False
        for mid, metric in list(selected.items()):
            series = next((s for s in metric.get("series_results", [])
                           if s["outcome_series_id"] == request["outcome_series_id"]), None)
            if series:
                selected[mid] = series["metric"]
                found = True
        if not found:
            raise ValueError("selected_series_not_visible_in_workflow_window")
    return selected, selected_task


def _nodes(request, metrics, facts, missing, hypotheses, knowledge, supplements):
    has_facts = bool(facts)
    comparisons = [child["metric"] for mid in ("STR-12", "STR-13", "STR-14") if mid in metrics
                   for child in task_metric_results(metrics[mid])]
    comparable = True if any(m["value"] is not None and m["data_status"] == "valid" for m in comparisons) else None
    if request["workflow_id"] == "W3":
        comparable = True if any(s["recorded_difference"] is not None for s in supplements.get("vo2_segments", [])) else None
    elif request["workflow_id"] in {"W2", "W4", "W5"}:
        mids = ("STATE-RHR", "STATE-SDNN", "BODY-MASS-DAILY")
        if request["workflow_id"] == "W4":
            outcome = request["result_metric_id"] or ("STR-11" if request["task_id"] else "BODY-MASS-DAILY")
            mids = (outcome,) if outcome != "STR-11" else ()
            if mids:
                comparisons = [metrics[outcome]]
        comparable = True if any(len(points) > 1 and all(points[0]["protocol"])
            for mid in mids
            for points in (metrics.get(mid, {}).get("value") or {}).values()) else comparable
    if comparable is None and any(m["data_status"] in {"incompatible", "conflicted"} for m in comparisons):
        comparable = False
    supported = any(q.get("permissions", {}).get("source_explanation") for q in knowledge["queries"])
    assessed = [h for h in hypotheses if h["status"] != "unassessable"]
    factual_support = any(h["support"] for h in assessed)
    return [
        {"node_id": "S0", "truth": True, "status": "completed", "request": request},
        {"node_id": "S1", "truth": True if has_facts else None, "status": "bounded" if has_facts and missing else "completed" if has_facts else "needs_data",
         "fact_refs": [item["metric_id"] for item in facts], "missing_refs": [item["metric_id"] for item in missing]},
        {"node_id": "S2", "truth": comparable, "status": "completed" if comparable else "needs_review" if comparable is False else "bounded",
         "metric_refs": [m["metric_id"] for m in comparisons], "limitation": "分量描述不等于能力显著变化；不可比或缺误差方法时不推断。"},
        {"node_id": "S3", "truth": factual_support if assessed else None, "status": "completed" if assessed else "bounded",
         "hypothesis_ids": [h["hypothesis_id"] for h in hypotheses], "identity": "factual_predicates_not_cause_confirmation"},
        {"node_id": "S4", "truth": True if supported else None, "status": "completed" if supported else "bounded",
         "knowledge_status": knowledge["status"], "metric_refs": [q["metric_id"] for q in knowledge["queries"]]},
        {"node_id": "S5", "truth": None, "status": "bounded" if request["workflow_id"] == "W1" else "completed", "candidate_ids": [],
         "action_identity": "record_or_review_inputs_no_automatic_prescription"},
        {"node_id": "S6", "truth": None, "status": "bounded", "metric_refs": [mid for mid in
          ("STR-27", "STR-28", "REPORT-RECOMMENDATION-FOLLOWUP") if mid in metrics],
         "limitation": "选择、实际执行、达标与后续变化分别记录；未反馈保持未知。"},
    ]


def run_workflow(repo, request: WorkflowRequest, *, knowledge_root=".local/knowledge", parent_run_id=None):
    if not isinstance(request, WorkflowRequest):
        raise TypeError("WorkflowRequest_required_no_client_metric_results")
    if repo.conn.in_transaction:
        raise ValueError("save_pending_edits_before_workflow")
    TrainingService(repo)  # Finish idempotent initialization before the input clock.
    request = replace(request, cutoff_time=request.normalized()["cutoff_time"])
    version = input_version(repo, request.context_id)
    visible_at = datetime.now(timezone.utc).isoformat()
    return _run_workflow(repo, request, knowledge_root=knowledge_root, parent_run_id=parent_run_id,
                         input_revision=version, data_visible_at=visible_at)


def _run_workflow(repo, request: WorkflowRequest, *, knowledge_root, parent_run_id, input_revision, data_visible_at):
    """Only repository calculations may populate this service's metric inputs.

    A public research MetricResult is deliberately not an accepted argument.
    Fixed cutoff and visible records are recomputed before cache lookup, and
    current knowledge eligibility is checked before reusing any workflow run.
    """
    if not isinstance(request, WorkflowRequest):
        raise TypeError("WorkflowRequest_required_no_client_metric_results")
    declared_request = request.normalized()
    if parent_run_id:
        parent = load_run(repo, parent_run_id)
        if parent["workflow_id"] != request.workflow_id:
            raise ValueError("successor_must_keep_workflow_identity")
    from .storage import report_context
    resolve_context = report_context if request.context_policy == "preserve_facts" else context_as_of
    declaration = resolve_context(repo, request.context_id, declared_request["cutoff_time"], request.mode)
    selected_context = {key: value for key, value in declaration["values"].items()
                        if key in {"primary_sleep_stream", "reference_selection", "sleep_selection"}}
    if request.selection_analysis_id:
        saved = repo.conn.execute("SELECT result_json FROM analysis_run WHERE run_id=?", (request.selection_analysis_id,)).fetchone()
        if saved is None:
            raise ValueError("selected_analysis_not_found")
        prior = json.loads(saved[0])
        if (instant(prior["cutoff_time"]) > instant(declared_request["cutoff_time"])
                or prior["timezone"] != request.timezone
                or bool(prior.get("retrospective")) != (request.mode == "retrospective")):
            raise ValueError("selected_analysis_time_or_mode_mismatch")
        selected_context = {**prior.get("selection_context", {}), **selected_context}
    if request.workflow_id == "W2":
        day_start = instant(declared_request["cutoff_time"]).astimezone(ZoneInfo(request.timezone)).replace(hour=0, minute=0, second=0, microsecond=0)
        selected_context.update(baseline_window={"start": (day_start-timedelta(days=request.baseline_days)).isoformat(),
            "end": declared_request["cutoff_time"], "timezone": request.timezone},
            baseline_completed_days=request.baseline_days)
    # Existing selection services re-resolve record IDs and protocol/visibility.
    analysis = analyze(repo, request.window_days, cutoff_time=declared_request["cutoff_time"],
        timezone_name=request.timezone, retrospective=request.mode == "retrospective",
        context=selected_context, period=request.period, use_cache=False,
        window_start=request.window_start, window_end=request.window_end)
    partial_period = None
    if request.workflow_id == "W4" and request.period:
        from .calendar import completed_periods
        partial_period = analysis
        periods = completed_periods(declared_request["cutoff_time"], request.timezone, request.period)
        analysis = analyze(repo, cutoff_time=declared_request["cutoff_time"], timezone_name=request.timezone,
            context=selected_context, retrospective=request.mode == "retrospective", use_cache=False,
            window_start=periods[0][0], window_end=periods[-1][1])
    advice = None
    if request.session_exercise_id:
        advice = build_advice_context(repo, request.session_id, request.session_exercise_id,
            request.selected_set_uuid, [], None, cutoff_time=declared_request["cutoff_time"], timezone_name=request.timezone,
            retrospective=request.mode == "retrospective", generation_origin="automatic_training")
        if not declared_request["task_id"]:
            declared_request["task_id"] = advice["context"]["task_id"]
            if not any(task["task_id"] == declared_request["task_id"] for task in analysis["strength_tasks"]):
                # A real selected task with no references is empty; it must not
                # inherit other exercises' global metrics or a long-review label.
                from healthzip.science import evaluate
                analysis["strength_tasks"].append({"task_id": declared_request["task_id"],
                    "exercise_id": advice["instance"]["catalog_id"],
                    "exercise_name": advice["instance"]["exercise"].get("name"),
                    "condition_key": advice["instance"].get("condition_key"), "protocol": advice["context"]["protocol"],
                    "metrics": {mid: evaluate(mid, [], cutoff_time=declared_request["cutoff_time"],
                        window_start=analysis["window_start"], window_end=analysis["window_end"], context=selected_context)
                        for mid in WORKFLOWS[request.workflow_id]["metrics"] if mid.startswith("STR-")}})
    metrics, selected_task = _select_metrics(analysis, declared_request, partial_period)
    source_report = None
    if request.source_run_id:
        source = load_run(repo, request.source_run_id)
        source_snapshot = load_analysis(repo, source["run_id"])
        if (request.workflow_id != "W1" or source["workflow_id"] not in {"W1", "W4"}
                or not source.get("task_selection") or not selected_task
                or source["task_selection"]["task_id"] != selected_task["task_id"]):
            raise ValueError("action_source_task_mismatch")
        if instant(declared_request["cutoff_time"]) < instant(source["request"]["cutoff_time"]):
            raise ValueError("action_source_time_after_current_action")
        source_report = {"run_id": source["run_id"], "analysis_run_id": source["analysis_run_id"],
            "cutoff_time": source["request"]["cutoff_time"], "context_id": source["context_id"],
            "window_start": source_snapshot["window_start"], "window_end": source_snapshot["window_end"],
            "current_action_cutoff_time": declared_request["cutoff_time"],
            "current_window_start": analysis["window_start"], "current_window_end": analysis["window_end"],
            "identity": "historical_report_link_with_independent_current_action_window"}
    strength_points = scoped_metrics(repo, declared_request, analysis, selected_task, metrics) if "STR-11" in metrics else []
    from .longitudinal import body_context, pretraining_contexts, review
    long_review = review(strength_points, {"start": analysis["window_start"], "end": analysis["window_end"], "timezone": request.timezone})
    before_training = pretraining_contexts(repo, strength_points, declared_request, selected_context)
    current_body = body_context(repo, declared_request["cutoff_time"], declared_request, selected_context) if advice else None
    from .selection import session_backgrounds
    session_contexts = session_backgrounds(repo, declared_request, analysis, selected_task, selected_context) if request.include_session_background else []
    background_contexts = before_training + session_contexts + ([current_body] if current_body else [])
    background_metrics = evidence.background_inputs(background_contexts)
    sessions = TrainingService(repo).sessions_as_of(cutoff_time=declared_request["cutoff_time"])
    # Capture dependencies before evidence retrieval, over every input window.
    # A version change during the preceding reads refuses the freeze outright.
    dependency_analysis = dict(analysis)
    starts = [analysis["window_start"]]
    if selected_context.get("baseline_window"):
        starts.append(selected_context["baseline_window"]["start"])
    starts += [m["window"]["start"] for ctx in background_contexts for m in ctx["metrics"].values()]
    dependency_analysis["dependency_window_start"] = min(starts, key=instant)
    if partial_period:
        dependency_analysis["dependency_window_end"] = partial_period["window_end"]
    before_dependencies = dependency_inputs(repo, declared_request, dependency_analysis, selected_task=selected_task,
        visible_at=data_visible_at if request.mode == "retrospective" else None)
    if input_version(repo, request.context_id) != input_revision:
        raise ValueError("concurrent_workflow_inputs_during_read_retry_required")
    try:
        knowledge = evidence.retrieve(request.workflow_id, metrics, sessions, declaration,
                                      root=knowledge_root, release_id=request.release_id, background_metrics=background_metrics,
                                      result_metric_id=request.result_metric_id or ("STR-11" if declared_request["task_id"] else "BODY-MASS-DAILY"))
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        knowledge = {"status": "service_failure", "queries": [], "release_id": request.release_id,
                     "reason_codes": [type(exc).__name__], "facts_preserved": True}
    facts, missing = describe(metrics)
    hypotheses = factors(metrics) if request.workflow_id in {"W1", "W2", "W4"} else []
    if request.workflow_id == "W4" and "STR-11" not in metrics:
        kind = "body_mass" if "BODY-MASS-DAILY" in metrics else "sleep_state"
        hypotheses = [h for h in hypotheses if h["hypothesis_id"] == kind]
    factor_contexts = session_contexts if request.include_session_background else before_training
    if factor_contexts:
        hypotheses = [h for h in hypotheses if h["hypothesis_id"] not in {"sleep_state", "body_mass"}] + pretraining_factors(factor_contexts)
    hypotheses = attach_evidence(hypotheses, knowledge)
    supplements = {}
    if declaration.get("status") == "restricted_requires_reconfirmation":
        supplements["context_restriction"] = declaration
    if current_body:
        supplements["current_body_context"] = {**current_body,
            "identity": "background_visible_at_advice_cutoff_not_a_completed_training_record"}
    if request.include_session_background:
        supplements["training_session_contexts"] = session_contexts
    if source_report:
        supplements["source_report"] = source_report
    if strength_points:
        supplements["strength_points"] = strength_points
        supplements["long_term_review"] = long_review
        supplements["pretraining_contexts"] = before_training
    if request.workflow_id == "W4" and request.period:
        from .calendar import comparison
        supplements["calendar_comparison"] = comparison(repo, declared_request, selected_context)
        mid = request.result_metric_id or ("STR-11" if request.task_id else "BODY-MASS-DAILY")
        partial_task = next((t for t in partial_period["strength_tasks"] if t["task_id"] == declared_request["task_id"]), None)
        partial_metric = ((partial_task or {}).get("metrics", {}).get(mid) if mid == "STR-11" else partial_period["metrics"][mid])
        supplements["partial_current_period"] = {"start": partial_period["window_start"], "end": partial_period["window_end"],
            "cutoff_time": declared_request["cutoff_time"], "metric_id": mid, "metric": partial_metric,
            "identity": "current_partial_calendar_period_not_compared_as_complete_total"}
        partial_followup = {key: partial_period["metrics"][key] for key in ("STR-27", "STR-28", "REPORT-RECOMMENDATION-FOLLOWUP")} if mid == "STR-11" else {}
        if selected_task:
            # Feedback belongs to the selected task even without a completed
            # reference in this period (e.g. a declined candidate).
            scoped_metrics(repo, declared_request, partial_period, selected_task, partial_followup)
        supplements["partial_current_period"]["followup"] = partial_followup
    if request.workflow_id == "W3":
        supplements["vo2_segments"] = vo2_segments(metrics["OBS-VO2-REPORTED"])
    if request.workflow_id == "W5":
        supplements["energy_coverage"] = energy_coverage(metrics["ENERGY-DEVICE-TOTAL"])
        supplements["identifiability_model"] = {"equations": ["D = E + b", "Q = I - E"],
            "unknowns": ["intake I", "true expenditure E", "device bias b", "tissue storage Q"],
            "invariance": "(I+c, E+c, b-c) preserves D and Q",
            "conclusion": "该模型无独立约束时不能唯一识别 I；体重不是已测得的组织储能 Q。",
            "identity": "algebraic_model_limitation_not_missing_literature_as_proof"}
    nodes = _nodes(declared_request, metrics, facts, missing, hypotheses, knowledge, supplements)
    nodes[2]["long_term_review_trigger"] = long_review["start_long_term_review"]
    nodes[3]["branch"] = "long_term_review" if long_review["start_long_term_review"] else "ordinary_review"
    nodes[3]["pretraining_reference_ids"] = [item["reference_record_id"] for item in before_training]
    candidate = None
    linked_candidate_bases = []
    if request.candidate_id:
        if request.workflow_id not in {"W1", "W4"} or (advice is None and not declared_request["task_id"]):
            raise ValueError("candidate_requires_selected_strength_task")
        candidate = next((row for row in TrainingService(repo).list_recommendations(cutoff_time=declared_request["cutoff_time"])
                          if row["candidate_id"] == request.candidate_id), None)
        if (candidate is None or (advice is not None and candidate["input_snapshot"].get("session_exercise_id") != request.session_exercise_id)
                or (advice is None and candidate["input_snapshot"].get("advice_context", {}).get("task_id") != declared_request["task_id"])
                or instant(candidate["created_at"]) > instant(declared_request["cutoff_time"])):
            raise ValueError("candidate_not_visible_or_not_for_selected_task")
        numerical = candidate["candidate"]["proposed_change"].get("load") is not None
        nodes[5].update(truth=True if numerical else None, status="completed" if numerical else "bounded",
                        candidate_ids=[candidate["candidate_id"]], action_identity="frozen_optional_task_requires_current_use_check")
        outcome = next((row for row in (metrics.get("STR-27", {}).get("value") or [])
                        if row["recommendation_id"] == candidate["candidate_id"]), None)
        if outcome:
            executed = outcome["execution_state"]
            nodes[6].update(truth=True if executed == "executed" else False if executed == "not_executed" else None,
                status="completed" if executed in {"executed", "not_executed"} else "bounded",
                outcome_reference={"metric_id": "STR-27", "recommendation_id": candidate["candidate_id"]},
                adoption=outcome["adoption"], execution_state=executed, task_met=outcome["short_term_success"])
    if request.workflow_id in {"W1", "W4"} and declared_request["task_id"]:
        from healthzip.advice import candidate_basis
        linked_candidate_bases = [candidate_basis(row) for row in TrainingService(repo).list_recommendations(cutoff_time=declared_request["cutoff_time"])
            if row["input_snapshot"].get("advice_context", {}).get("task_id") == declared_request["task_id"]]
        nodes[5].update(candidate_ids=[b["candidate_id"] for b in linked_candidate_bases],
            action_identity="existing_frozen_candidates_require_current_use_check")
    if request.workflow_id == "W4":
        outcomes = metrics.get("STR-27", {}).get("value") or []
        nodes[6].update(outcome_references=[{"metric_id": "STR-27", "recommendation_id": row["recommendation_id"],
            "adoption": row["adoption"], "execution_state": row["execution_state"], "task_met": row["short_term_success"]} for row in outcomes])
    supplements["followup"] = {mid: metrics[mid] for mid in ("STR-27", "STR-28", "REPORT-RECOMMENDATION-FOLLOWUP") if mid in metrics}
    task_selection = {key: selected_task.get(key) for key in ("task_id", "exercise_id", "exercise_name", "condition_key", "protocol")} if selected_task else None
    target = {"instance_id": advice["instance"]["id"], "condition": advice["instance"]["condition"],
              "effective_targets": advice["effective_targets"], "selected_target": advice["selected_target"]} if advice else None
    snapshot = {key: analysis[key] for key in ("cutoff_time", "window_start", "window_end", "timezone", "algorithm_version",
                "retrospective", "period", "reference_selection", "sleep_selection")}
    snapshot.update(metrics={mid: metric for mid, metric in metrics.items() if not mid.startswith("OBS-")},
                    observations={mid: metric for mid, metric in metrics.items() if mid.startswith("OBS-")},
                    task_selection=task_selection, target=target,
                    candidate_ref={key: candidate[key] for key in ("candidate_id", "cutoff_time", "created_at", "theory_version")}
                        if candidate else None)
    if selected_context.get("baseline_window"):
        analysis["dependency_window_start"] = min(analysis["window_start"], selected_context["baseline_window"]["start"], key=instant)
        snapshot["dependency_window_start"] = analysis["dependency_window_start"]
    if background_contexts:
        analysis["dependency_window_start"] = min([analysis.get("dependency_window_start", analysis["window_start"])] +
            [m["window"]["start"] for ctx in background_contexts for m in ctx["metrics"].values()], key=instant)
        snapshot["dependency_window_start"] = analysis["dependency_window_start"]
    if partial_period:
        analysis["dependency_window_end"] = partial_period["window_end"]
        snapshot["dependency_window_end"] = analysis["dependency_window_end"]
    # Audit IDs are transport receipts, not changes to scientific dependencies.
    stable_knowledge = evidence.identity(knowledge)
    dependencies = dependency_inputs(repo, declared_request, analysis, selected_task=selected_task,
        visible_at=datetime.now(timezone.utc).isoformat() if request.mode == "retrospective" else None)
    input_hash = canonical_hash({"request": declared_request, "version": VERSION,
        "snapshot": scientific_identity(snapshot), "knowledge": stable_knowledge, "declaration": declaration,
        "dependencies": dependencies, "supplements": scientific_identity(supplements), "candidate_bases": linked_candidate_bases})
    run_id = canonical_hash({"workflow": request.workflow_id, "scope": "local", "input_hash": input_hash})
    analysis_payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False)
    analysis_id = canonical_hash(snapshot)
    now = datetime.now(timezone.utc).isoformat()
    result = {"run_id": run_id, "parent_run_id": parent_run_id, "workflow_id": request.workflow_id,
        "workflow_version": VERSION, "title": FUNCTION_NAMES[WORKFLOWS[request.workflow_id]["task"]],
        "user_scope": "local", "request": declared_request, "context_id": declaration["context_id"],
        "analysis_run_id": analysis_id, "input_hash": input_hash, "created_at": now, "dependencies": dependencies,
        "input_consistency": {"scheme": "optimistic_input_versions_before_read_and_at_freeze",
            "data_visible_at": data_visible_at, "input_revision": input_revision,
            "event_cutoff_time": declared_request["cutoff_time"]},
        "status": "needs_review" if any(n["status"] == "needs_review" for n in nodes) else "bounded" if facts else "needs_data",
        "nodes": nodes, "facts": facts, "missing": missing,
        "hypotheses": hypotheses, "knowledge": knowledge, "supplements": supplements,
        "candidate_ids": [candidate["candidate_id"]] if candidate else [b["candidate_id"] for b in linked_candidate_bases],
        "linked_candidate_bases": linked_candidate_bases, "task_selection": task_selection,
        "next_steps": [{**item["next_step"], "metric_id": item["metric_id"], "reasons": item["reason_codes"]} for item in missing],
        "limitations": ["观察、描述、来源解释和行动权限分别核对。", "缺预测/因果方法不抹去已记录事实。"]}
    if repo.conn.in_transaction:
        raise ValueError("save_pending_edits_before_workflow")
    repo.conn.execute("BEGIN IMMEDIATE")
    try:
        if input_version(repo, request.context_id) != input_revision:
            # No retrieval/external service under this lock. Only when clocks
            # changed, recheck local relevant inputs to permit unrelated writes.
            current_version = input_version(repo, request.context_id)
            current_dependencies = dependency_inputs(repo, declared_request, dependency_analysis,
                selected_task=selected_task, visible_at=datetime.now(timezone.utc).isoformat())
            nonrecord_keys = set(input_revision) - {"training_data_version", "source_data_version"}
            if (before_dependencies != dependencies or before_dependencies != current_dependencies
                    or any(input_revision[k] != current_version.get(k) for k in nonrecord_keys)):
                raise ValueError("concurrent_relevant_workflow_inputs_changed_retry_required")
        existing = repo.conn.execute("SELECT result_json FROM workflow_run WHERE run_id=? AND user_id='local'", (run_id,)).fetchone()
        if existing:
            repo.conn.commit()
            return json.loads(existing[0])
        repo.conn.execute("INSERT OR IGNORE INTO analysis_run(run_id,cutoff_time,computed_at,algorithm_version,data_hash,result_json) VALUES(?,?,?,?,?,?)",
            (analysis_id, declared_request["cutoff_time"], now, analysis["algorithm_version"], input_hash, analysis_payload))
        repo.conn.execute("INSERT INTO workflow_run VALUES(?,?,?,?,?,?,?,?,?,?)", (run_id, "local", request.workflow_id,
            VERSION, parent_run_id, analysis_id, json.dumps(declared_request, sort_keys=True), input_hash,
            json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False), now))
        repo.conn.commit()
        return result
    except BaseException:
        repo.conn.rollback()
        raise


def resume_workflow(repo, run_id, *, context_id=None, cutoff_time=None, candidate_id=None, selection_analysis_id=None, knowledge_root=".local/knowledge"):
    previous = load_run(repo, run_id)
    request = WorkflowRequest(**previous["request"])
    request = replace(request, context_id=context_id if context_id is not None else request.context_id,
                      cutoff_time=cutoff_time or datetime.now(timezone.utc).isoformat(), trigger="context_updated",
                      selection_analysis_id=selection_analysis_id if selection_analysis_id is not None else request.selection_analysis_id,
                      candidate_id=candidate_id if candidate_id is not None else request.candidate_id)
    return run_workflow(repo, request, knowledge_root=knowledge_root, parent_run_id=run_id)
