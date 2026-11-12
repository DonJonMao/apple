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
    workbench.seed_core()
    st.caption("公开文献与私有训练记录分库。种子卡不代表已经审核，来源摘要不冒充全文。")
    route = st.selectbox("知识主题", ["strength", "progression", "plateau", "recovery", "energy", "personalization"])
    partitions = st.multiselect("来源分区", ["core", "research"], default=["core", "research"],
                               help="核心教材/正式指导与研究补充分开；接口和动作图示不授予科学建议权限。")
    question = st.text_input("检索专业依据", key="knowledge_question")
    reviewed_questions = sorted({binding["question"]
        for row in workbench.lib.theories.execute("SELECT review_json FROM theory WHERE status='approved'")
        for claim in json.loads(row[0]).get("claims", []) for binding in claim.get("answer_bindings", [])})
    selection = st.selectbox("或选择已明确审核目标与范围的问题", ["使用上方问题", *reviewed_questions])
    if selection != "使用上方问题":
        question = selection
    context = {"corpus_roles": partitions or ["core"]}
    with st.expander("明确问题目标（可选）"):
        st.caption("自由表述未被准确理解时，可明确本次只查询的目标。资料适用范围与指定来源仍会核对。")
        use_target = st.checkbox("明确选择本次目标", key="knowledge_explicit_target")
        if use_target:
            choices = {"渐进训练有哪些任务选择": ("progression_options", "options"),
                "是否必须训练至力竭": ("failure_necessity", "necessity"), "能否确定精确余力目标": ("effort_precision", "precision"),
                "训练组量及其边界": ("volume", "options"), "训练频次及其目标范围": ("frequency", "options"), "组间休息及其边界": ("rest", "options"),
                "持续进阶与初始收益": ("progression_necessity", "necessity"),
                "负荷和次数的关系": ("load_repetition_relation", "explanation"),
                "测量任务的可比范围": ("comparability", "scope"), "来源适用的人群": ("population_scope", "scope"),
                "逐步增加身体活动": ("gradual_progression", "options"), "症状与活动边界": ("symptoms", "scope"),
                "个人效果与因果边界": ("individual_effect", "inference"), "不同训练目标": ("goal_scope", "scope"),
                "周期组织是否必要": ("variation", "necessity"),
                "不显著与实用等效的区别": ("practical_equivalence", "explanation"),
                "非显著结果能说明什么": ("non_significance_interpretation", "explanation"),
                "等效检验与区间的判断逻辑": ("equivalence_test_logic", "explanation"),
                "实用等效界值如何论证": ("equivalence_margin_basis", "explanation"),
                "等效方法的研究设计范围": ("equivalence_design_scope", "scope"),
                "成人身体活动指南的年龄范围": ("adult_guideline_scope", "scope"),
                "安全活动建议的年龄范围": ("activity_safety_scope", "scope"),
                "力量训练的起步安排": ("muscle_strengthening_start", "options"),
                "身体活动增量的大小": ("activity_increment_size", "explanation"),
                "身体活动进阶速度的影响因素": ("progression_rate_factors", "explanation"),
                "力竭的定义": ("failure_definition", "explanation"),
                "回归协方差与HC/HAC适用范围": ("regression_covariance_scope", "scope")}
            chosen = st.selectbox("本次要回答", list(choices))
            confirmed = st.checkbox("我确认本次只查询所选目标；原问题中的其他目标需要另查", key="knowledge_target_confirmed")
            if confirmed:
                outcome, relation = choices[chosen]
                statistical = {"practical_equivalence", "non_significance_interpretation", "equivalence_test_logic", "equivalence_margin_basis", "equivalence_design_scope", "regression_covariance_scope"}
                physical_activity = {"adult_guideline_scope", "activity_increment_size", "progression_rate_factors", "activity_safety_scope"}
                subject = "statistical_inference" if outcome in statistical else "physical_activity" if outcome in physical_activity else "resistance_training"
                context["question_contract"] = {"subject": subject, "outcome": outcome,
                    "requested_relation": relation, "user_confirmed": True}
            else:
                st.caption("确认前按原问题检索，不把尚未确认的选择当作你的目标。")
        source_ids = [row[0] for row in workbench.lib.sources.execute("SELECT source_id FROM source ORDER BY source_id")]
        required_sources = st.multiselect("限定具体来源（留空表示不限）", source_ids)
        edition = st.text_input("限定版次标识（可选）", key="knowledge_requested_edition")
        chapter = st.text_input("限定章节标识（可选）", key="knowledge_requested_chapter")
        if required_sources or edition or chapter:
            context["source_constraints"] = {"source_ids": required_sources, **({"edition_id": edition} if edition else {}), **({"chapter_id": chapter} if chapter else {})}
    if st.button("查询本地证据"):
        result = workbench.query(question, route=route, context=context)
        st.write(result["answer"])
        st.caption(f"状态：{result.get('answer_status', result.get('status', 'unknown'))} · 主题：{route}")
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
    with st.expander("核心书目、章节覆盖与应用规则"):
        core = workbench.core_status()
        st.caption("书目登记、正文取得、主张核对和产品规则各有状态；AI辅助核对不等于独立专家审核。")
        for row in workbench.lib.sources.execute("SELECT source_id,manifest_json FROM source ORDER BY source_id"):
            manifest = json.loads(row["manifest_json"])
            if "core" not in manifest.get("corpus_roles", []):
                continue
            st.write({"source_id": row["source_id"], "title": manifest["title"], "edition": manifest.get("edition"),
                      "source_kind": manifest.get("source_kind"), "official_urls": manifest.get("official_urls")})
        st.write({"registered_rule_count": core["distinct_rule_count"], "effective_rule_count": core["effective_rule_count"]})
        st.caption("当前正文状态按有效解析、许可和来源状态重新核对。预置主题尚未逐项关联时，已取得正文也不代表该主题完整覆盖；主张及规则审核另列。原始登记状态保留供追溯。")
        st.json(core["current_chapter_coverage"])
        st.json(core["rules"])
