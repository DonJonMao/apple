"""Readable rendering of frozen MetricResults; no repository queries or formulas."""
from healthzip.science import definitions
from healthzip.science.contracts import task_metric_results

LABELS = {
    "completed_work_parent_sets": "完成工作组", "segments": "工作组片段", "unknown_work_sets": "资料不足的完成组",
    "completed": "已完成", "skipped": "已跳过", "unknown": "未确认", "planned": "原计划组",
    "extra_sets": "额外完成组", "completed_fraction_of_plan": "原计划完成比例",
    "observed_minutes": "已观察睡眠分钟", "complete_episode": "完整睡眠片段已确认",
    "rir": "记录 RIR", "rir_interval": "记录 RIR 区间", "original_rpe": "原始 RPE", "converted": "由 RPE 换算",
    "load_value": "负荷", "load_unit": "负荷单位", "load_basis": "负荷口径", "reps": "次数",
    "duration_minutes": "时长（分钟）", "session_rpe": "整场评分", "AU": "评分×分钟（AU）",
    "srpe_protocol": "评分量表", "duration_protocol": "计时协议", "actual_collection_delay_minutes": "结束后采集间隔（分钟）",
    "date": "观察日期", "value": "记录值", "protocol": "来源／设备／协议", "stream": "来源分组",
    "source_version": "来源版本", "unit": "单位", "source_name": "来源", "device": "设备",
    "difference": "差值", "delta_reps": "次数差", "delta_rir": "RIR 差", "delta_load": "负荷差",
    "reference_observed_at": "参考观察日期", "current_observed_at": "本次观察日期",
    "rir_before": "参考 RIR", "rir_after": "本次 RIR", "entered_change": "记录口径负荷差",
    "repetition_difference": "次数差", "recorded_change": "记录负荷差",
    "first": "起点", "last": "末点", "mean": "均值", "median": "中位数", "n": "样本数",
    "sessions": "记录场次", "observed_dates": "记录日期数", "span_days": "观察跨度（天）",
    "basal_kcal": "基础能量（kcal）", "active_kcal": "活动能量（kcal）", "device_total_kcal": "已配对记录能量合计（kcal）",
    "complete_days": "完整日数", "valid_day_mean_kcal_day": "完整日平均（kcal/日）", "paired_dates": "已配对日期",
    "observed_kcal": "已记录能量（kcal）", "total_kcal": "已记录能量（kcal）",
    "plates_per_side_kg": "单侧片重", "external_total_kg": "总外负荷", "per_hand_kg": "每只哑铃重量",
}
STATUS = {"valid": "有可用记录", "partial": "部分资料可用", "insufficient": "资料不足",
          "incompatible": "不可直接比较", "conflicted": "记录冲突", "not_applicable": "不适用",
          "not_identifiable": "现有信息不能唯一识别", "stale": "需要复核"}


def display(value):
    if value is None:
        return "未知"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:g}"
    return LABELS.get(str(value), str(value)).replace("|", "／").replace("\n", " ")


