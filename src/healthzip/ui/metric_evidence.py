"""Explicit metric evidence lookup shared by the six fixed analysis functions."""
import streamlit as st

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.domains import configuration
from healthzip.science import definitions
from healthzip.workflows.contracts import FUNCTION_NAMES


def render_metric_evidence(metrics):
    cfg, names = configuration(include_observations=True), definitions(include_observations=True)
    with st.expander('指标的原始依据与解释'):
        task = st.selectbox('分析功能', list(cfg['functions']),
            format_func=lambda key: FUNCTION_NAMES.get(key, cfg['functions'][key]['title']), key='metric_evidence_function')
        available = [mid for mid in metrics if task in cfg['profiles'][mid]['analysis_functions']]
        if not available:
            st.info('当前结果没有此功能对应的 MetricResult，暂不能按指标检索。')
            return
        mid = st.selectbox('查看指标依据', available,
            format_func=lambda key: names[key]['title'], key='metric_evidence_metric')
        candidate_scope = st.selectbox('依据范围', ['reviewed_metric', 'all'],
            format_func=lambda key: {'reviewed_metric': '已审核的指标依据',
                'all': '同领域资料（含待审核阅读材料）'}[key], key='metric_evidence_scope')
        mode = st.selectbox('检索方式', ['lexical', 'hybrid_rerank', 'hybrid', 'dense'],
            format_func=lambda key: {'lexical': '本地词项检索', 'hybrid_rerank': '混合检索并精排',
                                    'hybrid': '混合检索', 'dense': '语义检索'}[key])
        st.caption('语义检索和精排仅发送固定指标任务与公开资料；需要本机配置中的资料联网授权。个人结果另受下方解释授权控制。')
        population = st.selectbox('已明确的适用人群', ['unknown', 'adults', 'healthy_adults', 'trained_adults', 'adult_athletes'],
            format_func=lambda key: {'unknown': '尚未说明', 'adults': '成年人', 'healthy_adults': '健康成年人',
                'trained_adults': '有训练经验的成年人', 'adult_athletes': '成年运动员（已核对来源范围）'}[key],
            key='metric_evidence_population')
        protocol = st.text_input('该指标的已知测量协议（未知时留空）', key='metric_evidence_protocol')
        context = {'population': population, 'measurement_protocol': protocol}
        if mid in {'LOAD-SRPE', 'LOAD-SRPE-AU'}:
            st.caption('请按实际采集记录填写。逐组 RPE、RIR 和训练前计划强度不能代替训练后的整场评分。')
            context['srpe_scale'] = st.selectbox('整场感知强度量表',
                ['unknown', 'Foster_modified_CR10', 'other'],
                format_func=lambda key: {'unknown': '尚未确认', 'Foster_modified_CR10': 'Foster 修改 CR-10（整场）',
                                         'other': '其他量表'}[key], key='metric_evidence_srpe_scale')
            context['srpe_collection'] = st.selectbox('整场评分采集时点',
                ['unknown', 'retrospective_after_session', 'before_or_during_session'],
                format_func=lambda key: {'unknown': '尚未确认', 'retrospective_after_session': '训练结束后回顾整场',
                                         'before_or_during_session': '训练前或训练中'}[key], key='metric_evidence_srpe_collection')
        allow = st.checkbox('允许将此指标的结构化计算结果发送给已配置的解释服务', value=False)
        if st.button('查找原始依据并解释此指标', key='metric_evidence_run'):
            w = KnowledgeWorkbench('.local/knowledge')
            try:
                response = w.explain_metric(mid, task, metrics[mid],
                    context, mode=mode, candidate_scope=candidate_scope,
                    allow_explanation_network=allow)
            finally:
                w.close()
            evidence = response['evidence_context']
            st.write(response['explanation']['summary'])
            if evidence['status'] == 'insufficient_evidence':
                st.info('当前原文、审核或适用信息不足，不能据此形成来源支持的个人解释。')
            if evidence['retrieval_audit']['retrieval_degraded']:
                st.warning('部分检索服务不可用，本次结果已降级。')
            for span in evidence['evidence_spans']:
                st.write(span['source_metadata'].get('title'), span['content'])
                st.caption(f"{span['source_id']} · {span['source_version']} · {span['section_path']} · {span['evidence_role']}")
                st.json(span['locator'])
            st.json({'limitations': evidence['limitations'], 'permissions': evidence['capability_permissions'],
                     'conflicts': evidence['conflicts'], 'retrieval_audit': evidence['retrieval_audit']})
