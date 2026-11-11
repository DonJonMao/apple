# HealthZIP v1.3 实现与验证状态

更新：2026-11-11。开发基线为 `49349e44df9abf9dbfb480dfef00a53fc224d8c9`；本文记录v1.3源码与验证材料的交付状态，提交记录以Git历史为准。原用户PDF/ZIP保留在本地。历史v1.0说明存于 `docs/history/`。

## 五个维度分别交付

| 维度 | 实际状态 |
| --- | --- |
| implementation | 训练完整生命周期、离线记录/同步、v3迁移、77项MetricResult、Source/Theory分库、6路检索、候选闭环及研究评测均有可执行路径；依赖不足时明确降级 |
| software_verification | 最终整仓 **423 passed / 0 failed / 0 skipped**，Ruff及uv锁检查通过。日志见 `artifacts/verification/pytest.txt` / `pytest.xml`，Ruff见 `ruff.txt`；执行包178条验收具名测试记录在 `artifacts/science/acceptance-results.json` |
| corpus_acquisition | 43来源均已尝试，29取得科学身份元数据，14不同来源取得获许可/明确允许内部使用的全文；其余逐项保留权限/身份/访问原因 |
| theory_review | 20种子均有审计；11卡仅选定主张完成AI辅助阅读审阅，9草稿；没有冒充独立专家审核或授予个人数值处方权限 |
| scientific_validation | 趋势、能量与B0/B1评测可重跑，当前仅simulation_only；真人时间外预测/干预有效性和独立RAG语义审查未建立 |

因此不能将本交付称为“全部科学功能已获验证”。完整逐项状态见 `requirements_traceability.csv`（77指标+13操作需求），具体阻塞与重试见 `docs/delivery_audit_v1.3.md`。

## 已实现的软件行为

- 真实Repository上的动作搜索/分类/别名/收藏/自定义、器械、模板版本、临时/模板训练、目标与实际、逐组状态/修订/撤销/乐观冲突、计时、结束反馈及历史。动作替换、排序、条件维护与不同记录模式已接界面。
- 客户端稳定事件ID区分网络重试与真实相同组。独立HTML缓存动作/冻结模板，断网保存并刷新恢复，联网重试；冲突保留并阻止后续依赖事件。
- v1/v2至v3的事务迁移、失败回滚/重跑、拒绝降级，WAL一致备份且不覆盖恢复目标。旧健康样本在迁移时记录首次本机可见快照；旧训练未知口径/完成/历史可见性保留，并可编辑、删除和撤销原始字段。
- 新训练JSON/CSV交换支持预览、实际导入、重复导入、来源修订与本地冲突；旧CSV继续兼容且负荷口径unknown。预览不打开数据库。
- 六大科学功能使用单一MetricResult。图表、周月报告和AI读取同一canonical结果；半开窗口、截止时间、单位、计数域、来源、参数及区间身份可审计。
- 删除固定状态减重百分比、次数裁剪、同日会话合并、组RPE冒充sRPE、inBed算睡眠、未来/晚到状态泄漏；统一负荷与e1RM公式语义。总负荷未知时不伪造总重或变化百分比。
- 候选冻结明确计划、器械步长、理论权限及验证任务。结果只核对对应会话/动作、候选创建后发生且预先声明的参考工作组；未执行/未知/冲突/旧组不能算成功。反馈使分析失效，历史分析不会清除之后的待重算事件。
- Source/Theory分库，实际原文哈希/版本/许可/定位、审核、修订和发布。已审版本不能覆盖；检索先查权限/适用性。LLM仅解释证据，默认离线，网络只发经过最小投影的汇总信息，数值/单位/窗口/版本/限制校验失败回退。

## 实际验证入口

```bash
.venv/bin/python -m pytest -q --junitxml=artifacts/verification/pytest.xml
.venv/bin/ruff check src app.py tests
.venv/bin/python tools/demo_v13.py --output artifacts/demo
.venv/bin/python -m healthzip.science calibrate --output .local/science-evaluation --seed 1300 --repetitions 300
.venv/bin/python -m healthzip.knowledge evaluate src/healthzip/knowledge/data/rag_eval_cases.json --with-synthetic-metrics
.venv/bin/python -m healthzip.knowledge evaluate src/healthzip/knowledge/data/rag_holdout.json --split source_family_holdout
```

真实Streamlit控件验收覆盖空库胸部模板→上斜史密斯单边30×10/RIR/停止原因→下次仍为草稿→候选缺项→32.5×8/双侧+5kg→反馈和周报，以及临时/自定义、替换/排序/条件维护、非法数值提示。独立Chromium 390×844验证断网刷新、丢失响应重试和两个完全相同真实组，见 `artifacts/verification/offline_browser.json`。

安装wheel到独立核心环境后验证46动作、77指标、43来源和20理论种子可用；CLI预览/往返/重复导入/周分析/备份恢复均实际运行。用户手册PDF已嵌入中文字体，检查文字提取和实际渲染。软件验证不代表所有手机/浏览器已测试，亦未运行真人健康数据验证。

## 研究结果与剩余限制

趋势独立噪声模拟名义95%区间覆盖96%，自相关场景降至56%，异方差场景89.33%。这些失败场景保留并阻止个人有效性声明；零残差不冒充零生理噪声。能量联合协方差示例模拟覆盖95%，只是所设生成器下的数学传播验证。B1有无合成状态信号两种场景均保留B0作为发布选择。

RAG公开开发集gold证据组召回14/67，固定来源家族留出0/8；可定位引用不等于语义受支持。独立人工语义裁决分母为0，专业问答语义验收未完成。留出集保持固定，不按其失误调参。语料/审核受限的清单及合法副本导入、逐源重试、理论新版本、人工标注和真人数据评测入口均已提供。

本版不包含原生App、账号云服务、视觉VBT、饮食打卡、模型微调或自动完整计划。无手表/无AI/断网可继续记录；缺可比语义、理论或个人校准时只显示事实与具体缺项。
