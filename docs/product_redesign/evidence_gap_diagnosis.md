# 当前 RAG 缺口的只读诊断

日期：2026-11-21。这里只诊断现有公开知识元数据、代码与合成输入；没有读取真实健康记录或用户声明，没有获取新文献，没有修改科学指标、业务代码或知识数据库。

“来源不足”目前混合了三类不同问题：已审阅主张覆盖不全、使用者上下文缺失，以及上下文传递不完整。直接模型可以试验表达质量，但不能补出未采集的个人事实，也不能证明本地检索覆盖充分。

## 保存的检索结果

依据：[现有公开语料与合成健康数据检查](../../artifacts/product_redesign/rag_result_fix/public-corpus-synthetic-check.json)。该检查在公开知识库备份上运行，没有原库写入和网络请求；没有使用真实健康记录。此表描述这个检查的结果，不推断用户实际数据状态。

| 指标 | 检索到的段落 | 尚缺的已审阅证据 | 尚缺的调用上下文 |
| --- | ---: | --- | --- |
| 静息心率 `STATE-RHR` | 2 | `recovery` 域、`measurement_protocol` 证据类别 | 人群、测量协议 |
| SDNN `STATE-SDNN` | 5 | 本次返回没有报告类别或领域缺项 | 人群、测量协议 |
| 24 小时睡眠 `STATE-SLEEP-24H` | 3 | 本次返回没有报告类别或领域缺项 | 人群、测量协议 |

三项均检索到了原文；没有获得本期来源解释权限。`metric_retrieval.py:639–650` 分别检查已匹配主张的领域、证据类型和调用方上下文，最后合并为 `insufficient_evidence`。其中 `missing_applicability_context:population` / `measurement_protocol` 来自配置的 `present` 检查，不代表文献中没有人群或测量方法介绍。补充文献不会填入这些调用字段。反过来，字段非空也不等于完成了科学适用性验证。

此前“完成后结果消失”的修订标记问题见 [RAG 结果修复](rag_result_fix.md)。保存检查中的 `clock_matches_after_close=true` 表明该检查不再被读取后的版本变化作废；这与本文的证据充分性问题分开。

## 已审阅主张覆盖

此前只读检查了公开知识库的主张/指标关系和来源元数据，没有读取个人库：

- RHR 当前匹配的 `V15-CLAIM-RHR-WATCH-UNCERTAINTY-SCOPE` 绑定来源 `E7`，涵盖 `wearable` 域及测量不确定性、范围限制；范围明确不包含 HealthKit 日静息心率算法验证。因此“RHR 的已审阅协议与恢复域绑定未补齐”有实际依据，但不能据此断言整个语料库没有相关文本。
- SDNN 有 `V15-CLAIM-SDNN-PROTOCOL`、PPG 不确定性、个人基线范围等绑定；测量方法类证据已经存在，其协议方法范围不能升级为具体 Apple 型号或个人结论的验证。
- 睡眠有 `V15-CLAIM-SLEEP-STRUCTURE` 与 `V15-CLAIM-WATCH-SLEEP-STAGE-BOUNDARY`，分别涉及睡眠定义和设备测量边界；本次结果没有缺证据类别。

最小补充顺序是先核对已有来源中真正缺少的 RHR 协议内容，并建立范围明确、经过审阅的主张与指标绑定；只有已有资料确实不覆盖时才需增加新文献。不能用来源总量代替逐指标、逐主张覆盖判断。

## 人群声明的页面传递

`body_pages.py:332–349` 的健康详情解释只取当前会话 `analysis_contexts[workspace]` 中的声明引用。`workflow_page.py:278` 在复盘页提供人群选项，并在执行工作流后将保存的引用写入会话（`workflow_page.py:343–348`）。新浏览器会话未选定引用时，健康详情没有自动选择已保存声明的路径。

`workflows/evidence.py:25` 将未提供的人群设为 `unknown`。`workflows/storage.py:38` 允许保存人群和睡眠来源选择等字段，但没有通用的 `measurement_protocol` 声明字段。应完善明确选择、展示与复用声明的产品路径；不能默认为健康成人或运动员，也不能自动恢复已经撤回的声明。

## 协议传递的合成复现

完整合成输入、指标输出与解释上下文在 [evidence-gap-diagnosis.json](../../artifacts/product_redesign/rag_result_fix/evidence-gap-diagnosis.json)。纯函数调用顺序是 `evaluate(...)` → `local_context(...)`，零数据库访问、零网络请求；合成人群明确声明为 `adults`。3 个用例的断言均通过。

