"""Read-only material coverage; registration and scientific review stay separate."""

import json


def current_chapter_coverage(workbench, registrations):
    """Derive current availability without changing old coverage receipts.

    Seed topic placeholders are not exact chapter mappings. Available source
    prose cannot prove that every planned topic, table or claim is covered.
    """
    lib = workbench.lib
    sources = {}
    for source_id in sorted({row["source_id"] for row in registrations}):
        versions = [dict(row) for row in lib.sources.execute(
            "SELECT version_id,metadata_json FROM version WHERE source_id=? AND material_type='fulltext'",
            (source_id,))]
        spans = []
        for version in versions:
            for row in lib.sources.execute("SELECT span_id FROM span WHERE version_id=?", (version["version_id"],)):
                span = lib.span(row["span_id"])
                allowed, reason = lib.eligible(span, "fulltext")
                spans.append({"span_id": span["span_id"], "locator": json.loads(span["locator_json"]),
                              "allowed": allowed, "reason": reason})
        sources[source_id] = {"versions": versions, "spans": spans}

    result = []
    for row in registrations:
        registered = json.loads(row["payload_json"])
        source = sources[row["source_id"]]
        # The seed uses section-N only as an ordinal in the topic worklist;
        # it is not a locator asserting section N in the actual document.
        topic_placeholder = (str(row["chapter_id"]).startswith("section-")
                             and not registered.get("span_ids") and not registered.get("chapter_number"))
        matched = [] if topic_placeholder else [span for span in source["spans"]
            if str(span["locator"].get("chapter_id")) == str(row["chapter_id"])
            and span["locator"].get("edition_id") == row["edition_id"]]
        eligible = [span for span in source["spans"] if span["allowed"]]
        scoped_eligible = [span for span in matched if span["allowed"]]
        if topic_placeholder:
            status = ("source_content_available_topic_mapping_pending" if eligible else
                      "source_content_present_unavailable" if source["versions"] else "missing_source_content")
        elif scoped_eligible:
            status = ("partial_chapter_content_available" if registered.get("missing_pages") else
                      "chapter_content_available_review_separate")
        else:
            held_chapter = matched or any(
                metadata.get("edition_id") == row["edition_id"]
                and str(metadata.get("chapter_id")) == str(row["chapter_id"])
                for metadata in (json.loads(version["metadata_json"]) for version in source["versions"]))
            status = "chapter_content_present_unavailable" if held_chapter else "missing_source_content"
        result.append({"source_id": row["source_id"], "edition_id": row["edition_id"],
            "chapter_id": row["chapter_id"], "coverage_scope": "planned_topic" if topic_placeholder else "exact_chapter",
            "topic": registered.get("topic_zh"), "material_status": status,
            "registered_status": registered.get("status"),
            "registered_missing_pages": registered.get("missing_pages"),
            "registered_missing_footnote_ids": registered.get("missing_footnote_ids", []),
            "registered_table_review": registered.get("table_review"),
            "source_held_fulltext_version_count": len(source["versions"]),
            "source_eligible_span_count": len(eligible),
            "scope_eligible_span_ids": sorted(span["span_id"] for span in scoped_eligible),
            "unavailable_reasons": sorted({span["reason"] for span in (source["spans"] if topic_placeholder else matched)
                                            if not span["allowed"]}),
            "claim_review_status": "separate_claim_and_rule_review_required",
            "limits": ["Material availability does not establish complete chapter/topic coverage, numeric table verification, or claim approval."]})
    return result
