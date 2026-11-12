# 第五批后的边界修复开发记录

本记录接续语言开发阶段，不替换独立第五批评测或第一次开发评审。独立结果仍为8通过、15部分、7失败；1.4.10开发评审仍为26通过、4部分、0失败。两者均不因本轮新输出而改分。

本轮修改三个知识代码文件，并新增 `tests/unit/test_round5_method_boundaries.py`：

- 恢复中文“替我”和英文“give me”等直接委托动作的识别。整仓验证发现两项既有个人统计边界回归：请求判定个人停滞并给出概率，不能由一般方法说明满足。旧测试及其期望均未修改；一般“请解释如何选择等效界值”仍是方法解释。
- 当问题同时涉及协方差方法、个人重复记录、平台期和判定时，补充实用等效及研究设计适用性的解释要求。来源筛选仍逐项执行；显式限定单一来源不会获得另一来源的解释，个人统计计算仍保持未答且不生成数值行动。
- 指定教材正文缺失时，说明继续核对需要合法取得与所问版次、章节相符的相关正文，先核实书目与原文定位，再审主张；其他文献仍不能替代该正文或提供其页码。

先运行7项新增边界测试及既有来源范围测试，初始结果为6失败、14通过，保存于 `language-round5-boundary-failing-before.xml`。修复后20项通过。随后运行全部19个直接引入 `healthzip.knowledge` 的单元及集成测试文件，共466项通过、0失败，保存于 `language-round5-boundary-verification.xml`；三个修改代码文件及新增边界测试的Ruff检查通过。整仓失败记录由主任务另存于 `round5-full-suite-before-boundary-fix.xml`，最终整仓与发布包验证由主任务负责。

源码于 `2026-11-12T01:56:21.151482+00:00` 冻结后，以自动路由、`corpus_roles=[core,research]` 和发布 `core-boundary-source-explanations-1.4.11` 执行原30题的新开发查询。发布SHA256为 `5ab38c83ef77ebfcd5f4dee2521e5913df7f4fd0ad66b94fecc425cdf8656b5b`；本任务未改来源主张、应用规则或发布清单。

新完整输出仅在 `.local/v14-knowledge-round5-development/language-1.4.11-outputs.raw.json`，SHA256为 `b33e050723df76c52927906db1798e3b3009be4d90c5f2ca1369c6efb7f740e7`。公开回执为 `language-round5-boundary-replay-receipt.json`，含源码及原独立文件的哈希。原5个独立文件在执行前后完全一致；第一次开发输出的SHA256仍为 `6bf52a5d5380b79c7e08ce50ae27b59d071e3909eef145f004d0d2ab9d0023e1`，亦未覆盖。

新输出的自动状态仍为24项 `answered_with_support`、1项 `missing_source_content`、5项 `partially_answered`，数值行动为0。这仅记录软件行为，不能证明语义要点完整；第二次开发逐点评审由另一任务另存。缺失教材正文、个人统计校准、误判率、唯一最优参数、跨器械个人公斤数与成功概率仍没有新增推断权限。
