"""Real Chromium acceptance on an isolated synthetic workspace, never production."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tests/training")]
from product_redesign_fixture import create_product_fixture  # noqa: E402
from strength_workbench_browser_check import BrowserCheck, isolated_app, product_source_hashes  # noqa: E402

WIDTHS = (320, 375, 390, 430, 768, 1440)
PAGES = {"overview": "总览", "heart": "心率", "sleep": "睡眠", "weight": "体重",
         "cardio": "有氧", "workouts": "运动", "strength-home": "力量", "review": "复盘", "settings": "设置"}


def settle(page):
    page.get_by_test_id("stStatusWidget").wait_for(state="hidden", timeout=30000)
    page.wait_for_timeout(100)
    assert not page.get_by_test_id("stException").count(), page.get_by_test_id("stException").all_text_contents()


def navigate(page, label, before=False):
    radio = page.get_by_role("radio", name=label, exact=True, include_hidden=True)
    if radio.is_checked():
        settle(page)
        return
    old = page.locator('[data-hz-render]').get_attribute('data-hz-render') if not before and page.locator('[data-hz-render]').count() else None
    if not before and page.viewport_size["width"] <= 900:
        page.locator('.st-key-mobile_navigation button').first.click()
        page.get_by_test_id("stPopoverBody").wait_for(state="visible")
        settle(page)
        page.get_by_test_id("stPopoverBody").get_by_role("button", name=label, exact=True).click()
        page.get_by_test_id("stPopoverBody").wait_for(state="hidden")
    else:
        page.get_by_role("radio", name=label, exact=True).locator("xpath=ancestor::label[1]").click()
    if not before and label != "力量":
        page.get_by_role("heading", name=label, exact=True).first.wait_for()
    if not before and label != "设置":
        page.wait_for_function("old=>{const e=document.querySelector('[data-hz-render]');return e&&e.dataset.hzRender!==old}", arg=old)
    settle(page)


def geometry(page):
    return page.evaluate("""() => {
      const main=document.querySelector('[data-testid="stMain"]');
      return {viewport:innerWidth, document:document.documentElement.scrollWidth,
        main:main.scrollWidth, main_client:main.clientWidth,
        sidebar_visible:[...document.querySelectorAll('[data-testid="stSidebar"]')].some(e=>!!e.getClientRects().length),
        horizontal_overflow:[...document.querySelectorAll('input,button,[data-testid="stMetric"],iframe')]
          .filter(e=>e.getClientRects().length && !e.closest('[data-testid="stPopoverBody"]')
            && (!e.closest('details') || e.closest('details').open))
          .map(e=>({tag:e.tagName,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,html:e.outerHTML.slice(0,260),details:e.closest("details")?.open,visibility:getComputedStyle(e).visibility}))
          .filter(e=>e.left < -1 || e.right>innerWidth+1)};
    }""")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--before-root")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--mode", choices=("normal", "empty", "old", "single"), default="normal")
    args = parser.parse_args()
    before = bool(args.before_root)
    source_root = Path(args.before_root).resolve() if before else ROOT
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"data": "synthetic_only", "mode": args.mode, "kind": "real_chromium_browser",
              "real_mobile_safari_keyboard": "not_verified", "pages": {}, "errors": []}
    with tempfile.TemporaryDirectory(prefix="healthzip-product-browser-") as temporary:
        folder = Path(temporary)
        database = folder / ".local/healthzip.sqlite3"
        report["fixture"] = create_product_fixture(database, mode=args.mode)
        with isolated_app(source_root, folder) as base, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            report["browser"] = browser.version
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
            page = context.new_page()
            page.on("pageerror", lambda error: report["errors"].append(str(error)))
            page.goto(base)
            page.get_by_role("radio", name="导入与总览" if before else "总览", exact=True).wait_for()
            settle(page)
            check = BrowserCheck(page, database, output)
            labels = {"overview": "导入与总览", "heart": "心率 / HRV", "sleep": "睡眠",
                      "weight-cardio": "体重 / 有氧", "strength-home": "力量"} if before else PAGES
            for name, label in labels.items():
                page.set_viewport_size({"width": 1440, "height": 1000})
                navigate(page, label, before)
                if label == "力量":
                    check.wait(lambda: check.testid("strength-home").is_visible())
                measurements = []
                for width in ((1440, 390) if args.quick or before else WIDTHS):
                    page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 844})
                    check.close_mobile_sidebar()
                    page.wait_for_timeout(300)
                    dims = geometry(page)
                    deadline = time.monotonic() + 5
                    while dims["horizontal_overflow"] and time.monotonic() < deadline:
                        page.wait_for_timeout(100)
                        dims = geometry(page)
                    if not before:
                        assert not dims["sidebar_visible"], dims
                        assert dims["document"] <= dims["viewport"] and dims["main"] <= dims["main_client"], dims
                        assert not dims["horizontal_overflow"], dims
                    measurements.append(dims)
                    if width in (1440, 390):
                        page.get_by_test_id("stMain").evaluate("e=>e.scrollTo(0,0)")
                        page.screenshot(path=str(output / f"{name}-{width}.png"))
                report["pages"][name] = measurements
                print("PASS", name, flush=True)
            if not before and not args.quick:
                # Every top menu destination is operable at phone width.
                page.set_viewport_size({"width": 390, "height": 844})
                for label in PAGES.values():
                    navigate(page, label)
                report["mobile_top_menu"] = "all_nine_destinations_passed"
                # Scope switching through visible controls changes the factual window.
                navigate(page, "心率")
                windows = []
                for label in ("本周", "本月", "近30天"):
                    old = page.locator('[data-hz-render]').get_attribute('data-hz-render')
                    page.get_by_role("radio", name=label, exact=True).locator("xpath=ancestor::label[1]").click()
                    page.wait_for_function("old=>document.querySelector('[data-hz-render]')?.dataset.hzRender!==old", arg=old)
                    settle(page)
                    windows.append(page.get_by_text("所选范围：", exact=False).first.inner_text())
                assert len(set(windows)) >= 2
                report["range_switch"] = windows
                samples = []
                for _ in range(30):
                    navigate(page, "体重")
                    started = time.perf_counter()
                    navigate(page, "心率")
                    page.get_by_test_id("stMetric").first.wait_for() if args.mode != "empty" else None
                    samples.append((time.perf_counter() - started) * 1000)
                sorted_samples = sorted(samples)
                report["warm_click_to_settled_ms"] = {"samples": samples, "p50": sorted_samples[14], "p95": sorted_samples[28],
                    "definition": "visible navigation click until Streamlit run idle plus 100ms settling; local Chromium, includes client interaction"}
            report["source_sha256"] = product_source_hashes(source_root)
            report["status"] = "passed"
            (output / "browser-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            assert not report["errors"], report["errors"]
            context.close()
            browser.close()
    print(json.dumps({"status": report["status"], "pages": list(report["pages"]), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
