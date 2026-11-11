# 实现状态

更新时间：2026-11-08

## 增量同步迭代（2026-11-08）

- SQLite schema v2 已增加同步来源、文件游标、导入事件和批次增量计数。
- 支持 Health Auto Export 风格 JSON 与追加式 JSONL；CLI 提供 `import-json`、`sync-folder`、`sync-status`。
- JSONL 记录文件 offset，JSON 文件按内容 hash 跳过未改变文件；重叠窗口按上游 ID / 逻辑 fingerprint 幂等。
- 增量记录区分 `new / duplicate / updated / deleted / invalid`；更新保留旧版本为 `superseded`，默认分析过滤非 active 记录。
- Streamlit 导入页增加同步目录扫描入口。
- 已增加 token 保护的本机 REST 接收器（`healthzip serve`），接收前先保存原始 inbox，再事务导入；支持 Health Auto Export 风格健康 JSON 和力量 session JSON。
- 力量页增加手机快速逐组记录模式；同一快速训练可以保留相同重量 / 次数的重复组，并按 set number 幂等重试。
- REST 仍要求电脑运行并与手机处于可达网络；iOS 原生 companion App、后台守护安装脚本和跨网络同步尚未实现。

## 一键入口与使用手册（2026-11-08）

- 根目录 `healthzip` 统一封装 `setup / import / start / sync / status / report / token / doctor / serve`，默认数据库、同步目录、端口和 token 文件集中保存，日常不再重复输入 `--db-path`。
- `start` 同时启动 REST 接收器和 Streamlit；REST 默认允许可信局域网，网页默认只监听本机，使用 `start --lan` 才让手机打开网页；服务退出时两个进程一起停止。
- 新增 `docs/HealthZIP_使用手册.md` 和 `output/pdf/HealthZIP_使用手册.pdf`，覆盖完整 ZIP 回填、Health Auto Export 每日推送、力量快速记录、文件夹同步、备份和故障排查。

## 已完成

- ZIP 结构预检查、成员路径 / 符号链接 / 压缩比 / 大小限制与 `export.xml` 发现。
- `ZipFile.open()` + `lxml.etree.iterparse` 增量解析 `Record`、`Workout`、`WorkoutStatistics`、`WorkoutEvent`、`ActivitySummary` 和 `ExportDate`。
- Apple 时间的 UTC、原始本地时间、UTC offset 和本地日期保存；核心单位规范化与未知单位标记。
- SQLite schema、导入批次、原始样本、Workout 子项、活动摘要、外部 CSV 表、派生表和 Evidence Card 表。
- 报告 / UI 运行时会把 Evidence Cards 和日 / 周派生特征持久化，支持从本地样本重新分析。
- SHA-256 同文件识别、样本 fingerprint 去重、跨来源 Workout 重叠标记；批量提交和 `partial_failed` 状态。
- 心率 / HRV-SDNN 基线（中位数、MAD、robust z）、睡眠区间、Workout 周统计、体重 Theil-Sen 斜率、VO₂ max 趋势、力量表现、营养完整度和可选周期记录回顾。
- 四类 CSV 导入：力量组、每日营养、体重 / 围度、主观状态；错误行报告和重复保护。
- CLI、Streamlit 本地 UI、Markdown 报告、合成 fixture、单元 / 集成测试。
- UI 提供睡眠、训练、体重和 VO₂ max 的基础时间序列图表；`pyproject.toml`、`uv.lock`、可安装 wheel 和 schema 文件已补齐。
- README、实施计划和本实现状态说明。
- 力量训练前端直接记录：动作、器械、变式、每组重量、次数、RIR/RPE、热身、活动范围和备注；训练 session / set 采用事务写入、fingerprint 去重，可编辑训练信息并确认删除。
- P1 力量分析：同动作 / 器械 / 变式的 e1RM、同负重次数、正式组训练量、RIR/RPE 和训练日质量；身体状态与力量训练按同日 / ±1 日配对，并提供睡眠、RHR、HRV 偏离、疲劳、酸痛等上下文的描述性汇总。
- P1 周报 / 月报：训练频次、非热身重量×次数、上一周期比较、身体状态覆盖和可追溯 Evidence Cards；今日重量只输出近期记录基础上的保守起始范围、热身和首组复评规则。
- 可选 AI 解释：默认使用用户指定的 OpenAI-compatible endpoint / `deepseek-v4-flash`，API token 只从环境变量读取；只发送结构化 Evidence Cards，校验证据 ID / 数值事实 / 允许行动，失败时回退本地模板；Streamlit 需要用户明确勾选联网同意。

## 已验证

```text
pytest -q                     25 passed
ruff check src app.py tests   All checks passed
合成 ZIP 流式导入             785 个节点，784 个写入，未知类型登记，24 个 Workout
大 fixture 流式导入           171,774 个节点，Python tracemalloc 峰值约 2.0 MB
```

## 尚未完成 / 已知限制

- 尚未在真实用户 ZIP 上验证所有 Apple 导出版本、地区、系统版本和第三方来源；请先备份并在本机验证。
- 没有实现 HealthKit、iOS / watchOS、实时采集、后台同步或云端同步；AI 仅做可选的证据卡解释，不代替确定性计算。
- 同负荷心率成本、复杂周期个体模型、医学提示审定和用户研究属于后续 P2；当前只做保守汇总和记录回顾。
- 今日重量建议不具备精确处方能力：样本或动作条件不足时返回 `insufficient / provisional`；单个 HRV、RHR 或睡眠读数不会自动决定重量。
- 训练负荷优先使用非热身组重量×次数；当前手动 session 没有统一时长字段，因此不冒充 session-RPE load，结果会标记 `volume_kg_fallback`。
- `lxml` 是运行核心依赖；Streamlit / Plotly 是 UI 可选依赖。

## 本轮复核

- Streamlit `AppTest` 空数据库运行无异常；模拟填写动作、重量、次数并提交后成功写入 1 个训练组。
- 手动训练会话支持同日不同训练分开保存，重复提交按包含组内容的 fingerprint 去重。
- P1 配对汇总会写入 `daily_feature` 的算法版本和 source IDs；Markdown 报告包含身体状态 × 做组质量的描述统计和周 / 月建议。

## 用自己的 ZIP 验证

1. 从 iPhone「健康」App 导出 ZIP，并只在本机保存。
2. 先运行 `python -m healthzip.cli inspect /path/to/export.zip`，确认 XML 路径和成员限制通过。
3. 用独立数据库执行 `import-apple`，检查导入状态、未知类型、错误和日期跨度。
4. 执行 `inventory`、`quality` 和 `report`，逐个查看缺口与限制；不要把缺失记录解释成没有佩戴或没有进食。
5. 若需周期信息，单独使用 `--include-cycle`，确认本地报告内容后再保留数据库。
