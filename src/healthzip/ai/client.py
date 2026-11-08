"""OpenAI-compatible explanation client with deterministic local fallback.

The endpoint receives a small set of already-computed Evidence Cards. Raw Apple
Health XML, CSV rows, location data and cycle details are never sent by this
module. The caller can therefore use the feature when an endpoint is configured,
while retaining a useful local result when it is not.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class AIConfig:
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float = 20.0
    allow_sensitive: bool = False

    @classmethod
    def from_env(cls) -> Optional["AIConfig"]:
        key = os.getenv("HEALTHZIP_AI_API_KEY", "").strip()
        base = os.getenv(
            "HEALTHZIP_AI_BASE_URL",
            "http://111.19.156.30:8006/v1/chat/completions",
        ).strip()
        model = os.getenv("HEALTHZIP_AI_MODEL", "deepseek-v4-flash").strip()
        if not key or not base or not model:
            return None
        try:
            timeout = float(
                os.getenv("HEALTHZIP_AI_TIMEOUT_SECONDS", os.getenv("HEALTHZIP_AI_TIMEOUT", "20"))
            )
        except ValueError:
            timeout = 20.0
        return cls(
            base,
            model,
            key,
            max(2.0, min(timeout, 120.0)),
            os.getenv("HEALTHZIP_AI_ALLOW_SENSITIVE", "0") == "1",
        )


@dataclass
class AIResult:
    text: str
    source: str
    evidence_ids: list[str]
    limitations: list[str]
    allowed_actions: list[str]
    error: Optional[str] = None


def _endpoint(base: str) -> str:
    value = base.rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    if value.endswith("/v1"):
        return value + "/chat/completions"
    return value + "/v1/chat/completions"


def _safe_cards(cards: list[dict[str, Any]], allow_sensitive: bool = False) -> list[dict[str, Any]]:
    """Keep only fields needed to explain a result."""
    safe = []
    for card in cards:
        card_text = " ".join(str(card.get(key) or "") for key in ("id", "title", "summary")).lower()
        if not allow_sensitive and any(
            word in card_text
            for word in ("cycle", "menstrual", "pain", "gps", "location", "周期", "经期", "疼痛")
        ):
            continue
        item = {
            k: card.get(k)
            for k in (
                "id",
                "title",
                "status",
                "window",
                "summary",
                "facts",
                "limitations",
                "allowed_actions",
                "algorithm_version",
                "source_feature_ids",
                "source_feature_ids",
            )
            if k in card
        }
        item["facts"] = []
        for fact in card.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            metric = str(fact.get("metric", ""))
            if not allow_sensitive and any(
                word in metric.lower()
                for word in (
                    "location",
                    "gps",
                    "cycle",
                    "menstrual",
                    "pain",
                    "周期",
                    "经期",
                    "疼痛",
                )
            ):
                continue
            item["facts"].append(
                {
                    k: fact.get(k)
                    for k in ("metric", "value", "unit", "n_days", "n", "sample_count")
                    if k in fact
                }
            )
        if not allow_sensitive:
            item["summary"] = re.sub(
                r"(?:地址|经纬度|location|gps)[^，。；;]*",
                "[已省略]",
                str(item.get("summary") or ""),
                flags=re.I,
            )
        safe.append(item)
    return safe


def _fallback(cards: list[dict[str, Any]], reason: Optional[str] = None) -> AIResult:
    usable = [c for c in cards if c.get("status") not in {"not_imported", "insufficient"}]
    lines = [str(c.get("summary") or c.get("title") or "暂无结论") for c in usable[:5]]
    if not lines:
        lines = ["当前证据不足，先补充连续记录后再比较。"]
    limitations = []
    actions = []
    ids = []
    for card in cards:
        ids.append(str(card.get("id")))
        limitations.extend(str(x) for x in (card.get("limitations") or []))
        actions.extend(str(x) for x in (card.get("allowed_actions") or []))
    return AIResult(
        "；".join(lines),
        "deterministic_fallback",
        ids,
        list(dict.fromkeys(limitations)),
        list(dict.fromkeys(actions)),
        reason,
    )


def _walk_cards(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if {"id", "title", "status", "summary"}.issubset(value):
            found.append(value)
        else:
            for child in value.values():
                found.extend(_walk_cards(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_cards(child))
    return found


def build_evidence_payload(analysis: dict[str, Any], question: str = "") -> dict[str, Any]:
    """Return the minimal, non-sensitive payload used for an explanation."""
    cards = []
    seen: set[str] = set()
    for card in _walk_cards(analysis):
        card_id = str(card.get("id") or "")
        if card_id in seen:
            continue
        seen.add(card_id)
        cards.append(card)
    return {
        "evidence": _safe_cards(cards, False),
        "question": question[:500],
        "sensitive_context_included": False,
    }


def validate_ai_result(value: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "summary": value.get("summary"),
        "evidence_ids": value.get("evidence_ids"),
        "facts": value.get("facts", []),
        "limitations": value.get("limitations", []),
        "allowed_actions": value.get("allowed_actions", value.get("actions", [])),
    }
    checked = _validate(normalized, payload.get("evidence") or [])
    if checked is None:
        raise ValueError("AI response failed evidence validation")
    return {
        "summary": checked.text,
        "source": checked.source,
        "evidence_ids": checked.evidence_ids,
        "limitations": checked.limitations,
        "actions": checked.allowed_actions,
    }


def explain_analysis(
    analysis: dict[str, Any],
    question: str = "",
    *,
    config: Optional[AIConfig] = None,
    allow_network: bool = False,
) -> dict[str, Any]:
    payload = build_evidence_payload(analysis, question)
    cards = payload["evidence"]
    if not allow_network:
        fallback = _fallback(cards, "network_disabled")
        return {
            "summary": fallback.text,
            "source": "local_fallback",
            "evidence_ids": fallback.evidence_ids,
            "limitations": ["AI 解释不可用：当前未允许网络请求。"] + fallback.limitations,
            "actions": fallback.allowed_actions,
        }
    selected = config or AIConfig.from_env()
    if selected is None:
        fallback = _fallback(cards, "not_configured")
        return {
            "summary": fallback.text,
            "source": "local_fallback",
            "evidence_ids": fallback.evidence_ids,
            "limitations": ["AI 解释不可用：未配置 endpoint 或 API key。"] + fallback.limitations,
            "actions": fallback.allowed_actions,
        }
    result = AIClient(selected).explain(cards, question)
    return {
        "summary": result.text,
        "source": "ai" if result.source == "ai" else "local_fallback",
        "evidence_ids": result.evidence_ids,
        "limitations": result.limitations
        if result.source == "ai"
        else ["AI 解释不可用：已回退到本地确定性结果。"] + result.limitations,
        "actions": result.allowed_actions,
    }


def _numeric_facts(cards: list[dict[str, Any]]) -> dict[tuple[str, str], set[float]]:
    result: dict[tuple[str, str], set[float]] = {}
    for card in cards:
        cid = str(card.get("id"))
        for fact in card.get("facts") or []:
            if not isinstance(fact, dict) or not isinstance(fact.get("value"), (int, float)):
                continue
            result.setdefault((cid, str(fact.get("metric"))), set()).add(float(fact["value"]))
    return result


def _parse_model_content(content: Any) -> Any:
    """Parse JSON from common OpenAI-compatible response shapes."""
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        text_parts = [item.get("text", "") for item in content if isinstance(item, dict)]
        content = "".join(str(part) for part in text_parts)
    if not isinstance(content, str):
        return None
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    return json.loads(text)


def _validate(payload: Any, cards: list[dict[str, Any]]) -> Optional[AIResult]:
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("summary"), str)
        or not payload["summary"].strip()
    ):
        return None
    known = {str(c.get("id")): c for c in cards}
    ids = payload.get("evidence_ids")
    if not isinstance(ids, list) or not ids or any(str(x) not in known for x in ids):
        return None
    limitations = payload.get("limitations")
    actions = payload.get("allowed_actions")
    # A valid answer may have no additional limitations (the card can already
    # provide all of them), while it must still provide at least one bounded
    # action for the UI to render.  Empty lists are therefore accepted for
    # limitations but not for actions.
    if not isinstance(limitations, list) or not isinstance(actions, list) or not actions:
        return None
    permitted = {
        str(action)
        for card_id in ids
        for action in (known[str(card_id)].get("allowed_actions") or [])
    }
    if any(str(action) not in permitted for action in actions):
        return None
    numeric = _numeric_facts(cards)
    facts = payload.get("facts", [])
    if not isinstance(facts, list):
        return None
    for fact in facts:
        if not isinstance(fact, dict):
            return None
        eid, metric, value = (
            str(fact.get("evidence_id", "")),
            str(fact.get("metric", "")),
            fact.get("value"),
        )
        if (
            eid not in known
            or not isinstance(value, (int, float))
            or float(value) not in numeric.get((eid, metric), set())
        ):
            return None
    return AIResult(
        payload["summary"].strip(),
        "ai",
        [str(x) for x in ids],
        [str(x) for x in limitations],
        [str(x) for x in actions],
    )


class AIClient:
    def __init__(self, config: AIConfig):
        self.config = config

    @classmethod
    def from_env(cls) -> Optional["AIClient"]:
        config = AIConfig.from_env()
        return cls(config) if config else None

    def explain(self, cards: list[dict[str, Any]], question: str = "") -> AIResult:
        safe = _safe_cards(cards, self.config.allow_sensitive)
        if not safe:
            return _fallback(cards, "no_evidence")
        instruction = {
            "summary": "简洁中文解释",
            "evidence_ids": ["card_id"],
            "facts": [{"evidence_id": "card_id", "metric": "metric", "value": 0, "unit": "unit"}],
            "limitations": ["必须引用证据局限"],
            "allowed_actions": ["只能使用证据卡允许的行动"],
        }
        prompt = (
            "你是训练数据解释助手。只解释证据卡中的观察，不做诊断、因果归因或精确处方。输出严格 JSON，不要 Markdown。数值事实必须逐字来自对应 evidence_id 的 facts；summary 中不要添加卡片没有的数字。必须保留 limitations 和 allowed_actions。格式示例："
            + json.dumps(instruction, ensure_ascii=False)
        )
        if question:
            prompt += "\n用户问题：" + question[:500]
        body = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(safe, ensure_ascii=False)},
            ],
            "temperature": 0.1,
        }
        try:
            req = Request(
                _endpoint(self.config.base_url),
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": "Bearer " + self.config.api_key,
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urlopen(req, timeout=self.config.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
            content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
            parsed = _parse_model_content(content)
            if isinstance(parsed, dict) and "allowed_actions" not in parsed and "actions" in parsed:
                parsed = dict(parsed)
                parsed["allowed_actions"] = parsed["actions"]
            checked = _validate(parsed, safe)
            return checked or _fallback(cards, "validation_failed")
        except (
            OSError,
            HTTPError,
            URLError,
            TimeoutError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ) as exc:
            return _fallback(cards, type(exc).__name__)


__all__ = [
    "AIClient",
    "AIConfig",
    "AIResult",
    "build_evidence_payload",
    "validate_ai_result",
    "explain_analysis",
]
