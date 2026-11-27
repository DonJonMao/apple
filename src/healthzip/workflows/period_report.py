"""Frozen calendar reports composed from the existing metric/workflow services."""
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

try:
    import orjson
except ImportError:  # The command-line core still works without UI extras.
    orjson = None

from healthzip.analytics.cache import cached
from healthzip.analytics.v13 import persist
from healthzip.knowledge.revisions import knowledge_authority_clock
from healthzip.science.contracts import canonical_hash
from healthzip.training.current import knowledge_signature, objective_comparison
from healthzip.training.service import TrainingService

from .dependencies import input_version
from .evidence import report_evidence
from .presentation import display, metric_lines
from .report_inputs import period_facts, shared_report_inputs
from .reports import markdown, period_questions, review_analysis
from .storage import load_run, report_context

TRAINING = tuple(f"STR-{i:02}" for i in range(1, 16)) + ("STR-23", "STR-29")
BODY = ("STATE-SLEEP-MAIN", "STATE-SLEEP-24H", "STATE-SLEEP-COVERAGE", "STATE-SLEEP-STAGE", "STATE-SLEEP-TIMING",
        "STATE-RHR", "STATE-SDNN", "STATE-REFERENCE-MEDIAN", "STATE-REFERENCE-MAD", "STATE-DEVIATION",
        "STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN", "BODY-MASS-DAILY", "BODY-MASS-TREND",
        "LOAD-SRPE", "LOAD-DURATION", "LOAD-SRPE-AU", "ENERGY-BASAL", "ENERGY-ACTIVE", "ENERGY-DEVICE-TOTAL",
        "ENERGY-RECORD-COVERAGE", "ENERGY-IDENTIFIABILITY")


REPORT_VERSION = "joint-period-report-3.0.0"


def _fast_json_compatible(value):
    """Reject parser edge cases once per content build, preserving stdlib types."""
    pending = [value]
    seen = set()
    while pending:
        item = pending.pop()
        if isinstance(item, (dict, list, tuple)):
            if id(item) in seen:
                continue
            seen.add(id(item))
            pending.extend(item.values() if isinstance(item, dict) else item)
        elif isinstance(item, int) and not -(2**63) <= item <= 2**64-1:
            return False
        elif isinstance(item, float) and not math.isfinite(item):
            return False
    return True


def _decode_content(payload_json, fast_compatible):
    if fast_compatible and orjson is not None:
        try:
            return orjson.loads(payload_json)
        except orjson.JSONDecodeError:
            pass
    return json.loads(payload_json)


def _knowledge_identity(root):
    clock = knowledge_authority_clock(root)
    # The repository's trigger-backed revision covers source bytes, rules,
    # reviews, scope, notices and index releases. Historical payloads keep
    # their old content digests. Unmigrated stores still receive the full scan.
    if all((len(item) == 2 and item[1] == "missing") or
           (len(item) >= 3 and isinstance(item[2], tuple)) for item in clock[2:]):
        return canonical_hash([clock[0], clock[2:]]), "knowledge-authority-revision-1"
    return knowledge_signature(root), "legacy-content-digest"


class _UncachedReport(Exception):
    """A temporarily unavailable evidence stage cannot populate a hot cache."""

    def __init__(self, content):
        self.content = content


