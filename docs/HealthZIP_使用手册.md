# HealthZIP 使用手册

## 这份工具解决什么问题

HealthZIP 是一个完全在电脑本地运行的 Apple Health 数据整理和分析工具。它把 iPhone「健康」导出的 ZIP 作为第一次历史回填，再用 Health Auto Export 向电脑发送每日新增数据。数据写入本地 SQLite，网页界面显示数据质量、趋势、训练和报告。

工具不会接入 HealthKit，不需要账号，不把原始健康数据上传到云端，也没有自有 iOS App。当前最适合的使用方式是：Mac 开机时运行接收器，iPhone 和 Mac 在同一可信 Wi-Fi，Health Auto Export 按日 POST 到 Mac。

## 先记住三个命令

在项目根目录打开终端，第一次运行：

```text
./healthzip setup
```

导入第一次从 iPhone 导出的完整 ZIP：

```text
./healthzip import /path/to/AppleHealthExport.zip
```

以后每天让手机自动推送，并打开分析界面：

```text
./healthzip start
```

`start` 会同时启动 REST 接收器和 Streamlit 网页界面，并自动打开电脑上的网页。REST 默认监听可信局域网，网页默认只监听本机；若要让 iPhone Safari 也打开网页，使用 `./healthzip start --lan`。按 `Ctrl-C` 会停止这两个进程。电脑必须开机且该命令正在运行，Health Auto Export 才能送达数据。只在电脑本机使用时，可以执行 `./healthzip start --local`，此时手机不能访问。

Windows 没有执行权限时，在 PowerShell 使用 `py healthzip setup`、`py healthzip import <ZIP路径>` 和 `py healthzip start`。这里的 `<ZIP路径>` 代表实际路径，不要把尖括号一起输入。

## 第一次安装和导入

### 1. 准备

需要 Python 3.9 或更高版本，以及一个项目目录。不要把真实 ZIP、SQLite 数据库、原始同步 JSON 或个人 CSV 放进 Git 仓库。仓库里自带的 ZIP 和 CSV 都是合成测试数据。

### 2. 一键安装

```text
./healthzip setup
```

该命令会：

- 创建或检查 `.venv`；
- 安装项目、lxml、Streamlit 和 Plotly；
- 创建 `.local`；
- 生成 `.local/sync_token`，并尽量设置为仅当前用户可读；
- 保存默认设置到 `.local/healthzip.json`。

默认位置如下：

| 内容 | 默认位置 |
| --- | --- |
| SQLite 数据库 | `.local/healthzip.sqlite3` |
| REST 原始请求备份 | `.local/inbox/` |
| 文件夹同步目录 | `.local/phone-sync/` |
| 同步 token | `.local/sync_token` |
| 本地报告 | `reports/latest.md` |
| REST 端口 | `8765` |
| 网页端口 | `8501` |

### 3. 导入第一次完整 ZIP

在 iPhone「健康」App 中导出完整健康数据 ZIP，把它放在电脑上，然后执行：

```text
./healthzip import /Users/你的名字/Downloads/export.zip
```

入口会自动做三件事：检查 ZIP 结构、流式导入 `export.xml`、显示数据盘点。它不会把整个 XML 一次性读入内存，也不会要求手动解压。相同 ZIP 再导入会根据 SHA-256 跳过；不同快照中的重叠记录会按 fingerprint 去重。

如果第一次没有导入周期数据，之后明确需要周期字段时，使用高级命令：

```text
python -m healthzip.cli --db-path .local/healthzip.sqlite3 \
  import-apple /path/to/export.zip --include-cycle --recheck
```

### 4. 生成第一份报告

```text
./healthzip report
```

报告写入 `reports/latest.md`。报告中的每个结论都带有时间窗口、样本数、质量状态、来源和限制；数据不足时会说明缺什么，不会把空白当作零。

## iPhone 每日增量推送（推荐）

### 电脑端启动服务

在项目根目录执行：

```text
./healthzip start
```

终端会显示 REST 健康检查地址、网页地址和 token 文件位置。默认 REST 监听 `0.0.0.0:8765`，网页监听 `127.0.0.1:8501`；需要手机打开网页时才使用 `--lan`。REST 只用于可信局域网，不要做路由器端口转发，不要把它暴露到公网。

