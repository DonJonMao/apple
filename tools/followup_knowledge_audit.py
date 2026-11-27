"""Append narrowly reviewed uses of existing legal originals; audit actual answers.

No health workspace, rights grant, remote model or replacement claim is created.
Run on a public backup first. Existing exact claims/edges make reruns idempotent.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench, domains, vector_index
from healthzip.knowledge.core import _claim
from healthzip.knowledge.revisions import knowledge_authority_clock, prepare_retrieval_revisions
from healthzip.knowledge.topics import ANSWER_NEEDS, question_sources

VERSION = "followup-2026-11-27.1"
REVIEW = {"reviewer": "Codex original-passage check, 2026-11-27", "reviewer_kind": "ai_assisted",
    "reviewed_at": "2026-11-27", "content_checked": True, "application_checked": True,
    "independent_expert_validation": False,
    "rationale": "Read the identified original methods and limitations; narrow measurement/record-review use only. No individual threshold or device-validation transfer."}

READINGS = {
    "carter": {"source": "HC-CARTER-HRV-2026", "hash": "810d757557b4bc75c8a2", "paragraphs": [10,11,12,13,15,49,50,51,52,53,54,55],
        "population": "Human cardiovascular research methods guideline; heterogeneous laboratory and wearable studies, not a new validation cohort",
        "protocol": "ECG versus PPG; nocturnal/resting versus free-living measurements; whole-night RMSSD versus SDNN or shorter segments",
        "conclusion": "设备/指标/时段的一致性不能跨协议转移；可连续测量并不等于已验证恢复或训练用途。",
        "limits": "不将Oura/WHOOP特定夜间协议结果移植到当前Apple后台SDNN；不采用文中记录时长、采样率或呼吸频率作为产品强制门槛。"},
    "quer": {"source": "V15-QUER-RHR-2020", "hash": "9bfc6c8aa5bf6fdc4c60", "paragraphs": [10,14,37,39],
        "population": "92,457 adults in a retrospective sustained-wear Fitbit cohort; selected users, not a representative clinical sample",
        "protocol": "Fitbit Charge HR 1–3/Blaze/Alta HR/Ionic/Surge/Versa; proprietary daily PPG RHR; daily observation",
        "conclusion": "睡眠佩戴情况会影响该研究中的专有RHR算法；同人变化须先核对记录条件。",
        "limits": "不验证Apple RHR算法；研究佩戴时长筛选不是个人记录合格线；没有临床结果支持个人报警阈值。"},
    "hrv": {"source": "R3b", "hash": "680f5e25713c14b2c0f0", "paragraphs": [4,9,13,30,32],
        "population": "Narrative review; heterogeneous mostly adult athletic studies, many small samples; resistance-training evidence limited",
        "protocol": "SDNN and RMSSD are different; HRV segment length, posture, timing and acquisition method must be explicit",
        "conclusion": "HRV应与实际表现一起查看；过量训练研究存在不变或升高结果，不能把升高自动解释为恢复变好。",
        "limits": "非Apple后台短片段SDNN效度研究；不采用综述中泛化的高低好坏、SWC或训练阈值；未知年龄不默认成人。"},
    "sleep": {"source": "HC-ROBBINS-SLEEP-2024", "hash": "1fe5fc9ed1a05b873d6e", "paragraphs": [5,6,8,9,10,29,30,31,32],
        "population": "35 healthy adults aged 20–50; one scheduled laboratory night",
        "protocol": "Apple Watch Series 8, Fitbit Sense 2, Oura Gen3 algorithm 2.0; scheduled sleep episode vs PSG, epoch and total-duration analyses",
        "conclusion": "设备可漏掉实际记录区间；阶段一致性与整夜时长不同，设备/算法和观察口径必须保留。",
        "limits": "单夜实验不证明其他设备版本、失眠、日间睡眠或家庭环境准确；不将研究的缺失补清醒应用到产品。"},
    "strength": {"source": "S5", "hash": "7252e04f7b2bfea33ef5", "paragraphs": [8,11,12,21,23,49,50],
        "population": "43 young resistance-trained men and women; eight-week lower-body intervention",
        "protocol": "Fixed exercises, technique, tempo/rest instructions; load vs repetitions progression; actual standardized Smith squat 1RM",
        "conclusion": "重量和次数是不同进阶维度；同动作、条件与实际努力程度决定比较含义。",
        "limits": "不能把该试验1RM当任意训练e1RM效度；不推算个人增肌/能力百分比；要求力竭不等于每组实际达到。"},
    "sets": {"source": "S1", "hash": "6e002198c43cecbb3a9b", "paragraphs": [13,72,76],
        "population": "2026 ACSM overview of reviews for healthy adults",
        "protocol": "Sets, load, rest, technique and effort are distinct prescription dimensions; repetitions in reserve is a proximity-to-failure estimate",
        "conclusion": "组数只描述完成的组；不能单独建立相等刺激；没有足够证据给个人精确RIR目标。",
        "limits": "不默认用户成年；不输出建议训练剂量、固定RIR目标或有效刺激分数；CC-BY-NC-ND限制原文再分发。"},
}

CLAIMS = [
    {"id": "FOLLOWUP-RHR-WEAR-COMPARABILITY", "reading": "quer", "spans": [10,37,39],
     "topics": ["BODY-OBS-resting_heart_rate_bpm", "W2", "W4"], "purposes": ["comparison", "action_or_reassessment"],
     "statement": "比较静息心率变化前，先核对同一来源、算法和睡眠期间佩戴记录。Fitbit纵向研究中的日静息心率算法会随是否睡眠佩戴而变化；日期上的差值不能单独区分身体变化与记录条件变化。",
     "limits": ["该结论来自Fitbit成年用户研究，不验证Apple或其他设备算法。", "研究的佩戴时长筛选不作为个人合格线；不据此设置恢复、疾病或行动成功阈值。", "佩戴或算法信息缺失时保留实际值，条件一致性保持未知。"]},
    {"id": "FOLLOWUP-SDNN-PERFORMANCE-CONTEXT", "reading": "hrv", "spans": [9,13,32],
     "answer_need": "hrv_direction_and_training_response",
     "topics": ["BODY-OBS-hrv_sdnn_ms", "W2", "W6"], "purposes": ["mechanism_or_exception", "action_or_reassessment"],
     "statement": "HRV变化应与同日期的实际训练表现、疲劳和睡眠记录一起核对。综述中的过量训练研究既有HRV不变，也有HRV升高的结果，因此升高或降低本身不能判定恢复改善或恶化；下一次复评保留相同指标及测量条件。",
     "limits": ["HRV研究的人群、指标和协议差异较大，不将RMSSD结果替代SDNN。", "力量训练及普通使用者的用途证据仍不足；不把未知年龄当成人，也不据此给训练剂量或阈值。", "只核对已记录的背景；没有记录不能推断没有疲劳或睡眠问题。"]},
    {"id": "FOLLOWUP-SDNN-VALIDATION-TRANSFER", "reading": "carter", "spans": [10,53,55],
     "answer_need": "wearable_hrv_protocol_transfer",
     "answer_rationale": "Carter guideline paragraphs 10, 53 and 55 distinguish signal acquisition, device/metric/recording protocol validation and intended-use evidence; no device-independent accuracy bound is supported.",
     "topics": ["BODY-OBS-hrv_sdnn_ms"], "purposes": ["measurement", "comparison"],
     "statement": "核对SDNN时，先确认来源使用的信号、指标和记录时段。特定设备整夜RMSSD或心率与ECG较一致，并不能证明短时段、自由活动下的SDNN同样准确；更换设备或采样协议后，应分别查看实际轨迹与缺失条件。",
     "limits": ["原文综述的可穿戴一致性研究多在静息或睡眠条件下，具体Oura/WHOOP协议不验证当前Apple或其他设备的后台SDNN。", "PPG、ECG、RMSSD和SDNN的测量含义不互换；这里不给个人误差界限、恢复分数或训练成功阈值。", "信号类型、算法或采样时长未提供时保持未知；已有数值继续显示，不反推用户的测量协议。"]},
    {"id": "FOLLOWUP-SLEEP-EPISODE-COMPARABILITY", "reading": "sleep", "spans": [6,10,31],
     "topics": ["BODY-OBS-sleep_stage", "W6"], "purposes": ["comparison", "action_or_reassessment"],
     "statement": "复评睡眠时长或分期变化前，核对设备版本、所选睡眠时段和实际记录覆盖。单夜PSG对照研究中，正确佩戴的设备也可能遗漏部分时段；缺少记录不能当作清醒或没有睡眠。",
     "limits": ["研究对象为健康成年人，设备为Apple Watch Series 8、Fitbit Sense 2及Oura Gen3算法2.0；不验证其他型号/算法或未知人群。", "单次实验室安排的夜间睡眠不能推广为家庭多夜、午睡或睡眠障碍准确率。", "不采用该研究的缺失时段补清醒处理；未知时段继续显示为覆盖缺口。"]},
    {"id": "FOLLOWUP-SETS-NOT-STIMULUS", "reading": "sets", "spans": [13,76],
     "topics": ["W1", "W2", "W4"], "purposes": ["comparison", "action_or_reassessment"],
     "statement": "训练组数描述完成的组，不能单独表示相等的训练刺激。复评先核对同动作、器械、组位、实际负荷和次数，并分别保留填写的RIR及缺项；RIR是接近力竭程度的估计，现有综述不足以给出个人精确目标。",
     "limits": ["ACSM资料面向健康成年人；这里仅采用变量定义和证据局限，不默认用户成年或开训练处方。", "缺RIR不等于RIR=0；相同组数不证明相同努力程度、增肌或力量效果。", "同器械/组位的分层是产品描述规则，不是该文验证过的个人因果模型。"]},
]


def version(reading):
    return f"{reading['source']}:fulltext:{reading['hash']}:jats-owned-text-1.4.1"


def apply(w):
    results = []
    for spec in CLAIMS:
        reading = READINGS[spec["reading"]]
        vid = version(reading)
        spans = [f"{vid}:s{n:05d}" for n in spec["spans"]]
        unit = w.lib.sources.execute("SELECT domains_json,assignment_status FROM retrieval_unit WHERE span_id=?", (spans[0],)).fetchone()
        vector_index.register_spans(w, vid, json.loads(unit[0]) if unit else ["strength" if spec["reading"] == "sets" else "wearable"],
                                    assignment_status=unit[1] if unit else "provisional")
        for sid in spans:
            checked = w.lib.sources.execute("SELECT domains_json FROM retrieval_unit_domain_review WHERE span_id=?", (sid,)).fetchone()
            if not checked:
                vector_index.review_unit_domains(w, [sid], ["strength" if spec["reading"] == "sets" else "wearable"], REVIEW)
        claim = {"claim_id": spec["id"], "version": VERSION, "statement": spec["statement"],
            "scope": {"explanation_purpose": "measurement_context", "population": reading["population"],
                      "protocol": reading["protocol"], "use": "record_comparability_and_evidence_limits_only"},
            "conditions": [], "limitations": spec["limits"],
            "evidence_links": [{"source_id": reading["source"], "source_version_id": vid, "span_ids": spans}]}
        result = w.review_claim(claim, REVIEW)
        edges = []
        for topic in spec["topics"]:
            edges.append(domains.link(w, origin={"type": "claim", "id": spec["id"], "version": VERSION},
                relation="applies_to", target={"type": "metric", "id": topic, "version": domains.profile_version(topic)},
                span_ids=spans, applicability={}, actor=REVIEW["reviewer"],
                rationale="Only record-comparison methods and stated limitations; no personal effect or numerical prescription.",
                evidence_types=spec["purposes"], review=REVIEW))
            if spec.get('answer_need'):
                need = ANSWER_NEEDS[spec['answer_need']]
                binding = {key: need[key] for key in ('question', 'target_claim')}
                binding.update(relation='supports', answer_complete=True, target_coverage_complete=True,
                    rationale=spec.get('answer_rationale', 'R3b paragraphs 9, 13 and 32 directly address HRV direction, performance context and heterogeneous protocols; no individual cutoff is licensed.'))
                edges.append(domains.link(w, origin={"type": "claim", "id": spec["id"], "version": VERSION},
                    relation="applies_to", target={"type": "metric", "id": topic, "version": domains.profile_version(topic)},
                    span_ids=spans, applicability={}, actor=REVIEW["reviewer"],
                    rationale=("Explicitly checked answer to the HRV direction/performance question; existing claim and application review retained."
                               if spec['answer_need'] == 'hrv_direction_and_training_response' else "Explicitly checked measurement-validation transfer limits; no current-device accuracy is granted."),
                    evidence_types=spec["purposes"], review=REVIEW, answer_bindings=[binding]))
        results.append({"claim": result, "edges": edges})
    prepare_retrieval_revisions(w)
    return results


def audit(w, output, applied):
    output.mkdir(parents=True, exist_ok=True)
    readings = []
    for key, entry in READINGS.items():
        manifest = w.lib.source(entry["source"])["manifest"]
        refs = []
        for n in entry["paragraphs"]:
            span = w.lib.span(f"{version(entry)}:s{n:05d}", include_metadata=False)
            assert span is not None
            refs.append({"span_id": span["span_id"], "text_hash": span["text_hash"],
                "section": span["section_path"], "locator": json.loads(span["locator_json"]),
                "eligible": w.lib.eligible(span, "fulltext"), "rights": json.loads(span["rights_json"])})
        readings.append({"id": key, **entry, "title": manifest["title"], "url": manifest["canonical_url"],
            "doi": manifest.get("doi"), "year": manifest.get("year"), "source_version": version(entry),
            "references": refs, "read_scope": "listed_original_methods_and_limitations_passages",
            "whole_article_reread": False, "independent_expert_review": False})
    before = knowledge_authority_clock(w.lib.root)
    retrieval = []
    for topic in sorted({topic for claim in CLAIMS for topic in claim["topics"]} | {"W3", "BODY-OBS-six_minute_walk_m"}):
        result = question_sources(w, topic, include_evidence=True)
        retrieval.append({"topic": topic, "status": result["status"], "items": result["items"],
                          "retrieval": result["retrieval"], "field_definitions": result["field_definitions"]})
    checked = []
    for spec in CLAIMS:
        claim, review, evidence = _claim(w, {"claim_id": spec["id"], "version": VERSION})
        checked.append({"claim": claim, "review": review, "evidence": evidence,
            "actually_retrieved_topics": [r["topic"] for r in retrieval if any(i["claim_id"] == spec["id"] for i in r["items"])]})
    for name, payload in (("passage-readings.json", readings), ("narrow-claims.json", checked), ("retrieval.json", retrieval),
        ("ingestion.json", {"applied": applied, "only_append_claims_and_edges": True, "existing_rights_changed": False,
            "external_calls": 0, "retrieval_authority_stable": before == knowledge_authority_clock(w.lib.root)})):
        (output / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({s["claim"]["claim_id"]: s["actually_retrieved_topics"] for s in checked}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    workbench = KnowledgeWorkbench(args.root)
    try:
        applied = apply(workbench) if args.apply else []
        audit(workbench, args.output, applied)
    finally:
        workbench.close()
