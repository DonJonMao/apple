"""Optional explanations run independently of the factual page and its SQLite connection."""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import streamlit as st

from healthzip.ai.consent import NetworkConsent

PROMPT_VERSION = "health-change-explanation-2"
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="healthzip-explanation")
_JOBS: OrderedDict[str, tuple[float, Future]] = OrderedDict()
_LOCK = threading.Lock()
_MAX_JOBS = 32
_MAX_PENDING = 8
_TTL = 3600


def session_network_grant(allowed):
    """Called only on the UI thread; returned grants are safe for workers."""
    owner = st.session_state.get("_health_explanation_network_authority")
    if owner is None:
        owner = NetworkConsent(allowed)
        st.session_state["_health_explanation_network_authority"] = owner
    owner.set_allowed(allowed)
    return owner.grant()


def set_network_consent(allowed):
    """Apply a settings/review withdrawal to already queued or running jobs."""
    st.session_state["health_explanation_network_consent"] = bool(allowed)
    session_network_grant(allowed)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    default=str, allow_nan=False).encode()).hexdigest()


def _fact_identity(value):
    """A rerender's calculation timestamp is not a changed scientific input."""
    if isinstance(value, dict):
        metric = {"metric_id", "algorithm_version", "cutoff_time", "window"}.issubset(value)
        return {key: _fact_identity(item) for key, item in value.items()
                if not (metric and key == "computed_at")}
    if isinstance(value, (list, tuple)):
        return [_fact_identity(item) for item in value]
    return value


def knowledge_clock(root):
    """A cheap conservative UI freshness check; authority is rechecked in the worker."""
    output = []
    for name in ("sources.sqlite3", "theories.sqlite3"):
        for suffix in ("", "-wal"):
            path = Path(root) / (name + suffix)
            try:
                stat = path.stat()
                output.append((name + suffix, stat.st_ino, stat.st_mtime_ns, stat.st_size))
            except OSError:
                output.append((name + suffix, None))
    return output


def _model_identity():
    from healthzip.ai.client import AIConfig
    config = AIConfig.from_env()
    return None if config is None else [config.base_url, config.model, config.timeout_seconds,
                                        hashlib.sha256(config.api_key.encode()).hexdigest()]


def submit_job(key, compute):
    """Bounded, coalesced work. A Future never contains a caller's SQLite connection."""
    with _LOCK:
        now = time.monotonic()
        for old_key, (created, future) in list(_JOBS.items()):
            if future.done() and (now - created > _TTL or len(_JOBS) >= _MAX_JOBS):
                del _JOBS[old_key]
        if key in _JOBS:
            _JOBS.move_to_end(key)
            return _JOBS[key][1]
        if sum(not future.done() for _, future in _JOBS.values()) >= _MAX_PENDING:
            raise RuntimeError("explanation_queue_full")
        future = _EXECUTOR.submit(compute)
        _JOBS[key] = (now, future)
        return future


def job_result(key):
    with _LOCK:
        entry = _JOBS.get(key)
    if entry is None:
        return {"status": "expired"}
    future = entry[1]
    if not future.done():
        return {"status": "pending", "elapsed_seconds": time.monotonic() - entry[0]}
    try:
        return {"status": "ready", "result": future.result()}
    except Exception:
        # Errors can contain an endpoint or private source text. The local UI
        # exposes a retry, never the raw transport exception.
        return {"status": "failed"}


def _context_still_current(context):
    reference = context.get("_declaration_reference")
    if not reference:
        return True
    from healthzip.db.repository import Repository
    from healthzip.workflows.storage import context_as_of
    repo = Repository(context["_workspace_path"])
    try:
        declaration = context_as_of(repo, reference, None, "retrospective")
        return declaration.get("values", {}) == context.get("_declaration_values", {})
    except ValueError:
        return False
    finally:
        repo.close()


def _reviewed_explanation(metrics, context, allow_network, root, *, mode="lexical",
                          candidate_scope="reviewed_metric", task="explain_metric", include_empty=False):
    from healthzip.knowledge import KnowledgeWorkbench
    from healthzip.training.current import knowledge_signature

    if not all((Path(root) / name).is_file() for name in ("sources.sqlite3", "theories.sqlite3")):
        return {"status": "no_library", "knowledge_clock": knowledge_clock(root), "items": []}
    workbench = KnowledgeWorkbench(root)
    try:
        # Old libraries may finish an idempotent schema/profile upgrade during
        # their first lookup. Discard that answer and retry against the new
        # authoritative snapshot once; never relabel a stale answer as current.
        for _ in range(2):
            before = knowledge_signature(root)
            items = []
            if not _context_still_current(context):
                return {"status": "context_changed", "items": [], "knowledge_clock": knowledge_clock(root)}
            for identity, metric in metrics.items():
                if (metric.get("value") is None and not include_empty) or identity == "REPORT-STATE-SUMMARY":
                    continue
                items.append(workbench.explain_metric(
                    identity, task, metric, context.get("_metric_contexts", {}).get(identity, context),
                    mode=mode, candidate_scope=candidate_scope,
                    allow_explanation_network=allow_network,
                ))
            if not _context_still_current(context):
                return {"status": "context_changed", "items": [], "knowledge_clock": knowledge_clock(root)}
            if knowledge_signature(root) == before:
                return {"status": "ready", "items": items, "knowledge_clock": knowledge_clock(root)}
        return {"status": "changed", "items": [], "knowledge_clock": knowledge_clock(root)}
    finally:
        workbench.close()


