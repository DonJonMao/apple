"""Read-only evidence browsing; acquisition is an explicit public-data command."""

import streamlit as st

from healthzip.knowledge import KnowledgeWorkbench


def render_knowledge():
    workbench = KnowledgeWorkbench(".local/knowledge")
    try:
        _render(workbench)
    finally:
        workbench.close()


def _render(workbench):
    workbench.seed()
    st.caption("公开文献与私有训练记录分库。种子卡不代表已经审核，来源摘要不冒充全文。")
    route = st.selectbox("知识主题", ["strength", "progression", "plateau", "recovery", "energy", "personalization"])
    question = st.text_input("检索专业依据", key="knowledge_question")
    if st.button("查询本地证据"):
        result = workbench.query(question, route=route)
        st.write(result["answer"])
        st.caption(f"状态：{result.get('status', 'unknown')} · 主题：{route}")
        for observation in result.get("observations", []):
            st.write(observation)
        for limit in result.get("limits", []):
            st.caption(limit)
        for citation in result.get("citations", []):
            with st.expander(f"来源 {citation['source_id']} · {citation.get('evidence_level_used', '')}"):
                st.json(citation)
                for span_id in citation.get("span_ids", []):
                    st.write(workbench.lib.span(span_id))
    with st.expander("来源获取与理论审核状态"):
        st.json(workbench.status())
