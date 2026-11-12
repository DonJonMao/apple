"""Assemble v1.4 evidence without changing scientific labels or frozen outputs."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/v14"


def read(path):
    return json.loads((ROOT / path).read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def local_path_projection(text):
    text = text.replace(str(ROOT), "<repo>")
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"/home/[^/\s'\"<>]+", "<home>", text)
    return re.sub(r"/tmp/pytest-of-[^/\s'\"<>]+", "<pytest-temp>", text)


def main():
    # Only test diagnostics are projected here. Knowledge outputs and binding
    # hashes have their own allowlist projector and are deliberately untouched.
    projection_file = OUT / "test-publication-projection.json"
    previous = {entry["path"]: entry for entry in json.loads(projection_file.read_text())["files"]} if projection_file.exists() else {}
    projections = []
    for path in [*OUT.rglob("*.xml"), *OUT.rglob("*.txt")]:
        before = sha(path)
        original_text = path.read_text()
        value = original_text
        if path.suffix == ".xml":
            document = ET.fromstring(original_text)
            changed = False
            for element in document.iter():
                if "hostname" in element.attrib:
                    del element.attrib["hostname"]
                    changed = True
                for key, entry in list(element.attrib.items()):
                    clean = local_path_projection(entry)
                    if clean != entry:
                        element.set(key, clean)
                        changed = True
                for key in ("text", "tail"):
                    entry = getattr(element, key)
                    if entry:
                        clean = local_path_projection(entry)
                        if clean != entry:
                            setattr(element, key, clean)
                            changed = True
            if changed:
                value = ET.tostring(document, encoding="unicode")
        else:
            value = local_path_projection(original_text)
        # Clean XML is frozen evidence, including its serialization and whether
        # it has a final newline. Normalize only diagnostics that needed edits.
        if path.suffix != ".xml" or value != original_text:
            value = "\n".join(line.rstrip() for line in value.splitlines()).rstrip() + "\n"
        if value != original_text:
            path.write_text(value)
        relative = str(path.relative_to(ROOT))
        old = previous.get(relative, {})
        original_sha = old.get("original_sha256", before) if before == old.get("public_sha256") else before
        projections.append({"path": relative, "original_sha256": original_sha,
                            "public_sha256": sha(path), "test_results_changed": False})
    write(OUT / "test-publication-projection.json", {"files": projections})

    science = read("artifacts/v14/science/metric_audit_65.json")
    quality = read("artifacts/v14/knowledge/metric_audit_12.json")
    metrics = science["metrics"] + quality["metrics"]
    assert len(metrics) == len({m["metric_id"] for m in metrics}) == 77
    write(OUT / "metric-audit-77.json", {
        "baseline": science["review_baseline"], "metric_count": 77, "metrics": metrics,
        "scope": "Item-level implementation and bounded software verification, not 77 scientific validity claims.",
        "new_human_expert_reviews": 0, "new_real_personal_calibration": 0,
    })

    contract = read("Apple_v1.4_Codex_Execution_Pack/acceptance_manifest.json")
    catalog = read("artifacts/v14/catalog/coverage.json")
    media_totals = {item["media_type"]: item["objects"] for item in catalog.get("media_totals", [])}
    media_ready = {kind: sum(item["count"] for item in catalog.get("media", [])
                             if item["media_type"] == kind and item["fetch_status"] == "ready")
                   for kind in media_totals}
    media_complete = bool(media_totals) and media_ready == media_totals and not any(
        item["count"] for item in catalog.get("media", []) if item["fetch_status"] != "ready")
    media_summary = "; ".join(f"{kind}: {media_ready[kind]}/{count} ready" for kind, count in sorted(media_totals.items()))
    cases = []
    for original in contract["bug_cases"] + contract["feature_cases"]:
        identifier = original["id"]
        document = "docs/v14_catalog.md" if identifier.startswith("CAT") else "docs/v14_knowledge.md" if identifier.startswith("KB") else "docs/v14_delivery.md"
        state = "implemented_with_scoped_software_verification"
        limits = "See item-level evidence; software checks do not establish professional review or scientific efficacy."
        if identifier in {"KB-05", "E2E-09"}:
            state = "partial_semantic_coverage_independent_review_failed"
            limits = "Frozen independent AI rounds retained: 3/18; round 2 4/20; round 3 3/19 scorable plus one invalid rubric; round 4 10/24 pass, 6 partial, 8 fail; round 5 8/30 pass, 15 partial, 7 fail (87 points: 41 pass, 15 partial, 31 fail); round 6 3/12 pass, 6 partial, 3 fail (35 points: 17 pass, 6 partial, 12 fail). Subsequent replays are development verification, not a new independent pass rate. See docs/v14_knowledge.md."
        elif identifier in {"KB-01", "KB-02", "KB-03"}:
            state = "software_contract_verified_actual_textbook_body_gaps"
            limits = "Edition/chapter/rights gates work; paid source chapters not acquired."
        elif identifier == "CAT-10":
            state = "local_media_cache_complete_for_snapshot" if media_complete else "local_media_cache_partial_for_snapshot"
            limits = media_summary + ". Snapshot and readiness counts are from coverage.json; local verification does not establish remote whole-file checksums or universal codec support."
        elif identifier in {"CAT-09", "CAT-17"}:
            limits = "Chinese upstream/seed/AI draft identities and anatomical review status remain distinct; no professional mapping or stimulus weights inferred."
        cases.append({"id": identifier, "scenario": original["scenario"], "expected": original["expected"],
                      "state": state, "evidence_document": document, "limitations": limits})
    assert len(cases) == 63
    write(OUT / "acceptance-results.json", {"baseline": contract["baseline_commit"], "cases": cases,
                                          "all_product_semantics_passed": False})

    path = ROOT / "requirements_traceability.csv"
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields, rows = reader.fieldnames, [r for r in reader if not r["requirement_id"].startswith("V14-")]
    for item in [*cases, *metrics]:
        identifier = item.get("id", item.get("metric_id"))
        document = item.get("evidence_document", "artifacts/v14/metric-audit-77.json")
        rows.append({"requirement_id": "V14-" + identifier,
            "function_or_metric": item.get("scenario", identifier),
            "implementation_anchor": ";".join(item.get("implementation_paths", [])) or document,
            "contract": "Apple_v1.4_Codex_Execution_Pack/Codex_Goal_Prompt_v1.4.md",
            "evidence_refs": document,
            "verification_status": item.get("state", item.get("review_result")),
            "implementation": "see_item_evidence", "software_verification": "artifacts/v14/pytest.xml",
            "corpus_acquisition": "docs/v14_knowledge.md;docs/v14_catalog.md",
            "theory_review": "AI_content_application_check_where_explicit_not_independent_expert",
            "scientific_validation": "no_new_personal_real_world_or_causal_validation",
            "verification_evidence": document + ";artifacts/v14/final-manifest.json",
            "remaining_limits": item.get("limitations", item.get("scientific_validation_boundary", "Bounded software cases only")),
            "review_repair_ids": identifier, "review_verification_evidence": document})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    document = ET.parse(OUT / "pytest.xml")
    suites = list(document.getroot().iter("testsuite"))
    totals = {key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "errors", "failures", "skipped")}
    assert not totals["errors"] and not totals["failures"] and not totals["skipped"], totals
    totals["seconds"] = sum(float(s.get("time", 0)) for s in suites)
    assert (OUT / "ruff.txt").read_text().strip() == "All checks passed!"
    source_paths = [*ROOT.glob("src/**/*.py"), *ROOT.glob("src/**/*.json"), *ROOT.glob("src/**/*.html"),
                    *ROOT.glob("src/**/*.js"), *ROOT.glob("tools/*.py"), *ROOT.glob("tests/**/*.py"),
                    ROOT / "app.py", ROOT / "pyproject.toml", ROOT / "uv.lock"]
    manifest = {
        "run_at": datetime.now(timezone.utc).isoformat(), "version": "1.4.0",
        "baseline_commit": contract["baseline_commit"], "pytest": totals, "ruff": "passed",
        "lockfile": "offline_check_passed", "wheel": read("artifacts/v14/wheel-smoke.json"),
        "manual": read("artifacts/v14/manual-pdf.json"),
        "source_file_sha256": {str(p.relative_to(ROOT)): sha(p) for p in sorted(source_paths)},
        "artifact_sha256": {str(p.relative_to(ROOT)): sha(p) for p in sorted(OUT.rglob("*"))
                            if p.is_file() and p.name != "final-manifest.json"},
        "scope_limits": ["Synthetic health and training inputs; no private full ZIP benchmark",
                         "Real public-source acquisition and truthful AI-assisted reviews; no independent expert approval",
                         "Paid textbook bodies, four method/calibration rule topics and parts of explanatory scope/free-question semantics remain partial; record rules are not scientific evidence",
                         ("Catalog media cache complete for this snapshot; remote whole-file checksums and universal codec support are not established"
                          if media_complete else "Catalog media cache partial; ready objects only in offline package")],
    }
    write(OUT / "final-manifest.json", manifest)
    print(json.dumps({"pytest": totals, "metrics": len(metrics), "acceptance_cases": len(cases)}))


if __name__ == "__main__":
    main()
