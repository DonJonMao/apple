"""Reproduce the rights-cleared M2 source import and optional explanation release.

Original source bytes are required in .local. Public outputs contain only source
identity, exact locators/hashes, rights records and original summaries/drafts.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from lxml import html

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.acquisition import identity_check
from healthzip.knowledge.store import digest, now

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'src/healthzip').is_dir())
CACHE = ROOT / '.local/knowledge/method_discovery_round3'
PARSER = 'pdfplumber-reviewed-m2-regions-1.4.0'
PDF_SHA = '0a7abf1ff40f4fad98efe97afa42b7187a7d893ac55847596403999afdb857e0'
PAGE_SHA = '543b31f5bfbf3fe204ca5dd2c42d623d9ea37d8eb90f516b547a422f98e800e9'
CROSSREF_SHA = '01ce9a4b81c95bec91fb265946a33b3e144c49ecf8c9f3070576b1eedf493d91'


def write(path, value):
    if path.exists():
        if json.loads(path.read_text()) == value:
            return
        if path.name != "method_source_round3.json":
            raise ValueError("published method artifact immutable; use a new version")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def report_frozen_hashes(path, current):
    """Keep the original report's audit boundary when later files are added."""
    if not path.exists():
        return current
    original = json.loads(path.read_text())["frozen_artifact_sha256"]
    if any(current.get(name) != sha for name, sha in original.items()):
        raise ValueError("artifact from the original method audit changed")
    return original


def checked_bytes(name, sha):
    raw = (CACHE / name).read_bytes()
    if digest(raw) != sha:
        raise ValueError('reviewed bytes changed: ' + name)
    return raw


def frozen_hashes():
    """Protect all pre-existing evaluation evidence and the 17-claim public release."""
    paths = {ROOT / "artifacts/v14/knowledge" / name for name in
             ("release.json", "core_claims.jsonl", "advice_rules.jsonl")}
    for pattern in ("artifacts/v14/knowledge/independent*",
                    "artifacts/v14/knowledge/rag_*.json",
                    ".local/v14-knowledge-independent*/*",
                    ".local/v14-knowledge-evaluation/independent*"):
        paths.update(p for p in ROOT.glob(pattern) if p.is_file())
    paths.update(ROOT / "src/healthzip/knowledge/data" / name
                 for name in ("rag_eval_cases.json", "rag_holdout.json"))
    return {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(paths)}