如果只想单独启动 REST 接收器：

```text
./healthzip serve
```

### 确认 Mac 的局域网 IP

Wi-Fi 通常使用：

```text
ipconfig getifaddr en0
```

如果没有输出，再试 `ipconfig getifaddr en1`，或在「系统设置 → 网络 → Wi-Fi」查看 IP。假设 IP 是 `192.168.1.23`，REST 地址就是：

```text
http://192.168.1.23:8765
```

在 Mac 浏览器先打开 `http://192.168.1.23:8765/health`。看到 `{"status":"ok"}` 才继续配置手机。若浏览器也打不开，先检查 `./healthzip start` 是否还在运行以及 Mac 防火墙是否允许 Python 接收局域网连接。

### 在 Health Auto Export 中配置

Health Auto Export 的菜单名称可能随版本变化，找「自动化」「REST API」「自定义请求」或同类入口，配置：

| 设置 | 填写内容 |
| --- | --- |
| 方法 | `POST` |
| URL | `http://Mac局域网IP:8765/v1/ingest/health-auto-export` |
| Header 名 | `X-HealthZip-Token` |
| Header 值 | `./healthzip token` 输出的完整 token |
| 可选 Header | `X-HealthZip-Source: health_auto_export` |

不要把 token 写进公开截图、仓库或报告。iPhone 与 Mac 必须连接同一个 Wi-Fi。先在 Health Auto Export 中发送一次测试请求，再用 `./healthzip status` 查看最近批次。

心率和 HRV-SDNN 要选择「逐样本」或足够高粒度的导出。不要只选择每日 Min/Avg/Max 汇总来冒充原始样本；系统会把这种批次标为 `aggregate_not_raw`，不会用它生成原始心率趋势。Workout 可以按应用支持的标准结构一起发送。

### 每日运行时发生什么

REST 接收器先把原始 JSON 保存到 `.local/inbox/`，再在 SQLite 事务中导入。每条记录优先使用 Health Auto Export 的上游 ID；没有 ID 时使用逻辑 fingerprint。

`./healthzip status` 的批次统计含义：

| 计数 | 含义 |
| --- | --- |
| `new` | 第一次写入的记录 |
| `duplicate` | 已存在且内容没有变化，安全跳过 |
| `updated` | 同一逻辑记录内容改变，旧版本保留为 `superseded` |
| `deleted` | 上游明确要求删除，记录标记为 `deleted` |
| `invalid` | 格式、单位或粒度不符合要求；其他有效记录仍可提交 |

分析默认只使用 `active` 记录。因此手机每天只推送当天或最近窗口的数据，也不会因为重复推送而重复计数。Mac 休眠、关机、换 Wi-Fi 或 REST 服务停止期间，手机端可能显示发送失败；恢复后让 Health Auto Export 补发最近窗口即可。

## 网页界面和手机力量记录

运行 `./healthzip start` 后，在 Mac 打开 `http://127.0.0.1:8501`。如果要用同一 Wi-Fi 的 iPhone Safari 记录力量训练，先停止服务，再执行 `./healthzip start --lan`，然后打开 `http://Mac局域网IP:8501`。

力量页的「手机快速记录一组」每次填写：日期、动作、重量（kg）和次数；器械/变式、RIR/RPE、热身可以按需要填写。点「保存这一组」后继续下一组；同一 session 可以追加不同动作，要分成另一场训练时再点「开始新的快速训练」。完整训练表单另外支持活动范围和备注。网络重试按 set_number 幂等，不会因为重复点击无限复制同一组。

如果需要一次录入完整训练，可使用力量页的完整表单。也可以用模板导入：

```text
python -m healthzip.cli --db-path .local/healthzip.sqlite3 \
  import-strength templates/strength_sets_template.csv
```

训练记录仅用于描述性趋势和同动作比较，不会根据一个 HRV 或心率读数自动开重量处方。

## 文件夹同步备用方式

如果手机导出器只能把 JSON/JSONL 写入电脑目录，可以把文件放到 `.local/phone-sync/`，然后执行：