def _show_reviewed_result(result, extra_windows=None):
    if result.get("status") == "context_changed":
        st.caption("适用信息在查询期间已撤回或改变，请在复盘中重新确认。记录与图表保持可用。")
        return
    if result.get("status") == "no_library":
        st.caption("尚未配置本地知识库。上方事实与记录建议仍可使用；模型不会替代缺少的依据。")
        return
    if result.get("status") == "changed":
        st.caption("计算期间依据发生更新，请重新获取解释。")
        return
    supported = [item for item in result.get("items", [])
                 if item["evidence_context"]["capability_permissions"].get("source_explanation")]
    if not supported:
        st.caption("当前缺少通过审核且适用的完整依据，暂不能判断变化原因。可在复盘中补充已确认的适用信息；记录与趋势继续保留。")
        return
    st.markdown("**可能的解释**")
    st.caption("以下是来源支持的一般解释，不能据此确认本次变化的原因。")
    for item in supported:
        extra = (extra_windows or {}).get(item.get("metric_id"), {})
        if extra:
            st.caption(extra.get("label", "此指标使用独立时间窗口"))
        evidence = item["evidence_context"]
        statements = list(dict.fromkeys(statement for claim in evidence.get("matched_claims", [])
                                         for statement in claim.get("statements", [])))
        for statement in statements[:2]:
            st.write(statement)
        explanation = item.get("explanation", {})
        if explanation.get("source") == "ai":
            st.write(explanation["summary"])
        with st.expander("为什么这样判断 · 来源与适用范围", expanded=False):
            for source in evidence.get("source_metadata", []):
                title = source.get("title") or "原始来源"
                url = source.get("canonical_url")
                if url and str(url).startswith(("https://", "http://")):
                    st.markdown(f"[{title}]({url})")
                else:
                    st.write(title)
                if source.get("year"):
                    st.caption(str(source["year"]))
            for span in evidence.get("evidence_spans", []):
                st.caption(f"{span.get('section_path') or '原文片段'} · {span.get('source_version', '')}")
                st.write(span.get("content", ""))
            for claim in evidence.get("matched_claims", []):
                for limitation in claim.get("limitations", []):
                    st.caption(limitation)
            st.caption("仅使用当前通过审核、许可和适用范围检查的资料；审核身份保留，不等于个人因果验证。")


def render_health_explanation(view, *, workspace, context=None, allow_network=False,
                              root=".local/knowledge"):
    metrics = view.get("workspace_scope", {}).get("metrics", {})
    if not metrics:
        return
    grant = session_network_grant(allow_network)
    context = dict(context or {})
    scope = {key: value for key, value in view.get("workspace_scope", {}).items()
             if key not in {"timings_ms", "query_plan", "cache_policy"}}
    identity = _digest([PROMPT_VERSION, workspace, _fact_identity(scope),
                        context, allow_network, grant.identity, _model_identity()])
    ui_key = "health_explanation_job_" + workspace
    selected = st.session_state.get(ui_key)
    pending = selected and selected["identity"] == identity and job_result(selected["key"])["status"] == "pending"

    @st.fragment(run_every=0.75 if pending else None)
    def panel():
        selected = st.session_state.get(ui_key)
        status = job_result(selected["key"]) if selected and selected["identity"] == identity else None
        if status and status["status"] == "ready":
            result = status["result"]
            if result.get("knowledge_clock") == knowledge_clock(root):
                _show_reviewed_result(result, scope.get("extra_metric_windows"))
            else:
                st.caption("依据已有更新，之前的解释暂不用于当前记录。请重新获取。")
        elif status and status["status"] == "pending":
            text = "正在读取依据；你可以继续浏览和记录。"
            if status["elapsed_seconds"] > 20:
                text = "解释仍在处理，事实与趋势已可用。你可以切换页面，稍后回来查看。"
            st.caption(text)
        elif status and status["status"] in {"failed", "expired"}:
            st.caption("本次解释未完成。记录和图表不受影响，可以重试。")
        elif selected and selected["identity"] != identity:
            st.caption("范围或记录已更新，旧解释不再用于本期数据。")
        if st.button("查阅依据并解释变化", key="health_explanation_run",
                     disabled=bool(status and status["status"] == "pending")):
            snapshot = copy.deepcopy(metrics)
            key = _digest([identity, knowledge_clock(root)])
            if status and status["status"] in {"failed", "expired"}:
                key = _digest([key, time.monotonic_ns()])
            try:
                submit_job(key, lambda: _reviewed_explanation(snapshot, context, grant, root))
                st.session_state[ui_key] = {"identity": identity, "key": key}
                st.rerun()
            except RuntimeError:
                st.caption("解释任务较多，请稍后重试。事实与趋势不受影响。")
        if pending and status and status["status"] != "pending":
            st.rerun()
    panel()


