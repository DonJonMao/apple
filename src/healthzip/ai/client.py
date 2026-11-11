"""OpenAI-compatible explanation client with deterministic local fallback.

The endpoint receives a small set of already-computed Evidence Cards. Raw Apple
Health XML, CSV rows, location data and cycle details are never sent by this
module. The caller can therefore use the feature when an endpoint is configured,
while retaining a useful local result when it is not.
"""

from __future__ import annotations

import json
import math
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
            "",
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


def _network_metric_card(card: dict[str, Any]) -> dict[str, Any]:
    """Project canonical results to scalars; record rows and IDs stay local."""
    window = {k: v for k, v in card["window"].items()
              if k in {"start", "end", "timezone", "closure"}}
    original = card["facts"][0]
    value = original["value"]
    scalar = (isinstance(value, (int, float)) and not isinstance(value, bool)
              and math.isfinite(value))
    facts = ([{"metric": card["id"], "value": value, "unit": original.get("unit"),
               "window": window}] if scalar else [])
    for key in ("valid_n", "total_n", "n_sessions"):
        count = card.get(key)
        if isinstance(count, int) and not isinstance(count, bool):
            facts.append({"metric": card["id"] + ":" + key, "value": count,
                          "unit": "sessions" if key == "n_sessions" else card.get("count_domain", "records"),
                          "window": window})
    value_text = (f"{value} {original.get('unit') or ''}。" if scalar
                  else "结构化结果仅在本地显示。")
    summary = (f"{card['title']}：{value_text} 数据状态：{card['status']}；"
               f"时间范围：{window.get('start')} 至 {window.get('end')}；"
               f"数据截止：{card['cutoff_time']}；证据身份：{card['evidence_status']}。")
    public_limits = card.get("_public_limitations", [])
    limits = [x for x in card.get("limitations", []) if x in public_limits]
    if any(x not in public_limits for x in card.get("limitations", [])):
        limits.append("其他结果限制仅保留于本地；请同时查看本地指标卡。")
    return {"id": card["id"], "title": card["title"], "status": card["status"],
            "summary": summary, "facts": facts, "window": window,
            "cutoff_time": card["cutoff_time"], "evidence_status": card["evidence_status"],
            "limitations": limits, "allowed_actions": card["allowed_actions"],
            "algorithm_version": card["algorithm_version"]}


