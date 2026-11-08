# Apple Health ZIP 离线整理与分析工具 — 开发设计说明书

**项目代号：** Health ZIP Workbench  
**版本：** 1.0  
**目标平台：** macOS / Windows 桌面电脑，本地运行  
**当前阶段：** 先完成 Apple Health 导出 ZIP 的解析、整理、分析与可视化；暂不接入 HealthKit，不开发 iPhone / watchOS App。

---

## 0. 本文件与原始产品设计 PDF 的关系

本项目包内的 `reference_product_design_v1.0.pdf` 是此前形成的 31 页《Apple Watch 训练与身体状态解释 App 开发设计说明书》。它定义了长期产品方向、HealthKit 数据字典、男性 / 女性功能路由、分析方法与安全边界。

**本次电脑端原型只实现其中的数据导入之后的工作流。** 不要在本阶段实现 HealthKit 权限、iOS 工程、Watch 实时采集、后台同步、账号系统或云端服务。原 PDF 中凡是涉及 iOS / HealthKit 的内容，只作为未来数据来源和字段语义参考。

### 当前阶段的产品目标

让用户把 iPhone「健康」App 导出的 ZIP 文件导入电脑，在本地完成：

1. ZIP 内容检查和数据类型盘点。
2. 大型 `export.xml` 的流式解析。
3. 统一字段、单位、时间、来源与存储格式。
4. 数据质量 / 覆盖度 / 缺失情况检查。
5. 心率、HRV、睡眠、运动、体重、有氧适能等分析。
6. 额外导入力量训练、饮食和主观记录 CSV。
7. 根据实际可用数据启用相应功能；不足时明确告诉用户缺什么。
8. 在本地页面展示图表、结论、证据和限制。
9. 可选生成 Markdown / HTML 报告；AI API 不属于 MVP 必需依赖。

**成功标准不是页面漂亮，而是：导入真实 ZIP 后，用户能看到可信的数据盘点、可复算的分析结果，以及明确的数据不足提示。**

---

## 1. 范围、非目标与产品原则

### 1.1 本阶段必须做

- 本地桌面运行，无账号、无云数据库。
- 输入 Apple Health 导出 ZIP；默认不要求用户手工解压。
- 对大型 XML 使用流式解析，不能把整个 XML 一次性载入内存。
- SQLite 持久化导入批次、原始样本、训练会话、派生指标与分析结果。
- 可重复导入；同一个 ZIP 和不同 ZIP 中重叠的样本不能无限重复计数。
- 提供数据质量报告，区分「没有数据」「未记录」「文件中没有」「当前无法判断」。
- 支持力量训练 CSV、营养 CSV、体重 / 围度 CSV 和主观状态 CSV。
- 支持男性 / 不启用周期用户的通用功能，以及女性周期数据的可选分析。
- 所有核心分析必须由确定性代码完成，不依赖 LLM。
- 提供自动化测试、合成测试数据、安装说明和开发文档。

### 1.2 本阶段明确不做

- 不直接读取 Apple Health / HealthKit；桌面端不能直接访问 iPhone 的 HealthKit 数据库。
- 不开发 iOS、watchOS 原生 App，不做实时心率或运动中提示。
- 不做账号、登录、云端同步、多人数据平台。
- 不把原始 ZIP、完整健康记录或经期数据上传到第三方 API。
- 不做疾病诊断、医学风险概率、避孕 / 排卵判断。
- 不声称通过 HRV 测量局部肌肉损伤、肌肉蛋白合成或真实增肌量。
- 不通过心率推算基础代谢变化，不把 VO₂ max 变化简单归因为减重贡献百分比。
- 不生成未经验证的 0–100 恢复分、增肌分、代谢分或自动训练容量处方。

### 1.3 设计原则

1. **数据来源可追溯**：每条记录保留 source、device、时间、单位和导入批次。
2. **原始数据与派生数据分离**：不覆盖原始记录；分析结果带算法版本。
3. **缺失不是零**：没有饮食记录不等于 0 kcal；没有睡眠记录不等于 0 小时；没有经期记录不等于没有月经。
4. **先做个人内比较**：不随意用大众均值评价个体。
5. **可比条件优先**：不同运动类型、速度、坡度、器械、动作规范不强行比较。
6. **不把相关性写成因果**：可以说「同时出现」「与……相关」，不能说「60% 进步由减重造成」。
7. **质量门槛按功能独立判断**：一个数据源不足，不应该让整个 App 都不可用。
8. **隐私本地优先**：默认只在本机处理，不联网、不自动遥测。

---

## 2. 用户流程与最小交互

### 2.1 主流程

```text
启动本地应用
  → 选择 Apple Health ZIP 文件路径
  → 检查 ZIP 安全性与结构
  → 预扫描：显示文件大小、XML 路径、可识别记录类型
  → 用户确认导入范围（默认核心数据；周期数据可单独启用）
  → 流式解析 XML 并分批写入 SQLite
  → 导入完成：显示记录数、未知类型、错误数、时间跨度
  → 运行数据质量检查
  → 展示每项功能的可用状态
  → 查看趋势 / 图表 / 解释卡
  → 导入力量训练 / 饮食 CSV（可选）
  → 生成本地周报 / 导出报告
```

### 2.2 页面只需够用

使用 Streamlit 做本地 Web UI，浏览器访问 `http://localhost`。不需要视觉设计稿，不需要响应式移动端适配。