def review_m2():
    import pdfplumber

    raw = checked_bytes('M2-tue-pdf.raw', PDF_SHA)
    page = html.fromstring(checked_bytes('M2-tue-page.raw', PAGE_SHA))
    grant = json.loads(checked_bytes('M2-crossref.raw', CROSSREF_SHA))['message']
    if not page.xpath('//a[@href="http://creativecommons.org/licenses/by/4.0/"]'):
        raise ValueError('reviewed repository CC-BY license link absent')
    if not any(x.get('content-version') == 'vor' and x.get('URL') == 'http://creativecommons.org/licenses/by/4.0/' for x in grant['license']):
        raise ValueError('reviewed version-of-record license absent')
    selected = [{'name': 'context_boundaries', 'file_page_index': 3, 'printed_page': 203, 'bounding_box': [302, 110, 554, 252], 'text_hash': '706d441cfce9fdd6ed149aabb793b704e8d4685fc1a0693b5f02ea426a29b577'}, {'name': 'non_significance', 'file_page_index': 3, 'printed_page': 203, 'bounding_box': [302, 252, 554, 472], 'text_hash': '02ba296b5d11010d11410f10fd6979ad64f23be38ed88e15f4c5630d2eb11b6f'}, {'name': 'equivalence_definition', 'file_page_index': 3, 'printed_page': 203, 'bounding_box': [302, 538, 554, 604], 'text_hash': '6a12613203d36a36af1fff483db3af016e384549569950767ec53d2a2af8bb5e'}, {'name': 'tost_logic', 'file_page_index': 4, 'printed_page': 204, 'bounding_box': [40, 46, 292, 263], 'text_hash': '6d397fb24f600535f504030e7ebb97efabc599b56dbcfc6218b8ec131b4eaa94'}, {'name': 'design_scope_a', 'file_page_index': 8, 'printed_page': 208, 'bounding_box': [302, 677, 554, 731], 'text_hash': 'c3055785aea537d8f545d3e1bcdf96ef1f47ad676f09b88bbcd735343426f487'}, {'name': 'design_scope_b', 'file_page_index': 9, 'printed_page': 209, 'bounding_box': [40, 305, 292, 369], 'text_hash': 'ad5762334bebc4ac44fa5acc00ddc33ffdba9260acde39eec866b9603cf91565'}]
    spans = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        if len(pdf.pages) != 13:
            raise ValueError('expected one repository cover and twelve article pages')
        cover = pdf.pages[0].extract_text(x_tolerance=1)
        first = pdf.pages[1].extract_text(x_tolerance=1)
        if not all(s in cover for s in ('CC BY', 'Publisher’s PDF', '10.1113/EP090171')) or '10.1113/EP090171' not in first:
            raise ValueError('PDF identity/license/version check failed')
        for fragment in selected:
            text = pdf.pages[fragment['file_page_index']].crop(tuple(fragment['bounding_box'])).extract_text(x_tolerance=1, y_tolerance=3)
            if digest(text.encode()) != fragment['text_hash']:
                raise ValueError('reviewed region text changed: ' + fragment['name'])
            spans.append({'kind': 'paragraph', 'text': text,
                          'section_path': 'Method review / ' + fragment['name'],
                          'locator': {'file_page_index': fragment['file_page_index'],
                                      'printed_page': fragment['printed_page'],
                                      'bounding_box': fragment['bounding_box'],
                                      'coordinate_system': 'pdf_points_top_left',
                                      'extraction_method': 'pdfplumber_reviewed_single_column_region',
                                      'start_offset': 0, 'end_offset': len(text), 'language': 'en'},
                          'structured': {'numeric_review_status': 'not_approved_for_numeric_parameters',
                                         'ocr_used': False, 'table_overlap_indices': [],
                                         'continuation_group': 'equivalence_definition' if fragment['name'] in {'equivalence_definition', 'tost_logic'} else 'design_scope' if fragment['name'].startswith('design_scope') else None}})
    metadata = {'title': grant['title'][0], 'doi': '10.1113/EP090171',
                'authors': ['Raffaele Mazzolari', 'Simone Porcelli', 'David J. Bishop', 'Daniël Lakens'],
                'publication_years': [2022], 'journal': 'Experimental Physiology',
                'volume': 107, 'issue': 3, 'printed_pages': '201-212', 'page_count': 13,
                'manifestation': 'publisher_version_of_record_with_repository_cover',
                'content_review': {'reviewer_kind': 'ai_assisted', 'read_file_page_indices': list(range(13)),
                                   'article_file_page_indices': list(range(1, 13)),
                                   'reviewed_regions': [x['name'] for x in selected],
                                   'parse_scope': 'six selected prose regions; whole article read, not entirely indexed',
                                   'formula_transcription_verified': False,
                                   'numeric_table_parameters_activated': False},
                'identity_review': {'decision': 'matched', 'reviewer_kind': 'ai_assisted',
                                    'reviewer': 'Codex source review',
                                    'rationale': 'Repository cover identifies publisher version; article title, DOI, authors, year and continuous printed pages 201-212 match M2.'},
                'claim_activation': 'none'}
    rights = {'status': 'official_repository_version_license_reviewed', 'license_id': 'CC-BY-4.0',
              'license_url': 'http://creativecommons.org/licenses/by/4.0/',
              'evidence_url': 'https://research.tue.nl/en/publications/dfb93c9c-6529-4233-82a6-c87774e91752',
              'rights_evidence_sha256': PAGE_SHA, 'publisher_grant_sha256': CROSSREF_SHA,
              'reviewer_kind': 'ai_assisted', 'index_allowed': True, 'redistribution_allowed': True,
              'rights_scope': 'Article version of record only; repository administrative cover excluded from evidence spans.',
              'public_export_scope': 'metadata, locators, hashes and original review summaries only',
              'attribution': 'Mazzolari R, Porcelli S, Bishop DJ, Lakens D (2022). Myths and methodologies: The use of equivalence and non-inferiority tests for interventional studies in exercise physiology and sport science. Experimental Physiology 107(3):201-212. https://doi.org/10.1113/EP090171'}
    return raw, metadata, rights, spans


