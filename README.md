# HealthZIP v1.3.1

HealthZIP 是本地 Apple Health 整理和训练记录工作台：安全读取健康 App 导出的 ZIP，保存至 SQLite，直接记录训练，查看可比表现、身体状态、能量背景和周月复盘。界面使用 Streamlit，另有 CLI、局域网增量接收器和可下载的离线训练记录器。

核心不需要账号或 AI。公开文献与私人健康数据库分开；只有明确开启模型联网解释时，才发送当前结构化证据卡。模型不负责计算重量或补全缺失记录。

## 安装与启动

需要 Python 3.9+。macOS / Linux 在仓库根目录运行：

```bash
./healthzip setup
./healthzip start
```

需要手机通过同一可信局域网打开网页时用 `./healthzip start --lan`。停止时按 Ctrl-C。Windows 可用 `py healthzip setup` 和 `py healthzip start`。查看连接配置用 `./healthzip doctor`，本机 token 用 `./healthzip token`。

手动安装开发环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[ui,dev,research]'
.venv/bin/streamlit run app.py --server.address 127.0.0.1
```

也可 `uv sync --extra ui --extra dev --extra research`。核心依赖 lxml；UI、统计研究、获准PDF解析分别为 `ui`、`research`、`knowledge-pdf` 可选依赖。没有研究依赖时，观测和记录继续可用，研究模型返回缺项。

## 开始使用

- 健康数据：`./healthzip import /path/to/export.zip` 进行首次回填；后续使用 ZIP、手机导出 JSON/JSONL 或 Health Auto Export 局域网同步。重复文件不会重复计数。
- 训练：打开「力量」页，直接开始临时训练，或创建自选模板。动作可搜索、收藏和自定义；器械、侧别、动作幅度和负荷口径需要明确确认。计划目标与实际记录分开。
- 每组记录实际重量/次数/时长/距离、RIR/RPE、停止原因与质量。上次值带入后仍是草稿，需要点击完成。失败尝试、跳过、修订、撤销和中断续记保留独立状态。
- 断网记录：在力量页下载离线HTML；先联网缓存动作和模板，再打开本地文件。草稿及待同步事件保存在该浏览器，刷新可恢复；联网重试使用稳定事件ID。同重量的两个真实组保留为两组。
- 分析：六个功能页共用77项 MetricResult；数值、单位、截止时间、来源、版本、分母、缺项和区间均可展开。单边30→32.5kg对应两侧配重增加5kg，未知杆重不会补成含杆总重。
- 候选：用户计划、可比记录、实际器械步长及匹配审核依据共同决定是否能给候选。缺少依据时保存缺项；采纳、执行和后续结果另记，不自动改写模板。

参考比较需要在动作条件中填写结构化测量协议及版本，并在执行前指定参考组。同场多个动作分别分析。候选页面可选择当前组目标、双重进阶或可选策略试验；结束后从「历史 / 冲突」继续补录反馈和复核任务。只有解释权限的理论不能解锁数值候选。

完整操作、故障恢复和迁移说明见 [中文使用手册](docs/HealthZIP_使用手册.md) / [PDF](output/pdf/HealthZIP_使用手册.pdf)。针对 `0a943b4` 的 R01–R15 与 RAG 修复逐项证据见 [审查修复验收表](docs/review_fixes_2026-11-11.md)。

## 常用 CLI

所有私人文件默认放 `.local/`，报告默认放 `reports/`；这些目录不提交。

```bash
python -m healthzip.cli inspect /path/to/export.zip
python -m healthzip.cli --db-path .local/healthzip.sqlite3 import-apple /path/to/export.zip
python -m healthzip.cli --db-path .local/healthzip.sqlite3 import-strength templates/strength_sets_template.csv
python -m healthzip.cli training-import /path/to/training.json --preview
python -m healthzip.cli --db-path .local/healthzip.sqlite3 training-import /path/to/training.json
python -m healthzip.cli --db-path .local/healthzip.sqlite3 training-export-all reports/training.json
python -m healthzip.cli --db-path .local/healthzip.sqlite3 sync-folder .local/phone-sync
python -m healthzip.cli --db-path .local/healthzip.sqlite3 analyze-v13 --output reports/metrics.json
python -m healthzip.cli --db-path .local/healthzip.sqlite3 analyze-v13 --period week --output reports/week.json
python -m healthzip.cli --db-path .local/healthzip.sqlite3 report --output reports/latest.md
python -m healthzip.cli --db-path .local/healthzip.sqlite3 backup .local/backups/healthzip-v3.sqlite3
python -m healthzip.cli restore .local/backups/healthzip-v3.sqlite3 .local/restored.sqlite3
```

周期数据仍默认关闭，需要时给 `import-apple` 加 `--include-cycle`。`analyze-v13 --cutoff-time` 要求带时区的时间，`--context-json` 可提供本地研究协议与用户计划；未知可见时间不能进入历史决策。

## 公开知识与研究评测

```bash
python -m healthzip.knowledge seed
python -m healthzip.knowledge acquire --fulltext
python -m healthzip.knowledge status
python -m healthzip.knowledge query '单边片重与总重有什么区别' --route strength
python -m healthzip.science calibrate --output .local/science-evaluation --seed 1300 --repetitions 300
```

来源受限时逐项记录原因并继续其他来源；索引只接纳实际取得且权限允许的资料。原始字节及私有知识库保存在 `.local/knowledge`，公共获取/审核清单在 `artifacts/knowledge`。种子卡不等于已审核；AI辅助阅读性审核不授予数值候选权限。详见 [知识文档](docs/knowledge_v1.3.md) 和 [科学实现说明](docs/science_v1.3.md)。

当前RAG仍存在明显召回不足；30个可见开发案例与8个固定留出案例分别报告，不据此宣称专业问答已充分验证。统计模拟标记 `simulation_only`，尚无真人时间外效果验证；绝对摄入、个人预测或停滞标签在条件不足时保留不可识别/证据不足。

## 可选 AI 解释

自行配置 `HEALTHZIP_AI_BASE_URL`、`HEALTHZIP_AI_MODEL` 和 `HEALTHZIP_AI_API_KEY`；没有默认外部端点。CLI 必须加 `ai-explain --allow-network`，UI 必须勾选联网同意。数值、单位、窗口、行动、摘要或限制校验失败，回退本地结构化模板。不要把密钥写入仓库。

## 验证与交付证据

```bash
python -m pytest -q
ruff check src app.py tests
```

真实命令与结果见 [实现状态](IMPLEMENTATION_STATUS.md)、[本次修复验收表](docs/review_fixes_2026-11-11.md) 和 `artifacts/verification`。软件、语料取得、理论审核与科学验证分别列出。仓库内演示与测试使用合成数据；真实健康导出、数据库、个人CSV、日志与报告不提交。
