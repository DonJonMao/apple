"""Auditable lexical retrieval and a closed, deterministic explanation contract."""

from __future__ import annotations

import json
import math
import re
from collections import Counter

from .store import digest, dumps
from .support import assess_support, normalized_question

ROUTE_TERMS = {
    "strength": ("力量", "负重", "公斤", "史密斯", "卧推", "e1rm", "1rm", "rir", "rpe", "配重", "重复", "strength", "load"),
    "progression": ("进阶", "加重", "下次", "目标", "progression", "overload", "次数进步"),
    "plateau": ("停滞", "没涨", "不变", "平台", "plateau", "等效", "置信", "p值"),
    "recovery": ("睡", "恢复", "疲劳", "酸痛", "hrv", "sdnn", "rmssd", "心率", "recovery", "session-rpe"),
    "energy": ("能量", "热量", "摄入", "体重", "减重", "kcal", "energy", "消耗", "卡路里"),
    "personalization": ("个体", "预测", "因果", "模型", "随机", "personal", "验证", "留出"),
}
BOUNDARIES = {
    "strength": "保留动作、器械、侧别、活动范围和负重口径；条件未知时无法确认可比。模型估计与实测能力分开。",
    "progression": "候选需要用户目标、可比历史和器械可实现步长；当前没有依据保证某个新负荷必然完成。",
    "plateau": "记录不变可能是任务没有被挑战；停滞推断还需要真实时间、测量误差和预先定义的实用等效范围。",
    "recovery": "身体状态首先作为描述；缺测保持未知，不能据此自动换算训练负荷或局部肌肉恢复。",
    "energy": "设备报告、真实总消耗、净储能、相对摄入变化和绝对摄入是不同量；缺少可识别基线时保留事实。",
    "personalization": "个人预测需要与历史基线作时间前向比较；预测关联和建议后改善不能单独证明干预因果效应。",
}


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.lower())
    output = []
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            output.extend(word[i:i + 2] for i in range(max(1, len(word) - 1)))
        else:
            output.append(word)
    return output


def route_question(question: str, route: str | None = None) -> list[dict]:
    if route and route not in ROUTE_TERMS:
        raise ValueError("unknown knowledge route")
    scores = {key: [term for term in terms if term in question.lower()] for key, terms in ROUTE_TERMS.items()}
    primary = route or max(scores, key=lambda x: len(scores[x]))
    result = [{"route": primary, "reason": "explicit_user_route" if route else "lexical_intent", "matched_terms": scores[primary]}]
    for key in ROUTE_TERMS:
        if key != primary and scores[key]:
            result.append({"route": key, "reason": "cross_route_context:" + ",".join(scores[key]), "matched_terms": scores[key]})
    return result


def _context_match(required: dict, context: dict) -> tuple[bool, str]:
    from .applicability import context_match
    return context_match(required, context)


