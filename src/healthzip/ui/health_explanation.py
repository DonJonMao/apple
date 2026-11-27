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

PROMPT_VERSION = "health-change-explanation-4"
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
    """Only source/review changes invalidate results, never audit/checkpoint IO."""
    from healthzip.knowledge.revisions import knowledge_authority_clock

    return knowledge_authority_clock(root)


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
            existing = _JOBS[key][1]
            retry = False
            if existing.done():
                try:
                    retry = _retryable_response(existing.result())
                except Exception:
                    retry = True
            if not retry:
                _JOBS.move_to_end(key)
                return existing
            del _JOBS[key]
        if sum(not future.done() for _, future in _JOBS.values()) >= _MAX_PENDING:
            raise RuntimeError("explanation_queue_full")
        future = _EXECUTOR.submit(compute)
        _JOBS[key] = (now, future)
        return future


def _retryable_response(result):
    """A locally handled transport failure is not a reusable successful answer."""
    if not isinstance(result, dict):
        return False
    if result.get('status') in {'failed', 'changed', 'context_changed'}:
        return True
    if (result.get('reason_code') or result.get('error')) in {
            'TimeoutError', 'timeout', 'HTTPError', 'URLError', 'OSError',
            'ValueError', 'KeyError', 'IndexError', 'TypeError',
            'service_failed', 'retrieval_timeout', 'validation_failed', 'partial_validation'}:
        return True
    if result.get('retrieval_audit', {}).get('retrieval_degraded'):
        return True
    return any(_retryable_response(value) for key, value in result.items()
               if key in {'explanation', 'evidence_context'}) or any(
                   _retryable_response(item) for item in result.get('items', []))


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
    except TimeoutError:
        return {"status": "failed", "reason_code": "retrieval_timeout"}
    except Exception:
        # Errors can contain an endpoint or private source text. The local UI
        # exposes a retry, never the raw transport exception.
        return {"status": "failed", "reason_code": "service_failed"}


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

    if not all((Path(root) / name).is_file() for name in ("sources.sqlite3", "theories.sqlite3")):
        return {"status": "no_library", "knowledge_clock": knowledge_clock(root), "items": []}
    started = time.perf_counter()
    workbench = KnowledgeWorkbench(root)
    try:
        from healthzip.knowledge.revisions import prepare_retrieval_revisions

        prepare_retrieval_revisions(workbench)
        # Old libraries may finish an idempotent schema/profile upgrade during
        # their first lookup. Discard that answer and retry against the new
        # authoritative snapshot once; never relabel a stale answer as current.
        for _ in range(2):
            before = knowledge_clock(root)
            items = []
            if not _context_still_current(context):
                return {"status": "context_changed", "items": [], "knowledge_clock": knowledge_clock(root)}
            for identity, metric in metrics.items():
                if (metric.get("value") is None and not include_empty) or identity == "REPORT-STATE-SUMMARY":
                    continue
                item_started = time.perf_counter()
                item = workbench.explain_metric(
                    identity, task, metric, context.get("_metric_contexts", {}).get(identity, context),
                    mode=mode, candidate_scope=candidate_scope,
                    allow_explanation_network=allow_network,
                )
                item["elapsed_ms"] = (time.perf_counter() - item_started) * 1000
                items.append(item)
            if not _context_still_current(context):
                return {"status": "context_changed", "items": [], "knowledge_clock": knowledge_clock(root)}
            if knowledge_clock(root) == before:
                return {"status": "ready", "items": items, "knowledge_clock": before,
                        "timings_ms": {"retrieval_and_explanation": (time.perf_counter() - started) * 1000}}
        return {"status": "changed", "items": [], "knowledge_clock": knowledge_clock(root)}
    finally:
        workbench.close()


def _missing_evidence_notes(evidence):
    labels = {"population": "适用人群", "measurement_protocol": "测量方法与协议",
              "srpe_scale": "整场感知强度量表", "srpe_collection": "整场评分采集时点"}
    notes = []
    for reason in evidence.get("limitations", []):
        if reason.startswith("missing_applicability_context:"):
            field = reason.split(":", 1)[1]
            notes.append("尚未确认" + labels.get(field, "这项指标所需的适用信息"))
        elif reason.startswith(("missing_required_domain:", "missing_evidence_type:")):
            notes.append("现有资料尚未覆盖这项指标所需的全部依据")
        elif reason == "explicit_conflicting_claims_require_resolution":
            notes.append("相关依据存在尚未解决的冲突")
        elif reason == "no_complete_reviewed_metric_group":
            notes.append("尚无通过审核且适用的完整依据")
    return list(dict.fromkeys(notes))


