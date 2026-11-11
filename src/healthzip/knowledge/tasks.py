"""Small compositional question contract; concept recognition never scores evidence.

The supported vocabulary is explicit. Unknown/ambiguous targets remain unresolved;
recognized targets still require independently versioned source-claim reviews.
"""

from __future__ import annotations

import json
import re

CONCEPTS = {
    "resistance_training": ["力量", "抗阻", "练", "训练", "重复", "次数", "负重", "重量", "方案", "rir", "resistance", "repetition", "lifting", "training"],
    "device_measurement": ["设备", "温度计", "手表", "传感器", "组均", "device", "thermometer"],
    "longevity": ["寿命", "长寿", "活得更久", "longevity", "lifespan"],
    "personal_temperature": ["体温", "temperature"],
    "progression_options": ["进阶", "渐进", "加重", "增加重量", "增重", "多做", "加次数", "增加次数", "增加重复", "提高次数", "progression", "more reps", "more repetitions", "increase repetitions", "heavier"],
    "failure_necessity": ["力竭", "失败", "做不动", "failure", "exhaustion"],
    "effort_precision": ["rir", "余力", "剩余次数", "repetitions in reserve"],
    "volume": ["组量", "组数", "几组", "多少组", "volume", "sets"],
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
    compound = bool(re.search(r"两件事|分别|一方面.*另一方面|再.*(?:算|计算)|\band\s+then\b", text))
    population = context.get("population")
    if re.search(r"儿童|孩子|未成年|children|child", text) or (isinstance(context.get("age"), (int, float)) and context["age"] < 18):
        population = "children"
    elif re.search(r"患者|疾病|衰弱|康复|clinical|patient", text):
        population = "clinical"
    return {"source_constraints": source, "specific_source_unresolved": specific and not source.get("source_ids"),
            "personal_numeric_request": numeric, "compound_request": compound, "requested_population": population}


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
        return {**contract, **constraints, "resolution": "explicit_structured_task", "issues": []}
    text = re.sub(r"\bincreas(?:e|es|ed|ing)\b", "increase", question.lower())
    found = {key for key, terms in CONCEPTS.items() if any(term in text for term in terms)}
    if re.search(r"(?:每周|一周|weekly).*(?:几天|多少天|至少.*天|最低.*天)|how many days", text):
        found.add("frequency")
    subjects = found & {"resistance_training", "device_measurement"}
    # Outcomes asked about override incidental intervention words. This does not
    # infer a support relation; a matching reviewed scope/answer part is required.
    priority = ["longevity", "personal_temperature", "individual_error_bound", "capability_change",
                "failure_necessity", "effort_precision", "rest", "volume", "frequency", "progression_options"]
    outcomes = found & set(priority)
    # Intervention mentions may accompany an explicit measurement/inference
    # target. Otherwise never use an arbitrary priority to answer only one of
    # several recognized requested quantities.
    primary = outcomes & {"longevity", "personal_temperature", "individual_error_bound", "capability_change"}
    resolved = primary if primary else outcomes
    outcome = next(iter(resolved)) if len(resolved) == 1 else None
    subject = "device_measurement" if "device_measurement" in subjects else "resistance_training" if subjects else None
    issues = (["subject_unresolved"] if subject is None else []) + (["multiple_possible_outcomes"] if len(resolved) > 1 else ["outcome_unresolved"] if not resolved else [])
    relation = ("individual_inference" if outcome in {"longevity", "personal_temperature", "individual_error_bound"}
                else "inference" if outcome == "capability_change" else "necessity" if outcome == "failure_necessity"
                else "precision" if outcome == "effort_precision" else "options")
    return {"subject": subject, "outcome": outcome, "requested_relation": relation, **constraints,
            "possible_outcomes": sorted(outcomes), "issues": issues,
            "resolution": "unresolved_or_ambiguous_task" if issues else "compositional_concept_contract_v1.4.1"}


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
        matches = not task["issues"] and all(task.get(k) == definition.get(k) for k in ("subject", "outcome", "requested_relation"))
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
                         "answer_complete": definition.get("answer_complete", True) and not task["personal_numeric_request"] and not task["compound_request"],
                         "target_coverage_complete": not task["personal_numeric_request"] and not task["compound_request"],
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
