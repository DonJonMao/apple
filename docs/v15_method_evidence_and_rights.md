# v1.5 方法依据与 JATS 用途权限修复

2026-11-17。检索实现 `metric-hybrid-1.5.6`；整体目标及严格独立质量验收仍未完成。原77项定义、计算、领域配置、私人schema及数值候选权限均未改变。

## 已核对的来源方法

新增4条AI辅助来源主张，原样复用1条既有主张，追加11条指标边。审核只涵盖完整原文中的测量身份和限制，不验证本产品算法、个体误差、诊断或训练效果。原文、受限改写、向量、审核包与两库备份仅本地保存；公开回执只含定位、哈希、范围和限制。

|指标|本轮追加|仍保留的边界|
|---|---|---|
|STR-12 / STR-13|S5外部负荷、固定负荷增加次数及固定重复区间增加负荷的方法身份；3个完整段落|研究的重复区间不等于完全同次数；个人差值由本地可比合同计算，不由试验授予因果、能力或进阶权限。|
|BODY-MASS-DAILY / TREND / RELATIVE|S5校准秤与独立体成分估计的身份、测试条件；2个完整段落。复用E1基线信息限制并追加2条应用边|不要求用户复刻禁食/限水协议，不认定当前秤、日代表值、趋势或摄入反推已获验证。|
|STATE-RHR|E7静息与运动心率的测量不确定性；2个完整段落|未绑定HealthKit每日静息心率协议或recovery领域，仍为insufficient_evidence。|
|STATE-FATIGUE / SORENESS / PAIN|R5已有问卷、回顾时窗及工具迁移限制；3个完整段落|只追加scope_limit；本产品自编条目、锚点与训练前采集协议仍缺依据，继续拒绝充分性解释。|

依据是 [S5，PeerJ 2022](https://doi.org/10.7717/peerj.14142)、[R5，BJSM 2016](https://doi.org/10.1136/bjsports-2015-094758)、[E7，Apple Watch测量系统综述](https://doi.org/10.1038/s41746-025-02238-1) 和 [E1，能量平衡与体重动态](https://doi.org/10.1016/S0140-6736(11)60812-X)。逐段ID、内容哈希、绑定和审核身份见 [审核回执](../artifacts/v15/knowledge/reviewed-method-boundaries-1.json)。这些是实现者AI阅读决定，不是独立专家审定。

[第三版静态覆盖矩阵](../artifacts/v15/knowledge/evidence-coverage-matrix-3.json)按原77项统计：24项确定性计算无需RAG；有部分或完整绑定的项目29→33；证据类型与领域静态齐备21→26。新增齐备项目是上述2项力量比较及3项体重描述。静态齐备仍需通过运行时上下文、许可、冻结成员、冲突、完整组和K预算检查；不能称作26项科学有效或RAG准确率。

对这5份主张/原文包另作排名不可见的模型语义阅读，5份均被标为`supported_with_stated_limits`，共17个语句分项。标注模型与生产精排相同，实现者选择有限原文池，仍没有独立专家、独立来源家族检索题或个人验证。首次解析因模型使用`supported`而非`entailed`标签中止；保留原响应，只接受该明确同义标签，不改变不支持/矛盾判断，复用4份已完成响应，仅提交此前未执行的第5包。见 [语义核对元数据](../artifacts/v15/knowledge/method-claim-semantic-audit-1.json)。这不是最终答案或整体检索质量验收。

## 旧 JATS 许可字段遗漏

旧JATS解析已正确识别部分组件的CC BY-NC / NC-SA / NC-ND许可，但没有新增PDF接入所用的可选`noncommercial_only`字段。旧检索只检查该布尔字段，因而可能在商业上下文中放入NC正文。

真实库、同一旧冻结发布`v15-reviewed-metric-scope-1`、同一wearable领域与合成商业上下文的无模型诊断，修前放入63个NC许可候选。E7具体片段同时通过初筛和返回前检查。此为实际权限缺陷的复现，不是合成来源或检索质量案例。

新`source-usage-scope-1.5.0`在运行时从结构化许可ID、候选许可及许可URL推导NC限制；缺省或错误的false字段不能覆盖NC条款。非本地非商业用途还必须有已识别的许可或显式较宽授权，只有本地text-mining许可的旧记录不能凭空获得商业范围。该检查用于主张资格、原文候选、精排前后复核及父上下文；既有组件级范围、来源状态和索引许可检查继续执行。被许可排除的主张也不能充当商业冲突证据或被依赖主张绕过。

旧冻结成员仍按当前许可有效性检查；不重写旧rights JSON、解析版本或冻结成员。不修改历史Gold、历史商业探针输出及评分。`query_id`兼容算法保留，每次审计另外记录检索实现及用途策略版本。

修后同一发布的候选3736→3673，NC许可候选63→0，E7片段在初筛和最终复核均被拒绝。见 [真实权限回执](../artifacts/v15/retrieval/jats-commercial-rights-fix-1.json)。默认本地非商业用途及明确获准的CC0、CC BY/SA/ND、联邦作者正文继续按各自原组件权限使用；本次修复不授予再分发或改编许可。

## 增量索引、历史与复现

S5和R5全文已在v1.4取得，但所用两个JATS版本此前没有v1.5检索单元。本轮注册70+80个单元，文件级归属保持provisional，仅逐段审核项追加content_checked；没有新来源身份或新下载。实际增量新增149项文档向量，当前文档缓存44785→44934；历史两套评测快照保持原身份和分母。首轮索引在提交8项向量后因进度回调参数错误中止，恢复复用这8项，再生成141项；失败日志与请求尝试哈希保留，未把失败运行说成通过。见 [索引元数据](../artifacts/v15/knowledge/existing-method-sources-index-1.json)。

[历史保护回执](../artifacts/v15/verification/historical-protection-method-rights-1.json)核对28张知识表的所有原有行、680份此前已提交工件、旧318份清单及原Gold-2冻结文件。没有覆盖旧声明、审核、来源原文、历史发布或私人健康库。

本地可复现命令（审核包/语料需已按许可在本机取得，新备份/输出路径必须未存在）：

```bash
.venv/bin/pytest -q tests/knowledge/test_v15_rights_usage.py
.venv/bin/python tools/v15_apply_reviewed_bindings.py --help
.venv/bin/pytest -q
.venv/bin/ruff check src app.py tests tools/v15_apply_reviewed_bindings.py tools/v15_run_retrieval_benchmark.py tools/v15_migrate_legacy_domains.py
```

5项非空合成计算结果通过真实统一解释入口，实际5次query embedding及5次精排请求，均以5个完整Span满足有限方法解释合同，未降级；私人解释仍本地，公共请求未包含合成私人标记。5个旧发布仍拒绝新增依据，5个未知上下文均拒绝；RHR和3项主观评分继续拒绝充分性解释。首次集成的混合重复次数夹具无法形成同次数STR-13计算结果，后续只修夹具；已完成STR-12模型响应原样复用，失败日志和完整响应保留。见 [方法集成回执](../artifacts/v15/retrieval/method-boundaries-integration-1.json)。

整仓1590项通过（499.09秒），Ruff通过，289份软件输入全程不变；实际集成实现与被测文件匹配。见 [软件回归](../artifacts/v15/verification/regression-method-rights-1.json) 和 [发布时输入核验](../artifacts/v15/verification/method-rights-final-input-integrity-1.json)。这些属于已知缺口修复与软件检查，新增独立检索案例0。整体WP-F、复杂资料核对、独立专业审定及真实校准仍按[目标验收清单](v15_goal_acceptance_audit.md)保留开放项。