def create_report(repo, analysis, *, period, knowledge_root=".local/knowledge", progress=None, include_details=False):
    """Freeze a fresh version per explicit request; share its verified content."""
    if period not in {"week", "month"}:
        raise ValueError("calendar_week_or_month_required")
    TrainingService(repo)
    # Finish lazy schemas before taking the authority token. Missing stores
    # remain missing; an unavailable store is handled locally by retrieval.
    if all((Path(knowledge_root) / name).is_file() for name in ("sources.sqlite3", "theories.sqlite3")):
        from healthzip.knowledge import KnowledgeWorkbench
        from healthzip.knowledge.revisions import prepare_retrieval_revisions
        try:
            with closing(KnowledgeWorkbench(knowledge_root)) as workbench:
                prepare_retrieval_revisions(workbench)
        except (OSError, sqlite3.Error):
            pass
    context_id = (analysis.get("selection_context") or {}).get("workflow_context_id")
    before = input_version(repo, context_id)
    knowledge_before = _knowledge_identity(knowledge_root)
    from healthzip.ui.preferences import load_preferences
    cycle_enabled = bool(load_preferences(repo.path).get("cycle_enabled"))
    notify = progress or (lambda stage: None)
    fields = {field: analysis.get(field) for field in ("cutoff_time", "timezone", "selection_context", "source_filter",
              "retrospective", "algorithm_version")}
    key = {"version": REPORT_VERSION, "period": period, "selection": fields, "inputs": before,
           "knowledge": knowledge_before, "cycle_enabled": cycle_enabled}
    built = False

    def assemble():
        nonlocal built
        built = True
        with shared_report_inputs(repo), report_evidence(knowledge_root):
            payload, text, temporarily_unavailable = _assemble(
                repo, analysis, period, knowledge_root, before, knowledge_before, notify, cycle_enabled)
        from .report_objects import save_content
        payload_json = json.dumps(save_content(repo, payload), ensure_ascii=False)
        digest = hashlib.sha256(payload_json.encode())
        digest.update(b"\x00")
        digest.update(text.encode())
        result = payload_json, text, digest.hexdigest(), True  # The manifest only contains strings.
        if temporarily_unavailable:
            raise _UncachedReport(result)
        return result

    try:
        payload_json, text, content_signature, fast_compatible = cached(repo, "full-calendar-report", key, assemble,
                                    knowledge_root=knowledge_root)
    except _UncachedReport as unavailable:
        payload_json, text, content_signature, fast_compatible = unavailable.content
    if not built:
        notify("复用已核对的报告内容")
    # Only decode this application's validated, newly serialized report content.
    # Historical/imported JSON retains the standard parser in load_report.
    manifest = _decode_content(payload_json, fast_compatible)
    from .report_objects import read_content, read_reading
    payload = (read_content if include_details else read_reading)(repo, manifest)
    metadata = {"created_at": datetime.now(timezone.utc).isoformat(), "content_signature": content_signature,
                "report_id_signature_algorithm": "json-markdown-sha256-plus-created-at-1"}
    metadata["report_id"] = canonical_hash({"version": REPORT_VERSION, **metadata})
    # The verified content JSON is immutable. Appending only new freeze metadata
    # preserves every content field without serializing tens of MB a second time.
    saved_json = payload_json[:-1] + ", " + json.dumps(metadata, ensure_ascii=False)[1:]
    payload.update(metadata)
    notify("保存冻结版本")
    repo.conn.execute("BEGIN IMMEDIATE")
    try:
        if (input_version(repo, context_id) != before or _knowledge_identity(knowledge_root) != knowledge_before
                or bool(load_preferences(repo.path).get("cycle_enabled")) != cycle_enabled):
            raise ValueError("concurrent_joint_report_inputs_changed_retry_required")
        repo.conn.execute("INSERT INTO joint_period_report VALUES(?,?,?,?,?)", (payload["report_id"], "local",
            payload["created_at"], saved_json, text))
        repo.conn.commit()
    except BaseException:
        repo.conn.rollback()
        raise
    return {**payload, "markdown": text}


