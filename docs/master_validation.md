# 本轮验证记录

所有公开证据使用合成健康/训练数据。Python/SQLite、Streamlit AppTest、Node事件、真实Chromium、截图几何和实体手机分别记录。没有读取个人数据库来生成公开截图，也没有用历史测试数量替代本轮运行。

## 完整回归与修复记录

第一轮直接全量运行在发现12项失败后主动中断，结果为288通过、12失败、351.41秒；这是不完整运行。失败涉及空库的只读训练初始化，以及报告按需任务合同没有同步到旧周期页消费者。两类产品问题均修复，没有删除科学/行为断言。回执见 [preliminary-interrupted.json](../artifacts/master_redesign/validation/preliminary-interrupted.json)。

随后自动发现159个测试文件、2292个测试，所有文件各分配一次到4个隔离目录/进程，结果为 **2292通过、0失败、0错误、0跳过**；一个已有警告来自`record_property`与JUnit xunit2报告格式的兼容提示。各片约185–212秒。来源是[完整轮次1](../artifacts/master_redesign/validation/complete-round-1/results.json)，不是把多轮定向测试相加。

该轮运行期间仍有界面及报告优化修改，源清单明确列出了变化文件；后续还新增W4/W8/E正常业务连接，所以此结果不称为最终工作区全量通过。随后[完整轮次2](../artifacts/master_redesign/validation/complete-round-2/results.json)发现161文件、2302项，全部通过，0失败/错误/跳过。期间只修改了真实浏览器验收工具的等待/选择方式，因此原回执保留`needs_review`。此后真实未预置月份的AppTest发现总览/复盘返回时月份会重置，已补导航状态保留和独立行为断言；该轮结果作为修复前历史保留。

最终修复后的[冻结版本全量回归](../artifacts/master_redesign/validation/final/results.json)发现并执行 **2302项、161个文件，2302通过，0失败、0错误、0跳过**。4个隔离目录/进程中每个发现的文件仅分配一次，各片约186–210秒。运行前后源码SHA256完全一致，`source_changes_during_run=[]`，最终状态`passed`；不是把定向测试数量相加。源清单、发现列表、分片分配、每例结果和JUnit均随回执保存。[交付审计](../artifacts/master_redesign/validation/delivery-audit.json)再次确认当前源码一致、文档链接有效、13项主页面和6项专项浏览器检查通过，并单列未达标/未验证项。

W4/W8/E/W7专项浏览器的最终回执为6项通过、22张1440/390截图、无浏览器错误。早期控件尚未完成重绘、长页面滚动关闭菜单等失败保留在`pages/workflow-completion`；工具改为等待具体反馈状态，并先定位真实可搜索控件再键盘选择，没有跳过数值断言。最终核对实际Arrow表格和原训练input值，见`final-evidence-review.json`。

旧导航合同需要更新的测试，改为先进入五入口下的实际子页面；原有RIR零值、授权撤销、修订冲突、统计数值和冻结内容断言仍保留。表单测试按真实浏览器行为在同一次提交中传入选择，避免用额外AppTest重跑模拟一个并不存在的表单自动提交。

## 已执行的分层验证

| 层级 | 当前证据 | 说明 |
|---|---|---|
| 科学/导入/时态/缓存 | science/finish-tests.xml、master_science.md | 合成方法验证；与全量集合有重叠，不累加 |
| 来源与RAG | knowledge/public-question-final-tests.xml、independent-rag-final.json、public-method-model-final.json | 原文检索、事实篡改、公开模型分别计；无私人生成质量结论 |
| 训练真实浏览器 | training/training-browser-results.json、training-edge-results.json、scale.json | 真实服务回执、草稿、冲突、历史修改及30次规模返回 |
| 页面与正式模型 | pages/acceptance/browser.json、pages/workflow-completion/browser.json | 正式趋势/关联、稀疏回退、行动保存与冻结、报告生成及切页返回 |
| 空/旧/单点 | pages/states-empty、states-old、states-single | 每类6页面×1440/390，数值/空状态与主区域溢出检查 |
| 前端事件 | `node --test tests/training/strength_picker_events_check.cjs` | 3项通过：选中返回、取消保留、失败重试；JS语法检查通过 |
| 静态检查 | `.venv/bin/ruff check app.py src tests tools`、`git diff --check` | 全部通过，完整命令/退出码及依赖锁SHA256见validation/static-checks.json |
| 依赖锁 | `.venv/bin/uv lock --check --offline` | 新增可选报告解码依赖后53项锁检查通过，见static-checks.json |

## 复跑命令

```bash
.venv/bin/python tools/master_regression.py
.venv/bin/ruff check app.py src tests tools
git diff --check
node --test tests/training/strength_picker_events_check.cjs
node --check src/healthzip/ui/strength_component/workbench.js
.venv/bin/uv lock --check --offline
```

`master_regression.py`复制已跟踪公开资源及当前src/tests/tools，不复制`.local`、`.env`、`.git`或私人数据库。分片权重只借用历史耗时以平衡任务，实际通过数来自本次JUnit。每片使用独立目录和临时数据库，完成后比较工作区源码哈希；源码变化会标为`needs_review`。

真实浏览器环境：

```bash
export PLAYWRIGHT_BROWSERS_PATH=/tmp/healthzip-browser-bin
export LD_LIBRARY_PATH=/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu
.venv/bin/python tools/master_ui_acceptance.py --knowledge /tmp/hz-master-report-baseline/knowledge
.venv/bin/python tools/master_pages_browser.py --output artifacts/master_redesign/pages/after-final
```

性能基准的规模、冷/热定义、逐次时间及未达预算，统一见[master_performance.md](master_performance.md)，不把Python测试耗时或单条SQL耗时当页面性能。

尚未验证：实体iPhone/Safari、真实软键盘/输入法与移动网络、真实个人库回滚演练、真人纵向/干预效度、专家独立主张审核及私人回答模型效果。资料的可得性/许可/适用性缺口在[知识交付](master_knowledge.md)逐项说明。
