# 从这里开始

**你要交给 Codex 的不是单独一个 PDF，而是整个项目包。**

1. 解压 `Health_ZIP_Workbench_Codex_Pack.zip`，把文件夹内容复制到一个新的 Codex 工作区 / Git 仓库。
2. 在 Codex 中将 `CODEX_GOAL.md` 全文设置为 Goal。也可以先粘贴 `CODEX_PROMPT.txt`，再要求 Codex 完整读取 Goal 文件。
3. Codex 必须先阅读 `DESIGN_SPEC.md`、`AGENTS.md` 和 `reference_product_design_v1.0.pdf`。
4. 要求它按 Goal 自主实施，不要只输出计划。先完成 ZIP/XML 解析、SQLite、质量报告和测试，再做分析页面。
5. 先用 `fixtures/synthetic_apple_health_export.zip` 测试，再用 `fixtures/synthetic_apple_health_export_large.zip` 测试流式解析，最后导入你自己的 Apple Health ZIP。

## 本项目本次不做

- 不开发 iPhone / Watch App。
- 不接入 HealthKit。
- 不做云端账号、同步或 AI API。
- 不做精美前端。

先把本地数据整理、分析与解释链路做扎实。
