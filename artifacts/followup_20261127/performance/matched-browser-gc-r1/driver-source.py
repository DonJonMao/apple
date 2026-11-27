"""One real synthetic report click, with live worker subphases and thread stacks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/training"))
from followup_report_benchmark import raw_identity, validate_synthetic  # noqa: E402
from repair_preview_benchmark import fixture_copy  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402

INSTRUMENT = '''
import functools, gc, importlib, json, sys, threading, time, traceback
from pathlib import Path
_output = Path(OUTPUT)
_events = (_output / "worker-events.jsonl").open("w")
_stacks = (_output / "worker-stacks.txt").open("w")
_start = time.perf_counter()
_lock = threading.RLock()
def event(name, **fields):
    with _lock:
        _events.write(json.dumps({"elapsed_s": time.perf_counter()-_start,
            "event": name, "thread": threading.current_thread().name, **fields}, ensure_ascii=False)+"\\n")
        _events.flush()
def gc_event(phase, info):
    if info["generation"] == 2:
        event("gc:"+phase, **info)
gc.callbacks.append(gc_event)
def wrap(module, name):
    original = getattr(module, name)
    @functools.wraps(original)
    def measured(*args, **kwargs):
        started = time.perf_counter()
        label = module.__name__+"."+name
        event(label+":start")
        try:
            return original(*args, **kwargs)
        finally:
            event(label+":end", seconds=time.perf_counter()-started)
    setattr(module, name, measured)
for module, names in {
    "healthzip.workflows.period_report": ("create_report", "period_facts", "period_questions", "review_analysis", "persist"),
    "healthzip.analytics.body_metrics": ("analyze_questions",),
    "healthzip.analytics.body_questions": ("_training", "_strength_rows", "_render_question"),
    "healthzip.workflows.longitudinal": ("ordinary_review",),
    "healthzip.knowledge.topics": ("question_sources",),
}.items():
    for name in names:
        wrap(importlib.import_module(module), name)
def sample_stacks():
    while True:
        time.sleep(20)
        _stacks.write(f"Elapsed {time.perf_counter()-_start:.3f}s\\n")
        for identity, frame in sys._current_frames().items():
            _stacks.write(f"Thread {identity}\\n"+"".join(traceback.format_stack(frame)))
        _stacks.flush()
threading.Thread(target=sample_stacks, daemon=True).start()
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--knowledge-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-ms", type=int, default=240000)
    parser.add_argument("--post-script-gc", choices=("default", "false"), default="default")
    args = parser.parse_args()
    source, folder, output = args.source_root.resolve(), args.workspace.resolve(), args.output.resolve()
    assert not folder.exists() and not output.exists()
    validate_synthetic(args.fixture)
    output.mkdir(parents=True)
    database, counts = fixture_copy(args.fixture, folder)
    with closing(sqlite3.connect(database)) as conn:
        before = raw_identity(conn)
    (folder / ".local/knowledge").symlink_to(args.knowledge_root.resolve(), target_is_directory=True)
    bootstrap = folder / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "src").symlink_to(source / "src", target_is_directory=True)
    (bootstrap / ".streamlit").mkdir()
    config = (source / ".streamlit/config.toml").read_text()
    if args.post_script_gc == "false":
        config += "\n[runner]\npostScriptGC = false\n"
    (bootstrap / ".streamlit/config.toml").write_text(config)
    (bootstrap / "diagnostic_instrument.py").write_text(INSTRUMENT.replace("OUTPUT", repr(str(output))))
    (bootstrap / "app.py").write_text(
        "import sys,runpy,importlib\n"
        f"sys.path.insert(0,{str(bootstrap)!r})\nimport diagnostic_instrument\n"
        "import streamlit as st\nfrom datetime import datetime\n"
        "class RequestClock(datetime):\n @classmethod\n def now(cls,tz=None):\n"
        "  value=datetime.fromisoformat('2026-11-21T16:00:00+00:00')\n"
        "  return value.astimezone(tz) if tz else value.replace(tzinfo=None)\n"
        "for name in ('healthzip.analytics.workspaces','healthzip.analytics.workspace_summary'):\n"
        " importlib.import_module(name).datetime=RequestClock\n"
        "st.session_state.setdefault('review_period','本周')\n"
        f"runpy.run_path({str(source / 'app.py')!r},run_name='__main__')\n")
    hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (source / "src").rglob("*.py")}
    receipt = {"diagnostic_only": True, "source": str(source), "source_hashes": hashes,
               "counts": counts, "fixture": str(args.fixture), "workspace": str(folder),
               "cutoff": "2026-11-21T16:00:00+00:00", "initial_load": os.getloadavg(),
               "post_script_gc": args.post_script_gc, "effective_config": config,
               "automatic_python_gc_enabled": True}
    (output / "driver-source.py").write_bytes(Path(__file__).read_bytes())
    (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    started = None
    try:
        with isolated_app(bootstrap, folder) as base, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
            page = context.new_page()
            try:
                page.goto(base + "/?workspace=review")
                generate = page.get_by_role("button", name="生成当前周期复盘", exact=True)
                generate.wait_for(timeout=90000)
                page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
                started = time.perf_counter()
                generate.click()
                page.locator("[data-hz-report-id]").wait_for(timeout=args.timeout_ms)
                receipt.update(complete=True, report_id=page.locator("[data-hz-report-id]").get_attribute("data-hz-report-id"))
            except Exception as exc:
                receipt.update(complete=False, failure=repr(exc))
            finally:
                receipt["click_to_observed_end_s"] = time.perf_counter()-started if started else None
                page.screenshot(path=str(output / "observed-end.png"), full_page=True)
                (output / "observed-end.html").write_text(page.content())
                (output / "observed-end.txt").write_text(page.get_by_test_id("stMain").inner_text())
                browser.close()
    finally:
        shutil.copy2(folder / "synthetic-streamlit.log", output / "streamlit.txt")
        with closing(sqlite3.connect(database)) as conn:
            receipt["raw_before"] = before
            receipt["raw_after"] = raw_identity(conn)
            receipt["raw_unchanged"] = receipt["raw_before"] == receipt["raw_after"]
            receipt["reports_after"] = [row[0] for row in conn.execute("SELECT report_id FROM joint_period_report")]
        receipt["source_changes"] = [name for name, digest in hashes.items() if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest]
        receipt["final_load"] = os.getloadavg()
        (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
