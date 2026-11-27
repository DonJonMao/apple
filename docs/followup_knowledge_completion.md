# R05：实际资料库接入与具体内容补检索

本轮从已发布 `f863e2e80af5da41bd1e211a91ca9d788e44a38f` 继续；保留先前所有工件，不把公共备份当作实际安装。

## 用户实际能看到的内容

身体 → 心率 → 心率变异性 SDNN →「依据与原文」，现在默认能读到两个具体回答：HRV 升降本身不能判定训练恢复，需要核对实际表现/疲劳/睡眠；某设备整夜 RMSSD 或心率的一致性不能直接验证短片段、自由活动或另一设备的 SDNN。说明保留原研究范围、实际缺项及原文，不把未知年龄当成人，不推造当前设备精度。

复盘的问题分析 W2/W6 及相应新报告也使用 HRV 训练反应说明。RHR 的佩戴/算法核对、睡眠记录覆盖与版本限制、训练组数不等于相同刺激，已从公共备份实际安装到运行公共资料库。普通事实、趋势和训练流程没有因方法证据不足而被隐藏。

## 为什么原先未召回，现在能回答

原来只核对「测量、比较、解释、行动」四种用途。通用说明可以填满用途，却没有回答“HRV 方向能否单独代表训练反应”。新增内容没有获得特殊排序分数或 claim ID 白名单。

现在复用已有的 `answer_bindings` 结构，将已读原文、精确主张版本和具体、限定范围的命题绑定到既有 topic 应用审核边。首次检索之后，只有未回答且确有当前适用审核组的问题才触发补检索。缺用途和缺具体回答共用原来的一轮本地补检索，最多 6 个片段，总预算仍为初次 6 + 补充 6。完整前提、范围、审核、来源和使用权限全部经过现有门禁；相同主张的多条审核边只合成一个证据组，不重复显示文字。

实际 SDNN 检索为 12/12 个唯一片段；W2 为 12/12，原 `MASTER-HR-CONTEXT` 行动仍保留；W6 为 9/12。数量仅说明资源边界，具体答案和限制见 [六问内容答案](followup_knowledge_six_questions.md)。所有补充查询均为固定公开方法问题，没有私人值或远程模型调用。

## 实际安装与原数据保留

已写入真正的 `.local/knowledge`，不是仅存在于 `/tmp` 备份。安装前通过 SQLite backup 创建：

`.local/knowledge-backups/f863e2e-r05-before-20261127/`

备份原件的 SHA256 和大小见 `artifacts/followup_20261127/knowledge-completion/backup-before.json`。`tools/followup_knowledge_install.py` 在追加前后逐行比对备份与实际库：28 个受保护内容表、920,291 条原有行的内容 hash 一致。来源原文、使用权限、审核、科学状态、旧主张、关系和冻结 release 未改写。两库 UUID/跟踪版本/结构身份不变，仅科学授权修订计数因追加由 sources 2601→2609、theories 391→412 正常变化。

追加包含原先四条窄主张及本轮 Carter 段 10/53/55 的设备/指标/协议转移限制，共五条主张；新的明确回答绑定通过追加审核边保存，不覆盖原审核。安装前已统一验证所有精确原文版本和权限。`live-install/installed/` 分开记录原文阅读、审核、索引路由、默认检索和用途。

复现命令（仅用于有相同合法原件且已经独立备份的公共资料库）：

```bash
.venv/bin/python tools/followup_knowledge_install.py \
  --root .local/knowledge \
  --baseline .local/knowledge-backups/f863e2e-r05-before-20261127 \
  --output /path/to/receipt --apply
```

不提交数据库、公共原件或私人健康资料；没有打开真实健康库。没有修改 Apple 六分钟步行、Bellenger 接受稿等受限原件的索引/再分发权限。Carter 为已合法留存且允许当前本地用途的原文，阅读范围已记录，不声称本轮重读整篇或获得独立专家认可。

## 验证与剩余边界

[专项日志](../artifacts/followup_20261127/knowledge-completion/final-targeted.log)与 [XML](../artifacts/followup_20261127/knowledge-completion/final-targeted.xml)：23 项通过，包含完整证据预算、两内容问题共用一轮预算、条件不匹配、不完整绑定、撤销、来源撤回、商业用途权限、局部冲突及独立方法保留；也包含既有报告冻结/重开专项，不与全量知识测试重复累加。

[知识回归日志](../artifacts/followup_20261127/knowledge-completion/final-regression.log)与 [XML](../artifacts/followup_20261127/knowledge-completion/final-regression.xml)：最终 `pytest -q tests/knowledge tests/integration/test_followup_report_evidence.py` 为 **290 passed，62.47 秒**，已包含上述 23 项。`ruff-final.log` 为本轮知识实现、工具和测试的最终 Ruff 通过。更早 288 项回归及所有尝试日志保留，不累加成另一总数。

`live-browser/browser.json`：真实 Streamlit/Chromium + 合成健康库 + 实际 `.local/knowledge`，**14 项通过、0 页面错误、运行期间产品源码无变化**。六主题分别检查有数据与无数据，另检查报告生成/下载/重开/离线审计重建；390/1440 宽度主页面没有被撑宽。`hrv-response-390.png`、`hrv-protocol-390.png` 可直接看到新说明、限制与原文链接。数据案例使用合成设备与未知年龄，来源文字明确没有证明当前设备/个人适用性。

`live-browser/report.md` 为 38,604 字节，原 W2/W3/W4 行动说明及全部限制/URL仍在正文，冻结重开和审计重建相等。真实页面文字分别保存为 `data-*.txt`、`missing-*.txt`；知识的有用性通过具体比较、测量解释和下一步核对，未以全页拒答换低错误率。该浏览器轮未评估实体手机或远程模型，也不作为专用性能基准。

`six-question-content-answers.json` 将实际 36 条回答、直接依据、读取/审核/默认检索/页面证据分开记录。它不把论文数量、用途标签或界面存在当成每个设备协议的六问充分性。

仍未完成的科学验证：现用设备/算法的个人人体精度；精确 e1RM 个人误差与跨动作效度；个人精确 RIR 目标；其余夜间设备指标全套特异验证；未合法取得全文的教材/Plews 特定结论；独立专家审定、实体 iPhone/Safari、已授权目标远程模型验证。Apple 2021 六分钟步行的支持窗/上限只按精确元数据匹配使用，不推广到所有算法。上述限制不等于已知原文没读，也不代表全部 66 题内容已经充分。
