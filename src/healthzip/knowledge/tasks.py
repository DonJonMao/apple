"""Small compositional question contract; concept recognition never scores evidence.

The supported vocabulary is explicit. Unknown/ambiguous targets remain unresolved;
recognized targets still require independently versioned source-claim reviews.
"""

from __future__ import annotations

import json
import re

from .question_parts import lexical_concepts, requested_parts

CONCEPTS = {
    "resistance_training": ["力量", "抗阻", "练", "训练", "重复", "次数", "负重", "重量", "方案", "rir", "resistance", "repetition", "lifting", "training"],
    "device_measurement": ["设备", "温度计", "手表", "传感器", "组均", "device", "thermometer"],
    "longevity": ["寿命", "长寿", "活得更久", "longevity", "lifespan"],
    "personal_temperature": ["体温", "temperature"],
    "progression_options": ["进阶", "渐进", "加重", "增加重量", "增重", "多做", "加次数", "增加次数", "增加重复", "提高次数", "progression", "more reps", "more repetitions", "increase repetitions", "heavier"],
    "failure_necessity": ["力竭", "失败", "做不动", "failure", "exhaustion"],
    "effort_precision": ["rir", "余力", "剩余次数", "repetitions in reserve"],
    "volume": ["组量", "组数", "几组", "多少组", "volume"],
    "frequency": ["频率", "几天", "多少天", "frequency"],
    "rest": ["组间", "休息", "rest"],
    "capability_change": ["没进步", "没有进步", "不进步", "停滞", "平台", "没变", "一样", "相同次数", "plateau", "unchanged", "same reps"],
    "individual_error_bound": ["误差", "偏差", "error", "bias"],
}


def _ordinal(value):
    if value.isdigit():
        return str(int(value))
    digits = {char: index for index, char in enumerate("零一二三四五六七八九")}
    if value in digits:
        return str(digits[value])
    if "十" in value and value.count("十") == 1:
        tens, units = value.split("十")
        if (not tens or tens in digits) and (not units or units in digits):
            return str((digits.get(tens, 1) * 10) + digits.get(units, 0))
    return None


def request_constraints(question, context):
    text = question.lower()
    source = dict(context.get("source_constraints", {}))
    if not source.get("source_ids"):
        ids = re.findall(r"(?<![A-Za-z0-9_])(?:S\d+|CORE-[A-Z0-9-]+)(?![A-Za-z0-9_])", question)
        if ids:
            source["source_ids"] = ids
    for label, chinese, english in (("edition", "版", "edition"), ("chapter", "章", "chapter")):
        match = re.search(r"第\s*([\d零一二三四五六七八九十]+)\s*" + chinese, text)
        english_match = re.search(r"(\d+)(?:st|nd|rd|th)?\s+edition" if label == "edition" else r"chapter\s+(\d+)", text)
        if match or english_match:
            source["requested_" + label + "_number"] = _ordinal((match or english_match)[1])
        elif re.search(r"第.{1,8}" + chinese + r"|\b" + english + r"\b", text) and not source.get(label + "_id"):
            source["unresolved_" + label] = True
    if re.search(r"页码|\bpage number\b", text):
        source["requires_page_locator"] = True
    specific = bool(re.search(r"教材|教科书|textbook|第\s*[\d一二三四五六七八九十]+\s*[版章]|页码|\b(?:edition|chapter|page number)\b", text)
                    or re.search(r"(?:根据|依据|按照|按|according to)\s*(?:[A-Za-z][\w-]*|《[^》]+》)", question, re.IGNORECASE))
    numeric = bool(re.search(r"(?:我|个人|my|individual).*(?:多少|几公斤|精确|calculate|exact)", text)
                   and re.search(r"公斤|千克|重量|负荷|\bkg\b|\bload\b", text))
    numeric = numeric or bool(re.search(
        r"(?:应该|该用|能否|可不可以|可以|建议|\bshould\b|\bcan i\b).{0,20}\d+(?:\.\d+)?\s*(?:公斤|千克|磅|kg|lbs?)(?![a-z])", text))
    personal = bool(re.search(r"我|个人|\bi\b|\bmy\b|\bme\b|\bindividual\b", text))
    training_quantity = bool(re.search(r"次数|组数|组量|余力|休息|间歇|频率|天数|公斤|重量|负荷|\b(?:reps?|repetitions?|sets?|rir|rest|interval|frequency|load|weight)\b", text))
    choose_quantity = bool(re.search(r"多少|几次|几组|几天|多久|多长|最优|最好|精确|\b(?:how (?:much|many|long)|optimal|best|exact(?:ly)?)\b|\bwhich\b.{0,30}\b(?:rest|interval|duration|load|weight)\b", text))
    numeric = numeric or (personal and training_quantity and choose_quantity)
    compound = bool(re.search(r"两件事|分别|一方面.*另一方面|再.*(?:算|计算)|\band\s+then\b", text))
    comparison = bool(re.search(r"比较|对比|对照|区别|差异|变化|变了|\b(?:compar\w*|difference\w*|changed|versus|vs)\b", text)
                      and (len(set(re.findall(r"\b(?:19|20)\d{2}\b", text))) > 1
                           or re.search(r"(?:不同|两|各|旧|新).{0,5}(?:来源|版本|指南|版次)|(?:source|edition|guideline|paper)s\b", text)))
    population = context.get("population")
    if re.search(r"儿童|孩子|未成年|children|child", text) or (isinstance(context.get("age"), (int, float)) and context["age"] < 18):
        population = "children"
    elif re.search(r"患者|疾病|衰弱|康复|clinical|patient", text):
        population = "clinical"
    return {"source_constraints": source, "specific_source_unresolved": specific and not source.get("source_ids"),
            "personal_numeric_request": numeric, "compound_request": compound, "requested_population": population,
            "source_comparison_request": comparison}


