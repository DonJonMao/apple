# 力量/统计复审：912aefc

基线：`912aefc93b9bd9c1cebf297a10728c69c827e266`，工作树 `/workspace/scratch/a74a838d7f65/apple_review_912aefc`。已先读AGENTS、CODEX_GOAL、DESIGN_SPEC、V1_3_GOAL；只读审查，未外网采集，未修改仓库，未运行全套pytest。

## 原问题验证

| 原ID | 本次结论 | 实际验证 |
|---|---|---|
| R01 多动作参考丢弃 | **原场景通过** | Repository默认分析两动作各有3条参考及独立描述趋势；`reference_rows`现在按任务与session分组。下面N01为负荷变化的额外场景，不能继续把旧多动作丢弃说成未修。 |
| R02 UI协议不可用 | **通过** | 实际Streamlit控件填写协议ID、版本、参考规则、努力、节奏、休息；三场记录产生协议完整的描述趋势。旧自由文本保留为备注、不猜测结构化值，处理正确。 |
| R03 STR-26未接UI | **通过** | 模板与临时训练真实控件支持策略选择、当组目标、候选冻结、采纳、执行和历史反馈；有合成授权且协议完整时能产生低次数增重试验。无授权/协议未知仍不量化，处理正确。 |
| R10 alpha未消费 | **原问题通过** | 页面首看0.025对应97.5%区间；重复同快照复用receipt；改记录后下一预算被消费。当前正式推断仍受真实校准门控，不将缺真人资料列为缺陷。 |

独立运行7个聚焦Repository/Streamlit用例，**7 passed in 31.43s**。最终JUnit：`old_findings_regression.xml`。覆盖：`test_r01_default_repository_analysis_has_independent_action_tasks`、`test_r02_three_sessions_from_page_produce_protocol_identified_trend`、4个参数化`test_visible_candidate_task_end_to_end`、`test_r10_actual_analysis_view_registers_and_consumes_budget`。

## 剩余高影响问题

### N01 · P2：正常加重会使整个任务的描述趋势失效，已有同负荷子序列也不可见

**位置**：`src/healthzip/science/semantics.py:106–116`（任务身份未包含用于次数趋势的负荷层）；`src/healthzip/science/engine.py:132–146`（只按该任务分组后把全部记录交给各指标）；`src/healthzip/science/strength.py:237–241`（发现任意负荷不同就整体返回incompatible）。

**场景与最短复现**：同动作、器械、幅度和完整协议，先在30kg记录10/12/11次，再在32.5kg记录8/10/9次，各为不同场次的预指定参考。运行默认`evaluate_all`。

**Actual**：单独传30kg三次或32.5kg三次，STR-19均`valid`且有描述斜率；全部六次一起传入，只有1个任务，STR-19变成`incompatible`、value=null，原因`trend_reference_conditions_incompatible`。原始计数保留，但两个本来可计算的同负荷趋势都不提供。无需任何校准也能复现。

**Expected**：不应把不同负荷硬合成一条次数斜率；应保留同动作任务下各明确负荷/单位/观察协议的测量子序列，至少显示当前负荷层和历史负荷层的描述趋势、跨度及排除原因。跨负荷能力映射仍保持未验证。规范STR-19本就要求“改变负荷建立另一测量层或用已验证映射”。正常进阶不应反过来令已有分析全部消失。

**影响**：实际用户经常加重或减重；当一个观察窗口内出现不同重量时，功能3描述层会普遍退化。当前多动作修复只解决物理任务拆分，尚未解决指标特有的测量口径拆分。

**修法**：保留跨负荷的动作物理任务ID供STR-13等使用；为STR-19/20/22建立明确的`outcome_series_id`，按归一后可审计的负荷、单位/口径、协议及有效观察段选序列。不要全局把重量塞入所有任务键，以免阻断同次数负荷比较；也不要用未经验证e1RM静默连接。

**验收**：六次混合负荷记录应保留两个描述序列且各n=3；当前负荷的斜率须与单独计算三条一致。原值、时间支持和来源ID可追溯。不同单位仅在口径完整、可精确归一时合并；未知质量/协议保持相应排除。无校准时两序列均不发布正式停滞。

