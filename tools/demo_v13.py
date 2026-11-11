"""Reproducible synthetic v1.3 lifecycle through the real local services.

Only the clock and UUID generator are fixed. No database rows, metric values or
literature approvals are fabricated behind the service interfaces. The database
lives in a temporary directory; exported records are explicitly synthetic.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from healthzip.analytics.v13 import analyze, snapshot
from healthzip.db.repository import Repository
from healthzip.science import evaluate
from healthzip.science.semantics import flatten_record, load_change
from healthzip.training.semantics import timestamp
from healthzip.training.service import TrainingService

CUTOFF = "2026-11-11T12:00:00+00:00"


class DemoDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls.fromisoformat(CUTOFF)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


def build_demo(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    clock = {"now": "2026-11-09T07:00:00+00:00"}
    sequence = count()

    def demo_time(value=None):
        return timestamp(value if value is not None else clock["now"])

    def phase(value):
        clock["now"] = value

    with TemporaryDirectory(prefix="healthzip-synthetic-demo-") as temporary, \
            patch("healthzip.training.service.timestamp", demo_time), \
            patch("healthzip.training.service.uuid4", lambda: uuid5(NAMESPACE_URL, f"demo-v13:{next(sequence)}")), \
            patch("healthzip.science.contracts.datetime", DemoDatetime):
        repo = Repository(Path(temporary) / "synthetic.sqlite3")
        service = TrainingService(repo)
        empty_sessions = service.list_sessions()
        exercise = service.search_exercises("上斜史密斯")[0]
        machine = service.create_equipment("合成演示：上斜史密斯", "smith", configuration={
            "available_loads": [30, 32.5, 35], "load_step": 2.5,
            "step_basis": "plates_per_side_kg", "step_source": "synthetic_user_confirmation",
        }, event_id="demo-equipment")
        condition = {"equipment_instance_id": machine["id"], "load_basis": "plates_per_side_kg",
                     "load_basis_confirmed": True, "side": "both", "repetition_semantics": "simultaneous",
                     "rom_protocol": "synthetic_user_declared_full", "settings": {"bench_angle_degrees": 30},
                     "settings_confirmed": True, "symmetric_loading": True,
                     "effective_bar_mass_kg": None, "reference_protocol": {
                         "protocol_id": "synthetic_first_work", "version": "1", "reference_policy_id": "first_work_set",
                         "effort_protocol": "planned_reps_rir2", "tempo": "controlled", "rest_protocol": "user_declared_180s"}}
        template = service.create_template("合成演示：胸部计划", [{"exercise_id": exercise["exercise_id"],
            "condition": condition, "targets": {"sets": [{"set_type": "work", "reps_min": 8,
                "reps_max": 10, "rir": 2, "load_value": "30", "load_unit": "kg"}]}}], event_id="demo-template")
        phase("2026-11-09T08:00:00+00:00")
        first = service.start_session("合成演示：第一次胸部", template_id=template["id"], event_id="demo-session-1")
        first_draft = first["sets"][0]
        assert first["completed_sets"] == 0
        phase("2026-11-09T08:01:00+00:00")
        nominated = service.edit_set(first_draft["set_uuid"], {"reference_set": True},
                                     base_revision=first_draft["revision"], event_id="demo-reference-1")
        phase("2026-11-09T08:03:00+00:00")
        actual_first = service.edit_set(nominated["set_uuid"], {
            "completion_state": "completed", "load_value": "30", "load_unit": "kg", "reps": 10,
            "rir": 2, "stop_reason": "plan_target", "quality_status": "acceptable",
            "started_at": "2026-11-09T08:02:00+00:00", "ended_at": clock["now"],
        }, base_revision=nominated["revision"], event_id="demo-complete-1")
        phase("2026-11-09T08:45:00+00:00")
        service.end_session(first["id"], session_rpe=6, rpe_scale="cr10", duration_seconds=2700,
            duration_protocol="user_elapsed_including_rest", feedback={"note": "合成记录：达到计划次数后停止，未测试力竭。"},
            event_id="demo-end-1")

        phase("2026-11-11T08:00:00+00:00")
        second = service.start_session("合成演示：第二次胸部", template_id=template["id"], event_id="demo-session-2")
        instance = second["exercises"][0]
        carryover = service.last_values(instance["id"])
        second_draft = second["sets"][0]
        copied = service.edit_set(second_draft["set_uuid"], carryover["suggested_actual"],
                                  base_revision=second_draft["revision"], event_id="demo-copy-last")
        assert copied["completion_state"] == "draft"
        assert service.get_session(second["id"])["completed_sets"] == 0
        phase("2026-11-11T08:01:00+00:00")
        records, inherited = snapshot(repo, clock["now"])
        historical = [r for r in records if r.get("record_kind") == "strength_set"
                      and r.get("session_id") == first["id"]]
        candidate_metric = evaluate("STR-25", historical, cutoff_time=clock["now"],
            window_start="2026-11-01T00:00:00+00:00", window_end=clock["now"], context={
                **inherited, "progression_plan": {"rep_upper": 10, "target_rir_min": 2,
                    "target_rir_max": 2, "available_loads": [30, 32.5, 35], "next_target_reps": 8},
                "reviewed_principles": [],
            })
        assert candidate_metric["value"]["next_load"] is None
        assert candidate_metric["value"]["equipment_step_feasibility"]["next_recorded_setting"] == 32.5
        assert "reviewed_applicable_progression_principle_required" in candidate_metric["reason_codes"]
        candidate = {"candidate_id": "synthetic-demo-candidate", "target_session": second["session_uuid"],
                     "action_kind": "collect_or_confirm_evidence", "proposed_change": {"load": None,
                         "load_unit": "kg", "load_basis": "plates_per_side_kg"},
                     "target_range": {}, "reason_evidence_ids": ["STR-25"],
                     "eligibility": candidate_metric["reason_codes"], "uncertainty": candidate_metric["uncertainty"],
                     "verification_protocol": "记录预指定工作组的重量、次数、RIR、质量与停止原因；不适时退出。",
                     "followup_window": "第二次同条件训练", "rule_version": candidate_metric["algorithm_version"],
                     "user_choice": None}
        frozen = {"source_record_ids": [actual_first["set_uuid"]], "metric_result": candidate_metric,
                  "condition": instance["condition"], "plan_snapshot": instance["planned"],
                  "theory_authority": {"principles": [], "reason": "no_reviewed_numerical_authority_in_demo"}}
        service.record_recommendation(candidate, frozen, cutoff_time=clock["now"], theory_version="none_reviewed_for_numerical_action")

        phase("2026-11-11T08:02:00+00:00")
        nominated = service.edit_set(copied["set_uuid"], {"reference_set": True},
                                     base_revision=copied["revision"], event_id="demo-reference-2")
        phase("2026-11-11T08:04:00+00:00")
        actual_second = service.edit_set(nominated["set_uuid"], {
            "completion_state": "completed", "load_value": "32.5", "load_unit": "kg", "reps": 8,
            "rir": 2, "quality_status": "acceptable", "stop_reason": "plan_target",
            "started_at": "2026-11-11T08:03:00+00:00", "ended_at": clock["now"],
        }, base_revision=nominated["revision"], event_id="demo-complete-2")
        phase("2026-11-11T08:45:00+00:00")
        service.end_session(second["id"], session_rpe=7, rpe_scale="cr10", duration_seconds=2700,
            duration_protocol="user_elapsed_including_rest", feedback={"note": "合成用户自主尝试32.5×8；不是系统已批准加重。"},
            event_id="demo-end-2")
        service.recommendation_feedback(candidate["candidate_id"], user_choice="modified", execution_state="executed",
            actual_record_ids=[actual_second["set_uuid"]], outcome={"user_note": "自主尝试；缺少数值理论授权，不能算作建议效果验证。"},
            event_id="demo-candidate-feedback")
        phase(CUTOFF)
        weekly = analyze(repo, cutoff_time=CUTOFF, period="week")
        assert len(weekly["metrics"]) == 77
        assert weekly["metrics"]["STR-01"]["value"]["completed_work_parent_sets"] == 2
        assert weekly["metrics"]["STR-09"]["value"]["planned"] == 2
        assert [item["AU"] for item in weekly["metrics"]["LOAD-SRPE-AU"]["value"]] == [270, 315]
        assert weekly["metrics"]["STR-27"]["value"][0]["short_term_success"] is None
        change = load_change(flatten_record(actual_first), flatten_record(actual_second))
        assert change["plate_total_change_kg"] == 5
        assert change["total_load_change_percent"] is None
        records, context = snapshot(repo, CUTOFF)
        context["timezone"] = "Asia/Shanghai"
        context["plan_snapshot"] = {"sets": [s for p in context["session_plans"] for s in p["sets"]]}
        local_snapshot = {"records": records, "cutoff_time": CUTOFF,
                          "window_start": weekly["window_start"], "window_end": weekly["window_end"], "context": context}
        result = {"data_kind": "synthetic", "scientific_validation": "not_established",
                  "clock_and_ids": "fixed only for this synthetic demonstration", "started_with_empty_database": not empty_sessions,
                  "template": template, "initial_draft": first_draft, "first_actual": actual_first,
                  "last_values": carryover, "copied_draft": copied, "candidate_metric": candidate_metric,
                  "frozen_candidate": service.list_recommendations()[0], "second_actual": actual_second,
                  "load_change": change, "sessions": service.list_sessions(), "weekly_report": weekly}
        for name, payload in (("demo.json", result), ("metric_snapshot.json", local_snapshot)):
            (directory / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        repo.close()
    markdown = f"""# HealthZIP v1.3 合成端到端演示

