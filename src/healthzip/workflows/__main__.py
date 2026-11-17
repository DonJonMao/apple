"""Local workflow CLI. Accepts IDs/settings, never client-computed metrics."""
import argparse
import json

from healthzip.db.repository import Repository

from . import WorkflowRequest, resume_workflow, run_workflow


def main():
    parser = argparse.ArgumentParser(description="HealthZIP 五条本地确定性分析流程")
    parser.add_argument("--db", required=True)
    parser.add_argument("--workflow", choices=["W1", "W2", "W3", "W4", "W5"])
    parser.add_argument("--resume")
    parser.add_argument("--cutoff")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--baseline-days", type=int, default=28)
    parser.add_argument("--period", choices=["week", "month"])
    parser.add_argument("--context-id")
    parser.add_argument("--session-id", type=int)
    parser.add_argument("--exercise-instance")
    parser.add_argument("--set-uuid")
    parser.add_argument("--task-id")
    parser.add_argument("--series-id")
    parser.add_argument("--outcome", choices=["STR-11", "BODY-MASS-DAILY", "STATE-RHR", "STATE-SDNN"])
    parser.add_argument("--candidate-id")
    parser.add_argument("--retrospective", action="store_true")
    parser.add_argument("--release-id")
    args = parser.parse_args()
    if bool(args.resume) == bool(args.workflow):
        parser.error("指定 --workflow 或 --resume 中的一项")
    repo = Repository(args.db)
    try:
        if args.resume:
            result = resume_workflow(repo, args.resume, cutoff_time=args.cutoff, context_id=args.context_id)
        else:
            result = run_workflow(repo, WorkflowRequest(args.workflow, cutoff_time=args.cutoff, timezone=args.timezone,
                window_days=args.days, baseline_days=args.baseline_days, period=args.period, context_id=args.context_id,
                session_id=args.session_id, session_exercise_id=args.exercise_instance, selected_set_uuid=args.set_uuid,
                task_id=args.task_id, outcome_series_id=args.series_id, result_metric_id=args.outcome,
                candidate_id=args.candidate_id, mode="retrospective" if args.retrospective else "prospective",
                release_id=args.release_id))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