def _show_sources(evidence, *, supported):
    label = "为什么这样判断 · 来源与适用范围" if supported else "查阅检索到的原文 · 暂不用于本期解释"
    with st.expander(label, expanded=False):
        seen = set()
        for source in evidence.get("source_metadata", []):
            title = source.get("title") or "原始来源"
            url = source.get("canonical_url")
            identity = (title, url, source.get("year"))
            if identity in seen:
                continue
            seen.add(identity)
            if url and str(url).startswith(("https://", "http://")):
                st.markdown(f"[{title}]({url})")
            else:
                st.write(title)
            if source.get("year"):
                st.caption(str(source["year"]))
        for span in evidence.get("evidence_spans", []):
            st.caption(span.get("section_path") or "原文片段")
            st.write(span.get("content", ""))
        if supported:
            for claim in evidence.get("matched_claims", []):
                for limitation in claim.get("limitations", []):
                    st.caption(limitation)
        st.caption("原文可供核对；是否适用于本期数据仍取决于审核、测量条件与适用范围。")


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
    items = result.get("items", [])
    supported = [item for item in items
                 if item["evidence_context"]["capability_permissions"].get("source_explanation")]
    spans = {span.get("span_id", (item.get("metric_id"), index)) for item in items
             for index, span in enumerate(item["evidence_context"].get("evidence_spans", []))}
    st.markdown("**依据查询结果**")
    st.caption(f"已查询 {len(items)} 项指标，找到 {len(spans)} 段可查阅原文；"
               f"其中 {len(supported)} 项满足本期解释所需条件。")
    if not items:
        st.caption("用于此项解释的记录不足。上方日值与趋势仍可查看；可展开“分析依据与范围”核对解释指标使用的时间范围。")
        return
    if items and not any(item.get("explanation", {}).get("source") == "ai" for item in items):
        st.caption("本次展示本地检索依据，未生成模型回答。模型配置与联网授权可在设置中查看。")
    if not supported:
        st.caption("当前缺少通过审核且适用的完整依据，暂不能判断变化原因。可在复盘中补充已确认的适用信息；记录与趋势继续保留。")
    else:
        st.markdown("**可能的解释**")
        st.caption("以下是来源支持的一般解释，不能据此确认本次变化的原因。")
    from healthzip.science import definitions
    names = definitions(include_observations=True)
    for item in items:
        evidence = item["evidence_context"]
        allowed = evidence["capability_permissions"].get("source_explanation")
        st.write(names.get(item.get("metric_id"), {}).get("title", "本期指标"))
        explanation = item.get("explanation", {})
        reason = explanation.get("reason_code") or explanation.get("error")
        failure_labels = {
            "network_disabled": "未开启解释联网授权，当前使用本地事实与可用依据。",
            "not_configured": "尚未配置解释模型，当前使用本地事实与可用依据。",
            "no_evidence": "没有适用于本次解释的证据，已有记录与图表仍可查看。",
            "validation_failed": "模型返回的事实或引用未通过核验，已保留本地观察；本次模型解释暂不可用。",
            "TimeoutError": "解释服务超时，记录与图表保持可用，可稍后重试。",
            "timeout": "解释服务超时，记录与图表保持可用，可稍后重试。",
            "HTTPError": "解释服务返回错误，可稍后重试。",
            "URLError": "未能连接解释服务，可稍后重试。",
            "OSError": "解释服务连接中断，可稍后重试。",
            "partial_validation": "有一部分模型说明未通过核验，这里展示已核验的段落。",
        }
        if reason in failure_labels:
            st.caption(failure_labels[reason])
        for observation in item.get("deterministic_observations", []):
            text = (observation.get("text") or observation.get("summary")) if isinstance(observation, dict) else observation
            if text:
                st.write(text)
        _show_measurement_explanations(item)
        if not allowed:
            notes = _missing_evidence_notes(evidence)
            st.caption("；".join(notes) if notes else "现有依据尚不足以支持本期变化的解释。")
            if evidence.get("evidence_spans") or evidence.get("source_metadata"):
                _show_sources(evidence, supported=False)
            continue
        extra = (extra_windows or {}).get(item.get("metric_id"), {})
        if extra:
            st.caption(extra.get("label", "此指标使用独立时间窗口"))
        statements = list(dict.fromkeys(statement for claim in evidence.get("matched_claims", [])
                                         for statement in claim.get("statements", [])))
        for statement in statements[:2]:
            st.write(statement)
        if explanation.get("source") == "ai":
            st.write(explanation["summary"])
        _show_sources(evidence, supported=True)


