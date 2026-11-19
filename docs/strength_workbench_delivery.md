# 力量工作台验收记录

本轮以 `d91976e36d09a6c8415336f6c60c82a297d582f8` 为兼容基线，在原仓库上增量实施。入口、私人数据库、训练事件、修订、原有建议权限和科学分析继续保留。

## 实际界面

以下图片均来自真实启动的完整 `app.py`，通过 Chromium 点击和输入产生；资料全部为临时合成记录，不含用户 Apple Health 数据。

| 界面 | 截图 |
| --- | --- |
| 力量首页、月历与无未结束训练的入口 | [手机首页](../artifacts/strength_workbench/01-home-calendar-mobile.png) |
| 自由训练开始面板 | [开始训练](../artifacts/strength_workbench/02-start-empty-mobile.png) |
| 动作选择与已选状态 | [单选状态](../artifacts/strength_workbench/03-catalog-selected-mobile.png)、[有序多选](../artifacts/strength_workbench/08-catalog-multiselect-mobile.png) |
| 紧凑组行与完成状态 | [实际输入](../artifacts/strength_workbench/04-compact-set-input-mobile.png)、[完成组](../artifacts/strength_workbench/05-completed-set-mobile.png) |
| 完成和未完成数量、可选结束反馈 | [结束摘要](../artifacts/strength_workbench/06-end-summary-mobile.png) |
| 六动作卡片 | [手机卡片列表](../artifacts/strength_workbench/09-six-exercise-cards-mobile.png) |
| 桌面布局 | [组录入](../artifacts/strength_workbench/07-workbench-desktop.png)、[多动作列表](../artifacts/strength_workbench/10-six-cards-desktop.png) |
| 并发更改后的明确核对入口 | [冲突核对](../artifacts/strength_workbench/11-concurrent-review-mobile.png) |

需求中引用的五个 `IMG_8772.PNG` 至 `IMG_8776.PNG` 未出现在本次可访问附件目录中；可访问的是需求文本。实现与验收依据文本中的布局、颜色、交互和完整性合同，不宣称已经逐图核对这五份原图。

## 对照需求的验收

最终冻结资源的真实浏览器检查20个分项通过，页错误0、外网请求0；回执记录8个实际产品源文件的SHA-256，并确认整轮运行期间未改变。真实浏览器回执见 [browser-results.json](../artifacts/strength_workbench/browser-results.json)。脚本在临时工作目录启动完整应用，测试服务只绑定 `127.0.0.1`，HTTP 外网请求被阻断，数据库和知识目录均与生产隔离。验证同时回查真实训练表及事件，没有用前端颜色或静态 HTML 代替写入成功。

| 场景 | 结果 | 实际证据 |
| --- | --- | --- |
| 1. 无模板开始并结束 | 通过 | 首页开始→自由训练→胸部搜索→动作确认→自动全空草稿→32.5 kg×8，RIR 未知→完成→结束。无模板、参考身份或采纳步骤；未伪造组开始时间。 |
| 2. 批量动作 | 通过 | 六动作跨搜索保序选择，关闭不写入，确认后顺序与数据库一致；明确“再次添加此动作”产生合法独立实例。整体重试/原子回滚另由真实服务集成回归覆盖。 |
| 3. 六动作×三组 | 通过 | 经真实按钮为六动作各建三组，只有一张卡渲染完整编辑器，主输入行总数为三；切卡保留未提交输入。 |
| 4. 数值与测量类型 | 通过 | RIR 未知、0、2，32.5/33.75/20.75 kg，小数时长33.5秒、距离24.75米正确落库；已有模板显示真实确认的自重、助力、每只哑铃口径，不重复添加第四个草稿。 |
| 5. 草稿、更正与高级字段 | 通过 | 已存草稿刷新恢复，查看历史不丢本地输入；完成组更正保留原结束时间且只计一次。真实服务回执延迟时继续输入，新值仍为待保存。核对并发版本后主行保存保留最新疼痛、技术质量、质量说明和备注。 |
| 6. 重复请求与冲突 | 通过 | 已完成按钮双击不改事实；丢弃真实保存回执后点击同请求重试，不新增事实。另一真实 Repository 连接修改修订后，界面明确冲突并保输入；“核对最新记录”对照后，用户明确保留本地输入并再次保存成功。 |
| 7. 历史与建议 | 通过 | 最近一次混合三组完整展示；480天前的真实日期与记录可读，首次动作明确无历史；复制只生成无RIR、质量、时间和完成身份的草稿。显式查看建议不修改本次实际，生产资料缺项不妨碍继续记录。 |
| 8. 删除与撤销 | 通过 | 逐组删除/撤销完成数量3→2→3；整场删除/撤销3→0→3，经事件和数据库回查。既有冻结及删除重选边界由历史/当前建议回归保留。 |
| 9. 时间与结束 | 通过 | 返回仍可继续，计时展示期间训练事件增加0条；休息开始、暂停、继续、延长、结束均走原服务，没有自动60秒或虚构组开始。结束保留2个未完成草稿，可选20.5分钟、sRPE6及备注正确保存；训练中已存旧备注，结束时改新备注后，历史卡片显示新值。 |
| 10. 目录和空态 | 通过 | 无结果有明确提示，缺图有统一中性占位，长中文名称可读，记录流程不依赖外网媒体。真实本地合成中性图通过原媒体路径读取，再在浏览器触发解码失败；实际回退“无图片”，选择和记录继续。 |
| 11. 日历 | 通过 | 一个本地月份63场，1日独立61场，超过历史第一页50条；删除排除、UTC月界归属、跨月/跨年切换正确；选择过去日期后开始仍用真实今天。 |
| 12. 响应式 | 模拟浏览器通过，真机未验证 | 首页、组行、多选和六卡列表分别检查320/375/390/430/1440视口，页面与主要控件无横向溢出；桌面主区限制宽度。没有真实iPhone，未验证原生数字键盘、Safari及真实软键盘安全区。 |

