"""Small, explicit workflow contracts; no expressions or client metric inputs."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from healthzip.analysis_settings import DEFAULT_BASELINE_DAYS, DEFAULT_TIMEZONE, DEFAULT_WINDOW_DAYS
from healthzip.science.contracts import instant

VERSION = "analysis-workflows-1.7.0"
FUNCTION_NAMES = {
    "strength": "力量进阶", "recovery": "训练负荷与恢复背景",
    "cardiorespiratory": "心肺观察", "longitudinal": "长期趋势与可能因素",
    "metabolic": "体重与设备能量背景",
}
WORKFLOWS = {
    "W1": {"task": "strength", "metrics": tuple(f"STR-{i:02}" for i in range(1, 31)) + (
        "BODY-MASS-DAILY", "BODY-MASS-TREND", "STATE-SLEEP-24H", "STATE-FATIGUE", "STATE-PAIN",
        "STATE-RHR", "STATE-SDNN", "REPORT-RECOMMENDATION-FOLLOWUP"),
           "queries": ("STR-12", "STR-10")},
    "W2": {"task": "recovery", "metrics": ("STR-01", "STR-05", "STR-06", "STR-08", "STR-09", "STR-10", "STR-11", "STR-12", "STR-13", "STR-14", "STR-15", "STR-29",
        "STATE-SLEEP-MAIN", "STATE-SLEEP-24H", "STATE-SLEEP-COVERAGE", "STATE-SLEEP-STAGE", "STATE-SLEEP-TIMING",
        "STATE-RHR", "STATE-SDNN", "STATE-REFERENCE-MEDIAN", "STATE-REFERENCE-MAD", "STATE-DEVIATION",
        "STATE-FATIGUE", "STATE-SORENESS", "STATE-PAIN", "LOAD-SRPE", "LOAD-DURATION", "LOAD-SRPE-AU"),
        "queries": ("LOAD-SRPE-AU", "STATE-SDNN")},
    "W3": {"task": "cardiorespiratory", "metrics": ("OBS-VO2-REPORTED", "STATE-RHR", "STATE-SDNN"),
           "queries": ("OBS-VO2-REPORTED",)},
    "W4": {"task": "longitudinal", "metrics": ("STR-01", "STR-02", "STR-03", "STR-04", "STR-05", "STR-06", "STR-07", "STR-08", "STR-09", "STR-11", "STR-12", "STR-13",
        "STR-10", "STR-14", "STR-15", "STR-19", "STR-22", "STR-23", "STR-27", "STR-28", "STR-29", "STR-30",
        "STATE-RHR", "STATE-SDNN", "STATE-SLEEP-24H", "BODY-MASS-DAILY", "BODY-MASS-TREND", "REPORT-RECOMMENDATION-FOLLOWUP"),
        "queries": ("STR-19",)},
    "W5": {"task": "metabolic", "metrics": ("BODY-MASS-DAILY", "BODY-MASS-TREND", "ENERGY-BASAL", "ENERGY-ACTIVE",
        "ENERGY-DEVICE-TOTAL", "ENERGY-RECORD-COVERAGE", "ENERGY-IDENTIFIABILITY"),
        "queries": ("ENERGY-DEVICE-TOTAL", "ENERGY-IDENTIFIABILITY")},
}


@dataclass(frozen=True)
class WorkflowRequest:
    workflow_id: str
    cutoff_time: str | None = None
    timezone: str = DEFAULT_TIMEZONE
    mode: str = "prospective"
    trigger: str = "user_review"
    window_days: int = DEFAULT_WINDOW_DAYS
    baseline_days: int = DEFAULT_BASELINE_DAYS
    window_start: str | None = None
    window_end: str | None = None
    period: str | None = None
    session_id: int | str | None = None
    session_exercise_id: str | None = None
    selected_set_uuid: str | None = None
    task_id: str | None = None
    outcome_series_id: str | None = None
    result_metric_id: str | None = None
    context_id: str | None = None
    release_id: str | None = None
    candidate_id: str | None = None
    selection_analysis_id: str | None = None
    source_run_id: str | None = None
    context_policy: str = "require_valid"
    include_session_background: bool = False

    def normalized(self):
        if self.workflow_id not in WORKFLOWS or self.mode not in {"prospective", "retrospective"}:
            raise ValueError("unknown_workflow_or_mode")
        if self.context_policy not in {"require_valid", "preserve_facts"}:
            raise ValueError("unknown_context_policy")
        if type(self.window_days) is not int or self.window_days < 1:
            raise ValueError("positive_display_window_required")
        if type(self.baseline_days) is not int or self.baseline_days < 1:
            raise ValueError("positive_descriptive_baseline_window_required")
        if self.period not in {None, "week", "month"}:
            raise ValueError("unknown_calendar_period")
        if self.window_start is not None or self.window_end is not None:
            if self.window_start is None or self.window_end is None or self.period:
                raise ValueError("explicit_window_requires_both_bounds_without_period")
            if instant(self.window_start) >= instant(self.window_end):
                raise ValueError("explicit_window_must_be_nonempty")
        if self.result_metric_id not in {None, "STR-11", "BODY-MASS-DAILY", "STATE-RHR", "STATE-SDNN"}:
            raise ValueError("unknown_longitudinal_outcome")
        if (self.workflow_id == "W4" and self.result_metric_id not in {None, "STR-11"}
                and any((self.task_id, self.session_exercise_id, self.candidate_id))):
            raise ValueError("strength_task_requires_strength_outcome")
        ZoneInfo(self.timezone)
        if self.trigger not in {"user_review", "record_saved", "followup", "context_updated"}:
            raise ValueError("unknown_workflow_trigger")
        result = asdict(self)
        result["cutoff_time"] = instant(self.cutoff_time).isoformat() if self.cutoff_time else datetime.now(timezone.utc).isoformat()
        return result


def scientific_identity(value):
    """Ignore transport clocks/global DB digests, never in saved MetricResult.

    Relevant record revisions are separately hashed in the dependency manifest.
    Existing task snapshot digests also include unrelated global data_version.
    """
    if isinstance(value, dict):
        return {key: scientific_identity(item) for key, item in value.items()
                if key not in {"computed_at", "data_snapshot_hash"}}
    if isinstance(value, list):
        return [scientific_identity(item) for item in value]
    return value