def resolve_named_sources(w, question, context):
    """Resolve only actual registered names/identifiers, never infer an edition."""
    if context.get("source_constraints", {}).get("source_ids"):
        return context
    matches = set()
    name_sources = {}
    text = question.casefold()
    for row in w.lib.sources.execute("SELECT source_id,manifest_json FROM source"):
        manifest = json.loads(row["manifest_json"])
        identifiers = manifest.get("identifiers", {})
        names = [manifest.get("title"), *manifest.get("query_names", []),
                 manifest.get("doi"), identifiers.get("doi"), identifiers.get("pmcid")]
        for name in names:
            if not name:
                continue
            pattern = re.escape(str(name).casefold())
            if str(name).isascii():
                pattern = r"(?<![a-z0-9])" + pattern + r"(?![a-z0-9])"
            if re.search(pattern, text):
                matches.add(row["source_id"])
                name_sources.setdefault(str(name).casefold(), set()).add(row["source_id"])
    if matches:
        ambiguous = any(len(ids) > 1 for ids in name_sources.values())
        return {**context, "source_constraints": {**context.get("source_constraints", {}),
            "source_ids": sorted(matches), **({"unresolved_named_source": True} if ambiguous else {})}}
    return context


def source_constraints_match(w, evidence, constraints):
    if any(key.startswith("unresolved_") and value for key, value in constraints.items()):
        return False
    ids = constraints.get("source_ids", [])
    allowed = {sid for alias in ids for sid in w.lib.resolve(alias)}
    if ids and (not allowed or any(s["source_id"] not in allowed for s in evidence)):
        return False
    for field in ("edition_id", "chapter_id"):
        if constraints.get(field) is not None and any(str(s["locator"].get(field)) != str(constraints[field]) for s in evidence):
            return False
    if "requested_edition_number" in constraints and any(str(w.lib.source(s["source_id"])["manifest"].get("edition")) != constraints["requested_edition_number"] for s in evidence):
        return False
    if "requested_chapter_number" in constraints and any(str(s["locator"].get("chapter_id")) != constraints["requested_chapter_number"] for s in evidence):
        return False
    if constraints.get("requires_page_locator") and any(all(s["locator"].get(key) is None for key in ("file_page_index", "printed_page", "printed_page_label")) for s in evidence):
        return False
    return True


