# v1.3 交付证据与剩余条件

审计时间：2026-11-11。逐项追踪见根目录 `requirements_traceability.csv`：77 个指标及13项操作需求，共90行，每行分别记录 implementation、software_verification、corpus_acquisition、theory_review、scientific_validation。`python tools/build_delivery_traceability.py` 依据实际验收结果、来源获取清单和理论审核清单重建；正文可访问、软件通过、主张审核和个人有效性没有互相替代。

## 五个维度的实际状态

| 维度 | 当前证据 | 仍未建立的结论 |
|---|---|---|
| implementation | 77 个指标均有具名执行器与统一 MetricResult；训练、迁移、来源与理论分库、词项检索、研究评测路径已实现 | 具名执行器不代表无条件产生个人数值；所需上下文、审核或校准不满足时返回缺口 |
| software_verification | `artifacts/science/acceptance-results.json` 记录178/178执行通过；训练XML及浏览器工件记录真实本地重放、冲突、断网刷新和丢响应重试；知识/AI工件记录37项通过 | 合成夹具不能证明真人效果、所有浏览器兼容或回答语义正确 |
| corpus_acquisition | 43来源均尝试；29科学来源已取身份元数据；14不同来源有获许可/明确允许内部使用的全文；173版本/1157片段完整性检查无失败 | 其他正文未取得或许可/身份待处理；14全文不代表43来源覆盖完成 |
| theory_review | 20张种子均有审计；11张仅明确绑定的选定主张经过AI辅助阅读审阅；9张草稿；审核内容和发布可冻结 | 不是独立专家审核；卡片其他主张、公式、适用域和个人行动没有自动获批 |
| scientific_validation | 趋势、能量、预测有可重跑模拟、参数登记、失败返回和校准工件 | 模拟仅为 `simulation_only`；获授权真人时间外验证、个人干预效果和独立语义审核尚未建立 |

知识和AI的37项测试记录位于 `artifacts/verification/knowledge-ai-tests.xml`。整仓最新总测试数由根目录状态文档及其实际日志给出；本文件不把各个可能重叠的测试批次加总为独立验证。

## 功能仍受哪些具体条件约束

肌群组数需要版本化且已审核的动作映射；e1RM需要显式公式版本、适用域和已知总负荷。停滞类推断需要重复测量设计、误差、实用等效范围、校准及重复查看预算。当前真实理论审核全部为 `explanation_only`，因此不能凭11张解释卡开放 STR-25/26 的数值候选权限；页面仍能记录、查看事实和说明缺失证据。

预测 B1 与区间必须有适用域匹配的校准；当前模拟发布选择保留B0。净储能、摄入变化和绝对摄入依赖有依据的基线、参数和组成假设；默认未知时不会用7700、固定设备误差或TEF比例补值。上述计算API和评测路径存在，不将条件未满足伪装成已验证输出。

AI本地解释使用完整计算结果。经用户同意外发时，canonical结果先转换为标量/计数/状态/窗口的最小投影，逐行记录、备注、来源记录ID与嵌套值不外发；外发摘要从该投影生成。模型返回的事实必须同时匹配同一条证据的数值、单位、窗口、方向及版本；更改主张或局限则回退本地。测试使用本地模拟响应，本次没有发送真实健康资料到模型服务。

## 文献与RAG的真实缺口

`artifacts/knowledge/source_audit.json` 按43来源记录身份、实际版本、许可、失败记录及重试命令。E2/E3/E4等免费可读页面尚无明确可索引授权；M2有许可线索但官方全文接口实际403；S4候选开放副本仍需核对；N1/N2/N3全文未取得。Apple文档条款对网络复制/自动获取的限制已记录，没有把可浏览等同于获准建正文库。获合法副本后可通过 `import-document` 保存授权与身份声明。

当前两个评测集结果如下；引用可定位只证明所引对象存在，不证明回答覆盖了问题或主张受到支持。

| 项目 | 公开开发集 | 固定来源家族留出 |
|---|---:|---:|
| 案例数/结构通过 | 30/30 | 8/8 |
| 引用可定位 | 47/47 | 12/12 |
| gold evidence groups召回 | 14/67 | 0/8 |
| gold groups已审核语料覆盖 | 27/67 | 0/8 |
| 路由命中 | 23/30 | 3/8 |
| 独立人工语义裁决分母 | 0 | 0 |

因此RAG语义验收未完成，不能写成“引用100%所以答案可靠”。留出案例在首次运行前冻结，来源家族与公开开发集分离，但仍由实现代理另行编写，不称外部盲测。固定SHA256为 `62b2e34ece6a655341aad0b6751b3d577f10955a85c9333f208615a2ef97ca62`；不能按其失误调参后继续称独立。人工标注需绑定确切输出SHA、审核者与理由；没有标注时语义分数保持空值。

## 可继续执行的入口

```bash
# 重试逐来源获取；不得绕过403或把未知许可标成允许
PYTHONPATH=src python -m healthzip.knowledge acquire --source M2 --fulltext
# 导入已合法取得且完成身份核对的副本
PYTHONPATH=src python -m healthzip.knowledge import-document declaration.json
# 已审理论修改必须生成新草稿版本，再审阅，不能覆盖旧审核
PYTHONPATH=src python -m healthzip.knowledge revise-theory revision.json
PYTHONPATH=src python -m healthzip.knowledge review reviewed-claim.json
# 保持评测配置与留出不变；通过annotations绑定真实人工审核
PYTHONPATH=src python -m healthzip.knowledge evaluate src/healthzip/knowledge/data/rag_eval_cases.json --with-synthetic-metrics --annotations annotations.json
PYTHONPATH=src python -m healthzip.knowledge evaluate src/healthzip/knowledge/data/rag_holdout.json --split source_family_holdout
PYTHONPATH=src pytest -q tests/unit/test_ai_client.py tests/unit/test_knowledge.py
python tools/build_delivery_traceability.py
```

PDF文本层页序、坐标与表格已有可执行合成文件验证；扫描PDF仍明确无OCR，真实复杂表格/单位需人工核对。知识备份应完整包含两份SQLite和原始blobs；受限原文不随Git审计文件公开分发。个人数据仍与公共来源库分开。
