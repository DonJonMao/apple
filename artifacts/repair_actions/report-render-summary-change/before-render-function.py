def render_report(repo, report, *, runs=None):
    """Readable questions and actions; complete frozen details stay addressable."""
    if "questions" not in report:
        return render_legacy_report(repo, report)
    from collections import Counter

    from healthzip.analytics.display_format import format_measurement
    from healthzip.analytics.health_context import joint_observations

    current = report["current"]
    questions = [q for q in report["questions"] if q["report_status"] == "available"]
    lines = ["# 身体与力量联合" + ("周报" if report["period"] == "week" else "月报"), "",
             f"本期 {current['window_start']} 至 {current['cutoff_time']}（观察截止，{current['timezone']}）。",
             "这是截至所列时点的周期观察；前后变化不自动归因于训练或行动。"]
    if current.get("retrospective"):
        lines += ["口径区别：本期专项快照采用当前修订回看历史，可能包含截止后才导入或更正的记录。下方实际问题与行动沿用问题页的截止时可见记录；晚到记录不计入该结果，两者不作为同一可见性口径比较。"]
    if (current.get("selection_context") or {}).get("sleep_selection"):
        lines += ["睡眠口径区别：人工声明的睡眠片段保留在专项冻结结果；下方实际问题按记录睡眠事件的结束日期归属，计算完整日代表值的期间中位数。片段时长与期间统计是不同观察，不能互相替换。"]
    lines += ["", "## 本期主要变化", ""]
    statements = joint_observations(current).get("statements", []) if current.get("joint_health_context") else []
    lines += ["- " + text for text in statements]
    if not statements:
        lines.append("本期尚无可对齐的完整日身体比较；以下保留已记录事实与局部结果。")
    goal = next((q.get("goal_context") for q in questions if q.get("goal_context")), None)
    lines += ["", "## 目标与实际训练", ""]
    lines.append("当前目标：" + goal["title"] if goal else "尚未记录独立目标尺度；可查看同条件实际表现，不自动判定目标达成。")
    tasks = current.get("strength_tasks", [])
    source_ids = {source for task in tasks for source in task.get("source_record_ids", [])}
    unknown = Counter(reason for task in tasks for reason in task.get("reason_codes", []))
    lines.append(f"本期保留 {len(tasks)} 个独立训练任务、{len(source_ids)} 个原始组引用。未知条件逐条保留，未合并成可比组。")
    if unknown:
        lines.append(f"有 {sum(unknown.values())} 项条件缺口待核对；具体缺项与原记录身份在冻结明细中逐条保留。")
    if runs is None:
        runs = [load_run(repo, key) for key in report.get("workflow_run_ids", [])]
    sessions = {str(ctx["session_id"]): ctx for run in runs
                for ctx in run.get("supplements", {}).get("training_session_contexts", [])}
    if sessions:
        # A date-level reading summary, not a collapse of scientific identities.
        dates = Counter(ctx["training_started_at"][:10] for ctx in sessions.values())
        lines.append("实际训练日期：" + "；".join(f"{day}（{n}场）" for day, n in sorted(dates.items())) + "。")
        if len(sessions) == 1:
            lines.append("训练开始：" + next(iter(sessions.values()))["training_started_at"] + "。")
    else:
        lines.append("本期尚无可建立时间对应的训练记录；已有身体事实仍可查看。")
    declaration = report.get("declaration", {})
    if declaration.get("status"):
        lines += [declaration["limitation"], f"原声明 `{declaration['context_id']}`；受限原因 `{declaration['reason']}`。"]
    for question in questions:
        lines += ["", "## " + question["title"], "", question["observation"]]
        comparison_context = question.get("report_comparison_context") or {}
        if comparison_context.get("difference_is_explicit"):
            lines.append("本题使用截止时已可见的记录；睡眠按记录事件结束日期归属，显示完整日的期间统计。与上列不同可见性或人工片段口径分别阅读。")
        for note in dict.fromkeys(question.get("limitations", [])):
            lines.append("- " + note)
        association = question.get("association") or {}
        for group in association.get("groups", []):
            identity = group.get("identity") or {}
            label = " / ".join(str(identity.get(k) or "未记录") for k in ("source", "device"))
            times = "–".join(identity.get("actual_local_time_range", []))
            dates = " 至 ".join(identity.get("date_range", []))
            lines.append(f"分组：{label}；实际采样 {times or '未记录'}；{dates}；配对 {identity.get('paired_dates', 0)} 天。")
            if group.get("status") == "estimated":
                interval = group.get("interval", [])
                estimate = f"观察性条件关联 {group['coefficient']:+.2f} ms/小时"
                if len(interval) == 2:
                    estimate += f"，区间 [{interval[0]:.2f}, {interval[1]:.2f}]"
                lines.append(estimate + "；不是因果效果，同批相邻变化不作为独立支持投票。")
            else:
                lines.append("本组不可估计：" + str(group.get("reason") or "现有记录尚不满足模型条件") + "。")
        ordinary = question.get("ordinary_training") or {}
        ordinary_groups = ordinary.get("series", [])
        unpaired = [group for group in ordinary_groups if not group.get("comparisons")]
        comparable = [group for group in ordinary_groups if group.get("comparisons")]
        for group in comparable:
            lines.append("- " + group["summary"])
        if unpaired:
            missing_conditions = Counter(reason for group in unpaired for reason in group.get("limitations", []))
            lines.append(f"另有 {len(unpaired)} 条独立轨迹（{sum(g['record_count'] for g in unpaired)} 条实际记录）尚无可唯一配对的比较。完整轨迹按动作查看。")
            labels = {"equipment_instance_unknown": "器械未记录", "settings_unknown": "器械设置未记录",
                      "rir_missing_effort_unknown": "RIR缺失，努力程度未知", "set_position_unknown": "组位未记录"}
            lines.append("；".join(f"{labels.get(reason, '相关测量条件尚待核对')}：{count}条轨迹" for reason, count in sorted(missing_conditions.items())))
        evidence = question.get("evidence", {})
        for item in evidence.get("items", [])[:2]:
            lines.append("适用说明：" + item["statement"])
            lines.extend("- " + limit for limit in item.get("limitations", []))
            for citation in item.get("citations", []):
                lines.append(f"来源：[{citation['title']}]({citation['url']}) · {citation.get('locator') or citation.get('section') or '定位见审计包'}")
        if evidence.get("restricted_items"):
            lines.append("部分主张或其必要前提存在分歧，仅限制相关解释和建议；独立资料仍保留。")
        if evidence.get("status") in {"not_configured", "service_failure", "no_applicable_sources"}:
            lines.append({"not_configured": "资料库尚未配置；以下为记录与测量核对入口。",
                          "service_failure": "本题资料服务未完成，事实与图表保留。",
                          "no_applicable_sources": "未取得本题适用的已审核说明；不据此补造原因或阈值。"}[evidence["status"]])
        # The selected numerical row retains its identity and standardized units.
        for row in question.get("rows", []):
            if row.get("type") == "metric" and row.get("value") is not None:
                value = format_measurement(row["value"], row.get("unit"), kind=row.get("metric"))
                delta = ("；较前期 " + format_measurement(row["difference"], row.get("unit"), kind=row.get("metric"), signed=True)
                         if row.get("difference") is not None else "；前期比较不足")
                lines.append(f"- {row.get('title', row.get('metric'))}：{value}{delta}；来源 {row.get('source') or '未注明'}。")
        lines.extend("下一步：" + step for step in question.get("steps", []))
    lines += ["", "## 上次行动观察", ""]
    actions = [a for q in questions for a in q.get("action_reviews", [])]
    if not actions:
        lines.append("本期没有截止时点可见的已选行动；不把未反馈推断为已执行。")
    for action in actions:
        lines.append("- " + str(action.get("summary") or action.get("action_text", "已选行动")))
        lines.append("执行：" + str(action.get("execution_label") or action.get("status", "未知")) + "。")
        if action.get("review_due"):
            lines.append("计划复评：" + action["review_due"] + "。")
    lines += ["", "## 下一步", ""]
    steps = list(dict.fromkeys(step for q in questions for step in q.get("steps", [])))
    lines += ["- " + step for step in steps[:3]] or ["继续记录实际值与测量条件，之后按相同口径复评。"]
    lines += ["", "## 冻结依据与明细", "",
              f"报告格式 `{report['version']}`；事实快照 `{report['analysis_run_id']}`。",
              "每题的完整观测、来源记录、日期、分组、行动定义与已选资料保存在冻结结果，可按问题浏览或另行下载完整审计包。",
              "相同内容对象由报告引用复用；再次生成是新的报告版本。后续修订、删除或撤销不会改写此历史正文。",
              "历史说明不代表当前有效建议；当前建议需重新核对资料与适用条件。"]
    return "\n".join(lines)
