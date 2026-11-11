# 使用顺序

1. 阅读Apple_v1.4_Revision_Plan_912aefc.md。
2. 将Codex_Goal_Prompt_v1.4.md作为实施Goal正文，并提供本包。
3. verified_findings.json是13项已复现缺陷；metric_revision_matrix.json是77指标的变更合同。
4. catalog_plan.md、core_knowledge_plan.md为可独立分工的详细章节。
5. evidence只含合成复现/软件日志。没有私人健康数据、真实教材正文、wger完整媒体或生产批准记录。

复现脚本固定于审查时工作区，部分路径需换成实施机器路径。以仓库虚拟环境运行，设置PYTHONPATH=src；先读取脚本，不把其synthetic批准复制到生产。evidence/state脚本会生成合成ZIP/SQLite；evidence/knowledge会创建隔离测试库；不在真实个人库运行。审查过程中未修改或推送仓库。

方案中的拟新增CLI、Schema与字段是待实现接口，不表示当前版本已存在。核心教材仅核对书目/目录的条目不能当作已读正文。所有数量/测试结果绑定2026-11-11及912aefc提交。
