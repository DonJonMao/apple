"""Frozen calendar reports composed from the existing metric/workflow services."""
import hashlib
import json
import math
from datetime import datetime, timezone

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
from .reports import markdown, review_analysis
from .storage import load_run, report_context

TRAINING = tuple(f"STR-{i:02}" for i in range(1, 16)) + ("STR-23", "STR-29")
BODY = ("STATE-SLEEP-MAIN", "STATE-SLEEP-24H", "STATE-SLEEP-COVERAGE", "STATE-SLEEP-STAGE", "STATE-SLEEP-TIMING",
        "STATE-RHR", "STATE-SDNN", "STATE-REFERENCE-MEDIAN", "STATE-REFERENCE-MAD", "STATE-DEVIATION",
        "STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN", "BODY-MASS-DAILY", "BODY-MASS-TREND",
        "LOAD-SRPE", "LOAD-DURATION", "LOAD-SRPE-AU", "ENERGY-BASAL", "ENERGY-ACTIVE", "ENERGY-DEVICE-TOTAL",
        "ENERGY-RECORD-COVERAGE", "ENERGY-IDENTIFIABILITY")


REPORT_VERSION = "joint-period-report-1.3.1"


def _fast_json_compatible(value):
    """Reject parser edge cases once per content build, preserving stdlib types."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
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


def create_report(repo, analysis, *, period, knowledge_root=".local/knowledge", progress=None):
    """Freeze a fresh version per explicit request; share its verified content."""
    if period not in {"week", "month"}:
        raise ValueError("calendar_week_or_month_required")
    TrainingService(repo)
    context_id = analysis.get("selection_context", {}).get("workflow_context_id")
    before = input_version(repo, context_id)
    knowledge_before = _knowledge_identity(knowledge_root)
    notify = progress or (lambda stage: None)
    fields = {field: analysis.get(field) for field in ("cutoff_time", "timezone", "selection_context",
              "retrospective", "algorithm_version")}
    key = {"version": REPORT_VERSION, "period": period, "selection": fields, "inputs": before,
           "knowledge": knowledge_before}
    built = False

    def assemble():
        nonlocal built
        built = True
        with shared_report_inputs(repo), report_evidence(knowledge_root):
            payload, text, temporarily_unavailable = _assemble(
                repo, analysis, period, knowledge_root, before, knowledge_before, notify)
        payload_json = json.dumps(payload, ensure_ascii=False)
        digest = hashlib.sha256(payload_json.encode())
        digest.update(b"\x00")
        digest.update(text.encode())
        result = payload_json, text, digest.hexdigest(), _fast_json_compatible(payload)
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
    payload = _decode_content(payload_json, fast_compatible)
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
        if input_version(repo, context_id) != before or _knowledge_identity(knowledge_root) != knowledge_before:
            raise ValueError("concurrent_joint_report_inputs_changed_retry_required")
        repo.conn.execute("INSERT INTO joint_period_report VALUES(?,?,?,?,?)", (payload["report_id"], "local",
            payload["created_at"], saved_json, text))
        repo.conn.commit()
    except BaseException:
        repo.conn.rollback()
        raise
    return {**payload, "markdown": text}


def _assemble(repo, analysis, period, knowledge_root, before, knowledge_before, notify):
    context_id = analysis.get("selection_context", {}).get("workflow_context_id")
    notify("读取本期事实")
    current = period_facts(repo, cutoff_time=analysis["cutoff_time"], timezone_name=analysis["timezone"],
        period=period, context=analysis.get("selection_context"), retrospective=analysis.get("retrospective", False))
    declaration = report_context(repo, context_id, current["cutoff_time"], "retrospective" if current["retrospective"] else "prospective")
    # Explicit current bounds: W4's two earlier complete periods are a separate
    # comparison below and cannot replace current training or body facts.
    notify("核对本期训练与知识依据")
    runs = review_analysis(repo, current, include_background=True, knowledge_root=knowledge_root, include_session_background=True)
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
        "current": current, "analysis_run_id": current_analysis_id, "declaration": declaration, "workflow_run_ids": [r["run_id"] for r in runs],
        "historical_run_ids": [r["run_id"] for r in historical], "objective_comparisons": comparisons,
        "period_identity": "current_partial_local_calendar_period", "input_revision": before,
        "knowledge_signature": knowledge_before[0], "knowledge_signature_algorithm": knowledge_before[1]}
    temporary_failures = any(run.get("knowledge", {}).get("status") == "service_failure"
                             for run in (*runs, *historical))
    return payload, render_report(repo, payload), temporary_failures


def load_report(repo, report_id):
    row = repo.conn.execute("SELECT payload_json,markdown FROM joint_period_report WHERE report_id=? AND user_id='local'", (report_id,)).fetchone()
    if row is None:
        raise ValueError("joint_report_not_found")
    return {**json.loads(row[0]), "markdown": row[1]}


def render_report(repo, report):
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