所有数据均为合成数据。固定时钟和 UUID 仅保证演示可复现；实际调用 Repository、TrainingService、analytics.v13 和全部 77 项指标执行器。

复现：`PYTHONPATH=src python tools/demo_v13.py --output artifacts/demo`

1. 从空临时数据库建立胸部模板，选择上斜史密斯，明确每侧片重、双侧对称、30°靠背、ROM及同次双侧重复。有效杆重保持未知。
2. 模板开始后为草稿，完成组数是 0；先指定参考组，再记录每侧 30 kg × 10 次、RIR 2、动作质量可接受、达到计划后停止。
3. 下次带入上次重量和次数后仍为草稿，完成组数仍是 0；RIR 和停止原因重新填写。
4. STR-25 核对物理档位 32.5 kg，但 `next_load=null`，原因是缺少已审核且适用的数值进阶理论。冻结原始依据、计划、规则版本和缺项。
5. 合成用户自主选择每侧 32.5 kg × 8 次、RIR 2；双侧片重变化为 **+5 kg**。杆重未知，因此总负荷及总负荷变化百分比未知；该记录不证明力量下降或建议有效。
6. 两场均记录 45 分钟和整场 CR10 RPE（6、7），得到 270、315 AU，并保存选择、执行和用户反馈。
7. 生成本地日历周报告：窗口 `{weekly['window_start']}` 至 `{weekly['window_end']}`，截止 `{CUTOFF}`。已完成工作组 2，冻结计划组 2；当前周未结束，不能与完整上周直接比较总量。

`demo.json` 包含逐步实际返回值、冻结候选和完整周指标；`metric_snapshot.json` 可作为 `python -m healthzip.science evaluate` 的输入。临时数据库运行后删除。没有睡眠、心率和设备能量输入时，相关指标保持缺失，不补零。

此演示验证软件数据流和失败路径；没有声明已完成人体校准、数值理论专业审核或个人干预效果验证。
"""
    (directory / "README.md").write_text(markdown, encoding="utf-8")
    return {"output": str(directory), "metrics": 77, "data_kind": "synthetic", "checks": "passed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/demo"))
    args = parser.parse_args()
    print(json.dumps(build_demo(args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
