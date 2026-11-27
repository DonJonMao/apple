# R06：普通训练工作流冻结存储方案与实施记录

分析基线：`6f7d9c3`。以下先记录只读核查与最小实现边界，末尾单列随后获分配的实施和验证；旧结果没有迁移。最终三档实际计量已完成：两压力档各净减少 50,075,074 字节冻结负载，原组与离线重建均保留；冷生成仍未达标。详见本文末尾实际计量及[性能汇总](../artifacts/followup_20261127/performance/completion-performance-r5.md)。

## 已核实的重复与调用链

[已保存的诊断](../artifacts/followup_20261127/performance/workflow-ordinary-storage-diagnostic.json) 中，同一批 W4、W2、W5 的 `supplements.ordinary_training` 都有 10,000 条记录，规范 JSON 各为 **25,467,813 UTF-8 字节**，SHA256 均为 `49608a5931c3cc08594526590ab9564e29159a56394f7a85454a615e81341d12`。三份合计 76,403,439 字节；额外两份相同展开内容为 50,935,626 字节。这是普通训练字段的计量，不是整个数据库或审计包可直接兑现的净节省。

目前的完整链路如下：

1. `period_report._assemble` 调用 `reports.review_analysis`，产生当前 W4 和适用背景 W2/W5；历史完整周期另行运行。
2. `service.run_workflow` 调用 `selection.ordinary_strength_review`。`report_inputs.report_value` 已在本次请求内共享相同范围、可见性和记录 ID 的普通训练结果。
3. `workflow_input_hash` 基于完整科学内容形成工作流身份；`service.py` 最后的事务仍将完整 `result` 写到 `workflow_run.result_json`，因此请求内共享没有延伸到永久存储。
4. 报告问题走 `report_objects._save_training`：每条科学分组写为 `ordinary-training-series`，上层对象引用这些分组，另有按需读取目录。该表是既有永久对象表 `report_content_object`，不受普通缓存清理控制。
5. `storage.load_run` 目前只 `json.loads`；`service.run_workflow` 命中既有运行时也直接 `json.loads`。所有 UI、续跑、当前适用性复核和 `reports.markdown` 都依赖公开工作流结果保持展开结构。
6. `audit_bundle` 直接读取已存工作流 JSON，并已有递归收集 `$frozen_object` 的能力；`reconstruct_report` 只还原报告主体。当前报告正文相等检查不能单独证明导出的各工作流训练细节可完整还原。

失败浏览器截图停在“分析本期实际问题与行动”，位于工作流保存前的 `period_questions` 阶段。因此，本存储方案不能被直接当成浏览器 600 秒问题的原因或已完成修复；该慢路径由另一项诊断处理。

## 建议的最小实现

复用现有对象表、对象种类、内容寻址和 `$frozen_object`，不新增事实库、快照表或文件存储。

### 保存与读取

- 只对新写入的工作流结果使用内部格式标记，例如 `storage_format = "workflow-training-references-1"`。仅将存储副本中的 `supplements.ordinary_training` 替换为现有普通训练根对象引用；其他顶层字段、`knowledge.queries` 等路径保持原位。
- 将 `_save_training` 的分组/根对象保存部分提取为可复用函数。报告仍可创建阅读目录；工作流只需根引用，不应为没有读者的目录额外产生孤立对象。
- 对象和工作流行都在已有 `BEGIN IMMEDIATE` / commit / rollback 内保存。**不能调用内部自行 commit 的 `save_content` 来冻结工作流。** 如果工作流插入失败，新对象和分析快照一起回滚，原有共享对象保留。
- 在生成存储副本前，继续按完整的原始结果计算 `input_hash` / `run_id` / `analysis_run_id`。这是存储编码变化，不应为了强迫迁移而改变科学算法版本或旧运行身份。
- `load_run` 识别新格式并还原普通训练对象，返回与当前公开结果相同的字段和值，移除内部存储标记。旧内联行仍原样解析。既有运行命中分支必须通过同一解码入口，不能继续把引用清单直接返回给用户。
- 一次 `load_run` 可批量读取根对象引用的分组，再按原引用列表恢复顺序；避免把过去一次 JSON 读取变成 10,000 次独立 SELECT。必须保留重复引用的列表位置、每个未知条件组及其真实记录身份。
- 跨调用返回独立可修改结构，不用全局可变缓存。首版不引入跨事务的对象 ID 备忘录，避免 rollback 后继续复用未提交引用。若后续剖析证明确需减少重复编码，再单独增加限定于请求、提交状态可验证的准备缓存。

