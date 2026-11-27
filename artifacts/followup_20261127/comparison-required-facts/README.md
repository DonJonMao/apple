# 周期比较仅派生实际使用的事实

这是一项次级性能修复，不代表 R06 冷报告预算通过。原 10 万／100 万记录压力夹具、旧结果与用户数据均未修改。

## 修改边界

`src/healthzip/science/reports.py` 仍先对完整原始记录执行 as-of 修订解析，再按各比较范围取记录。RHR、SDNN 和睡眠比较复用原有日代表值定义；不再为三个比较范围生成随后丢弃的能量日、体重和症状事实。完整报告的 `derive_report_context` 仍生成全部原有领域；统计方法、来源身份和输出契约保持。

64cdd53 固定源码的诊断 profile 中，四次 `report_comparison` 累计 3.780 秒，其中十二次完整事实派生累计 2.867 秒。这只是当前候选的插桩耗时上界，不是可宣称的完整报告节省量。

## 软件证据

- `before.txt` / `before.xml`：首次新增夹具把前期记录放在 elapsed-time 对照范围外，独立期望值断言失败。保留此试验；它不作为产品缺陷证据。
- `before-r2.txt` / `before-r2.xml`：调整夹具日期后，独立 RHR／SDNN／睡眠数值和来源断言通过，修复前仍执行三次无关能量派生，按预期失败。
- `after.txt` / `after.xml`：十五项比较测试通过，包括原算法 oracle、跨类型更正、删除、冲突、未来事件、晚到修订、缺失 ID、未知可见性、夏令时和跨夜睡眠、七十七项指标等价；新增用例还验证完整报告中的体重、症状及完整能量日不丢失。
- `related.txt` / `related.xml`：相关测试共 187 项通过。
- `ruff-r2.txt`：修改源码、测试及测量脚本 Ruff 通过。

相关测试命令：

```sh
.venv/bin/pytest tests/science/test_followup_report_comparison_preparation.py tests/science/test_state_energy_prediction.py tests/science/test_energy_interval_scaling.py tests/science/test_metric_acceptance.py tests/science/test_health_fact_comparisons.py tests/science/test_v14_sleep_context_time.py -q --junitxml=artifacts/followup_20261127/comparison-required-facts/related.xml
```

## 单阶段配对测量

`measure_phase.py` 使用确定性纯内存合成数据：13,465 条记录，含 3,360 条能量、105 条生理／睡眠及 10,000 条未知条件普通训练身份。不访问数据库，不替代原压力夹具，也不运行完整报告。

旧／新交替运行三对，阶段中位耗时为 **0.7018 秒／0.2845 秒**；六次完整输出 SHA256 相同，输入 SHA256 未变。样本、源码身份、共享机器负载和进程峰值内存见 `phase-measurement.json`。这里的三次中位数不是 P95、冷打开或完整报告耗时。

```sh
.venv/bin/python artifacts/followup_20261127/comparison-required-facts/measure_phase.py --before-source /home/sn_maozhifang/healthzip-followup-validation-tmp/source-64cdd53-profile-r1/src/healthzip/science/reports.py --output artifacts/followup_20261127/comparison-required-facts/phase-measurement.json
```

修改后 reports.py 的 SHA256 为 `4f02bfccbd58ca1addfe2fdf15fab9e0b8276089736d558838cf7c017e1f07b0`；原固定源码为 `8d91102953847ce0438a7987c2e5b3b1827b6196fd308ea7217b7b8385237123`。此工件不声明最终整库回归或真实页面验收；后续整合由根代理记录。
