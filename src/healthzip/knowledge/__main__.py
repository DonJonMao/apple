"""Run with python -m healthzip.knowledge; public acquisition never sends health data."""

import argparse
import json
from pathlib import Path

from .workbench import KnowledgeWorkbench


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local versioned public evidence libraries")
    parser.add_argument("--root", default=".local/knowledge")
    parser.add_argument("--spec-dir")
    parser.add_argument("--output")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    sub.add_parser("status")
    sub.add_parser("verify")
    p = sub.add_parser("acquire")
    p.add_argument("--source", action="append")
    p.add_argument("--fulltext", action="store_true")
    p.add_argument("--contact", default="")
    p.add_argument("--timeout", type=float, default=18)
    p.add_argument("--no-smoke", action="store_true")
    p = sub.add_parser("query")
    p.add_argument("question")
    p.add_argument("--route")
    p.add_argument("--release")
    p.add_argument("--context", help="JSON file with applicability context, never ingested into SourceLibrary")
    p = sub.add_parser("evaluate")
    p.add_argument("cases")
    p.add_argument("--split", default="visible_development")
    p.add_argument("--annotations")
    p.add_argument("--with-synthetic-metrics", action="store_true", help="Use explicit development fixtures through the deterministic metric executor")
    p = sub.add_parser("review")
    p.add_argument("review_file", help="JSON object with theory_id, version and explicit claim-level review")
    p = sub.add_parser("revise-theory")
    p.add_argument("revision_file", help="JSON: theory_id,from_version,new_version,reviewer,rationale,optional card_patch")
    p = sub.add_parser("import-document")
    p.add_argument("declaration", help="JSON: source_id,path,license_id,rights_evidence_url,authorized_by,identity_review")
    p = sub.add_parser("release")
    p.add_argument("release_id")
    p = sub.add_parser("source-state")
    p.add_argument("source_id")
    p.add_argument("state", choices=["withdrawn", "corrected_pending_review", "acquired"])
    p.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    w = KnowledgeWorkbench(args.root, args.spec_dir)
    try:
        if args.command == "seed":
            result = w.seed()
        elif args.command == "status":
            result = w.status()
        elif args.command == "verify":
            result = w.verify()
        elif args.command == "acquire":
            w.seed()
            result = w.acquire(args.source, args.fulltext, args.contact, args.timeout, not args.no_smoke)
        elif args.command == "query":
            context = json.loads(Path(args.context).read_text()) if args.context else {}
            result = w.query(args.question, args.route, context, release_id=args.release)
        elif args.command == "evaluate":
            provider = None
            if args.with_synthetic_metrics:
                from healthzip.science.rag_fixtures import metric_provider
                provider = metric_provider
            result = w.evaluate(args.cases, args.split, annotations_path=args.annotations, metric_provider=provider)
        elif args.command == "review":
            result = w.review_theory(**json.loads(Path(args.review_file).read_text()))
        elif args.command == "revise-theory":
            result = w.revise_theory(**json.loads(Path(args.revision_file).read_text()))
        elif args.command == "import-document":
            result = w.import_document(**json.loads(Path(args.declaration).read_text()))
        elif args.command == "release":
            result = w.release(args.release_id)
        else:
            result = w.lib.update_state(args.source_id, args.state, args.reason)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            target = Path(args.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
        return 0
    finally:
        w.close()


if __name__ == "__main__":
    raise SystemExit(main())