def parse_task(question, context=None):
    context = context or {}
    constraints = request_constraints(question, context)
    if context.get("question_contract"):
        contract = context["question_contract"]
        if not all(contract.get(k) for k in ("subject", "outcome", "requested_relation")):
            raise ValueError("question contract requires subject, outcome and requested relation")
        if contract.get("user_confirmed") is True:
            constraints.update(personal_numeric_request=False, compound_request=False)
        part = {**contract, "part_id": contract["outcome"], "label": contract["outcome"]}
        scoped = requested_parts(question, {contract["subject"], contract["outcome"]}, context)
        parts = [{**part, **{k: v for k, v in p.items() if k in {"part_id", "label", "requested_goal"}}}
                 for p in scoped if p["outcome"] == contract["outcome"]] or [part]
        if constraints["personal_numeric_request"]:
            parts.append({"part_id": "personal_numeric_request", "label": "个人具体训练参数", "reason": "personal_numeric_authority_unavailable"})
        elif constraints["compound_request"]:
            parts.append({"part_id": "unresolved_compound_request", "label": "复合问题的其他目标", "reason": "additional_target_unresolved"})
        if constraints["source_comparison_request"]:
            parts.append({"part_id": "source_comparison", "label": "指定来源或版本之间的比较", "reason": "cross_source_comparison_not_reviewed"})
        return {**contract, **constraints, "required_answer_parts": parts, "resolution": "explicit_structured_task", "issues": []}
    found = lexical_concepts(question, CONCEPTS)
    parts = requested_parts(question, found, context)
    outcomes = {p["outcome"] for p in parts}
    subject = parts[0]["subject"] if parts else None
    outcome = parts[0]["outcome"] if len(parts) == 1 else None
    relation = parts[0]["requested_relation"] if len(parts) == 1 else None
    issues = (["subject_unresolved"] if subject is None else []) + (["multiple_possible_outcomes"] if len(parts) > 1 else ["outcome_unresolved"] if not parts else [])
    if constraints["personal_numeric_request"]:
        parts.append({"part_id": "personal_numeric_request", "label": "个人具体训练参数", "reason": "personal_numeric_authority_unavailable"})
    elif constraints["compound_request"] and len(parts) < 2:
        parts.append({"part_id": "unresolved_compound_request", "label": "复合问题的其他目标", "reason": "additional_target_unresolved"})
    if re.search(r"完整.*(?:计划|方案)|(?:full|complete|entire)\s+(?:training\s+)?(?:plan|program)", question.lower()):
        parts.append({"part_id": "entire_plan", "label": "完整个人训练计划", "reason": "entire_plan_not_authorized"})
    if constraints["source_comparison_request"]:
        parts.append({"part_id": "source_comparison", "label": "指定来源或版本之间的比较", "reason": "cross_source_comparison_not_reviewed"})
    return {"subject": subject, "outcome": outcome, "requested_relation": relation, **constraints,
            "possible_outcomes": sorted(outcomes), "issues": issues, "required_answer_parts": parts,
            "resolution": "compositional_answer_parts_v1.4.2" if parts else "unresolved_or_ambiguous_task"}


def core_candidates(w, question, context, roles):
    from .core import _claim
    task = parse_task(question, context)
    candidates, excluded = [], []
    for row in w.lib.theories.execute("SELECT * FROM source_claim WHERE status='verified' ORDER BY claim_id,version"):
        payload = json.loads(row["payload_json"])
        definition = payload.get("answer_task", {})
        if not definition:
            continue
        try:
            claim, review, evidence = _claim(w, {"claim_id": row["claim_id"], "version": row["version"]})
        except ValueError as exc:
            excluded.append({"theory_id": row["claim_id"], "reason": str(exc)})
            continue
        if any(not set(s["corpus_roles"]) & roles for s in evidence):
            continue
        goals = set(claim["scope"].get("applicable_goals", []))
        if claim["scope"].get("goal"):
            goals.add(claim["scope"]["goal"])
        matching_parts = [part for part in task["required_answer_parts"]
                          if all(part.get(k) is not None and part.get(k) == definition.get(k)
                                 for k in ("subject", "outcome", "requested_relation"))
                          and (not part.get("requested_goal") or part["requested_goal"] in goals)]
        matches = bool(matching_parts)
        if task["specific_source_unresolved"] or not source_constraints_match(w, evidence, task["source_constraints"]):
            excluded.append({"theory_id": row["claim_id"], "reason": "requested_source_or_edition_unavailable"})
            matches = False
        requested_population = task.get("requested_population")
        source_population = claim["scope"].get("population")
        population_matches = requested_population is None or requested_population == source_population or (source_population == "adults" and requested_population == "healthy_adults")
        if matches and not population_matches:
            excluded.append({"theory_id": row["claim_id"], "reason": "question_population_scope_mismatch"})
            matches = False
        bindings = []
        target = {"proposition": json.dumps({k: definition[k] for k in ("subject", "outcome", "requested_relation")}, sort_keys=True), "scope": claim["scope"]}
        if matches:
            bindings = [{"question": question, "target_claim": target,
                         "relation": definition.get("evidence_relation", "supports"),
                         "answer_complete": definition.get("answer_complete", True),
                         "target_coverage_complete": definition.get("answer_complete", True),
                         "requested_part_ids": [p["part_id"] for p in matching_parts],
                         "rationale": review["rationale"], "target_resolution": task["resolution"]}]
        parts = [{"text": p["text"], "span_ids": p["span_ids"], "support_rationale": review["rationale"],
                  "limitations": claim["limitations"], "answer_bindings": bindings} for p in definition["answer_parts"]]
        candidates.append({"theory_id": row["claim_id"], "theory_version": row["version"],
            "card": {"title": claim["statement"], "domains": definition.get("routes", ["progression"]), "kind": "source_claim"},
            "review": {"claims": parts, "evidence_links": claim["evidence_links"], "applicability": {"required": claim.get("conditions", [])},
                       "reviewer_kind": review["reviewer_kind"], "authority": "explanation_only"},
            "spans": [w.lib.span(x["span_id"]) for x in evidence], "exact_reviewed_question": bool(matches),
            "corpus_roles": sorted({r for x in evidence for r in x["corpus_roles"]}), "resolved_task": task})
    return candidates, excluded