| 输入路径 | 明确输入的协议 | 指标结果 | `local_context` 输出 |
| --- | --- | --- | --- |
| 单一来源睡眠 | `protocol_id=synthetic_sleep_protocol` | 360 分钟，`partial`；值仅含时长、完整性、归属日期与区间 | `measurement_protocol=null` |
| 逐日 SDNN 对照 | `protocol_id=synthetic_hrv_protocol` | 日值 40 ms，`valid`；日点保留 `protocol` | `synthetic_hrv_protocol` |
| 清洗后 NN 的 SDNN | `artifact_cleaning_protocol=synthetic_nn_cleaning` | `valid`；值保留 `cleaning_protocol` | `measurement_protocol=null` |

睡眠的缺口已确认：`science/state.py:19–33` 能读取显式 `protocol_id`，但 `state.py:143–147` 生成睡眠时长结果时不保留该字段。`workflows/evidence.py:42–61` 只读取 `value.streams[*].protocol_id` 或值中列表点的 `protocol[2]`，因而无法从睡眠区间反推出协议。`MetricResult` 的 `source_record_ids` 保留身份，不包含原始协议；当前健康详情也没有给 `local_context` 传入源记录。

日值 SDNN 对照证明显式协议在这条路径可以传递，因此不能泛称“心率协议提取全部失效”。此前公开语料检查的 Apple XML 合成夹具没有协议元数据，其心率缺项是输入本身未提供协议。

清洗后 NN 路径的 `state.py:218–219` 保留了 `cleaning_protocol`，但适配器未识别。这是另一条信息未被消费的路径；它不是普通健康页面日值 SDNN 路径。清洗方法名称也不自动代表完整的采集协议或经过验证的适用性，后续应明确两者语义，不能只为通过非空检查而直接改名。

可从仓库根目录重新运行以下命令核对工件中的输入：

```bash
PYTHONPATH=src python3 - <<'PY'
import json
from pathlib import Path
from healthzip.science import evaluate
from healthzip.workflows.evidence import local_context

p = Path('artifacts/product_redesign/rag_result_fix/evidence-gap-diagnosis.json')
saved = json.loads(p.read_text())
for case in saved['cases']:
    metric = evaluate(case['metric_id'], case['records'],
                      context=case['computation_context'], **saved['bounds'])
    context = local_context(case['metric_id'], metric, [], saved['declaration'])
    assert metric['value'] == case['metric_value']
    assert metric['data_status'] == case['metric_data_status']
    assert context == case['retrieval_context']
    print(case['name'], context['measurement_protocol'])
PY
```

## 本轮结论与后续优先级

1. 用直接模型试验实际回答的可读性、事实一致性和不确定性表达；独立检查引用，不能把模型自报来源视为已经验证。
2. 保留当前已检索原文和具体缺项展示，避免空白结果让用户误以为没有执行检索。
3. 补齐健康详情的人群声明选择和真实协议元数据传递。睡眠须保留所选来源与协议的关系，不能以设备名称替代协议。
4. 针对 RHR 补齐真正缺少的已审阅协议主张；SDNN 与睡眠优先解决上下文问题，而非盲目增加资料。
5. 分别设计一般知识说明与个人变化解释的适用条件。可以审查当前所有说明都要求“人群与协议非空”的产品规则是否过宽，但本轮没有放宽检查或更改科学合同。

上述合成运行验证软件传递现象，不证明任何真实人群的测量有效性或医学结论。本轮只新增诊断文档与合成工件。

## 四个直接模型响应的独立审读

审读对象为 [直接模型试验工件](../../artifacts/product_redesign/direct_model_probe/probe-results.json) 中的四个原始响应。模型为 `deepseek-v4-flash`；输入明确为合成数据，未进行 RAG。以下核对输入和输出内部的一致性，不是临床验证，也不声称已经联网核实书目或阅读全文。原始模型响应保留，不替模型改写成“通过”结果。