def retrieve(workbench, question: str, routes: list[dict], context: dict, k: int = 6, release_id: str | None = None) -> dict:
    if not 1 <= k <= 50:
        raise ValueError("k must be a positive retrieval resource budget at most 50")
    route_ids = {x["route"] for x in routes}
    candidates, excluded = [], []
    roles = set(context.get("corpus_roles", ["core", "research"]))
    if not roles or not roles <= {"core", "research", "interface", "catalog"}:
        raise ValueError("unknown corpus partition")
    allowed_core_refs = None
    release_scope = {"selection_version": "frozen-membership-1.4.4",
                     "core_claims": "current", "legacy_theories": "current",
                     "current_validity_checks": True}
    if release_id is not None:
        core_release = workbench.lib.theories.execute(
            "SELECT manifest_json,sha256 FROM core_release WHERE release_id=?", (release_id,)
        ).fetchone()
        legacy_release = workbench.lib.theories.execute(
            "SELECT sha256 FROM theory_release WHERE release_id=?", (release_id,)
        ).fetchone()
        if core_release is None and legacy_release is None:
            raise ValueError("unknown release")
        allowed_core_refs = {(c["claim_id"], c["version"])
                             for c in json.loads(core_release["manifest_json"])["claims"]} if core_release else set()
        rows = workbench.lib.released_theories(release_id) if legacy_release else []
        release_scope.update(
            core_claims="frozen_snapshot" if core_release else "excluded_no_snapshot",
            legacy_theories="frozen_snapshot" if legacy_release else "excluded_no_snapshot",
            core_release_sha256=core_release["sha256"] if core_release else None,
            legacy_release_sha256=legacy_release["sha256"] if legacy_release else None,
        )
    else:
        rows = workbench.lib.theories.execute("SELECT * FROM theory ORDER BY theory_id,version")
    for row in rows:
        card, review = json.loads(row["card_json"]), json.loads(row["review_json"])
        if not route_ids.intersection(card.get("domains", [])):
            continue
        if row["status"] != "approved":
            excluded.append({"theory_id": row["theory_id"], "reason": "theory_" + row["status"]})
            continue
        matched, reason = _context_match(review.get("applicability", {}).get("required", {}), context)
        if not matched:
            excluded.append({"theory_id": row["theory_id"], "reason": reason})
            continue
        links, spans = review.get("evidence_links", []), []
        reasons = []
        for link in links:
            for sid in link["span_ids"]:
                span = workbench.lib.span(sid)
                if not span:
                    reasons.append("missing_span:" + sid)
                    continue
                ok, why = workbench.lib.eligible(span, context.get("required_material"))
                if not ok:
                    reasons.append(why)
                else:
                    manifest = workbench.lib.source(span["source_id"])["manifest"]
                    source_roles = set(manifest.get("corpus_roles", ["research"]))
                    if not source_roles & roles or not source_roles & {"core", "research"}:
                        reasons.append("corpus_partition_excluded")
                        continue
                    spans.append(span)
        if reasons or not spans:
            excluded.append({"theory_id": row["theory_id"], "reason": ";".join(reasons) or "no_spans"})
            continue
        text = card.get("title", "") + " " + " ".join(c["text"] for c in review.get("claims", []))
        exact_binding = any(normalized_question(binding["question"]) == normalized_question(question)
                            for claim in review.get("claims", []) for binding in claim.get("answer_bindings", []))
        candidates.append({"theory_id": row["theory_id"], "theory_version": row["version"], "card": card,
                           "review": review, "spans": spans, "terms": Counter(tokens(text)), "exact_reviewed_question": exact_binding})
    from .tasks import core_candidates, parse_task, source_constraints_match
    core, core_excluded = core_candidates(workbench, question, context, roles, allowed_refs=allowed_core_refs)
    excluded.extend(core_excluded)
    for candidate in core:
        matched, reason = _context_match(candidate["review"]["applicability"]["required"], context)
        if not matched:
            excluded.append({"theory_id": candidate["theory_id"], "reason": reason})
            continue
        if not route_ids.intersection(candidate["card"]["domains"]) and not candidate["exact_reviewed_question"]:
            continue
        candidate["terms"] = Counter(tokens(candidate["card"]["title"] + " " + " ".join(c["text"] for c in candidate["review"]["claims"])))
        candidates.append(candidate)
    task = parse_task(question, context)
    for candidate in candidates:
        evidence = [{"source_id": span["source_id"], "locator": json.loads(span["locator_json"])} for span in candidate["spans"]]
        if task["specific_source_unresolved"] or not source_constraints_match(workbench, evidence, task["source_constraints"]):
            for claim in candidate["review"]["claims"]:
                claim["answer_bindings"] = []
            candidate["exact_reviewed_question"] = False
            excluded.append({"theory_id": candidate["theory_id"], "reason": "requested_source_or_edition_unavailable"})
    query_terms = set(tokens(question))
    for item in candidates:
        score = 0.0
        for token in query_terms:
            df = sum(token in c["terms"] for c in candidates)
            tf = item["terms"].get(token, 0)
            if tf:
                score += (1 + math.log(tf)) * math.log(1 + (len(candidates) + 1) / (df + 1))
        item["score"] = score
    candidates.sort(key=lambda x: (not x["exact_reviewed_question"], -x["score"], x["theory_id"], x["theory_version"]))
    chosen = [{k: v for k, v in c.items() if k != "terms"} for c in candidates if c["score"] > 0 or c["exact_reviewed_question"]][:k]
    return {"retriever_version": "lexical-1.4.1", "question_contract": task, "k": k, "candidates": chosen, "excluded": excluded,
            "_support_candidates": [{k: v for k, v in c.items() if k != "terms"} for c in candidates],
            "eligible_candidate_count": len(candidates), "numeric_action_authority": "none", "release_id": release_id,
            "release_scope": release_scope}


