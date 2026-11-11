"""Typed, provenance-labelled applicability; absence never matches a requirement."""

from __future__ import annotations

SOURCES = {"source_scope", "user_plan", "measurement_contract", "equipment_constraint", "product_scope"}


def lookup(context, path):
    value = context
    for name in path.split("."):
        if not isinstance(value, dict) or name not in value:
            return None
        value = value[name]
    return value


def check_conditions(conditions, context):
    problems = []
    for condition in conditions:
        field, op = condition.get("field"), condition.get("op")
        if not field or op not in {"eq", "in", "range", "present"} or condition.get("origin") not in SOURCES:
            raise ValueError("typed condition requires field, eq/in/range/present and an explicit origin")
        value = lookup(context, field)
        missing = value is None or value == "unknown" or value == "" or value == []
        if missing:
            problems.append({"field": field, "reason": "missing_context", "origin": condition["origin"]})
            continue
        expected = condition.get("value")
        matches = op == "present"
        if op == "eq":
            matches = type(value) is type(expected) and value == expected
        elif op == "in":
            matches = isinstance(expected, list) and any(type(value) is type(x) and value == x for x in expected)
        elif op == "range":
            matches = (isinstance(value, (int, float)) and not isinstance(value, bool)
                       and (condition.get("min") is None or value >= condition["min"])
                       and (condition.get("max") is None or value <= condition["max"]))
        if not matches:
            problems.append({"field": field, "reason": "scope_mismatch", "origin": condition["origin"], "actual": value})
    return {"matches": not problems, "issues": problems}


def context_match(required, context):
    if isinstance(required, list):
        checked = check_conditions(required, context)
        issue = checked["issues"][0] if checked["issues"] else None
        return checked["matches"], (issue["reason"] + ":" + issue["field"]) if issue else "matched"
    for key, expected in required.items():
        actual = lookup(context, key)
        if actual is None or actual == "unknown":
            return False, "unknown_applicability:" + key
        if isinstance(expected, list):
            if actual not in expected:
                return False, "scope_mismatch:" + key
        elif actual != expected:
            return False, "scope_mismatch:" + key
    return True, "matched"
