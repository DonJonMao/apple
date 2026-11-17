#!/usr/bin/env python3
"""Small actual-public-corpus integration over isolated synthetic health records.

Pass a disposable SQLite backup of the public knowledge store: retrieval audits
are written only to that copy. No source, claim, rule or release is added here.
This is a functional check, not a scientific Gold or retrieval-quality estimate.
"""
import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService
from healthzip.workflows import WorkflowRequest, load_analysis, run_workflow, save_context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-copy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = []
    for scale, timing, population in (
        ("Foster_modified_CR10", "after", "adult_athletes"),
        ("cr10", "after", "adult_athletes"),
        ("Foster_modified_CR10", "unknown", "adult_athletes"),
        ("Foster_modified_CR10", "after", "unknown"),
    ):
        with tempfile.TemporaryDirectory(prefix="healthzip-analysis-check-") as temporary:
            repo = Repository(Path(temporary) / "synthetic.sqlite3")
            try:
                svc = TrainingService(repo)
                end = datetime.now(timezone.utc) - timedelta(hours=1)
                session = svc.start_session("Synthetic integration only", started_at=(end-timedelta(minutes=50)).isoformat())
                svc.end_session(session["id"], ended_at=end.isoformat(), session_rpe=6, rpe_scale=scale,
                    rpe_collected_at=(end+timedelta(minutes=15)).isoformat() if timing == "after" else None,
                    duration_seconds=3000, duration_protocol="user_elapsed_including_rest")
                context_id = save_context(repo, {"population": population})
                run = run_workflow(repo, WorkflowRequest("W2", context_id=context_id), knowledge_root=args.knowledge_copy)
                query = next((q for q in run["knowledge"]["queries"] if q["metric_id"] == "LOAD-SRPE-AU"), {})
                metric = load_analysis(repo, run["run_id"])["metrics"]["LOAD-SRPE-AU"]
                cases.append({"scale": scale, "collection": timing, "population": population,
                    "release_id": run["knowledge"]["release_id"], "knowledge_status": run["knowledge"]["status"],
                    "query_status": query.get("status"), "permissions": query.get("permissions"),
                    "claim_versions": [{"claim_id": c["claim_id"], "version": c["claim_version"]} for c in query.get("claims", [])],
                    "spans": query.get("spans", []), "limitations": query.get("limitations", []),
                    "query_policy": run["knowledge"].get("query_policy"), "audit": query.get("audit"),
                    "observed_AU": metric["value"][0]["AU"], "fact_preserved": any(f["metric_id"] == "LOAD-SRPE-AU" for f in run["facts"])})
            finally:
                repo.close()
    output = {"identity": "functional_integration_not_scientific_validation", "created_at": datetime.now(timezone.utc).isoformat(),
        "private_inputs": "isolated_synthetic_repository_only", "knowledge": "existing_actual_release_disposable_copy",
        "production_permissions_changed": False, "cases": cases}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"cases": len(cases), "source_explanation": [bool((c["permissions"] or {}).get("source_explanation")) for c in cases],
                      "facts_preserved": all(c["fact_preserved"] for c in cases), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
