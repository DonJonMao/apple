"""Permanent, content-addressed report content in the existing workspace database.

These objects are historical records, never entries in an evictable cache.
Existing reports remain inline and are not migrated or recomputed.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

FORMAT = "frozen-report-references-1"


def save_object(repo, kind, payload):
    """Append-only immutable content. The caller owns the commit boundary."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
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
    for question in content.get("questions", []):
        frozen = dict(question)
        if question.get("ordinary_training"):
            ordinary = question["ordinary_training"]
            # Request-local identical objects may be shared by the producer.
            # This only avoids encoding twice; stored identity is content based.
            if id(ordinary) not in ordinary_objects:
                ordinary_objects[id(ordinary)] = save_object(repo, "ordinary-training", ordinary)
            frozen["ordinary_training"] = ordinary_objects[id(ordinary)]
        evidence = dict(question.get("evidence") or {})
        if "evidence_spans" in evidence:
            evidence["evidence_spans"] = [save_object(repo, "evidence-span", span) for span in evidence["evidence_spans"]]
        frozen["evidence"] = evidence
        questions.append(frozen)
    content["questions"] = questions
    identity = save_object(repo, FORMAT, content)["$frozen_object"]
    repo.conn.commit()
    return {"storage_format": FORMAT, "content_ref": identity,
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
    for question in content.get("questions", []):
        ordinary = question.get("ordinary_training") or {}
        if "$frozen_object" in ordinary:
            question["ordinary_training"] = resolve(ordinary)
        evidence = question.get("evidence") or {}
        if "evidence_spans" in evidence:
            evidence["evidence_spans"] = [resolve(span) if "$frozen_object" in span else span
                                          for span in evidence["evidence_spans"]]
    reference = content.pop("current_ref")
    current = repo.one("SELECT result_json FROM analysis_run WHERE run_id=?", (reference["id"],))
    if current is None:
        raise ValueError("frozen_report_analysis_missing")
    return {**content, "current": _decode_content(current[0], fast_compatible)}


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

    if manifest.get("storage_format") == FORMAT:
        reference = {"$frozen_object": manifest["content_ref"]}
        collect(reference)
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
    return {"format": "healthzip-frozen-audit-2", "report_manifest": manifest,
            "content_objects": objects, "workflow_runs": runs, "analysis_objects": analyses,
            "scope": "frozen observations, methods and selected evidence; not a fresh recommendation"}


def reconstruct_report(bundle):
    """Rebuild the public report offline, without the original database or web."""
    manifest = bundle["report_manifest"]
    if manifest.get("storage_format") != FORMAT:
        return dict(manifest)
    resolved = {}
    def resolve(value):
        if isinstance(value, dict):
            if set(value) == {"$frozen_object"}:
                identity = value["$frozen_object"]
                if identity not in resolved:
                    resolved[identity] = resolve(bundle["content_objects"][identity])
                return resolved[identity]
            return {key: resolve(child) for key, child in value.items()}
        if isinstance(value, list):
            return [resolve(child) for child in value]
        return value
    content = resolve(bundle["content_objects"][manifest["content_ref"]])
    reference = content.pop("current_ref")
    content["current"] = bundle["analysis_objects"][reference["id"]]
    return {**content, **{key: value for key, value in manifest.items()
                         if key not in {"storage_format", "content_ref", "content_decoder"}}}
