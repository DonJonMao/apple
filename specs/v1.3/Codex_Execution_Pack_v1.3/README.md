# HealthZIP v1.3 Codex 执行包

日期：2026-11-11。此包为完整开发规格和原创种子，不含实际产品代码修改或伪造的验证结果。

## 使用方式

在既有 DonJonMao/apple checkout 中打开本包，把 Codex_Goal_Prompt_v1.3.md 作为 Goal 指令；按 Development_Manual_v1.3.md 实施。先核对实际 HEAD 和 AGENTS，参考静态核查提交为49349e44df9abf9dbfb480dfef00a53fc224d8c9。

## 文件与状态

| 文件 | 用途 | 当前状态 |
| --- | --- | --- |
| Development_Manual_v1.3.md | 详细开发手册、公式、接口、迁移与验收 | 规范，不是代码完成证明 |
| Codex_Goal_Prompt_v1.3.md | 完整执行目标和完成判据 | 可直接使用 |
| metrics.json | 77项逐指标契约 | 待实现/验证 |
| metric_result.schema.json | 唯一运行时返回合同 | 需实现语义校验 |
| metric_definition.schema.json | 指标定义的最小结构 | 已检查字段完整 |
| parameter_registry.schema.json | 参数身份和来源合同 | 禁止无依据处方比例 |
| canonical_contract.md | 分册名称到统一合同的映射 | 优先适用 |
| sources.json | 43项来源身份与获取路径 | 真实状态逐项保留，非已抓语料 |
| theory_seed_cards.json | 核心理论卡草稿，独立于原文库 | 待证据定位及审阅 |
| knowledge_routes.json | 6功能路由、共享来源与边界 | 规范 |
| exercise_catalog_seed.json | 46项原创动作及分类/口径种子 | 肌群映射未审核，不可量化剂量 |
| rag_eval_cases.json | 30个正反/对抗开发回归案例 | 未运行真实RAG，不是留出集 |
| metric_acceptance_catalog.json | 178条指标验收描述 | 待实现为实际测试并执行 |
| requirements_traceability.csv | 功能与指标追踪模板 | 实施时补文件、测试及剩余缺口 |
| manifest.sha256 | 本包文件哈希 | 用于交接完整性 |

软件完成、软件测试、原文取得、理论审核和科学验证是五种独立状态。文献有链接不等于可合法批量取得全文；模拟通过不等于真人有效；RIR缺失不等于0；旧记录口径未知不能悄悄补默认值。数据不足时保留正常记录和描述，研究路径仍需完整可运行。

当前知识采集接口按2026-11-11官方文档核查；执行时再次做连通性与身份核对。不要继续使用已退役的PMC旧OA Web Service。

规格校验命令：`python validate_spec.py`。只核对本包结构与引用，不执行产品或科学验证。PDF已检查文字可提取、书签、页面边界并做渲染目视检查，记录见spec_validation.json。
