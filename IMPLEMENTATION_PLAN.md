# 实施计划

1. **P0 导入基础**：ZIP 安全检查、XML 流式解析、时间/单位规范化、SQLite 导入批次与去重。
2. **P0 质量与分析**：数据盘点、覆盖状态、心率/HRV、睡眠、Workout、体重、有氧、营养、力量 CSV 分析。
3. **P0 交付面**：Typer 兼容 CLI、Streamlit 可选 UI、Markdown 报告、合成 fixture 集成测试。
4. **验证**：pytest、Ruff（若环境提供），确认大文件解析不读取完整 XML。

本仓库当前没有既有 Python 应用；先以标准库实现稳定的导入/分析核心，Polars、Plotly、Streamlit 等依赖作为可选 UI/分析增强。
