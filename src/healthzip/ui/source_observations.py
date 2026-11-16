"""Display source observations with the same canonical window and provenance."""
import streamlit as st

from healthzip.science.observations import definitions


def render_source_observations(observations):
    for mid, definition in definitions().items():
        if mid not in observations:
            continue
        metric = observations[mid]
        with st.expander(definition['title']):
            st.caption(f"{metric['window']['start']} 至 {metric['window']['end']} · 数据截止 {metric['cutoff_time']}")
            if metric['value'] is None:
                st.info('当前窗口没有可用的已导入记录；缺少记录不代表没有相应生理现象。')
            else:
                for stream in metric['value']['streams']:
                    st.write({'来源': stream['source_name'], '设备': stream['device'],
                        '来源版本': stream['source_version'], '协议': stream['protocol_id'] or '未核验'})
                    st.dataframe(stream['observations'], hide_index=True, use_container_width=True)
            st.caption(f"可用记录 {metric['valid_n']}/{metric['total_n']} · {metric['data_status']}")
            for limitation in metric['limitations']:
                st.caption(limitation)
            with st.expander('记录来源及完整计算依据'):
                st.json(metric)
