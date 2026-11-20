"""Full-app search timing, from browser input through painted current results."""

from __future__ import annotations

import argparse
import json
import tempfile
from contextlib import closing
from pathlib import Path

from playwright.sync_api import sync_playwright
from product_redesign_training_browser import RedesignCheck, percentile
from strength_browser_fixture import create_fixture
from strength_workbench_browser_check import isolated_app

from healthzip.db.repository import Repository
from healthzip.training.service import TrainingService

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/product_redesign/training/training-search-results.json"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="training-search-") as temp:
        folder = Path(temp)
        database = folder / ".local/healthzip.sqlite3"
        database.parent.mkdir()
        create_fixture(database)
        with closing(Repository(database)) as repo:
            svc = TrainingService(repo)
            svc.add_alias("psa.ex.barbell_bench_press", "合成别名")
            svc.favorite("psa.ex.barbell_bench_press")
        with isolated_app(ROOT, folder) as base, sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.add_init_script("window.__catalogCommands=0;window.addEventListener('message',e=>{if(e.data?.type==='streamlit:setComponentValue')window.__catalogCommands++})")
            page.goto(base + "/?workspace=strength")
            check = RedesignCheck(page, database, args.output.parent)
            check.wait(lambda: check.testid("strength-home").is_visible(), timeout=60000)
            check.click("open-start")
            check.click("open-catalog")
            commands = page.evaluate("window.__catalogCommands")
            samples = []
            for query in ["卧推", "夹胸", "合成别名", "press", "no-synthetic-result"] * 6:
                samples.append(check.frame.evaluate("""query=>new Promise((resolve,reject)=>{
                    const start=performance.now(), input=document.querySelector('[data-search="catalog"]');
                    const timer=setTimeout(()=>{observer.disconnect();reject(Error('no current search result'))},5000);
                    function ready(){
                        const list=document.querySelector('[data-catalog-query]');
                        if(list?.dataset.catalogQuery!==query)return;
                        observer.disconnect();clearTimeout(timer);
                        requestAnimationFrame(()=>resolve(performance.now()-start));
                    }
                    const observer=new MutationObserver(ready);observer.observe(document.querySelector('#app'),{childList:true,subtree:true,attributes:true});
                    input.value=query;input.dispatchEvent(new Event('input',{bubbles:true}));
                })""", query))
                actual = check.frame.locator('[data-action="catalog-select"]').evaluate_all("rows=>rows.map(row=>row.dataset.id)")
                expected = check.service_read(lambda svc: [row["exercise_id"] for row in svc.search_catalog(query)["items"]])
                assert actual == expected, (query, actual, expected)
            assert page.evaluate("window.__catalogCommands") == commands
            check.click("catalog-clear")
            check.click("catalog-view", "favorites")
            assert check.action("catalog-select", "psa.ex.barbell_bench_press").count() == 1
            check.click("catalog-info", "psa.ex.barbell_bench_press")
            check.click("favorite", "psa.ex.barbell_bench_press")
            assert not check.action("catalog-select", "psa.ex.barbell_bench_press").count()
            skeleton = browser.new_page(viewport={"width": 390, "height": 844})
            skeleton.goto(check.frame.url)
            assert skeleton.locator(".initial-loading .skeleton").count() == 2
            assert skeleton.locator(".initial-loading svg").evaluate("e=>e.getBoundingClientRect().width") == 18
            skeleton.locator("#app").screenshot(path=str(args.output.parent / "training-initial-loading-mobile.png"))
            skeleton.close()
            result = {"data": "synthetic_only", "environment": "real Chromium, full Streamlit app, localhost, 390px viewport", "method": "input event to next animation frame after current query results; includes debounce", "n": len(samples), "p50_ms": percentile(samples, .5), "p95_ms": percentile(samples, .95), "samples_ms": samples, "checks": {"exact_same_search_results_as_service": True, "user_alias": True, "no_search_network_commands": True, "favorite_updates_visible_results": True, "initial_two_card_skeleton_with_18px_icon": True}}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps(result, ensure_ascii=False))
            browser.close()


if __name__ == "__main__":
    main()
