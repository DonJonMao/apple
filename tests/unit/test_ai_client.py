import json

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
