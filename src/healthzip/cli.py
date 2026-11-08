"""Command-line entry point for the local workbench."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, List, Optional

from healthzip.ai import explain_analysis
from healthzip.analytics import all_analysis, persist_analysis
from healthzip.config import DEFAULT_DB_PATH
from healthzip.db.repository import Repository
from healthzip.importers.apple_xml import import_apple_zip
from healthzip.importers.apple_zip import inspect_zip
from healthzip.importers.csv_importers import (
    import_measurements_csv,
    import_nutrition_csv,
    import_strength_csv,
    import_subjective_csv,
)
from healthzip.importers.incremental import import_json_file, sync_folder
from healthzip.quality import inventory, readiness
from healthzip.reporting import render_report
from healthzip.sync_server import serve


def _repo(args: argparse.Namespace) -> Repository:
    return Repository(args.db_path or DEFAULT_DB_PATH)


def _dump(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="healthzip", description="本地 Apple Health ZIP 整理与分析工具"
    )
    p.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite 路径")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("inspect", help="仅检查 ZIP，不导入")
    s.add_argument("zip_path")
    s = sub.add_parser("import-apple", help="流式导入 Apple Health ZIP")
    s.add_argument("zip_path")
    s.add_argument("--include-cycle", action="store_true")
    s.add_argument("--recheck", action="store_true")
    sub.add_parser("inventory", help="数据盘点")
    s = sub.add_parser("quality", help="功能质量状态")
    s.add_argument("--window-days", type=int, default=30)
    s.add_argument("--as-of", default=None, help="可选参考日期；用于识别历史数据 stale")
    for name, func in (
        ("import-strength", import_strength_csv),
        ("import-nutrition", import_nutrition_csv),
        ("import-measurements", import_measurements_csv),
        ("import-subjective", import_subjective_csv),
    ):
        s = sub.add_parser(name)
        s.add_argument("csv_path")
    s = sub.add_parser("report", help="生成 Markdown 报告")
    s.add_argument("--window-days", type=int, default=30)
    s.add_argument("--output", default="reports/latest.md")
    s = sub.add_parser("ai-explain", help="用可选的 OpenAI-compatible 服务解释本地 Evidence Cards")
    s.add_argument("--question", default=None)
    s.add_argument("--allow-network", action="store_true", help="明确允许发送结构化摘要到 AI 服务")
    s = sub.add_parser("import-json", help="导入手机导出的一份 JSON 增量数据")
    s.add_argument("json_path")
    s.add_argument("--source", default="phone_export")
    s.add_argument("--source-kind", default="health_auto_export")
    s = sub.add_parser("sync-folder", help="扫描 JSON/JSONL 手机同步目录并导入新增数据")
    s.add_argument("directory")
    s.add_argument("--source", default="phone_export")
    s.add_argument("--source-kind", default="health_auto_export")
    sub.add_parser("sync-status", help="查看增量同步来源、文件游标和最近批次")
    s = sub.add_parser("serve", help="启动本机 / 局域网增量接收器")
    s.add_argument("--bind", default="127.0.0.1", help="监听地址；局域网访问时显式使用 0.0.0.0")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--token-env", default="HEALTHZIP_SYNC_TOKEN")
    s.add_argument("--max-body-mb", type=int, default=20)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inspect":
        _dump(inspect_zip(args.zip_path).as_dict())
        return 0
    if args.command == "serve":
        serve(
            args.db_path or DEFAULT_DB_PATH,
            bind=args.bind,
            port=args.port,
            token=os.environ.get(args.token_env),
            max_body_bytes=max(1, args.max_body_mb) * 1024 * 1024,
        )
        return 0
    repo = _repo(args)
    try:
        if args.command == "import-apple":
            _dump(
                import_apple_zip(
                    args.zip_path,
                    repo,
                    include_cycle=args.include_cycle,
                    skip_duplicate_file=not args.recheck,
                ).as_dict()
            )
        elif args.command == "inventory":
            _dump(inventory(repo))
        elif args.command == "quality":
            _dump(readiness(repo, window_days=args.window_days, as_of=args.as_of))
        elif args.command == "report":
            result = all_analysis(repo, args.window_days)
            persist_analysis(repo, result)
            out = render_report(result, inventory(repo), args.output)
            print(str(out))
        elif args.command == "ai-explain":
            result = all_analysis(repo, 30)
            persist_analysis(repo, result)
            _dump(
                explain_analysis(result, question=args.question, allow_network=args.allow_network)
            )
        elif args.command == "import-strength":
            _dump(import_strength_csv(args.csv_path, repo))
        elif args.command == "import-nutrition":
            _dump(import_nutrition_csv(args.csv_path, repo))
        elif args.command == "import-measurements":
            _dump(import_measurements_csv(args.csv_path, repo))
        elif args.command == "import-subjective":
            _dump(import_subjective_csv(args.csv_path, repo))
        elif args.command == "import-json":
            _dump(
                import_json_file(
                    args.json_path,
                    repo,
                    source_name=args.source,
                    source_kind=args.source_kind,
                ).as_dict()
            )
        elif args.command == "sync-folder":
            _dump(
                sync_folder(
                    args.directory,
                    repo,
                    source_name=args.source,
                    source_kind=args.source_kind,
                )
            )
        elif args.command == "sync-status":
            _dump(repo.sync_status())
        return 0
    finally:
        repo.close()


if __name__ == "__main__":
    raise SystemExit(main())
