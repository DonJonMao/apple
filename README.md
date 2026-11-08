# Health ZIP Workbench

本项目是一个完全本地运行的 Apple Health 导出 ZIP 整理与分析原型。它读取 iPhone「健康」App 导出的 ZIP，在本机流式解析 `export.xml`，将规范化样本写入 SQLite，并生成数据盘点、质量状态、趋势分析和 Markdown Evidence Card 报告。

它不接入 HealthKit、不开发 iPhone / Watch App，也不需要账号或云服务。默认情况下健康数据、周期记录、ZIP 和报告不会被上传；AI 解释是可选功能，只有用户明确勾选或使用 `--allow-network` 时才发送已经汇总的 Evidence Cards。

## 最简单的使用方式

项目根目录的 `healthzip` 是一键入口。macOS / Linux 首次只需要：

```bash
./healthzip setup
```

它会创建 `.venv`、安装核心和 UI 依赖、创建 `.local`、生成本机保存的 REST token，并显示局域网地址。之后的常用操作只有：

```bash
./healthzip import /path/to/AppleHealthExport.zip  # 第一次历史回填
./healthzip start                                 # 启动手机增量接收器和网页界面
./healthzip status                                # 查看新增/更新/删除和数据盘点
./healthzip report                                # 生成 reports/latest.md
```

`start` 会同时启动 REST 接收器和 Streamlit，并自动打开电脑上的网页。REST 默认监听可信局域网，网页默认只监听本机；需要用 iPhone Safari 打开网页时使用 `./healthzip start --lan`。按 `Ctrl-C` 会一起停止；电脑需要保持开机并运行它，Health Auto Export 才能每日推送。只想在电脑本机使用时可执行 `./healthzip start --local`。`./healthzip doctor` 检查环境，`./healthzip token` 显示应填入手机导出器的 token。文件夹同步备用方式使用 `./healthzip sync`，默认扫描 `.local/phone-sync`。

Windows 可用 `py healthzip setup`、`py healthzip start` 等同样的子命令；也可以在 PowerShell 中把 `./healthzip` 换成 `py healthzip`。

## 安装与启动（高级方式）

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

### 手机增量同步（当前增量版本）

全量 ZIP 仍用于第一次历史回填；日常数据可以由手机导出器写入一个本地 JSON/JSONL 同步目录，再按游标导入。当前适配 Health Auto Export 风格的
`{"data":{"metrics":[...],"workouts":[...]}}` 结构，并保留来源、上游记录 ID、批次和新增 / 重复 / 更新 / 删除计数：

```bash
python -m healthzip.cli --db-path .local/healthzip.sqlite3 \
  sync-folder /path/to/phone-sync --source phone_export
python -m healthzip.cli --db-path .local/healthzip.sqlite3 sync-status
```

JSONL 会保存上次读取位置；文件追加、重启和离线补传不会重复导入。JSON 文件按内容 hash 跳过未改变的文件；覆盖式滚动窗口重新扫描时依靠上游 ID 或逻辑 fingerprint 幂等。修改记录会保留旧版本并标记为 `superseded`，删除事件会标记为 `deleted`，默认分析只使用 `active` 记录。

手机导出器的心率和 HRV 必须选择逐样本或高粒度格式。只有每日 `Min/Avg/Max` 汇总时，系统会拒绝将它伪装成原始心率样本，并在批次错误中说明原因。

Streamlit 侧栏提供「手机增量同步目录」和「扫描增量数据」按钮。本机 REST 接收器已经可用；手机原生 companion App 属于后续迭代。同步目录和 REST inbox 里的原始健康数据不会提交到 Git。

本机 REST 接收器也已提供，默认仅监听本机：

```bash
export HEALTHZIP_SYNC_TOKEN="请在本机保存的随机长 token"
python -m healthzip.cli --db-path .local/healthzip.sqlite3 serve \
  --bind 127.0.0.1 --port 8765
```

需要手机通过同一局域网访问时才显式使用 `--bind 0.0.0.0`，并在导出器中配置
`http://电脑局域网IP:8765/v1/ingest/health-auto-export`、请求头
`X-HealthZip-Token` 和可选的 `X-HealthZip-Source`。接收器会先将原始 JSON 保存到数据库目录的 `inbox/`，再事务导入；不要把端口转发到公网。未设置环境变量时会临时生成 token，每次重启都会变化，正式使用应显式设置 `HEALTHZIP_SYNC_TOKEN`。

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

同一局域网内要用手机快速记录力量组时，可以显式监听局域网地址：

```bash
streamlit run app.py --server.address 0.0.0.0
```

手机访问电脑的局域网 IP；该模式只适用于可信局域网，不应直接暴露到公网。

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