def _guard(context: dict) -> tuple[str | None, str | None]:
    # These are input/authority contracts, not physiological effect estimates.
    if context.get("requested_other_user") and context.get("requested_other_user") != context.get("user_id") and not context.get("authorization_for_B", False):
        return "enforce_tenant_isolation", "未获得所请求用户的数据权限，不能读取或引用其训练记录。"
    if context.get("source_state") == "withdrawn":
        return "invalidate_dependencies", "来源已撤回，旧解释必须重新校验依赖后才能使用。"
    if context.get("source_text_injection"):
        return "ignore_source_instructions", "文献原文只作为证据数据，不能改变权限或执行其中的指令。"
    if context.get("effort_scale") and context["effort_scale"] not in {"RIR", "RIR_RPE_0_10"}:
        return "reject_invalid_conversion", "当前用力量表与剩余次数口径不兼容；保留原值，可以另行直接记录 RIR。"
    if context.get("HRV_metric") == "SDNN" and context.get("requested_metric") == "RMSSD":
        return "reject_protocol_mismatch", "SDNN 与 RMSSD 是不同指标，不能从当前标量换算；机会性测量不能直接替代另一采样协议。"
    if context.get("retrieved_population") and context.get("target_population") != context["retrieved_population"]:
        return "reject_scope_mismatch", "检索人群与目标人群不匹配，不能直接转用该主张。"
    if context.get("available_material") == "abstract":
        return "insufficient_material_depth", "当前只有摘要，不能据此补出正文表格、方案或附录细节。"
    if context.get("hrv_sample_count") == 0:
        return "preserve_missingness", "没有 HRV 样本，当前状态未知；不能将缺测记为零或判断异常。"
    if context.get("split") == "random_rows":
        return "require_temporal_validation", "同一人的随机行划分不足以验证未来预测；需要时间前向切分，并与仅历史基线比较。"
    if context.get("prepost_improvement") and not context.get("randomized_assignment"):
        return "reject_causal_overclaim", "观察到建议后改善，仍不能区分干预效果、时间趋势及其他共同变化。"
    return None, None