def _fields(value, path=""):
    """Supplemental field table, preserving every value without raw JSON prose."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _fields(item, (path + " · " if path else "") + LABELS.get(key, key))
    elif isinstance(value, list):
        for index, item in enumerate(value, 1):
            yield from _fields(item, f"{path} · 第 {index} 项")
    else:
        yield f"|{display(path)}|{display(value)}|"


def metric_lines(metric, *, title=None):
    name = title or definitions(include_observations=True)[metric["metric_id"]]["title"]
    if metric.get("task_results"):
        lines = []
        for task in task_metric_results(metric):
            lines += metric_lines(task["metric"], title=name + " · " + str(task.get("exercise_name") or "独立训练任务"))
            lines += [f"任务 `{task['task_id']}`；条件 `{task.get('condition_key')}`；协议：{display(task.get('protocol'))}。", ""]
        return lines
    window = metric["window"]
    lines = [f"#### {name}", "",
        f"范围 {window['start']} 至 {window['end']}（不含终点，{window['timezone']}）；截止 {metric['cutoff_time']}。",
        f"样本（有效/总数）{display(metric['valid_n'])}/{display(metric['total_n'])}；单位 {display(metric['unit'])}；{STATUS.get(metric['data_status'], metric['data_status'])}。", ""]
    value, mid = metric["value"], metric["metric_id"]
    if value is None:
        lines += ["此项没有可用数值；缺失不填零，也不表示没有训练或没有观察。", ""]
    elif mid == "OBS-VO2-REPORTED":
        for stream in value["streams"]:
            lines += ["来源／设备／协议／版本：" + " / ".join(display(stream.get(k)) for k in ("source_name", "device", "protocol_id", "source_version")) + "。", "",
                "|观察日期|记录值|单位|来源记录|", "|---|---:|---|---|"]
            lines += [f"|{p['observed_at']}|{display(p['value'])}|{display(metric['unit'])}|{p['source_record_id']}|" for p in stream["observations"]]
            lines.append("")
    elif mid in {"STATE-RHR", "STATE-SDNN", "BODY-MASS-DAILY"}:
        for points in value.values():
            lines += ["|观察日期|记录值|单位|来源／设备／协议|", "|---|---:|---|---|"]
            lines += [f"|{p['date']}|{display(p['value'])}|{display(metric['unit'])}|{' / '.join(display(v) for v in p['protocol'])}|" for p in points]
            lines.append("")
    elif mid == "STR-11":
        lines += ["|参考记录|负荷|口径|次数|RIR|参考协议|", "|---|---|---|---:|---|---|"]
        lines += [f"|{p['id']}|{display(p['load_value'])} {display(p['load_unit'])}|{display(p['load_basis'])}|{display(p['reps'])}|{display(p['rir']) if p['rir'] is not None else display(p.get('rir_interval'))}|{display(p['reference_policy_id'])}|" for p in value]
        lines.append("")
    elif isinstance(value, (int, float, str)):
        lines += [f"数值：{display(value)} {display(metric['unit'])}。", ""]
    else:
        items = value if isinstance(value, list) else [value]
        for index, item in enumerate(items, 1):
            if isinstance(item, dict):
                readable = [f"{LABELS[key]} {display(v)}" for key, v in item.items()
                            if key in LABELS and not isinstance(v, (dict, list))]
                if readable:
                    lines += [f"记录 {index}：" + "；".join(readable) + "。", ""]
        lines += ["<details><summary>补充分项与核对字段</summary>", "",
            "|记录分项|数值／已记录条件|", "|---|---|", *_fields(value), "", "</details>", ""]
    if metric.get("daily_buckets") and mid == "ENERGY-DEVICE-TOTAL":
        lines += ["|记录日期|基础能量（kcal）|活动能量（kcal）|配对合计（kcal）|完整日|", "|---|---:|---:|---:|---|"]
        lines += [f"|{d['date']}|{display(d['basal_kcal'])}|{display(d['active_kcal'])}|{display(d['device_total_kcal'])}|{display(d['complete'])}|" for d in metric["daily_buckets"]]
        lines.append("")
    lines += [f"计算版本 {metric['algorithm_version']}；参数版本 {display(metric.get('parameter_set_id'))}。",
        "来源记录：" + "、".join(str(s) for s in metric["source_record_ids"]) + "。",
        "限制：" + "；".join(metric.get("limitations", [])) + "。",
        "核对原因：" + "；".join(metric["reason_codes"]) + "。", ""]
    return lines


def frozen_fact_lines(snapshot, run):
    lines = ["本节读取该次运行保存的事实，后续修改记录不会重算本下载。", ""]
    task = snapshot.get("task_selection")
    if task:
        lines += [f"训练任务：{task.get('exercise_name') or '已选动作'}；条件 `{task.get('condition_key')}`；协议 {display(task.get('protocol'))}。", ""]
    for metric in {**snapshot["metrics"], **snapshot["observations"]}.values():
        lines += metric_lines(metric)
    for segment in run["supplements"].get("vo2_segments", []):
        difference = segment["recorded_difference"]
        lines += [f"同来源观测 {segment['first_at']} → {segment['last_at']}；样本 {segment['n']}；"
            + (f"变化 {display(difference)} {segment['unit']}。" if difference is not None else "尚无可比较差值，单次观测或来源／版本／协议不足。"),
            segment["limitation"], ""]
    for coverage in run["supplements"].get("energy_coverage", []):
        lines += [f"完整能量日覆盖 {coverage['complete_days']}/{coverage['window_days']}；完整日平均 {display(coverage['mean_kcal_per_complete_day'])} kcal/日。",
            "缺日不填零，不外推完整周总量；设备能量为基础与活动分量的既有配对结果，不另加运动摘要或 TEF。", ""]
    for period in run["supplements"].get("calendar_comparison", {}).get("periods", []):
        lines += [f"完整比较周期：{period['start']} 至 {period['end']}（不含终点）。", ""]
        lines += metric_lines(period["metric"]) if period["metric"] else ["此周期未记录所选任务，历史比较不足；不以零作基线。", ""]
    partial = run["supplements"].get("partial_current_period")
    if partial:
        lines += [f"本期未结束部分：{partial['start']} 至 {partial['cutoff_time']}。", ""]
        lines += metric_lines(partial["metric"]) if partial["metric"] else ["本期没有该任务的可用记录。", ""]
    return lines
