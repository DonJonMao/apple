"""Rebuild delivery evidence from executed audits, without upgrading science status."""

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text())


def build():
    metrics = read("src/healthzip/science/metrics.json")["metrics"]
    sources = {s["source_id"]: s for s in read("artifacts/knowledge/source_audit.json")["sources"]}
    aliases = read("src/healthzip/knowledge/data/sources.json")["source_aliases"]
    theory = {t["theory_id"]: t for t in read("artifacts/knowledge/theory_audit.json")["cards"]}
    seed = read("src/healthzip/knowledge/data/theory_seed_cards.json")["cards"]
    accepted = read("artifacts/science/acceptance-results.json")
    scientific_details = {m["metric_id"]: m for m in read("docs/science_traceability.json")["metrics"]}
    by_metric = defaultdict(list)
    for case in accepted["cases"]:
        by_metric[case["metric_id"]].append(case)

    fields = ["requirement_id", "function_or_metric", "implementation_anchor", "contract",
              "evidence_refs", "verification_status", "implementation", "software_verification",
              "corpus_acquisition", "theory_review", "scientific_validation",
              "verification_evidence", "remaining_limits"]
    rows = []

    def add(identity, title, anchor, software, evidence, limits, *, corpus="not_applicable_operational_requirement",
            review="not_applicable_operational_requirement", scientific="not_a_personal_effect_validation_claim",
            status="implemented_with_scoped_verification", contract="V1_3_GOAL.md", refs=""):
        rows.append(dict(zip(fields, [identity, title, anchor, contract, refs, status,
                                     "implemented_with_explicit_gates", software, corpus, review,
                                     scientific, evidence, limits])))

    training = "artifacts/verification/training-tests.xml"
    knowledge = "artifacts/verification/knowledge-ai-tests.xml"
    add("UX-01", "临时与模板训练", "src/healthzip/training/service.py;src/healthzip/ui/training_page.py",
        "executed_lifecycle_roundtrip_and_template_snapshot_fixtures_passed", training,
        "Synthetic local training workflows; no broad device usability study")
    add("UX-02", "动作分类搜索自定义", "src/healthzip/training/service.py;src/healthzip/training/exercise_catalog_seed.json",
        "executed_catalog_navigation_custom_identity_fixtures_passed", training,
        "46 seed exercises are a navigation catalogue; unreviewed muscle maps cannot authorize quantitative dose")
    add("UX-03", "记录修订幂等与离线", "src/healthzip/training/service.py;src/healthzip/ui/offline_recorder.html;src/healthzip/sync_server.py",
        "executed_revision_conflict_retry_fixtures_and_390x844_Chromium_offline_check_passed",
        training + ";artifacts/verification/offline_browser.json",
        "Local browser storage can be cleared; no cloud sync; browser/device coverage remains limited")
    add("MIG-01", "v1/v2升级与未知保留", "src/healthzip/db/repository.py::Repository._migrate_schema",
        "executed_v1_incremental_upgrade_v2_training_upgrade_rollback_and_rerun_fixtures_passed",
        training + ";tests/unit/test_incremental.py::test_v1_database_is_upgraded_without_replacing_rows",
        "Synthetic legacy databases; unknown historical equipment/load/visibility remain unknown")
    add("KB-01", "理论与来源分库", "src/healthzip/knowledge/store.py;src/healthzip/knowledge/workbench.py",
        "executed_separate_store_version_span_release_and_integrity_checks_passed",
        knowledge + ";artifacts/knowledge/integrity.json;artifacts/knowledge/source_audit.json;artifacts/knowledge/theory_audit.json",
        "43 sources attempted; 14 distinct eligible fulltexts; 11 cards contain only selected explanation claims; 9 draft",
        corpus="14/43_distinct_sources_with_eligible_fulltext;29_scientific_metadata_sources",
        review="11/20_AI_assisted_selected_claims_explanation_only;9/20_draft;0_independent_expert_reviews",
        scientific="not_established_by_integrity_or_ingestion")
    add("RAG-01", "按功能检索和引用校验", "src/healthzip/knowledge/retrieval.py;src/healthzip/knowledge/evaluation.py",
        "schema_30/30;citation_locatability_47/47;route_match_23/30;gold_group_recall_14/67",
        "artifacts/knowledge/rag_eval_cases_latest_eval.json;" + knowledge,
        "Visible development set; semantic adjudication denominator=0; no semantic acceptance claim",
        corpus="reviewed_gold_group_coverage_27/67", review="independent_answer_semantic_review_pending",
        scientific="not_established;not_independent_external_evaluation", status="implemented_evaluation_acceptance_not_met")
    add("AI-01", "统一指标本地解释与最小外发投影", "src/healthzip/ai/client.py",
        "executed_canonical_summary_value_unit_window_direction_limits_and_private_nested_payload_regressions_passed",
        knowledge, "No live model request made; structured results and record IDs stay local; generated prose limited to exact evidence statements")
    add("KB-02", "官方来源获取身份许可与定位", "src/healthzip/knowledge/acquisition.py;src/healthzip/knowledge/documents.py",
        "executed_4_provider_smoke_checks;173_versions_1157_spans_integrity_checked;PDF_text_page_bbox_table_fixture_passed",
        "artifacts/knowledge/acquisition_initial.json;artifacts/knowledge/source_audit.json;artifacts/knowledge/integrity.json;artifacts/knowledge/pdf_parser_smoke.json",
        "Restricted sources stay blocked; Apple document copying terms unresolved; scanned PDF has no OCR",
        corpus="partial_14/43_fulltext_sources;all43_attempted", review="license_and_identity_checks_do_not_establish_scientific_support",
        scientific="not_established_by_acquisition")
    add("KB-03", "逐主张审核与候选权限", "src/healthzip/knowledge/workbench.py::KnowledgeWorkbench.reviewed_principles",
        "executed_review_span_scope_authority_and_retraction_invalidation_fixtures_passed",
        knowledge + ";artifacts/knowledge/theory_audit.json;artifacts/knowledge/release_latest.json",
        "All actual reviewed cards are explanation_only; qualified human candidate authority remains absent",
        corpus="partial_source_coverage", review="11_selected_claim_reviews_AI_assisted;9_draft;0_qualified_human_candidate_reviews",
        scientific="independent_expert_and_action_effect_validation_pending")
    add("RAG-02", "固定来源家族留出评测", "src/healthzip/knowledge/evaluation.py;src/healthzip/knowledge/data/rag_holdout.json",
        "schema_8/8;citation_locatability_12/12;route_match_3/8;gold_group_recall_0/8",
        "artifacts/knowledge/rag_holdout_latest_eval.json",
        "Frozen before first run; implementing-agent authored; not externally blinded; do not tune against holdout outcomes",
        corpus="reviewed_gold_group_coverage_0/8", review="independent_answer_semantic_review_pending_denominator_0",
        scientific="not_established", status="implemented_evaluation_acceptance_not_met")
    add("TEMP-01", "事件时间与可见时间隔离", "src/healthzip/temporal.py;src/healthzip/db/temporal_schema.py;src/healthzip/science/contracts.py::select_as_of",
        "executed_future_late_arrival_revision_deletion_and_conflict_cutoff_counterexamples_passed",
        training + ";artifacts/science/software-tests.xml",
        "Unknown historical availability cannot establish prospective performance; retrospective mode stays labeled")
    add("SCI-01", "参数校准与可执行研究评测", "src/healthzip/science/registry.py;src/healthzip/science/research.py;src/healthzip/science/evaluation.py",
        "executed_registry_scope_checks_and_reproducible_trend_energy_prediction_simulations",
        "artifacts/science/calibration_manifest.json;artifacts/science/trend_simulation.json;artifacts/science/energy_simulation.json;artifacts/science/prediction_simulation.json",
        "Synthetic scenarios do not provide authorized real-world time-forward validation; no personal numerical effect licensed",
        corpus="partial_method_fulltext_coverage", review="model_assumptions_and_scope_need_independent_review",
        scientific="simulation_only;real_world_validation_pending")
    add("MIG-02", "WAL备份与非破坏恢复", "src/healthzip/db/backup.py",
        "executed_online_backup_and_restore_to_new_path_fixture_passed", training,
        "Private backups must remain private; restore requires a fresh destination path")

    for metric in metrics:
        identity = metric["metric_id"]
        refs = sorted({canonical for ref in metric["evidence_refs"] for canonical in aliases.get(ref, [ref])})
        eligible = [s for s in refs if sources.get(s, {}).get("eligible_fulltext_version_ids")]
        pending = [s for s in refs if s not in eligible]
        linked = [theory[t["theory_id"]] for t in seed if identity in t["metric_ids"]]
        reviewed = [t["theory_id"] for t in linked if t["status"] == "approved"]
        draft = [t["theory_id"] for t in linked if t["status"] != "approved"]
        cases = by_metric[identity]
        passed = sum(c.get("passed") is True for c in cases)
        assert cases and passed == len(cases), identity
        if identity.startswith("STR-"):
            anchor = "strength.py::strength_metric"
        elif identity.startswith(("STATE-", "LOAD-")):
            anchor = "state.py::state_metric"
        elif identity.startswith(("BODY-", "ENERGY-")):
            anchor = "energy.py::energy_metric"
        elif identity.startswith("PRED-"):
            anchor = "prediction.py::prediction_metric"
        elif identity.startswith("REPORT-"):
            anchor = "reports.py::report_metric"
        else:
            anchor = "evaluation.py::quality_metric"
        scientific = ("synthetic_accounting_only;independent_semantic_adjudication_pending" if identity.startswith("QAL-")
                      else "definition_or_model_contract_software_checked;personal_effect_validation_not_established")
        if identity.startswith("PRED-") or identity in {"STR-19", "STR-20", "STR-22", "STR-24", "ENERGY-NET-STORAGE", "ENERGY-DELTA-INTAKE", "ENERGY-ABSOLUTE-INTAKE"}:
            scientific = "simulation_and_guardrail_checks_only;real_world_scope_validation_pending"
        activation = metric.get("activation_conditions", "")
        limits = "Fulltext presence does not approve metric formula or applicability; selected explanation claims do not license numerical actions. " + (activation if isinstance(activation, str) else json.dumps(activation, ensure_ascii=False))
        number = int(identity.split("-")[1]) if identity.startswith("STR-") else None
        if number in {5, 6}:
            limits += " Numerical muscle counts require reviewed versioned muscle mappings."
        elif number in {16, 17}:
            limits += " Numerical formula output requires an explicit version/domain and known total load."
        elif number is not None and 18 <= number <= 24:
            limits += " Inferential outputs require repeat design/error, practical equivalence, calibration and repeated-look allocation where applicable."
        elif number in {25, 26}:
            limits += " Actual corpus has no qualified progression/trial numerical capability; show evidence request instead."
        elif identity.startswith("PRED-"):
            limits += " API supports calibration contexts; default simulation release remains B0, without validated B1/interval authority."
        elif identity in {"ENERGY-NET-STORAGE", "ENERGY-DELTA-INTAKE", "ENERGY-ABSOLUTE-INTAKE"}:
            limits += " Numerical output requires independently supported baseline, parameter and composition assumptions; otherwise unknown."
        if identity.startswith("QAL-"):
            limits += " Actual corpus evaluation is partial; synthetic accounting labels are not human answer reviews."
        limits += " Required inputs/context: " + "; ".join(scientific_details[identity]["required_inputs_or_context"])
        add(identity, metric["title"], "src/healthzip/science/" + anchor + ";src/healthzip/science/engine.py::evaluate",
            f"executed_synthetic_catalog_fixtures_passed={passed}/{len(cases)};" + ";".join(c["case_id"] for c in cases),
            "artifacts/science/acceptance-results.json;artifacts/science/software-tests.xml;docs/science_traceability.json;artifacts/knowledge/source_audit.json;artifacts/knowledge/theory_audit.json",
            limits, corpus=f"eligible_fulltext={len(eligible)}/{len(refs)};eligible=" + ";".join(eligible) + ";pending=" + ";".join(pending),
            review="related_AI_assisted_explanation_claims=" + ";".join(reviewed) + ";draft=" + ";".join(draft) + ";metric_formula_independent_review=not_established",
            scientific=scientific, contract="src/healthzip/science/metrics.json#" + identity,
            refs=";".join(metric["evidence_refs"]))
    assert len(metrics) == 77 and len({r["requirement_id"] for r in rows}) == len(rows)
    with (ROOT / "requirements_traceability.csv").open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} requirements: 77 metrics and {len(rows) - 77} operational requirements")


if __name__ == "__main__":
    build()