def query(workbench, question: str, *, route: str | None = None, context: dict,
          personal_metrics: list[dict], k: int = 6, proposed_answer: dict | None = None,
          release_id: str | None = None) -> dict:
    routes = route_question(question, route)
    context = dict(context)
    from .tasks import resolve_named_sources
    context = resolve_named_sources(workbench, question, context, release_id)
    if route:
        context["query_route_explicit"] = route
    if "rmssd" in question.lower() and context.get("HRV_metric") == "SDNN":
        context.setdefault("requested_metric", "RMSSD")
    guard, guard_text = _guard(context)
    retrieval = retrieve(workbench, question, routes, context, k, release_id)
    observations = []
    for metric in ([] if guard == "enforce_tenant_isolation" else personal_metrics):
        # Only already-computed, traceable metric objects are carried through; no inferred numbers.
        if metric.get("metric_id") and (metric.get("data_cutoff") or metric.get("cutoff_time")) and (metric.get("algorithm_version") or metric.get("formula_version") or metric.get("definition_version")):
            observations.append(metric)
    claims, citations, related = [], [], []
    support_candidates = retrieval.pop("_support_candidates")
    displayed = {(c["theory_id"], c["theory_version"]) for c in retrieval["candidates"]}
    assessment, supported = assess_support(question, context, support_candidates,
        required_parts=retrieval["question_contract"]["required_answer_parts"], displayed=displayed)
    assessment["conflict_screen"] = {"complete": True, "eligible_theories_checked": len(support_candidates),
                                      "scope": "all eligible route and applicability matches before display budget"}
    if not guard:
        for candidate in retrieval["candidates"]:
            related.append({"theory_id": candidate["theory_id"], "theory_version": candidate["theory_version"],
                            "source_statements": [c["text"] for c in candidate["review"]["claims"]],
                            "evidence_links": candidate["review"]["evidence_links"],
                            "status": "reading_material_not_answer_support"})
        for candidate, claim, binding in supported:
            if not any(c["text"] == claim["text"] and c["theory_id"] == candidate["theory_id"] for c in claims):
                claims.append({"text": claim["text"], "theory_id": candidate["theory_id"],
                               "theory_version": candidate["theory_version"], "span_ids": claim["span_ids"],
                               "kind": "reviewed_evidence_claim", "direction": claim.get("direction", "unspecified"),
                               "limitations": claim.get("limitations", []), "target_claim": binding["target_claim"],
                               "evidence_relation": binding["relation"], "support_rationale": binding["rationale"]})
            for link in candidate["review"]["evidence_links"]:
                cited = [sid for sid in link["span_ids"] if sid in claim["span_ids"]]
                if not cited:
                    continue
                citation = {"theory_id": candidate["theory_id"], "theory_version": candidate["theory_version"],
                            **link, "span_ids": cited, "evidence_level_used": "fulltext" if all(workbench.lib.span(s)["material_type"] == "fulltext" for s in cited) else "abstract"}
                if citation not in citations:
                    citations.append(citation)
    sentences = [guard_text] if guard_text else [c["text"] for c in claims]
    if not guard:
        computed = [f"已计算指标 {m['metric_id']}：{dumps(m.get('value'))}；单位 {m.get('unit')}；时间窗 {dumps(m.get('window'))}；截止 {m.get('cutoff_time', m.get('data_cutoff'))}；版本 {m.get('algorithm_version', m.get('formula_version'))}。" for m in observations]
        sentences = computed + sentences
    if not sentences:
        sentences = ["已找到相关阅读材料，但尚未建立其对当前目标主张及适用条件的支持关系；当前问题仍未得到证据支持的回答。" if related else "当前没有匹配且完成逐主张审核的证据；可以查看已记录事实，尚不能作出该项科学判断。"]
        task = retrieval["question_contract"]
        if task["source_constraints"].get("unresolved_named_source"):
            sentences.append("已识别机构或来源名称，但尚未确定所指的具体文件；请使用完整书名、指南名称、版次或来源ID。其他来源不能替代所问文件。")
        elif task["specific_source_unresolved"] or any(x["reason"] == "requested_source_or_edition_unavailable" for x in retrieval["excluded"]):
            sentences.append("尚无与所要求来源、版次、章节、附录或表格一致的可核验依据；主文提及附件不等于已取得附件，其他文献不能替代指定正文或提供它的页码。")
        elif task["issues"]:
            sentences.append("尚未可靠识别整句要回答的目标；可以在“明确问题目标”中选择并确认一个目标后查询。涉及多个目标时应分别核对，不能把时间描述自动当作训练频率问题。")
        elif any("population_scope_mismatch" in x["reason"] for x in retrieval["excluded"]):
            sentences.append("已核对来源的人群范围与问题指定人群不同，不能据此称该方案已经在目标人群验证。")
    if assessment["status"] == "conflicting_evidence" and not guard:
        sentences.append("对目标主张存在相互冲突的已审证据关系；不能选择其中一项当作确定结论。")
    limits = [BOUNDARIES[x["route"]] for x in routes]
    limits.extend(limit for c in claims for limit in c["limitations"])
    if assessment["status"] == "partial_answer_support" and not guard:
        limits.append("仅部分目标或限定条件有已审关系；未覆盖的目标保持未知，当前不是完整回答。")
        sentences.append("以上只回答已明确且有依据的部分；复合目标或个人精确数字请求仍未得到支持，需要分别核对。")
    if assessment["uncovered_parts"] and not guard:
        reasons = {"display_budget_omitted_supported_part": "已有匹配依据，但未纳入本次展示；可提高展示条数后核对",
            "personal_numeric_authority_unavailable": "通用来源不能单独确定个人具体训练参数",
            "additional_target_unresolved": "尚未明确复合问题的这一目标",
            "entire_plan_not_authorized": "当前问答不生成完整个人训练计划",
            "cross_source_comparison_not_reviewed": "尚未核对指定来源或版本的完整对应比较；单篇材料不能替代对照",
            "statistical_data_and_model_required": "方法解释不能替代实际数据、预设界值和模型条件下的统计计算",
            "study_level_extraction_unreviewed": "尚未核对指定附录或表格的逐项试验、样本量和效应，通用说明不能替代原始数据",
            "nutrition_prescription_unreviewed": "当前没有核对足以支持个人营养摄入参数的来源与适用条件",
            "personal_forecast_authority_unavailable": "一般来源解释不能替代适用的个人预测模型、前瞻数据和校准",
            "no_eligible_complete_answer_relation": "尚无满足来源、范围与关系要求的完整依据"}
        sentences.extend(f"尚未回答：{p['label']}（{reasons[p['reason']]}）。" for p in assessment["uncovered_parts"])
    if not claims and not guard:
        limits.append("来源目录、文献全文取得和理论审核是独立状态；种子卡不能充当已审核证据。")
    output = {"observations": observations, "answer": "\n".join(sentences), "claims": claims,
              "limits": limits, "citations": citations, "status": guard or assessment["status"],
              "support_assessment": assessment, "related_materials": related,
              "routes": routes, "retrieval": retrieval, "source": "local_structured_template", "numeric_actions": [],
              "answer_scope": "computed_observations_and_reviewed_source_claims_not_personal_prescription",
              "private_data_policy": "caller_supplied_authorized_metrics_only_no_private_database_access"}
    output["answer_status"] = {"evidence_supported": "answered_with_support", "partial_answer_support": "partially_answered",
                               "insufficient_evidence": "missing_source_content"}.get(output["status"], output["status"])
    if not claims and any("missing_context" in x["reason"] or "unknown_applicability" in x["reason"] for x in retrieval["excluded"]):
        output["answer_status"] = "missing_context"
    output["corpus_partitions"] = sorted(context.get("corpus_roles", ["core", "research"]))
    output["evidence_bundle_hash"] = digest(dumps({k: output[k] for k in ("observations", "claims", "citations", "routes", "support_assessment")}).encode())
    if proposed_answer is not None:
        errors = validate_answer(workbench, proposed_answer, output)
        output["generation_validation"] = {"accepted": not errors, "errors": errors}
        # Display prose remains the same auditable template even if a provider validates.
    return output