- **导入页**：输入 ZIP 本地路径；检查结构；显示导入进度、记录数和错误。
- **数据总览**：每类数据的覆盖跨度、有效天数、最近记录日期、来源设备。
- **数据质量**：逐项显示 `可分析 / 初步 / 数据不足 / 未导入`，展示缺失原因。
- **心率与恢复**：RHR、HRV-SDNN、运动心率、心率恢复（有样本才显示）。
- **睡眠**：睡眠时长、入睡 / 醒来时间、有效夜数；不做临床睡眠诊断。
- **训练**：Workout 次数、类型、时长、距离、心率；另有力量组日志页。
- **体重与营养**：体重趋势、已记录营养、饮食完整度。
- **女性周期（自选）**：仅在导入时启用并确有数据时展示；默认不展示生殖敏感数据。
- **报告**：按可用数据生成结论、证据、限制和数据缺口。

### 2.3 大文件导入交互

MVP 优先使用本地文件路径输入，而不是 Streamlit `file_uploader` 把大型 ZIP 全部读入内存。用户复制文件路径即可。可后续增加系统文件选择器，但不能为了文件选择器破坏流式读取。

---

## 3. 技术选型与工程结构

### 3.1 推荐技术栈

| 层 | 技术 | 选择理由 |
|---|---|---|
| 语言 | Python 3.12（允许 3.11+） | 本地数据处理、分析和快速迭代 |
| XML / ZIP | Python `zipfile` + `lxml.etree.iterparse` | 从 ZIP 内部流式读取 XML，不必先完整解压 |
| 数据库存储 | SQLite（Python 标准库 `sqlite3`） | 单机、无需服务、易备份和迁移 |
| 数据处理 | Polars | 高效列式处理；仅在分析层转 DataFrame，不在解析时堆积所有记录 |
| 图表 | Plotly | 时间序列与交互图表 |
| UI | Streamlit | 快速本地可视化，不需要精美前端 |
| CLI | Typer | 可从命令行执行导入、分析、导出 |
| 数据验证 | Pydantic（仅用于边界输入） | CSV / 配置校验；不要把所有数据库行都转成重对象 |
| 测试 | pytest | 单元、集成、回归测试 |
| 代码质量 | Ruff | lint + format |
| 环境与锁定 | `uv` + `pyproject.toml` + lockfile | 可复现安装 |

**不要同时引入 Pandas、Polars、DuckDB、Spark 等多个分析栈。** 首版 SQLite 保存数据，Polars 做分析即可。除非真实数据规模测试证明 SQLite 不够，再单独评估 DuckDB。

### 3.2 建议目录结构

```text
health-zip-workbench/
├── app.py                       # Streamlit 入口
├── pyproject.toml
├── uv.lock
├── README.md
├── AGENTS.md                    # Codex 项目约束与开发规范
├── src/healthzip/
│   ├── cli.py                   # Typer CLI
│   ├── config.py
│   ├── importers/
│   │   ├── apple_zip.py         # ZIP 安全检查、查找 export.xml
│   │   ├── apple_xml.py         # 流式 XML 解析
│   │   ├── strength_csv.py
│   │   ├── nutrition_csv.py
│   │   └── measurements_csv.py
│   ├── normalize/
│   │   ├── types.py             # HealthKit type → canonical type
│   │   ├── units.py
│   │   └── timestamps.py
│   ├── db/
│   │   ├── schema.sql
│   │   ├── repository.py
│   │   └── migrations.py
│   ├── quality/
│   │   ├── inventory.py
│   │   ├── coverage.py
│   │   └── readiness.py
│   ├── analytics/
│   │   ├── baselines.py
│   │   ├── heart.py
│   │   ├── sleep.py
│   │   ├── workouts.py
│   │   ├── weight.py
│   │   ├── strength.py
│   │   ├── nutrition.py
│   │   ├── cycle.py
│   │   └── insights.py
│   ├── reporting/
│   │   ├── markdown_report.py
│   │   └── export.py
│   └── ui/
│       ├── pages/
│       └── components/
├── templates/
│   ├── strength_sets_template.csv
│   ├── nutrition_daily_template.csv
│   ├── body_measurements_template.csv
│   └── subjective_log_template.csv
├── tests/
│   ├── fixtures/
│   ├── unit/
│   └── integration/
└── data/                         # gitignored: 本地数据库和导入缓存
```

如果 Codex 检查后发现已有项目结构，应优先适配现有仓库，不要机械重建或覆盖用户已有代码。

---

## 4. Apple Health ZIP 格式与解析要求

### 4.1 导出包结构

Apple Health 导出 ZIP 通常包含 `apple_health_export/export.xml`，也可能有 `workout-routes/` 等附件；文件夹名称和附件存在性不能写死。解析器应扫描 ZIP 成员，寻找 XML 根节点为 `HealthData` 的导出文件，并在导入报告中显示实际识别到的路径。

### 4.2 必须支持的 XML 节点

