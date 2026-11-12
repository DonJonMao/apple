# 第五批后的语言解析开发记录

本轮在独立第五批冻结并完成评审后才使用题目开发。原独立评价为30题中8通过、15部分、7失败；题目、原输出、判断、判断回执和源包均未改。后续自动状态不作为新的独立语义得分。

变更仅涉及请求理解与来源识别：

- HC/HAC方法名称和回归背景跨句时保留同一方法对象，识别HC版本和小样本问题；不再将方法误差误标成个人误差界限。
- TOST支持与中文连写、单侧检验和区间越界表述；保留设计适用问题与数值计算请求的区别。
- 作者全名、姓氏和规范引用前缀来自已登记书目。只有作者引用句法才解析；同姓对应多个来源时仍保持歧义，版次/章节/分区限制继续执行。
- 显式来源中已审主张的一般健康目标帮助解释公共健康频次与个人最佳增肌频次之间的边界；不将最低频次提升为个人最佳值。
- 补齐肌力训练起步、相对增量、力竭定义、足够努力、特异性、跨器械负荷换算和个人因果解释的通用表达。
- 描述研究计划和询问界值依据不自动变成个人统计计算；实际请求个人界值、误判率、成功概率或训练数值仍单列未答。

开发前保存了30题的原目标解析及5个独立文件哈希，见 `language-round5-development-freeze.json`。另先运行新的语言回归夹具，初始24项中16失败、8通过，保留在 `language-round5-development-failing-before.xml`；随后添加两项一般方法解释的边界回归。夹具使用合成来源，只证明软件行为。

最终定向命令：

```bash
.venv/bin/pytest -q tests/unit/test_round5_question_language.py tests/unit/test_v14_question_language.py tests/unit/test_covariance_question_language.py tests/unit/test_v14_knowledge.py tests/unit/test_source_explanation_topics.py --junitxml=artifacts/v14/knowledge/language-round5-development-verification.xml
.venv/bin/ruff check src/healthzip/knowledge/tasks.py src/healthzip/knowledge/question_parts.py tests/unit/test_round5_question_language.py
```

347项通过，Ruff通过。没有运行整仓测试或提交。

源码于 `2026-11-12T01:42:28.615749+00:00` 冻结后，以自动路由、`corpus_roles=[core,research]` 和新发布 `core-detailed-source-explanations-1.4.10` 执行原30题开发查询。完整输出仅在 `.local/v14-knowledge-round5-development/language-1.4.10-outputs.raw.json`，SHA256为 `6bf52a5d5380b79c7e08ce50ae27b59d071e3909eef145f004d0d2ab9d0023e1`。公开回执为 `language-round5-development-replay-receipt.json`。

自动状态为24项 `answered_with_support`、1项 `missing_source_content`、5项 `partially_answered`；数值行动为0。这些状态不能证明答复要点完整或语义正确，须另做开发语义评审。1.4.10的正文修订由来源审核任务负责；本语言任务未写入来源主张、应用规则或发布版本。

剩余边界：四本教材目标正文仍缺；个人统计校准、误判率、唯一最优参数、跨器械个人公斤数和成功概率没有因此获得权限。来源作者引用仍依赖已登记书目信息；未知或歧义来源不会由词语相似度补全。
