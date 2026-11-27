# R03：来源估计与行动复评

已修复。选择行动时从现有 `METRIC_CATALOG.kind` 冻结观察单位；不增加第二套指标注册表。真实日代表值和睡眠继续日等权；区间累计量标明“完整日已记录累计量的期间中位数”，稀疏样本说明不能代表未测时段，事件保留实际记录和数量。低频估计使用 `source_estimate_points`，包括当天已经可见的点。

在“复盘 → 问题分析”选择六分钟步行距离后，“行动复评”会显示来源估计值、记录数量、明确提供发布时间的数量，以及支持窗口相对计划和实际执行的关系。示例为 **420 → 445 m**，同时指出支持窗口跨越计划开始、不能据此判断这次行动的效果。它不会再将当天的 445 m 排除为“未完整日”，也不会称为“行动后每日测量中位数”。

## 实现与边界

- `body_metrics.estimate_period_summary` 供身体详情、问题页与行动共同使用。窗口内末次**来源观测点**是紧凑显示选择；全部点、原始时间与来源记录仍保存，不计算独立样本数、显著性或置信区间。已知发布时间与导入可见时间分别保存，未提供的发布时间保持未知。
- 新行动 `action-outcomes-3.0` 冻结观察类型、统计版本、来源、固定基线/后续窗口、定义及问题身份。支持窗口逐点区分开始前、跨越开始、窗口内、延伸出窗口或未知；实际执行另行判断。延迟或停止不移动窗口。
- 相同支持窗口重复发布同值不会增加独立测量；未知窗口不推造。方法或算法版本分组改变时保留已有数值并停止同方法差值。源记录的后续修订只影响新评估。
- 旧非日观察行动缺少观察单位时不静默改算：保留原定义、反馈与旧复评，提示历史口径，可显式创建含 `supersedes_action_id` 的关联新行动。已有日指标/训练行动的同方法统计、RIR=0、执行未知/延期/停止合同继续回归。
- 官方 Apple 2021 文档的 4 周和 500 m 不再凭一个算法字符串套用到所有设备。只接受明确的文档/版本、Apple Watch 机型、watchOS 7、方法与算法身份；推定支持窗口还要求来源明确给出 `estimate_at`，并标为推定。匹配规则中列出 2021 年机型是保守的产品匹配选择，不能冒充厂家逐机型认证。来源已有显式窗口优先保留，未来系统或其他设备保持未知。
- 依据为 Apple *Using Apple Watch to Estimate Six-Minute Walk Distance*, May 2021，[原文](https://images.apple.com/healthcare/docs/site/Using_Apple_Watch_to_Estimate_Six_Minute_Walk_Distance.pdf)：p3 设备与系统，p4 前4周与通常周更，p8 500 m 报告上限，p9 未验证显著纵向变化且不能移用临床测试变化阈值。具体原文阅读及用途权限见知识交付；没有专家审定或人体行动效果验证。

## 行为证据

| 场景 | 证据与结果 |
|---|---|
| 修改前真实复现 | [before.xml](../artifacts/followup_20261127/actions/before.xml) 三项失败；[隔离00a35d2真实页面](../artifacts/followup_20261127/actions/browser-before/browser.json) 显示420 m→未知、支持窗丢失。旧源码由git archive写入临时目录，没有切换工作区或改写历史 |
| 跨计划起点、同日可见 | 新测试精确核对445 m、原支持窗、与基线重叠、发布时间和独立测量次数未知 |
| 重复/不重叠/未知/版本改变 | 同窗两次发布保留2个来源ID、仅1个已知支持窗；不重叠也不判独立；新版本不混算；截止后才可见的记录被排除 |
| 精确上限/未知设备 | 确切声明范围才获得500 m上限和有依据的推定支持窗；只算法名、watchOS 11或其他设备不获得；两个上限值不判能力未变 |
| 冻结与消费者一致 | 同一范围详情、W7与行动逐项比较；W4冻结报告同一review；追加原记录修订后历史截止和旧冻结正文/对象不变 |
| 实际页面 | [browser-r4](../artifacts/followup_20261127/actions/browser-r4/browser.json)：真实选择→保存→同日估计→展开支持窗→填写延期/停止反馈→W4→生成并重开报告；六宽度无主页面横溢。已目视检查[390估计结果](../artifacts/followup_20261127/actions/browser-r4/estimate-review-390.png)，完整显示数值、单位、支持窗和限制 |

专项命令：

```bash
.venv/bin/python -m pytest tests/integration/test_followup_action_observation_units.py \
  tests/integration/test_action_outcome_repairs.py tests/science/test_question_context.py \
  tests/science/test_master_science.py -q \
  --junitxml=artifacts/followup_20261127/actions/final-tests.xml
PLAYWRIGHT_BROWSERS_PATH=/tmp/healthzip-browser-bin \
LD_LIBRARY_PATH=/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu \
.venv/bin/python tools/followup_actions_browser.py --output <新的输出目录>
```

本阶段专项103项通过（含11个新R03场景，不与全量相加），相关Ruff通过。`iteration-1/2`保留中途失败：一次补丁位置错误、测试插入缩进错误，以及主题门禁后旧空W6夹具不再提供行动；后者改为真实睡眠背景而仍无SDNN，继续验证首次SDNN动态失效。旧master合成源仅声明算法名的上限预期改为未知，并另增严格范围正反例，未放宽产品要求。

浏览器r1为控件选择脚本选错选项，r2为工具仍读取旧大报告`current`字段；均保留失败。r3/r4真实行为通过；r4期间另有代理修改报告实现，改动文件清单保存在回执，行动/估计文件没有变化。最终受验源码与必要补跑由总交付核对，不能用阶段回执冒充全仓最终身份。

实体 iPhone、Safari、软键盘及人体效度未验证。所有健康数据均为新建合成库，无私人记录外发；正常观察不自动证明行动效果。
