"""Official metadata/JATS acquisition, explicit rights gates and reproducible receipts."""

from __future__ import annotations

import json
import re
import time
from difflib import SequenceMatcher
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from lxml import etree

from .rights import PARSER_VERSION, owned_subtree, owner, rights_for_node, rights_from_xml
from .store import Libraries, now

OAI = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"
EUROPE = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
CROSSREF = "https://api.crossref.org/works/"
XML_PARSER = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)
POLICY = {
    "version": "acquisition-1.3.1", "declared_use": "local_internal_noncommercial_research_and_retrieval",
    "provider_min_interval_seconds": {"pmc.ncbi.nlm.nih.gov": 0.4, "eutils.ncbi.nlm.nih.gov": 0.4,
                                      "api.crossref.org": 1.0, "www.ebi.ac.uk": 0.4},
    "max_attempts": 2, "timeout_seconds": 18, "max_response_bytes": 20_000_000,
    "note": "Operational rate/backoff settings, not physiological parameters. PMC requests are sequential.",
}


def _text(node) -> str:
    return " ".join(" ".join(node.itertext()).split()) if node is not None else ""


def _norm_title(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def identity_check(expected: dict, actual: dict) -> tuple[str, list[str]]:
    conflicts = []
    matched_id = False
    for key in ("doi", "pmid", "pmcid"):
        if expected.get(key) and actual.get(key):
            if str(expected[key]).lower() != str(actual[key]).lower():
                conflicts.append(key + "_mismatch")
            else:
                matched_id = True
    title_a, title_b = _norm_title(expected.get("title", "")), _norm_title(actual.get("title", ""))
    # Identity fuzzy tolerance only flags a review candidate, never merges canonical records.
    if title_a and title_b and SequenceMatcher(None, title_a, title_b).ratio() < 0.9:
        conflicts.append("title_mismatch")
    years = actual.get("publication_years") or []
    if expected.get("year") and years and expected["year"] not in years:
        conflicts.append("year_mismatch")
    if conflicts:
        return "conflict", conflicts
    return ("matched" if matched_id and title_b else "pending"), conflicts


def parse_jats(raw: bytes) -> tuple[dict, list[dict], dict]:
    root = etree.fromstring(raw, parser=XML_PARSER)
    articles = root.xpath("//*[local-name()='article']")
    article = articles[0] if articles else root
    tree = article.getroottree()
    rights = rights_from_xml(article)
    meta_nodes = article.xpath("./*[local-name()='front']/*[local-name()='article-meta']")
    meta = meta_nodes[0] if meta_nodes else article
    metadata: dict[str, Any] = {"publication_years": [], "authors": [], "relations": []}
    titles = meta.xpath(".//*[local-name()='article-title']")
    metadata["title"] = _text(titles[0]) if titles else ""
    for el in meta.xpath(".//*[local-name()='article-id']"):
        kind = el.get("pub-id-type")
        if kind in {"doi", "pmid", "pmc"}:
            value = _text(el)
            metadata["pmcid" if kind == "pmc" else kind] = ("PMC" + value.removeprefix("PMC")) if kind == "pmc" else value
    for node in meta.xpath(".//*[local-name()='pub-date']"):
        years = node.xpath("./*[local-name()='year']/text()")
        for year in years:
            if year.isdigit():
                metadata["publication_years"].append(int(year))
    for node in meta.xpath(".//*[local-name()='contrib'][@contrib-type='author']"):
        metadata["authors"].append(_text(node))
    for node in article.xpath(".//*[local-name()='related-article']"):
        metadata["relations"].append(dict(node.attrib))
    spans = []
    # Preserve each evidence unit and its native source locator, including tables and equations.
    for node in article.xpath(".//*[local-name()='p' or local-name()='table-wrap' or local-name()='disp-formula']"):
        if any(etree.QName(a).localname in {"permissions", "license"}
               or etree.QName(a).localname in {"table-wrap", "disp-formula"} and owner(a, article) is owner(node, article)
               for a in node.iterancestors()):
            continue
        original = node
        node = owned_subtree(node)
        kind = {"p": "paragraph", "table-wrap": "table", "disp-formula": "formula"}[etree.QName(node).localname]
        text = _text(node)
        if not text:
            continue
        sections = []
        for ancestor in reversed(list(original.iterancestors())):
            if etree.QName(ancestor).localname in {"sec", "abstract", "app"}:
                ts = ancestor.xpath("./*[local-name()='title']")
                sections.append(_text(ts[0]) if ts else etree.QName(ancestor).localname)
        structured = {}
        if kind == "table":
            rows = [[_text(c) for c in r.xpath("./*[local-name()='th' or local-name()='td']")] for r in node.xpath(".//*[local-name()='tr']")]
            structured = {"caption": " ".join(_text(n) for n in node.xpath("./*[local-name()='caption']")),
                          "rows": rows, "cells": [{"row": r, "column": c, "text": value} for r, row in enumerate(rows) for c, value in enumerate(row)],
                          "footnotes": [_text(n) for n in node.xpath(".//*[local-name()='fn']")],
                          "raw_xml": etree.tostring(node, encoding="unicode"),
                          "units": None, "population": None, "analysis_set": None, "outcome_timepoint": None,
                          "numeric_review_status": "pending", "merged_cells": "preserved_in_raw_xml_not_inferred"}
        elif kind == "formula":
            structured = {"raw_xml": etree.tostring(node, encoding="unicode"), "variable_dictionary": None,
                          "units": None, "assumptions": None, "execution_authority": "none_pending_review"}
        spans.append({"kind": kind, "section_path": "/".join(sections), "text": text,
                      "locator": {"xpath": tree.getpath(original), "native_id": original.get("id"),
                                  "paragraph_id": len(spans), "start_offset": 0, "end_offset": len(text),
                                  "language": article.get("{http://www.w3.org/XML/1998/namespace}lang", "und"),
                                  "extraction_method": PARSER_VERSION}, "structured": structured,
                      "rights": rights_for_node(original, article, rights)})
    return metadata, spans, rights


class Acquirer:
    def __init__(self, libraries: Libraries, *, contact: str = "", timeout: float = 18):
        self.lib = libraries
        self.contact = contact
        self.timeout = timeout
        self.last_request: dict[str, float] = {}

    def request(self, url: str, source_id: str | None = None, method: str = "GET") -> tuple[bytes, dict]:
        host = urlparse(url).hostname or ""
        if urlparse(url).scheme != "https" or not host:
            raise ValueError("acquisition requires HTTPS")
        for attempt in range(POLICY["max_attempts"]):
            delay = POLICY["provider_min_interval_seconds"].get(host, 1.0)
            time.sleep(max(0.0, self.last_request.get(host, 0) + delay - time.monotonic()))
            self.last_request[host] = time.monotonic()
            headers = {"User-Agent": "HealthZIP/1.3 public-evidence-research" + (" (mailto:" + self.contact + ")" if self.contact else ""),
                       "Accept": "application/json, application/xml, text/xml, */*"}
            try:
                with urlopen(Request(url, headers=headers, method=method), timeout=self.timeout) as response:
                    raw = response.read(POLICY["max_response_bytes"] + 1)
                    if len(raw) > POLICY["max_response_bytes"]:
                        raise ValueError("response_size_limit")
                    receipt = {"url": url, "resolved_url": response.url, "http_status": response.status,
                               "etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified"),
                               "content_type": response.headers.get("Content-Type"), "fetched_at": now(), "attempt": attempt + 1,
                               "method": method, "provider_policy": POLICY["version"]}
                    self.lib.log(source_id, "http_success", receipt)
                    return raw, receipt
            except HTTPError as exc:
                retry = exc.code in {429, 500, 502, 503, 504} and attempt + 1 < POLICY["max_attempts"]
                self.lib.log(source_id, "http_failure", {"url": url, "status": exc.code, "attempt": attempt + 1, "will_retry": retry})
                if retry:
                    try:
                        seconds = float(exc.headers.get("Retry-After", "1"))
                    except ValueError:
                        seconds = 1.0
                    if seconds > 60:
                        raise RuntimeError(f"deferred_retry_after:{seconds}") from exc
                    time.sleep(max(0, seconds))
                    continue
                raise
            except (URLError, TimeoutError, OSError) as exc:
                self.lib.log(source_id, "network_failure", {"url": url, "error": type(exc).__name__, "message": str(exc)[:300]})
                raise
        raise RuntimeError("retry_exhausted")

    def smoke_test(self) -> list[dict]:
        urls = {"pmc_oai": OAI + "?verb=Identify", "europe_pmc": EUROPE + "search?query=EXT_ID:9528903&format=json&pageSize=1",
                "crossref": CROSSREF + "10.7717/peerj.14142", "pubmed": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi?db=pubmed&retmode=json"}
        output = []
        for provider, url in urls.items():
            try:
                raw, receipt = self.request(url)
                output.append({"provider": provider, "status": "reachable", "byte_length": len(raw), "receipt": receipt})
            except Exception as exc:
                output.append({"provider": provider, "status": "unavailable", "reason": str(exc)[:300]})
        self.lib.log(None, "provider_smoke_test", {"results": output, "policy": POLICY})
        return output

    def crossref(self, source: dict) -> dict:
        sid = source["source_id"]
        url = CROSSREF + quote(source["doi"], safe="")
        if self.contact:
            url += "?" + urlencode({"mailto": self.contact})
        raw, receipt = self.request(url, sid)
        value = json.loads(raw)["message"]
        metadata = {"doi": value.get("DOI"), "title": " ".join(value.get("title", [])), "authors": value.get("author", []),
                    "publication_dates": {k: value[k] for k in ("published", "published-print", "published-online", "issued") if k in value},
                    "publication_years": list({v["date-parts"][0][0] for k, v in value.items() if k in {"published", "published-print", "published-online", "issued"} and v.get("date-parts")}),
                    "license_candidates": value.get("license", []), "relations": value.get("relation", {}),
                    "updates": value.get("update-to", []), "updates_checked_at": now(),
                    "update_check_limit": "absence of Crossref flags is not proof of no correction/retraction"}
        status, conflicts = identity_check(source, metadata)
        metadata["identity_conflicts"] = conflicts
        version = self.lib.record_version(sid, raw, "metadata", receipt, metadata,
                    {"status": "metadata_only", "index_allowed": False, "abstract_rights": "not_inferred_from_metadata_license"}, status)
        updates = metadata["updates"]
        if any("retract" in str(x.get("type", "")).lower() for x in updates):
            self.lib.update_state(sid, "withdrawn", "Crossref update relation requires review", {"updates": updates})
        elif updates:
            self.lib.update_state(sid, "corrected_pending_review", "Crossref update relation requires review", {"updates": updates})
        return {"source_id": sid, "metadata_version_id": version, "identity_status": status, "identity_conflicts": conflicts}

    def pubmed(self, source: dict) -> dict:
        query = {"db": "pubmed", "id": str(source["pmid"]), "retmode": "xml", "tool": "healthzip"}
        if self.contact:
            query["email"] = self.contact
        raw, receipt = self.request("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urlencode(query), source["source_id"])
        root = etree.fromstring(raw, parser=XML_PARSER)
        metadata = {"pmid": str(source["pmid"]), "title": " ".join(root.xpath("//ArticleTitle//text()")),
                    "publication_years": [int(x) for x in root.xpath("//PubDate/Year/text()") if x.isdigit()],
                    "publication_dates": [{"status": n.get("PubStatus"), "text": _text(n)} for n in root.xpath("//PubMedPubDate")],
                    "authors": [_text(n) for n in root.xpath("//AuthorList/Author")],
                    "publication_types": root.xpath("//PublicationType/text()"),
                    "corrections": [{"type": n.get("RefType"), "citation": _text(n), "pmid": n.findtext("PMID")} for n in root.xpath("//CommentsCorrections")],
                    "updates_checked_at": now(), "update_check_limit": "No flags means not found by this provider at this time."}
        # Reference-list ArticleIds belong to cited papers, never to this source.
        for node in root.xpath("/PubmedArticleSet/PubmedArticle/PubmedData/ArticleIdList/ArticleId"):
            key = node.get("IdType")
            if key in {"doi", "pmc"}:
                metadata["pmcid" if key == "pmc" else key] = _text(node)
        status, conflicts = identity_check(source, metadata)
        metadata["identity_conflicts"] = conflicts
        version = self.lib.record_version(source["source_id"], raw, "metadata", receipt, metadata,
                                         {"status": "metadata_and_abstract_internal_review_only", "index_allowed": False,
                                          "reason": "PubMed access does not transfer abstract copyright."}, status,
                                         parser_version="pubmed-1.3.1")
        abstract = root.xpath("//Abstract/AbstractText")
        abstract_version = None
        if abstract:
            abstract_xml = etree.tostring(root.find(".//Abstract"))
            spans = [{"kind": "paragraph", "section_path": n.get("Label", "abstract"), "text": _text(n),
                      "locator": {"xpath": root.getroottree().getpath(n), "start_offset": 0, "end_offset": len(_text(n))}}
                     for n in abstract]
            abstract_version = self.lib.record_version(source["source_id"], abstract_xml, "abstract", receipt, metadata,
                        {"status": "abstract_rights_review_required", "index_allowed": False}, status, spans,
                        parser_version="pubmed-1.3.1")
        if "Retracted Publication" in metadata["publication_types"] or any(x["type"] == "RetractionIn" for x in metadata["corrections"]):
            self.lib.update_state(source["source_id"], "withdrawn", "PubMed retraction metadata", {"corrections": metadata["corrections"]})
        elif any(x["type"] == "ErratumIn" for x in metadata["corrections"]):
            self.lib.update_state(source["source_id"], "corrected_pending_review", "PubMed correction metadata", {"corrections": metadata["corrections"]})
        return {"status": "metadata_fetched", "version_id": version, "abstract_version_id": abstract_version,
                "identity_status": status, "corrections": metadata["corrections"]}

    def fulltext(self, source: dict) -> dict:
        sid = source["source_id"]
        pmcid = source.get("pmcid")
        if not pmcid:
            candidates = self.lib.sources.execute(
                "SELECT metadata_json FROM version WHERE source_id=? AND identity_status='matched' AND material_type='metadata' ORDER BY created_at DESC", (sid,)
            ).fetchall()
            pmcids = {json.loads(r[0]).get('pmcid') for r in candidates if json.loads(r[0]).get('pmcid')}
            if len(pmcids) == 1:
                pmcid = next(iter(pmcids))
                source = {**source, 'pmcid': pmcid}
                self.lib.log(sid, 'verified_fulltext_location_discovered', {'pmcid': pmcid, 'basis': 'identity_matched_official_metadata'})
            elif len(pmcids) > 1:
                return {'status': 'identity_review_required', 'reason': 'conflicting_official_pmc_ids', 'candidates': sorted(pmcids)}
        if not pmcid:
            return self.publisher_fulltext(source)
        query = {"verb": "GetRecord", "identifier": "oai:pubmedcentral.nih.gov:" + pmcid.removeprefix("PMC"), "metadataPrefix": "pmc_fm"}
        raw, receipt = self.request(OAI + "?" + urlencode(query), sid)
        metadata, _, rights = parse_jats(raw)
        status, conflicts = identity_check(source, metadata)
        version = self.lib.record_version(sid, raw, "metadata", receipt, metadata, {**rights, "index_allowed": False}, status)
        if status != "matched":
            return {"status": "identity_review_required", "metadata_version_id": version, "conflicts": conflicts}
        if not rights["index_allowed"]:
            return {"status": "rights_review_required", "metadata_version_id": version, "rights": rights}
        query["metadataPrefix"] = "pmc"
        raw, receipt = self.request(OAI + "?" + urlencode(query), sid)
        root = etree.fromstring(raw, parser=XML_PARSER)
        errors = root.xpath("//*[local-name()='error']")
        if errors:
            return {"status": "fulltext_unavailable", "reason": _text(errors[0])}
        metadata, spans, rights = parse_jats(raw)
        status, conflicts = identity_check(source, metadata)
        if not root.xpath("//*[local-name()='body']"):
            return {"status": "fulltext_unavailable", "reason": "response has no article body"}
        version = self.lib.record_version(sid, raw, "fulltext", receipt, metadata, rights, status, spans, PARSER_VERSION)
        return {"status": "fulltext_fetched", "version_id": version, "span_count": len(spans), "rights": rights,
                "identity_status": status, "conflicts": conflicts, "theory_review": "pending"}

    def publisher_fulltext(self, source: dict) -> dict:
        """Follow publisher-deposited TDM links only with an explicit matching CC grant.

        Crossref does not grant rights: a version-specific publisher licence URL is recorded
        as the grant being relied on. Non-licence TDM policy links never open this gate.
        """
        candidates = self.lib.sources.execute("SELECT * FROM version WHERE source_id=? AND material_type='metadata' AND identity_status='matched' ORDER BY created_at DESC", (source['source_id'],)).fetchall()
        links = []
        for row in candidates:
            receipt = json.loads(row['receipt_json'])
            if 'api.crossref.org' not in receipt.get('url', ''):
                continue
            message = json.loads((self.lib.root / row['storage_uri']).read_bytes()).get('message', {})
            for grant in message.get('license', []):
                url = grant.get('URL', '')
                if 'creativecommons.org/licenses/by/' not in url:
                    continue
                for link in message.get('link', []):
                    if link.get('content-version') == grant.get('content-version') and link.get('intended-application') == 'text-mining' and link.get('content-type') in {'application/xml', 'application/pdf'}:
                        links.append((link, grant, row['version_id']))
        if not links:
            return {"status": "rights_or_location_pending", "reason": "No authorized fulltext route established; publisher/mirror URLs and generic TDM policy links are discovery only."}
        links.sort(key=lambda x: x[0].get('content-type') != 'application/xml')
        errors = []
        for link, grant, metadata_version in links:
            url = link['URL']
            if not url.startswith('https://'):
                errors.append({'url': url, 'reason': 'non_https_candidate_not_used'})
                continue
            try:
                raw, receipt = self.request(url, source['source_id'])
                rights = {'license_id': 'CC-BY', 'license_url': grant['URL'], 'status': 'publisher_deposited_version_specific_cc_grant',
                          'grant_metadata_version': metadata_version, 'index_allowed': True, 'redistribution_allowed': True,
                          'declared_use': POLICY['declared_use'], 'rights_scope': grant['content-version']}
                if link['content-type'] == 'application/pdf':
                    from .documents import parse_pdf
                    metadata, spans = parse_pdf(raw)
                    status = 'pending'
                    parser_version = 'pdfplumber-layout-1.3.0'
                else:
                    metadata, spans, embedded_rights = parse_jats(raw)
                    status, conflicts = identity_check(source, metadata)
                    metadata['identity_conflicts'] = conflicts
                    metadata['embedded_rights'] = embedded_rights
                    parser_version = PARSER_VERSION
                version = self.lib.record_version(source['source_id'], raw, 'fulltext', receipt, metadata, rights, status, spans, parser_version)
                return {'status': 'fulltext_fetched', 'version_id': version, 'identity_status': status, 'span_count': len(spans), 'rights': rights,
                        'theory_review': 'pending'}
            except Exception as exc:
                errors.append({'url': url, 'reason': str(exc)[:300]})
        return {'status': 'publisher_access_blocked', 'attempts': errors, 'retry': 'acquire --source ' + source['source_id'] + ' --fulltext'}

    def acquire_one(self, source_id: str, *, fulltext: bool = False) -> dict:
        source = self.lib.source(source_id)["manifest"]
        output = {"source_id": source["source_id"], "metadata": None, "fulltext": {"status": "not_requested"}}
        try:
            if source.get("doi"):
                output["metadata"] = self.crossref(source)
            else:
                # Check official documentation availability; HEAD does not claim fulltext receipt.
                _, receipt = self.request(source["canonical_url"], source["source_id"], method="HEAD")
                output["metadata"] = {"status": "official_url_reachable", "receipt": receipt, "identity_review": "pending", "rights": "terms_review_required"}
        except Exception as exc:
            output["metadata"] = {"status": "failed", "reason": str(exc)[:400]}
        if source.get("pmid"):
            try:
                output["pubmed"] = self.pubmed(source)
            except Exception as exc:
                output["pubmed"] = {"status": "failed", "reason": str(exc)[:400]}
        if fulltext:
            try:
                output["fulltext"] = self.fulltext(source)
            except Exception as exc:
                output["fulltext"] = {"status": "failed", "reason": str(exc)[:400]}
        self.lib.log(source["source_id"], "acquisition_result", output)
        return output