def _assemble(repo, analysis, period, knowledge_root, before, knowledge_before, notify, cycle_enabled):
    context_id = (analysis.get("selection_context") or {}).get("workflow_context_id")
    notify("读取本期事实")
    selected_context = dict(analysis.get("selection_context") or {})
    if "source_filter" in analysis:
        selected_context["source_filter"] = list(analysis["source_filter"] or ())
    current = period_facts(repo, cutoff_time=analysis["cutoff_time"], timezone_name=analysis["timezone"],
        period=period, context=selected_context, retrospective=analysis.get("retrospective", False))
    declaration = report_context(repo, context_id, current["cutoff_time"], "retrospective" if current["retrospective"] else "prospective")
    # Explicit current bounds: W4's two earlier complete periods are a separate
    # comparison below and cannot replace current training or body facts.
    notify("分析本期实际问题与行动")
    sources = selected_context.get("source_filter") or ()
    questions = period_questions(repo, current, period=period, knowledge_root=knowledge_root, source_filter=sources,
                                 cycle_enabled=cycle_enabled)
    notify("核对本期训练与知识依据")
    applicable = [q["id"] for q in questions if q["id"] in {"W2", "W3", "W5"} and q["report_status"] == "available"]
    runs = review_analysis(repo, current, include_background=True, knowledge_root=knowledge_root,
                          include_session_background=True, background_workflows=applicable)
    notify("比较前两个完整周期")
    historical = review_analysis(repo, current, period=period, knowledge_root=knowledge_root)
    # Keep the canonical period snapshot addressable by existing analysis
    # consumers even when no extra selection context required a persisted run.
    notify("整理可追溯报告")
    current_analysis_id = persist(repo, current)
    instances = {}
    for run in runs:
        for ctx in run["supplements"].get("training_session_contexts", []):
            for row in ctx["actual_records"]:
                instance = repo.conn.execute("SELECT session_exercise_id FROM strength_set WHERE set_uuid=?", (row["set_uuid"],)).fetchone()
                if instance and instance[0]:
                    instances.setdefault(instance[0], set()).add(row["set_uuid"])
    comparisons = []
    for identity, set_ids in sorted(instances.items()):
        comparison = objective_comparison(repo, identity, cutoff_time=current["cutoff_time"])
        comparisons.append({**comparison, "rows": [r for r in comparison["rows"] if r["set_uuid"] in set_ids],
            "scope": "only_actual_set_ids_visible_in_current_report_period"})
    payload = {"version": REPORT_VERSION, "period": period, "cutoff_time": current["cutoff_time"],
        "current": current, "questions": questions, "analysis_run_id": current_analysis_id, "declaration": declaration, "workflow_run_ids": [r["run_id"] for r in runs],
        "historical_run_ids": [r["run_id"] for r in historical], "objective_comparisons": comparisons,
        "period_identity": "current_partial_local_calendar_period", "input_revision": before,
        "knowledge_signature": knowledge_before[0], "knowledge_signature_algorithm": knowledge_before[1]}
    from healthzip.knowledge.claim_status import frozen_claim_references
    payload["current_claim_refs"] = frozen_claim_references(questions=questions, runs=(*runs, *historical))
    temporary_failures = any(run.get("knowledge", {}).get("status") == "service_failure"
                             for run in (*runs, *historical))
    temporary_failures |= any(q.get("evidence", {}).get("status") == "service_failure" for q in questions)
    return payload, render_report(repo, payload, runs=runs), temporary_failures


def load_report(repo, report_id, *, include_details=False):
    row = repo.conn.execute("SELECT payload_json,markdown FROM joint_period_report WHERE report_id=? AND user_id='local'", (report_id,)).fetchone()
    if row is None:
        raise ValueError("joint_report_not_found")
    saved = json.loads(row[0])
    if saved.get("storage_format") in {"frozen-report-references-1", "frozen-report-references-2"}:
        from .report_objects import read_content, read_reading
        content = (read_content if include_details else read_reading)(repo, saved)
        metadata = {key: value for key, value in saved.items() if key not in {"storage_format", "content_ref", "reading_ref", "content_decoder"}}
        return {**content, **metadata, "markdown": row[1]}
    return {**saved, "markdown": row[1]}


