"""JATS permissions belong to a document component, never to arbitrary descendants."""

from __future__ import annotations

import re
from copy import deepcopy

from lxml import etree

POLICY_VERSION = "jats-scoped-rights-1.4.0"
PARSER_VERSION = "jats-owned-text-1.4.1"
OWNERS = {"article", "sub-article", "fig", "table-wrap", "supplementary-material"}
LABELS = {
    "by": "CC-BY", "by-sa": "CC-BY-SA", "by-nc": "CC-BY-NC",
    "by-nc-sa": "CC-BY-NC-SA", "by-nd": "CC-BY-ND", "by-nc-nd": "CC-BY-NC-ND",
}


def text(node):
    return " ".join(" ".join(node.itertext()).split())


def owner(node, article):
    return next((x for x in [node, *node.iterancestors()] if etree.QName(x).localname in OWNERS), article)


def _article_permission(node, component):
    ancestors = list(node.iterancestors())
    if component not in ancestors:
        return False
    names = [etree.QName(x).localname for x in ancestors[:ancestors.index(component)]]
    if etree.QName(component).localname == "sub-article" and "front-stub" in names:
        return "permissions" in names and "body" not in names
    return "permissions" in names and "article-meta" in names and "front" in names and "body" not in names


def _grant(component, licenses, rights_text, *, ambiguous=False):
    tree = component.getroottree()
    scope = etree.QName(component).localname
    license_text = " ".join(text(x) for x in licenses)
    urls = []
    for node in licenses:
        urls.extend(v for child in node.iter() for v in child.attrib.values() if "creativecommons.org" in v.lower())
    urls.extend(re.findall(r"https?://creativecommons\.org/[^\s<>\"']+", license_text))
    urls = sorted(set(u.rstrip(".,;)") for u in urls))
    identified = set()
    for url in urls:
        match = re.search(r"creativecommons\.org/licenses/([a-z-]+)/", url.lower())
        if match and match[1] in LABELS:
            identified.add(LABELS[match[1]])
        elif "/publicdomain/zero/" in url.lower():
            identified.add("CC0")
    if not identified:
        for match in re.finditer(r"\bcc\s+(by(?:[- ](?:nc|nd|sa))*)\b", license_text.lower()):
            label = match[1].replace(" ", "-")
            if label in LABELS:
                identified.add(LABELS[label])
        if "this file is available for text mining" in license_text.lower():
            identified.add("PMC-explicit-text-mining-notice")
    restricted = bool(re.search(r"all rights reserved|not (?:covered|licensed)|permission (?:is )?required|reprinted with permission", rights_text, re.I))
    # Recognize explicit component-only wording, including numbered components.
    # This is a conservative syntax guard, not general natural-language legal review.
    component_name = r"(?:fig(?:ure)?s?\.?|tables?|supplement(?:ary)?(?:\s+materials?)?)"
    identifier = r"(?:\s+[A-Za-z]?\d+[A-Za-z]?(?:\s*[-–,]\s*[A-Za-z]?\d+[A-Za-z]?)*)?"
    component_only = rf"\b{component_name}{identifier}\s+(?:only|alone)\b|\b(?:only|solely)\s+(?:to|for)\s+(?:the\s+)?{component_name}\b"
    wrong_scope = scope in {"article", "sub-article"} and bool(re.search(component_only, license_text, re.I))
    conflict = len(identified) > 1 or (bool(identified) and restricted)
    allowed = len(identified) == 1 and not (conflict or wrong_scope or ambiguous)
    license_id = next(iter(identified)) if len(identified) == 1 else None
    return {
        "scope_policy_version": POLICY_VERSION, "scope_id": tree.getpath(component), "scope_kind": scope,
        "rights_scope": scope, "status": "license_identified" if allowed else "conflicting_pending_review" if conflict else "scope_pending_review" if wrong_scope or ambiguous else "unknown_pending_review",
        "license_id": license_id, "license_url": urls[0] if len(urls) == 1 else None,
        "license_candidates": sorted(identified), "license_text": license_text,
        "index_allowed": allowed,
        "redistribution_allowed": allowed and license_id in {"CC0", "CC-BY", "CC-BY-SA"},
        "derivative_redistribution_allowed": allowed and license_id in {"CC0", "CC-BY", "CC-BY-SA"},
        "declared_use": "local_internal_noncommercial_research_and_retrieval",
        "usage_restriction": "Only this component and explicitly inherited descendants; unknown or conflicting component rights remain pending.",
        "evidence_locator": [tree.getpath(x) for x in licenses],
        "review": "machine_scope_parsing_not_independent_legal_or_scientific_review",
    }