丢失/延迟回执测试只在浏览器的消息投递层设置门控：Python 仍收到真实命令、完成原验证和写入，浏览器随后点击真实重试按钮。没有伪造后端回执、替换核心选择/计算/权限，或直接调用隐藏按钮。

## 执行命令与限制

开发环境有 Playwright，Chromium `158.0.8127.18` 位于临时浏览器安装目录，所需系统库也位于临时目录。实际运行命令：

```sh
PLAYWRIGHT_BROWSERS_PATH=/tmp/healthzip-browser-bin \
LD_LIBRARY_PATH=/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu \
.venv/bin/python tests/training/strength_workbench_browser_check.py \
  --output artifacts/strength_workbench
```

这是本环境的开发验证路径，生产运行不依赖 Playwright、临时浏览器目录或外部 CDN。组件为随包分发的三个原生 HTML/CSS/JavaScript 文件，没有 npm 构建步骤。运行和打包说明见 [界面说明](strength_workbench.md)。

全套 pytest 分为四个互不重叠的文件清单，在四份隔离的公开代码副本中执行；每份副本都有独立的临时知识目录，不读取生产 `.local/knowledge`。文件清单、各片命令、实际结果与最终源码核对见 [验证回执](../artifacts/strength_workbench/verification.json) 和 [分片清单](../artifacts/strength_workbench/pytest-shards.json)。每片实际使用以下命令结构，文件参数为清单中该片的全部 `files`，不是抽样：

```sh
PYTHONPATH=/tmp/healthzip-strength-final-N/src \
/home/sn_maozhifang/apple/.venv/bin/python -m pytest -q --tb=short \
  --junitxml=/tmp/healthzip-strength-final-N.xml <该片完整文件列表>
```

最终四片分别为510、515、523、492项，共 **2040通过，0失败、0错误、0跳过**，覆盖全部132份pytest测试文件且无重复分配。另一次训练与桥接集中回归223项通过。警告包括现有 `jsonschema.RefResolver` 弃用提示及 `record_property` 的JUnit格式兼容提示，未静音，均未导致断言失败。提交前发现三片早期副本缺少最后的媒体容错和输入保护修正，已同步最终源码并重新执行对应分片，回执只采用最后结果。

以下检查全部通过：

```sh
.venv/bin/ruff check src app.py tests
node --check src/healthzip/ui/strength_component/workbench.js
git diff --check
.venv/bin/python -m pip wheel . --no-deps --no-build-isolation \
  --wheel-dir /tmp/healthzip-strength-wheel
```

wheel为 `health_zip_workbench-1.4.0-py3-none-any.whl`，SHA-256为 `b1a94f4472cd194ce185da9c86856342bc8db576d804d15ac7c6bc08afeeceb4`。三个组件资源均与最终源码逐字节一致。项目规定的Ruff范围是 `src app.py tests`；额外尝试的全目录扫描仍发现执行包和工具目录中的既有80项问题，本轮未修改这些无关文件。

## 部署与提交范围

已通过SQLite backup API完成部署前本地备份，随后重启 `healthzip-ui.service` 和 `healthzip-rest.service`。两项user systemd服务均保持enabled、active/running，UI与REST健康检查均返回HTTP 200；监听地址、token及CORS保持原配置。

部署后在390和1440像素视口打开真实力量首页，点击“健康总览”返回真实总览，页面选择和地址同步正确，无页面错误。该检查只切换视图，不创建训练；前后数量核对一致，未写入训练。最初的检查误用按钮文字而忽略其无障碍名称“返回健康总览”，修正定位并实际点击后通过，无需修改产品代码。

本提交包括力量组件及桥接、原训练入口的按需管理视图、结束备注的兼容保存、相关回归适配、合成浏览器脚本、11张运行截图及界面文档。实际提交SHA与逐文件清单可在Git提交中核对；私人数据库、Apple导出ZIP、用户PDF、本地运行日志和配置均不在提交范围。

实际测试仅说明软件行为及模拟视口结果，不增加真实科学审核、个体有效性、建议权限或原生手机验证声明。