### 审计包和离线还原

如果审计导出重新调用展开后的 `load_run` 填入三份工作流，数据库虽然减少重复，审计包仍会膨胀。因此保留 `audit_bundle` 对工作流原始冻结 JSON 的读取及其现成的递归对象收集，让包中的对象按 ID 唯一出现。

- 当包中出现新工作流引用格式时，将审计格式明确升为 `healthzip-frozen-audit-3`；没有新工作流引用的旧包仍可保持 `healthzip-frozen-audit-2`。
- 在 `report_objects.py` 增加 `reconstruct_workflow(bundle, run_id)`，复用报告已有递归还原逻辑，支持旧内联和新引用两种工作流。它仅使用导出包内对象，移除内部存储标记，公开结果必须等于 `load_run`。
- `reconstruct_report` 对旧、新包仍还原相同报告；任何缺少的工作流/根对象/分组对象都明确失败，不回退到当前训练数据，也不悄悄丢组。
- 需要调整当前测试中“`bundle['workflow_runs'][id] == load_run(...)`”这一旧传输形状断言：对新格式验证 **实际文件反序列化后 `reconstruct_workflow(...) == load_run(...)`**，同时继续检查原始冻结工作流清单和每条源记录。这是显式版本化传输，不放宽科学内容相等要求。
- 单份工作流的现有 UI 下载继续通过公开展开结果生成自足 JSON，不改使用流程。它没有跨三个工作流的同一快照重复问题。

## 不变项与风险

- 不 UPDATE 旧 `workflow_run.result_json`、`joint_period_report.payload_json`、Markdown 或旧对象；同身份重复请求返回原有行，不把旧内联数据后台换成引用。
- 对象身份仍由现有工作区路径/文件身份、`local`、对象种类和完整冻结内容决定；窗口、可见性截止、修订、协议、算法等记录在原内容或运行依赖中。引用解析按所在库的 `user_id='local'` 查询；移库/合法备份后读取原有引用不能重新计算对象 ID。
- 只是共享相同字节，不能把 10,000 个未知条件任务合并成一个可比组。`None` 与 0、RIR、辅助重量、组位、同名不同条件和所有版本/日期保持。
- 不假设报告问题的 ordinary 对象与三个工作流对象完全相同；它们只有在完整内容身份相等时才复用。存储净节省须包含根、分组、目录、运行清单的全部唯一字节后重新计量。
- 输出对象写入不能影响 `input_version` 的私人输入时钟。当前知识撤销和数据修订仍由原 `check_current_use` 检查，不能因历史内容仍可读就把旧建议重新视为当前有效。
- 把 10,000 组对象的序列化移进工作流写事务可能增加锁时长；首版需记录保存阶段用时。纯编码可后续移到锁外准备，但并发输入核对和对象实际插入必须保留事务边界。

## 建议的文件所有权

可把以下内容独立分配给“工作流冻结存储”实现者；在明确分配前不改产品：

