"""A finished retrieval must show its result, including actionable evidence gaps."""
from streamlit.testing.v1 import AppTest


def _render(allowed):
    app = AppTest.from_string("""
import streamlit as st
from healthzip.ui.health_explanation import _show_reviewed_result
_show_reviewed_result(st.session_state['result'])
""")
    app.session_state["result"] = {"status": "ready", "items": [{
        "metric_id": "STATE-RHR", "explanation": {"source": "local_fallback"},
        "evidence_context": {
            "capability_permissions": {"source_explanation": allowed},
            "limitations": [] if allowed else ["missing_applicability_context:population",
                                               "missing_applicability_context:measurement_protocol"],
            "matched_claims": [{"statements": ["Synthetic reviewed interpretation."],
                                "limitations": ["Synthetic only."]}],
            "source_metadata": [{"title": "Synthetic original source", "year": 2026,
                                 "canonical_url": "https://example.invalid/source"}],
            "evidence_spans": [{"span_id": "synthetic-span", "section_path": "Methods",
                                "content": "Synthetic original measurement description."}],
        }}]}
    return app.run()


def test_insufficient_evidence_shows_retrieval_receipt_gaps_and_readable_original():
    app = _render(False)
    assert not app.exception
    text = "\n".join(x.value for x in app.markdown)
    captions = "\n".join(x.value for x in app.caption)
    assert "依据查询结果" in text and "已查询 1 项指标，找到 1 段" in captions
    assert "尚未确认适用人群" in captions and "尚未确认测量方法与协议" in captions
    assert "未生成模型回答" in captions
    assert "Synthetic original source" in text and "Synthetic original measurement description." in text
    assert "Synthetic reviewed interpretation." not in text
    assert "可能的解释" not in text
    assert any("暂不用于本期解释" in e.label and not e.proto.expanded for e in app.expander)


def test_supported_local_evidence_is_visible_without_a_configured_model():
    app = _render(True)
    assert not app.exception
    text = "\n".join(x.value for x in app.markdown)
    assert "可能的解释" in text and "Synthetic reviewed interpretation." in text
    assert "Synthetic original source" in text
    assert any("1 项满足本期解释所需条件" in x.value for x in app.caption)


def test_measurement_context_retains_fact_and_deduplicates_original_links():
    app = _render(False)
    result = app.session_state["result"]
    item = result["items"][0]
    item["deterministic_observations"] = [{"summary": "本期 68 bpm，记录 2/7 天。"}]
    item["measurement_explanations"] = [{"statement": "记录条件影响比较的解释。",
        "limitations": ["不能证明个人病因。"], "sources": [
            {"title": "Specific source", "canonical_url": "https://example.invalid/method"},
            {"title": "Specific source", "canonical_url": "https://example.invalid/method"}]}]
    item["local_next_steps"] = ["核对对应日期的采样时段。"]
    item["explanation"]["reason_code"] = "validation_failed"
    app.session_state["result"] = result
    app.run()
    text = "\n".join(x.value for x in app.markdown)
    assert "本期 68 bpm，记录 2/7 天。" in text
    assert text.count("https://example.invalid/method") == 1
    assert "核对对应日期的采样时段" in text
    assert any("未通过核验" in item.value for item in app.caption)
