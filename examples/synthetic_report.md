# Health ZIP Workbench 本地分析报告

生成时间：2026-11-04T15:57:34.706327+00:00

> 本报告仅整理和解释导入数据，不是医疗诊断，也不把缺失记录解释为没有佩戴、没有睡眠或没有进食。

## 数据盘点

|规范化类型|原始类型|样本数|有效日期|起始|结束|来源数|
|---|---|---:|---:|---|---|---:|
|active_energy_kcal|HKQuantityTypeIdentifierActiveEnergyBurned|45|45|2026-09-20|2026-11-03|1|
|body_mass_kg|HKQuantityTypeIdentifierBodyMass|45|45|2026-09-20|2026-11-03|1|
|dietary_carbohydrates_g|HKQuantityTypeIdentifierDietaryCarbohydrates|45|45|2026-09-20|2026-11-03|1|
|dietary_energy_kcal|HKQuantityTypeIdentifierDietaryEnergyConsumed|45|45|2026-09-20|2026-11-03|1|
|dietary_fat_g|HKQuantityTypeIdentifierDietaryFatTotal|45|45|2026-09-20|2026-11-03|1|
|dietary_protein_g|HKQuantityTypeIdentifierDietaryProtein|45|45|2026-09-20|2026-11-03|1|
|heart_rate_bpm|HKQuantityTypeIdentifierHeartRate|135|45|2026-09-20|2026-11-03|1|
|hrv_sdnn_ms|HKQuantityTypeIdentifierHeartRateVariabilitySDNN|23|23|2026-09-20|2026-11-03|1|
|menstrual_cramps|HKCategoryTypeIdentifierMenstrualCramps|2|2|2026-09-23|2026-10-21|1|
|menstrual_flow|HKCategoryTypeIdentifierMenstrualFlow|2|2|2026-09-23|2026-10-21|1|
|respiratory_rate_bpm|HKQuantityTypeIdentifierRespiratoryRate|45|45|2026-09-20|2026-11-03|1|
|resting_heart_rate_bpm|HKQuantityTypeIdentifierRestingHeartRate|46|45|2026-09-20|2026-11-03|1|
|sleep_stage|HKCategoryTypeIdentifierSleepAnalysis|135|46|2026-09-19|2026-11-03|1|
|sleeping_wrist_temperature_c|HKQuantityTypeIdentifierAppleSleepingWristTemperature|45|45|2026-09-20|2026-11-03|1|
|steps|HKQuantityTypeIdentifierStepCount|45|45|2026-09-20|2026-11-03|1|
|vo2_max_ml_kg_min|HKQuantityTypeIdentifierVO2Max|7|7|2026-09-20|2026-11-01|1|

## Evidence Cards

### 静息心率趋势
状态：`usable`
时间范围：2026-10-05 至 2026-11-03

最近 30 个日期有记录，中位数为 58.7 bpm。

事实：
- `resting_heart_rate_bpm`：60.218 bpm（样本/日期 30）
- `baseline_median`：58.697 bpm（样本/日期 30）
- `MAD`：1.221 bpm（样本/日期 —）
- `robust_z`：0.84 personal_deviation（样本/日期 —）
- `quartiles`：[57.3936119853794, 58.69718935294115, 59.65805838211382] bpm（样本/日期 —）

允许的下一步：continue_observation

### HRV-SDNN 基线
状态：`usable`
时间范围：2026-09-20 至 2026-11-03

最近 23 个日期有记录，中位数为 46.2 ms。

事实：
- `hrv_sdnn_ms`：49.48 ms（样本/日期 23）
- `baseline_median`：46.23 ms（样本/日期 23）
- `MAD`：2.567 ms（样本/日期 —）
- `robust_z`：0.854 personal_deviation（样本/日期 —）
- `quartiles`：[44.21412956059546, 46.23007485990163, 49.49426679985337] ms（样本/日期 —）

允许的下一步：continue_observation

