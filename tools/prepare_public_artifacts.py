"""Project public audit files without changing private corpora or evaluation results.

Run before publishing regenerated artifacts. Original file/output hashes identify
the unprojected evidence; public-output hashes identify the readable projection.
This tool does not grant permission to redistribute any source article.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTION_VERSION = "public-artifacts-1.1.0"
EVALUATIONS = (
    "artifacts/knowledge/visible_eval.json",
    "artifacts/knowledge/holdout_eval.json",
    "artifacts/knowledge/rag_eval_cases_latest_eval.json",
    "artifacts/knowledge/rag_holdout_latest_eval.json",
)
SPAN_FIELDS = {"span_id", "source_id", "version_id", "text_hash", "locator_json", "rights_json"}
RIGHTS_FIELDS = {
    "license_id", "license_url", "index_allowed", "redistribution_allowed",
    "derivative_redistribution_allowed", "declared_use", "evidence_locator", "review",
    "rights_scope", "status", "usage_restriction",
    "scope_policy_version", "scope_id", "scope_kind", "inherited_from_scope",
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def redact_local_paths(value: str) -> str:
    value = value.replace(str(ROOT), "<repo>")
    value = re.sub(r"/home/[^/\s'\"<>]+", "<home>", value)
    return re.sub(r"/tmp/pytest-of-[^/\s'\"<>]+", "<pytest-temp>", value)


def write_json(path: Path, value) -> None:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if not path.exists() or path.read_bytes() != raw:
        path.write_bytes(raw)


def project_span(span: dict) -> dict:
    result = {key: value for key, value in span.items() if key in SPAN_FIELDS}
    rights = json.loads(result["rights_json"])
    result["rights_json"] = canonical({key: value for key, value in rights.items() if key in RIGHTS_FIELDS})
    return result


def project_evaluation(value: dict, original_sha256: str) -> tuple[dict, int]:
    before_counts = canonical(value["counts"])
    span_count = 0
    for case in value["cases"]:
        output = case["output"]
        for candidate in output.get("retrieval", {}).get("candidates", []):
            original = candidate.get("spans", [])
            candidate["spans"] = [project_span(span) for span in original]
            span_count += len(original)
        # output_sha256 deliberately remains the original semantic-review binding.
        case["public_output_sha256"] = digest(canonical(output).encode())
    previous = value.get("publication_projection", {})
    value["publication_projection"] = {
        "version": PROJECTION_VERSION,
        "original_artifact_sha256": previous.get("original_artifact_sha256", original_sha256),
        "scope": "retrieval spans only: ID, exact source version, text hash, locator and rights status",
        "removed": ["source text", "structured source content", "article metadata", "license prose"],
        "span_occurrences_projected": span_count,
        "case_output_sha256_scope": "Unprojected original result; existing semantic annotation binding is unchanged.",
        "case_public_output_sha256_scope": "Canonical JSON of the published output after source-content projection.",
        "evaluation_changed": False,
        "private_corpus_modified": False,
        "limits": "Public metadata is not a substitute for authorized source reading; no scores or adjudications were recomputed.",
    }
    assert canonical(value["counts"]) == before_counts
    return value, span_count


def prepare() -> dict:
    audit_path = ROOT / "artifacts/verification/publication-projection.json"
    audit = json.loads(audit_path.read_text()) if audit_path.exists() else {
        "projection_version": PROJECTION_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Public artifacts only; source bytes, private databases and core source code are untouched.",
        "files": {},
    }
    audit["projection_version"] = PROJECTION_VERSION
    changed = {}

    def record(path: Path, before: bytes, policy: str, **extra):
        relative = str(path.relative_to(ROOT))
        after = path.read_bytes()
        old = audit["files"].get(relative, {})
        original = old.get("original_file_sha256", digest(before)) if digest(before) == old.get("public_file_sha256") else digest(before)
        audit["files"][relative] = {
            "original_file_sha256": original,
            "public_file_sha256": digest(after),
            "policy": policy,
            **extra,
        }
        if before != after:
            changed[relative] = {"before": digest(before), "after": digest(after)}

    for name in EVALUATIONS:
        path = ROOT / name
        before = path.read_bytes()
        value, count = project_evaluation(json.loads(before), digest(before))
        write_json(path, value)
        record(path, before, "source_span_metadata_allowlist", span_occurrences_projected=count)

    for path in sorted((ROOT / "artifacts").rglob("*.xml")):
        before = path.read_bytes()
        root = ET.fromstring(before)
        if root.tag not in {"testsuite", "testsuites"}:
            continue
        removed = 0
        redacted = False
        for element in root.iter():
            if "hostname" in element.attrib:
                del element.attrib["hostname"]
                removed += 1
            for key, value in list(element.attrib.items()):
                clean = redact_local_paths(value)
                redacted |= clean != value
                element.set(key, clean)
            for field in ("text", "tail"):
                value = getattr(element, field)
                if value:
                    clean = redact_local_paths(value)
                    redacted |= clean != value
                    setattr(element, field, clean)
        if removed or redacted:
            path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
        record(path, before, "redact_JUnit_hostnames_and_local_paths_preserve_all_test_results")

    path = ROOT / "artifacts/verification/build.txt"
    before = path.read_bytes()
    text = redact_local_paths(before.decode())
    if text.encode() != before:
        path.write_text(text)
    record(path, before, "replace_local_repository_and_home_paths")

    # Update only explicit pointers to changed public files, never source/dataset
    # hashes, original model-output hashes or other scientific identifiers.
    def refresh_references(value):
        touched = False
        if isinstance(value, dict):
            artifact = value.get("artifact")
            if artifact in changed and "sha256" in value:
                entry = audit["files"][artifact]
                value["sha256"] = entry["public_file_sha256"]
                value["publication_projection"] = {
                    "version": PROJECTION_VERSION,
                    "original_file_sha256": entry["original_file_sha256"],
                    "policy": entry["policy"],
                    "test_results_changed": False,
                }
                touched = True
            for key, child in value.items():
                if key == "source_file_sha256" and isinstance(child, dict):
                    for name in child:
                        if name in changed:
                            child[name] = changed[name]["after"]
                            touched = True
                elif refresh_references(child):
                    touched = True
        elif isinstance(value, list):
            for child in value:
                if refresh_references(child):
                    touched = True
        return touched

    reference_files = sorted((ROOT / "artifacts").rglob("*.json")) + [ROOT / "docs/science_traceability.json"]
    for path in reference_files:
        if path == audit_path or str(path.relative_to(ROOT)) in EVALUATIONS:
            continue
        before = path.read_bytes()
        value = json.loads(before)
        if refresh_references(value):
            write_json(path, value)
            record(path, before, "refresh_explicit_public_artifact_hash_references")

    audit["checks"] = audit_public()
    write_json(audit_path, audit)
    return {"changed_files": sorted(changed), "checks": audit["checks"]}


def audit_public() -> dict:
    spans = 0
    cases = 0
    for name in EVALUATIONS:
        value = json.loads((ROOT / name).read_text())
        assert value["publication_projection"]["evaluation_changed"] is False
        for case in value["cases"]:
            cases += 1
            assert digest(canonical(case["output"]).encode()) == case["public_output_sha256"]
            for candidate in case["output"].get("retrieval", {}).get("candidates", []):
                for span in candidate.get("spans", []):
                    assert set(span) <= SPAN_FIELDS
                    assert set(json.loads(span["rights_json"])) <= RIGHTS_FIELDS
                    spans += 1
    junit = 0
    for path in (ROOT / "artifacts").rglob("*.xml"):
        root = ET.fromstring(path.read_bytes())
        if root.tag in {"testsuite", "testsuites"}:
            assert all("hostname" not in element.attrib for element in root.iter())
            for element in root.iter():
                assert all(redact_local_paths(value) == value for value in [*element.attrib.values(), element.text or "", element.tail or ""])
            junit += 1
    assert not re.search(r"/home/[^/\s'\"]+", (ROOT / "artifacts/verification/build.txt").read_text())
    for name in ("artifacts/science/acceptance-results.json", "docs/science_traceability.json"):
        run = json.loads((ROOT / name).read_text())["test_run"]
        assert run["sha256"] == digest((ROOT / run["artifact"]).read_bytes())
    return {"status": "passed", "evaluation_files": len(EVALUATIONS), "case_outputs": cases,
            "source_span_occurrences": spans, "junit_files": junit,
            "source_text_in_retrieval_spans": 0, "junit_hostname_attributes": 0,
            "test_reference_hashes_match": True}


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False, indent=2))