| 文件 | 允许修改范围 |
| --- | --- |
| `src/healthzip/workflows/report_objects.py` | 普通训练存取原语、工作流存储格式及副本；批量还原；审计格式和离线工作流还原 |
| `src/healthzip/workflows/storage.py` | 仅 `load_run` 调用统一解码入口 |
| `src/healthzip/workflows/service.py` | 只修改最后保存事务和既有运行返回分支；计算、证据、输入身份逻辑保持 |
| `tests/integration/test_workflow_frozen_training.py`（新增） | 新存储、回滚、并发、旧字节、离线工作流还原的独立场景 |
| `tests/integration/test_analysis_workflow_runs.py` | 增补带普通训练对象的事务/并发场景 |
| `tests/integration/test_current_training_acceptance.py` | 更新两处导出工作流相等断言为版本化离线还原；继续核科学内容 |
| `tests/integration/test_analysis_w1_flow.py` | 测试辅助读取通过公开 `load_run` 获取已还原结果，继续核旧运行相等 |

`reports.py`、`period_report.py`、UI、`report_inputs.py`、科学分析与知识检索预计无需修改；保持主代理慢路径诊断可并行。最终性能脚本与基线由主代理统一运行；其中应新增逐工作流实际文件离线还原核对，不只是 `reconstruct_report` 相等。

## 必要回归与计量

1. 用独立小夹具分别生成 W4/W2/W5：运行/分析身份不变、公开结果逐字段相等，持久化只保留共享引用；同名不同内容不误去重，记录更正产生新对象但旧对象不变。
2. 覆盖相同已知条件多次记录、未知条件独立组、同场重复、RIR=None/0、不同负荷口径和真实日期顺序；恢复后的分组、记录 ID、值及限制全部相等。
3. 准备旧内联运行与旧报告，记录原始 TEXT 字节；读、续跑、当前审核、缓存清理、源记录更正/撤销和新报告创建后，旧字节不变。
4. 同时验证新运行首返、重复命中、`load_run`、`resume_workflow`、`check_current_use`、工作流页及单份下载的公开契约；不能只测试冷写入一次。
5. 强制工作流 INSERT 失败时，新分析和新对象均回滚；原有共享对象完整。并发相同请求得到一个运行和同一组对象，不产生悬空引用。待保存用户编辑仍被原边界保护。
6. 从实际导出的文件重新载入，逐报告和逐工作流还原；断开原库和外部知识后仍相等。新/旧格式混用、缺对象报错、跨工作区拒绝、合法数据库备份重开都覆盖。
7. 运行既有 `test_analysis_workflow_runs.py`、`test_current_training_reports.py`、`test_current_training_acceptance.py`、`test_report_repair_contract.py`、`test_repair_report_review.py`、`test_followup_workflow_identity.py` 和工作流/普通训练页面相关回归；Ruff。范围外全量回归和浏览器实测由主代理在最终代码稳定后安排。
8. 在原样 10,000 组压力夹具上重新统计：每个工作流行字节、普通训练根/分组/目录对象数与唯一 UTF-8 字节、审计文件字节、保存/还原耗时、峰值内存；全部原组和独立未知任务继续存在。三份旧 25,467,813 字节只能作为保留基线，不能预先填入优化后的结果。

## 本次已实施与验证

- `report_objects.save_workflow` 仅在既有工作流事务内创建保存副本，原始公开结果不被修改。它复用 `_save_training(..., include_preview=False)`，没有另建存储系统，也不生成无人引用的阅读目录。
- `read_workflow` 先读取根对象，再以一次按 ID 的查询取回全部分组，按原顺序恢复；`load_run` 和相同运行命中分支使用同一解码逻辑。不同调用返回独立结构，合法数据库备份重开后仍可读取原引用，其他工作区缺对象时明确失败。
- 新工作流维持 `allow_nan=False` 的原边界；旧报告默认序列化和解码规则不变。对象哈希仍使用既有 `scope + NUL + encoded` 字节，`encoded` 只生成一次后同时用于哈希和落库；没有修改通用 `canonical_hash` 或科学版本。
- 新引用工作流使用审计格式 3，`reconstruct_workflow` 支持格式 2/3 和混合的新旧运行。真正写出的审计文件在原数据库移走后仍可还原报告与每个工作流；缺少分组对象时不会读取当前数据补齐。
- [修复前失败](../artifacts/followup_20261127/workflow-storage/before.txt) 是真实小夹具的共享存储断言失败，保留原结果。[首轮 7 项](../artifacts/followup_20261127/workflow-storage/targeted-r1.txt) 通过后，补充非有限数值边界；[核心回归 50 项](../artifacts/followup_20261127/workflow-storage/core-r2.txt) 全部通过，包含 10 个新专项以及既有工作流、冻结报告、审计和身份回归。[本范围 Ruff](../artifacts/followup_20261127/workflow-storage/ruff-r2.txt) 通过。各轮测试结果分开保留，不叠加当作最终全量回归。
- [消费方回归](../artifacts/followup_20261127/workflow-storage/consumers-r2.txt) 的 3 个既有测试函数实际展开为 4 个案例，全部通过：W1 正常选择/执行/复评，以及两处报告审计使用处。它们使用 AppTest 和合成仓库，不是实际浏览器验证。
- 上述小型场景只证明共享与兼容契约；后续已完成固定 r5 源码的三档后端实测及下列实际冻结库计量。浏览器与最终性能预算另见本轮性能汇总，不能以存储节省推断冷生成达标。

