import json

import pytest

from healthzip.ai.client import (
    AIConfig,
    build_evidence_payload,
    explain_analysis,
    validate_ai_result,
)


def _analysis():
    return {
        "heart": {
            "cards": [
                {
                    "id": "rhr",
                    "title": "RHR",
                    "status": "usable",
                    "summary": "57 bpm",
                    "facts": [{"metric": "rhr", "value": 57, "unit": "bpm"}],
                    "limitations": [],
                    "allowed_actions": ["continue_observation"],
                }
            ]
        }
    }


def test_ai_payload_is_minimal_and_validation_is_bounded():
    payload = build_evidence_payload(_analysis(), "怎么安排今天训练？")
    assert payload["sensitive_context_included"] is False
    assert payload["evidence"][0]["id"] == "rhr"
    result = validate_ai_result(
        {
            "summary": "依据记录继续观察。",
            "evidence_ids": ["rhr"],
            "limitations": [],
            "actions": ["continue_observation"],
        },
        payload,
    )
    assert result["source"] == "ai"


def test_ai_without_consent_or_key_uses_local_fallback():
    result = explain_analysis(_analysis(), allow_network=False)
    assert result["source"] == "local_fallback"
    assert "AI 解释不可用" in result["limitations"][0]


def test_ai_payload_filters_sensitive_cycle_cards():
    payload = build_evidence_payload(
        {
            "cycle": {
                "card": {
                    "id": "cycle_review",
                    "title": "周期记录回顾",
                    "status": "provisional",
                    "summary": "已记录周期事件",
                    "facts": [{"metric": "observed_bleeding_events", "value": 2}],
                    "allowed_actions": ["continue_observation"],
                }
            }
        }
    )
    assert payload["evidence"] == []


def test_ai_request_uses_openai_compatible_contract(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "summary": "继续观察。",
                                        "evidence_ids": ["rhr"],
                                        "limitations": [],
                                        "actions": ["continue_observation"],
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        return Response()

    monkeypatch.setattr("healthzip.ai.client.urlopen", fake_urlopen)
    result = explain_analysis(
        _analysis(),
        config=AIConfig(
            base_url="http://example.test/v1/chat/completions",
            model="deepseek-v4-flash",
            api_key="secret",
        ),
        allow_network=True,
    )
    assert result["source"] == "ai"
    assert captured["body"]["model"] == "deepseek-v4-flash"
    assert captured["url"].endswith("/chat/completions")


def _canonical_payload(*, structured=False):
    from healthzip.science.contracts import Window, result

    metric = result(
        "STR-04", Window("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z",
                         "2026-11-01T00:00:00Z"),
        ({"groups": [{"volume": 1500, "unit": "kg·次", "notes": "private-health-note",
                      "record_id": "private-record-identifier"}], "known_sets": 2}
         if structured else 1500),
        data_status="partial", reasons=["one_set_missing_repetitions"],
        records=[{"id": "synthetic:set:1"}], valid_n=2, total_n=3,
    )
    analysis = {"v13": {"metrics": {"STR-04": metric}}}
    payload = build_evidence_payload(analysis)
    card = payload["evidence"][0]
    answer = {"summary": card["summary"], "evidence_ids": [card["id"]],
              "facts": [{**card["facts"][0], "evidence_id": card["id"]}],
              "limitations": [], "actions": ["review_records"]}
    return analysis, payload, answer


def test_canonical_metrics_preserve_value_context_and_limits_without_network(monkeypatch):
    def unexpected_network(*args, **kwargs):
        raise AssertionError("Network must not run without consent")

    monkeypatch.setattr("healthzip.ai.client.urlopen", unexpected_network)
    analysis, payload, answer = _canonical_payload()
    metric = analysis["v13"]["metrics"]["STR-04"]
    card = payload["evidence"][0]
    assert card["facts"][0]["value"] == metric["value"]
    assert card["facts"][0]["window"] == metric["window"]
    assert card["cutoff_time"] == metric["cutoff_time"]
    assert "source_feature_ids" not in card
    for value in [metric["window"]["start"], metric["window"]["end"],
                  metric["cutoff_time"], metric["evidence_status"]]:
        assert value in card["summary"]
    checked = validate_ai_result(answer, payload)
    fallback = explain_analysis(analysis)
    assert str(metric["value"]) in fallback["summary"]
    assert metric["window"]["start"] in fallback["summary"]
    assert fallback["source"] == "local_fallback"
    assert set(card["limitations"]) <= set(checked["limitations"])
    assert set(metric["limitations"] + metric["reason_codes"]) <= set(fallback["limitations"])


def test_nested_records_and_private_notes_stay_local_at_network_boundary(monkeypatch):
    analysis, payload, _ = _canonical_payload(structured=True)
    metric = analysis["v13"]["metrics"]["STR-04"]
    metric["limitations"].append("private-limitation-note")
    assert "private-health-note" in explain_analysis(analysis)["summary"]
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps({
                "summary": "继续观察。", "evidence_ids": ["STR-04"], "limitations": [],
                "actions": ["review_records"],
            })}}]}).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = request.data.decode()
        return Response()

    monkeypatch.setattr("healthzip.ai.client.urlopen", fake_urlopen)
    result = explain_analysis(analysis, config=AIConfig("https://example.test", "test", "secret"),
                              allow_network=True)
    assert result["source"] == "ai"
    for private in ("private-health-note", "private-record-identifier", "synthetic:set:1",
                    "private-limitation-note", "groups"):
        assert private not in captured["body"]
        assert private not in json.dumps(payload)
    assert "private-limitation-note" in result["limitations"]
    assert all(isinstance(f["value"], (int, float)) for f in payload["evidence"][0]["facts"])


