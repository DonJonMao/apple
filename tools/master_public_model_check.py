import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from healthzip.ai.client import AIConfig
from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.model_services import load_services
from healthzip.knowledge.revisions import prepare_retrieval_revisions
from healthzip.science import evaluate

w = KnowledgeWorkbench(".local/knowledge")
prepare_retrieval_revisions(w)
providers = load_services(w.root)
calls = []
for provider in providers:
    orig = provider.post

    def wrap(payload, orig=orig, provider=provider):
        t = time.perf_counter()
        rec = {
            "model": provider.config.model_id,
            "purpose": type(provider).__name__,
            "status": "attempted",
        }
        calls.append(rec)
        try:
            response = orig(payload)
            rec["status"] = "received"
            return response
        except Exception as e:
            rec["error"] = str(e)[:80]
            raise
        finally:
            rec["seconds"] = round(time.perf_counter() - t, 3)

    provider.post = wrap
start = datetime(2026, 3, 10, tzinfo=timezone.utc)
rows = []
for i, value in enumerate([62, 65, 60, 61, 67, 64, 62, 63, 64, 62, 66, 62, 69, 63]):
    t = start + timedelta(days=i, hours=6)
    rows.append(
        dict(
            id=f"synthetic-{i}",
            canonical_type="resting_heart_rate_bpm",
            value=value,
            unit="bpm",
            source_name="SYNTHETIC_CONTEXT_NEVER_SENT",
            event_start=t.isoformat(),
            event_end=t.isoformat(),
            available_at=t.isoformat(),
        )
    )
end = start + timedelta(days=len(rows))
m = evaluate(
    "STATE-RHR",
    rows,
    cutoff_time=end.isoformat(),
    window_start=(start + timedelta(days=7)).isoformat(),
    window_end=end.isoformat(),
    context={"timezone": "UTC"},
)
result = w.explain_metric(
    "STATE-RHR",
    "explain_metric",
    m,
    {},
    mode="hybrid_rerank",
    candidate_scope="reviewed_metric",
    services=providers,
)
a = result["evidence_context"]["retrieval_audit"]
safe = {
    k: a.get(k)
    for k in [
        "requested_mode",
        "requested_k",
        "lexical_candidates",
        "dense_candidates",
        "fusion_candidates",
        "reranked_candidates",
        "retrieval_degraded",
        "degradation_reasons",
        "rankings",
        "personal_metric_values_sent",
        "private_context_sent",
    ]
}
out = {
    "actual_remote_model_calls": calls,
    "public_retrieval": safe,
    "used_claims": [x["claim_id"] for x in result["measurement_explanations"]],
    "answer_model_configured": AIConfig.from_env() is not None,
    "private_explanation_consent": False,
    "answer_generation": result["explanation"]["source"],
}
Path("artifacts/master_redesign/knowledge/public-model.json").write_text(
    json.dumps(out, indent=2, ensure_ascii=False) + "\n"
)
print(len(calls), safe["reranked_candidates"], out["used_claims"])
w.close()