## r5 实际压力存储结论

从三档后端验收保留的合成 SQLite 副本以 `mode=ro` 和 `query_only` 读取，未改写任何工作流或对象。比较基准是**这些相同最终工作流**用原严格内联 JSON 编码的字节数，不是把旧 r3 三个工作流直接拿来相减；实际公共知识内容及运行数量已经不同。读到的全部对象、每行字节、对象种类和计量驱动身份分别保留在 [personal](../artifacts/followup_20261127/workflow-storage/pressure-personal-r5.json)、[100k](../artifacts/followup_20261127/workflow-storage/pressure-100k-r5.json)、[1m](../artifacts/followup_20261127/workflow-storage/pressure-1m-r5.json)。

| 合成档位 | 工作流数 | 实际引用格式 JSON（B） | 同结果原内联 JSON（B） | 工作流专用根及系列对象（B） | 净节省（B） |
|---|---:|---:|---:|---:|---:|
| 两年个人 | 3 | 1,220,939 | 1,340,159 | 88,836 | 30,384 |
| 10 万压力 | 5 | 44,822,168 | 121,226,068 | 26,328,826 | 50,075,074 |
| 100 万压力 | 5 | 45,420,829 | 121,824,729 | 26,328,826 | 50,075,074 |

净节省已经扣除引用格式需要的全部独占对象；报告仍需要的对象和其他现有对象保留在两侧。此批实际没有报告与工作流共用的相同训练对象，因此把全部工作流引用对象都计入成本的保守算法也得到同样节省。压力档各有两个工作流普通训练根和 **10,000 个独立系列对象**，没有把未知条件合并成可比较任务；全部 10,000 个原组和未知任务均通过实际导出完整性核对。这里的 B 是 UTF-8 负载字节，不等同 SQLite 文件页、WAL、内存或计算时间。

完整审计导出分别为 4,580,896 / 264,094,247 / 294,849,182 B，耗时 0.211 / 13.523 / 13.781 秒；实际写出的文件重新读入后，报告以及全部 3 / 5 / 5 个工作流分别还原并与冻结公开结果精确相等。导出文件只保留在合成临时工作区，公开工件只保存计量元数据；没有把含受许可约束原文的完整审计包复制进仓库。三档原始数据八表哈希、公共知识权威身份和固定产品源码均不变。

压力冷生成仍分别为 119.114 / 172.928 秒，未达到 15 秒；生成峰值树 RSS 分别为 2,111,604 / 2,488,252 KiB，审计峰值为 2,098,596 / 2,497,700 KiB。引用存储确实减少了相同科学内容的永久重复，但没有消除所有科学计算和大对象还原成本。原慢路径、失败和早轮结果继续保留；实际页面时钟、30 次热测、宽度及阅读验证见[本轮最终性能汇总](../artifacts/followup_20261127/performance/completion-performance-r5.md)。