def render_legacy_report(repo, report):
    current = report["current"]
    lines = ["# 身体与力量联合" + ("周报" if report["period"] == "week" else "月报"), "",
        f"本期：{current['window_start']} 至 {current['window_end']}；统一数据截止 {current['cutoff_time']}（{current['timezone']}）。",
        "当前周期尚未结束，这是截至所列时点的部分报告。前期比较和历史背景分别列示，不以部分总量直接判断完整周期变化。", ""]
    declaration = report["declaration"]
    if declaration.get("status"):
        lines += [declaration["limitation"], f"原声明 `{declaration['context_id']}`；受限原因 `{declaration['reason']}`。", ""]
    from healthzip.analytics.health_context import joint_observations, sleep_comparison_metric
    if current.get("joint_health_context"):
        joint = joint_observations(current)
        lines += ["## 同一时间窗的具体变化", "", *joint["statements"], "",
                  "睡眠按观测事件结束的本地日期与当日心率对齐；日值不能证明采样一定在醒来后。未记录不是没有发生。", ""]
        for mid in ("STATE-RHR", "STATE-SDNN", "REPORT-STATE-SUMMARY"):
            metric = current["metrics"].get(mid, {})
            if mid == "REPORT-STATE-SUMMARY":
                metric = sleep_comparison_metric(metric)
            for stream in metric.get("comparison", {}).get("streams", []):
                from healthzip.analytics.health_context import coverage_label, period_label
                lines += ["；".join(f"{label} {period_label(stream[period])}，{coverage_label(stream[period])}"
                    for period, label in (("current", "本期"), ("previous", "前期"), ("reference", "个人参考"))), ""]
        lines += ["下一步：", *["- " + text for text in joint["next_steps"]], ""]
    lines += ["## 本阶段训练发生了什么", ""]
    for mid in TRAINING:
        lines += metric_lines(current["metrics"][mid])
    lines += ["## 本阶段身体背景", "", "周期整体记录与下文每次训练开始前的背景分别计算；缺失不补零，未记录不表示正常。", ""]
    for mid in BODY:
        lines += metric_lines(current["metrics"][mid])
    vo2 = current.get("observations", {}).get("OBS-VO2-REPORTED")
    if vo2 and vo2["value"] is not None:
        lines += metric_lines(vo2)
    lines += ["## 身体与训练的时间对应", "", "以下只描述共现与可比记录，不确认原因。每次背景的事件截止为该次训练开始；可见性模式单列。", ""]
    runs = [load_run(repo, identity) for identity in report["workflow_run_ids"]]
    joined = 0
    for run in runs:
        task = run.get("task_selection")
        if not task:
            continue
        lines += [f"### {task.get('exercise_name') or '本次动作'}", ""]
        if task.get("inventory_tasks"):
            lines += [f"本期保留 {len(task['inventory_tasks'])} 个独立实际任务；缺少预指定参考的任务不作专项趋势或停滞判定。",
                "专项指标按需计算；此处完整保留实际组、各自条件及来源身份，未请求的专项预测不标为已完成。", "",
                "<details><summary>独立任务与原始记录对应</summary>", "", "```json",
                json.dumps(task["inventory_tasks"], ensure_ascii=False), "```", "", "</details>", ""]
        long_review = run["supplements"].get("long_term_review", {})
        for item in long_review.get("tasks", []):
            lines += [f"比较状态：{item['status']}；比较次数 {item['n']}；实际使用 RIR 差值 {item['rir_used_n']} 次。"]
            for comparison in item["comparisons"]:
                lines += [f"- {comparison['observed_at']}：负荷差 {display(comparison['load_change'])} {comparison['load_unit']}；"
                          f"次数差 {display(comparison['repetitions_change'])}；RIR 差 {display(comparison['rir_change'])}；{comparison['identity']}。"]
        if long_review.get("start_long_term_review"):
            lines += ["所选周期内记录性未改善已启动长期复核；这不是生理或严格统计停滞结论。", ""]
        for ctx in run["supplements"].get("training_session_contexts", []):
            joined += 1
            lines += [f"训练开始 {ctx['training_started_at']}；身体背景可见性 {ctx['visibility']}；背景回看 {ctx['baseline_days']} 日（产品查看范围）。", ""]
            for actual in ctx["actual_records"]:
                lines += [f"- {actual['ended_at']}：{display(actual['load_value'])} {display(actual['load_unit'])} × {display(actual['reps'])} 次，RIR {display(actual['rir'])}。"]
            for mid in ("STATE-SLEEP-24H", "STATE-RHR", "STATE-SDNN", "BODY-MASS-DAILY", "STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN"):
                lines += metric_lines(ctx["metrics"][mid])
        for factor in run["hypotheses"]:
            lines += [f"- {factor['title']}：支持该记录性线索的观察 {len(factor['support'])} 项，"
                      f"削弱该线索的观察 {len(factor['counterevidence'])} 项，待核对项 {len(factor.get('unknown', []))} 项。计数不是原因的概率或评分。"]
            for change in factor.get("comparisons", []):
                lines += [f"  {change['first_observed_at']} 至 {change['later_observed_at']}："
                          f"记录变化 {display(change['difference'])} {display(change['unit'])}；同来源与协议对照。"]
            for claim in factor.get("source_claim_refs", []):
                lines += [f"  解释依据：{'；'.join(claim['statements'])}；主张 `{claim['claim_id']}@{claim['version']}`。用途仅限其已核对范围。"]
            lines += ["<details><summary>支持、削弱与未知的具体记录</summary>", "", "```json",
                      json.dumps({k: factor.get(k) for k in ("support", "counterevidence", "unknown", "source_claim_refs")}, ensure_ascii=False, indent=2),
                      "```", "", "</details>"]
    if not joined:
        lines += ["本期尚无可建立时间对应的训练记录；上方身体事实仍保留，不推断未训练或拒绝建议。", ""]
    lines += ["## 下一阶段", "", "继续记录实际重量、次数与已有 RIR；不需要填写建议采纳反馈。以下观察与确认项来自本期实际缺项及适用来源，数值训练选项在本次训练入口按当前计划和行动规则核对。", ""]
    for run in runs:
        from healthzip.science import definitions
        names = definitions()
        for factor in run["hypotheses"]:
            lines += [f"- {factor['title']}：{factor['next_step']}（依据：本期 {', '.join(names[mid]['title'] for mid in factor['metric_refs'])} 的记录与缺项；不表示该因素已被确认为原因。）"]
        for step in run["next_steps"]:
            lines += [f"- {names.get(step['metric_id'], {}).get('title', '来源观测')}：{step['text']}（入口：{step['location']}）"]
    lines += ["", "<details><summary>本期客观对照、原建议与实际记录</summary>", "", "```json",
              json.dumps(report["objective_comparisons"], ensure_ascii=False, indent=2), "```", "", "</details>", "",
              "<details><summary>本期完整证据链与方法边界</summary>", "", *markdown(runs, repo=repo), "</details>", "",
              "## 前两个完整周期的历史比较", "", "以下范围属于前期比较，不是本期事实或本期分母。", "",
              "<details><summary>展开历史范围、数值与证据</summary>", "",
              *markdown([load_run(repo, identity) for identity in report["historical_run_ids"]], repo=repo), "</details>"]
    return "\n".join(lines)


