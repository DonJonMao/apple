# 力量训练改版与验证

2026-11-20。本轮使用合成记录；既有 SQLite、事件幂等、修订、条件快照与知识权限继续作为事实来源。旧多选工作台截图属于历史版本。

## 用户操作

力量首页优先开始/继续训练。点击开始即生成日期时间标题，进入空训练；点击添加动作打开独立目录，点一个动作，收到保存回执后返回同一训练并定位第一组。取消不新增。已存在动作提供回到原卡片与明确再次添加两个入口。

动作卡默认展开，可逐卡收起；数字先写本机状态，完成本组才确认完成事实。手机字段标签可见，输入至少16px、主要操作至少44px。按实际类型显示次数、秒数或米数，自重允许外部负荷留空，助力可为0，单边与每只哑铃口径不换算。复制仅创建允许字段的草稿，不复制实际RIR、完成、时间、疼痛或质量。

可上移/下移、加组、删除后撤销、查看历史和显式更正。结束先显示已完成动作/组、未完成组和实际经过时间。可先保存未完成草稿，或只计完成部分并保留本机未同步内容；空训练和未完成组不增加完成统计。可选建议在独立工作线程运行，用户可返回继续保存。

## 实现与边界

| 范围 | 实现 |
| --- | --- |
| 单次动作选择、稳定输入、局部回执 | [workbench.js](../src/healthzip/ui/strength_component/workbench.js)：同视图按稳定身份更新DOM，保留焦点和发出请求后的新值；同一命令ID重试 |
| 自然高度与局部状态 | [workbench.css](../src/healthzip/ui/strength_component/workbench.css)、[index.html](../src/healthzip/ui/strength_component/index.html)：ResizeObserver报告实际内容高度，无内部纵向滚动；初载两卡骨架、18px状态图标 |
| 事实写入 | [training_bridge.py](../src/healthzip/ui/training_bridge.py)：复用TrainingService，默认标题、真实重排、历史草稿更正、已删除行恢复保护 |
| 草稿 | sessionStorage保留每个标签页自己的副本，localStorage支持再次打开；按数据库/用户/会话/组隔离。没有回执不会显示已保存。清理浏览器站点数据仍会删除未同步副本 |
| 目录性能 | 元数据索引最多5000项，仅内存保留；180ms去抖后在本地匹配名称、英文、别名、部位、器械、收藏、最近使用。每次打开重读，驻留时60秒复核；收到新服务快照时按训练/目录版本及实际偏好内容失效。媒体仅随请求页传输，超过上限回退服务端分页 |
| 目录一致性 | 添加始终由服务器校验当前目录并写入，缓存不会授予保存成功；其他进程修改别名/收藏也会使下一服务快照失效。目录驻留且无请求时，在60秒复核前可显示旧元数据 |
| 可选建议 | [training_workbench.py](../src/healthzip/ui/training_workbench.py)：有界队列、独立Repository连接、局部轮询和超时说明；记录/资料依赖改变则旧建议明确过期 |

没有新增训练表或第二套实际记录，没有修改科学进阶公式。`TrainingService(..., initialize=False)`只跳过初始化写入，供已经初始化数据库的只读摘要使用；它不是禁止调用写入方法的安全权限模式。

## 行为验收

| 场景 | 已验证内容与证据层级 |
| --- | --- |
| A09–A12 | 真实完整应用Chromium：直接开始、单选自动返回、32.5×8/RIR0保留、取消与刷新恢复；Node事件回归检查取消延时搜索、重复点击、失败重试。搜索脚本核对中文/英文/个人别名结果与真实服务相同 |
| A13 | 真实浏览器：复制无RIR/完成身份，结束前未完成输入保存为draft，完成统计仅3组；真实服务覆盖自重、助力0、时长、距离、历史草稿更正 |
| A14–A15 | 真实浏览器：丢回执后同ID重试、待回执刷新、保存期间另组输入DOM/焦点不变、真实双标签页并发修订冲突、刷新保留各自草稿与显式核对、数据库切换隔离、结束保留本机非法文本以便更正 |
| A16–A18、A22 | 真实Chromium的320/375/390/430/768/1440px几何：主页、选择、进行中、超时、训练历史、动作历史、30动作长训练，前10动作各3组；无内部纵向滚动/横向溢出，最后字段和操作可达。另用30动作专项证明父iframe高度更新后，取消返回原添加入口、新增组字段实际位于可见区域且获得焦点。430px高度模拟可用视区缩小，未宣称真机键盘 |
| A17 | 实际丢回执超时、校验失败与重试截图；真实静态组件初载骨架截图，图标18px。回执刷新保留现有内容 |
| A20 | 真实服务在可控慢建议线程未完成时仍保存实际组；原Streamlit AppTest验证资料故障后可保存并恢复。没有故意拖慢知识提供器的训练专用完整浏览器场景 |
| A21 | 5项真实服务/知识库测试，2项Streamlit AppTest；具体卧推—夹胸选择流程尚未单独录制真实Chromium点击或真机操作 |

最终主浏览器17项、额外边界8项、搜索5项与高度定位2项均通过；对应JSON为本轮实际证据。

