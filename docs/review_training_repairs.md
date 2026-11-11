# 训练记录审查修复：R02、R04、R07、R08 接线、R09

核查基线为 `0a943b49638247e16197cf7fa768cde33f5d0901`。本文件只报告训练子任务；科学模块、建议生成和理论审核的完整验收由对应修复记录汇总。所有复现使用临时 SQLite 和合成记录，没有读取个人数据库。

## 修复前复现

先新增下列测试，再运行生产修复。命令实际返回 **7 failed**，证据保存在 `artifacts/verification/review-training-baseline.xml`。

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/training/test_review_training_repairs.py \
  tests/integration/test_review_training_ui.py \
  --junitxml=artifacts/verification/review-training-baseline.xml
```

|编号|触发与实际错误|原因|
|---|---|---|
|R04|真实 AppTest 同时显示当前/历史两组控件。当前把 10 次改成 9 次，重渲染后历史保存恢复为 10 次；历史先编辑备注的变体也静默覆盖。|持久控件值来自旧行，保存却使用新读取的数据库 revision，并提交全部字段。|
|R07|临时训练逐组目标改为 6–8 次、RIR 2 后另存模板缺少 sets；模板训练从 10–12 改为 6–8 后另存仍是上限 12。|另存与建议读取旧实例计划，没有逐组有效目标接口。|
|R09|后组初始休息 120 秒；前组结束后移 60 秒后仍为 120。显式清空前组结束时间被改成当前系统时间。|仅重算当前组；空端点被当成新完成时的默认时间，后组依赖未更新。|
|R02|从普通模板页面填写结构化协议时找不到协议 ID/版本/规则控件。|页面只提供自由文本，与科学模块的结构化可比性合同不一致。|

## 已实现的修复

**R04：持久表单版本与脏字段。** `ui/training_page.py` 为每个视图及组绑定加载时的 revision、字段快照和控件映射。没有待保存改动的表单可以同步新版本；已有脏字段时保留原版本，提交真实字段补丁，由领域服务保存冲突。清洁表单点击保存为无操作，不增加 revision。自动保存成功只推进该表单已确认的版本，同一提交的多个回调可依次保存；不会从数据库借用其他视图的新版本。保存后的系统时间等派生显示在下一次渲染同步，未提交的其他字段继续保留。

验收包含双视图、重复重渲染、无意字段保存、脏备注并发以及同次提交多个实际字段。冲突提议只含用户改过的备注，不含陈旧次数。

**R07：唯一的当前目标接口。** `TrainingService.current_targets(session_exercise_id)` 返回：

```text
session_exercise_id
revision                 # 目标 UUID/内容的 SHA256，与实际完成修订分开
sets[]                   # set_uuid、当前组 revision、completion_state、target
targets                  # 明确填写的当前目标集合；没有时为空对象
original_targets         # 实例开始时的原计划，保持不变
```

`save_session_as_template` 和建议页面使用该接口。正常跳过组仍保留其明确目标；已删除组和已替换实例不成为新模板的有效项目。修改实际次数或跳过执行不会改变目标内容版本。原会话 `plan_snapshot` 不改写，依从性分析仍可读取原计划。临时训练、模板训练、跳过及目标版本变化都有专属回归。

**R02：明确的协议结构与版本。** 普通条件表单提供 `protocol_id`、`version`、`reference_policy_id`、`effort_protocol`、`tempo`、`rest_protocol` 六项文字字段，保存在 `condition.reference_protocol`。自由文本单独保存为 `reference_protocol_note`。旧文本只作为备注，不生成结构化默认值；空字段保持 null，完整性与可比性仍由科学模块检查。版本及完整协议定义随条件冻结；修改已执行条件仍须使用替换流程。

页面控件为 `<condition_prefix>_protocol_id/version/policy/effort/tempo/rest`，备注保留 `<condition_prefix>_protocol`。纯 AppTest 验收从空库创建模板和器械，填写协议，连续三场预声明参考组，按同一负荷记录 6、7、8 次，再由默认 `analyze()` 获取同一任务的 3 条参考和描述性斜率。没有登记置信预算时不制造趋势区间；该验收不声称个人训练效应。

**R08：结束后的反馈入口。** 历史已完成或中断训练会调用 `render_candidates(..., allow_create=False, key_prefix='history_')`。它展示冻结候选并保留反馈入口；当前和历史控件键分开。建议模块及结束后反馈端到端测试由根任务维护，训练页只负责上述接线。

**R09：依赖端点重新派生。** 增、改、删、撤销组记录后，领域服务检查同一会话的有效相邻执行端点。前组结束或后组开始改变时重新计算；缺开始、缺前组结束、重叠或无法定位执行顺序时返回未知。显式清空结束时间保留 null，不自动替换为系统时间。受影响后组写入独立 `derive_rest` 审计事件和新 revision，截止时间重放仍返回更正前的休息值。

新增 `rest_derivation_json` 保存算法版本、前组 UUID、两个端点和未知原因；`rest_recorded_s/rest_recorded_method` 单独保存用户主动记录。派生值不覆盖主动值，也不使用休息计时目标。页面可分别查看和填写；CSV/JSON 交换保留主动记录字段。测试覆盖 120→60 秒、端点清空、删除/撤销邻组、旧截止快照和 CSV 往返。

休息重派生不会替用户解决已有字段冲突。历史重放仅在对应的显式决议事件已进入截止时间时清除该冲突；新增回归同时核对决议前后及旧截止快照。

## 验收文件与命令

生产文件：`src/healthzip/training/service.py`、`semantics.py`、`schema.py`、`src/healthzip/ui/training_page.py`。

专属回归：`tests/training/test_review_training_repairs.py`、`tests/integration/test_review_training_ui.py`。修复后证据为 `artifacts/verification/review-training-fixed.xml`；训练领域与既有训练页面的合并回归为 `artifacts/verification/review-training-current.xml`。根任务执行最终全量 pytest/Ruff。

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/training/test_review_training_repairs.py tests/integration/test_review_training_ui.py \
  --junitxml=artifacts/verification/review-training-fixed.xml
PYTHONPATH=src .venv/bin/python -m pytest -q tests/training \
  tests/integration/test_review_training_ui.py tests/integration/test_v13_training_ui.py \
  --junitxml=artifacts/verification/review-training-current.xml
ruff check src/healthzip/training src/healthzip/ui/training_page.py \
  tests/training/test_review_training_repairs.py tests/integration/test_review_training_ui.py
```

实现和软件回归与语料覆盖、独立专业审阅、真人科学验证分别报告。本次修复没有扩大理论权限，没有以合成审核代替真实专业审核，也没有放宽缺协议、缺校准或缺依据的门槛。
