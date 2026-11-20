# 改版验证记录

本轮验证全部使用合成数据或隔离临时工作区，不读取生产 `.local`，不提交数据库。Python/SQLite与Streamlit AppTest、Node事件测试、真实Chromium、截图几何检查分别记录；没有真机iPhone/Safari或移动网络验收。

## 完整回归与失败修复

首轮隔离全量结果为2090通过、6失败。失败包括旧同步建议测试没有等待异步完成、报告未使用当前适用声明，以及空值指标的显式依据查询被跳过。保留原行为断言，分别修正等待合同、当前声明绑定和显式查询空值定义的支持；没有把缺失科学数值补成零。原始逐例结果摘要见[首轮](../../artifacts/product_redesign/validation/initial.json)。

第二轮四个隔离分片共2107通过、4失败。四项失败均来自生成报告时误把显式历史截止时间替换为当前时点；已修正为自动范围取当前、显式历史范围保留截止时间和回顾身份。包括这四项的报告专项22项通过，新增当前窗口Markdown测试还核对当前事实/声明、撤回后权限、历史截止和既有冻结运行不被改写。

第二轮逐例记录：[分片0](../../artifacts/product_redesign/validation/integration-round-2-shard-0.json)、[分片1](../../artifacts/product_redesign/validation/integration-round-2-shard-1.json)、[分片2](../../artifacts/product_redesign/validation/integration-round-2-shard-2.json)、[分片3](../../artifacts/product_redesign/validation/integration-round-2-shard-3.json)，[当时源码清单](../../artifacts/product_redesign/validation/integration-round-2-source-manifest.json)。测试输出中的临时路径和stdout/stderr不复制进公开工件；逐例名称、结果与耗时保留。

最终完整回归：**2123通过、0失败、0跳过、1项既有JUnit格式警告**。144个测试文件，四个分片各约220–227秒。最终回归使用同一份冻结源码，将所有自动发现的测试文件按前轮耗时分成四个隔离副本，不共享临时数据库。最终结果与逐例记录见[最终验收摘要](../../artifacts/product_redesign/validation/final-results.json)，[源码SHA256清单](../../artifacts/product_redesign/validation/final-source-manifest.json)。分片按文件分配，不跳过慢测试、不排除先前失败测试。

## 其余检查

- `ruff check src app.py tests`及本轮新增tools通过，`git diff --check`通过。仓库根目录额外扫描曾报告80处既有历史PDF/评测工具问题；本轮没有将根目录全量Ruff声称为通过，也没有批量修改无关历史工具。
- `node --test tests/training/strength_picker_events_check.cjs` 3项通过，`node --check .../workbench.js`通过。
- `uv lock --check --offline`通过；锁定52个依赖包。
- 最终wheel构建通过，200个包内文件与当前源码逐字节一致，包含主题、训练JS/CSS/HTML和新增Python模块。校验见[安装包回执](../../artifacts/product_redesign/validation/package-check.json)。wheel只在临时目录生成，不提交二进制发行包。
- 授权专项46项通过，包含真实KnowledgeWorkbench延迟检索、设置撤回回调及本地HTTP正负对照。未撤回的合成请求确实发送；排队/检索/请求构造期间撤回的旧任务不得发送，重新授权也不复活旧任务。已发送请求不承诺可以撤回。
- 两项工作区/浏览会话隔离AppTest通过：同样的指标事实不能复用另一个数据库或独立浏览会话的请求状态。

完整结果中的一个既有pytest警告来自`record_property`与JUnit xunit2格式不兼容，不影响行为断言；未通过关闭警告掩盖失败。

## 真实界面证据

|层级|覆盖和证据|边界|
|---|---|---|
|真实Chromium导航与布局|[9页、6宽度、手机菜单和范围切换](../../artifacts/product_redesign/after/browser-results.json)；[最终1440/390截图复核](../../artifacts/product_redesign/final-visual/browser-results.json)|同机headless Chromium，不等同真机|
|空/旧/单点|[空数据](../../artifacts/product_redesign/states-empty/browser-results.json)、[旧数据](../../artifacts/product_redesign/states-old/browser-results.json)、[单点](../../artifacts/product_redesign/states-single/browser-results.json)，每类9页×桌面/手机|具体值/窗口含后端和AppTest断言；几何检查不替代数值检查|
|训练交互|[17主流程、8边界、5搜索、2滚动](../../artifacts/product_redesign/training/training-delivery-summary.json)；真实双页签冲突、丢回执同ID重试、刷新、30动作长训练、取消返回位置及连续视频|数字键盘缩小视区采用Chromium模拟，未验证实际iOS软键盘|
|解释故障|[最终4场景](../../artifacts/product_redesign/explanations-consent-final/explanation-browser-results.json)：8秒慢worker、失败重试、未授权、未配置|故障在独立worker注入；不伪造成功数据，不使用个人数据或外部模型|
|对比度/触控/焦点|[最终视觉几何结果](../../artifacts/product_redesign/visual-accessibility.json)：caption8.641:1、数字输入16px、主要点击区域至少44px、可见键盘焦点|检查1440/390px，不冒充完整无障碍认证|
|前置卧推与后续夹胸|真实服务、审核知识库和Streamlit AppTest核对顺序、负荷、RIR、已知睡眠/休息及权限撤回|特定两场选择流程未另录Chromium；没有做因果或真人科学有效性验证|

10万/百万后端和浏览器的原始逐次样本、计时起点、首次启动成本、运行中冷范围的小样本限制及保留的慢轮次见[性能报告](performance.md)。
