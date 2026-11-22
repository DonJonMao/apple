"""Read current public methods independently of a personal fact snapshot."""
import sqlite3
from pathlib import Path

import streamlit as st

from healthzip.knowledge import KnowledgeWorkbench
from healthzip.knowledge.revisions import knowledge_authority_clock
from healthzip.knowledge.topics import TOPICS, question_sources


def render_topic_sources(topic, *, root='.local/knowledge'):
    if topic not in TOPICS:
        return
    with st.expander('依据与原文'):
        if not all((Path(root) / name).is_file() for name in ('sources.sqlite3', 'theories.sqlite3')):
            st.caption('当前工作区尚未配置资料库。')
            return
        key = ('topic_sources', str(Path(root).resolve()), topic)
        clock = knowledge_authority_clock(root)
        if st.button('查阅本题依据', key=str(key)):
            w = None
            try:
                w = KnowledgeWorkbench(root)
                answer = question_sources(w, topic)
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
        if result['status'] == 'conflicting':
            st.caption('本题来源存在尚待核对的分歧。')
        elif not result['items']:
            st.caption('本地资料尚无适用于这项问题的已审阅说明。')
        for source in result.get('field_definitions', []):
            st.markdown(f"[Apple 字段定义 · {source['symbol']}]({source['url']})")
        for item in result['items']:
            st.write(item['statement'])
            for limit in item['limitations'][:2]:
                st.caption(limit)
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
