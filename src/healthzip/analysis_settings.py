"""Shared product viewing defaults, never physiological decision thresholds."""

DEFAULT_WINDOW_DAYS = 30
DEFAULT_BASELINE_DAYS = 28
DEFAULT_TIMEZONE = "Asia/Shanghai"

# Only these viewing/context references may transfer between workflow entry points.
REVIEW_FIELDS = ("window_days", "baseline_days", "window_start", "window_end", "period",
                "cutoff_time", "timezone", "mode", "context_id", "selection_analysis_id", "release_id")