def render_report(repo, report, *, runs=None):
    """Readable questions and actions; complete frozen details stay addressable."""
    if "questions" not in report:
        return render_legacy_report(repo, report)
    from collections import Counter

    from healthzip.analytics.display_format import format_measurement, local_timestamp
    from healthzip.analytics.health_context import coverage_label
    from healthzip.knowledge.topics import answer_evidence
    from healthzip.workflows.report_objects import report_findings

    current = report["current"]
    questions = [q for q in report["questions"] if q["report_status"] == "available"]
    lines = ["# 身体与力量联合" + ("周报" if report["period"] == "week" else "月报"), "",
             f"本期 {local_timestamp(current['window_start'], current['timezone'])} 至 {local_timestamp(current['cutoff_time'], current['timezone'])}（结束时刻不含，{current['timezone']}）。",
             "这是截至所列时点的周期观察；前后变化不自动归因于训练或行动。"]
    if current.get("retrospective"):
        lines += ["口径区别：本期专项快照采用当前修订回看历史，可能包含截止后才导入或更正的记录。下方实际问题与行动沿用问题页的截止时可见记录；晚到记录不计入该结果，两者不作为同一可见性口径比较。"]
    if (current.get("selection_context") or {}).get("sleep_selection"):
        lines += ["睡眠口径区别：人工声明的睡眠片段保留在专项冻结结果；下方实际问题按记录睡眠事件的结束日期归属，计算完整日代表值的期间中位数。片段时长与期间统计是不同观察，不能互相替换。"]
    lines += ["", "## 本期主要变化", ""]
    statements = report_findings(report)
    lines += ["- " + text for text in statements]
    if not statements:
        lines.append("本期尚无可对齐的完整日身体比较；以下保留已记录事实与局部结果。")
    background = [q for q in report["questions"] if q.get("report_status") == "background_only"]
    additional_background = [q for q in background if q["observation"] not in statements]
    if additional_background:
        lines += ["", "## 已填写的状态与备注", ""]
        for question in additional_background:
            lines.append(question["observation"])
            lines.extend("下一步：" + step for step in question["steps"])
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
        dates = Counter(local_timestamp(ctx["training_started_at"], current["timezone"], date_only=True) for ctx in sessions.values())
        lines.append("实际训练日期：" + "；".join(f"{day}（{n}场）" for day, n in sorted(dates.items())) + "。")
        if len(sessions) == 1:
            lines.append("训练开始：" + local_timestamp(next(iter(sessions.values()))["training_started_at"], current["timezone"]) + "。")
    else:
        lines.append("本期尚无可建立时间对应的训练记录；已有身体事实仍可查看。")
    declaration = report.get("declaration", {})
    if declaration.get("status"):
        lines += [declaration["limitation"], f"原声明 `{declaration['context_id']}`；受限原因 `{declaration['reason']}`。"]
    rendered_claims, rendered_citations = {}, {}
    shown_training = set()
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
            if group["series_id"] in shown_training:
                continue
            lines.append("- " + group["summary"])
            shown_training.add(group["series_id"])
        unseen = [group for group in unpaired if group["series_id"] not in shown_training]
        if unseen:
            unpaired = unseen
            shown_training.update(group["series_id"] for group in unpaired)
            missing_conditions = Counter(reason for group in unpaired for reason in group.get("limitations", []))
            lines.append(f"另有 {len(unpaired)} 条独立轨迹（{sum(g['record_count'] for g in unpaired)} 条实际记录）尚无可唯一配对的比较。完整轨迹按动作查看。")
            from healthzip.workflows.presentation import condition_label
            lines.append("；".join(f"{condition_label(reason)}：{count}条轨迹" for reason, count in sorted(missing_conditions.items())))
        evidence = question.get("evidence", {})
        for item in answer_evidence(question):
            identity = (item["claim_id"], item["version"])
            lines.append("")
            if identity in rendered_claims:
                lines.append(f"适用依据：见前文说明〔{rendered_claims[identity]}〕及其适用限制。")
                continue
            number = rendered_claims.setdefault(identity, len(rendered_claims) + 1)
            label = "行动依据" if "action_or_reassessment" in item.get("purposes", []) else "适用说明"
            lines.append(f"{label}〔{number}〕：" + item["statement"])
            lines.extend("- " + limit for limit in item.get("limitations", []))
            originals = {}
            for citation in item.get("citations", []):
                key = (citation.get("source_id"), citation.get("version"))
                original = originals.setdefault(key, {"citation": citation, "locations": []})
                locator = citation.get("locator") or {}
                location = citation.get("section") or "定位见冻结明细"
                if isinstance(locator, dict) and locator.get("page") is not None:
                    location += f" · 第{locator['page']}页"
                elif isinstance(locator, dict) and locator.get("paragraph_id") is not None:
                    location += f" · 段落{locator['paragraph_id']}"
                if location not in original["locations"]:
                    original["locations"].append(location)
            for key, original in originals.items():
                location = "；".join(original["locations"])
                if key in rendered_citations:
                    lines.append(f"- 原文：见来源〔{rendered_citations[key]}〕 · {location}")
                    continue
                reference = rendered_citations.setdefault(key, len(rendered_citations) + 1)
                citation = original["citation"]
                lines.append(f"- 来源〔{reference}〕：[{citation['title']}]({citation['url']}) · {location}")
        lines.append("")
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
                summary = (row.get("comparison") or {}).get("current")
                if summary and summary.get("statistic_kind") == "source_estimate_points":
                    statistic = (f"；窗口内末次来源估计；{summary.get('record_count', 0)}条记录，"
                                 f"发布日期已知{summary.get('publication_count', 0)}条；独立测量次数未知")
                else:
                    statistic = (f"；期间日代表值中位数；{coverage_label(summary)}" if summary else "")
                identity = " / ".join(str(row.get(k) or "未记录") for k in ("source", "device"))
                lines.append(f"- {row.get('title', row.get('metric'))}：{value}{delta}{statistic}；来源/设备 {identity}。")
        if question["id"] == "W5":
            energy = [coverage for run in runs if run["workflow_id"] == "W5"
                      for coverage in run.get("supplements", {}).get("energy_coverage", [])]
            for coverage in energy:
                mean = format_measurement(coverage["mean_kcal_per_complete_day"], "kcal/日")
                source = " / ".join(str(value or "未注明") for value in coverage["stream"])
                lines.append(f"设备配对能量专项：完整能量日覆盖 {coverage['complete_days']}/{coverage['window_days']}；"
                             f"已记录完整日平均 {mean}；来源/设备/协议/版本 {source}。")
            if energy:
                lines.append("缺日不填零，不外推完整周期总量；设备能量为基础与活动分量的既有配对结果，不另加运动摘要或 TEF。")
        lines.extend("下一步：" + step for step in question.get("steps", []))
    lines += ["", "## 上次行动观察", ""]
    actions = [a for q in questions for a in q.get("action_reviews", [])]
    if not actions:
        lines.append("本期没有截止时点可见的已选行动；不把未反馈推断为已执行。")
    for action in actions:
        lines.append("- " + str(action.get("summary") or action.get("action_text", "已选行动")))
        lines.append("执行：" + str(action.get("execution_label") or action.get("status", "未知")) + "。")
        if action.get("review_due"):
            lines.append("计划复评：" + local_timestamp(action["review_due"], current["timezone"]) + "。")
    lines += ["", "## 下一步", ""]
    # Prioritize the selected goal/action, then real events and recent relevant
    # observations. Topic numbering is not a recommendation ranking.
    preferred = [q for q in questions if q.get("action_reviews") or q.get("goal_context")]
    if goal and goal.get("goal") in {"strength", "hypertrophy"}:
        preferred += [q for q in questions if q["id"] == "W1"]
    preferred += [q for q in questions if q["id"] == "E"]
    def latest(question):
        return max((r["date"] if len(r["date"]) == 10 else local_timestamp(r["date"], current["timezone"], date_only=True)
                    for r in question.get("rows", []) if r.get("date")),
                   default=local_timestamp(current["window_start"], current["timezone"], date_only=True))
    preferred += sorted(questions, key=latest, reverse=True)
    preferred += background
    steps = list(dict.fromkeys(step for q in preferred for step in q.get("steps", [])))
    lines += ["- " + step for step in steps[:3]] or ["继续记录实际值与测量条件，之后按相同口径复评。"]
    lines += ["", "## 冻结依据与明细", "",
              f"报告格式 `{report['version']}`；事实快照 `{report['analysis_run_id']}`。",
              "每题的完整观测、来源记录、日期、分组、行动定义与已选资料保存在冻结结果，可按问题浏览或另行下载完整审计包。",
              "相同内容对象由报告引用复用；再次生成是新的报告版本。后续修订、删除或撤销不会改写此历史正文。",
              "历史说明不代表当前有效建议；当前建议需重新核对资料与适用条件。"]
    return "\n".join(lines)
