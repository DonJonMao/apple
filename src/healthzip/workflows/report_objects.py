"""Permanent, content-addressed report content in the existing workspace database.

These objects are historical records, never entries in an evictable cache.
Existing reports remain inline and are not migrated or recomputed.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

LEGACY_FORMAT = "frozen-report-references-1"
FORMAT = "frozen-report-references-2"
WORKFLOW_FORMAT = "workflow-training-references-1"


def report_findings(payload):
    """Use recorded primary facts, including useful context-only observations."""
    from healthzip.analytics.health_context import joint_observations
    current = payload["current"]
    context = current.get("joint_health_context") or {}
    dates = context.get("dates_by_metric", {})
    if any(dates.get(mid) for mid in ("STATE-RHR", "STATE-SDNN", "sleep")) or context.get("training_sessions"):
        return joint_observations(current)["statements"]
    observations = [q["observation"] for q in payload.get("questions", [])
                    if q.get("report_status") in {"available", "background_only"} and q.get("observation")]
    return list(dict.fromkeys(observations))[:3] or ["本期尚无可对齐的完整日身体比较；以下保留已记录事实与局部结果。"]


def reading_view(payload):
    """Explicit small frozen reading projection, not a recomputed analysis."""
    from healthzip.analytics.health_context import (
        joint_observations,
        sleep_comparison_metric,
        stream_labels,
    )
    current = payload["current"]
    if not all(k in current for k in ("window_start", "window_end", "cutoff_time", "timezone")):
        return {"version": "report-reading-view-2", "window": {}, "findings": [], "charts": [],
                "limitation": "此冻结内容未提供标准周期阅读字段，原始内容仍可完整读取。"}
    observations = joint_observations(current)
    charts = []
    for mid, title, unit, scale in (("STATE-RHR", "静息心率", "bpm", 1),
            ("STATE-SDNN", "SDNN", "ms", 1), ("REPORT-STATE-SUMMARY", "已记录睡眠", "小时", 60)):
        metric = current.get("metrics", {}).get(mid, {})
        if mid == "REPORT-STATE-SUMMARY":
            metric = sleep_comparison_metric(metric)
        streams = []
        original_streams = metric.get("comparison", {}).get("streams", [])
        for stream, label in zip(original_streams, stream_labels(original_streams)):
            compact = {k: v for k, v in stream.items() if k not in {"current", "previous", "reference"}}
            compact["display_label"] = label
            for name in ("current", "previous", "reference"):
                period = stream.get(name, {})
                compact[name] = {k: v for k, v in period.items() if k not in {
                    "daily_points", "partial_daily_points", "source_record_ids", "exclusions", "records"}}
                for field in ("daily_points", "partial_daily_points"):
                    compact[name][field] = [{k: v for k, v in point.items() if k in {
                        "date", "value", "n", "raw_record_count", "conditions", "fact_id"}}
                        for point in period.get(field, [])]
            streams.append(compact)
        if any(s.get("current", {}).get("value") is not None or s.get("current", {}).get("partial_daily_points") for s in streams):
            charts.append({"metric_id": mid, "title": title, "unit": unit, "scale": scale,
                           "comparison": {"streams": streams}})
    tasks = current.get("strength_tasks", [])
    return {"version": "report-reading-view-2", "window": {"start": current["window_start"],
        "end": current["window_end"], "cutoff_time": current["cutoff_time"], "timezone": current["timezone"]},
        "findings": report_findings(payload), "charts": charts,
        "training": {"task_count": len(tasks),
            "source_record_count": len({i for task in tasks for i in task.get("source_record_ids", [])})},
        "global_metric_count": len(current.get("metrics", {})),
        "joint_fact_id": observations["context"].get("fact_id")}


def _save_training(repo, ordinary, *, include_preview=True, allow_nan=True):
    # Each scientific group retains its own identity. This is storage sharing,
    # not pooling unknown conditions or choosing a best set.
    groups = [save_object(repo, "ordinary-training-series", group, allow_nan=allow_nan)
              for group in ordinary.get("series", [])]
    header = {k: v for k, v in ordinary.items() if k != "series"}
    reference = save_object(repo, "ordinary-training", {**header, **({"series": groups} if "series" in ordinary else {})},
                            allow_nan=allow_nan)
    if not include_preview:
        return reference, None
    index = [{"series_id": group["series_id"], "summary": group["summary"],
              "record_count": group["record_count"], "reference": reference}
             for group, reference in zip(ordinary.get("series", []), groups)]
    preview = {k: v for k, v in header.items() if k in {"version", "window", "record_count", "limitations", "identity"}}
    return reference, {**preview, "index_ref": save_object(repo, "ordinary-training-index", index)}


def save_workflow(repo, result):
    """Freeze a storage copy inside the caller's existing workflow transaction."""
    ordinary = result.get("supplements", {}).get("ordinary_training")
    if not ordinary:
        return result
    reference, _ = _save_training(repo, ordinary, include_preview=False, allow_nan=False)
    return {**result, "storage_format": WORKFLOW_FORMAT,
            "supplements": {**result["supplements"], "ordinary_training": reference}}