### 睡眠时长与作息
状态：`usable`
时间范围：2026-09-19 至 2026-11-02

已记录 45 个夜晚，平均睡眠 4.3 小时。

事实：
- `sleep_nights`：45 nights（样本/日期 —）
- `sleep_hours_mean`：4.33 h（样本/日期 —）

限制：
- 缺失夜晚不代表零睡眠。
- 该模块不做临床睡眠诊断。

允许的下一步：review_sleep_window、continue_observation

### 训练频率与时长
状态：`usable`
时间范围：— 至 —

已记录 24 次训练，共 1038 分钟。

事实：
- `workout_sessions`：24 sessions（样本/日期 —）
- `weeks`：7 weeks（样本/日期 —）

限制：
- 不同运动类型不合并为无量纲健康分。
- WorkoutStatistics 是摘要，不等于逐秒心率序列。

允许的下一步：continue_observation

### 体重趋势
状态：`usable`
时间范围：2026-09-20 至 2026-11-03

已记录 45 个称重日期。稳健斜率约 -0.17 kg/周。

事实：
- `weight_days`：45 days（样本/日期 —）
- `weight_slope`：-0.17449340626908097 kg/week（样本/日期 —）

限制：
- 短期变化也可能包含水分、糖原、胃肠内容物和称量条件。
- 不能据此判断脂肪、肌肉或水分的具体变化。

允许的下一步：continue_observation

### 有氧适能（Apple 估计值）
状态：`usable`
时间范围：2026-09-20 至 2026-11-01

有 7 个估计点。

事实：
- `vo2_max`：40.05 mL/(kg·min)（样本/日期 7）

限制：
- 这是 Apple 的估计值，不是气体分析仪实测。
- 不能把相对值变化简单归因于减重。

允许的下一步：continue_observation

### 力量表现趋势
状态：`not_imported`
时间范围：— 至 —

尚未导入力量组记录。

事实：
- `exercise_conditions`：0 conditions（样本/日期 —）
- `usable_conditions`：0 conditions（样本/日期 —）

限制：
- 需要导入力​​量训练 CSV。

允许的下一步：continue_observation

### 营养记录与完整度
状态：`provisional`
时间范围：— 至 —

已记录 45 天，其中完整记录 0 天。

事实：
- `logged_days`：45 days（样本/日期 —）
- `complete_days`：0 days（样本/日期 —）
- `logged_energy_total`：101640.0 kcal（样本/日期 —）
- `logged_protein_total`：6795.0 g（样本/日期 —）

限制：
- 部分或未确认的日期只代表已记录部分，不能断言全天摄入不足。

允许的下一步：continue_observation

### 周期记录回顾
状态：`provisional`
时间范围：2026-09-23 至 2026-10-21

已记录 2 个出血事件日期。

事实：
- `observed_bleeding_events`：2 events（样本/日期 —）

限制：
- 一个周期只能做记录回顾；不确认排卵、避孕或医学状态。
- 缺少记录不等于没有月经。

允许的下一步：continue_observation

## 质量与缺口

- **resting_heart_rate**：`usable`；当前门槛已满足或可初步展示
- **hrv_sdnn**：`usable`；当前门槛已满足或可初步展示
- **sleep**：`usable`；当前门槛已满足或可初步展示
- **vo2_max**：`usable`；当前门槛已满足或可初步展示
- **body_mass**：`usable`；当前门槛已满足或可初步展示
- **workouts**：`usable`；当前门槛已满足或可初步展示
- **strength**：`not_imported`；需要导入更多同动作 / 器械记录
- **nutrition**：`not_imported`；请标记完整记录日；部分记录不能断言全天摄入不足

## 实施限制

- 所有计算在本机完成，未调用 AI API。
- 原始 Apple 健康数据保留来源、单位、时间和导入批次；派生结论带算法版本。
- 需要更多数据时只展示缺口，不生成强行结论。