| XML 节点 | 处理要求 |
|---|---|
| `HealthData` | 根节点，读取 locale 等导出级元信息 |
| `ExportDate` | 保存导出时间，报告标注数据快照时间 |
| `Me` | 只读取完成必要分析所需的有限字段；不要默认显示生日等身份信息 |
| `Record` | 主要数据记录；读取 type、value、unit、startDate、endDate、creationDate、sourceName、sourceVersion、device、metadata |
| `Workout` | 读取 workoutActivityType、startDate、endDate、duration、totalDistance、totalEnergyBurned、sourceName、device、metadata |
| `WorkoutStatistics` | 作为 workout 子项读取 type、average、maximum、minimum、sum、unit、时间范围；不把它误认为逐秒心率序列 |
| `WorkoutEvent` | 保存暂停 / 恢复 / 分段等事件（如存在） |
| `ActivitySummary` | 读取每日活动摘要；与逐条 activeEnergy 记录分开保存，不能重复求和 |
| `Correlation` | 首版可登记类型和数量，按明确白名单解析；未知结构安全跳过 |
| `ClinicalRecord`、`Electrocardiogram` 等 | 首版不导入临床正文 / ECG 波形；只在类型盘点中显示已跳过的数量，避免无必要收集敏感信息 |

XML 里出现未知节点或新类型时，不能导致整个导入失败。必须记录 `unknown_type_counts` 和样本示例（脱敏后），并继续处理已支持节点。

### 4.3 重点 HealthKit 类型映射

使用原始 HealthKit 类型标识作为输入，不依赖中文显示名。以下为首版白名单，实际 XML 类型应以真实导出为准。

| 分组 | XML 类型标识 | 规范化名称 / 单位 |
|---|---|---|
| 心率 | `HKQuantityTypeIdentifierHeartRate` | `heart_rate_bpm` / count/min |
| 静息心率 | `HKQuantityTypeIdentifierRestingHeartRate` | `resting_heart_rate_bpm` / count/min |
| HRV | `HKQuantityTypeIdentifierHeartRateVariabilitySDNN` | `hrv_sdnn_ms` / ms |
| 心率恢复 | `HKQuantityTypeIdentifierHeartRateRecoveryOneMinute` | `heart_rate_recovery_1m` / 保留导出单位与原值 |
| VO₂ max | `HKQuantityTypeIdentifierVO2Max` | `vo2_max_ml_kg_min` / mL/(kg·min) |
| 呼吸频率 | `HKQuantityTypeIdentifierRespiratoryRate` | `respiratory_rate_bpm` |
| 血氧 | `HKQuantityTypeIdentifierOxygenSaturation` | `oxygen_saturation_fraction`，展示时转百分数 |
| 睡眠腕温 | `HKQuantityTypeIdentifierAppleSleepingWristTemperature` | `sleeping_wrist_temperature_c` / °C |
| 睡眠 | `HKCategoryTypeIdentifierSleepAnalysis` | `sleep_stage` / category + interval |
| 训练 | `Workout` 节点 | `workout_session` |
| 步数 | `HKQuantityTypeIdentifierStepCount` | `steps` / count |
| 活动能量 | `HKQuantityTypeIdentifierActiveEnergyBurned` | `active_energy_kcal` / kcal |
| 静息能量 | `HKQuantityTypeIdentifierBasalEnergyBurned` | `basal_energy_kcal` / kcal |
| 运动时间 | `HKQuantityTypeIdentifierAppleExerciseTime` | `exercise_minutes` / min |
| 距离 | `HKQuantityTypeIdentifierDistanceWalkingRunning`、`HKQuantityTypeIdentifierDistanceCycling` | 分别保存，不混合 |
| 体重 | `HKQuantityTypeIdentifierBodyMass` | `body_mass_kg` / kg |
| 身高 | `HKQuantityTypeIdentifierHeight` | `height_cm` / cm |
| 体脂 / 瘦体重 | `HKQuantityTypeIdentifierBodyFatPercentage`、`HKQuantityTypeIdentifierLeanBodyMass` | 可选；保留测量设备和方法 |
| 饮食 | `HKQuantityTypeIdentifierDietaryEnergyConsumed`、`DietaryProtein`、`DietaryCarbohydrates`、`DietaryFatTotal`、`DietaryWater`、`DietaryCaffeine` | 营养样本；不要假定存在完整食物 / 餐次明细 |
| 女性周期 | `HKCategoryTypeIdentifierMenstrualFlow`、`IntermenstrualBleeding`、`CervicalMucusQuality`、`OvulationTestResult`、相关症状类型 | 仅在用户主动启用时解析；不自动推断排卵或避孕 |

**重要：** RMSSD、围绝经状态、心率分区等类型在不同系统版本 / 导出中可能不存在。解析器采用“识别到什么就记录什么”的能力探测方式，不得为了和原 PDF 字段表一致而伪造数据。

### 4.4 时间与单位

- 解析 Apple 时间字符串中的 UTC offset；保存 `timestamp_utc`、`local_datetime`、`utc_offset_minutes` 和 `local_date`。
- 不要把所有日期先转成 UTC 日期再按天聚合，否则跨时区和午夜数据会错位。
- 原始 `unit` 与 `value` 必须保留；规范化单位另存。
- 单位转换需有明确映射和测试：kg / lb、cm / m、kcal / kJ、秒 / 分钟、count/min、ms、°C 等。
- 无法识别单位时保留原值、标记 `unit_status=unknown`，不要静默转换。

### 4.5 大文件与安全