主浏览器脚本：[product_redesign_training_browser.py](../tests/training/product_redesign_training_browser.py)。额外边界：[product_redesign_training_edges.py](../tests/training/product_redesign_training_edges.py)。异步高度与定位：[product_redesign_training_scroll.py](../tests/training/product_redesign_training_scroll.py)。搜索/初载：[product_redesign_training_search.py](../tests/training/product_redesign_training_search.py)。结果与截图位于[training工件](../artifacts/product_redesign/training/)。本地Chromium视口、事件与几何检查不等于真实iPhone Safari、软键盘或移动网络验收。

## A21：先核对事实，再决定解释权限

[sequence_review.py](../src/healthzip/training/sequence_review.py)读取用户明确选择的两场不同训练，核对时序、唯一动作实例、记录顺序、条件可比性、完成工作组、同负荷逐组次数/RIR变化及可获得的实际时间。前置动作的工作组/次数与后续动作表现分开，不用总吨位等同刺激。

已有睡眠采用训练前24小时真实样本和既有指标，来源分开；训练间隔由已完成组的实际记录给出。使用当前可见回顾身份，不把晚到资料伪装成当时已知。缺少休息/实际组时间/睡眠时明确列缺项，不补造。

只有显式请求来源时，才以现有MetricResult与当前声明、最新兼容冻结索引走真实 `reviewed_metric` 检索。候选疲劳解释要求同负荷下降、前置工作增加、实际记录顺序和明确适用的审核主张共同成立；不推断因果、肌肉损伤或恢复不全。不可用时事实保留，撤回声明或证据后不得沿用过期解释权限。

[test_sequence_review.py](../tests/training/test_sequence_review.py)正例使用合成知识库经过真实登记、审核、冻结、检索和当前权限复核；它验证软件许可链，不代表文献已获独立专业审定。[UI测试](../tests/training/test_sequence_review_ui.py)检查12→10、RIR0、单边口径，以及更正、导入睡眠、撤回声明后的过期提示。详情见[健康详情交付](product_health_details.md)。

## 性能与回归

全部为同机localhost、真实Streamlit 1.67.0与headless Chromium、Python3.11.7/aarch64；共享执行环境，不是手机线上成绩。宿主可见192逻辑CPU、2,109,313,276KiB内存，并非独占配额；与[整体性能环境](../artifacts/product_redesign/backend-after-100k.json)一致。基准合成夹具初始66场会话、5组、49项目录、0条健康样本，数据库1,699,840字节；长训练逐步增加至30动作，时间包含真实保存/回执/可编辑视图。10万/100万健康样本及1万训练组的全局性能另见整体验收，不把这里的小型训练交互测试扩大到该规模。

| 操作 | 样本/方法 | P50 | P95 |
| --- | --- | ---: | ---: |
| 搜索优化前 | 30次input到当前结果下一动画帧，含180ms去抖及服务回执 | 468ms | 496.3ms |
| 选择动作→保存回执→可编辑训练页 | 30次，训练增加至30个动作 | 496.0ms | 686.3ms |
| 本地目录搜索 | 30次同方法，服务结果逐项核对，零搜索网络命令 | 184.8ms | 187.9ms |
| 本机数字输入 | 40次真实input处理到下一动画帧，零组件命令 | 16.6ms | 16.8ms |

选择动作→真实保存→回到可编辑训练页的30次P50/P95见[主结果JSON](../artifacts/product_redesign/training/training-browser-results.json)，逐次原始样本均保留。[搜索前](../artifacts/product_redesign/training/training-search-before.json)、[搜索后](../artifacts/product_redesign/training/training-search-results.json)、[边界结果](../artifacts/product_redesign/training/training-edge-results.json)分别标明实测方法。首次目录下载/打开不计入已加载目录的本地搜索成绩；超过5000项目录回退服务端，不声称满足本地搜索预算。

已执行训练相关pytest批次238通过（58.44秒）；目录追加后桥接/训练改版30通过（4.75秒），Node既有事件回归3通过。全库pytest和Ruff由整合验收统一记录，不能用这些数量替代浏览器或真机覆盖。

```sh
PYTHONPATH=src .venv/bin/pytest tests/training tests/integration/test_training_bridge.py tests/integration/test_training_redesign.py tests/integration/test_current_training_flow.py -q
node --test tests/training/strength_picker_events_check.cjs
PYTHONPATH=src .venv/bin/python tests/training/product_redesign_training_browser.py
PYTHONPATH=src .venv/bin/python tests/training/product_redesign_training_edges.py
PYTHONPATH=src .venv/bin/python tests/training/product_redesign_training_search.py
PYTHONPATH=src .venv/bin/python tests/training/product_redesign_training_scroll.py
```

浏览器需安装Playwright Chromium及系统库。本轮用临时工作目录隔离数据库、知识库与日志，不访问生产`.local`。截图包括手机/桌面实际训练、动作选择、校验失败、超时、结束摘要、历史和初载；[连续录制](../artifacts/product_redesign/training/video/page@6553f0d087fa133f8304396ead527b0e.webm)保留完整“加动作→填组→再添加→结束”流程与后续长训练检查。重复及未通过的中途录制已移除；主结果JSON记录视频文件名与实际训练源码SHA256。
