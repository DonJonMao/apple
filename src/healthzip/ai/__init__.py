"""Optional, evidence constrained AI explanations."""

from .client import (
    AIClient,
    AIConfig,
    AIResult,
    build_evidence_payload,
    explain_analysis,
    validate_ai_result,
)

__all__ = [
    "AIClient",
    "AIConfig",
    "AIResult",
    "build_evidence_payload",
    "explain_analysis",
    "validate_ai_result",
]