- 用 `zipfile.ZipFile.open(member)` 获取 ZIP 内 XML 的文件流。
- 使用 `lxml.etree.iterparse` 或等效安全的增量解析器；禁止 `ET.parse()` / `read()` 一次性读取完整 XML。
- XML parser 必须禁用 DTD、外部实体、网络访问；不允许解析外部实体。
- 解析完成一个 `Record` / `Workout` 后立即清理 XML element 和前置兄弟节点，控制内存。
- ZIP 安全检查：成员数量上限、单成员解压大小上限、总解压大小上限、压缩比上限；拒绝绝对路径、`..` 路径和符号链接式危险路径。
- 默认不把整个 ZIP 解压到磁盘；不执行 ZIP 内任何文件。
- 对损坏 XML：报告行 / 节点附近可用信息，保留已成功提交的批次状态为 `partial_failed`，不谎称完整导入。
- 每批事务提交；导入中断后可删除未完成批次或从头重跑，不能留下半写入的有效 anchor 状态。

---

## 5. 统一数据模型与存储

### 5.1 核心表

建议使用 SQLite，表结构至少包含：

**`import_batch`**
- `id`、`file_sha256`、`file_name`、`file_size_bytes`、`exported_at`、`imported_at`
- `status`：`running / completed / partial_failed / failed`
- `xml_member_path`、`records_seen`、`records_inserted`、`records_deduplicated`、`records_skipped`、`errors_count`
- `date_min`、`date_max`、`unknown_type_counts_json`

**`health_sample`**
- `id`（内部主键）、`fingerprint`（唯一索引）、`import_batch_id`
- `raw_type`、`canonical_type`、`raw_value`、`raw_unit`、`normalized_value`、`normalized_unit`
- `start_utc`、`end_utc`、`creation_utc`、`local_date`、`utc_offset_minutes`
- `source_name`、`source_version`、`device`、`metadata_json`
- `quality_flags_json`、`created_at`

**`workout`**
- `id`、`fingerprint`、`import_batch_id`、`activity_type`
- `start_utc`、`end_utc`、`duration_seconds`
- `distance_value`、`distance_unit`、`energy_value`、`energy_unit`
- `source_name`、`source_version`、`device`、`metadata_json`

**`workout_statistic`**
- `workout_id`、`raw_type`、`statistic_start`、`statistic_end`
- `average_value`、`minimum_value`、`maximum_value`、`sum_value`、`unit`

**`strength_session` / `strength_set`**
- session：时间、名称、来源、备注、导入批次
- set：动作 ID / 名称、器械、变式、左右侧、组序号、重量 kg、次数、RIR、RPE、热身标记、动作标准标签

**`nutrition_day` / `nutrition_entry`**
- 日汇总：日期、kcal、蛋白、碳水、脂肪、完整性状态 `complete / partial / unknown`
- 可选餐次：时间、名称、食物、份量、营养值和来源

**`body_measurement` / `subjective_log` / `cycle_event`**
- 体重、身高、体脂、围度；主观疲劳 / 酸痛 / 睡眠感受；周期出血与症状。
- `cycle_event` 仅在用户主动启用周期功能时导入或录入。

**`daily_feature` / `insight`**
- 派生指标必须记录算法版本、时间窗口、样本数、质量状态和计算时间。
- Insight 必须包含 `facts`、`limitations`、`source_feature_ids`、`allowed_actions`，可以从结论回溯到原始样本。

### 5.2 去重

1. 同一个 ZIP：用 SHA-256 识别完全相同文件，提示「已导入过」，允许用户选择跳过或重新校验。
2. 不同 ZIP 有重叠历史：为 `Record` 生成稳定 fingerprint，至少包括 `raw_type + startDate + endDate + value + unit + sourceName + device`；规范化日期字符串，避免无意义格式差异。
3. 不同 source 的同时间同数值样本不能自动删除；保留来源，交给质量层判断是否为疑似重复。
4. Workout 使用独立 fingerprint；相同运动可能由 Watch 和第三方 App 重复写入，默认标记 `possible_duplicate`，不要未经用户确认就删除。
5. 每次导入保留 batch 关联；删除某个 batch 时必须先确认样本是否还被其他 batch 引用。

### 5.3 性能

- XML 解析器按 1,000–10,000 条样本批量写 SQLite，批量大小可配置。
- `health_sample` 对 `(canonical_type, start_utc)`、`local_date`、`source_name` 建索引。
- UI 查询使用聚合 SQL / Polars，不把数百万原始行传给 Streamlit。
- 图表默认展示日 / 周聚合；用户需要时再钻取原始样本。
- 对 1GB 级 XML 不承诺固定耗时，但测试应验证峰值内存近似有界，而不是随已解析样本数线性增长。

---

## 6. 外部 CSV 模板

### 6.1 力量训练 `strength_sets_template.csv`

字段：

```csv
session_id,datetime,exercise,exercise_variant,equipment,side,set_number,weight_kg,reps,rir,rpe,is_warmup,range_of_motion,notes
s001,2026-10-01T18:30:00+08:00,Barbell Bench Press,Paused,Barbell,bilateral,1,60,8,2,8,false,full,
s001,2026-10-01T18:33:00+08:00,Barbell Bench Press,Paused,Barbell,bilateral,2,60,8,2,8,false,full,
```

- `weight_kg` 必须可解析为数字；支持导入时指定原始单位 lb 并统一转 kg。
- `rir` / `rpe` 可空；不能互相自动换算成精确值。
- `is_warmup` 必须解析布尔值；热身组不计入工作组统计。
- 同动作只有在动作变式、器械、动作幅度和负重口径足够接近时才比较。

### 6.2 饮食 `nutrition_daily_template.csv`

字段：

```csv
date,energy_kcal,protein_g,carbohydrate_g,fat_g,log_status,notes
2026-10-01,2300,150,260,70,complete,
2026-10-02,1800,110,190,55,partial,漏记晚餐
```