```text
./healthzip sync
```

也可以指定目录：

```text
./healthzip sync /path/to/phone-sync
```

JSON 文件按内容 hash 判断是否改变；JSONL 文件保存上次读取位置，追加数据、重启和离线补传都只处理新增完整行。文件被截断或轮替时会从头扫描，并用逻辑 key 去重。文件夹同步和 REST 接收是两种独立入口，选一种即可。

## 查看状态、质量和报告

日常只需：

```text
./healthzip status
./healthzip report
```

需要更细的质量窗口时，使用高级 CLI：

```text
python -m healthzip.cli --db-path .local/healthzip.sqlite3 inventory
python -m healthzip.cli --db-path .local/healthzip.sqlite3 quality --window-days 30
```

Streamlit 页面包括导入与总览、数据质量、心率/HRV、睡眠、运动、体重/有氧、力量、营养、周期和报告。AI 解释是可选项；默认不联网，只有明确勾选并配置服务时才会发送结构化 Evidence Cards，不发送原始 ZIP/XML。

## 常见问题排查

| 现象 | 处理方法 |
| --- | --- |
| 手机返回 401 | 在 Mac 执行 `./healthzip token`，重新复制完整 token；不要每次手动生成新 token |
| 手机返回 404 | URL 必须是 `/v1/ingest/health-auto-export`，不要漏掉路径 |
| Mac 浏览器打不开 `/health` | 重新执行 `./healthzip start`，确认端口 8765 未被其他程序占用 |
| Mac 能打开，iPhone 打不开 | 确认同一 Wi-Fi、使用 Mac 局域网 IP、没有访客网络隔离，检查防火墙 |
| 每天没有新数据 | Mac 必须开机并运行 `start`；iOS 后台自动化不是严格实时，可在 HAE 中手动补发 |
| 批次显示 `aggregate_not_raw` | 在 HAE 选择逐样本/高粒度心率和 HRV，而不是每日 Min/Avg/Max |
| `invalid` 或 `partial_failed` | 在 `status` 的最近批次错误中查看具体字段；有效记录仍会保留 |
| 页面打不开 | 确认网页端口 8501 未被占用；手机访问前先用 `./healthzip start --lan`，再使用 `http://MacIP:8501` |
| 想换电脑 | 复制 `.local/healthzip.sqlite3`；如需重放接收请求，也复制 `.local/inbox/`，再在新电脑运行 `./healthzip setup` 后替换数据库 |
| 不知道环境是否正确 | 执行 `./healthzip doctor`，它会检查 Python、虚拟环境、lxml、Streamlit、数据库和局域网 IP |

## 备份、隐私和删除

定期备份 `.local/healthzip.sqlite3`。如果希望保留可重放的原始接收内容，一起备份 `.local/inbox/`。这些目录已在 `.gitignore` 中排除，不应提交到 Git 或上传网盘。

默认服务只在可信局域网工作。不要把 8765 或 8501 做公网端口转发，不要把 token 分享给他人。HealthZIP 不会根据缺失记录断言「没有睡眠」「没有佩戴」或「没有吃饭」，报告也不是医疗诊断。

当前版本没有原生 iOS companion App、严格实时的 iOS 后台推送、macOS launchd 自动常驻或 Windows 计划任务。电脑关机或睡眠时，REST 无法接收；需要可靠的长期运行时，可以把 `./healthzip start` 加入你自己的登录启动项，但仍应保留 token 和防火墙保护。

## 常用命令速查

| 目的 | 命令 |
| --- | --- |
| 首次安装 | `./healthzip setup` |
| 导入完整 ZIP | `./healthzip import /path/to/export.zip` |
| 启动 REST + 网页 | `./healthzip start` |
| 仅本机启动 | `./healthzip start --local` |
| 查看 token | `./healthzip token` |
| 文件夹增量同步 | `./healthzip sync [目录]` |
| 查看状态 | `./healthzip status` |
| 生成报告 | `./healthzip report` |
| 检查环境 | `./healthzip doctor` |
| 仅启动 REST | `./healthzip serve` |
| 高级 CLI 帮助 | `python -m healthzip.cli --help` |
