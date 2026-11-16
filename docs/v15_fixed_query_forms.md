# 固定查询形式与成对检索评测

后续评测工具增加显式候选范围和Gold范围冻结，公开服务身份脱敏；省略范围仍为历史 `all`。使用页面的 `reviewed_metric` 路径须同时冻结范围版本和索引发布，详见 [范围及新增来源任务](v15_scoped_prospective_evaluation.md)。下文旧成绩和运行身份不修改。

`metric-hybrid-1.5.4` 增加显式 `query_form`：`zh`、`en`、`zh_synonym`。三种形式由独立静态文件 `src/healthzip/knowledge/data/query_forms_v15.json` 登记，覆盖原77项和两个明确隔离的来源观测扩展，以及指标解释/六功能任务。纯确定性指标仍跳过RAG。该文件是实现者AI编写的固定任务改写，不是科学主张、专家审定或已证明完全等价的翻译。

省略参数时，原来的任务中文标题、指标查询和全部别名仍按原顺序组合，原默认查询ID算法保留；原77项领域配置字节及哈希不改。选择形式时，只发送对应的固定任务标题和对应表达，不拼接其他形式或英文别名。调用者只能选择登记代码，不能传入任意查询文本。计算结果、备注、私人上下文从未插入检索查询。

```python
evidence = workbench.retrieve_for_metric(
    metric_id, analysis_task, computed_metric_result, context, release_id,
    mode="hybrid_rerank", query_form="en",
)
```

统一产品 `explain_metric` 服务也转发这一参数。检索审计记录形式、语言、表达类别、登记版本/哈希和实际固定查询UTF-8哈希；新形式有独立查询ID。Embedding适配器仍使用同一固定指令前缀，指令和适配实现也在评测实现哈希中，未改变文档索引或科学权限。

新索引发布冻结 `query_forms_sha256`；变更登记文件后旧发布拒绝使用已变化配置。历史发布没有该字段时，仍可使用原组合查询；需检索的任务若显式选择新增形式，历史发布会拒绝，不会默默获得新查询语义。产品中的纯账目跳过没有证据检索，也不需要模型或冻结索引。离线比较仍要固定所声明的发布身份，空冻结发布即可表达没有资料；不存在的发布不能充作评测身份。

## 同一Gold的成对运行

`tools/v15_run_retrieval_benchmark.py --query-forms zh en zh_synonym` 分别执行A–E及相同适用性/聚合预算的 `A_filtered`。每个形式使用相同Gold、发布、模型身份、候选预算、K和实现；不把中文变成开放式私人提问。Gold冻结回执必须明确固定查询登记哈希；包含来源观测扩展时还必须冻结观测配置。原77项执行器与来源观测执行器分别适配，不把扩展ID传给旧执行器。

每个形式保留独立的逐例结果、A–E评分、词项参考及耗时；总表 `query-forms-evaluation.json` 分别报告形式、语言、形式×领域和跨领域。每个指标都保留实际分母。中文原表达与中文同义表达归入同一语言时，是两次相关的查询实例；它们不会增加独立知识案例数。领域重叠同样不能相加当作总体题数。这里没有总体置信区间或自然语言问答泛化结论。

运行身份哈希覆盖全部知识Python/JSON，以及用于构造计算结果的科学Python/JSON；修复此前只冻结基础领域文件而漏掉扩展配置的问题。运行期间每次任务前重新校验实现/配置，变动即停止。完成的形式可按原身份及公开文件哈希继续组装成对报告；不改写已完成或失败的结果。旧运行目录不可用于新实现。离线消融仅改变语义适用性判断，权利和生命周期仍始终生效。

```bash
.venv/bin/python tools/v15_run_retrieval_benchmark.py \
  --root .local/v15/query-forms-snapshot-1 \
  --gold artifacts/v15/retrieval/benchmark-gold-3.json \
  --services-config .local/knowledge/model-services.json \
  --release-id v15-query-forms-corpus-1 \
  --private-output .local/v15/query-forms-run-1 \
  --public-output artifacts/v15/retrieval/query-forms-run-1 \
  --evaluation-purpose independent_test \
  --query-forms zh en zh_synonym
```

上面 `independent_test` 是运行用途标记，本身不能建立独立性。新Gold的实际创建、标注、排名暴露和来源选择范围，以及最终实跑结果，须结合冻结回执和本轮评测说明判断。历史Gold及已暴露案例的改写只能作开发材料；新指标任务也不自动成为新的来源家族留出。所有原文、模型原始答复、数据库、向量和配置凭据仍只在本地。

本次144次入口调用已完成，逐方法、形式、语言、领域及真实分母见 [前瞻任务结果](v15_query_forms_evaluation.md)。软件回归和实际运行输入一致性见 `artifacts/v15/verification/query-forms-final-input-integrity-1.json`；局部排名改善没有解决全部预期可答任务的证据充分性。