- `log_status` 只允许 `complete / partial / unknown`。
- `partial` / `unknown` 不可用于断言全天热量或蛋白不足。
- 同一天多条记录应明确是 meal rows 还是 daily totals，不能混用累加。

### 6.3 体重与围度 `body_measurements_template.csv`

```csv
datetime,measurement,body_part,value,unit,source,notes
2026-10-01T07:30:00+08:00,body_mass,,98.5,kg,smart_scale,
2026-10-01T07:32:00+08:00,waist,waist,100,cm,tape,
```

### 6.4 主观状态 `subjective_log_template.csv`

```csv
 date,energy_level,fatigue,soreness,stress,sleep_quality,pain_location,pain_level,illness_or_travel,notes
2026-10-01,3,2,4,2,4,legs,3,false,
```

量表需要在 UI 中解释锚点（例如 1–5 的含义），不可只存一个无定义整数。以上 CSV 模板应同时放在项目 `templates/` 和导入页下载入口。

---

## 7. 数据质量、30 天观察期与功能解锁

### 7.1 不要求所有指标连续 30 天

Apple Watch 的不同指标采样方式不同：静息心率可能按日汇总，HRV 是间歇样本，VO₂ max 可能几周才出现一次，睡眠取决于佩戴与设置，运动只在用户记录时存在。因此不能用「每天都有记录」作为统一条件。

系统需要分别计算：

- `time_span_days`：最早与最晚记录相隔多少天。
- `observed_days`：有有效样本的不同本地日期数。
- `valid_samples`：有效样本数量。
- `coverage_ratio`：有效观察日 / 所选窗口天数（仅作记录覆盖，不等同佩戴率）。
- `gap_days`：窗口内没有该类型样本的日期数。
- `last_observed_at`：该类型最后一条记录时间。
- `source_count`：来源 / 设备数量；多来源切换要提示。

**不能仅凭 Health ZIP 判断用户某天一定没有佩戴手表。** 无样本也可能是未同步、未开启功能、未导出、授权范围或该指标本来就不是每日测量。界面应说「这几天没有该类记录」，而不是「这几天没戴手表」。

### 7.2 默认质量状态

- `usable`：达到当前功能的最低可比数据要求，可以生成该功能的正式趋势描述。
- `provisional`：有数据但样本量 / 时间跨度不足，只能展示初步描述。
- `insufficient`：不应生成该功能的推断，只展示缺口与采集建议。
- `not_imported`：用户没有导入该类数据或未启用该功能。
- `stale`：历史数据可分析，但快照太旧，不能描述为「今天状态」。

### 7.3 MVP 初始门槛（可配置、非医学阈值）

| 功能 | 初步展示 | 稳定趋势的工程起点 | 数据不足时提示 |
|---|---|---|---|
| 静息心率个人基线 | ≥7 个有效日期 | 最近 30 天内 ≥14 个有效日期，且来源稳定 | 再记录 / 同步一段时间；不强求连续日 |
| HRV-SDNN 基线 | ≥5 个不同日期的样本 | 最近 30 天 ≥10 个不同日期样本，场景 / 来源可比 | HRV 样本稀疏，暂不评价恢复趋势 |
| 睡眠 | ≥3 个有效夜晚可描述 | 30 天内 ≥14 个有效夜晚，且时区与阶段处理可靠 | 只显示已有夜晚，不把缺失夜晚当作零睡眠 |
| VO₂ max | ≥1 个点显示原值 | ≥2 个相隔至少 14 天的同来源估计点，才描述变化 | 暂无足够估计点；日常不要求每天有 VO₂ max |
| 体重趋势 | ≥2 个不同日期显示原值 | ≥5 次测量、跨度 ≥14 天；建议 30 天内覆盖更多日期 | 目前只能显示称重记录，不能判断趋势 |
| 同负荷心率成本 | 有训练记录可查看原始心率 | 最近与参考窗口各 ≥3 次可比训练；路线 / 速度 / 运动类型接近 | 训练条件不可比，不能判断心肺变化 |
| 训练频率与时长 | ≥1 次 workout | 按周展示；覆盖 ≥2 周才比较周趋势 | 只做记录汇总 |
| 力量表现 | ≥1 次同动作训练展示记录 | 同动作 / 器械 / 变式 ≥3 次可比训练暴露 | 需要导入更多组记录；不估算增肌量 |
| 饮食 | 显示已记录样本 | 至少 7 个 `complete` 日才做周汇总；不足则显示已记录部分 | 请标记当天是否完整记录 |
| 周期模式 | ≥1 次已确认出血只做记录回顾 | ≥3 个完整、可比周期才允许探索重复个人模式 | 一个周期不能建立稳定周期效应；不套 28 天模板 |

这些门槛是 **MVP 工程默认值**，不是生理学共识或临床诊断界限。必须在配置文件集中管理，并在界面说明「这是产品的数据质量门槛」。

### 7.4 30 天用户体验

1. 用户首次导入 ZIP 后，先展示历史覆盖。如果过去已经有 6 个月数据，立即使用可用历史，不要强制从零开始等 30 天。
2. 如果数据不足，提示「目前这项分析还不可靠」。列出缺少的记录类型、当前有效天数和建议的下一步。
3. 用户未来继续佩戴并让 Watch 正常同步到 iPhone 健康。
4. 用户再次从健康 App 导出 ZIP，导入新快照。程序对重叠历史去重，补入新增样本，更新覆盖报告。
5. 不要把两个 ZIP 的导出日期误当成采样日期；导出只是快照，不代表期间每天都有数据。
6. 30 天之后按每项功能自己的门槛重新计算；即使满 30 天，缺少力量组记录也仍然不能做力量表现分析。

