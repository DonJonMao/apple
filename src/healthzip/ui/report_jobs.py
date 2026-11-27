"""Independent report tasks reuse the bounded job queue and frozen report store."""
from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from time import perf_counter

from healthzip.db.repository import Repository
from healthzip.ui.health_explanation import _digest, job_result, knowledge_clock, submit_job

_PROGRESS = OrderedDict()
_LOCK = RLock()


def report_progress(key):
    with _LOCK:
        return _PROGRESS.get(key, "任务正在排队")


def submit_report(database, *, cutoff_time, timezone_name, period, context_id, revision, attempt=0):
    key = "period-report:" + _digest({"database": str(database), "cutoff": cutoff_time, "zone": timezone_name,
        "period": period, "context_id": context_id, "revision": revision, "attempt": attempt,
        "knowledge": knowledge_clock(".local/knowledge")})

    def progress(stage):
        with _LOCK:
            _PROGRESS[key] = stage
            _PROGRESS.move_to_end(key)
            while len(_PROGRESS) > 64:
                _PROGRESS.popitem(last=False)

    def compute():
        from healthzip.workflows.period_report import create_report
        started = perf_counter()
        repo = Repository(database)
        try:
            progress("读取本期事实")
            context = {"workflow_context_id": context_id} if context_id else None
            analysis = {"cutoff_time": cutoff_time, "timezone": timezone_name, "selection_context": context or {}}
            result = create_report(repo, analysis, period=period, progress=progress)
            result["job_elapsed_seconds"] = perf_counter()-started
            progress("已保存，可以查看和下载")
            return result
        finally:
            repo.close()
    submit_job(key, compute)
    return key


def poll_report(key):
    return job_result(key)