def explanation_contract():
    definition = json.loads((ROOT / "src/healthzip/knowledge/data/method_equivalence.json").read_text())
    version = definition["source_version_id"]
    parts = [{"part_id": p["part_id"], "text": p["text"],
              "span_ids": [version + f":s{i:05d}" for i in p["span_indices"]],
              "evidence_relation": p["evidence_relation"]}
             for p in definition["answer_parts"]]
    claim = {"claim_id": definition["claim_id"], "version": definition["version"],
             "statement": "\n".join(p["text"] for p in parts), "scope": definition["scope"],
             "limitations": definition["limitations"], "numeric": False,
             "evidence_links": [{"source_id": "M2", "source_version_id": version,
                                 "span_ids": [version + f":s{i:05d}" for i in range(6)]}],
             "answer_task": {**{k: definition[k] for k in ("subject", "outcome", "requested_relation")},
                             "evidence_relation": "supports", "answer_complete": True,
                             "required_answer_parts": [p["part_id"] for p in parts],
                             "routes": definition["routes"], "answer_parts": parts}}
    rule = {"rule_id": definition["rule_id"], "rule_version": definition["version"],
            "requested_capability": "source_explanation",
            "capability_policy_version": "personal-trial-policy-1.4.0",
            "claim_refs": [{"claim_id": claim["claim_id"], "version": claim["version"]}],
            "routes": definition["routes"], "permitted_actions": [], "numeric_provenance": [],
            "conditions": [{"field": "requested_capability", "op": "eq",
                            "value": "source_explanation", "origin": "product_scope"}],
            "coverage_scope": "general_equivalence_method_explanation_only",
            "application_logic": "解释不显著、情境化界值、TOST及原文研究设计范围；个人判断缺少界值、误差或模型时说明缺项，不输出个人阈值、等效结论、停滞标签或训练候选。",
            "limits": definition["limitations"],
            "remaining_source_gaps": definition["remaining_personal_inference_gaps"],
            "forbidden": ["numeric_training_candidate", "individual_equivalence_inference",
                          "plateau_confirmation", "individual_prediction", "causal_effect"],
            "implementation_validation_refs": [
                "tests/unit/test_method_equivalence_contract.py",
                "tests/unit/test_v14_knowledge_coverage.py::test_explanation_rule_never_becomes_candidate_authority",
                "src/healthzip/knowledge/core.py::core_principles"]}
    return definition, claim, rule


def reviewed_record(w, table, field, identifier, version, *, application=False):
    row = w.lib.theories.execute(
        f"SELECT review_json FROM {table} WHERE {field}=? AND version=?", (identifier, version)
    ).fetchone()
    if row:
        return json.loads(row[0])
    return {"reviewer": "Codex method source and application review", "reviewer_kind": "ai_assisted",
            "reviewed_at": now(), "independent_expert_validation": False,
            "application_checked" if application else "content_checked": True,
            "rationale": (
                "Checked exact six M2 regions and their continuation across printed pages 203/204 and 208/209. "
                "First four regions directly support non-significance, contextual margins and TOST; last two qualify design scope. "
                "Personal time-series applicability is explicitly an unvalidated product extrapolation. "
                "No personal calibration is needed to explain this general method, and no personal numerical authority is granted."
            )}


def theory_snapshot(w):
    return {name: [dict(r) for r in w.lib.theories.execute(f"SELECT * FROM {name} ORDER BY 1,2")]
            for name in ("source_claim", "application_rule", "core_release")}


def assert_existing_unchanged(before, after):
    for table, rows in before.items():
        for row in rows:
            if row not in after[table]:
                raise ValueError("pre-existing immutable knowledge record changed: " + table)