| 案例 | 保留的价值 | 需要纠正或核实的内容 |
| --- | --- | --- |
| `matched_7_day_heart_sleep` | 正确给出心率 +5 bpm、SDNN −9 ms、记录睡眠 −0.9 h；候选解释附有缺项 | `next_steps[0]` 新增 `<4 h`、连续 `<6 h` 标准，没有逐条来源映射；睡眠、咖啡因与 SDNN/自主神经方向的泛化需要核实研究范围。并未查出这些值来自输入或已有规则。 |
| `sleep_duration_unknown_coverage` | 识别 4 晚与 5 晚的记录覆盖差异，提出核对漏记原因 | `possible_explanations[0].hypothesis` 写“睡眠时长确实有所增加”，应限定为已记录夜晚的均值；年龄未知却用成人 `7–9 h` 形成个体睡眠不足候选；新增“至少 14 天”和 `1–10` 评分但未映射依据；`unknowns` 又称两窗时间间隔未知，与输入的连续两窗不符。 |
| `unknown_protocol_population` | 保留了指标定义、人群、设备一致性缺项 | HRV 未定义且跨设备，仍首先解释为副交感增强/恢复改善；设备 `10–20 ms`、体位 `3–5 bpm`、技术误差 `5–10%`、至少 10 次/5–7 条等具体数值没有可核验的逐主张依据。`references[2].verification_status` 虽称待核验，又把特定记录方式和误差界限归给 Plews，须核原文，不能仅验证书目存在。 |
| `sparse_unequal_windows` | 没把缺失睡眠直接填成 0，也没有把稀疏点直接判为持续恶化 | `possible_explanations[2].what_is_missing` 与 `unknowns[1]` 漏掉已提供的 11 月 7 日心率 61；`next_steps[0]` 将 11 月 11–13 日采集称为 11 月 8–10 日“当前窗口”的多次测量；把 `5–7 bpm` 差解释为可在正常变异内，却无个体适用依据；睡前要求记录睡眠时长，容易把预计时长当成已发生记录。 |

四个响应都能生成更完整的候选解释和记录步骤，且参考条目标为待核验；但这次小样本不能证明直接模型比 RAG 更准确。上述事实遗漏、窗口错位、未经支持的量化和适用性问题表明，模型可作为表达层试验，数值与时间范围仍需由确定性计算提供，引用与关键主张仍需核实。书目存在、书目元数据准确、原文支持具体说法、适用于该输入，是四个不同检查。

## 直接模型提及的论文是否已在本地

使用 SQLite `mode=ro` 检查公开来源库全部 63 条 `source` 的 `manifest_json` 与 `canonical_identity`，按规范化题名和 PMID 匹配；没有搜索私人库、没有读取来源正文，也没有联网下载。查询和结果见 [本地来源登记核对](../../artifacts/product_redesign/rag_result_fix/direct-reference-local-presence.json)。

Task Force 1996、Plews 2013、Nunan 2010、Watson 2015、Ohayon 2017、Ancoli-Israel 2003、Shaffer 2017、Carter 2003 这 8 篇均未发现独立来源登记。另检索 Czeisler/Buxton 书章题名也未命中。这里的“未登记”不排除其题名或结论出现在已有综述的参考文献或正文中；二手引用也不等于已取得并审阅该原始论文。

本地另有下列相关资料，当前来源记录的 `acquisition_state` 均为 `acquired`：

| 来源 ID | 已有资料 | 优先核查的范围 |
| --- | --- | --- |
| `R3b` | *Heart Rate Variability Applications in Strength and Conditioning: A Narrative Review*，2024 | HRV 指标定义、测量条件、解释范围与已有主张绑定 |
| `E7` | *The accuracy of Apple Watch measurements: a living systematic review and meta-analysis*，2026 | 具体设备与研究协议的测量限制；不能自动转为所有 Apple 日静息心率算法的验证 |
| `R4` | *Effects of Acute Sleep Loss on Physical Performance: A Systematic and Meta-Analytical Review*，2022 | 睡眠与体能的研究范围；不自动支持个体 SDNN 变化的原因 |
| `R5` | *Monitoring the athlete training response: subjective self-reported measures trump commonly used objective measures: a systematic review*，2016 | 主观记录的用途与人群范围；不自动授予随意评分或天数阈值 |
| `V15-NIH-SLEEP-2011` | *Your Guide to Healthy Sleep*，2011 | 睡眠一般知识、适用年龄和采集解释边界 |
| `V15-QUER-RHR-2020` | 92,457 名成人日静息心率变异与年龄、性别、睡眠、BMI、季节关联研究，2020 | 群体关联和设备协议；不能直接跨设备推导个人正常波动阈值 |

不应为“扩充数量”重复获取这些已有资料，也不应因为模型列出的 8 篇未独立登记就整批下载。先逐条确认需要表达的主张能否由已有全文支持，再补审核、协议范围与引用绑定；确需原始方法或共识时，再定向补对应论文。本轮未作全文内容充分性审定，也未新增任何主张或解释权限。
