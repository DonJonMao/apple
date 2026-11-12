"""Small compositional question contract; concept recognition never scores evidence.

The supported vocabulary is explicit. Unknown/ambiguous targets remain unresolved;
recognized targets still require independently versioned source-claim reviews.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

from .question_parts import covariance_method_context, lexical_concepts, requested_parts

CONCEPTS = {
    "resistance_training": ["力量", "抗阻", "练", "训练", "重复", "次数", "负重", "重量", "方案", "身体活动", "运动", "锻炼", "rir", "resistance", "repetition", "lifting", "training", "exercise", "workout", "physical activity"],
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

ENGLISH_ORDINALS = {name: str(index) for index, name in enumerate(
    ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
     "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth", "twentieth"), 1)}
CHAPTER_REFERENCE = r"第\s*([\d零一二三四五六七八九十]+)\s*章|chapter\s+(\d+)"


def _ordinal(value):
    if value in ENGLISH_ORDINALS:
        return ENGLISH_ORDINALS[value]
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
    semantic = _semantic_question(question, context).lower()
    kind = _document_kind(semantic)
    if kind and not context.get("source_document_kind_resolved") and not source.get("document_kind"):
        source["document_kind"] = kind
    if not source.get("source_ids"):
        ids = re.findall(r"(?<![A-Za-z0-9_])(?:S\d+|CORE-[A-Z0-9-]+)(?![A-Za-z0-9_])", question)
        if ids:
            source["source_ids"] = ids
    for label, chinese, english in (("edition", "版", "edition"), ("chapter", "章", "chapter")):
        if label == "chapter":
            numbers = {_ordinal(value) for groups in re.findall(CHAPTER_REFERENCE, text)
                       for value in groups if value}
            if len(numbers) > 1 and None not in numbers:
                source["requested_chapter_numbers"] = sorted(numbers, key=int)
                source.pop("requested_chapter_number", None)
                continue
        match = re.search(r"第\s*([\d零一二三四五六七八九十]+)\s*" + chinese, text)
        english_match = re.search(r"(\d+|" + "|".join(ENGLISH_ORDINALS) + r")(?:st|nd|rd|th)?\s+edition" if label == "edition" else r"chapter\s+(\d+)", text)
        if match or english_match:
            source["requested_" + label + "_number"] = _ordinal((match or english_match)[1])
        elif re.search(r"第[^版页节章。？！;；]{1,8}" + chinese + r"|\b" + english + r"\b", text) and not source.get(label + "_id"):
            source["unresolved_" + label] = True
    for kind, pattern in {
        "appendix": r"(?:附录|\b(?:supplemental\s+|supplementary\s+)?appendix\s+)\s*([\d零一二三四五六七八九十]+|[a-z]\b)",
        "table": r"(?:表\s*|\btable\s+)([\d零一二三四五六七八九十]+)",
    }.items():
        numbers = [(_ordinal(value) or value) for value in re.findall(pattern, text)]
        if numbers:
            source["requested_" + kind + "_numbers"] = sorted(set(numbers))
    if re.search(r"页码|\bpage number\b", text):
        source["requires_page_locator"] = True
    page_pattern = (r"(?:(pdf|文件)\s*)?第\s*([\d零一二三四五六七八九十]+)"
                    r"(?:\s*[-–]\s*([\d零一二三四五六七八九十]+))?\s*页|"
                    r"(?:(pdf|file)\s+)?(?:pages?|pp?\.)\s*(\d+)(?:\s*[-–]\s*(\d+))?")
    page_matches = list(re.finditer(page_pattern, text))
    for page in page_matches:
        raw_start, raw_end = page[2] or page[5], page[3] or page[6]
        start, end = _ordinal(raw_start), _ordinal(raw_end or raw_start)
        file_page = bool(page[1] or page[4])
        if start is None or end is None or int(start) > int(end) or (file_page and int(start) < 1):
            source["unresolved_page"] = True
            continue
        bounds = [int(start) - int(file_page), int(end) - int(file_page)]
        source.setdefault("requested_file_page_ranges" if file_page else "requested_printed_page_ranges", []).append(bounds)
    intro = re.search(r"(?:根据|依据|按照|按|according to|as reported by)\s*(?:(?:the|this|these|that|those)\s+)?([A-Za-z][\w-]*|《[^》]+》)", question, re.IGNORECASE)
    generic_intros = {"the", "this", "these", "that", "those", "current", "available", "existing", "general",
                      "published", "scientific", "evidence", "research", "studies", "literature", "data", "review", "guidance", "guidelines", "principles"}
    named_intro = bool(intro and intro[1].casefold() not in generic_intros)
    specific = bool(re.search(r"教材|教科书|textbook|第\s*[\d一二三四五六七八九十]+\s*[版章]|页码|\b(?:edition|chapter|page number)\b", text) or named_intro)
    # A pronoun belongs to its request clause, not every question in the input.
    clauses = re.split(r"[。？！?！;；]|(?<!\d)\.(?!\d)|\b(?:and then|then)\b|然后|再(?=(?:给我|帮我|为我)?(?:计算|算出|求出|选择|列出))", semantic)
    numeric = False
    for clause in clauses:
        personal = bool(re.search(r"我|个人|\bi\b|\bmy\b|\bme\b|\bindividual\b", clause))
        quantity = bool(re.search(r"次数|组数|组量|余力|休息|间歇|频率|天数|公斤|重量|负荷|配重|负重|秒数|时长|速度|配速|跑.{0,4}(?:多久|多快|多远)|(?<![a-z])rir\s*\d*(?![a-z])|\b(?:reps?|repetitions?|sets?|rest|interval|frequency|loads?|weights?|seconds?|minutes?|pace|speed|duration|distance)\b", clause))
        choose = bool(re.search(r"多少|几次|几组|几天|多久|多长|多快|多远|最优|最好|恰好|精确|\b(?:how (?:much|many|long|fast|far)|optimal|best|exact(?:ly)?)\b|\bwhich\b.{0,30}\b(?:rest|interval|duration|load|weight)\b", clause))
        choose |= bool(re.search(r"最佳|固定", clause) and re.search(
            r"\d+(?:\.\d+)?\s*(?:rir|次|组|秒|分钟|公斤|千克|kg)\b|(?<![a-z])rir\s*\d+", clause))
        numeric |= personal and quantity and choose
        numeric |= bool(re.search(r"(?:应该|该用|能否|可不可以|可以|建议|\bshould\b|\bcan i\b).{0,20}\d+(?:\.\d+)?\s*(?:公斤|千克|磅|kg|lbs?)(?![a-z])", clause))
    compound = bool(re.search(r"两件事|分别(?=.{0,8}(?:回答|解释|说明|讨论|计算|给出))|一方面.*另一方面|(?:再|然后)\s*(?:给我|帮我|为我)?\s*(?:计算|算出|求出|列出|选择)|\band\s+then\b", semantic))
    comparison = bool(re.search(r"比较|对比|对照|区别|差异|变化|变了|\b(?:compar\w*|difference\w*|changed|versus|vs)\b", text)
                      and (len(set(re.findall(r"\b(?:19|20)\d{2}\b", text))) > 1
                           or re.search(r"(?:不同|两|各|旧|新).{0,5}(?:来源|版本|指南|版次)|(?:source|edition|guideline|paper)s\b", text)))
    # In a method-suitability question, 计算方法/公式/etc. names the object
    # being discussed; it is not itself an instruction to execute that method.
    calculation_action = r"计算(?!(?:的)?(?:方法|方式|公式|过程|步骤|示例|框架|原理))|算出|求出|\b(?:calculate|compute|estimate)\b"
    statistical_calculation = bool(re.search(calculation_action, text)
                                   and re.search(r"统计量|p值|等效|置信区间|斜率|协方差|标准误|成功概率|误判率|错误率|\b(?:statistic|equivalence|p-value|confidence interval|slope|covariance|standard errors?)\b", text))
    # A concrete personal result may be requested without repeating 'compute',
    # including after a separate question about the method. Definitions and
    # explanations of that result remain method questions.
    statistical_calculation |= bool(re.search(
        r"(?:给(?:出)?|提供|报告|确定)(?:给)?(?:我|个人)的?(?!解释|说明|介绍|讨论)"
        r"(?:本次|这次|训练|回归|数据|记录|结果|的)*"
        r"(?:统计量|p值|置信区间|斜率|协方差|标准误)"
        r"(?!(?:的)?(?:计算|定义|含义|意义|原理|方法|公式|步骤|示例|条件|假设|范围|是否|能否))", text))
    statistical_calculation |= bool(covariance_method_context(text, context.get("named_source_task_subjects"))
        and re.search(r"我|个人|\b(?:my|me|individual)\b", text)
        and re.search(r"选择|设定|决定|确定|\b(?:choose|select|set|pick|determine)\b", text)
        and re.search(r"带宽|滞后|核函数|预白化|\b(?:bandwidth|lags?|kernel|prewhitening)\b", text))
    personal_bound_action = bool(re.search(
        r"(?:帮我|为我|替我|给(?:出)?我|告诉我|我的.{0,12}(?:数据|记录|结果))|"
        r"\b(?:for me|for my|give me|tell me|my (?:data|records)|(?:want you to|could you) (?:choose|select|set|give|provide))\b", text))
    statistical_calculation |= bool(
        personal_bound_action
        and re.search(r"判定|判断|选择|设定|确定|给出|提供|\b(?:decide|determine|choose|select|give|provide)\b", text)
        and re.search(r"等效界|等效范围|停滞.{0,8}概率|\b(?:equivalence (?:bounds?|margins?)|probability)\b", text))
    statistical_calculation |= bool(re.search(r"我|个人|\b(?:my|me|individual)\b", text)
        and re.search(r"给出|告诉|提供|" + calculation_action + r"|\b(?:give|provide)\b", text)
        and re.search(r"误判率|错误率|成功概率|\b(?:error rate|success probability)\b", text))
    population = context.get("population")
    age = context.get("age")
    if not isinstance(age, (int, float)) or isinstance(age, bool) or not math.isfinite(age):
        age = None
    stated_age = re.search(r"(?<![0-9])(\d+)\s*(?:岁|[- ]years?[- ]old\b)", text)
    if age is None and stated_age:
        age = int(stated_age[1])
    if re.search(r"儿童|孩子|未成年|children|child", text) or (isinstance(age, (int, float)) and not isinstance(age, bool) and age < 18):
        population = "children"
    elif re.search(r"患者|疾病|衰弱|康复|clinical|patient", text):
        population = "clinical"
    extraction = bool(re.search(r"列出|逐项|提取|\b(?:list|extract|enumerate)\b", semantic)
                      and re.search(r"样本量|效应|原始试验|原始研究|\b(?:sample sizes?|effects?|trials?|studies)\b", semantic))
    nutrition = bool(re.search(r"蛋白质|营养|饮食|\b(?:protein|nutrition|diet)\b", semantic)
                     and re.search(r"多少|应吃|摄入|处方|\b(?:how much|intake|prescri\w*|grams?)\b", semantic))
    forecast = any(
        re.search(r"我|个人|\b(?:i|my|me|individual)\b", clause)
        and re.search(r"多少|几公斤|多长|多大|\b(?:how (?:much|many|long)|exact(?:ly)?)\b", clause)
        and re.search(r"预测|未来|今后|下周|下个月|算出.{0,24}(?:会|将)|\b(?:predict\w*|forecast\w*|will|next|future)\b", clause)
        for clause in clauses
    )
    return {"source_constraints": source, "specific_source_unresolved": specific and not (source.get("source_ids") or source.get("issuer_source_ids")),
            "personal_numeric_request": numeric, "compound_request": compound, "requested_population": population,
            "source_comparison_request": comparison, "statistical_calculation_request": statistical_calculation,
            "requested_age": age, "study_detail_request": extraction, "nutrition_prescription_request": nutrition,
            "personal_forecast_request": bool(forecast)}


def _name_pattern(name):
    # Spaces may occur between lexical tokens, including Latin/Chinese joins;
    # never split an ASCII identifier into arbitrary characters.
    tokens = re.findall(r"[a-z0-9_]+|[^\s]", str(name).lower())
    pattern = r"\s*".join(re.escape(token) for token in tokens)
    if tokens and re.match(r"[a-z0-9]", tokens[0]):
        pattern = r"(?<![a-z0-9])" + pattern
    if tokens and re.search(r"[a-z0-9]$", tokens[-1]):
        pattern += r"(?![a-z0-9])"
    return pattern


def _author_query_names(manifest):
    """Derive bibliographic author tokens; they still need an author-reference phrase.

    The citation fallback accepts only the conventional surname + initials prefix,
    never arbitrary words from titles. Shared surnames remain ambiguous across works.
    """
    authors = manifest.get("authors") or []
    if isinstance(authors, str):
        authors = re.split(r";|\band\b|,", authors)
    names = set()
    for author in authors:
        if isinstance(author, dict):
            given, family = author.get("given", ""), author.get("family", "")
            author = " ".join(x for x in (given, family) if x)
        tokens = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'-]*", str(author))
        if len(tokens) >= 2:
            names.add(" ".join(tokens))
            # Full names usually end in the surname; initials-first bibliographic
            # forms instead put the family name before the final initials.
            family = tokens[0] if re.fullmatch(r"[A-Z]{1,4}", tokens[-1]) else tokens[-1]
            names.add(family)
    prefix = manifest.get("citation", "").split(". ", 1)[0]
    for entry in prefix.split(","):
        match = re.fullmatch(r"\s*([A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'-]+)\s+[A-Z]{1,4}\s*", entry)
        if match:
            names.add(match[1])
    return sorted(names)


def _author_reference(text, start, end):
    before, after = text[max(0, start - 40):start], text[end:end + 40]
    return bool(re.search(r"(?:根据|按照|依据|按|结合)\s*$|\b(?:according to|by|from)\s+$", before)
                or re.match(r"\s*(?:等|的?(?:文章|论文|研究)|关于|(?:et al\.?|[’']s\s+(?:paper|article|study)|\(?\d{4}))", after))


def _semantic_question(question, context):
    chars = list(question)
    for start, end in context.get("recognized_source_name_spans", []):
        chars[start:end] = [" "] * (end - start)
    return "".join(chars)


def _document_kind(text):
    # Lack of a personal copy is background, not a request to replace an
    # explicitly named source with a textbook. Retain positive genre requests.
    text = re.sub(r"(?:我|我们)?(?:没有|没买|没带|缺少|暂无|还没买)(?:任何|这本|那本|一本|可用的|授权的)?(?:教材|教科书)", "", text)
    text = re.sub(r"\b(?:i|we)\s+(?:do\s+not|don't|don’t)\s+(?:have|own)\s+(?:(?:a|any|the)\s+)?textbooks?\b", "", text)
    if re.search(r"教材|教科书|\btextbooks?\b", text):
        return "textbook"
    if re.search(r"指南|指导文件|\b(?:guidelines?|guidance|position stand)\b", text):
        return "guideline"
    return None


@lru_cache(maxsize=1)
def _registered_document_kinds():
    sources = json.loads((Path(__file__).parent / "data/core_sources.json").read_text())["sources"]
    return {entry.get("canonical_source_id", entry["source_id"]): entry.get("document_kind") for entry in sources}


def _source_document_kind(w, source_id):
    # Upgraded read-only libraries may predate this bibliographic field. Use
    # the exact registered identity, never the issuer/authority as a book type.
    return w.lib.source(source_id)["manifest"].get("document_kind") or _registered_document_kinds().get(source_id)


def _allowed_source_ids(w, constraints):
    ids = constraints.get("source_ids") or constraints.get("issuer_source_ids", [])
    allowed = {sid for alias in ids for sid in w.lib.resolve(alias)}
    if constraints.get("document_kind"):
        allowed = {sid for sid in allowed if _source_document_kind(w, sid) == constraints["document_kind"]}
    return allowed


def resolve_named_sources(w, question, context, release_id=None):
    """Resolve only actual registered names/identifiers, never infer an edition."""
    matches = set()
    name_sources, issuer_mentions = {}, {}
    spans, issuer_spans, chapters = [], [], set()
    text = question.lower()
    for row in w.lib.sources.execute("SELECT source_id,manifest_json FROM source"):
        manifest = json.loads(row["manifest_json"])
        identifiers = manifest.get("identifiers", {})
        names = [row["source_id"], manifest.get("title"), *manifest.get("query_names", []),
                 manifest.get("doi"), identifiers.get("doi"), identifiers.get("pmcid")]
        author_names = _author_query_names(manifest)
        for issuer in [manifest.get("issuing_body"), *manifest.get("query_issuer_names", [])]:
            occurrences = list(re.finditer(_name_pattern(issuer), text)) if issuer else []
            if occurrences:
                issuer_mentions.setdefault(issuer, set()).add(row["source_id"])
                issuer_spans.extend(m.span() for m in occurrences)
        for name in names:
            if not name:
                continue
            occurrences = list(re.finditer(_name_pattern(name), text))
            if occurrences:
                matches.add(row["source_id"])
                name_sources.setdefault(str(name).casefold(), set()).add(row["source_id"])
                spans.extend(m.span() for m in occurrences)
        for name in author_names:
            occurrences = [m for m in re.finditer(_name_pattern(name), text)
                           if _author_reference(text, m.start(), m.end())]
            if occurrences:
                matches.add(row["source_id"])
                name_sources.setdefault(str(name).casefold(), set()).add(row["source_id"])
                spans.extend(m.span() for m in occurrences)
        if row["source_id"] in matches:
            for chapter, names in manifest.get("chapter_query_names", {}).items():
                if any(re.search(_name_pattern(name), text) for name in names):
                    chapters.add(chapter)
    existing = context.get("source_constraints", {})
    supplied = {sid for alias in existing.get("source_ids", []) for sid in w.lib.resolve(alias)}
    if matches or supplied or issuer_mentions:
        issuer_only = bool(issuer_mentions) and not (matches or supplied)
        ambiguous = (any(len(ids) > 1 for ids in name_sources.values())
                     or (not issuer_only and any(not ids & (matches | supplied) for ids in issuer_mentions.values())))
        semantic = _semantic_question(question, {"recognized_source_name_spans": spans}).lower()
        # Bind type words to clauses that actually name the requested source.
        # A later background statement about owning a book cannot retarget it.
        references = spans + issuer_spans
        genre = r"(?:教材|教科书|指南|指导文件|\b(?:textbooks?|guidelines?|guidance|position stand)\b)"
        named_clauses = [semantic[m.start():m.end()] for m in re.finditer(r"[^,，。;；!?！？]+", question)
                         if any(m.start() <= start < m.end() for start, _ in references)
                         or re.search(r"(?:根据|依据|按照|按|用|从|采用|\b(?:from|in|under|according to|use|using)\b).{0,35}" + genre,
                                      semantic[m.start():m.end()])]
        kind = existing.get("document_kind") or _document_kind(" ".join(named_clauses) if references else semantic)
        issuer_ids = sorted({sid for ids in issuer_mentions.values() for sid in ids})
        return _source_subject_context(w, {**context, "recognized_source_name_spans": sorted(set(spans)), "source_document_kind_resolved": True,
            "source_constraints": {**existing, "source_ids": existing.get("source_ids") or sorted(matches),
            **({"issuer_source_ids": issuer_ids, "source_resolution": "issuer_scope_not_document_identity"} if issuer_only else {}),
            **({"document_kind": kind} if kind else {}),
            **({"chapter_id": next(iter(chapters))} if len(chapters) == 1 and not existing.get("chapter_id") else {}),
            **({"unresolved_chapter": True} if len(chapters) > 1 else {}),
            **({"unresolved_named_source": True} if ambiguous else {})}}, release_id)
    return context


def _source_subject_context(w, context, release_id=None):
    """A named work supplies domain context only where its reviewed tasks agree.

    This does not activate a claim: current rights, release membership, source
    status and scope are still checked by retrieval for every answer binding.
    """
    constraints = context["source_constraints"]
    if constraints.get("unresolved_named_source"):
        return context
    allowed = _allowed_source_ids(w, constraints)
    frozen = None
    if release_id is not None:
        release = w.lib.theories.execute("SELECT manifest_json FROM core_release WHERE release_id=?", (release_id,)).fetchone()
        frozen = {(r["claim_id"], r["version"]) for r in json.loads(release[0])["claims"]} if release else set()
    subjects, goals = {}, {}
    for row in w.lib.theories.execute("SELECT claim_id,version,payload_json FROM source_claim WHERE status='verified'"):
        if frozen is not None and (row["claim_id"], row["version"]) not in frozen:
            continue
        claim = json.loads(row["payload_json"])
        task = claim.get("answer_task", {})
        sources = {link["source_id"] for link in claim.get("evidence_links", [])}
        if sources and sources <= allowed and task.get("subject") and task.get("outcome"):
            subjects.setdefault(task["outcome"], set()).add(task["subject"])
            scope = claim.get("scope", {})
            declared_goals = scope.get("applicable_goals", []) + ([scope["goal"]] if scope.get("goal") else [])
            goals.setdefault(task["outcome"], set()).update(declared_goals)
    return {**context, "named_source_task_subjects": {key: next(iter(values)) for key, values in subjects.items() if len(values) == 1},
            "named_source_task_goals": {key: sorted(values) for key, values in goals.items() if values}}


def source_constraints_match(w, evidence, constraints):
    if any(key.startswith("unresolved_") and value for key, value in constraints.items()):
        return False
    ids = constraints.get("source_ids") or constraints.get("issuer_source_ids", [])
    allowed = _allowed_source_ids(w, constraints)
    if ids and (not allowed or any(s["source_id"] not in allowed for s in evidence)):
        return False
    if constraints.get("document_kind") and any(_source_document_kind(w, s["source_id"]) != constraints["document_kind"] for s in evidence):
        return False
    for field in ("edition_id", "chapter_id"):
        if constraints.get(field) is not None and any(str(s["locator"].get(field)) != str(constraints[field]) for s in evidence):
            return False
    if "requested_edition_number" in constraints and any(str(w.lib.source(s["source_id"])["manifest"].get("edition")) != constraints["requested_edition_number"] for s in evidence):
        return False
    if "requested_chapter_number" in constraints and any(str(s["locator"].get("chapter_id")) != constraints["requested_chapter_number"] for s in evidence):
        return False
    if "requested_chapter_numbers" in constraints and any(str(s["locator"].get("chapter_id")) not in constraints["requested_chapter_numbers"] for s in evidence):
        return False
    for kind in ("printed", "file"):
        ranges = constraints.get("requested_" + kind + "_page_ranges", [])
        for span in evidence if ranges else []:
            locator = span["locator"]
            page = locator.get("file_page_index") if kind == "file" else locator.get("printed_page", locator.get("printed_page_label"))
            if isinstance(page, bool) or page is None or not str(page).isdigit() or not any(a <= int(page) <= b for a, b in ranges):
                return False
    for kind in ("appendix", "table"):
        requested = constraints.get("requested_" + kind + "_numbers")
        if requested:
            actual = set()
            for span in evidence:
                locator = span["locator"]
                number = locator.get(kind + "_id")
                if number is None and str(locator.get("chapter_id", "")).startswith(kind + ":"):
                    number = str(locator["chapter_id"]).split(":", 1)[1]
                if number is None:
                    return False
                actual.add(str(number))
            if actual != set(requested):
                return False
    if constraints.get("requires_page_locator") and any(all(s["locator"].get(key) is None for key in ("file_page_index", "printed_page", "printed_page_label")) for s in evidence):
        return False
    return True


def requested_material(w, task, roles):
    """Check actual eligible fulltext separately from reviewed answer relations.

    A matching span proves some material at the requested location is present;
    it never certifies the complete book, page range or requested proposition.
    """
    constraints = task["source_constraints"]
    if task["specific_source_unresolved"] or constraints.get("unresolved_named_source"):
        return {"status": "unresolved_source", "matching_span_ids": []}
    if not constraints:
        return {"status": "not_requested", "matching_span_ids": []}
    ids = constraints.get("source_ids") or constraints.get("issuer_source_ids")
    allowed = _allowed_source_ids(w, constraints) if ids else None
    matching, partition_excluded, components = [], False, {}
    for row in w.lib.sources.execute("SELECT s.span_id,v.source_id FROM span s JOIN version v ON v.version_id=s.version_id WHERE v.material_type='fulltext'"):
        if allowed is not None and row["source_id"] not in allowed:
            continue
        span = w.lib.span(row["span_id"])
        evidence = [{"source_id": span["source_id"], "locator": json.loads(span["locator_json"])}]
        local_constraints = dict(constraints)
        for kind in ("appendix", "table", "chapter"):
            key = "requested_" + kind + "_numbers"
            if key not in constraints:
                continue
            locator = evidence[0]["locator"]
            number = locator.get(kind + "_id")
            if number is None and str(locator.get("chapter_id", "")).startswith(kind + ":"):
                number = str(locator["chapter_id"]).split(":", 1)[1]
            if str(number) in constraints[key]:
                local_constraints[key] = [str(number)]
        if not source_constraints_match(w, evidence, local_constraints) or not w.lib.eligible(span, "fulltext")[0]:
            continue
        if not set(w.lib.source(span["source_id"])["manifest"].get("corpus_roles", ["research"])) & roles:
            partition_excluded = True
            continue
        matching.append(span["span_id"])
        for kind in ("appendix", "table", "chapter"):
            components.setdefault(kind, set()).update(local_constraints.get("requested_" + kind + "_numbers", []))
    missing = {kind: sorted(set(constraints["requested_" + kind + "_numbers"]) - components.get(kind, set()))
               for kind in ("appendix", "table", "chapter") if constraints.get("requested_" + kind + "_numbers")}
    missing = {kind: numbers for kind, numbers in missing.items() if numbers}
    return {"status": ("partially_available" if missing else "available") if matching else "partition_excluded" if partition_excluded else "unavailable",
            "matching_span_ids": matching, "missing_components": missing, "coverage": "matching_spans_only_not_complete_document_or_answer"}


def _chapter_parts(question, parts, context, constraints):
    """Bind explicit chapter references to their local targets, never just an OR.

    A repeated target in different chapters needs evidence for each chapter.
    When the grammar leaves the binding unclear, retain every requested
    chapter instead of silently declaring one chapter sufficient.
    """
    chapters = constraints.get("requested_chapter_numbers", [])
    if len(chapters) < 2:
        return parts
    assignments = {}
    for clause in re.split(r"[。？！!?;；,，]|(?<!\d)\.(?!\d)", question.lower()):
        local_chapters = {_ordinal(value) for groups in re.findall(CHAPTER_REFERENCE, clause)
                          for value in groups if value} - {None}
        if not local_chapters:
            continue
        for local in requested_parts(clause, lexical_concepts(clause, CONCEPTS, context), context):
            assignments.setdefault(local["outcome"], set()).update(local_chapters)
    scoped = []
    for part in parts:
        if not part.get("outcome"):
            scoped.append(part)
            continue
        selected = sorted(assignments.get(part["outcome"], set(chapters)), key=int)
        for chapter in selected:
            scoped.append({**part, "source_constraints": {"requested_chapter_number": chapter},
                           "part_id": part["part_id"] + (":chapter:" + chapter if len(selected) > 1 else ""),
                           "label": part["label"] + "（第" + chapter + "章）"})
    return scoped


def _part_source_matches(w, evidence, definition, constraints):
    if not constraints:
        return True
    # A qualifying comparison to another requested chapter is not itself an
    # answer from that chapter. Require a directly supporting answer block.
    direct = [answer for answer in definition["answer_parts"]
              if answer.get("evidence_relation", definition.get("evidence_relation", "supports")) in {"supports", "refutes"}]
    # A wholly qualified answer can itself be the reviewed scope statement;
    # mixed contracts must anchor on their direct blocks, regardless of default.
    for answer in direct or definition["answer_parts"]:
        spans = [span for span in evidence if span["span_id"] in answer["span_ids"]]
        if spans and source_constraints_match(w, spans, constraints):
            return True
    return False


def parse_task(question, context=None):
    context = context or {}
    constraints = request_constraints(question, context)
    semantic = _semantic_question(question, context)
    extra_parts = []
    if constraints["study_detail_request"]:
        extra_parts.append({"part_id": "study_details", "label": "附录或表格中的逐项研究数据", "reason": "study_level_extraction_unreviewed"})
    if constraints["nutrition_prescription_request"]:
        extra_parts.append({"part_id": "nutrition_prescription", "label": "个人营养摄入参数", "reason": "nutrition_prescription_unreviewed"})
    if constraints["personal_forecast_request"]:
        extra_parts.append({"part_id": "personal_forecast", "label": "个人未来变化的定量预测", "reason": "personal_forecast_authority_unavailable"})
    if context.get("question_contract"):
        contract = context["question_contract"]
        if not all(contract.get(k) for k in ("subject", "outcome", "requested_relation")):
            raise ValueError("question contract requires subject, outcome and requested relation")
        if contract.get("user_confirmed") is True:
            constraints.update(personal_numeric_request=False, compound_request=False)
            # The visible confirmation explicitly narrows this query to the
            # selected target. Source and population constraints still apply.
            extra_parts = []
        part = {**contract, "part_id": contract["outcome"], "label": contract["outcome"]}
        scoped = requested_parts(semantic, {contract["subject"], contract["outcome"]}, context)
        parts = [{**part, **{k: v for k, v in p.items() if k in {"part_id", "label", "requested_goal"}}}
                 for p in scoped if p["outcome"] == contract["outcome"]] or [part]
        parts = _chapter_parts(semantic, parts, context, constraints["source_constraints"])
        if constraints["personal_numeric_request"]:
            parts.append({"part_id": "personal_numeric_request", "label": "个人具体训练参数", "reason": "personal_numeric_authority_unavailable"})
        elif constraints["compound_request"]:
            parts.append({"part_id": "unresolved_compound_request", "label": "复合问题的其他目标", "reason": "additional_target_unresolved"})
        if constraints["source_comparison_request"] and contract.get("user_confirmed") is not True:
            parts.append({"part_id": "source_comparison", "label": "指定来源或版本之间的比较", "reason": "cross_source_comparison_not_reviewed"})
        if constraints["statistical_calculation_request"] and contract.get("user_confirmed") is not True:
            parts.append({"part_id": "statistical_calculation", "label": "具体数据的统计计算", "reason": "statistical_data_and_model_required"})
        return {**contract, **constraints, "required_answer_parts": parts + extra_parts, "resolution": "explicit_structured_task", "issues": []}
    found = lexical_concepts(semantic, CONCEPTS, context)
    parts = requested_parts(semantic, found, context)
    parts = _chapter_parts(semantic, parts, context, constraints["source_constraints"])
    outcomes = {p["outcome"] for p in parts}
    subject = parts[0]["subject"] if parts else None
    outcome = parts[0]["outcome"] if len(parts) == 1 else None
    relation = parts[0]["requested_relation"] if len(parts) == 1 else None
    issues = (["subject_unresolved"] if subject is None else []) + (["multiple_possible_outcomes"] if len(parts) > 1 else ["outcome_unresolved"] if not parts else [])
    if constraints["personal_numeric_request"]:
        parts.append({"part_id": "personal_numeric_request", "label": "个人具体训练参数", "reason": "personal_numeric_authority_unavailable"})
    elif constraints["compound_request"] and len(parts) < 2:
        parts.append({"part_id": "unresolved_compound_request", "label": "复合问题的其他目标", "reason": "additional_target_unresolved"})
    if re.search(r"(?:制定|设计|生成|安排|写|给我).{0,16}(?:完整|整个|全套).{0,12}(?:计划|方案)|(?:完整|整个|全套).{0,12}(?:计划|方案).{0,12}(?:制定|设计|生成)|\b(?:write|make|build|design|generate|create|give)\b.{0,24}\b(?:full|complete|entire)\s+(?:training\s+)?(?:plan|program)\b", question.lower()):
        parts.append({"part_id": "entire_plan", "label": "完整个人训练计划", "reason": "entire_plan_not_authorized"})
    if constraints["source_comparison_request"]:
        parts.append({"part_id": "source_comparison", "label": "指定来源或版本之间的比较", "reason": "cross_source_comparison_not_reviewed"})
    if constraints["statistical_calculation_request"]:
        parts.append({"part_id": "statistical_calculation", "label": "具体数据的统计计算", "reason": "statistical_data_and_model_required"})
    return {"subject": subject, "outcome": outcome, "requested_relation": relation, **constraints,
            "possible_outcomes": sorted(outcomes), "issues": issues, "required_answer_parts": parts + extra_parts,
            "resolution": "compositional_answer_parts_v1.4.2" if parts else "unresolved_or_ambiguous_task"}


def core_candidates(w, question, context, roles, allowed_refs=None):
    from .core import _answer_revision, _claim
    task = parse_task(question, context)
    candidates, excluded = [], []
    if allowed_refs is None:
        rows = list(w.lib.theories.execute("SELECT * FROM source_claim ORDER BY claim_id,version"))
    else:
        # Frozen membership uses current records so revocation and source checks
        # still run; the snapshot cannot restore old scientific validity.
        rows = [w.lib.theories.execute("SELECT * FROM source_claim WHERE claim_id=? AND version=?", ref).fetchone()
                for ref in sorted(allowed_refs)]
        rows = [row for row in rows if row is not None]
    replaced = set()
    for row in rows:
        try:
            predecessor = _answer_revision(w, json.loads(row["payload_json"]))
        except ValueError:
            continue
        if predecessor:
            replaced.add((predecessor["claim_id"], predecessor["version"]))
    for row in rows:
        if (row["claim_id"], row["version"]) in replaced:
            excluded.append({"theory_id": row["claim_id"], "version": row["version"], "reason": "answer_version_replaced"})
            continue
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
                          and (not part.get("requested_goal") or part["requested_goal"] in goals)
                          and _part_source_matches(w, evidence, definition, part.get("source_constraints"))]
        matches = bool(matching_parts)
        if task["specific_source_unresolved"] or not source_constraints_match(w, evidence, task["source_constraints"]):
            excluded.append({"theory_id": row["claim_id"], "reason": "candidate_source_constraints_mismatch", "target_matched": matches})
            matches = False
        requested_population = task.get("requested_population")
        source_population = claim["scope"].get("population")
        scope_question = definition["outcome"] in {"population_scope", "adult_guideline_scope", "activity_safety_scope"}
        population_matches = (scope_question or requested_population is None
                              or requested_population == source_population
                              or (source_population == "adults" and requested_population == "healthy_adults"))
        if matches and not population_matches:
            excluded.append({"theory_id": row["claim_id"], "reason": "question_population_scope_mismatch"})
            matches = False
        age_range = claim["scope"].get("age_range")
        if (matches and not scope_question and task.get("requested_age") is not None
                and age_range and not (age_range[0] <= task["requested_age"] <= age_range[1])):
            excluded.append({"theory_id": row["claim_id"], "reason": "question_age_scope_mismatch"})
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
                  "limitations": claim["limitations"], "answer_bindings": [
                      {**binding, "relation": p.get("evidence_relation", binding["relation"])} for binding in bindings
                  ]} for p in definition["answer_parts"]]
        candidates.append({"theory_id": row["claim_id"], "theory_version": row["version"],
            "card": {"title": claim["statement"], "domains": definition.get("routes", ["progression"]), "kind": "source_claim"},
            "review": {"claims": parts, "evidence_links": claim["evidence_links"], "applicability": {"required": claim.get("conditions", [])},
                       "reviewer_kind": review["reviewer_kind"], "authority": "explanation_only"},
            "spans": [w.lib.span(x["span_id"]) for x in evidence], "exact_reviewed_question": bool(matches),
            "corpus_roles": sorted({r for x in evidence for r in x["corpus_roles"]}), "resolved_task": task})
    return candidates, excluded
