# R04 / R05 交付核对

后续实际接入已继续完成，最新状态见 [R05 实际安装与内容补检索](followup_knowledge_completion.md)。下文保留 f863e2e 发布时“仅安装公共备份”的历史状态和当时回执；不再代表当前实际资料库。

基于 `00a35d23c3468ff1b48304d044bcdfe0b5ce5173` 的当前工作区继续修改。旧回执、来源版本、审核、权限、数据库和冻结历史未删除或重写。验证仅用合成健康库及公共资料备份；没有外部模型调用。

## R04：已修复，证据随实际回答进入正文

报告不再使用 `items[:2]`。`knowledge/topics.py::answer_evidence` 根据回答用途选择已通过检索门禁的完整主张，按精确 claim/version 去重；正文保留其适用限制和原文位置，重复引用指向首次说明。同一来源/版本只显示一次链接，各用途保留原文定位，段落不再连排。不会给本地计算的数值伪配论文依据。

`knowledge/claim_status.py` 和 `workflows/reports.py::current_report_source_status` 在重新阅读时核查精确版本、当前冲突、必要前提、范围和来源使用权限。新增冲突只限制相关主张/行动；独立方法与事实保留。来源外链暂时不可达不写成科学撤回，缺版本与服务不可用分别标识。冻结正文和当时的审核不改变。来源与目标索引支持按所用主张查询，不以全文全库扫描代替当前核查。

新报告保存小型 `current_claim_refs`，普通阅读不为当前状态核查恢复工作流 JSON。旧报告仍有兼容回溯路径。

可复核证据在 `artifacts/followup_20261127/knowledge/`：

- `reproduction.json`、`report-before.md`：基线真实 W2/W4 排第三行动已冻结却不在正文；冻结后新增冲突仍被标 current。基线 W3 数据不足，未虚称已复现 W3 正文遗漏。
- `third-tests.log/xml`：12 项专项。包括真实检索的全部六种排列、去重、精确版本/范围、依赖冲突、权限、服务不可用，以及真实 create→冻结→重新打开→离线审计重建；知识变化后原正文相等。当前状态查询不读取 workflow_run/analysis_run。
- `knowledge-regression.log/xml`：`pytest -q tests/knowledge tests/integration/test_followup_report_evidence.py`，279 passed；包含上述专项，不重复累加。
- 最后修改来源去重和段落后：`final-evidence-tests-2.log/xml` 为 13 passed，新增“同一原文支持不同用途仍保留两条说明、只显示一次链接”。`ruff-final.log` 为涉及文件的最终 Ruff 通过。279 项是该排版修改之前的知识回归，最终全量回归由主交付记录。
- `real-report-e2e.json`、`report-after.md`：公共真实语料的 W2/W3/W4 均有事实行，目标行动的 statement、全部限制和 URL 确实进入正文，重新打开和审计重建相等。最终排版结果以 `browser-report-final/report.md` 为准。
- 浏览器回执另见下述真实页面结果。早期失败的测试、脚本和日志保留；未用失败轮代表最终通过。

## R05：部分完成，已核验内容与剩余缺口分开

[六问实际答案](followup_knowledge_six_questions.md) 覆盖 RHR、SDNN、睡眠、联合分析、力量/复评和六分钟步行估计，每问有直接出处、产品选择与研究结论边界。机器可读副本为 `six-question-content-answers.json`；这不是 66 题全覆盖结论，也不宣称页面把 36 个格子的文字逐字铺开。

先读现有合法原文，再建立四条窄用途主张。`public-backup/passage-readings.json` 记录精确来源/版本/段落/hash/权限；`narrow-claims.json` 分开记录审核、绑定和实际命中；`retrieval.json` 记录当前真实检索。审核明确为 AI 辅助，未有独立专家审定。

| 窄用途主张 | 实际状态 |
|---|---|
| RHR 佩戴/算法与同人比较 | 公共备份已入库、已审核/路由，默认命中 RHR 和 W4 |
| 睡眠时段/覆盖与版本限制 | 公共备份已入库、已审核/路由，默认命中睡眠和 W6 |
| 完成组数不等于相同刺激 | 公共备份已入库、已审核/路由，默认命中 W1 |
| HRV 变化应结合实际表现/疲劳 | 公共备份已入库、已审核/路由，属于完整候选；默认有界检索尚未选中，不能称已用于默认页面 |

Apple 2021 六分钟步行全文已读，具体支持窗口、算法上限和纵向限制已提供给 R03 实现。原件 `index_allowed=false` 保留，未伪造索引授权。Bellenger 合法留存接受稿已核对相关方法/结果/限制，仍不允许索引/再分发；用可索引 R3b 的窄方法说明作为替代。Plews 当前只有摘要级材料，没有声称读过全文或采用最少天数结论。详见 `additional-reading-status.json`。

尚未完成：新 HRV 主张进入默认回答；现用设备/算法的人体个体效度；精确 e1RM 个人误差、跨动作效度及精确 RIR 目标；其他夜间设备指标的全套特异验证；授权教材缺口与真正独立专家评审。已有负荷/次数、健康事实、图表及记录核对仍可用。

## 公共资料安装与环境边界

本轮新主张只应用于 `/tmp/healthzip-followup-knowledge-20261127` 公共备份。实际 `.local/knowledge` 未追加；私人健康库未打开。仓库提交包含可复现的精确版本核验/追加工具，不提交公共数据库或受限原件。已有权利和旧版本不改变，重复执行不会替换已存在主张。

在含对应合法原文版本的公共资料库备份上执行：

```bash
.venv/bin/python tools/followup_knowledge_audit.py \
  --root /path/to/public-knowledge-backup \
  --output /path/to/receipt --apply
```

缺原文、权限不满足或精确版本不符会失败；不能用这一命令授予权限。去掉 `--apply` 仅核查已安装内容。公开提交不等于原运行资料库已更新。

## 真实页面验证

使用 `tools/followup_knowledge_browser.py`，真实 Streamlit、Chromium、合成健康库与上述公共备份，禁用外部模型。`browser-fifth/browser.json` 为 14 项、0 页面错误：六个核心主题各有数据/无数据分支，加实际生成下载/重新打开/离线审计重建及报告页面。390/1440 宽度均未撑宽主页面；真实 RHR 数值、比较和趋势可见，新 RHR/睡眠/组数主张在页面中确实可见。截图和正文各自保存，未用截图代替点击回执。

来源段落修正后单独补跑 `--report-only`：`browser-report-final/browser.json` 为 2 项、0 页面错误；`report-action-390.png` / `report-action-1440.png` 实际显示 W3 行动说明、完整限制和原文。下载正文 37,576 字节，W2/W3/W4 目标行动与冻结/重开/审计一致。界面全流程单次 17.11 秒，包括等待和下载按钮可用；不是纯生成时间或 P95 性能成绩。

并行实施期间，六主题轮开始后 `body_questions.py`、`analysis_page.py`、`period_report.py`、`report_objects.py` 有变化；报告补跑期间 `body_questions.py` 又有主题门禁修改。回执分别记录开始和结束源码 hash，不将本轮当作所有最终文件的静态代码验收。最终主题门禁/主发现首屏由主交付的稳定版本补验；本轮知识选择、完整引用及冻结重建核对已通过。前四次浏览器脚本的旧标题/折叠状态/虚拟下拉定位失败日志和已有截图均保留，没有改产品期望来过关。

实体 iPhone/Safari/软键盘、人体效度和已授权目标远程模型均未验证。
