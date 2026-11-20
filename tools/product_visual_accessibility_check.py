"""Measure actual theme contrast, keyboard focus and touch areas in Chromium."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tests/training"), str(ROOT / "tools")]
from earthy_ui_browser_check import COLOR_EVIDENCE  # noqa: E402
from product_redesign_browser_check import navigate, settle  # noqa: E402
from product_redesign_fixture import create_product_fixture  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402


def color(locator):
    locator.first.wait_for(state="visible")
    result = locator.first.evaluate(COLOR_EVIDENCE)
    result["minimum"] = 4.5
    result["passed"] = result["contrast"] >= 4.5
    return result


def touch(locator):
    locator.first.scroll_into_view_if_needed()
    rectangle = locator.first.bounding_box()
    return {"width": rectangle["width"], "height": rectangle["height"],
            "minimum": 44, "passed": rectangle["width"] >= 43.5 and rectangle["height"] >= 43.5}


def focus(page, locator, ring=None):
    locator.first.focus()
    page.keyboard.press("Tab")
    page.keyboard.press("Shift+Tab")
    active = locator.first.evaluate("e => e === document.activeElement")
    visible = locator.first.evaluate("e => e.matches(':focus-visible')")
    measurement = (ring or locator).first.evaluate(COLOR_EVIDENCE)
    outline = measurement["outline"]
    outline_visible = "none" not in outline and "0px" not in outline
    shadow = measurement["box_shadow"]
    # Streamlit uses a genuine box-shadow focus ring on buttons and summaries.
    # Accept that visible ring, rather than requiring one CSS implementation.
    shadow_ring = re.search(r"0px 0px 0px ([0-9.]+)px", shadow)
    shadow_visible = bool(shadow_ring and float(shadow_ring.group(1)) >= 2)
    return {"active": active, "focus_visible": visible, "outline": outline,
            "box_shadow": measurement["box_shadow"],
            "passed": active and visible and (outline_visible or shadow_visible)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    report = {"data": "synthetic_only", "kind": "real_chromium_computed_styles",
              "method": "existing COLOR_EVIDENCE alpha compositing and WCAG luminance; 4.5:1 minimum",
              "real_device": "not_verified", "viewports": {}, "errors": []}
    with tempfile.TemporaryDirectory(prefix="healthzip-visual-accessibility-") as temporary:
        folder = Path(temporary)
        create_product_fixture(folder / ".local/healthzip.sqlite3")
        with isolated_app(ROOT, folder) as base, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            report["browser"] = browser.version
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
            page = context.new_page()
            page.on("pageerror", lambda error: report["errors"].append(str(error)))
            page.goto(base)
            page.get_by_role("radio", name="总览", exact=True).wait_for()
            settle(page)
            for width in (1440, 390):
                page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 844})
                navigate(page, "总览")
                primary = page.get_by_role("button", name="开始训练", exact=True)
                results = {"contrast": {"primary_button": color(primary.locator("p"))},
                           "touch": {"primary_button": touch(primary)},
                           "focus": {"primary_button": focus(page, primary)}}
                navigate(page, "心率")
                page.get_by_role("radio", name="近30天", exact=True).locator("xpath=ancestor::label[1]").click()
                settle(page)
                results["contrast"].update({
                    "caption": color(page.get_by_test_id("stCaptionContainer").filter(has_text="所选范围").first.locator("p")),
                    "metric_label": color(page.get_by_test_id("stMetricLabel").first.locator("p")),
                    "body_text": color(page.get_by_text("本期首末记录相差", exact=False).first),
                    "metric_value": color(page.get_by_test_id("stMetricValue").first.locator("div").first),
                })
                period_input = page.get_by_role("radio", name="近30天", exact=True)
                period = period_input.locator("xpath=ancestor::label[1]")
                results["contrast"]["selected_period"] = color(period.locator("p"))
                results["touch"]["period"] = touch(period)
                results["focus"]["period"] = focus(page, period_input, period)
                details = page.get_by_test_id("stExpander").filter(has_text="原始明细").locator("summary")
                results["touch"]["details"] = touch(details)
                results["focus"]["details"] = focus(page, details)
                if width > 900:
                    nav_input = page.get_by_role("radio", name="心率", exact=True)
                    nav = nav_input.locator("xpath=ancestor::label[1]")
                    results["contrast"]["selected_navigation"] = color(nav.locator("p"))
                    results["touch"]["navigation"] = touch(nav)
                    results["focus"]["navigation"] = focus(page, nav_input, nav)
                else:
                    menu = page.locator(".st-key-mobile_navigation button").first
                    results["touch"]["menu"] = touch(menu)
                    results["focus"]["menu"] = focus(page, menu)
                    menu.click()
                    nav = page.get_by_test_id("stPopoverBody").get_by_role("button", name="心率", exact=True)
                    results["contrast"]["selected_navigation"] = color(nav.locator("p"))
                    results["touch"]["navigation"] = touch(nav)
                    results["focus"]["navigation"] = focus(page, nav)
                    page.keyboard.press("Escape")
                page.get_by_role("radio", name="自定义", exact=True).locator("xpath=ancestor::label[1]").click()
                settle(page)
                numeric = page.get_by_role("spinbutton", name="最近天数")
                results["touch"]["number_input"] = touch(numeric)
                results["focus"]["number_input"] = focus(page, numeric)
                results["number_input_font_px"] = numeric.evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
                results["passed"] = all(entry["passed"] for section in ("contrast", "touch", "focus") for entry in results[section].values()) and results["number_input_font_px"] >= 16
                report["viewports"][str(width)] = results
            context.close()
            browser.close()
    report["css_sha256"] = hashlib.sha256((ROOT / "src/healthzip/ui/assets/theme.css").read_bytes()).hexdigest()
    report["status"] = "passed" if all(view["passed"] for view in report["viewports"].values()) and not report["errors"] else "failed"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
