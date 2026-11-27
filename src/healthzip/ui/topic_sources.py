"""Read current methods with optional local computed-question eligibility."""
import sqlite3
from pathlib import Path

import streamlit as st

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.revisions import knowledge_authority_clock
from healthzip.knowledge.topics import TOPICS, question_sources


def render_topic_sources(topic, *, root='.local/knowledge', computed_question=None):
    if topic not in TOPICS:
        return
    with st.expander('依据与原文'):
        if not all((Path(root) / name).is_file() for name in ('sources.sqlite3', 'theories.sqlite3')):
            st.caption('当前工作区尚未配置资料库。')
            return
        from healthzip.knowledge.topics import ANSWER_NEEDS_VERSION
        key = ('topic_sources', str(Path(root).resolve()), topic,
               (computed_question or {}).get('fact_id'), ANSWER_NEEDS_VERSION)
        clock = knowledge_authority_clock(root)
        if st.button('查阅本题依据', key=str(key)):
            w = None
            try:
                w = KnowledgeWorkbench(root)
                answer = question_sources(w, topic, computed_question=computed_question)
                if knowledge_authority_clock(root) == clock:
                    st.session_state['_current_topic_sources'] = (key, clock, answer)
                else:
                    st.caption('资料在查询期间更新，请重新查阅。')
            except (sqlite3.Error, OSError, ValueError):
                st.caption('本次资料查询未完成，可重新查阅。')
            finally:
                if w:
                    w.close()
        saved = st.session_state.get('_current_topic_sources')
        if not saved or saved[:2] != (key, clock):
            return
        result = saved[2]
        if result['status'] in {'conflicting', 'partial_conflict'}:
            st.caption('部分主张存在分歧；以下独立说明仍可使用，相关争议及依赖它的建议单独列出。')
        elif not result['items']:
            st.caption('本地资料尚无适用于这项问题的已审阅说明。')
        for source in result.get('field_definitions', []):
            st.markdown(f"[Apple 字段定义 · {source['symbol']}]({source['url']})")
        for item in result['items']:
            st.write(item['statement'])
            for limit in item['limitations']:
                st.caption(limit)
            if item.get('scope'):
                with st.expander('这条说明的适用范围'):
                    labels = {'population': '研究人群', 'population_and_design': '研究人群与设计',
                              'devices': '设备', 'measurement_conditions': '测量条件',
                              'comparison_method': '比较方法', 'metric': '指标',
                              'study_population': '研究人群', 'study_scope': '研究范围',
                              'protocol': '测量协议', 'device_family': '设备范围'}
                    for field, label in labels.items():
                        if item['scope'].get(field):
                            st.write(f"{label}：{item['scope'][field]}")
                    st.caption('这是原资料的适用范围，不代表当前用户或设备已经符合这些条件。')
            seen = set()
            for source in item['citations']:
                if source['url'] in seen:
                    continue
                seen.add(source['url'])
                section = source.get('section')
                if source['url'] and source['url'].startswith(('https://', 'http://')):
                    st.markdown(f"[{source['title']}]({source['url']})")
                if section:
                    st.caption(section)
        restricted = result.get('restricted_items', [])
        if restricted:
            with st.expander('有分歧的说明与受限建议'):
                for item in restricted:
                    st.write(item['statement'])
                    st.caption('该主张或其必要前提存在未解决分歧，不能作为确定建议。')
                    for limitation in item['limitations']:
                        st.caption(limitation)
                    for source in item['citations']:
                        if source['url'] and source['url'].startswith(('https://', 'http://')):
                            st.markdown(f"[{source['title']}]({source['url']})")
