"""Verify the warm theme through the real app using isolated synthetic data.

This development-only Playwright check blocks external HTTP(S), exercises the
existing workspaces, and records computed styles, screenshots and source hashes.
It never resolves the app's database or knowledge directory to production.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright
from strength_browser_fixture import create_fixture
from strength_workbench_browser_check import BrowserCheck, isolated_app, product_source_hashes
from workspace_summary_browser_check import create_body_fixture, settled

WORKSPACES = (
    "导入与总览", "数据质量", "心率 / HRV", "睡眠", "运动", "体重 / 有氧",
    "力量", "分析", "周期", "报告",
)
WIDTHS = (320, 375, 390, 430, 1440)

COLOR_EVIDENCE = """element => {
    const rgba = value => {
        const values = value.match(/[\\d.]+/g)?.map(Number) || [0, 0, 0, 0];
        return [...values.slice(0, 3), values.length > 3 ? values[3] : 1];
    };
    const over = (top, bottom) => top.slice(0,3).map((n,i) =>
        n * top[3] + bottom[i] * (1-top[3]));
    const ancestors = [];
    for (let node = element; node; node = node.parentElement) ancestors.unshift(node);
    let background = [255,255,255];
    for (const node of ancestors) background = over(rgba(getComputedStyle(node).backgroundColor), background);
    const style = getComputedStyle(element);
    const effectiveOpacity = ancestors.reduce((value,node)=>value*Number(getComputedStyle(node).opacity),1);
    const textColor = rgba(style.color);
    textColor[3] *= effectiveOpacity;
    const foreground = over(textColor, background);
    const luminance = values => values.map(n => n/255).map(n =>
        n <= .04045 ? n/12.92 : ((n+.055)/1.055)**2.4)
        .reduce((n,v,i) => n+v*[.2126,.7152,.0722][i],0);
    const a = luminance(foreground), b = luminance(background);
    return {color:style.color, background, font_family:style.fontFamily,
        font_size:style.fontSize, font_weight:style.fontWeight,
        contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),
        opacity:style.opacity, effective_opacity:effectiveOpacity,
        outline:style.outline, box_shadow:style.boxShadow,
        focus_visible:element.matches(':focus-visible')};
}"""


class ThemeCheck:
    def __init__(self, page, database, output, report):
        self.page = page
        self.output = output
        self.report = report
        self.strength = BrowserCheck(page, database, output)

    def passed(self, name, **evidence):
        self.report["results"][name] = {"status": "passed", **evidence}
        print("PASS " + name, flush=True)

    def workspace(self, name):
        radio = self.page.get_by_role("radio", name=name, exact=True)
        radio.locator("xpath=ancestor::label[1]").click()
        self.strength.wait(lambda: radio.is_checked(), "workspace " + name)
        settled(self.page)
        assert not self.page.get_by_test_id("stException").count()
        self.strength.close_mobile_sidebar()

    def outer_widths(self, name):
        evidence = []
        for width in WIDTHS:
            self.page.set_viewport_size({"width": width, "height": 1000 if width > 600 else 900})
            self.page.wait_for_timeout(180)
            self.strength.close_mobile_sidebar()
            settled(self.page)
            self.page.wait_for_function("""() => {
                const main=document.querySelector('[data-testid="stMain"]');
                return document.documentElement.scrollWidth<=document.documentElement.clientWidth &&
                    document.body.scrollWidth<=document.documentElement.clientWidth &&
                    main.scrollWidth<=main.clientWidth;
            }""", timeout=5000)
            dimensions = self.page.evaluate("""() => ({
                viewport:document.documentElement.clientWidth,
                document:document.documentElement.scrollWidth,
                body:document.body.scrollWidth,
                main:document.querySelector('[data-testid="stMain"]')?.scrollWidth,
                main_client:document.querySelector('[data-testid="stMain"]')?.clientWidth
            })""")
            assert dimensions["document"] <= dimensions["viewport"], dimensions
            assert dimensions["body"] <= dimensions["viewport"], dimensions
            assert dimensions["main"] <= dimensions["main_client"], dimensions
            navigation = self.page.locator(".st-key-workspace_navigation")
            assert navigation.get_by_role("radio").count() == len(WORKSPACES)
            assert navigation.get_by_role("radio", name="力量", exact=True).is_visible()
            chrome = self.page.get_by_test_id("stHeader").bounding_box()
            for selector in (".earthy-brand", ".st-key-shell_open_training button"):
                rectangle = self.page.locator(selector).bounding_box()
                assert rectangle["y"] >= chrome["y"] + chrome["height"], rectangle
            brand = self.page.locator(".earthy-brand").bounding_box()
            title = self.page.get_by_role("heading", name="训练与健康记录", exact=True).bounding_box()
            assert title["y"] >= brand["y"] + brand["height"] - 1, {"brand": brand, "title": title}
            stats = self.page.locator(".st-key-earthy_overview_stats")
            if name in {"overview", "导入与总览"}:
                date_value = stats.get_by_test_id("stMetricValue").first
                date_text = date_value.locator("p").first
                assert date_text.inner_text() == self.report["body_fixture"]["recent"][:10]
                text_geometry = date_text.evaluate("""e=>{
                    const range=document.createRange();range.selectNodeContents(e);
                    const r=range.getBoundingClientRect();
                    const metric=e.closest('[data-testid="stMetric"]').getBoundingClientRect();
                    return {left:r.left,right:r.right,metric_left:metric.left,metric_right:metric.right,
                        family:getComputedStyle(e).fontFamily,overflow:getComputedStyle(e).overflow};
                }""")
                assert text_geometry["left"] >= text_geometry["metric_left"] - 1, text_geometry
                assert text_geometry["right"] <= text_geometry["metric_right"] + 1, text_geometry
                assert "Fraunces" in text_geometry["family"], text_geometry
                dimensions["date_text_geometry"] = text_geometry
            evidence.append({"width": width, **dimensions})
        self.passed("widths_" + name, measurements=evidence)

    def contrast(self, name, locator, minimum=4.5):
        locator.first.wait_for(state="visible")
        measurement = locator.first.evaluate(COLOR_EVIDENCE)
        assert measurement["contrast"] >= minimum, {"sample": name, **measurement}
        if name in {"hero_body", "stats_label", "selected_navigation", "summary_caption"}:
            assert "Inter" in measurement["font_family"], {"sample": name, **measurement}
        self.passed("contrast_" + name, minimum=minimum, **measurement)

    def keyboard_focus(self, name, locator):
        locator.focus()
        keyboard = self.page.keyboard
        keyboard.press("Tab")
        keyboard.press("Shift+Tab")
        measurement = locator.evaluate(COLOR_EVIDENCE)
        focused = locator.evaluate("e => e === document.activeElement")
        assert focused and measurement["focus_visible"], measurement
        assert measurement["outline"] != "none" and not measurement["outline"].startswith("none"), measurement
        assert " 0px" not in measurement["outline"], measurement
        self.passed("keyboard_focus_" + name, focused=focused, **measurement)

    def screenshot(self, name, *, full_content=False):
        settled(self.page)
        self.strength.close_mobile_sidebar()
        original = self.page.viewport_size
        if full_content:
            height = self.page.get_by_test_id("stMain").evaluate("e=>e.scrollHeight") + 80
            self.page.set_viewport_size({"width": original["width"], "height": min(height, 6000)})
            self.page.get_by_test_id("stMain").evaluate("e=>e.scrollTo(0,0)")
            self.page.wait_for_timeout(250)
        self.page.screenshot(path=str(self.output / name), full_page=True)
        if full_content:
            self.page.set_viewport_size(original)

    def overview(self):
        self.page.set_viewport_size({"width": 1440, "height": 1100})
        self.workspace("导入与总览")
        hero = self.page.locator(".st-key-earthy_overview_hero")
        assert hero.is_visible()
        image = hero.locator("img").first
        image.wait_for(state="visible")
        photo = image.evaluate("""async image => {
            await image.decode();
            return {source_type:image.src.startsWith('data:image/')?'embedded':'other',
                    width:image.naturalWidth,height:image.naturalHeight,
                    radius:getComputedStyle(image).borderRadius,alt:image.alt};
        }""")
        assert photo["source_type"] == "embedded" and photo["width"] > 500
        assert photo["alt"]
        fonts = self.page.evaluate("""async () => {
            await document.fonts.load('600 24px Fraunces', 'Loam');
            await document.fonts.load('400 16px Inter', 'Health');
            await document.fonts.ready;
            return {fraunces:document.fonts.check('600 24px Fraunces','Loam'),
                    inter:document.fonts.check('400 16px Inter','Health'),
                    loaded:[...document.fonts].filter(f=>f.status==='loaded')
                        .map(f=>({family:f.family,status:f.status,style:f.style}))};
        }""")
        assert fonts["fraunces"] and fonts["inter"]
        assert any("Fraunces" in font["family"] for font in fonts["loaded"])
        assert any("Inter" in font["family"] for font in fonts["loaded"])
        stats = self.page.locator(".st-key-earthy_overview_stats")
        assert stats.get_by_test_id("stMetric").count() == 4
        assert "已有数据项目" in stats.inner_text()
        metric_style = stats.get_by_test_id("stMetric").first.evaluate("""e=>({
            background:getComputedStyle(e).backgroundColor,border:getComputedStyle(e).borderWidth
        })""")
        assert metric_style["background"] == "rgba(0, 0, 0, 0)", metric_style
        assert metric_style["border"] == "0px", metric_style
        assert "HealthZIP Serif SC" in hero.locator("h2").evaluate("e=>getComputedStyle(e).fontFamily")
        for value in stats.get_by_test_id("stMetricValue").all():
            assert "Fraunces" in value.locator("p").first.evaluate("e=>getComputedStyle(e).fontFamily")
        assert self.page.locator(".overview-workspace-card").count() == 4
        self.passed("local_photo_fonts_and_real_stats", photo=photo, fonts=fonts,
                    stats=stats.inner_text(), metric_style=metric_style, cards=4)
        self.contrast("heading", self.page.get_by_role("heading", name="训练与健康记录", exact=True))
        self.contrast("hero_heading", hero.locator("h2"), 3)
        self.contrast("hero_emphasis", hero.locator("h2 em"), 3)
        self.contrast("hero_body", hero.locator("p").first)
        self.contrast("main_primary", self.page.locator(".st-key-overview_open_training button"))
        self.contrast("stats_value", stats.get_by_test_id("stMetricValue").first)
        self.contrast("stats_label", stats.get_by_test_id("stMetricLabel").first)
        self.contrast("stats_note", stats.locator(".overview-stats"))
        self.contrast("summary_caption", self.page.locator(".st-key-earthy_summary [data-testid=stCaptionContainer] p"))
        self.contrast("card_record_date", self.page.locator(".overview-card-date").first)
        selected_option = self.page.get_by_role("radio", name="导入与总览", exact=True).locator("xpath=ancestor::label[1]")
        selected_style = selected_option.evaluate("""e=>({background:getComputedStyle(e).backgroundColor,
            radius:getComputedStyle(e).borderRadius})""")
        assert selected_style["background"] != "rgba(0, 0, 0, 0)", selected_style
        assert float(selected_style["radius"].split("px")[0]) >= 18, selected_style
        circle = selected_option.locator(":scope > div > div:first-child:not([data-testid=stMarkdownContainer])")
        assert circle.count() == 1 and circle.evaluate("e=>getComputedStyle(e).display") == "none"
        self.contrast("selected_navigation", selected_option.locator("p"))
        self.passed("pill_workspace_navigation", native_circle_hidden=True, **selected_style)
        self.keyboard_focus("main_primary", self.page.locator(".st-key-overview_open_training button"))
        chrome = self.page.get_by_test_id("stHeader").bounding_box()
        for locator in (self.page.locator(".earthy-brand"),
                        self.page.locator(".st-key-shell_open_training button")):
            rectangle = locator.bounding_box()
            assert rectangle["y"] >= chrome["y"] + chrome["height"], rectangle
        self.screenshot("overview-desktop.png")
        self.screenshot("overview-desktop-full.png", full_content=True)
        self.outer_widths("overview")
        self.page.set_viewport_size({"width": 375, "height": 1000})
        self.screenshot("overview-mobile.png")

    def mobile_import_sidebar(self):
        self.page.set_viewport_size({"width": 375, "height": 1000})
        self.strength.close_mobile_sidebar()
        opener = self.page.get_by_role("button", name="Expand sidebar", exact=True)
        opener.wait_for(state="visible")
        assert opener.is_enabled()
        opener.click()
        sidebar = self.page.get_by_test_id("stSidebar")
        self.strength.wait(lambda: sidebar.bounding_box()["x"] >= -1, "sidebar reopened")
        settings = sidebar.get_by_text("导入与存储设置", exact=True)
        settings.click()
        sidebar.get_by_role("textbox", name="SQLite 路径", exact=True).wait_for(state="visible")
        self.strength.close_mobile_sidebar()
        assert opener.is_visible()
        self.passed("mobile_import_sidebar", real_expand_button=True,
                    import_settings_reopened=True, closed_again=True)

    def sticky_header(self):
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.workspace("导入与总览")
        header = self.page.locator(".st-key-earthy_app_header")
        navigation = self.page.locator(".st-key-workspace_navigation")
        main = self.page.get_by_test_id("stMain")
        main.evaluate("e=>e.scrollTo(0,0)")
        self.page.wait_for_timeout(200)
        before = header.bounding_box()
        main.evaluate("e=>e.scrollTo(0,600)")
        self.page.wait_for_timeout(350)
        after = header.bounding_box()
        positions = {
            "before": before, "after": after,
            "actual_scroll": main.evaluate("e=>e.scrollTop"),
            "header_style": header.evaluate("""e=>{
                let sticky=e;
                while(sticky && getComputedStyle(sticky).position!=='sticky')sticky=sticky.parentElement;
                return {position:getComputedStyle(e).position,
                    sticky_ancestor:sticky?{tag:sticky.tagName,testid:sticky.dataset.testid}:null,
                    backdrop:getComputedStyle(e).backdropFilter};
            }"""),
            "navigation_style": navigation.evaluate("e=>({position:getComputedStyle(e).position,top:getComputedStyle(e).top})"),
        }
        assert positions["actual_scroll"] > 100, positions
        assert after and after["y"] >= -1 and after["y"] <= before["y"] + 2, positions
        assert positions["header_style"]["sticky_ancestor"], positions
        assert "blur" in positions["header_style"]["backdrop"], positions
        self.passed("sticky_blurred_header", **positions)
        main.evaluate("e=>e.scrollTo(0,0)")

    def four_card_navigation(self):
        destinations = (("查看睡眠记录", "睡眠"), ("查看心率记录", "心率 / HRV"),
                        ("查看运动记录", "运动"), ("查看体重与有氧", "体重 / 有氧"))
        for button, destination in destinations:
            self.workspace("导入与总览")
            self.page.get_by_role("button", name=button, exact=True).click()
            settled(self.page)
            assert self.page.get_by_role("radio", name=destination, exact=True).is_checked()
            assert not self.page.get_by_test_id("stException").count()
        self.passed("four_real_workspace_cards", destinations=dict(destinations))

    def all_workspaces(self):
        visited = []
        for name in WORKSPACES:
            self.workspace(name)
            assert self.page.get_by_role("heading", name="训练与健康记录", exact=True).is_visible()
            assert self.page.locator(".earthy-brand").is_visible()
            assert self.page.get_by_text("当前数据分析", exact=True).is_visible()
            self.outer_widths(name)
            visited.append(name)
        self.passed("all_ten_workspaces", names=visited, common_header_and_navigation=True)

    def body_summary(self):
        self.page.set_viewport_size({"width": 375, "height": 1000})
        self.workspace("睡眠")
        periods = {}
        for label in ("本周", "本月"):
            self.page.get_by_role("radio", name=label, exact=True).locator("xpath=ancestor::label[1]").click()
            settled(self.page)
            text = self.page.get_by_test_id("stMain").inner_text()
            assert label + "：" in text and "平均" in text and "合成摘要手表" in text
            assert "synthetic-summary-device" not in text
            periods[label] = {"conclusion_visible": True, "real_source_visible": True}
        self.screenshot("sleep-mobile.png")
        self.passed("sleep_week_and_month", periods=periods)

    def strength_theme(self):
        self.page.set_viewport_size({"width": 390, "height": 1000})
        self.workspace("力量")
        check = self.strength
        check.wait(lambda: check.testid("strength-home").is_visible(), "strength home")
        self.contrast("strength_heading", check.frame.get_by_role("heading", name="力量训练", exact=True), 3)
        self.contrast("strength_body", check.frame.locator(".hero p"))
        self.contrast("strength_primary", check.testid("start-training"))
        self.screenshot("strength-home-mobile.png")
        check.testid("start-training").click()
        check.testid("start-free-training").click()
        check.wait(lambda: check.testid("catalog-search").is_visible(), "action picker")
        check.testid("catalog-search").fill("杠铃卧推")
        check.wait(lambda: check.frame.locator(".catalog-card").count() == 1, "one catalog result")
        check.frame.locator(".catalog-card").get_by_role("button", name="添加", exact=True).click()
        check.testid("catalog-confirm").click()
        check.wait(lambda: check.frame.locator(".exercise-card").count() == 1, "one recorded exercise")
        session = check.active()
        identity = session["sets"][0]["set_uuid"]
        check.fill_row(identity, load="32.5", quantity="8")
        field = check.row(identity).locator('[data-field="load_value"]')
        self.contrast("strength_input", field)
        self.keyboard_focus("strength_input", field)
        check.complete_row(identity)
        check.wait(lambda: check.active()["completed_sets"] == 1, "completed set committed")
        self.contrast("strength_completed", check.row(identity).locator(".set-state"))
        self.contrast("strength_completed_button", check.row(identity).locator(".complete-button"), 3)
        check.assert_widths("earthy_completed_set")
        self.report["results"].update(check.results)
        self.page.set_viewport_size({"width": 390, "height": 1000})
        check.row(identity).scroll_into_view_if_needed()
        self.screenshot("strength-record-mobile.png")
        self.page.set_viewport_size({"width": 1440, "height": 1100})
        check.wait(lambda: check.frame.evaluate("innerWidth") >= 760, "desktop component resize")
        check.row(identity).scroll_into_view_if_needed()
        self.screenshot("strength-record-desktop.png")
        self.passed("real_strength_record_with_new_theme", load=32.5, reps=8, rir=None,
                    template=False, production_untouched=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--chromium", help="Optional local Chromium executable")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    hashes = product_source_hashes(root)
    report = {"data": "synthetic_only", "entrypoint": "app.py", "results": {},
              "checked_at": datetime.now(timezone.utc).isoformat(),
              "tested_source_sha256": hashes, "real_iphone_keyboard": "not_verified"}
    external, errors = [], []
    try:
        with tempfile.TemporaryDirectory(prefix="synthetic-earthy-ui-") as temporary:
            folder = Path(temporary)
            database = folder / ".local/healthzip.sqlite3"
            create_fixture(database)
            report["body_fixture"] = create_body_fixture(database)
            with isolated_app(root, folder) as base, sync_playwright() as playwright:
                options = {"headless": True, "args": ["--no-sandbox"]}
                if args.chromium:
                    options["executable_path"] = args.chromium
                browser = playwright.chromium.launch(**options)
                report["browser"] = browser.version
                context = browser.new_context(viewport={"width": 1440, "height": 1100})

                def local_only(route):
                    if route.request.url.startswith(base + "/"):
                        route.continue_()
                    else:
                        external.append(route.request.url)
                        route.abort()

                context.route("http**/*", local_only)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base)
                page.get_by_role("heading", name="训练与健康记录", exact=True).wait_for()
                check = ThemeCheck(page, database, output, report)
                check.overview()
                check.mobile_import_sidebar()
                check.sticky_header()
                check.four_card_navigation()
                check.all_workspaces()
                check.body_summary()
                check.strength_theme()
                assert not errors and not external, {"errors": errors, "external": external}
                assert product_source_hashes(root) == hashes, "Product source changed during browser run"
                report.update(status="passed", sources_unchanged_during_run=True)
                context.close()
                browser.close()
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        report.update(external_requests=external, page_errors=errors)
        (output / "earthy-browser-results.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"status": report["status"], "checks": len(report["results"])}))


if __name__ == "__main__":
    main()