def existing_or_create_release(w, release_id):
    """Read a frozen release on rerun, even when later claims have been added."""
    row = w.lib.theories.execute(
        "SELECT manifest_json,sha256 FROM core_release WHERE release_id=?", (release_id,)
    ).fetchone()
    if row:
        if digest(row["manifest_json"].encode()) != row["sha256"]:
            raise ValueError("stored immutable release hash mismatch")
        return {"release_id": release_id, "sha256": row["sha256"],
                **json.loads(row["manifest_json"])}
    return w.release_core(release_id)


def verify_stored_source(w, version, raw, rights, spans):
    row = w.lib.sources.execute("SELECT * FROM version WHERE version_id=?", (version,)).fetchone()
    if not row or row["sha256"] != digest(raw) or row["identity_status"] != "matched":
        raise ValueError("stored M2 source identity differs from reviewed bytes")
    if json.loads(row["rights_json"]) != rights:
        raise ValueError("stored M2 rights differ from reviewed grant")
    stored = w.lib.sources.execute("SELECT span_id FROM span WHERE version_id=?", (version,)).fetchall()
    if len(stored) != len(spans):
        raise ValueError("stored M2 span count differs from six reviewed regions")
    for i, expected in enumerate(spans):
        span = w.lib.span(version + f":s{i:05d}")
        if span["text_hash"] != digest(expected["text"].encode()) or json.loads(span["locator_json"]) != expected["locator"]:
            raise ValueError("stored M2 reviewed span differs")
        if not w.lib.eligible(span, "fulltext")[0]:
            raise ValueError("reviewed M2 fulltext region is ineligible")


