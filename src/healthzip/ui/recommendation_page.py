"""Freeze a candidate and follow its actual execution, including abstentions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import streamlit as st

from healthzip.analytics.v13 import snapshot
from healthzip.science import evaluate


def render_candidates(repo, svc, session, instance):
    key = instance["id"]
    with st.expander("本次候选与后续复核"):
        st.caption("可选改变来自明确计划和可比记录；未满足依据时保留缺项。采纳不会自动修改模板。")
        targets = instance.get("planned", {}).get("sets", [])
        target = targets[0] if targets else {}
        loads = st.text_input("本台器械实际可用重量 / 刻度（逗号分隔）", key="loads_" + key)
        if st.button("核对候选依据并保存", key="candidate_" + key):
            try:
                available = [float(x.strip()) for x in loads.split(",") if x.strip()]
                now = datetime.now(timezone.utc)
                records, context = snapshot(repo, now.isoformat())
                records = [r for r in records if r.get("record_kind") == "strength_set" and r.get("condition_key") == instance.get("condition_key") and r.get("session_id") != session["id"] and r.get("completion_state") == "completed" and r.get("ended_at")]
                records.sort(key=lambda r: datetime.fromisoformat(r["ended_at"].replace("Z", "+00:00")))
                plan = {"rep_upper": target.get("reps_max"), "target_rir_min": target.get("rir"),
                        "target_rir_max": target.get("rir"), "available_loads": available,
                        "next_target_reps": target.get("reps_min")}
                if any(plan[k] is None for k in ("rep_upper", "target_rir_min", "target_rir_max")):
                    plan = None
                # These are user goals and physical choices, not physiological
                # constants. Store their distinct identities before freezing.
                from healthzip.science.registry import ParameterRegistry
                if repo.conn.in_transaction:
                    raise ValueError("请先保存当前编辑，再核对候选依据。")
                registry = ParameterRegistry(str(repo.path))
                parameters = []
                try:
                    for kind, value, unit in (("user_plan", plan, "declared_task"),
                                              ("equipment_constraint", available, "recorded_load_unit")):
                        digest = hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()
                        parameters.append(registry.register({"parameter_id": f"{kind}:{key}", "version": digest,
                            "kind": kind, "definition": "用户计划目标" if kind == "user_plan" else "用户确认本台器械可用档位",
                            "value_or_distribution": value, "unit": unit,
                            "provenance": {"basis": "user_declared", "source_ids": [], "source_location": "training_candidate_form"},
                            "scope": {"session_exercise_id": key, "condition_key": instance.get("condition_key")},
                            "validation_status": "user_declared"}))
                finally:
                    registry.close()
                from healthzip.knowledge import KnowledgeWorkbench
                knowledge = KnowledgeWorkbench(".local/knowledge")
                try:
                    authority = knowledge.reviewed_principles("progression", instance["condition"])
                finally:
                    knowledge.close()
                metric = evaluate("STR-25", records, cutoff_time=now.isoformat(),
                                  window_start=(now-timedelta(days=365)).isoformat(), window_end=now.isoformat(),
                                  context={**context, "progression_plan": plan, "reviewed_principles": authority["principles"]})
                metric["parameter_set_id"] = parameters[0]["parameter_id"] + "@" + parameters[0]["version"]
                metric["parameters_used"] = [{"parameter_id": p["parameter_id"], "version": p["version"], "kind": p["kind"]} for p in parameters]
                value = metric.get("value") or {}
                candidate = {"candidate_id": str(uuid4()), "target_session": session["session_uuid"],
                             "action_kind": value.get("candidate") or "collect_or_confirm_evidence",
                             "proposed_change": {"load": value.get("next_load"),
                                                 "load_unit": records[-1].get("load_unit") if records else None,
                                                 "load_basis": instance["condition"].get("load_basis")},
                             "target_range": {"reps_min": target.get("reps_min"), "reps_max": target.get("reps_max"),
                                              "rir_min": target.get("rir"), "rir_max": target.get("rir")},
                             "reason_evidence_ids": ["STR-25"], "eligibility": metric["reason_codes"],
                             "uncertainty": metric["uncertainty"],
                             "verification_protocol": "记录首个预指定工作组的实际完成、RIR、动作质量与停止原因；不合适时可退回或结束。",
                             "followup_window": "下一次同条件训练", "rule_version": metric["algorithm_version"], "user_choice": None}
                frozen = {"source_record_ids": [r.get("set_uuid") or r["raw_id"] for r in records],
                          "metric_result": metric, "plan_snapshot": instance.get("planned"), "condition": instance["condition"], "theory_authority": authority,
                          "session_exercise_id": key, "parameter_manifest": parameters}
                svc.record_recommendation(candidate, frozen, cutoff_time=now.isoformat(), theory_version=str(authority.get("source_release") or authority.get("review_snapshot_sha256") or "none_reviewed_for_numerical_action"))
                st.success("已保存当时依据与缺项，后续不会改写该快照。")
            except ValueError as exc:
                st.error(str(exc))
        def belongs(record):
            frozen = record["input_snapshot"]
            owner = frozen.get("session_exercise_id")
            if owner is None:
                condition_key = frozen.get("condition", {}).get("condition_key")
                owner = next((x["id"] for x in session["exercises"] if x.get("condition_key") == condition_key), None)
            return record.get("target_session") == session["session_uuid"] and owner == key
        candidates = [x for x in svc.list_recommendations() if belongs(x)]
        for record in candidates:
            candidate = record["candidate"]
            cid = candidate["candidate_id"]
            st.write("候选 / 缺项", candidate["action_kind"], candidate["eligibility"])
            st.caption(candidate["verification_protocol"])
            with st.expander("查看冻结依据", expanded=False):
                st.json(record["input_snapshot"])
            choice = st.selectbox("我的选择", ["deferred", "accepted", "declined", "modified"],
                                  format_func=lambda x: {"deferred": "暂缓", "accepted": "采纳", "declined": "不采纳", "modified": "修改后采用"}[x], key="choice_" + cid)
            execution = st.selectbox("实际执行", ["unknown", "executed", "partially_executed", "not_executed"],
                                     format_func=lambda x: {"unknown": "尚未记录", "executed": "已执行", "partially_executed": "部分执行", "not_executed": "未执行"}[x], key="execution_" + cid)
            reason = st.text_input("未执行原因 / 后续结果", key="reason_" + cid)
            if st.button("保存选择与执行反馈", key="feedback_" + cid):
                try:
                    svc.recommendation_feedback(cid, user_choice=choice, execution_state=execution,
                        nonexecution_reason=reason or "unknown", outcome={"user_note": reason},
                        actual_record_ids=[r["set_uuid"] for r in instance["sets"] if execution in {"executed", "partially_executed"} and r.get("completion_state") in {"completed", "aborted"} and not r.get("deleted_at")])
                    st.success("反馈已保存；采纳率不代表个人效果已经验证。")
                except ValueError as exc:
                    st.error(str(exc))