def rights_from_xml(article):
    components = [article, *article.xpath(".//*[local-name()='sub-article' or local-name()='fig' or local-name()='table-wrap' or local-name()='supplementary-material']")]
    scopes = {}
    for component in components:
        kind = etree.QName(component).localname
        all_licenses = [x for x in component.xpath(".//*[local-name()='license']") if owner(x, article) is component]
        licenses = ([x for x in all_licenses if _article_permission(x, component)]
                    if kind in {"article", "sub-article"} else all_licenses)
        # Only rights-bearing nodes supply restriction text; study findings are
        # not scanned as permission instructions.
        rights_nodes = [x for x in component.xpath(".//*[local-name()='permissions' or local-name()='copyright-statement' or local-name()='attrib']") if owner(x, article) is component]
        if kind not in {"article", "sub-article"}:
            rights_nodes += component.xpath("./*[local-name()='caption']")
        rights_text = " ".join(text(x) for x in rights_nodes)
        grant = _grant(component, licenses, rights_text, ambiguous=len(licenses) != len(all_licenses))
        if kind not in {"article", "sub-article"} and not all_licenses and not rights_nodes:
            parent = next((x for x in component.iterancestors() if x in scopes), None)
            if parent is not None:
                inherited = scopes[parent]
                grant = {**inherited, "scope_id": component.getroottree().getpath(component),
                         "scope_kind": kind, "rights_scope": kind, "inherited_from_scope": inherited["scope_id"]}
        elif kind not in {"article", "sub-article"} and not all_licenses:
            # Ordinary captions do not themselves revoke article permission;
            # explicit copyright/reuse notices do need component-level review.
            notice = bool(re.search(r"copyright|permission|rights reserved|licensed|©", rights_text, re.I))
            parent = next((x for x in component.iterancestors() if x in scopes), None)
            if not notice and parent is not None:
                inherited = scopes[parent]
                grant = {**inherited, "scope_id": component.getroottree().getpath(component),
                         "scope_kind": kind, "rights_scope": kind, "inherited_from_scope": inherited["scope_id"]}
        scopes[component] = grant
    primary = scopes[article]
    return {**primary, "component_scopes": list(scopes.values()),
            "partially_indexable": any(g["index_allowed"] for g in scopes.values())}


def rights_for_node(node, article, rights):
    identity = article.getroottree().getpath(owner(node, article))
    return next(x for x in rights["component_scopes"] if x["scope_id"] == identity)


def owned_subtree(node):
    """Copy only this component's content; descendant components own their bytes.

    Preserve the excluded component's tail, which belongs to the parent. Apply
    the same projection to text, tables and raw_xml, never only to display prose.
    """
    clone = deepcopy(node)
    for child in list(clone.iterdescendants()):
        if child.getparent() is None:
            continue
        if etree.QName(child).localname in OWNERS | {"permissions", "license"}:
            parent, previous, tail = child.getparent(), child.getprevious(), child.tail or ""
            if previous is not None:
                previous.tail = (previous.tail or "") + tail
            else:
                parent.text = (parent.text or "") + tail
            parent.remove(child)
    return clone
