# 六项工作流缺陷修复验收

> 2026-11-18 四项后续修复追加在本文末尾；此前六项验收及回执仍是历史证据。

审查基线：`6f3a8e1cf1947455366190d87858cfd0d8206545`。本轮版本：`analysis-workflows-1.6.2`。只处理六项现有缺陷及必要的调用关联，不重新开展资料审查、教材获取、向量构建或科学验证。

## 逐项行为与证据

|问题|原复现场景|修复位置|行为回归|
|---|---|---|---|
|1 多任务结构|两种器械或动作的 STR-11 汇总是映射，W2 因当作行列表而崩溃|`science/contracts.py::task_metric_results`；`workflows/facts.py`、`selection.py`、`service.py`；工作流页面|`test_workflow_six_repairs.py::test_w2_and_calendar_reports_handle_real_task_shapes`：真实训练生成单任务、多器械、多动作的指标、事实及周/月报告|
|2 365 日覆盖近期|最近六次 10/10/9/10/10/10、RIR2 无改善，但 300 日前的 8 次掩盖近期分支|`advice.py::freeze_candidate`；`analysis_settings.py`；候选页面、工作流页面及 CLI|`test_candidate_default_review_does_not_replace_recent_scope_with_history_search`；`test_candidate_reuse_runs_selected_scope_without_rewriting_candidate`：30 日六条背景、14/45/365 日、重复请求及原快照不变|
|3 上下文未传递|合成主张要求 adults，手动满足而自动报告丢失所选声明|`analytics/v13.py`、`analytics/core.py`、`workflows/reports.py`、`storage.py`、`dependencies.py`；练前及页面请求|`test_analysis_workflow_evidence.py::test_confirmed_context_reaches_automatic_review`；交叉测试：实际词法检索/条件判定，未知和错误人群拒绝，更新/撤回后当前使用受限，旧运行不改|
|4 本期新任务遗漏|新动作或新器械只出现在本周/本月，历史两期没有它|`workflows/reports.py`、`service.py::_select_metrics`；长期趋势任务选择控件|`test_current_period_new_tasks_are_included_without_invented_history`：week/month × 新器械/新动作/完全无历史；当前事实可追溯，历史为空且不补零|
|5 下载漏数值|W3 已有 40→42、变化2，周期复核下载没有它们|`workflows/presentation.py`、`reports.py::markdown`；下载、候选展示、完整报告调用点|`test_w3_download_contains_frozen_observations_and_change`；`test_w5_download_complete_day_values_and_frozen_coverage`；交叉测试覆盖 W1/W2/W4、当前周期、数据修改后的历史下载不变|
|6 旧事实配新依赖|检索中真实编辑 10→12，旧10仍被判 current|`workflows/service.py`、`dependencies.py::input_version`|`test_interleaved_real_revision_never_saves_old_facts_with_new_current_dependencies`：检索及冻结前两个同步点 × 编辑/删除/迟到导入/无关草稿/无变更；`test_context_withdrawn_during_retrieval_refuses_freeze_without_orphans`|

上述 `test_workflow_six_repairs.py` 位于 `tests/integration/`，`test_analysis_workflow_evidence.py` 位于 `tests/knowledge/`。组合用例 `test_cross_entry_context_multitask_candidate_reuse_and_calendar_download` 同时经过多任务、本期新任务、明确上下文、近期无改善、候选复用、反馈及周/月下载；没有 mock 最终指标、证据权限或 current 判断。原有 W1 页面完整候选闭环及 W2–W5 页面回归继续执行。

## 范围、上下文和冻结合同