def assert_public_projection(value, spans):
    """Inspect decoded strings, including source prose escaped inside nested JSON."""
    def strings(item):
        if isinstance(item, str):
            yield item
            if item.lstrip().startswith(("{", "[")):
                try:
                    nested = json.loads(item)
                except json.JSONDecodeError:
                    pass
                else:
                    yield from strings(nested)
        elif isinstance(item, dict):
            for child in item.values():
                yield from strings(child)
        elif isinstance(item, list):
            for child in item:
                yield from strings(child)

    public = " ".join(" ".join(s.split()) for s in strings(value))
    for span in spans:
        source = " ".join(span["text"].split())
        if source[:120] in public:
            raise ValueError("public output contains source body text")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/v14/knowledge")
    parser.add_argument("--activate-explanation", action="store_true",
                        help="Review the separate 1.4.4 explanation claim/rule and create a new immutable release.")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frozen_before = frozen_hashes()
    raw, metadata, rights, spans = review_m2()
    definition, claim, rule = explanation_contract()
    w = KnowledgeWorkbench(ROOT / ".local/knowledge")
    output = {}
    try:
        before = theory_snapshot(w)
        status, conflicts = identity_check(w.lib.source("M2")["manifest"], metadata)
        if status != "matched":
            raise ValueError("M2 identity mismatch: " + str(conflicts))
        receipt = json.loads((CACHE / "M2-tue-pdf.receipt.json").read_text())
        version = w.lib.record_version("M2", raw, "fulltext", receipt, metadata, rights, status, spans, PARSER)
        if version != definition["source_version_id"]:
            raise ValueError("unexpected M2 source version identity")
        verify_stored_source(w, version, raw, rights, spans)
        if theory_snapshot(w) != before:
            raise ValueError("source-only import mutated claims, rules or releases")
        review_path = args.output_dir / "M2_method_review.json"
        report = {
            "source_id": "M2", "source_version_id": version, "source_imported": True,
            "raw_sha256": PDF_SHA, "byte_length": len(raw), "page_count": 13,
            "article_page_count": 12, "repository_cover_pages": 1, "span_count": len(spans),
            "parser_version": PARSER, "rights": rights, "identity_review": metadata["identity_review"],
            "content_review": metadata["content_review"],
            "reviewed_locators": [{"span_id": version + f":s{i:05d}",
                                   "text_hash": digest(s["text"].encode()), "locator": s["locator"]}
                                  for i, s in enumerate(spans)],
            "review_summary": [p["text"] for p in definition["answer_parts"]],
            "source_only_import_claim_rule_release_mutations": 0,
            "personal_calibration_supplied": False, "independent_human_or_expert_reviews": 0,
            "remaining_personal_inference_gaps": definition["remaining_personal_inference_gaps"],
            "frozen_artifact_sha256": report_frozen_hashes(review_path, frozen_before),
            "separate_explanation_contract": "method_explanation-1.4.4.json"
        }
        output[review_path] = report
        discovery = json.loads((CACHE / "staged_public/method_source_round3.json").read_text())
        discovery["method_results"]["M2"] = (
            "Rights-cleared version of record imported as six exact prose regions; "
            "the source import itself changed no claims, rules or releases. "
            "The separately reviewed general explanation is recorded in method_explanation-1.4.4.json."
        )
        active_method = w.lib.theories.execute(
            "SELECT status FROM source_claim WHERE claim_id=? AND version=?",
            (claim["claim_id"], claim["version"])).fetchone()
        active = args.activate_explanation or bool(active_method and active_method[0] == "verified")
        discovery.update(source_import_completed=True, source_import_artifact="M2_method_review.json",
                         new_source_claims_activated=int(active), new_application_rules_activated=int(active),
                         new_explanation_release=definition["release_id"] if active else None,
                         frozen_release_unchanged=True)
        discovery["notes"][0] = (
            "M2 formal article accessibility is closed; a separate general-method explanation "
            "is available in 1.4.4. Personal thresholds, time-series calibration and plateau inference remain unapproved."
            if active else "M2 formal article accessibility is closed; explanation activation is a separate operation."
        )
        output[args.output_dir / "method_source_round3.json"] = discovery
        output[args.output_dir / "N2_repository_review.json"] = json.loads(
            (CACHE / "staged_public/N2_repository_review.json").read_text())
        if args.activate_explanation:
            content_review = reviewed_record(w, "source_claim", "claim_id", claim["claim_id"], claim["version"])
            application_review = reviewed_record(w, "application_rule", "rule_id", rule["rule_id"], rule["rule_version"], application=True)
            w.review_claim(claim, content_review)
            w.review_rule(rule, application_review)
            release = existing_or_create_release(w, definition["release_id"])
            if any(p["rule_id"] == rule["rule_id"] for p in w.reviewed_principles("progression", {"requested_capability": "source_explanation"})["principles"]):
                raise ValueError("method explanation acquired candidate authority")
            output[args.output_dir / "release-1.4.4.json"] = release
            output[args.output_dir / "method_explanation-1.4.4.json"] = {
                "claim": claim, "content_review": content_review, "rule": rule,
                "application_review": application_review, "source_corpus_roles": w.lib.source("M2")["manifest"]["corpus_roles"],
                "release_id": release["release_id"], "release_sha256": release["sha256"],
                "claims_in_release": len(release["claims"]), "rules_in_release": len(release["rules"]),
                "candidate_rule_count": w.core_status()["effective_candidate_rule_count"],
                "personal_calibration_supplied": False, "independent_human_or_expert_reviews": 0,
                "frozen_artifact_sha256": report_frozen_hashes(
                    args.output_dir / "method_explanation-1.4.4.json", frozen_before),
                "previous_release_records_unchanged": True,
            }
        assert_existing_unchanged(before, theory_snapshot(w))
        if frozen_before != frozen_hashes():
            raise ValueError("frozen release or independent evaluation artifact changed")
        for path, value in output.items():
            assert_public_projection(value, spans)
            write(path, value)
        print(json.dumps({"source_version_id": version, "source_imported": True,
                          "span_count": len(spans), "explanation_activated": args.activate_explanation,
                          "release_id": definition["release_id"] if args.activate_explanation else None,
                          "previous_records_and_evaluations_unchanged": True}, ensure_ascii=False))
    finally:
        w.close()


if __name__ == "__main__":
    main()