---

## 8. 分析功能与计算方法

本节对应原 PDF 的共享功能、长期训练适应与女性周期增强，但把它们改为适合 ZIP 离线分析的 MVP 版本。

### 8.1 数据盘点（P0）

输入：所有识别到的 XML 类型、样本时间、来源、Workout、CSV 数据。  
方法：计数、时间跨度、不同日期数、最后记录时间、来源分布、未知类型统计。  
输出：`Data Inventory` 表格和覆盖矩阵。  
实现：固定规则，无 AI。

### 8.2 个人心率 / HRV 基线（P0）

输入：静息心率、HRV-SDNN，来源与日期；睡眠数据可作背景。  
方法：先按本地日期聚合，再计算中位数、MAD、分位数和最近窗口变化。HRV-SDNN 与 RMSSD 必须分开，不得换算或拼接。  
公式：

```text
median = median(x)
MAD = median(abs(x - median))
robust_z = (x_today - median) / (1.4826 * MAD)
```

当 MAD=0、样本量不足或来源混杂时，返回 `not_estimable`，不能用很小分母强行计算。robust_z 是个人历史偏离量，不是疾病概率。

### 8.3 睡眠与作息（P0）

输入：`HKCategoryTypeIdentifierSleepAnalysis` 记录及其 start / end / value。  
方法：合并同一来源的重叠区间；按用户本地时区的醒来日归属一晚；区分 asleep、core、deep、REM、awake、inBed。`inBed` 不算睡眠时长；不同来源重叠不累加。  
输出：每晚总睡眠、入睡 / 醒来时间、夜间覆盖情况、与用户自定目标的差值。不能输出睡眠疾病诊断。

### 8.4 运动与训练负荷（P0）

输入：Workout 起止时间、duration、activityType、WorkoutStatistics；可选 session-RPE CSV。  
方法：训练次数、时长、类型、距离、能量统计；若有 session-RPE，计算 `session_load = duration_minutes × session_RPE`。WorkoutStatistics 里的平均 / 最大心率不是完整逐秒心率。  
输出：每周训练频率和时长、运动类型分布、训练记录时间线。跑步、骑行、力量不混成一个无量纲分数。

### 8.5 同负荷心率成本（P1）

输入：运动期间心率样本、Workout、配速 / 距离 / 路线 / 坡度（实际导出有才使用）、天气 / 温度（若没有则不假定）。  
方法：先按运动类型筛选，找到速度 / 坡度 / 时长相近的稳态段，再比较心率中位数或拟合简单个人回归。统计单位是训练会话，不是把同一次训练每秒心率当独立样本。  
输出：相似外部负荷下的心率变化。不能称为摄氧效率、乳酸阈值或最优心率区间。

### 8.6 VO₂ max 与体重解释（P1）

输入：VO₂ max 样本、体重记录。  
方法：显示原始估计值及时间趋势；解释相对 VO₂ max 的单位是 mL/(kg·min)，体重是分母的一部分。可以做代数分解示例，但不得宣称减重导致了多少心肺进步。  
Apple Watch 的 VO₂ max 是估计值，且通常只在符合条件的户外走 / 跑 / 徒步场景产生，不要求每天有记录。

### 8.7 体重趋势（P0）

输入：bodyMass 样本或 CSV。  
方法：同一天多次称重先聚合；采用 Theil–Sen 稳健斜率估计每周变化；显示测量次数和跨度。  
不能把短期波动直接解释成脂肪、肌肉或水分变化。女性周期相关体重解释另见 8.11。

### 8.8 力量训练表现（P0 / CSV）

输入：动作、变式、器械、左右侧、组数、重量、次数、RIR / RPE、热身标记。  
方法：同动作 / 器械 / 变式 / 动作幅度条件下比较重复次数、负重、工作组数；可选计算 Epley e1RM 作为粗略趋势参考：

```text
e1RM_estimate = weight × (1 + reps / 30)
```

该公式只在相近动作条件、较低次数工作组等条件下作为估计，不是测得 1RM，更不是肌肉增长量。首版可以只比较相同重量下的次数和相同次数下的重量。

### 8.9 营养记录（P0 / CSV 或 HealthKit 样本）

输入：能量、蛋白、碳水、脂肪和每日记录完整性。  
方法：展示已记录摄入；蛋白参考目标可以按用户目标和体重配置，例如一般运动人群常见参考范围 1.4–2.0 g/kg/day，但不对特殊人群自动套用。  
如果 `log_status != complete`，只说「已记录部分」，不说「全天摄入不足」。HealthKit 营养样本不保证包含完整餐次、食物和份量。

### 8.10 长期报告（P0 模板 / P1 统计）

输入：以上已计算的指标、质量标签、用户目标。  
方法：描述窗口变化、支持证据、可能解释和限制。只有关联证据时使用「同时出现」「可能相关」，不输出人为因果贡献百分比。  
实现：模板和规则优先，无 AI 也能完成。

### 8.11 女性周期增强（P1，自选）

