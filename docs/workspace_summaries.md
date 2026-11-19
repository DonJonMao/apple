# 当前数据分析与统一导航

各工作区的标题和主区导航始终保持一致，力量页只在训练组件内使用深色卡片。无需先返回健康总览，就能直接切换睡眠、心率、力量等工作区。

“当前数据分析”默认展示本周结论，也可切换本月。先显示中文结论，再显示日期、实际计算截止和有记录日期；指标、来源与限制收在“分析依据与范围”中。窗口独立于下方明细的可选分析天数：本周是所选时区周一零点至截止时刻，本月是月初零点至截止时刻，均为尚未结束的部分周期。

- 心率与HRV按来源、设备和记录条件分别描述已有静息心率、SDNN的记录，不合成恢复分数。
- 睡眠按来源描述正有效观察时长、记录日期及其范围；零或未知时长不进入平均分母，不把缺失日当作零小时或推断未佩戴。
- 运动描述已有场次、记录时长和设备能量，缺失保持未知，不把设备能量称为全天代谢。摘要按截止时点可见的Workout自身字段读取；明细页原有整场附表回退语义保留，并不混入摘要的历史可见性。
- 体重和有氧适能保留来源及估计身份。当前周期没有称重就说明缺少记录，不把过去的称重包装成当前体重，也不把差值解释为脂肪或肌肉变化。
- 力量只描述实际完成的组及其训练、动作，不把草稿、跳过或删除记录计为完成，不累加不同负荷语义为一个总容量。
- 周期只描述已记录的来源观察，不推断周期阶段、身体状态或处方。总览、数据质量、分析和报告页面提供综合记录摘要，原分析与报告功能保持。

摘要完全在本地计算，复用既有指标与可见修订选择，不外发私人数据。缓存使用数据库身份、数据修订、工作区、时区和分钟时间键；同一键复用原结果与原截止，新增、修改、删除或撤销后重新计算。缓存不新增数据库写入；分析暂不可用时仍可查看明细和记录训练，不让可选摘要阻塞训练保存。

力量首页每天的训练卡片新增直接删除入口，包括已完成的零动作、零完成组训练。删除按钮与查看详情分开，先确认目标会话与修订，取消不写入，确认和撤销使用原事件机制，不删除用户记录作为软件测试。

## 本轮验证与界面

公开验证均使用隔离合成数据库、真实导入和原训练服务。新增17项后端回归验证日历/时区边界、有效分母、来源隔离、删除撤销、并发修订、热缓存不重算及无派生写入；4项完整应用回归验证真实周/月结论、统一导航和摘要失败时仍可记录训练。全部134份pytest文件分片执行，最终2061项通过，0失败、错误或跳过。片1首次输出515项通过和完整XML后，命令会话以143退出；随后拆成两个独立子片重跑并核对真实退出码，最终回执采用完成的子片结果，未把退出143改写为成功。

真实Chromium完成22项力量流程检查与5项摘要检查，均无页面错误和外网请求，产品源码在整轮运行前后保持一致。截图与逐项回执：

- [睡眠本周结论](../artifacts/workspace_updates/sleep-week-summary-mobile.png)、[本月结论](../artifacts/workspace_updates/sleep-month-summary-mobile.png)。
- [力量保留统一顶部导航](../artifacts/workspace_updates/strength-unified-navigation-desktop.png)。
- [首页空训练删除确认](../artifacts/workspace_updates/home-empty-session-delete-mobile.png)。
- [力量浏览器回执](../artifacts/workspace_updates/strength-browser-results.json)、[摘要浏览器回执](../artifacts/workspace_updates/summary-browser-results.json)、[最终验证回执](../artifacts/workspace_updates/verification.json)及[完整测试文件清单](../artifacts/workspace_updates/pytest-shards.json)。

实际命令如下，pytest各片的精确文件参数及退出码记录在最终回执中；每片从独立临时公开代码目录运行，避免读取生产知识目录。

```sh
.venv/bin/python -m pytest -q --tb=short --junitxml=<该片XML路径> <该片完整测试文件列表>
.venv/bin/ruff check src app.py tests
node --check src/healthzip/ui/strength_component/workbench.js
.venv/bin/python -m pip wheel . --no-deps --no-build-isolation --wheel-dir /tmp/healthzip-workspace-wheel
```

浏览器验证使用本环境的临时Chromium与动态库路径；它们不属于生产依赖。可复跑脚本为：

```sh
PLAYWRIGHT_BROWSERS_PATH=/tmp/healthzip-browser-bin \
LD_LIBRARY_PATH=/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu \
.venv/bin/python tests/training/strength_workbench_browser_check.py --output /tmp/healthzip-workspace-browser
PLAYWRIGHT_BROWSERS_PATH=/tmp/healthzip-browser-bin \
LD_LIBRARY_PATH=/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu \
.venv/bin/python tests/training/workspace_summary_browser_check.py --output artifacts/workspace_updates
```

构建后的wheel包含两个新增摘要模块，组件资源与最终源码逐字节一致。已重启30上的UI服务，部署后逐页切换总览、心率、睡眠、运动、体重、力量和周期，并实际切换睡眠周/月摘要；训练卡片删除按钮可达，仅检查入口，没有执行生产删除或训练写入。UI与REST保持运行，访问配置不变。

仍未验证真实iPhone数字键盘、Safari或软键盘安全区。现有Altair/jsonschema弃用与JUnit属性兼容警告未静音，不影响通过的断言。
