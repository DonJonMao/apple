# 第六批后的语言组合开发记录

本轮在第六批独立题目和实际输出冻结后使用其失败情形开发。原第六批12题及35个评分点、原输出与独立评分保持不变；本轮测试和后续回放只属于开发检查。第五批也未重新评分。开发前保存原第五、六批共15个冻结JSON文件的SHA256，见 `language-round6-development-freeze.json`。

本轮只修改 `knowledge/question_parts.py`、`knowledge/tasks.py`，新增 `tests/unit/test_round6_question_composition.py`；未修改来源主张、发布清单、定义文件、旧测试期望或 `retrieval.py`。

- 保留复合问题中彼此独立的解释要求。询问每组是否必须力竭时，明确的保留重复数、RIR或足够努力表述仍要求余力精度解释，不能被力竭必要性吞掉。
- 统计方法背景中的个人重复观察或前后分段比较，若同时询问实质变化和框架适用，要求实用等效及研究设计范围说明。仅保存记录或查看前后标签不会产生统计任务。
- 协方差区间用于个人平台期判断时，保留现有的实用等效与设计前提。单问HC3等估计方法的有限样本效度，不凭个人序列字样额外索取未问的等效方法。
- 有氧/身体活动的逐步增加顺序与抗阻重量或重复次数的进阶分开；“循序渐进”不再仅因含“渐进”就误派抗阻加重任务。
- 同句询问等效界值与TOST支持等效的判据时保留两个任务，同时识别“怎样确定”“怎么定”等界值依据关系。
- 新增三个通用结构化任务：`resistance_training/training_modality_adherence/explanation`、`physical_activity/aerobic_activity_volume/explanation`、`physical_activity/activity_type_complementarity/explanation`。识别依赖领域对象和请求关系，不使用题号、完整题句或指定来源ID；没有符合来源、范围及关系要求的已审主张时，不将任务标为完整回答。
- 明确请求个人精确RIR、跑步速度或时长时仍单列个人参数未答项，不生成数值行动。一般指南频次与个人最优目标之间的推论问题保留一般解释路径。

最初30个新反例为24失败、6通过，保存于 `language-round6-development-failing-before.xml`。追加的2个界值/TOST组合反例为1失败、1通过，保存于 `language-round6-compound-method-failing-before.xml`。第一次广泛回归发现1项已有一般指南目标解释被误标为个人参数请求，保留于 `language-round6-development-initial-regression.xml`；未修改旧测试，收紧明确数值动作识别后，321项定向测试通过。

最终执行全部21个直接引入 `healthzip.knowledge` 的单元和集成测试文件，504项通过、0失败，耗时188.90秒。证据为 `language-round6-development-verification.xml`；修改代码及新增测试的Ruff检查通过。代码于 `2026-11-12T02:41:43.491591+00:00` 冻结，哈希与验证信息见 `language-round6-code-freeze.json`。

新来源说明与1.4.12发布由另一任务负责。待准确发布身份核验后，使用原12题、自动路由、`corpus_roles=[core,research]` 执行一次独占新建的开发回放；数据库以SQLite只读模式打开，并核验代码、数据定义、发布身份、原15个冻结文件及数据库在查询前后不变。原始输出保留在 `.local`，公开回执只保存元数据；另行语义复核不能替换原独立评分。
