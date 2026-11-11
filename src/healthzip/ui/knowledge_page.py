"""Read-only browsing distinguishes related reading from supported answers."""

import json

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
    reviewed_questions = sorted({binding["question"]
        for row in workbench.lib.theories.execute("SELECT review_json FROM theory WHERE status='approved'")
        for claim in json.loads(row[0]).get("claims", []) for binding in claim.get("answer_bindings", [])})
    selection = st.selectbox("或选择已明确审核目标与范围的问题", ["使用上方问题", *reviewed_questions])
    if selection != "使用上方问题":
        question = selection
    if st.button("查询本地证据"):
        result = workbench.query(question, route=route)
        st.write(result["answer"])
        st.caption(f"状态：{result.get('status', 'unknown')} · 主题：{route}")
        with st.expander("目标主张、适用条件与证据关系"):
            st.json(result["support_assessment"])
        for observation in result.get("observations", []):
            st.write(observation)
        for limit in result.get("limits", []):
            st.caption(limit)
        for citation in result.get("citations", []):
            with st.expander(f"来源 {citation['source_id']} · {citation.get('evidence_level_used', '')}"):
                st.json(citation)
                for span_id in citation.get("span_ids", []):
                    st.write(workbench.lib.span(span_id))
        for material in result.get("related_materials", []):
            with st.expander(f"相关阅读：{material['theory_id']} · 不等于当前问题已获支持"):
                for statement in material["source_statements"]:
                    st.write(statement)
                st.json(material["evidence_links"])
    with st.expander("来源获取与理论审核状态"):
        st.json(workbench.status())
