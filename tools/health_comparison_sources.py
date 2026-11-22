"""Acquire the explicitly requested public sources, preserving receipt and rights states.

No private health inputs are accepted. Existing full text is reused. New scholarly
full text follows the established Acquirer identity and component-rights checks.
Apple documents are retained for local manual review; download alone grants no
index or scientific claim permission.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlencode

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.acquisition import EUROPE, Acquirer, identity_check, parse_jats
from healthzip.knowledge.rights import PARSER_VERSION
from healthzip.knowledge.store import now

SOURCES = [
    {"source_id": "HC-APPLE-HEART-2024", "title": "Heart Rate, Calorimetry, and Activity on Apple Watch", "year": 2024,
     "canonical_url": "https://www.apple.com/health/pdf/Heart_Rate_Calorimetry_Activity_on_Apple_Watch_November_2024.pdf"},
    {"source_id": "HC-APPLE-RHR-FIELD", "title": "restingHeartRate", "canonical_url": "https://developer.apple.com/documentation/healthkit/hkquantitytypeidentifier/restingheartrate",
     "download_url": "https://developer.apple.com/tutorials/data/documentation/healthkit/hkquantitytypeidentifier/restingheartrate.json"},
    {"source_id": "HC-APPLE-SDNN-FIELD", "title": "heartRateVariabilitySDNN", "canonical_url": "https://developer.apple.com/documentation/healthkit/hkquantitytypeidentifier/heartratevariabilitysdnn",
     "download_url": "https://developer.apple.com/tutorials/data/documentation/healthkit/hkquantitytypeidentifier/heartratevariabilitysdnn.json"},
    {"source_id": "HC-CARTER-HRV-2026", "title": "Guidelines for Rigor and Reproducibility of Heart Rate Variability within Human Cardiovascular Research", "year": 2026,
     "doi": "10.1152/ajpheart.00041.2026", "pmcid": "PMC13477148"},
    {"source_id": "HC-APPLE-SLEEP-2025", "title": "Estimating Sleep Stages from Apple Watch", "year": 2025,
     "canonical_url": "https://www.apple.com/health/pdf/Estimating_Sleep_Stages_from_Apple_Watch_Oct_2025.pdf"},
    {"source_id": "HC-ROBBINS-SLEEP-2024", "title": "Accuracy of Three Commercial Wearable Devices for Sleep Tracking in Healthy Adults", "year": 2024,
     "doi": "10.3390/s24206532"},
    {"source_id": "HC-PLEWS-COMPLIANCE-2014", "title": "Monitoring training with heart-rate variability: how much compliance is needed for valid assessment?", "year": 2014,
     "doi": "10.1123/ijspp.2013-0455", "pmid": "24334285"},
    {"source_id": "HC-DAVIS-WILSON-MISSING-2025", "title": "Effects of Missing Data on Heart Rate Variability Measured From A Smartwatch: Exploratory Observational Study", "year": 2025,
     "doi": "10.2196/53645"},
    {"source_id": "HC-BELLENGER-2016", "title": "Contextualizing Parasympathetic Hyperactivity in Functionally Overreached Athletes With Perceptions of Training Tolerance", "year": 2016,
     "doi": "10.1123/ijspp.2015-0495", "pmid": "26640275"},
    {"source_id": "HC-ALAVI-STRESS-2021", "title": "Real-time alerting system for COVID-19 and other stress events using wearable data", "year": 2022,
     "doi": "10.1038/s41591-021-01593-2", "pmcid": "PMC8799466"},
    {"source_id": "HC-AASM-ADULT-SLEEP-2015", "title": "Recommended Amount of Sleep for a Healthy Adult: A Joint Consensus Recommendation of the American Academy of Sleep Medicine and Sleep Research Society", "year": 2015,
     "doi": "10.5664/jcsm.4758", "pmcid": "PMC4442216"},
]


def acquire(root, output):
    w = KnowledgeWorkbench(root)
    receipts = []
    try:
        a = Acquirer(w.lib)
        for source in SOURCES:
            source = {"corpus_roles": ["research"], **source}
            source.setdefault("canonical_url", "https://doi.org/" + source.get("doi", ""))
            w.lib.seed({"sources": [source]}, {"cards": []})
            canonical = w.lib.source(source["source_id"])["source_id"]
            source["source_id"] = canonical
            existing = w.lib.sources.execute("SELECT version_id FROM version WHERE source_id=? AND material_type='fulltext'", (canonical,)).fetchall()
            result = {"source_id": canonical, "canonical_url": source["canonical_url"]}
            if existing:
                result.update(status="reused_existing_fulltext", version_ids=[r[0] for r in existing])
            elif "doi" not in source:
                try:
                    raw, receipt = a.request(source.get("download_url", source["canonical_url"]), canonical)
                    if raw.startswith(b"%PDF"):
                        from healthzip.knowledge.documents import parse_pdf
                        metadata, spans = parse_pdf(raw)
                        parser = "pdfplumber-layout-1.3.0"
                    else:
                        value = json.loads(raw)
                        metadata, spans, parser = {"title": value.get("metadata", {}).get("title")}, [], "apple-docc-json-1"
                    version = w.lib.record_version(canonical, raw, "fulltext", receipt, metadata,
                        {"index_allowed": False, "status": "official_document_terms_review_required", "redistribution_allowed": False},
                        "pending", spans, parser)
                    result.update(status="fulltext_received_pending_identity_and_rights_review", version_id=version, byte_length=len(raw))
                except Exception as exc:
                    result.update(status="failed", reason=type(exc).__name__ + ":" + str(exc)[:250])
            else:
                result.update(a.acquire_one(canonical, fulltext=True))
                # Official Europe PMC provides a second lawful JATS route; same
                # identity/body/rights checks apply, no HTML challenge bypass.
                if result.get("fulltext", {}).get("status") != "fulltext_fetched":
                    try:
                        search, _ = a.request(EUROPE + "search?" + urlencode({"query": "DOI:" + source["doi"], "format": "json", "pageSize": 1}), canonical)
                        rows = json.loads(search).get("resultList", {}).get("result", [])
                        pmcid = next((r["pmcid"] for r in rows if r.get("pmcid") and r.get("doi", "").lower() == source["doi"].lower()), None)
                        if not pmcid:
                            raise ValueError("official_index_has_no_matching_pmc_fulltext")
                        raw, receipt = a.request(EUROPE + pmcid + "/fullTextXML", canonical)
                        metadata, spans, rights = parse_jats(raw)
                        status, conflicts = identity_check(source, metadata)
                        if b"<body" not in raw:
                            raise ValueError("response_has_no_article_body")
                        version = w.lib.record_version(canonical, raw, "fulltext", receipt, metadata, rights, status, spans, PARSER_VERSION)
                        result["europe_pmc"] = {"status": "fulltext_fetched", "version_id": version, "identity_status": status, "identity_conflicts": conflicts,
                            "index_allowed": rights.get("index_allowed"), "span_count": len(spans), "license": rights.get("license_id")}
                    except Exception as exc:
                        result["europe_pmc"] = {"status": "unavailable", "reason": type(exc).__name__ + ":" + str(exc)[:250]}
            receipts.append(result)
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(json.dumps({"schema": "health-comparison-source-acquisition-1", "created_at": now(), "public_sources_only": True,
                "scientific_review": "separate_explicit_step", "results": receipts}, ensure_ascii=False, indent=2) + "\n")
            print(canonical, result.get("status") or result.get("europe_pmc", result.get("fulltext", {})).get("status"), flush=True)
    finally:
        w.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=".local/knowledge")
    p.add_argument("--output", default="artifacts/health_comparison/source-acquisition.json")
    args = p.parse_args()
    acquire(args.root, args.output)
