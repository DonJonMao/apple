"""Capture real synthetic pages at fixed dates for the master redesign audit."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tests/training"), str(ROOT / "tools")]
from health_change_browser import WRAPPER  # noqa: E402
from health_change_fixture import CUTOFF, create_health_change_fixture  # noqa: E402
from product_redesign_browser_check import geometry, settle  # noqa: E402
from product_redesign_fixture import create_product_fixture  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("fixed", "empty", "old", "single"), default="fixed")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = {"data": "synthetic_only", "mode": args.mode, "cutoff": CUTOFF if args.mode == "fixed" else "current process clock", "pages": {}, "errors": []}
    with tempfile.TemporaryDirectory(prefix="hz-master-pages-") as tmp:
        folder = Path(tmp)
        result["fixture"] = (create_health_change_fixture(folder / ".local/healthzip.sqlite3") if args.mode == "fixed"
                             else create_product_fixture(folder / ".local/healthzip.sqlite3", mode=args.mode))
        wrapper = folder / "wrapper"
        wrapper.mkdir()
        (wrapper / "src").symlink_to(args.code_root / "src", target_is_directory=True)
        (wrapper / ".streamlit").symlink_to(args.code_root / ".streamlit", target_is_directory=True)
        (wrapper / "app.py").write_text(WRAPPER.format(cutoff=CUTOFF, app=str(args.code_root / "app.py")))
        with isolated_app(wrapper if args.mode == "fixed" else args.code_root, folder) as base, sync_playwright() as engine:
            browser = engine.chromium.launch(headless=True, args=["--no-sandbox"])
            result["browser"] = browser.version
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
            page.on("pageerror", lambda exc: result["errors"].append(str(exc)))
            routes = ("overview", "heart", "sleep") if args.mode == "fixed" else ("overview", "heart", "sleep", "weight", "cardio", "workouts")
            for route in routes:
                page.goto(base + "/?workspace=" + route)
                page.locator("[data-hz-render]").wait_for(state="attached", timeout=45000)
                settle(page)
                contents = page.get_by_test_id("stMain").inner_text()
                if route == "heart" and args.mode == "single":
                    assert page.get_by_test_id("stMetric").count() > 0 and "60.0 bpm" in contents
                if route == "overview" and args.mode == "old":
                    assert "最近一次" in contents
                if args.mode == "empty" and route in {"heart", "sleep", "weight", "cardio"}:
                    assert page.get_by_test_id("stMetric").count() == 0
                for width in (1440, 390):
                    page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 844})
                    page.wait_for_timeout(200)
                    page.get_by_test_id("stMain").evaluate("e => e.scrollTo(0, 0)")
                    name = route + "-" + str(width)
                    result["pages"][name] = geometry(page)
                    assert not result["pages"][name]["horizontal_overflow"], result["pages"][name]
                    page.screenshot(path=str(args.output / (name + ".png")), full_page=True)
                (args.output / (route + ".txt")).write_text(page.get_by_test_id("stMain").inner_text())
            browser.close()
    (args.output / "browser.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
