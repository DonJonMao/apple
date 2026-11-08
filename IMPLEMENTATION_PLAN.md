# 实施计划

1. **P0 导入基础**：ZIP 安全检查、XML 流式解析、时间/单位规范化、SQLite 导入批次与去重。
2. **P0 质量与分析**：数据盘点、覆盖状态、心率/HRV、睡眠、Workout、体重、有氧、营养、力量 CSV 分析。
3. **P0 交付面**：Typer 兼容 CLI、Streamlit 可选 UI、Markdown 报告、合成 fixture 集成测试。
4. **验证**：pytest、Ruff（若环境提供），确认大文件解析不读取完整 XML。

5. **增量同步基础**：保留 ZIP 作为历史回填；增加 schema v2 的同步来源 / 文件游标 / 导入事件，支持 Health Auto Export 风格 JSON、追加式 JSONL 和本地同步目录扫描。
6. **下一轮**：补充 launchd / Windows Task Scheduler 调度、移动端 REST/快速记录的真实设备试点、更新 / 删除 tombstone 的更多来源适配；自有 iOS companion 另立项目。

本仓库当前没有既有 Python 应用；先以标准库实现稳定的导入/分析核心，Polars、Plotly、Streamlit 等依赖作为可选 UI/分析增强。
