"""Automatic current training presentation; all calculations stay in services."""
import sqlite3

import streamlit as st

from healthzip.training.current import (
    current_advice,
    equipment_loads,
    objective_comparison,
    save_equipment_loads,
)
from healthzip.workflows import load_run
from healthzip.workflows.presentation import metric_lines

LABELS = {"double_progression": "按原计划上沿核对进阶", "heavier_lower_reps": "更难档位与较低次数的可选方案",
          "repetition_progression": "同负荷的次数进阶选项"}


def render_current_training(repo, instance, *, source_report_id=None):
    st.markdown("#### 本次训练建议与实际记录")
    settings = equipment_loads(repo, instance)
    with st.expander("本动作的器械档位（保存后复用）"):
        text = st.text_input("实际可用档位（逗号分隔，与记录口径一致）",
            value=",".join(str(v) for v in settings["available_loads"]), key="current_loads_" + instance["id"])
        st.caption("档位是器械事实；数值建议还需要适用的行动规则和个人记录。")
        if st.button("保存本动作档位", key="current_loads_save_" + instance["id"]):
            try:
                save_equipment_loads(repo, instance["id"], [x.strip() for x in text.split(",") if x.strip()])
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    try:
        result = current_advice(repo, instance["id"],
            context_id=st.session_state.get("analysis_contexts", {}).get(str(repo.path.resolve())),
            window_days=int(st.session_state.get("analysis_window_days", 30)),
            timezone_name=st.session_state.get("analysis_timezone", "Asia/Shanghai"), source_report_id=source_report_id)
        st.caption(f"本次建议的数据截止：{result['created_at']}。目标与实际记录分别保存。")
        review = load_run(repo, result["review_run_id"])
        body = result.get("body") or {}
        if restriction := review["supplements"].get("context_restriction"):
            st.warning(restriction["limitation"])
        with st.expander("当前身体背景：睡眠、心率、SDNN、体重与自评", expanded=True):
            for mid in ("STATE-SLEEP-24H", "STATE-RHR", "STATE-SDNN", "BODY-MASS-DAILY", "STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN"):
                metric = body.get("metrics", {}).get(mid)
                if metric:
                    st.markdown("\n".join(metric_lines(metric)))
        available = 0
        for index, group in enumerate(result["groups"], 1):
            for option in group["options"]:
                if option["load"] is None:
                    continue
                available += 1
                st.write(f"待开始目标组 {index}：{LABELS[option['strategy']]}；"
                         f"{option['load']} {option['load_unit']} × {option['reps']} 次；"
                         f"目标 RIR {option['rir'] if option['rir'] is not None else '未指定'}。")
                st.caption(option["basis"]["weight_origin"] + "；" + option["basis"]["repetitions_origin"] + "；" + option["basis"]["rir_origin"])
                with st.expander(f"目标组 {index} · {LABELS[option['strategy']]}的依据"):
                    st.write("个人参考记录", option["basis"]["reference_set_id"])
                    for rule in option["basis"]["rules"]:
                        st.write("策略依据", rule.get("application_logic") or rule.get("permitted_actions"))
                        st.write("来源与版本", rule.get("rule_id", rule.get("theory_id")), rule["version"], rule["evidence_spans"])
                    st.write(option["limitations"])
        if not available:
            st.info("当前尚未形成获许可的数值选项。你可以继续原计划或自由记录实际训练；下方列出本次具体缺项。")
        for message in result["unknown"]:
            st.info(message)
        with st.expander("近期表现、长期复核与具体缺项"):
            from healthzip.workflows.reports import markdown
            st.markdown("\n".join(markdown([review], repo=repo)))
            for group in result["groups"]:
                for option in group["options"]:
                    if option["load"] is None:
                        st.write(LABELS[option["strategy"]], option["metric"]["reason_codes"])
                        st.write("规则适用缺项", option["excluded_rules"])
        with st.expander("建议版本与原计划详情"):
            st.json(result)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        st.warning(f"本次建议待更新：{exc}。仍可保存实际训练；再次打开本次训练时会重新核对。")
    render_objective_comparison(repo, instance["id"])


def render_objective_comparison(repo, instance_id):
    try:
        comparison = objective_comparison(repo, instance_id)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        st.warning(f"客观对照待更新：{exc}。实际训练记录不受影响。")
        return
    labels = {"record_removed": "记录已删除，保留历史版本", "no_actual_record": "尚无实际记录",
              "linked_objectively": "已按本次任务和组关联", "ambiguous": "对应建议存在歧义",
              "no_prior_applicable_advice": "没有可唯一关联的练前建议"}
    st.caption("实际记录自动对照；这不表示采纳、拒绝、执行或效果。")
    for index, row in enumerate(comparison["rows"], 1):
        actual = row["actual"]
        st.write(f"组 {index}：{labels[row['status']]}")
        if row["status"] not in {"no_actual_record", "record_removed"}:
            st.write(f"实际 {actual['load_value']} {actual['load_unit']} × {actual['reps']} 次；"
                     f"RIR {actual['rir'] if actual['rir'] is not None else '未记录'}；时间 {actual['ended_at'] or actual['started_at']}。")
            if row["frozen_group"]:
                for option in row["frozen_group"]["options"]:
                    if option["load"] is not None:
                        st.caption(f"此前可选方案：{option['load']} {option['load_unit']} × {option['reps']} 次；"
                                   "实际不同只表示记录不同，不推断你的选择或训练效果。")
            for mid, metric in row.get("reference_comparison", {}).items():
                value = metric.get("value") or {}
                if mid == "STR-12" and value.get("delta_reps") is not None:
                    st.write(f"与建议生成时的同条件、同负荷参考相比，记录次数变化 {value['delta_reps']:+g} 次；"
                             f"参考 RIR {value.get('rir_before')}，本次 RIR {value.get('rir_after')}。")
                elif mid == "STR-14" and value.get("delta_rir") is not None:
                    st.write(f"同负荷、同次数的记录 RIR 变化 {value['delta_rir']:+g}；自报变化不等于确定的能力提升。")
    with st.expander("客观对照的版本与身份详情"):
        st.json(comparison)