- 候选的 365 日范围仅用于找历史参考及既有数值规则。复核使用 `WorkflowRequest` 的窗口、截止时刻、时区、模式、上下文与来源选择引用。默认查看 30 日、背景回看 28 日是共享产品设置，不是生理阈值；页面传当前选择，CLI 提供 `--review-days`、`--review-cutoff`、`--context-id`。手动工作流中的候选继承保存请求的范围；W4 的周/月比较将前两个完整周期的实际起止传入 W1，避免将同一周期标签误解为当前部分周期。对应 `test_candidate_from_calendar_trend_keeps_complete_comparison_bounds` 两项边界回归通过。
- 候选幂等键继续表示业务意图。改变复核范围不增加候选、采纳或执行记录；复用时仍运行复核，通过新 workflow_run 的 parent/candidate 引用关联，返回 `current_analysis_review`。候选原 `input_snapshot.analysis_review` 不覆盖，页面分开显示原冻结与后续复核。
- 并发的同一候选请求若已由另一请求成功保存，仅此前瞻请求可重新执行完整复核后复用候选；没有匹配业务候选或回顾模式时，不自动重试。重试预算仅是软件资源限制，后续计算仍通过相同一致性检查。
- 只有明确选择的 `workflow_context_id` 从分析快照传入报告；练前请求直接传 `context_id`。页面按本地库保存当前明确选择的版本，不查询数据库“最新一条”。无声明仍为 unknown。`save_context(..., replaces_context_id=...)` 和 `withdraw_context` 追加生命周期事件，当前使用检查识别失效；历史运行不回写。重新确认已撤回内容会产生新版本。
- 上述上下文生命周期限制相应工作流的来源解释，不新增数值行动门槛。候选当前使用继续按实际个人档案、记录、目标和独立 ApplicationRule 核对。`test_withdrawn_explanation_context_does_not_revoke_independent_action_rules` 验证分析需要复核时，另有有效规则的候选仍可使用。
- 周/月任务按语义 task_id 合并前两个完整周期与当前未完成周期的实际任务。选中任务必须在其中一个合法分支可见；历史缺失只计算空任务指标，不借其他器械或伪造历史。反馈仍按实际时间归期。
- `markdown(..., repo=repo)` 读取 workflow_run 关联的冻结 analysis_run 以及已冻结分段/覆盖/本期事实；不调用分析器重算。正文包含名称、数值、单位、日期/范围、样本、来源/协议/算法版本和边界；补充审计字段单列。W5 的 2000 是四个完整日的平均，不是补零后的周平均或真实 TEE。
- 记录事件截止时间与分析读取时的数据可见时刻分别保存。计算前记录训练、来源、档案、目录和所选上下文版本；检索前捕获同一范围的依赖，最终短写事务内验证。相关中途修订明确拒绝冻结并要求重试；不把所有运行标为 needs_review。时钟变化时仅在短事务内复查本地相关依赖，确认为无关的写入仍允许原结果保存。检索不占用写事务，失败回滚 analysis_run/workflow_run 两表。

schema 仍为 5，沿既有幂等迁移追加 `workflow_context_event` 及上下文缓存版本。旧运行、来源/主张/规则、权限、分析方法和已发布工件不改写。本轮只打开隔离合成库；真实本地库的备份/恢复遵守原交付文档。

## 本轮验证记录

修正夹具后在基线代码副本复现 **15 failed、4 passed、13 deselected（23.58 秒）**，包括真实多动作和正确类型的人群条件；不是以夹具错误充当生产缺陷。早期日志里的器械类型不匹配、无效合成条件 origin、反馈缺少必填原因和合成知识根目录缺失均单独修正，未降低验收断言。

新增定向回归 37 项通过；整仓首跑发现候选并发请求的关联退出问题，修复后包含原并发用例及六项回归的 31 项通过。首跑在 126 passed / 1 failed 时中断，保留开发身份；重新制作隔离副本进行最终整仓验证，不将中断运行计为通过。

日历范围传递补充后，第二次整仓在 123 passed / 0 failed 时中断并重新制作最终副本；这次中断也不计作整仓通过。日历范围两项定向回归保留原边界断言。

权限边界补充回归发现并移除了开发过程中增加的多余候选限制；第三次整仓因此中断，pytest 在中断清理临时目录时出现 KeyError，没有完整汇总，不计作完成。最终代码定向验证 **45 passed、0 failed（73.84 秒）**，涵盖独立行动权限、六项缺陷、交叉场景及原有候选幂等/并发。

最终定向、整仓和 Ruff 结果及受验代码文件哈希见 [`workflow-six-fixes-verification.json`](../artifacts/analysis-core/workflow-six-fixes-verification.json)。旧 1710 项回执保持历史身份，不能用来证明本轮通过。

最终隔离整仓执行 `PYTHONPATH=src <repo>/.venv/bin/python -m pytest -q`：**1744 passed、0 failed、0 skipped、0 warnings，633.42 秒，退出码 0**。既定 `ruff check src tests app.py tools/analysis_core*.py` 通过。301 份源代码、测试、配置、夹具和规范输入在主工作区与受验副本之间逐文件哈希一致；清单 SHA256 为 `dbfa36d75ea1de403e286e32fc677ec7608f504ffc071521028ee603f428bcff`。原始日志保留在本机，公开回执只保存摘要与哈希。

验收仅证明六项软件缺陷修复。描述性未改善仍不等于统计/生理停滞；来源解释及独立有效行动仍按现有权限使用。不新增科学 Gold、个人因果确证、真人校准或干预效果结论。

## 2026-11-18：四项后续修复

审查基线 `281ef9bda66322b26e9da4afbf4231da4512095c`，实现版本 `analysis-workflows-1.6.3`。本轮默认固定同一家健身房、既有重量口径稳定；继续使用真实 task_id、candidate_id、动作条件及既有负荷语义，不要求场馆登记、器械校准或跨场馆换算。未重新开展资料复核、四本教材获取、知识库或向量重建。

