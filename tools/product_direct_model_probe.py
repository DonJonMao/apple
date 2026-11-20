"""Explicit, synthetic-only direct-chat probe using the configured owned model.

This experiment does not enable a production explanation path or authorize any
private health transmission. It bypasses retrieval intentionally to assess what
the model can explain from four fixed synthetic cases. Credentials stay in the
existing configuration and are never written to the probe artifacts.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from healthzip.knowledge.model_services import ModelClient, ModelUnavailable, load_services

SYSTEM = """你在进行一个明确授权的产品研发试验，所有输入都为完全合成的测试数据，不对应任何真实个人。
你可以使用一般医学、睡眠和运动科学知识直接回答；本次没有进行RAG、联网文献检索或本地知识库查询。
必须分开写：观察到什么、可能为什么、具体下一步、还无法确定什么。不要把时间先后或相关性写成确定因果。
不要虚构未提供的训练、症状、测量条件、人群信息；缺失不是零。不要把SDNN、RMSSD和未定义的HRV混为一谈。
不要诊断疾病、给个体用药或精确训练负荷处方。一般知识只能提供候选解释，不能成为已验证的个人原因。
可以给最多3条你有把握准确定位的真实参考来源，便于后续核对；不要求DOI，有把握才提供。不能编造来源。
所有参考一律标成“待核验参考建议”，不能声称它已被检索、已被本地审核或已验证。没有把握时直接说明缺乏可靠引用。
只返回一个JSON对象，中文正文约500至900字。键为 observations（字符串数组）、possible_explanations（含hypothesis/why_consistent/what_is_missing的对象数组）、next_steps（含action/purpose的对象数组）、unknowns（字符串数组）、references（含citation/locating_information/verification_status的对象数组）。
即使无法比较，也应解释限制并给一两个具体的记录或核对步骤，而不是只输出免责声明。"""

CASES = [
    {"id": "matched_7_day_heart_sleep", "title": "同口径七天：静息心率、SDNN与睡眠一起变化", "facts": {
        "synthetic_only": True,
        "comparison": "两个连续且完整的7天窗口，每个窗口都有7个心率日值和7个睡眠记录日",
        "person_context": "合成成年人，未提供病史、用药和训练经验",
        "measurement": "同一设备与版本；心率及HRV均在晨起同一时间段、坐位静息5分钟后采集；HRV字段明确为SDNN毫秒，不能换成RMSSD",
        "previous": {"resting_heart_rate_mean_bpm": 60, "sdnn_mean_ms": 45, "recorded_sleep_mean_hours": 6.8},
        "current": {"resting_heart_rate_mean_bpm": 65, "sdnn_mean_ms": 36, "recorded_sleep_mean_hours": 5.9},
        "sleep_scope": "只有设备记录的睡眠时长，未独立验证整夜完整性与真实入睡时间",
        "not_recorded": ["训练量及动作顺序", "感染症状", "饮酒和咖啡因", "用药", "压力及主观疲劳"],
        "question": "这些变化可能怎样理解？最值得先核对什么？可以做哪一两项具体行动，哪些原因目前无法判断？"}},
    {"id": "sleep_duration_unknown_coverage", "title": "只有睡眠时长，记录完整性未知", "facts": {
        "synthetic_only": True,
        "comparison": "连续两个7天窗口；前期只有4晚有效记录，本期只有5晚有效记录，其他日期没有记录",
        "previous_observed_nights_mean_hours": 5.4, "current_observed_nights_mean_hours": 6.1,
        "coverage": "不知道每晚记录是否完整；没有可核对的上床/入睡/起床时间、午睡和佩戴中断记录",
        "other_health_data": "无心率、无HRV、无白天嗜睡或精神状态记录；年龄与病史未知",
        "question": "能否说睡眠已经改善或仍然睡眠不足？怎样区分时长变化和漏记，下一步具体补哪些信息？"}},
    {"id": "unknown_protocol_population", "title": "测量协议、人群和HRV定义未知", "facts": {
        "synthetic_only": True,
        "comparison": "两个7天窗口各3条记录；前期来自设备A，本期来自设备B，测量时段和体位未知",
        "previous": {"labelled_resting_heart_rate_mean_bpm": 60, "undefined_hrv_mean_ms": 34},
        "current": {"labelled_resting_heart_rate_mean_bpm": 57, "undefined_hrv_mean_ms": 48},
        "hrv_definition": "源字段只写HRV（毫秒），不知道SDNN还是RMSSD，也不知道采样长度与伪差处理",
        "person_context": "年龄、成年人身份、健康状况、训练背景、用药均未知",
        "sleep": "没有记录",
        "question": "能否据此认为身体状态或恢复改善？在解释前应核对什么，哪些现成阈值或研究结论不能直接套用？"}},
    {"id": "sparse_unequal_windows", "title": "稀疏记录与不等长窗口", "facts": {
        "synthetic_only": True,
        "previous_window": {"dates": "合成11月1日至7日，共7天", "resting_hr_observations_bpm": [60, 62, 61],
                            "observation_dates": ["11月1日", "11月4日", "11月7日"], "recorded_sleep_hours": [6.5, 7.0]},
        "current_window": {"dates": "合成11月8日至10日，共3天", "resting_hr_observations_bpm": [67],
                           "observation_dates": ["11月10日"], "recorded_sleep_hours": []},
        "measurement": "两期来自同一设备，但具体测量协议未知；没有症状、训练、压力或睡眠覆盖记录",
        "question": "本期这条心率记录说明什么？能否把两个窗口直接判为持续恶化，或把没有睡眠记录解释成没有睡觉？给具体下一步。"}},
]


def _safe_usage(raw):
    if not isinstance(raw, dict):
        return {}
    fields = ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "reasoning_tokens")
    result = {key: value for key, value in raw.items() if key in fields and type(value) is int}
    for name in ("prompt_tokens_details", "completion_tokens_details"):
        if isinstance(raw.get(name), dict):
            result[name] = {key: value for key, value in raw[name].items() if type(value) is int}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-network", action="store_true", help="Explicitly authorize only these synthetic direct-chat requests")
    parser.add_argument("--output", required=True)
    parser.add_argument("--knowledge-root", default=".local/knowledge")
    parser.add_argument("--case", action="append", choices=[case["id"] for case in CASES])
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    _, reranker = load_services(Path(args.knowledge_root))
    if reranker is None:
        raise SystemExit("No configured owned chat model is available.")
    # This local copy only changes the per-request timeout. No consent, source
    # library, application environment or persisted configuration is modified.
    config = replace(reranker.config, timeout_seconds=60)
    client = ModelClient(config)
    report = {"experiment": "direct_chat_without_retrieval", "data": "four_fixed_synthetic_cases",
              "executed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
              "model": config.model_id, "model_version": config.model_version,
              "configured_role": "public_evidence_reranker_chat", "network_explicitly_requested": args.run_network,
              "private_health_transmitted": False, "production_configuration_changed": False,
              "retrieval_used": False, "citations": "unverified_reference_suggestions", "cases": []}
    selected = [case for case in CASES if not args.case or case["id"] in args.case]
    for case in selected:
        user = "以下完全是合成测试案例，不是真实用户数据。\n" + json.dumps(case["facts"], ensure_ascii=False, indent=2)
        payload = {"model": config.model_id, "temperature": 0, "max_tokens": 2600,
                   "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
        record = {"case_id": case["id"], "title": case["title"], "synthetic_input": case["facts"],
                  "request": payload, "status": "not_run"}
        if args.run_network:
            started = time.perf_counter()
            try:
                value = client.post(payload)
                choices = value.get("choices", [])
                if len(choices) != 1:
                    raise ModelUnavailable("unexpected_choice_count")
                choice = choices[0]
                content = choice.get("message", {}).get("content")
                if not isinstance(content, str):
                    raise ModelUnavailable("missing_text_response")
                record.update(status="received", elapsed_seconds=round(time.perf_counter() - started, 3),
                              returned_model=value.get("model"), finish_reason=choice.get("finish_reason"),
                              usage=_safe_usage(value.get("usage")), response_text=content)
                try:
                    parsed = json.loads(content.removeprefix("```json").removesuffix("```").strip())
                    record["parsed_response"] = parsed
                    record["json_object"] = isinstance(parsed, dict)
                except ValueError:
                    record["json_object"] = False
            except ModelUnavailable as error:
                record.update(status="failed", elapsed_seconds=round(time.perf_counter() - started, 3),
                              error_code=str(error))
        (output / (case["id"] + ".json")).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        report["cases"].append({key: record[key] for key in (
            "case_id", "title", "status", "elapsed_seconds", "finish_reason", "usage", "json_object") if key in record})
        print(json.dumps(report["cases"][-1], ensure_ascii=False), flush=True)
    (output / "probe-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