def render_optional_ai(analysis, *, key, question, allow_network):
    """Shared async adapter for the existing review page's consent and model contract."""
    from healthzip.ai.client import explain_analysis

    grant = session_network_grant(allow_network)
    identity = _digest([PROMPT_VERSION, key, _fact_identity(analysis), question, allow_network,
                        grant.identity, _model_identity()])
    current = st.session_state.get(key)
    pending = current and current["identity"] == identity and job_result(current["key"])["status"] == "pending"

    @st.fragment(run_every=0.75 if pending else None)
    def panel():
        current = st.session_state.get(key)
        status = job_result(current["key"]) if current and current["identity"] == identity else None
        if status and status["status"] == "ready":
            response = status["result"]
            st.write(response["summary"])
            st.caption("模型解释" if response["source"] == "ai" else "本地确定性解释")
        elif status and status["status"] == "pending":
            st.caption("正在解释；其他记录和操作仍可使用。")
        elif status and status["status"] in {"failed", "expired"}:
            st.caption("解释未完成，可以重试。")
        elif current:
            st.caption("数据或问题已改变，请为当前内容重新生成解释。")
        if st.button("解释当前证据", key=key + "_run", disabled=bool(status and status["status"] == "pending")):
            snapshot = copy.deepcopy(analysis)
            job_key = identity
            if status and status["status"] in {"failed", "expired"}:
                job_key = _digest([identity, time.monotonic_ns()])
            try:
                submit_job(job_key, lambda: explain_analysis(snapshot, question=question, allow_network=grant))
                st.session_state[key] = {"identity": identity, "key": job_key}
                st.rerun()
            except RuntimeError:
                st.caption("解释任务较多，请稍后重试。记录和图表不受影响。")
        if pending and status and status["status"] != "pending":
            st.rerun()
    panel()


def render_metric_request(metric, *, task, context, mode, candidate_scope, allow_network, key,
                          root=".local/knowledge", workspace=None):
    """Keep the existing evidence browser's detailed controls without blocking the page."""
    grant = session_network_grant(allow_network)
    # Equal facts in two databases do not make their private requests identical.
    # Standalone consumers without a Repository still get a session boundary.
    namespace = str(Path(workspace).resolve()) if workspace is not None else st.session_state.setdefault(
        "_metric_evidence_session", uuid4().hex)
    identity = _digest([PROMPT_VERSION, namespace, str(Path(root).resolve()), key,
                        _fact_identity(metric), task, context, mode, candidate_scope,
                        allow_network, grant.identity, _model_identity()])
    selected = st.session_state.get(key)
    pending = selected and selected["identity"] == identity and job_result(selected["key"])["status"] == "pending"

    @st.fragment(run_every=0.75 if pending else None)
    def panel():
        selected = st.session_state.get(key)
        status = job_result(selected["key"]) if selected and selected["identity"] == identity else None
        if status and status["status"] == "ready":
            result = status["result"]
            if result.get("knowledge_clock") == knowledge_clock(root):
                _show_reviewed_result(result)
                if candidate_scope == "all":
                    with st.expander("检索到的阅读材料（不自动授予解释权限）", expanded=False):
                        for item in result.get("items", []):
                            evidence = item["evidence_context"]
                            for span in evidence.get("evidence_spans", []):
                                st.write(span.get("source_metadata", {}).get("title", "原始来源"))
                                st.write(span.get("content", ""))
                                st.caption(f"{span.get('section_path', '')} · {span.get('evidence_role', '')}")
            else:
                st.caption("依据已经更新，请重新读取；旧解释暂不用于当前记录。")
        elif status and status["status"] == "pending":
            st.caption("正在查阅依据与解释；其他记录和操作仍可使用。")
        elif status and status["status"] in {"failed", "expired"}:
            st.caption("本次依据查询未完成，可以重试。")
        elif selected:
            st.caption("指标、范围或适用信息已改变，请重新查阅。")
        if st.button("查找原始依据并解释此指标", key="metric_evidence_run",
                     disabled=bool(status and status["status"] == "pending")):
            snapshot = copy.deepcopy(metric)
            job_key = _digest([identity, knowledge_clock(root)])
            if status and status["status"] in {"failed", "expired"}:
                job_key = _digest([job_key, time.monotonic_ns()])
            try:
                submit_job(job_key, lambda: _reviewed_explanation(
                    {snapshot["metric_id"]: snapshot}, context, grant, root,
                    mode=mode, candidate_scope=candidate_scope, task=task, include_empty=True))
                st.session_state[key] = {"identity": identity, "key": job_key}
                st.rerun()
            except RuntimeError:
                st.caption("解释任务较多，请稍后重试。")
        if pending and status and status["status"] != "pending":
            st.rerun()
    panel()