def _safe_cards(cards: list[dict[str, Any]], allow_sensitive: bool = False,
                *, network_projection: bool = True) -> list[dict[str, Any]]:
    """Keep only fields needed to explain a result."""
    from healthzip.science.contracts import definitions

    canonical = definitions() if network_projection else {}
    safe = []
    for card in cards:
        if network_projection and (card.get("_canonical_metric_result") or card.get("id") in canonical):
            # Older callers already ran metric_card and lost its raw contract
            # envelope. They still require exactly the same network boundary.
            card = dict(card)
            definition = canonical.get(card["id"], {})
            card.setdefault("_public_limitations", [definition.get("uncertainty", ""),
                            *definition.get("forbidden_inferences", [])])
            card.setdefault("cutoff_time", None)
            card.setdefault("evidence_status", "unknown")
            card = _network_metric_card(card)
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
                "cutoff_time",
                "evidence_status",
                "n_sessions",
                "uncertainty",
                "parameter_set_id",
                "calibration_artifact_id",
            )
            if k in card
        }
        item["facts"] = []
        for fact in card.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            if network_projection and isinstance(fact.get("value"), (dict, list)):
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
                    for k in ("metric", "value", "unit", "n_days", "n", "sample_count",
                              "window", "direction", "algorithm_version")
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
        if network_projection:
            item.pop("source_feature_ids", None)
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
        if {"metric_id", "algorithm_version", "cutoff_time", "window", "value",
            "data_status", "evidence_status", "source_record_ids"}.issubset(value):
            from healthzip.analytics.v13 import metric_card
            from healthzip.science.contracts import definitions

            card = metric_card(value)
            window = value["window"]
            card["summary"] += (
                f" 时间范围：{window.get('start')} 至 {window.get('end')}；"
                f"数据截止：{value['cutoff_time']}；证据身份：{value['evidence_status']}。"
            )
            for key in ("cutoff_time", "evidence_status", "n_sessions", "uncertainty",
                        "valid_n", "total_n", "count_domain",
                        "parameter_set_id", "calibration_artifact_id"):
                card[key] = value.get(key)
            definition = definitions()[value["metric_id"]]
            card["_canonical_metric_result"] = True
            card["_public_limitations"] = [definition.get("uncertainty", ""),
                                           *definition.get("forbidden_inferences", [])]
            found.append(card)
        elif {"id", "title", "status", "summary"}.issubset(value):
            found.append(value)
        else:
            for child in value.values():
                found.extend(_walk_cards(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_cards(child))
    return found


def _analysis_cards(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    # all_analysis also contains legacy cards and week/month snapshots. Its
    # primary canonical snapshot is the single source for this explanation.
    primary = analysis.get("v13")
    value = primary if isinstance(primary, dict) and "metrics" in primary else analysis
    cards: dict[str, dict[str, Any]] = {}
    for card in _walk_cards(value):
        card_id = str(card.get("id") or "")
        if card_id not in cards or card.get("_canonical_metric_result"):
            cards[card_id] = card
    return list(cards.values())


def build_evidence_payload(analysis: dict[str, Any], question: str = "") -> dict[str, Any]:
    """Return the minimal, non-sensitive payload used for an explanation."""
    return {
        "evidence": _safe_cards(_analysis_cards(analysis), False),
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
    # Full structured metrics remain available locally. Projection happens
    # only at the network boundary, including when previewing its payload.
    cards = _analysis_cards(analysis)
    local_cards = _safe_cards(cards, True, network_projection=False)
    if not allow_network:
        fallback = _fallback(local_cards, "network_disabled")
        return {
            "summary": fallback.text,
            "source": "local_fallback",
            "evidence_ids": fallback.evidence_ids,
            "limitations": ["AI 解释不可用：当前未允许网络请求。"] + fallback.limitations,
            "actions": fallback.allowed_actions,
        }
    selected = config or AIConfig.from_env()
    if selected is None:
        fallback = _fallback(local_cards, "not_configured")
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


def _same_fact_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isfinite(actual) and math.isfinite(expected) and actual == expected
    try:
        return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        return False


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


def _grounded_summary(summary: str, cards: list[dict]) -> bool:
    """Accept only whole evidence statements or a small neutral vocabulary.

    Numeric token matching cannot detect swapped metrics, units, directions or
    time windows. Until a semantic verifier is validated, generated prose must
    select exact, already-computed statements; otherwise use the local template.
    """
    neutral = {"继续观察。", "依据记录继续观察。", "现有记录不足以作出判断。"}
    if summary in neutral:
        return True
    allowed = {str(c.get("summary") or "").strip() for c in cards}
    allowed.discard("")
    if summary in allowed:
        return True
    # Explicit line-separated extracts preserve the complete claim context.
    return bool(summary.strip()) and all(line.strip() in allowed for line in summary.splitlines())


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
    cited = [known[str(eid)] for eid in ids]
    known_limits = {str(item) for card in cited for item in card.get("limitations", [])}
    if any(not isinstance(item, str) or item not in known_limits for item in limitations):
        return None
    if not _grounded_summary(payload["summary"].strip(), cited):
        return None
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
        # A value and its context must match the same source fact. Separate
        # membership checks would allow mixing two windows of one metric.
        if eid not in ids or not any(
            f.get("metric") == metric
            and _same_fact_value(value, f.get("value"))
            and f.get("unit") == fact.get("unit")
            and ("window" not in fact or
                 f.get("window", known[eid].get("window")) == fact["window"])
            and ("direction" not in fact or f.get("direction") == fact["direction"])
            and ("algorithm_version" not in fact or
                 f.get("algorithm_version", known[eid].get("algorithm_version"))
                 == fact["algorithm_version"])
            for f in known[eid].get("facts", [])
        ):
            return None
    return AIResult(
        payload["summary"].strip(),
        "ai",
        [str(x) for x in ids],
        list(dict.fromkeys([str(x) for x in limitations] + [str(x) for c in cited for x in c.get("limitations", [])])),
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
            "summary": "逐字选择证据卡summary；多个完整句用换行连接；不得自行添加数值、方向、因果或改换时间窗",
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
            if checked is not None:
                checked.limitations = list(dict.fromkeys([
                    *checked.limitations,
                    *(str(limit) for card in cards for limit in card.get("limitations", [])),
                ]))
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
