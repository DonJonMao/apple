# R07 历史复盘菜单：交互同步与真实绘制验收

本项基于已提交的 `6f7d9c3` 产品源码继续验证，未改产品样式、报告内容或历史数据。短程 A/B 使用该提交原配置；正式历史验证追加本轮 `runner.postScriptGC=false` 配置，唯一配置差异及前后 hash 见[受验快照](../artifacts/followup_20261127/history-interaction-r1/source-snapshot.json)。修复对象是正式浏览器验收脚本中“展开尚未完成即滚动选择控件”的时序。原失败证据和旧的重试耗时完整保留，不改写为通过。

## 已定位的关闭原因

[短程 A/B 原始回执](../artifacts/followup_20261127/history-interaction-r1/browser-ab/receipt.json)在同一个应用、三个新浏览器上下文中比较了原始箭头操作、等待真实动画完成的箭头操作及四次交替历史选择。使用原个人规模合成库中已保存的 31 份报告；没有重新生成报告。原库、复制库报告、产品文件及公共资料审核身份前后均未变化。

原操作在 `<details>` 正以 `height:50px; overflow:hidden` 展开时调用 `scrollIntoView`，不仅滚动主页面，也将该祖先容器的 `scrollTop` 设为 89。菜单在 2700.6 ms 打开；之后展开动画增加容器高度，滚动位置被依次压回 52、26、20，菜单在 2807.7 ms 关闭。这些事件处于同一服务端渲染身份。

安装的 Streamlit 1.67 的展开器使用 500 ms Web Animation 修改高度，完成后清除临时 `height/overflow`；React Aria 菜单捕获包含触发器的祖先滚动，并关闭弹层。[安装代码及文件 hash](../artifacts/followup_20261127/history-interaction-r1/installed-streamlit-code.json)与浏览器事件构成对应证据。超过 25 个选项会启用虚拟列表，但本次证据没有证明它是关闭原因；不能将 3 份和 31 份报告的差异直接归因于虚拟化。

等待祖先实际 Web Animation 完成和几何/滚动连续三帧稳定，再滚动并再次等待稳定后，`details.scrollTop` 保持 0，菜单正常绘制；四次交替选择均一次成功且打开完整目标 ID。[1440 宽实际菜单图](../artifacts/followup_20261127/history-interaction-r1/browser-ab/synchronized-arrow.png)已目视核对。基线失败截图和 HTML 留在同目录。

## 正式脚本改动

`tools/followup_report_browser_benchmark.py::history_input` 复用 `tools/followup_history_interaction.py` 的实际状态同步，取消最多三次选择重试。一次失败即保留错误与事件，不能用第二次成功掩盖第一次失败。五秒是失稳失败上限，不是固定等待；选择准备与点击“打开这份复盘”后的读取延迟继续分别计时。

菜单核对绑定实际输入节点及其 `aria-controls`，检查展开状态、选项祖先的显示/透明度、视口位置和实际命中，不再只凭旧隐藏节点或 `aria-expanded` 声称截图可见。正式截图完成后再次核对可绘制/命中状态。

新增 `--history-only`，复制现有冻结报告后执行冷读取与热返回，不为本次交互验证增加报告版本。运行前后检查原库及复制库报告内容不变。清单新增同步工具的源码 hash。产品代码使用独立归档，避免其他并行修复变化混入本项测量。

## 正式验收状态

[正式结果汇总](../artifacts/followup_20261127/history-interaction-r1/formal-receipt.json)与[原始 31 次回执](../artifacts/followup_20261127/history-interaction-r1/formal-history/reopen.json)已完成。合成库含 11,680 条健康记录、1,672 个训练组和原有 31 份报告；31 次打开交替选择两个不同的完整报告 ID，全部一次成功。31 次均核对完整目标 ID、真实冻结图表数组及新 DOM。下载在最后一次打开后执行 1 次，字节 hash 与该份原冻结 Markdown 相等；没有逐份下载 31 次。没有声称逐一打开全部 31 个不同版本。

| 单独计时的阶段 | 冷样本 | 热 30 次 P50 | 热 30 次 P95 |
|---|---:|---:|---:|
| 选择准备（实际动画等待、滚动、输入、选择） | 514.8 ms | 924.9 ms | 960.2 ms |
| 点击打开至首批事实 | 293.2 ms | 369.9 ms | 472.8 ms |
| 点击打开至真实趋势 | 1265.0 ms | 373.4 ms | 476.4 ms |
| 点击打开至可交互 | 1464.5 ms | 379.3 ms | 481.7 ms |

分位数均使用 nearest-rank。打开阶段通过原冷 3 秒／热 P95 1 秒预算；准备阶段独立报告，不能用打开耗时代替完整操作，也不能把两个 P95 相加称为端到端 P95。旧／新正式运行配置不同，打开阶段的差异不单独归因于菜单同步修复。

320／375／390／430／768／1440 六宽度均无主页面横向溢出，第一条实际发现完整在首屏。390 和 1440 的下一步、当前来源限制及菜单截图均保留当前冻结报告身份。[390 菜单](../artifacts/followup_20261127/history-interaction-r1/formal-history/reopen-390-history-versions.png)、[1440 菜单](../artifacts/followup_20261127/history-interaction-r1/formal-history/reopen-1440-history-versions.png)已按原图目视核对，实际菜单选项及不同版本 ID 可见；本轮共 14 张截图通过[联系表](../artifacts/followup_20261127/history-interaction-r1/formal-history-contact.png)核对布局。截图不替代前述真实操作和精确值断言。

进程正常退出 0，总墙钟 71.65 秒，GNU time 最大 RSS 188,768 KiB，CPU user/system 35.81/5.12 秒。该值是运行命令的资源回执，不冒充单独应用阶段的精细内存采样。本次仅此应用／浏览器验收，其他代理做轻量代码／文档工作；共享宿主机有 192 逻辑 CPU，外部负载不受控，不能作为普通设备实测。完整命令及资源见 [GNU time](../artifacts/followup_20261127/history-interaction-r1/formal-history-time.txt)。

原库报告、复制库报告、公共资料审核身份、受验产品和驱动 hash 均未变化，见 [summary.json](../artifacts/followup_20261127/history-interaction-r1/formal-history/summary.json)。Ruff、Python 编译、嵌入 JavaScript 的 Node 语法检查通过；现有同时间戳版本精确打开和短 ID 冲突区分专项 `pytest` 为 2 通过、4 未选中（4.01 秒），见 [驱动检查](../artifacts/followup_20261127/history-interaction-r1/driver-checks.json)及 [JUnit](../artifacts/followup_20261127/history-interaction-r1/history-tests.xml)。全仓最终回归由总交付另行列示。

旧正式历史回执 `performance/final-browser-history-personal-r1/reopen.json` 保留原样：30 次热选择均需两次准备，准备 P95 2646.5 ms，点击打开后 P95 607.2 ms。两类耗时不能相互替代。此前 `history-visual-supplement-r1` 的失败及没有实际绘制菜单的旧桌面图继续作为失败记录，不重新标为通过。

本项不证明压力库报告冷生成达标，也不覆盖实体 iPhone、Safari 或软键盘；相关失败和未验证边界继续单列。