def _show_measurement_explanations(item):
    """Narrow reviewed measurement uses never grant a personal causal claim."""
    explanations = item.get("measurement_explanations", [])
    if explanations:
        st.markdown("**这类记录怎样理解**")
    seen_sources = set()
    for explanation in explanations[:2]:
        st.write(explanation.get("statement") or explanation.get("text", ""))
        for limitation in explanation.get("limitations", [])[:2]:
            st.caption(limitation)
        for source in explanation.get("sources", []):
            url = source.get("canonical_url")
            if url and url not in seen_sources and str(url).startswith(("https://", "http://")):
                st.markdown(f"[{source.get('title') or source.get('source_id') or '查看原文'}]({url})")
                seen_sources.add(url)
    for step in item.get("local_next_steps", [])[:3]:
        text = step.get("text") if isinstance(step, dict) else step
        if text:
            st.write("下一步：" + text)


def render_health_explanation(view, *, workspace, context=None, allow_network=False,
                              root=".local/knowledge"):
    metrics = view.get("workspace_scope", {}).get("metrics", {})
    if not metrics:
        return
    grant = session_network_grant(allow_network)
    context = dict(context or {})
    scope = {key: value for key, value in view.get("workspace_scope", {}).items()
             if key not in {"timings_ms", "query_plan", "cache_policy"}}
    namespace = str(Path(context.get("_workspace_path", workspace)).resolve())
    identity = _digest([PROMPT_VERSION, namespace, str(Path(root).resolve()), _fact_identity(scope),
                        context, allow_network, grant.identity, _model_identity()])
    ui_key = "health_explanation_job_" + _digest([namespace, str(Path(root).resolve()), scope.get("workspace")])
    request_key = ui_key + ":requested"
    submission_error = False
    # A fragment can outlive the page's factual cache. Its click records intent;
    # the full rerun first obtains the current page snapshot, then submits it.
    # Submitting inside the old fragment would immediately invalidate its own
    # result when the rerun advances an expired automatic cutoff.
    request = st.session_state.pop(request_key, None)
    if request is not None:
        snapshot = copy.deepcopy(metrics)
        job_key = _digest([identity, knowledge_clock(root)])
        if request["retry"]:
            job_key = _digest([job_key, time.monotonic_ns()])
        try:
            submit_job(job_key, lambda: _reviewed_explanation(snapshot, context, grant, root))
            st.session_state[ui_key] = {"identity": identity, "key": job_key}
        except RuntimeError:
            submission_error = True
    selected = st.session_state.get(ui_key)
    pending = selected and selected["identity"] == identity and job_result(selected["key"])["status"] == "pending"

    @st.fragment(run_every=0.75 if pending else None)
    def panel():
        if submission_error:
            st.caption("解释任务较多，请稍后重试。事实与趋势不受影响。")
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
            st.caption("依据检索超时。记录和图表不受影响，可以重试。" if
                       status.get("reason_code") == "retrieval_timeout" else
                       "本次解释未完成。记录和图表不受影响，可以重试。")
        elif selected and selected["identity"] != identity:
            st.caption("范围或记录已更新，旧解释不再用于本期数据。")
        if st.button("查阅依据并解释变化", key="health_explanation_run",
                     disabled=bool(status and status["status"] == "pending")):
            st.session_state[request_key] = {
                "retry": bool(status and status["status"] in {"failed", "expired"})}
            st.rerun()
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
