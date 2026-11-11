"""Import the actually held N1 official article without activating knowledge claims.

This offline import verifies the original official-page and PDF bytes. It never
fetches a new URL, reviews a SourceClaim, or replaces the frozen core release.
"""

from __future__ import annotations

import json
from pathlib import Path

from lxml import html

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.acquisition import identity_check
from healthzip.knowledge.documents import parse_pdf
from healthzip.knowledge.store import digest, now

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".local/knowledge/method_discovery_round2"
PUBLIC = ROOT / "artifacts/v14/knowledge"
PAGE_SHA = "5247f37193e4791b6b386c25f203dd262a3155f43d8d5ab018f066125ba9d08c"
PDF_SHA = "194d6fc4b1e58f6312bcd0eaff136e12ffc9d272165413af6e5316e99931c053"
PARSER = "pdfplumber-layout-n1-1.4.0"


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    frozen_paths = [PUBLIC / "release.json", PUBLIC / "core_claims.jsonl",
                    ROOT / ".local/v14-knowledge-independent-round2/source_packet.json"]
    before = {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in frozen_paths}
    raw_page, raw_pdf = (CACHE / "N1.raw").read_bytes(), (CACHE / "N1-paper.raw").read_bytes()
    if digest(raw_page) != PAGE_SHA or digest(raw_pdf) != PDF_SHA or not raw_pdf.startswith(b"%PDF"):
        raise ValueError("actual reviewed official source bytes required")
    page = html.fromstring(raw_page)
    license_links = page.xpath('//*[@id="jss-copyright"]//a[@href="http://creativecommons.org/licenses/by/3.0/"]')
    if len(license_links) != 1:
        raise ValueError("reviewed article license declaration missing")
    citation = {n.get("name"): n.get("content") for n in page.xpath('//meta[starts-with(@name,"citation_")]')}
    metadata, spans = parse_pdf(raw_pdf)
    if metadata["page_count"] != 17 or {s["locator"]["file_page_index"] for s in spans} != set(range(17)):
        raise ValueError("complete 17-page parse required")
    metadata.update(title=citation["citation_title"], doi=citation["citation_doi"],
                    authors=[citation["citation_author"]], publication_years=[2004],
                    journal=citation["citation_journal_title"], volume=citation["citation_volume"], issue="10",
                    identity_review={"decision": "matched", "reviewer_kind": "ai_assisted",
                        "reviewer": "Codex knowledge source review", "reviewed_at": now(),
                        "rationale": "Official citation DOI/title/author/year agree with registered N1; PDF title/author, 17-page sequence and final November 2004 Volume 11 Issue 10 imprint read."},
                    content_review={"read_file_page_indices": list(range(17)), "reviewer_kind": "ai_assisted",
                        "scope": "method assumptions, computational framework, applications and references read",
                        "formula_transcription_verified": False, "numeric_table_parameters_activated": False},
                    claim_activation="none; no SourceClaim or ApplicationRule created")
    rights = {"status": "official_article_license_reviewed", "license_id": "CC-BY-3.0",
              "license_url": "http://creativecommons.org/licenses/by/3.0/",
              "evidence_url": "https://www.jstatsoft.org/article/view/v011i10",
              "rights_evidence_sha256": PAGE_SHA, "reviewer_kind": "ai_assisted",
              "rights_scope": "Article prose; separate linked software has GPL terms and was not imported",
              "index_allowed": True, "redistribution_allowed": True,
              "public_export_scope": "metadata and original review summaries only; original article stays local",
              "attribution": "Achim Zeileis (2004). Econometric Computing with HC and HAC Covariance Matrix Estimators. Journal of Statistical Software, 11(10), 1–17. https://doi.org/10.18637/jss.v011.i10"}
    receipt = json.loads((CACHE / "N1-paper.receipt.json").read_text())
    w = KnowledgeWorkbench(ROOT / ".local/knowledge")
    try:
        status, conflicts = identity_check(w.lib.source("N1")["manifest"], metadata)
        if status != "matched":
            raise ValueError("N1 identity mismatch: " + str(conflicts))
        version = w.lib.record_version("N1", raw_pdf, "fulltext", receipt, metadata, rights,
                                       status, spans, PARSER)
        current = w.lib.sources.execute("SELECT * FROM version WHERE version_id=?", (version,)).fetchone()
        stored_metadata = json.loads(current["metadata_json"])
        active_n1_claims = [r["claim_id"] for r in w.lib.theories.execute("SELECT * FROM source_claim WHERE status='verified'")
                           if any(x.get("source_id") == "N1" for x in json.loads(r["payload_json"]).get("evidence_links", []))]
        if active_n1_claims:
            raise ValueError("N1 must remain outside active claims during frozen evaluation")
        query = w.query("HC HAC covariance estimation", route="personalization", context={})
        n1_candidates = [c["theory_id"] for c in query["retrieval"]["candidates"]
                         if any(s["source_id"] == "N1" for s in c["spans"])]
        if n1_candidates:
            raise ValueError("unchecked N1 source unexpectedly entered an answer candidate")
        result = {"source_id": "N1", "source_version_id": version, "raw_sha256": PDF_SHA,
            "official_page_sha256": PAGE_SHA, "parser_version": PARSER,
            "byte_length": len(raw_pdf), "page_count": metadata["page_count"], "span_count": len(spans),
            "identity_status": status, "rights": rights, "identity_review": stored_metadata["identity_review"],
            "content_review": stored_metadata["content_review"],
            "new_active_claims": active_n1_claims, "unchecked_source_answer_candidates": n1_candidates,
            "personal_calibration_supplied": False, "independent_human_or_expert_reviews": 0,
            "method_scope": [
                {"file_pages": [1, 2, 3, 4, 5], "summary": "在线性回归与相应正则条件下介绍HC/HAC协方差估计；区分独立异方差与随滞后减弱的相关误差，并讨论渐近一致性和有限样本修正。"},
                {"file_pages": [6, 7, 8], "summary": "HAC实现需要明确数据顺序、权重/核、带宽或截断滞后以及预白化；不同软件默认配置并不代表训练任务已得到校准。"},
                {"file_pages": [9, 10, 11, 12, 13, 14, 15], "summary": "示例涉及横截面公共支出、宏观投资时间序列和利率结构变点；使用回归系数检验及特定变点程序，不能据此授予任意反复查看下的个人训练平台期保证。"},
                {"file_pages": [16, 17], "summary": "参考文献和作者/期刊出版信息已读；被引用文章未因此视为已取得或精读。"}],
            "next_release_candidates": [{"status": "draft_explanation_only_not_a_SourceClaim",
                "topic": "MEASUREMENT-UNCERTAINTY / PLATEAU-CANDIDATE method background",
                "possible_scope": "解释异方差/自相关为何影响回归标准误，以及HAC的模型条件、滞后/带宽选择与渐近范围。",
                "missing_before_activation": ["精确方法主张及对应片段独立核对", "产品估计量、数据单位与误差依赖的匹配核对"],
                "does_not_supply": ["M1同任务重测误差模型或个人校准", "M2实用等效界值依据", "N2任意时点有效序贯协议", "个人小样本覆盖率或平台期真实性"]}],
            "extraction_limits": ["PDF公式文本有字符/顺序瑕疵；尚未核准公式转录。", "表格行/图形不作为数值参数依据。"],
            "frozen_artifact_sha256": before}
        if before != {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in frozen_paths}:
            raise ValueError("frozen claim/release/source packet changed")
        write(PUBLIC / "N1_method_review.json", result)
        acquisition = json.loads((PUBLIC / "method_source_round2.json").read_text())
        for source in acquisition["sources"]:
            if source["source_id"] == "N1":
                source.update(scope="official_fulltext_imported_read_no_claim_activation", fulltext_receipt=receipt,
                              source_version_id=version, license_id="CC-BY-3.0", article_pages_read=17,
                              review_artifact="N1_method_review.json")
            elif source["source_id"] == "N2":
                source.update(scope="official_access_challenge_no_article", article_body_acquired=False,
                              classification_reason="HTTP 200 body contains Request unsuccessful / Incapsula challenge, not article text.",
                              retry_or_bypass_attempted=False)
        acquisition.update(production_corpus_modified=True, modification_scope="N1 source version only; no new claims/rules",
                           frozen_claims_release_and_packet_unchanged=True)
        write(PUBLIC / "method_source_round2.json", acquisition)
        print(json.dumps({k: result[k] for k in ("source_version_id", "span_count", "page_count", "identity_status", "new_active_claims")}, ensure_ascii=False))
    finally:
        w.close()


if __name__ == "__main__":
    main()