def read_workflow(repo, stored):
    """Restore the unchanged public workflow contract, including legacy rows."""
    if "storage_format" not in stored:
        return stored
    if stored["storage_format"] != WORKFLOW_FORMAT:
        raise ValueError("unsupported_workflow_storage_format")
    ordinary = read_object(repo, stored["supplements"]["ordinary_training"])
    if "series" in ordinary:
        references = ordinary["series"]
        identities = list(dict.fromkeys(group["$frozen_object"] for group in references))
        rows = repo.rows("SELECT object_id,payload_json FROM report_content_object WHERE user_id='local' "
                         "AND object_id IN (SELECT value FROM json_each(?))", (json.dumps(identities),)) if identities else []
        groups = {row["object_id"]: row["payload_json"] for row in rows}
        if len(groups) != len(identities):
            raise ValueError("frozen_report_content_missing")
        # Restore list order, including repeated references, with independent
        # mutable values. The parser retains stdlib integer/float semantics.
        ordinary["series"] = [json.loads(groups[group["$frozen_object"]]) for group in references]
    return {**{key: value for key, value in stored.items() if key != "storage_format"},
            "supplements": {**stored["supplements"], "ordinary_training": ordinary}}


def save_object(repo, kind, payload, *, allow_nan=True):
    """Append-only immutable content. The caller owns the commit boundary."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=allow_nan)
    scope = json.dumps([str(repo.path.resolve()), repo.path.stat().st_ino, "local", kind])
    identity = hashlib.sha256((scope + "\0" + encoded).encode()).hexdigest()
    repo.conn.execute("INSERT OR IGNORE INTO report_content_object VALUES(?,?,?,?,?)",
                      (identity, "local", kind, encoded, datetime.now(timezone.utc).isoformat()))
    return {"$frozen_object": identity}


def read_object(repo, reference, *, fast_compatible=False):
    row = repo.one("SELECT payload_json FROM report_content_object WHERE object_id=? AND user_id='local'",
                   (reference["$frozen_object"],))
    if row is None:
        raise ValueError("frozen_report_content_missing")
    from .period_report import _decode_content
    return _decode_content(row[0], fast_compatible)


def save_content(repo, payload):
    from .period_report import _fast_json_compatible
    # Validate the complete public content once, before it becomes immutable.
    # This flag covers the canonical analysis and every referenced object, not
    # just the small manifest. Older or integer/float edge-case content keeps
    # the standard parser without losing original precision or nonfinite values.
    fast_compatible = _fast_json_compatible(payload)
    # The canonical analysis already has an immutable persisted identity. Do not
    # serialize another copy in each report or in the content object.
    content = {key: value for key, value in payload.items() if key != "current"}
    content["current_ref"] = {"table": "analysis_run", "id": payload["analysis_run_id"]}
    questions = []
    ordinary_objects = {}
    question_previews = []
    for question in content.get("questions", []):
        frozen = dict(question)
        if question.get("ordinary_training"):
            ordinary = question["ordinary_training"]
            # Request-local identical objects may be shared by the producer.
            # This only avoids encoding twice; stored identity is content based.
            if id(ordinary) not in ordinary_objects:
                ordinary_objects[id(ordinary)] = _save_training(repo, ordinary)
            frozen["ordinary_training"] = ordinary_objects[id(ordinary)][0]
        evidence = dict(question.get("evidence") or {})
        if "evidence_spans" in evidence:
            evidence["evidence_spans"] = [save_object(repo, "evidence-span", span) for span in evidence["evidence_spans"]]
        frozen["evidence"] = evidence
        reference = save_object(repo, "report-question", frozen)
        questions.append(reference)
        preview = {k: v for k, v in question.items() if k in {
            "id", "title", "topic_status", "report_status", "observation", "steps", "limitations", "fact_id",
            "analysis_version", "analysis_identity", "window", "source_filter", "goal_context"}}
        preview["evidence"] = {k: v for k, v in evidence.items() if k != "evidence_spans"}
        preview["details_ref"] = reference
        preview["row_count"] = len(question.get("rows", []))
        if question.get("ordinary_training"):
            preview["ordinary_training"] = ordinary_objects[id(question["ordinary_training"])][1]
        question_previews.append(preview)
    content["questions"] = questions
    identity = save_object(repo, FORMAT, content)["$frozen_object"]
    small = {k: v for k, v in payload.items() if k not in {"current", "questions", "objective_comparisons"}}
    small.update(questions=question_previews, reading_view=reading_view(payload))
    reading = save_object(repo, "report-reading-view", small)["$frozen_object"]
    repo.conn.commit()
    return {"storage_format": FORMAT, "content_ref": identity,
            "reading_ref": reading,
            "version": payload["version"], "period": payload["period"],
            "content_decoder": "orjson-compatible-1" if fast_compatible else "stdlib"}


def read_content(repo, manifest):
    from .period_report import _decode_content
    fast_compatible = manifest.get("content_decoder") == "orjson-compatible-1"
    row = repo.one("SELECT payload_json FROM report_content_object WHERE object_id=? AND user_id='local'",
                   (manifest["content_ref"],))
    if row is None:
        raise ValueError("frozen_report_content_missing")
    content = _decode_content(row[0], fast_compatible)
    resolved = {}
    def resolve(reference):
        identity = reference["$frozen_object"]
        if identity not in resolved:
            resolved[identity] = read_object(repo, reference, fast_compatible=fast_compatible)
        return resolved[identity]
    content["questions"] = [resolve(q) if "$frozen_object" in q else q for q in content.get("questions", [])]
    for question in content.get("questions", []):
        ordinary = question.get("ordinary_training") or {}
        if "$frozen_object" in ordinary:
            question["ordinary_training"] = resolve(ordinary)
            if "series" in question["ordinary_training"]:
                question["ordinary_training"]["series"] = [resolve(group) if "$frozen_object" in group else group
                    for group in question["ordinary_training"]["series"]]
        evidence = question.get("evidence") or {}
        if "evidence_spans" in evidence:
            evidence["evidence_spans"] = [resolve(span) if "$frozen_object" in span else span
                                          for span in evidence["evidence_spans"]]
    reference = content.pop("current_ref")
    current = repo.one("SELECT result_json FROM analysis_run WHERE run_id=?", (reference["id"],))
    if current is None:
        raise ValueError("frozen_report_analysis_missing")
    return {**content, "current": _decode_content(current[0], fast_compatible)}


def read_reading(repo, manifest):
    if manifest.get("reading_ref"):
        return read_object(repo, {"$frozen_object": manifest["reading_ref"]},
                           fast_compatible=manifest.get("content_decoder") == "orjson-compatible-1")
    # Old reports retain their frozen format. They are never silently rewritten.
    content = read_content(repo, manifest)
    return {**content, "legacy_read_requires_full_restore": True}


def read_question(repo, preview):
    """Only the explicitly requested question; trajectories have a separate index."""
    if "details_ref" not in preview:
        return preview
    question = read_object(repo, preview["details_ref"])
    if preview.get("ordinary_training"):
        question["ordinary_training"] = preview["ordinary_training"]
    return question


def audit_bundle(repo, report_id):
    """Self-contained manifest and unique objects, resolved only from frozen bytes."""
    row = repo.one("SELECT payload_json,markdown FROM joint_period_report WHERE report_id=? AND user_id='local'", (report_id,))
    if row is None:
        raise ValueError("joint_report_not_found")
    manifest = {**json.loads(row[0]), "markdown": row[1]}
    objects, runs, analyses = {}, {}, {}

    def collect(value):
        if isinstance(value, dict):
            if set(value) == {"$frozen_object"}:
                identity = value["$frozen_object"]
                if identity not in objects:
                    objects[identity] = read_object(repo, value)
                    collect(objects[identity])
            else:
                for child in value.values():
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    if manifest.get("storage_format") in {FORMAT, LEGACY_FORMAT}:
        reference = {"$frozen_object": manifest["content_ref"]}
        collect(reference)
        if manifest.get("reading_ref"):
            collect({"$frozen_object": manifest["reading_ref"]})
        content = objects[manifest["content_ref"]]
        current = content["current_ref"]["id"]
        frozen = repo.one("SELECT result_json FROM analysis_run WHERE run_id=?", (current,))
        if frozen is None:
            raise ValueError("frozen_report_analysis_missing")
        analyses[current] = json.loads(frozen[0])
    else:
        content = manifest
    for identity in (*content.get("workflow_run_ids", []), *content.get("historical_run_ids", [])):
        frozen = repo.one("SELECT result_json,analysis_run_id FROM workflow_run WHERE run_id=? AND user_id='local'", (identity,))
        if frozen is None:
            raise ValueError("frozen_report_workflow_missing")
        runs[identity] = json.loads(frozen[0])
        collect(runs[identity])
        if frozen[1] not in analyses:
            analysis = repo.one("SELECT result_json FROM analysis_run WHERE run_id=?", (frozen[1],))
            if analysis is None:
                raise ValueError("frozen_report_workflow_analysis_missing")
            analyses[frozen[1]] = json.loads(analysis[0])
    format_name = ("healthzip-frozen-audit-3" if any(run.get("storage_format") == WORKFLOW_FORMAT for run in runs.values())
                   else "healthzip-frozen-audit-2")
    return {"format": format_name, "report_manifest": manifest,
            "content_objects": objects, "workflow_runs": runs, "analysis_objects": analyses,
            "scope": "frozen observations, methods and selected evidence; not a fresh recommendation"}


def _resolve_bundle_objects(bundle, value, *, share_references=True):
    resolved = {}

    def resolve(value):
        if isinstance(value, dict):
            if set(value) == {"$frozen_object"}:
                identity = value["$frozen_object"]
                if identity not in resolved:
                    resolved[identity] = resolve(bundle["content_objects"][identity])
                elif not share_references:
                    # Workflow consumers receive the same independent mutable
                    # values as load_run, even when a series occurs twice.
                    return deepcopy(resolved[identity])
                return resolved[identity]
            return {key: resolve(child) for key, child in value.items()}
        if isinstance(value, list):
            return [resolve(child) for child in value]
        return value
    return resolve(value)


def reconstruct_workflow(bundle, run_id):
    """Restore one workflow from either audit format, without current records."""
    if bundle.get("format") not in {"healthzip-frozen-audit-2", "healthzip-frozen-audit-3"}:
        raise ValueError("unsupported_frozen_audit_format")
    result = _resolve_bundle_objects(bundle, bundle["workflow_runs"][run_id], share_references=False)
    if "storage_format" in result:
        if result.pop("storage_format") != WORKFLOW_FORMAT:
            raise ValueError("unsupported_workflow_storage_format")
    return result


def reconstruct_report(bundle):
    """Rebuild the public report offline, without the original database or web."""
    manifest = bundle["report_manifest"]
    if manifest.get("storage_format") not in {FORMAT, LEGACY_FORMAT}:
        return dict(manifest)
    content = _resolve_bundle_objects(bundle, bundle["content_objects"][manifest["content_ref"]])
    reference = content.pop("current_ref")
    content["current"] = bundle["analysis_objects"][reference["id"]]
    return {**content, **{key: value for key, value in manifest.items()
                         if key not in {"storage_format", "content_ref", "reading_ref", "content_decoder"}}}