def test_pre_adapted_canonical_card_uses_the_same_network_projection():
    from healthzip.analytics.v13 import metric_card

    analysis, _, _ = _canonical_payload(structured=True)
    card = metric_card(analysis["v13"]["metrics"]["STR-04"])
    payload = build_evidence_payload({"cards": [card]})
    for private in ("private-health-note", "private-record-identifier", "synthetic:set:1", "groups"):
        assert private not in json.dumps(payload)


def test_all_analysis_explanation_uses_only_primary_canonical_snapshot():
    analysis, _, _ = _canonical_payload()
    metric = analysis["v13"]["metrics"]["STR-04"]
    mixed = {
        "legacy": {"id": "STR-04", "title": "legacy", "status": "valid", "summary": "legacy-result"},
        "v13": analysis["v13"],
        "period_snapshots": {"week": {"metrics": {"STR-04": {**metric, "value": 9999}}}},
    }
    payload = build_evidence_payload(mixed)
    assert len(payload["evidence"]) == 1
    assert payload["evidence"][0]["facts"][0]["value"] == 1500
    assert payload["evidence"][0]["cutoff_time"] == metric["cutoff_time"]
    local = explain_analysis(mixed)
    assert local["evidence_ids"] == ["STR-04"]
    assert local["summary"].count("1500") == 1
    assert "legacy-result" not in local["summary"] and "9999" not in local["summary"]


@pytest.mark.parametrize("field,value", [
    ("value", {"groups": [{"volume": 1600, "unit": "kg·次"}], "known_sets": 2}),
    ("unit", "kcal"), ("window", {"start": "2025-01-01"}),
    ("window", None), ("direction", "improved"),
    ("algorithm_version", "invented-algorithm"),
])
def test_canonical_fact_rejects_changed_value_or_context(field, value):
    _, payload, answer = _canonical_payload()
    answer["facts"][0][field] = value
    with pytest.raises(ValueError, match="evidence validation"):
        validate_ai_result(answer, payload)


@pytest.mark.parametrize("change", ["summary", "limitations"])
def test_canonical_prose_cannot_add_unsupported_claims(change):
    _, payload, answer = _canonical_payload()
    answer[change] = "训练量增加导致肌肥大。" if change == "summary" else ["明天加重5kg。"]
    with pytest.raises(ValueError, match="evidence validation"):
        validate_ai_result(answer, payload)


def test_matching_values_and_context_must_belong_to_the_same_fact():
    analysis = _analysis()
    card = analysis["heart"]["cards"][0]
    card["facts"] = [
        {"metric": "rhr", "value": 57, "unit": "bpm", "window": "October", "direction": "down"},
        {"metric": "rhr", "value": 60, "unit": "bpm", "window": "November", "direction": "up"},
    ]
    payload = build_evidence_payload(analysis)
    answer = {"summary": "继续观察。", "evidence_ids": ["rhr"],
              "facts": [{"evidence_id": "rhr", "metric": "rhr", "value": 57,
                         "unit": "bpm", "window": "November", "direction": "up"}],
              "limitations": [], "actions": ["continue_observation"]}
    with pytest.raises(ValueError, match="evidence validation"):
        validate_ai_result(answer, payload)


@pytest.mark.parametrize("expected,actual", [(1, True), (True, 1), ({"v": 1}, {"v": True}),
                                           ({"v": float("nan")}, {"v": float("nan")})])
def test_boolean_and_nonfinite_facts_are_not_numeric_matches(expected, actual):
    analysis = _analysis()
    analysis["heart"]["cards"][0]["facts"][0]["value"] = expected
    payload = build_evidence_payload(analysis)
    answer = {"summary": "继续观察。", "evidence_ids": ["rhr"],
              "facts": [{"evidence_id": "rhr", "metric": "rhr", "value": actual, "unit": "bpm"}],
              "limitations": [], "actions": ["continue_observation"]}
    with pytest.raises(ValueError, match="evidence validation"):
        validate_ai_result(answer, payload)