输入：经期出血记录、症状、体重、HRV、静息心率、腕温、睡眠和训练表现。  
方法：1 个周期只做记录回顾；数据充分时按已确认经期开始日对齐个人历史，观察是否重复出现某些变化。周期长度不固定，不默认第 14 天排卵。  
使用激素避孕、妊娠、哺乳、围绝经、周期不规律或记录缺失时，允许阶段未知 / 关闭自然周期模型。腕温不是核心体温；周期预测不能用于避孕或诊断。  
输出：「类似波动曾在过去周期出现」「本次同时伴随睡眠缩短」「样本不足，暂不能确认个人模式」。

### 8.12 低能量可用性线索（P2 / 谨慎）

首版不诊断 RED-S，不用固定 EA 阈值自动判病。只把持续快速体重下降、训练量上升、饮食记录不完整 / 已记录摄入偏低、持续疲劳或周期变化并列展示为「建议复核的线索」，并明确观测局限。男性同样适用，不依赖月经信号。

---

## 9. 数据分析输出规范：Evidence Card

每一条对用户可见的分析结论都必须由结构化证据对象产生，不允许在 UI 里临时拼凑数字。

```json
{
  "id": "resting_hr_trend_2026-11-04",
  "title": "静息心率趋势",
  "status": "provisional",
  "window": {"start": "2026-10-06", "end": "2026-11-04"},
  "summary": "最近 30 天有 18 个日期记录，当前中位数为 57 bpm。",
  "facts": [
    {"metric": "resting_heart_rate", "value": 57, "unit": "bpm", "n_days": 18},
    {"metric": "baseline_median", "value": 59, "unit": "bpm", "n_days": 24}
  ],
  "limitations": ["当前窗口存在缺失日期", "来源在窗口中发生变化"],
  "allowed_actions": ["review_data_sources", "continue_observation"],
  "source_feature_ids": ["daily_rhr_2026-10-06_2026-11-04"],
  "algorithm_version": "0.1.0"
}
```

要求：

- `status` 只允许 `usable / provisional / insufficient / stale / not_imported`。
- `facts` 中每个数值必须可追溯到 `daily_feature` 或原始样本。
- `limitations` 必须说明数据缺失、样本少、来源混杂、运动条件不可比等问题。
- `allowed_actions` 是有限枚举，不允许 LLM 发明新的药物、补剂、剂量或训练处方。
- `insufficient` 时不输出趋势结论，只输出「需要什么数据」。
- UI 必须同时显示结论、时间窗口、有效样本量和数据状态。

---

## 10. AI API 策略

### MVP 不需要 AI API

数据解析、去重、单位换算、睡眠区间、心率基线、训练统计、体重趋势、营养汇总、数据完整度、女性周期对齐和模板周报都能由确定性代码完成。

### 后续可选 AI 能力

- 将已计算的 Evidence Cards 改写成更自然的中文解释。
- 对用户自然语言问题进行意图识别，再检索本地已计算结果。
- 从饮食文字 / 图片提取候选食物和份量，必须由用户确认后入库。

### 禁止方式

- 把整个 ZIP 或完整 `export.xml` 发给 LLM。
- 让 LLM 直接读几百万条样本后自己计算 HRV / 恢复 / 增肌效率。
- 让 LLM 自行创造因果百分比、健康评分、训练减量或营养剂量。
- 默认联网调用模型；用户没有单独授权时不得发送任何健康数据。

如果未来加入模型，必须通过接口 `ExplanationProvider` 与本地分析层解耦；无 API key、断网、模型超时、返回不合规时，仍然能用模板完整展示。

---

## 11. CLI 与运行方式

建议提供以下命令（命令名可在实现时微调，但能力必须覆盖）：

```bash
# 创建环境与安装
uv sync

# 查看 ZIP 包结构，不导入
uv run healthzip inspect "/path/to/export.zip"

# 导入 ZIP（默认核心数据；周期数据需显式 opt-in）
uv run healthzip import-apple "/path/to/export.zip" --include-cycle false

# 查看数据盘点与质量
uv run healthzip inventory
uv run healthzip quality --window-days 30

# 导入力量 / 饮食 / 测量 CSV
uv run healthzip import-strength templates/strength_sets_template.csv
uv run healthzip import-nutrition templates/nutrition_daily_template.csv
uv run healthzip import-measurements templates/body_measurements_template.csv

# 生成本地报告
uv run healthzip report --window-days 30 --format markdown --output reports/latest.md

# 启动本地 UI
uv run streamlit run app.py
```

CLI 应支持 `--db-path`，默认数据库放在项目 `.local/` 或用户指定目录；原始 ZIP 默认不复制到项目。所有本地数据目录必须 gitignore。

---

## 12. 测试策略与验收条件

### 12.1 合成 fixture

项目必须自带合成 `synthetic_apple_health_export.zip`，包含：

- 心率、静息心率、HRV-SDNN、VO₂ max、呼吸频率、腕温。
- 睡眠多个阶段，包含跨午夜区间与重叠样本。
- 至少两种 Workout，包含 WorkoutStatistics 和 WorkoutEvent。
- 体重、活动能量、步数、饮食营养样本。
- 周期出血与症状样本（默认测试可禁用周期导入）。
- 未知 HealthKit type、缺失 unit、错误日期、重复记录。
- 一个大于 1MB 的可扩展 fixture 生成器，用于验证流式解析；不要把真实用户 ZIP 放进 Git。

### 12.2 必须有的测试