### N02 · P2：校准范围检查只比较调用者提供的键，遗漏关键适用条件反而可通过

**位置**：`src/healthzip/science/registry.py:200–211`，尤其211行；STR-22调用在`src/healthzip/science/strength.py:270,278`。

**最短复现**：仅测试谓词，不伪造真人验证或写注册表。给定一个形状为已校准的测试对象，其scope限定`exercise_id=bench`、`population=trained_adults`、`outcome_unit=repetitions`、`protocol_id=reference_v1`。调用`calibration_matches(..., scope={'population':'trained_adults'})`。

**Actual**：返回True；完整scope且exercise_id=squat返回False；空scope返回False。也就是说，只保留一个可匹配字段、删掉动作/协议/单位，反而越过了这些必要限制。根因是`all(...)`遍历调用方scope，而不是验证工件声明的完整必需适用条件。

**Expected**：关键适用项未知必须返回False并给缺项原因。调用方声明scope不应比从真实任务和测量序列推导的范围更宽。存在真实校准资料并不能证明该资料适用于缺失上下文或其他任务。

**影响与边界**：当前缺真人校准时STR-22仍正确拒绝正式结论；本问题不是要求立即启用正式标签。它是正式启用所依赖的范围门控本身不正确：以后接入一项真实但限于特定动作/协议的工件，部分scope即可使该限定丢失。应在接入真实校准前修复。

**修法**：为校准工件明确`required_scope`和可选范围约束，从任务、单位、协议版本与人群资料构造实际scope。逐个验证工件必需条件已知且匹配，不接受调用者以省略键放宽范围。范围验证失败不能退化为“部分键匹配”。保留不可变工件ID与审阅/验证状态，不改动无资料时的保守行为。

**验收**：完整正确scope=True；错误动作=False；遗漏动作/协议/单位=False；人群未知=False；额外不影响适用性的审计字段不应凭空扩大授权或造成不必要拒绝。加入真实任务scope与输入context冲突的反例，结果必须以可追溯真实字段为准。

## 已落盘复现

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python /workspace/scratch/a74a838d7f65/review912/strength/repro_remaining.py
```

在新工作树执行。脚本`repro_remaining.py`，完整输出`repro_remaining.json`。输出同时保存一个未升格为当前高影响发现的检查：STR-21会拒绝kg等效界限与次数终点不符，单独STR-22没有共享这项量纲校验，但目前其他门控仍保留unknown。建议统一推断输入验证，避免以后单指标入口绕过相邻指标检查；不将此描述成当前已向用户发布错误停滞。

## 权威教材/指南驱动候选所需的最小接口

这些是下一步实现建议，不是额外复审失败项：

1. `GuidelineClaim`挂在既有TheoryCard/SourceVersion上：教材/指南名称、ISBN/DOI、版次、章节页码/表格、原文span、适用人群、任务/协议、建议性质、证据级别、授权用途和人工审核版本。书籍的权威身份不能自动授予所有处方数值。
2. `CandidateRule`把已审阅主张操作化：允许行动、所需个人事实、明确不适用/未知条件、可执行目标的来源类别、可提供的限定语与退出/复核任务；若有数值规则，必须记录原文对应位置与适用边界。用户目标、器械档位、统计参数和文献规则分别保存，禁止任意加权恢复分。
3. `propose_candidates(task_snapshot, user_goal, permitted_actions, evidence_release)`返回候选及逐条审计：匹配了哪项规则、哪些条件成立/未知、哪些候选被排除及原因、所提数值是目标还是模型估计、执行后观察什么。未知不能被默认视作满足；LLM负责解释，计算服务负责数值。
4. 保留来源冲突，不用投票或综合分混平。指南支持一般进阶原则，并不证明某个人必然能完成下一档。没有个体效应证据时仍可提供有明确前提、可撤回的用户选择试验，不能以“须真人验证”为由删除整个执行/反馈流程。

未重复统计训练分支已经发现的疼痛/技术限制门控问题，也未重复主评审的全历史性能问题。
