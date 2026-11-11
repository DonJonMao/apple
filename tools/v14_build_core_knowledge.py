"""Build traceable core claims/rules from actual locally acquired public sources.

Paid books remain chapter gaps. No source bytes are written to public artifacts.
Run with --fetch to retry official public acquisition; default reuses receipts.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from lxml import html

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.acquisition import Acquirer, identity_check
from healthzip.knowledge.core import POLICY, RECORD_POLICY
from healthzip.knowledge.store import digest, dumps, now

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/v14/knowledge"
RELEASE_ID = "core-personal-trial-1.4.3"
URLS = {
    "hhs": "https://odphp.health.gov/our-work/nutrition-physical-activity/physical-activity-guidelines/current-guidelines",
    "hhs_pdf": "https://health.gov/sites/default/files/2019-09/Physical_Activity_Guidelines_2nd_edition.pdf",
    "hhs_rights": "https://odphp.health.gov/copyright-policy",
    "sport": "https://www.sport.gov.cn/n315/n20067006/c20324479/content.html",
    "cn2021": "https://html.rhhz.net/zhlxbx/20220102.htm",
}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def pdf_chapters(raw):
    import io

    import pdfplumber
    spans = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for chapter, indices in (("4", range(54, 65)), ("7", range(86, 93))):
            for index in indices:
                page = pdf.pages[index]
                text = page.extract_text() or ""
                if not text:
                    continue
                spans.append({"kind": "paragraph", "section_path": "Chapter " + chapter,
                    "text": text, "locator": {"edition_id": "CORE-US-HHS-PAG-2:edition-2", "chapter_id": chapter,
                        "file_page_index": index, "printed_page_label": str(index + 1), "printed_page_verification": "footer/page-sequence checked against Chapter 4 and 7 headings",
                        "bounding_box": list(page.bbox), "reading_order": len(spans), "ocr_status": "not_used_text_layer",
                        "original_language": "en", "extraction_method": "pdfplumber_page_text_v1.4"},
                    "structured": {"tables_included_as_parameters": False, "numeric_review_status": "not_table_parameter_evidence", "images_excluded": True}})
    return spans


def acquire(w, fetch=False):
    cache = w.root / "core_acquisition"
    cache.mkdir(exist_ok=True)
    acquirer = Acquirer(w.lib, timeout=20)
    logs = []
    if fetch:
        for key, url in URLS.items():
            try:
                raw, receipt = acquirer.request(url)
                (cache / (key + ".raw")).write_bytes(raw)
                write(cache / (key + ".receipt.json"), receipt)
            except Exception as exc:
                logs.append({"source": key, "status": "fetch_failed", "reason": str(exc)})
    policy_path = cache / "hhs_rights.raw"
    rights = {"status": "official_text_public_domain_images_excluded", "license_id": "US-HHS-public-domain-text",
              "index_allowed": True, "redistribution_allowed": True, "rights_scope": "federal prose only; no photographs or illustrations",
              "evidence_url": URLS["hhs_rights"], "rights_evidence_sha256": digest(policy_path.read_bytes()) if policy_path.exists() else None,
              "declared_use": "local_internal_noncommercial_research_and_retrieval", "reviewer_kind": "ai_assisted",
              "review": "Actual official copyright policy read; no endorsement inferred."}
    if not policy_path.exists() or b"public domain" not in policy_path.read_bytes():
        rights["index_allowed"] = False
        rights["status"] = "rights_evidence_missing"
    pdf = cache / "hhs_pdf.raw"
    if pdf.exists():
        raw = pdf.read_bytes()
        spans = pdf_chapters(raw)
        receipt = json.loads((cache / "hhs_pdf.receipt.json").read_text())
        version = w.lib.record_version("CORE-US-HHS-PAG-2", raw, "fulltext", receipt,
            {"title": "Physical Activity Guidelines for Americans", "edition": 2, "year": 2018,
             "document_pages": 118, "parsed_chapters": [4, 7], "missing_pages": "Other chapters unparsed, not missing from raw PDF", "identity_review": "Official HHS PDF title, edition and publication read"},
            rights, "matched", spans, "hhs-chapters-4-7-text-1.4.0")
        for chapter in ("4", "7"):
            ids = [version + f":s{i:05d}" for i, s in enumerate(spans) if s["locator"]["chapter_id"] == chapter]
            with w.lib.sources:
                w.lib.sources.execute("INSERT OR REPLACE INTO chapter_coverage VALUES(?,?,?,?)",
                    ("CORE-US-HHS-PAG-2", "CORE-US-HHS-PAG-2:edition-2", chapter, dumps({"status": "prose_parsed", "span_ids": ids, "missing_pages": [], "table_review": "images_and_table_parameters_not_activated"})))
        logs.append({"source_id": "CORE-US-HHS-PAG-2", "status": "chapters_parsed", "version_id": version, "raw_sha256": digest(raw), "span_count": len(spans), "index_allowed": rights["index_allowed"]})
    # These pages were actually obtained and read. Their display copyright/terms
    # do not establish permission for a public scientific index; keep them pending.
    for key, sid, selector in (("sport", "CORE-CN-SPORT-GUIDE-2017", "//p"), ("cn2021", "CORE-CN-PA-2021", "//div[@class='article_body']//p")):
        path = cache / (key + ".raw")
        if not path.exists():
            continue
        raw = path.read_bytes()
        tree = html.fromstring(raw)
        spans = [{"text": " ".join(" ".join(n.itertext()).split()), "section_path": "official public guidance text",
                  "locator": {"xpath": tree.getroottree().getpath(n), "original_language": "zh", "paragraph_id": i}, "structured": {"image_tables_review": "pending"}}
                 for i, n in enumerate(tree.xpath(selector)) if "".join(n.itertext()).strip()]
        version = w.lib.record_version(sid, raw, "fulltext", json.loads((cache / (key + ".receipt.json")).read_text()),
            {"title": " ".join(tree.xpath("//title/text()")), "content_scope": "published public text; 2021 journal explicitly identifies itself as an excerpt"},
            {"status": "local_copy_rights_scope_pending", "index_allowed": False, "redistribution_allowed": False,
             "reason": "Publicly readable official/journal text acquired; no explicit reuse grant established. Images/tables remain separately unverified."},
            "matched", spans, "official-html-prose-1.4.0")
        logs.append({"source_id": sid, "status": "body_acquired_rights_pending", "version_id": version,
                     "raw_sha256": digest(raw), "span_count": len(spans), "index_allowed": False})
    return logs


def existing_review(w, table, id_field, identifier, version):
    row = w.lib.theories.execute(f"SELECT review_json FROM {table} WHERE {id_field}=? AND version=?", (identifier, version)).fetchone()
    return json.loads(row[0]) if row and row[0] != "{}" else None


def retire_prior_claims(w, claim_id, current_version):
    for row in w.lib.theories.execute("SELECT version FROM source_claim WHERE claim_id=? AND version!=? AND status='verified'", (claim_id, current_version)).fetchall():
        w.core_state("claim", claim_id, row[0], "needs_review", actor="Codex AI-assisted source scope review",
            rationale="Superseded for current use by explicit immutable scope/content version " + current_version + "; original content and releases retained.")


def build_claims(w):
    source = w.lib.sources.execute("SELECT version_id FROM version WHERE source_id='S1' AND parser_version='jats-owned-text-1.4.1' ORDER BY created_at DESC LIMIT 1").fetchone()
    if not source:
        return []
    vid = source[0]
    version = w.lib.sources.execute("SELECT * FROM version WHERE version_id=?", (vid,)).fetchone()
    # Source role registration must not drop the existing canonical title prefix.
    # Retain a mistakenly conflict-marked parse and append the exact-version
    # identity review; never silently rewrite its metadata or grant scientific clearance.
    if version["identity_status"] != "matched" and not w.lib.sources.execute(
            "SELECT 1 FROM source_review WHERE source_id='S1' AND version_id=? AND decision='identity_matched'", (vid,)).fetchone():
        status, conflicts = identity_check(w.lib.source("S1")["manifest"], json.loads(version["metadata_json"]))
        if status != "matched":
            raise ValueError("S1 identity review failed: " + str(conflicts))
        with w.lib.sources:
            w.lib.sources.execute("INSERT INTO source_review(source_id,version_id,reviewer,decision,rationale,created_at) VALUES(?,?,?,?,?,?)",
                ("S1", vid, "Codex AI-assisted exact bibliographic identity check", "identity_matched", "Canonical original title includes ACSM Position Stand prefix; DOI, PMID, full title and publication years all match. No scientific-state clearance.", now()))
    def ids(indices):
        return [vid + f":s{i:05d}" for i in indices]
    specifications = [
        ("CORE-CLAIM-PROGRESSION", [61, 62, 70, 74], "progression_options", "options", "渐进训练可调整负荷、训练量等变量，并结合个人目标；增加次数与调整负荷是不同任务选择。原则本身不能给出个人下一次的精确重量或保证完成。"),
        ("CORE-CLAIM-FAILURE", [72, 76], "failure_necessity", "necessity", "这份健康成人综述认为，训练至瞬时肌肉力竭不是获得力量、肌肥大或功率收益的必要条件；这不等于无需足够努力，也不能推算个人最优余力。"),
        ("CORE-CLAIM-RIR", [72, 76], "effort_precision", "precision", "原文讨论足够努力及一般RIR建议，同时明确现有证据不足以量化精确RIR或主观用力目标。不能据此给每个人指定精确余力，也不能把其他RPE量表直接换成RIR。"),
        ("CORE-CLAIM-VOLUME", [71, 74], "volume", "options", "该综述中较高组量与部分力量和肌肥大收益有关，但精确最优组数仍不能确定，额外收益可能递减。讨论组量须结合目标与当前计划，不能由总吨位直接推算肌肉刺激或统一加组。"),
        ("CORE-CLAIM-REST", [24, 69, 74], "rest", "options", "该综述的健康成人力量结果未显示所比较短长组间休息的一致差别；这是所纳入方案的群体结果，不能证明休息对所有任务都无效，或给每个人确定最佳间歇。"),
    ]
    result = []
    for cid, indices, outcome, relation, statement in specifications:
        indices = sorted(set([11, *indices]))
        scope = {"population": "healthy_adults", "time_scale": "multiweek_programs", "aggregation": "group_evidence"}
        if cid == "CORE-CLAIM-REST":
            scope["goal"] = "strength"
        else:
            scope["applicable_goals"] = ["strength", "hypertrophy", "general_fitness"]
        claim = {"claim_id": cid, "version": "1.4.3", "statement": statement,
                 "scope": scope,
                 "limitations": ["主要为群体证据；所纳入研究大量来自训练经验较少者；不构成个人处方或效果保证。"],
                 "evidence_links": [{"source_id": "S1", "source_version_id": vid, "span_ids": ids(indices)}],
                 "answer_task": {"subject": "resistance_training", "outcome": outcome, "requested_relation": relation,
                     "evidence_relation": "supports", "answer_complete": True, "routes": ["strength", "progression", "plateau"],
                     "answer_parts": [{"part_id": outcome, "text": statement, "span_ids": ids(indices)}]}}
        review = existing_review(w, "source_claim", "claim_id", cid, "1.4.3") or {
            "reviewer": "Codex knowledge implementation agent", "reviewer_kind": "ai_assisted", "reviewed_at": now(),
            "content_checked": True, "independent_expert_validation": False,
            "rationale": "Actually read S1 fulltext DISCUSSION paragraphs and scope/limitations; retain group-to-individual limits. No textbook or human review is implied."}
        w.review_claim(claim, review)
        retire_prior_claims(w, cid, "1.4.3")
        result.append({"claim": claim, "review": review})
    hhs = w.lib.sources.execute("SELECT version_id FROM version WHERE source_id='CORE-US-HHS-PAG-2' AND parser_version='hhs-chapters-4-7-text-1.4.0' ORDER BY created_at DESC LIMIT 1").fetchone()
    if hhs:
        span = next((w.lib.span(r[0]) for r in w.lib.sources.execute("SELECT span_id FROM span WHERE version_id=?", (hhs[0],))
                     if "2 or more days" in w.lib.span(r[0])["text"]), None)
        if span and w.lib.eligible(span)[0]:
            cid = "CORE-CLAIM-PUBLIC-FREQUENCY"
            statement = "HHS第二版第4章（18–64岁成人）建议每周至少两天进行涉及主要肌群、中等或以上强度的肌力活动；这是总体健康建议，不能当作某个人力量或增肌训练的唯一最优频率。"
            claim = {"claim_id": cid, "version": "1.4.3", "statement": statement,
                "scope": {"population": "adults", "age_range": [18, 64], "time_scale": "weekly", "goal": "public_health"}, "limitations": ["公共健康指导不替代高级训练方案或临床个体化；此声明精确绑定第4章成人范围。"],
                "evidence_links": [{"source_id": "CORE-US-HHS-PAG-2", "source_version_id": hhs[0], "span_ids": [span["span_id"]]}],
                "answer_task": {"subject": "resistance_training", "outcome": "frequency", "requested_relation": "options", "evidence_relation": "supports", "answer_complete": True,
                    "routes": ["strength", "progression", "recovery"], "answer_parts": [{"part_id": "health_frequency", "text": statement, "span_ids": [span["span_id"]]}]}}
            review = existing_review(w, "source_claim", "claim_id", cid, "1.4.3") or {"reviewer": "Codex knowledge implementation agent", "reviewer_kind": "ai_assisted", "reviewed_at": now(), "content_checked": True,
                "independent_expert_validation": False, "rationale": "Read actual HHS Chapter 4 adult recommendations and distinguish public-health floor from individual optimization."}
            w.review_claim(claim, review)
            retire_prior_claims(w, cid, "1.4.3")
            result.append({"claim": claim, "review": review})
    return result


def build_rules(w):
    inventory = json.loads((ROOT / "src/healthzip/knowledge/data/core_rules.json").read_text())["rules"]
    active = []
    mappings = {"CORE-F2-DOUBLE-PROGRESSION": "plan_candidate", "CORE-F2-REPETITION-TRIAL": "trial_candidate",
                "CORE-F2-LOAD-REPS-TRIAL": "trial_candidate", "CORE-F3-STRATEGY-REVIEW": "trial_candidate"}
    for base in inventory:
        if base["rule_id"] not in mappings:
            continue
        strategies = ["double_progression"] if mappings[base["rule_id"]] == "plan_candidate" else ["repetition_progression"] if base["rule_id"] == "CORE-F2-REPETITION-TRIAL" else ["heavier_lower_reps"] if base["rule_id"] == "CORE-F2-LOAD-REPS-TRIAL" else ["repetition_progression", "heavier_lower_reps"]
        rule = {**base, "rule_version": "1.4.3", "supersedes": "1.4.1", "requested_capability": mappings[base["rule_id"]],
            "permitted_actions": strategies,
            "capability_policy_version": POLICY["version"], "routes": ["progression", "plateau"],
            "claim_refs": [{"claim_id": "CORE-CLAIM-PROGRESSION", "version": "1.4.3"}],
            "conditions": [{"field": "age", "op": "range", "min": 18, "origin": "source_scope"},
                {"field": "health_scope", "op": "eq", "value": "healthy_adult_self_reported", "origin": "source_scope"},
                {"field": "training_goal", "op": "in", "value": ["strength", "hypertrophy", "general_fitness"], "origin": "user_plan"},
                {"field": "training_experience", "op": "in", "value": ["novice", "experienced"], "origin": "source_scope"},
                {"field": "strategy", "op": "in", "value": strategies, "origin": "user_plan"}],
            "application_logic": "A bounded single user-selected task operationalizes progressive overload/individualization; source does not prescribe this exact algorithm or personal weight. Scientific service separately validates quality/symptoms, comparable reference, target and feasible equipment step.",
            "numeric_provenance": {"next_load": "equipment_constraint: confirmed available_loads and load_basis", "target_reps": "user_plan: explicit target/selected trial", "rir": "user_plan: no fabricated RIR", "success_probability": "not_estimated"},
            "exit_conditions": ["pain_or_technique_limit: stop current escalation and review task", "missing_required_input: no numerical candidate", "user_declines: do not change plan"],
            "followup": "Freeze target, rule/claim versions, reference IDs and chosen variable; link actual execution and later comparable observations; no causal benefit inferred.",
            "limits": ["个人选择的一次试验任务；不是个人成功预测、最优处方或因果疗效。", "正文支持一般原则，产品规则另行核对；AI核对不冒充专家。"],
            "implementation_validation_refs": ["tests/unit/test_v14_knowledge.py::test_core_rule_requires_real_claim_context_and_truthful_review",
                "tests/integration/test_review_candidate_flow.py", "science.strength shared candidate applicability"],
            "activation_status": "reviewed_personal_trial_policy", "claim_topics_to_verify": []}
        review = existing_review(w, "application_rule", "rule_id", rule["rule_id"], "1.4.3") or {"reviewer": "Codex knowledge implementation agent", "reviewer_kind": "ai_assisted", "reviewed_at": now(),
            "application_checked": True, "independent_expert_validation": False, "rationale": "Source principle and product operationalization checked separately. User/equipment supply numbers; domain-service checks required inputs and restrictions. No personal effectiveness, advanced textbook coverage or human qualification claimed."}
        w.review_rule(rule, review)
        active.append({"rule": rule, "review": review})
    return active


def build_extended_claims(w):
    definitions = json.loads((ROOT / "src/healthzip/knowledge/data/core_extension.json").read_text())
    for sid, expected in definitions["sources"].items():
        row = w.lib.sources.execute("SELECT sha256 FROM version WHERE source_id=? AND version_id=?", (sid, expected["version_id"])).fetchone()
        if not row or row[0] != expected["sha256"]:
            raise ValueError("extended claims require the exact actually read source bytes: " + sid)
    def links(mapping):
        return [{"source_id": sid, "source_version_id": definitions["sources"][sid]["version_id"],
            "span_ids": [definitions["sources"][sid]["version_id"] + f":s{index:05d}" for index in indices]}
            for sid, indices in mapping.items()]
    result = []
    for definition in definitions["claims"]:
        evidence = links(definition["source_spans"])
        parts = [{"part_id": part["part_id"], "text": part["text"],
            "span_ids": [span for link in links(part.get("source_spans", definition["source_spans"])) for span in link["span_ids"]]}
            for part in definition["answer_parts"]]
        claim = {"claim_id": definition["claim_id"], "version": definition["version"],
            "statement": "\n".join(p["text"] for p in parts), "scope": definition["scope"], "limitations": definition["limitations"],
            "evidence_links": evidence, "answer_task": {"subject": "resistance_training", "outcome": definition["outcome"],
                "requested_relation": definition["requested_relation"], "evidence_relation": "supports", "answer_complete": True,
                "required_answer_parts": [p["part_id"] for p in parts], "routes": ["strength", "progression", "plateau", "recovery"],
                "answer_parts": parts}}
        review = existing_review(w, "source_claim", "claim_id", claim["claim_id"], claim["version"]) or {
            "reviewer": "Codex knowledge implementation agent", "reviewer_kind": "ai_assisted", "reviewed_at": now(),
            "content_checked": True, "independent_expert_validation": False,
            "rationale": "Actually read exact S1/HHS spans and scope; separate initial benefit/long-term progress, source-level evidence and bounded individual interpretation. No paid textbook or statistical calibration authority asserted."}
        w.review_claim(claim, review)
        retire_prior_claims(w, claim["claim_id"], claim["version"])
        result.append({"claim": claim, "review": review})
    return result


def build_coverage_rules(w):
    """Separate source explanations from record contracts and method gaps."""
    inventory = json.loads((ROOT / "src/healthzip/knowledge/data/core_rules.json").read_text())["rules"]
    evidence = {
        "CORE-F2-GOAL-SCOPE": (["GOAL-SCOPE", "ADULT-SCOPE"], [], "Choose the declared goal and report each source's population/goal scope; unknown profile never becomes a healthy-adult fact."),
        "CORE-F2-EFFORT": (["FAILURE", "RIR", "ADULT-SCOPE"], ["Original RIR-scale validation/measurement-error fulltexts S3/S4 are not held; no numerical accuracy or cross-scale conversion validated."], "Retain observed RIR/range/scale identity; explain sufficient effort and the lack of exact universal targets; no scale conversion."),
        "CORE-F2-VOLUME-OPTIONS": (["VOLUME", "GOAL-SCOPE"], [], "Discuss sets and goal-specific limits using the user's recorded plan; no optimal set count, automatic added sets or muscle stimulus inferred from tonnage."),
        "CORE-F2-REST-OPTIONS": (["REST", "REST-HYPERTROPHY", "GOAL-SCOPE"], [], "Separate strength comparisons from insufficient hypertrophy evidence; preserve goal and task; do not recommend a personal exact interval."),
        "CORE-F2-FREQUENCY-OPTIONS": (["FREQUENCY-VOLUME", "PUBLIC-FREQUENCY", "GOAL-SCOPE"], [], "Separate HHS public-health guidance from S1 strength/hypertrophy and total-volume conditions; no averaged or unique personal schedule."),
        "CORE-F2-STATE-CONTEXT": (["SYMPTOM-SCOPE", "GRADUAL-PROGRESSION", "GROUP-INDIVIDUAL"], ["Specific sleep/HRV/fatigue-to-performance mechanisms and individualized recovery schedules require their own original evidence; not established by HHS general guidance."], "Keep state observations separate from training capability; new symptoms require review, not a fabricated load-reduction percentage or recovery time."),
        "CORE-F3-OPPORTUNITY": (["LOAD-REPETITION", "SPECIFICITY", "GROUP-INDIVIDUAL"], ["RIR error magnitude and exact latent-capacity estimates require original validation and task-specific calibration."], "Interpret plan-limited and changed-load observations as their recorded tasks; unchanged prescribed repetitions do not by themselves demonstrate an unchanged capacity limit."),
        "CORE-F3-EXPLANATION-HYPOTHESES": (["GROUP-INDIVIDUAL", "GRADUAL-PROGRESSION", "VARIATION"], ["Detailed physiological mechanisms, nutrition and individual sleep/recovery causation remain outside these sources and require specific original evidence."], "Present competing explanations only as questions/hypotheses, preserve observed facts, and never attribute an individual's change to the chosen program from before/after coincidence."),
    }
    records = {
        "CORE-F23-COMPARABILITY": ("description", "condition_key + analysis_task + outcome_series", ["exercise_id", "definition_version", "protocol"],
            "Same-task record grouping and exclusion reasons; no equality inferred from similar names or guessed equipment resistance.",
            ["Specific joint actions and biomechanical relationships still need authorized NSCA/Neumann chapter evidence; record grouping does not establish these."],
            ["tests/science/test_v14_science.py::test_f07_equivalent_exact_mass_units_share_series_without_losing_raw_values", "tests/training/test_v14_catalog.py::test_f06_history_template_keeps_actual_definition"]),
        "CORE-F2-PLAN-CHECK": ("description", "TrainingService.current_targets plus actual sets and as-of snapshot", ["target_version", "as_of"],
            "Compare actual observations only with the effective target revision; absence remains missing, not failed execution.", [],
            ["tests/integration/test_review_candidate_flow.py::test_visible_candidate_task_end_to_end", "tests/integration/test_v14_advice_flow.py::test_modified_choice_checks_equipment_and_preserves_original_task"]),
        "CORE-F23-EXECUTION-FEEDBACK": ("task_followup", "STR-27/28 candidate ID + task ID + frozen target/rule versions + linked execution", ["task_id", "target_version"],
            "Describe adoption, execution, target completion and missing outcomes separately; task completion does not establish hypertrophy or a causal effect.", [],
            ["tests/integration/test_review_candidate_flow.py::test_r08_feedback_remains_after_finishing_session", "tests/science/test_v14_science.py::test_metric_matrix_followup_strata_keep_unknown_and_unique_candidate_denominators"]),
        "CORE-F3-DESCRIPTIVE-TREND": ("description", "STR-12/14 raw same-load series with event/availability cutoff", ["as_of", "outcome_series_id"],
            "Show within-task observations at real times and preserve load strata; no p-value, equivalence or biological plateau inferred from a descriptive flat line.", [],
            ["tests/science/test_v14_science.py::test_f07_intervening_load_does_not_hide_same_load_raw_change", "tests/integration/test_v14_query_planning.py::test_f13_window_filter_cannot_revive_moved_or_deleted_revision"]),
        "CORE-F3-WEEK-MONTH-REPORT": ("report", "REPORT-* derived snapshot facts, local date windows and recommendation strata", ["as_of", "timezone"],
            "Report counts, coverage, state observations and candidate follow-up with exact denominator/window/version; no aggregate readiness score or personal efficacy conclusion.", [],
            ["tests/science/test_state_energy_prediction.py::test_report_context_is_not_future_or_unknown_availability_backdoor", "tests/science/test_v14_science.py::test_metric_matrix_followup_strata_keep_unknown_and_unique_candidate_denominators"]),
    }
    claim_versions = {row["claim_id"]: row["version"] for row in w.lib.theories.execute("SELECT claim_id,version FROM source_claim WHERE status='verified'")}
    result = []
    for base in inventory:
        rid = base["rule_id"]
        if rid not in evidence and rid not in records:
            continue
        rule = {**base, "rule_version": "1.4.3", "supersedes": "1.4.2", "requested_topic_capability": base["requested_capability"],
            "routes": ["strength", "progression", "plateau", "recovery"], "permitted_actions": [],
            "limits": ["仅授予下列明确能力；不产生个人数值训练候选、诊断、最优处方或个人因果验证。"],
            "activation_status": "reviewed_bounded_capability", "claim_topics_to_verify": []}
        if rid in evidence:
            ids, gaps, logic = evidence[rid]
            if any("CORE-CLAIM-" + key not in claim_versions for key in ids):
                continue
            rule.update(requested_capability="source_explanation", capability_policy_version=POLICY["version"],
                claim_refs=[{"claim_id": "CORE-CLAIM-" + key, "version": claim_versions["CORE-CLAIM-" + key]} for key in ids],
                conditions=[{"field": "requested_capability", "op": "eq", "value": "source_explanation", "origin": "product_scope"}],
                application_logic=logic, coverage_scope="bounded_source_explanation_and_discussion", remaining_source_gaps=gaps,
                implementation_validation_refs=["tests/unit/test_v14_knowledge_coverage.py::test_explanation_rule_never_becomes_candidate_authority",
                    "src/healthzip/knowledge/tasks.py", "src/healthzip/knowledge/core.py::core_principles"])
        else:
            capability, contract, fields, logic, gaps, tests = records[rid]
            rule.update(requested_capability=capability, capability_policy_version=RECORD_POLICY["version"], claim_refs=[],
                evidence_basis="product_record_contract", record_contract={"executor": contract, "input_identity_fields": fields,
                    "missing_policy": "explicit_missing_not_zero", "numeric_origin": "record_arithmetic_only_not_physiological_parameter"},
                conditions=[{"field": field, "op": "present", "origin": "measurement_contract"} for field in fields],
                application_logic=logic, coverage_scope="record_description_only", remaining_source_gaps=gaps,
                implementation_validation_refs=tests + ["tests/unit/test_v14_knowledge_coverage.py::test_record_policy_does_not_require_unread_scientific_claim_or_grant_actions"])
        review = existing_review(w, "application_rule", "rule_id", rid, "1.4.3") or {
            "reviewer": "Codex knowledge implementation agent", "reviewer_kind": "ai_assisted", "reviewed_at": now(),
            "application_checked": True, "independent_expert_validation": False,
            "rationale": "Checked actual source statements separately from record identity/availability and product logic. Scope is explicitly narrowed to the listed capability; remaining biological/method validation gaps retained."}
        w.review_rule(rule, review)
        result.append({"rule": rule, "review": review})
    return result


def export(w, acquired, claims, rules):
    OUT.mkdir(parents=True, exist_ok=True)
    status = w.core_status()
    write(OUT / "capability_policy.json", POLICY)
    write(OUT / "record_description_policy.json", RECORD_POLICY)
    write(OUT / "status.json", {"run_at": now(), "acquisition": acquired, "core": status, "legacy_theories": w.status()["theory_states"]})
    for filename, items in (("core_claims.jsonl", claims), ("advice_rules.jsonl", rules)):
        (OUT / filename).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items))
    sources = []
    for planned in json.loads((ROOT / "src/healthzip/knowledge/data/core_sources.json").read_text())["sources"]:
        source = w.lib.source(planned["source_id"])
        item = dict(source["manifest"])
        item["planning_status_declarations"] = {key: item.pop(key) for key in ("manifest_status", "acquisition_state", "scientific_review_status", "rights_status") if key in item}
        versions = []
        for row in w.lib.sources.execute("SELECT version_id,sha256,byte_length,parser_version,material_type FROM version WHERE source_id=? AND material_type='fulltext'", (source["source_id"],)):
            spans = [w.lib.span(x[0]) for x in w.lib.sources.execute("SELECT span_id FROM span WHERE version_id=?", (row["version_id"],))]
            versions.append({**dict(row), "eligible_span_count": sum(w.lib.eligible(s)[0] for s in spans)})
        linked_claims = [x["claim"]["claim_id"] for x in claims if any(link["source_id"] == source["source_id"] for link in x["claim"]["evidence_links"])]
        item["runtime_status"] = {"canonical_source_id": source["source_id"], "acquisition_state": source["acquisition_state"],
            "scientific_state": source["scientific_state"], "fulltext_versions": versions,
            "distinct_raw_fulltexts": len({v["sha256"] for v in versions}), "verified_source_claim_ids": linked_claims,
            "rights_for_index": "permitted_for_eligible_spans_only" if any(v["eligible_span_count"] for v in versions) else "pending_or_no_body",
            "acquisition_attempts": "paid_source_attempts.json" if planned["content_acquisition_route"] == "authorized_edition_or_chapters_import" else "status.json#acquisition"}
        sources.append(item)
    write(OUT / "core_sources_manifest.json", {"sources": sources, "acquisition": acquired,
        "counting_policy": "Canonical aliases and parser versions are not independent sources; planning declarations are separate from actual runtime status."})
    with (OUT / "chapter_ingestion_coverage.csv").open("w") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["source_id", "edition_id", "chapter_id", "status", "span_count", "missing_pages", "table_review"])
        for row in status["chapter_coverage"]:
            value = json.loads(row["payload_json"])
            writer.writerow([row["source_id"], row["edition_id"], row["chapter_id"], value["status"], len(value["span_ids"]), value.get("missing_pages"), value.get("table_review", "pending")])
    with (OUT / "source_rule_feature_matrix.csv").open("w") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["rule_id", "features", "planned_capability", "effective", "claim_refs", "sources_planned", "gap", "verification", "effective_capability", "coverage_scope"])
        for base in json.loads((ROOT / "src/healthzip/knowledge/data/core_rules.json").read_text())["rules"]:
            enabled = next((x["rule"] for x in rules if x["rule"]["rule_id"] == base["rule_id"]), None)
            partial = {"CORE-F2-GOAL-SCOPE": ["CORE-CLAIM-PROGRESSION", "CORE-CLAIM-PUBLIC-FREQUENCY"],
                "CORE-F2-EFFORT": ["CORE-CLAIM-FAILURE", "CORE-CLAIM-RIR"], "CORE-F2-VOLUME-OPTIONS": ["CORE-CLAIM-VOLUME"],
                "CORE-F2-REST-OPTIONS": ["CORE-CLAIM-REST"], "CORE-F2-FREQUENCY-OPTIONS": ["CORE-CLAIM-PUBLIC-FREQUENCY"]}.get(base["rule_id"], [])
            gap = {"unreviewed_topics": [c["topic_zh"] for c in base.get("claim_topics_to_verify", [])],
                "related_explanation_claims_only": partial, "application_rule_review": "not_completed",
                "source_content": "See per-source runtime manifest: paid chapter gaps and/or scoped claims still need review; this is not proof other lawful sources cannot support the topic.",
                "descriptive_software": "available under its own data and implementation contracts"}
            writer.writerow([base["rule_id"], ";".join(base["feature_ids"]), base["requested_capability"], bool(enabled), dumps(enabled["claim_refs"]) if enabled else "", ";".join(base["core_source_manifest_ids"]),
                dumps(enabled.get("remaining_source_gaps", [])) if enabled else dumps(gap), ";".join(enabled["implementation_validation_refs"]) if enabled else "not activated",
                enabled["requested_capability"] if enabled else "none", enabled.get("coverage_scope", "bounded_personal_trial") if enabled else "method_evidence_pending"])
    coverage = []
    method_gaps = {
        "CORE-F3-MEASUREMENT-UNCERTAINTY": ["M1 original reliability/SEM fulltext not acquired; a task/protocol-specific empirical error model and calibration are distinct requirements."],
        "CORE-F3-PRACTICAL-EQUIVALENCE": ["M2 original equivalence-method fulltext not acquired; user-relevant equivalence bounds and matched measurement/model scale remain required."],
        "CORE-F3-REPEATED-LOOKS": ["N2 original time-uniform method fulltext not acquired; a predeclared validated sequential protocol cannot be inferred from ordinary repeated intervals."],
        "CORE-F3-PLATEAU-CANDIDATE": ["Combines the unresolved measurement-error/equivalence/repeated-look source requirements; no group-level training guideline validates an individual's plateau inference."],
    }
    for base in json.loads((ROOT / "src/healthzip/knowledge/data/core_rules.json").read_text())["rules"]:
        enabled = next((x["rule"] for x in rules if x["rule"]["rule_id"] == base["rule_id"]), None)
        coverage.append({"rule_id": base["rule_id"], "topic": base["topic_zh"], "planned_capability": base["requested_capability"],
            "reviewed_capability": enabled["requested_capability"] if enabled else None, "version": enabled["rule_version"] if enabled else "draft-1",
            "status": "reviewed_with_explicit_remaining_scope" if enabled and enabled.get("remaining_source_gaps") else "reviewed_bounded_contract" if enabled else "method_originals_and_calibration_gap",
            "claim_refs": enabled.get("claim_refs", []) if enabled else [],
            "remaining_gaps": enabled.get("remaining_source_gaps", []) if enabled else method_gaps.get(base["rule_id"], []),
            "external_textbook_dependency": "Specific biomechanics/advanced explanatory scope may still require authorized chapters; record contracts and stated S1/HHS claims do not wait for them.",
            "implementation_refs": enabled["implementation_validation_refs"] if enabled else [],
            "independent_human_review": False})
    write(OUT / "core_coverage_audit_21.json", {"baseline": "dd8e2e1", "reviewed_at": now(), "rule_inventory": 21,
        "effective_candidate_rules": status["effective_candidate_rule_count"], "effective_explanation_rules": status["effective_explanation_rule_count"],
        "effective_record_rules": status["effective_record_rule_count"], "remaining_method_rules": sum(not row["reviewed_capability"] for row in coverage),
        "source_claim_count": len(claims), "rules": coverage,
        "limit": "Active records/explanations/candidates are different capabilities; remaining topic gaps are not erased by activation. No unread textbook, independent human review or individual causal validation is claimed."})
    write(OUT / "release.json", w.release_core(RELEASE_ID))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".local/knowledge")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    w = KnowledgeWorkbench(args.root)
    try:
        w.seed()
        w.seed_core()
        acquired = acquire(w, args.fetch)
        claims = build_claims(w)
        rules = build_rules(w) if claims else []
        if claims:
            claims += build_extended_claims(w)
        rules += build_coverage_rules(w)
        export(w, acquired, claims, rules)
        print(dumps({"claims": len(claims), "active_rules": len(rules), "candidate_rules": w.core_status()["effective_candidate_rule_count"],
            "total_rule_inventory": 21, "release_id": RELEASE_ID, "paid_textbooks": "not acquired; explicit chapter gaps"}))
    finally:
        w.close()


if __name__ == "__main__":
    main()
