# Health ZIP Workbench

本项目是一个完全本地运行的 Apple Health 导出 ZIP 整理与分析原型。它读取 iPhone「健康」App 导出的 ZIP，在本机流式解析 `export.xml`，将规范化样本写入 SQLite，并生成数据盘点、质量状态、趋势分析和 Markdown Evidence Card 报告。

它不接入 HealthKit、不开发 iPhone / Watch App，也不需要账号或云服务。默认情况下健康数据、周期记录、ZIP 和报告不会被上传；AI 解释是可选功能，只有用户明确勾选或使用 `--allow-network` 时才发送已经汇总的 Evidence Cards。

## 安装与启动

需要 Python 3.9+。核心导入和 CLI 只使用标准库与 `lxml`；Streamlit 仅用于本地 UI。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install lxml pytest ruff
python -m pip install -e '.[ui]'  # 可选：Streamlit + Plotly
```

如果使用 `uv`，开发环境可以执行 `uv sync --extra dev --extra ui`；只运行 CLI 时执行 `uv sync` 即可。

## CLI

所有命令都支持 `--db-path`，默认写入 `.local/healthzip.sqlite3`。原始 ZIP 不会被复制到数据库目录。

```bash
python -m healthzip.cli inspect fixtures/synthetic_apple_health_export.zip
python -m healthzip.cli --db-path .local/healthzip.sqlite3 import-apple fixtures/synthetic_apple_health_export.zip
python -m healthzip.cli --db-path .local/healthzip.sqlite3 inventory
python -m healthzip.cli --db-path .local/healthzip.sqlite3 quality --window-days 30
python -m healthzip.cli --db-path .local/healthzip.sqlite3 import-strength templates/strength_sets_template.csv
python -m healthzip.cli --db-path .local/healthzip.sqlite3 import-nutrition templates/nutrition_daily_template.csv
python -m healthzip.cli --db-path .local/healthzip.sqlite3 import-measurements templates/body_measurements_template.csv
python -m healthzip.cli --db-path .local/healthzip.sqlite3 import-subjective templates/subjective_log_template.csv
python -m healthzip.cli --db-path .local/healthzip.sqlite3 report --window-days 30 --output reports/latest.md
python -m healthzip.cli --db-path .local/healthzip.sqlite3 ai-explain --question "请解释最近的身体状态和训练趋势"
```

周期数据默认关闭；只有用户明确选择时才导入：

```bash
python -m healthzip.cli --db-path .local/healthzip.sqlite3 import-apple export.zip --include-cycle
```

同一个 ZIP 的 SHA-256 重复导入会返回 `already_imported`。如果第一次关闭周期、之后明确要重新扫描，可使用 `--recheck --include-cycle`；这会按 fingerprint 去重健康样本。

### AI 解释（可选）

AI 服务使用 OpenAI-compatible Chat Completions 接口。不要把 token 写入代码、README、数据库或报告，先在当前终端设置环境变量：

```bash
export HEALTHZIP_AI_BASE_URL="http://111.19.156.30:8006/v1/chat/completions"
export HEALTHZIP_AI_MODEL="deepseek-v4-flash"
export HEALTHZIP_AI_API_KEY="<your-token>"
export HEALTHZIP_AI_TIMEOUT_SECONDS="20"  # 可选
```

命令行调用必须显式加 `--allow-network`；不加时只生成本地确定性回退：

```bash
python -m healthzip.cli --db-path .local/healthzip.sqlite3 ai-explain \
  --question "结合睡眠、HRV 和力量训练给出下一步观察重点" --allow-network
```

AI 只接收本地计算后的 Evidence Cards（摘要、事实、窗口、限制和允许行动），不接收原始 ZIP/XML 或逐条健康样本。返回结果会校验证据 ID、数值事实和允许行动；请求失败、格式不合法或未配置 token 时自动回退到本地模板，并标明来源。

## 本地 UI

```bash
streamlit run app.py --server.address 127.0.0.1
```

在侧栏输入本地 ZIP 路径和 SQLite 路径，先检查再点击「流式导入」。页面包含导入、总览、质量、心率 / HRV、睡眠、运动、体重 / 有氧、力量、营养、周期和报告页。大型 ZIP 使用路径输入，不通过内存型上传控件读取。

力量页可以直接记录一次训练：填写训练日期和名称，在每一行填写动作、器械、变式、重量、次数、RIR/RPE、是否热身、活动范围和备注，然后点击「保存训练记录」。同一组重复提交会按 fingerprint 去重；最近训练可展开查看、编辑训练信息或勾选确认后删除。正式组会进入动作条件的 e1RM、同负重次数和训练量趋势。

力量页还提供身体状态 × 做组质量的同日 / 相邻日配对表和描述性中位数汇总（睡眠、RHR / HRV 偏离、疲劳、酸痛等），当前周 / 月报告，以及今日训练起始重量范围。建议范围只参考近期同动作记录和已记录的状态信号，必须先热身和首组复评；它不是精确处方，单个 HRV 或心率读数不会自动决定重量。

页面中的「AI 证据解释」默认不联网。只有勾选「允许把当前结构化摘要发送到已配置的 AI 服务」后才会尝试请求；未勾选时使用本地回退。页面会显示 endpoint 和 model，但不会显示 token。

## 流式与安全行为

- XML 由 `ZipFile.open()` 和 `lxml.etree.iterparse` 增量读取，不构造完整记录列表。
- 禁止 DTD、外部实体和网络访问；ZIP 成员路径、符号链接、成员数、单成员大小、总解压大小和压缩比会检查。
- 保留原始 type、value、unit、source、device、时间和 metadata，同时写入 canonical type / normalized value。
- 未知 HealthKit type、缺失数据和无法确认的单位会登记或降级，不会静默伪造零值。
- SQLite 通过样本 fingerprint 去重；不同来源的重叠 Workout 保留并标记 `suspected_duplicate`。

## 测试与合成数据

仓库中的 ZIP 和 CSV 都是合成数据。运行：

```bash
PYTHONPATH=src pytest -q
ruff check src app.py tests
```

使用 uv 时对应为 `uv run --extra dev pytest -q` 与 `uv run --extra dev ruff check src app.py tests`。

大文件 fixture 已在 `fixtures/synthetic_apple_health_export_large.zip`，用于流式解析压力验证；它不代表真实用户数据。

## 分析边界

分析按功能独立判断 `usable / provisional / insufficient / not_imported / stale`。个人基线使用中位数、MAD 和分位数；睡眠区间去重；体重趋势使用稳健斜率；力量表现只比较动作 / 器械 / 变式一致的记录；营养部分记录不用于断言全天摄入不足。系统不生成恢复总分、疾病诊断、避孕 / 排卵判断、RED-S 诊断、肌肉损伤或精确增肌量结论。

合成数据示例报告见 [examples/synthetic_report.md](examples/synthetic_report.md)。详见 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) 和项目设计说明 [DESIGN_SPEC.md](DESIGN_SPEC.md)。