|问题|原场景与根因|修复及验证|
|---|---|---|
|周期反馈串入|A 只有历史参考，B 本期有反馈；过滤依赖 partial_task 是否存在，导致 A 继承全局反馈|`workflows/service.py` 始终使用已选任务身份调用 `scoped_metrics`，同时重算 STR-27、STR-28、FOLLOWUP。周/月 × 只有 A、只有 B、双方、均无反馈，检查候选、状态、分母和汇总；A 未训练时自己的反馈仍保留。|
|声明替换后页面悬空|输入 invalid 截止时刻，旧声明已停用、页面选择却未更新；刷新自动分析在控件前失败|`ui/workflow_page.py` 在保存前校验请求格式和可检查约束，声明提交后立即同步页面选择；后续计算失败仍引用真实已提交版本。`workflows/storage.py`、`analytics/core.py` 和 `app.py` 对明确失效的选择保留 ID、显示恢复提示及事实，不自动选最新版本或静默改 unknown。真实 app.py AppTest 覆盖无效输入、修正、第二连接中途修改导致分析失败、外部撤回/替换后重新确认。|
|历史报告与当前行动混用时刻|W4 保存后新建训练，候选用旧 cutoff 重建新训练而报不可见；仅更新 cutoff 又会移动日历范围|`advice.py` 按 `source_run_id` 读取原冻结快照的实际起止，新 W1 使用当前行动时刻及当前目标；服务复核任务、范围、时区、模式、声明和来源选择。原 W4 不作跨工作流 parent；原报告、当前复核和候选分别可追溯。跨周/月、新增计划组、修改目标、历史记录修订、删除目标/变更条件、重复候选及真实页面路径均有回归。|
|W2 漏体重依赖|检索期间第二连接用公开增量接口把 80 修订为 90，旧背景仍保存且误判 current|`workflows/dependencies.py` 将 body_mass_kg 纳入 W2 已有类别和背景窗口查询，覆盖修订、删除及迟到新增；冻结前已有版本/依赖核对拒绝相关变化且不留半保存。无观察的草稿不进入 W2 会话依赖，窗口外体重也不使结果失效。并检查 W1/W2/W4/W5 的 CSV 体重来源依赖。|

新增行为回归集中在 `tests/integration/test_workflow_four_repairs.py`。组合用例按真实服务串联：两个动作 → 旧报告 → 后来新建训练 → 生成/复用候选 → 分别反馈 → 周/月报告 → 页面与实际下载载荷核对。下载只截获传输载荷，计算、归属、权限和 current 判断均由真实服务执行。反馈编辑后旧运行及旧下载仍不改变。

声明只影响其授权的来源解释；未增加数值行动规则或修改独立候选的当前使用权限。后台自动复核发现已选声明失效时暂停该声明的解释，保留明确原因及原始事实，用户在原页面重新确认即可保存新版本。完整分析和检索不占用声明写事务；外部撤回不会被失败重试悄悄恢复。

`source_run_id` 是 JSON 请求中的冻结来源引用，无私有数据库 schema 升级。新复核显式保存原报告 cutoff、analysis_run_id、实际历史起止和当前行动 cutoff；重新读取历史范围内现可见的修订也是新运行。原工作流 parent 仍只允许同一 workflow_id。候选的幂等键保持业务意图，复用候选只追加复核，不重复采纳、执行或反馈。W4 页保存反馈续算候选的 W1，保持已选 W4 的冻结范围。

本轮先在基线完成四项复现：修正非行为字段的测试比较后 **7 failed、4 passed，24.44 秒**。初版测试中直接比较分别计算的 MetricResult 时间戳，以及把自动新运行误当成旧运行被修改，均已改为核对实质指标/分母及逐个旧 run_id 的不可变内容；没有降低任务归属或科学权限断言。

定向组合首次执行为 **85 passed、1 failed，193.88 秒**：旧 W4 页面回归发现反馈回调只传 candidate_id，而新续算代码读取完整候选对象。已改为从实际候选记录与同来源的 W1 复核解析引用，保留原测试断言。最终定向执行四项新回归、此前六项、长期复核、W1、来源权限及候选幂等/并发文件：**93 passed、0 failed、0 skipped、0 warnings，203.93 秒**。既定 Ruff 通过。

最终隔离整仓 `PYTHONPATH=src <repo>/.venv/bin/python -m pytest -q`：**1779 passed、0 failed、0 skipped、0 warnings，718.51 秒，退出码 0**。既定 `ruff check src tests app.py tools/analysis_core*.py` 通过，退出码 0。最终整仓只执行一次并完整结束，未跳过测试或中断重跑。

302 份代码、测试、配置、合成夹具及规范输入在受验副本与当前工作区逐文件哈希一致；清单 SHA256 为 `c868b6fdf3c4fcca230bb10807693e62de26dfcb66f7f3a37ede32892c0c756e`。新的完整结果、命令、工具版本、日志哈希和输入清单见 [`workflow-four-fixes-verification.json`](../artifacts/analysis-core/workflow-four-fixes-verification.json)，此前 1744 项回执保持历史身份。

本轮四项软件验收通过。描述性未改善仍不是严格统计/生理停滞，来源解释和独立行动规则仍按既有适用范围核对；这些回归不构成个人因果确证、真人校准或真实干预效果验证。