def validate_answer(workbench, candidate: dict, bundle: dict) -> list[str]:
    """Closed generation contract prevents prose from smuggling numbers or causal assertions.

    A model may select/reorder approved sentences. Free-form new scientific claims need review,
    not a permissive regex that checks just a few numeral fields.
    """
    errors = []
    if not isinstance(candidate, dict):
        return ["invalid_answer_object"]
    allowed_sentences = set(bundle["answer"].splitlines()) | set(bundle["limits"])
    sentences = [x.strip() for x in str(candidate.get("answer", "")).splitlines() if x.strip()]
    if not sentences or any(s not in allowed_sentences for s in sentences):
        errors.append("unsupported_summary_sentence")
    allowed_metrics = {dumps(x) for x in bundle.get("observations", [])}
    for observation in candidate.get("observations", []):
        if dumps(observation) not in allowed_metrics:
            errors.append("metric_value_unit_direction_window_or_version_mismatch")
    allowed_claims = {dumps(x) for x in bundle.get("claims", [])}
    if any(dumps(x) not in allowed_claims for x in candidate.get("claims", [])):
        errors.append("unapproved_target_claim_or_evidence_relation")
    if "support_assessment" in candidate and candidate["support_assessment"] != bundle.get("support_assessment"):
        errors.append("target_support_assessment_changed")
    allowed_citations = {dumps(c) for c in bundle["citations"]}
    for citation in candidate.get("citations", []):
        if dumps(citation) not in allowed_citations:
            errors.append("unapproved_citation")
            continue
        theory = workbench.lib.theories.execute("SELECT status FROM theory WHERE theory_id=? AND version=?", (citation['theory_id'], citation['theory_version'])).fetchone()
        core_claim = workbench.lib.theories.execute("SELECT status FROM source_claim WHERE claim_id=? AND version=?", (citation['theory_id'], citation['theory_version'])).fetchone()
        if not (theory and theory[0] == 'approved' or core_claim and core_claim[0] == 'verified'):
            errors.append('theory_approval_no_longer_current')
        for sid in citation.get("span_ids", []):
            span = workbench.lib.span(sid)
            if not span or not workbench.lib.eligible(span)[0]:
                errors.append("stale_withdrawn_or_unavailable_citation")
    if candidate.get("numeric_actions"):
        errors.append("numeric_action_not_authorized_by_explanation_layer")
    if candidate.get("status") and candidate["status"] != bundle["status"]:
        errors.append("status_escalation")
    return sorted(set(errors))