1. ZIP 结构发现：不同根目录、不同成员顺序、缺少可选文件。
2. 安全性：ZIP Slip、异常压缩比、超大成员、恶意 XML / DTD / 外部实体。
3. XML 解析：所有支持节点、未知类型跳过、格式错误部分失败。
4. 时间：UTC offset、跨午夜、夏令时 / 时区变化、日期聚合。
5. 单位：kg/lb、m/km、kcal/kJ、ms、count/min、°C。
6. 去重：相同 ZIP 重导入、重叠 ZIP、不同 source 同值保留、疑似重复 workout 标记。
7. 睡眠：重叠阶段、inBed 不计入睡眠、同一夜跨日期归属。
8. 缺失：空值不等于零；缺餐、缺睡眠、缺经期记录不推断不存在。
9. 统计：MAD=0、样本不足、异常值、趋势斜率、可比训练筛选。
10. CSV：列缺失、单位错误、RIR / RPE 为空、布尔解析、重复导入。
11. 增量与重建：重新导入后结果幂等；删除导入批次后派生结果更新。
12. UI：没有 ZIP、损坏 ZIP、数据不足、只有部分数据、导入成功的基本流程。

### 12.3 MVP Definition of Done

- [ ] 在 macOS 本地按 README 成功安装并运行。
- [ ] 可从本地文件路径导入 Apple Health ZIP，不要求用户手工解压。
- [ ] XML 使用流式解析；内存不随已处理记录数线性增长。
- [ ] 导入结果显示记录总数、各类型计数、日期跨度、来源和错误。
- [ ] 支持至少本设计列出的核心心率、睡眠、Workout、体重、活动能量、VO₂ max 类型；未知类型安全跳过。
- [ ] 数据写入 SQLite，重复导入不重复计数。
- [ ] 可导入力量训练和营养 CSV 模板。
- [ ] 质量报告按功能显示 `usable / provisional / insufficient / not_imported / stale`。
- [ ] 至少完成心率 / HRV、睡眠、运动统计、体重、力量表现、营养完整性六类分析。
- [ ] 女性周期数据默认 opt-in；启用后可查看已记录周期 / 症状，不推断避孕或医学状态。
- [ ] UI 可查看时间序列图表和 Evidence Cards；每个结论有来源、窗口、样本量与限制。
- [ ] 离线可运行；没有任何 API key 也能完成全部 MVP。
- [ ] 测试通过；Ruff 通过；README 完整。
- [ ] `.gitignore` 排除数据库、原始 ZIP、导出报告和个人 CSV。

---

## 13. 开发优先级

| 阶段 | 目标 | 不要提前做的事 |
|---|---|---|
| P0-1 | ZIP 检查 + XML 流式解析 + SQLite + 数据盘点 | 不做 UI 美化、AI、复杂模型 |
| P0-2 | 数据质量报告 + 心率 / HRV / 睡眠 / Workout / 体重分析 | 不做恢复总分、因果归因 |
| P0-3 | 力量训练 / 营养 CSV + 趋势分析 | 不做动作自动识别、食物视觉识别 |
| P0-4 | Streamlit 基础页面 + Evidence Cards + Markdown 报告 | 不做账号、云端、原生手机端 |
| P1 | 周期分析、同负荷心率比较、更多导出格式 | 不做固定周期训练处方 |
| P2 | AI 解释、复杂个体模型、群体对标 | 未有验证前不做风险概率或增肌量估计 |

---

## 14. 原始产品 PDF 的映射

| 原 PDF 章节 / 功能 | 桌面 ZIP 原型中的实现 |
|---|---|
| 数据字典 A：生理与睡眠 | Apple XML parser + 心率 / HRV / 睡眠分析 |
| 数据字典 B：运动与活动 | Workout / WorkoutStatistics / ActivitySummary 解析 |
| 数据字典 C：体重、饮食、主观记录 | HealthKit 样本 + CSV 模板 |
| 数据字典 D：周期与女性生理状态 | 可选周期样本解析 + 本地症状 / 周期分析 |
| 数据质量与统一结构 | SQLite schema + inventory / coverage / readiness |
| 功能表 A：共享每日反馈 | 心率基线、睡眠、训练统计、营养完整度 |
| 功能表 B：长期进步与训练适应 | 心率成本、体重趋势、力量表现、长期报告 |
| 功能表 C：周期增强 | 周期相关体重、症状—表现地图、腕温 / 睡眠解释 |
| 算法 M1–M8 | 本文第 8 节；仅实现可观测且能复算的部分 |
| HealthKit 授权 / 增量同步 / Watch 实时 | 当前阶段不实现；保留未来 adapter 接口 |

**未来 HealthKit 接入原则：** 将来新增 `HealthKitAdapter`，把 HealthKit 样本映射到同一套 canonical schema；不要把 XML parser 或 HealthKit SDK 代码写进 analytics 模块。桌面版数据模型应保持来源无关。

---

## 15. 最终交付清单

Codex 完成后必须交付：

1. 可运行的项目源码。
2. `README.md`（安装、启动、导入、常见问题）。
3. `AGENTS.md`（项目约束）。
4. `pyproject.toml` 和锁文件。
5. SQLite schema / migration。
6. 合成 Apple Health ZIP fixture 与 CSV 模板。
7. 单元 / 集成测试与测试报告。
8. 本地 UI 与 CLI。
9. 示例分析报告（只用合成数据生成）。
10. 一份 `IMPLEMENTATION_STATUS.md`：完成项、未完成项、已知限制、真实 ZIP 验证步骤。

Codex 不得只交架构图、伪代码或静态 Demo。必须实现真实文件导入、解析、存储、分析和 UI 主流程。
