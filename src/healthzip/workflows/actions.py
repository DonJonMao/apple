"""User-selected observations and append-only follow-up of the frozen question."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from healthzip.science.contracts import canonical_hash, instant


def select_action(repo, question, action_text, review_due, *, source_filter=(), selected_at=None):
    if action_text not in question.get("steps", []):
        raise ValueError("请选择本次问题分析中给出的行动。")
    if "source_filter" in question:
        frozen_sources = sorted(question.get("source_filter") or [])
        if source_filter and sorted(source_filter) != frozen_sources:
            raise ValueError("行动来源须与这次保存的观察一致。")
        source_filter = frozen_sources
    now = instant(selected_at) if selected_at else datetime.now(timezone.utc)
    if instant(review_due) <= now:
        raise ValueError("复评时间须晚于行动选择时间。")
    if instant(question["window"]["end"]) > now:
        raise ValueError("行动依据不能含尚未发生的记录。")
    # Retrying the same deliberate choice keeps one action identity.
    identity = canonical_hash({"question": question, "text": action_text, "due": review_due,
                               "source_filter": sorted(source_filter)})
    with repo.transaction():
        repo.conn.execute("INSERT OR IGNORE INTO review_action VALUES(?,?,?,?,?,?,?,?)",
            (identity, "local", question["id"], now.isoformat(), instant(review_due).isoformat(),
             action_text, json.dumps(question, ensure_ascii=False), json.dumps(sorted(source_filter))))
    return identity


def list_actions(repo):
    rows = repo.rows("SELECT a.*,e.status,e.notes,e.result_json,e.recorded_at AS feedback_at FROM review_action a "
        "LEFT JOIN review_action_event e ON e.rowid=(SELECT max(rowid) FROM review_action_event WHERE action_id=a.action_id) "
        "WHERE a.user_id='local' ORDER BY a.selected_at DESC LIMIT 100")
    return [dict(row) for row in rows]


def followup(repo, action_id, *, cutoff_time=None):
    from healthzip.analytics.body_metrics import analyze_questions
    row = repo.one("SELECT * FROM review_action WHERE action_id=? AND user_id='local'", (action_id,))
    if row is None:
        raise ValueError("所选行动在当前工作区不存在。")
    baseline = json.loads(row["baseline_json"])
    now = instant(cutoff_time) if cutoff_time else datetime.now(timezone.utc)
    selected = instant(row["selected_at"])
    duration = instant(baseline["window"]["end"]) - instant(baseline["window"]["start"])
    # Follow-up uses the frozen baseline's duration and source choice. An ongoing
    # interval is explicitly partial and does not silently replace the baseline.
    end = min(selected + duration, now)
    if end <= selected:
        return {"status": "awaiting_observations", "baseline": baseline, "current": None}
    current = analyze_questions(repo, window_start=selected.isoformat(), window_end=end.isoformat(),
        cutoff_time=now.isoformat(), timezone_name=baseline["window"]["timezone"],
        source_filter=json.loads(row["source_filter_json"]), question_ids=[row["question_id"]])[0]
    return {"status": "partial" if end < selected + duration else "complete_window", "baseline": baseline,
            "current": current, "selected_at": selected.isoformat(), "comparison_duration_days": duration / timedelta(days=1),
            "method_matches": baseline.get("analysis_version") == current.get("analysis_version"),
            "interpretation": "记录性行动前后观察；执行情况由本人反馈。"}


def save_feedback(repo, action_id, status, notes, result, *, event_id):
    if status not in {"executed", "partial", "not_executed", "stopped"}:
        raise ValueError("请选择真实执行情况。")
    action = repo.one("SELECT baseline_json FROM review_action WHERE action_id=? AND user_id='local'", (action_id,))
    if not action:
        raise ValueError("所选行动在当前工作区不存在。")
    if result and result.get("baseline") != json.loads(action["baseline_json"]):
        raise ValueError("复评结果不属于本次行动保存的观察。")
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True) if result else None
    with repo.transaction():
        existing = repo.one("SELECT action_id,status,notes,result_json FROM review_action_event WHERE event_id=?", (event_id,))
        if existing:
            if tuple(existing) != (action_id, status, notes, serialized):
                raise ValueError("这次保存标识已用于不同反馈，请保留当前输入后重试。")
            return
        repo.conn.execute("INSERT INTO review_action_event VALUES(?,?,?,?,?,?)",
            (event_id, action_id, datetime.now(timezone.utc).isoformat(), status, notes, serialized))
