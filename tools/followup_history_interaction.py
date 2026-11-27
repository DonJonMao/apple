"""Diagnose real history-menu animation/scroll interactions on a synthetic copy.

No report is generated. Baseline and synchronized cases use one application and
fresh browser contexts. Synchronization awaits actual animation/geometry state;
it does not retry a failed selection or change the product's CSS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/training"))
from followup_report_benchmark import shared_knowledge, validate_synthetic  # noqa: E402
from repair_preview_benchmark import fixture_copy  # noqa: E402
from strength_workbench_browser_check import isolated_app  # noqa: E402

# Include all matching controls, rather than accidentally inspecting a hidden
# control retained briefly during a Streamlit rerender.
TRACE = """() => {
  window.__historyStop?.();window.__historyTrace=[];window.__historyNodeIds=new WeakMap();let nextId=1,last='';
  const identity=e=>{if(!e)return null;if(!window.__historyNodeIds.has(e))window.__historyNodeIds.set(e,nextId++);
    return {node:window.__historyNodeIds.get(e),tag:e.tagName,id:e.id,testid:e.getAttribute?.('data-testid'),
      role:e.getAttribute?.('role'),className:typeof e.className==='string'?e.className:null};};
  const animations=e=>e.getAnimations?.().map(a=>({state:a.playState,time:a.currentTime,
    duration:a.effect?.getComputedTiming().duration,keyframes:a.effect?.getKeyframes()}))??[];
  const geometry=e=>{const b=e.getBoundingClientRect();const s=getComputedStyle(e);return {...identity(e),
    box:{x:b.x,y:b.y,width:b.width,height:b.height},scrollTop:e.scrollTop,scrollLeft:e.scrollLeft,
    scrollHeight:e.scrollHeight,clientHeight:e.clientHeight,style:e.getAttribute('style'),
    overflow:s.overflow,opacity:s.opacity,visibility:s.visibility,display:s.display,
    animations:animations(e)};};
  window.__historySnapshot=event=>{const inputs=[...document.querySelectorAll('input[role=combobox][aria-label=历史复盘]')];
    return {at:performance.now(),type:event?.type??'snapshot',target:identity(event?.target),
      targetContainsInputs:inputs.map(e=>!!event?.target?.contains?.(e)),focus:identity(document.activeElement),
      render:document.querySelector('[data-hz-render]')?.dataset.hzRender,
      controls:inputs.map(e=>({...geometry(e),value:e.value,expanded:e.getAttribute('aria-expanded'),
        ancestors:(()=>{const list=[];for(let p=e.parentElement;p;p=p.parentElement)list.push(geometry(p));return list;})()})),
      menus:[...document.querySelectorAll('[role=listbox]')].map(geometry),
      options:[...document.querySelectorAll('[role=option]')].map(e=>({text:e.innerText,...geometry(e)}))};};
  const track=event=>{const row=window.__historySnapshot(event);const key=JSON.stringify({...row,at:0});
    if(key!==last){window.__historyTrace.push(row);last=key;}};
  window.__historyTrack=track;for(const name of ['scroll','pointerdown','click','focusin','focusout','input','keydown'])
    document.addEventListener(name,track,true);
  window.__historyObserver=new MutationObserver(()=>track({type:'mutation'}));
  window.__historyObserver.observe(document.body,{subtree:true,attributes:true,childList:true});
  window.__historyStop=()=>{window.__historyObserver.disconnect();for(const name of ['scroll','pointerdown','click','focusin','focusout','input','keydown'])document.removeEventListener(name,track,true);};track({type:'start'});
} """

# Waiting for actual Web Animations completion also covers the expander's
# ResizeObserver-triggered height animation after a responsive width change.
READY = """async e => {
  const started=performance.now();let stable=0,previous='';const observations=[];
  const frame=()=>new Promise(resolve=>requestAnimationFrame(resolve));
  while(performance.now()-started<5000){
    if(!e.isConnected)throw new Error('history control replaced while preparing');
    const chain=[];for(let p=e;p;p=p.parentElement)chain.push(p);
    const active=chain.flatMap(p=>p.getAnimations?.()??[]).filter(a=>a.playState==='running'||a.playState==='pending');
    const details=e.closest('details');const b=e.getBoundingClientRect();
    const state={box:{x:b.x,y:b.y,width:b.width,height:b.height},scroll:chain.map(p=>[p.scrollTop,p.scrollLeft]),
      active:active.length,detailsStyle:details?.getAttribute('style'),detailsOpen:details?.open};
    observations.push({at:performance.now(),...state});
    const key=JSON.stringify(state);
    if(!active.length&&details?.open&&details.style.overflow!=='hidden'&&key===previous)stable++;else stable=0;
    if(stable>=3)return {elapsed_ms:performance.now()-started,observations};
    previous=key;
    if(active.length)await Promise.race([Promise.all(active.map(a=>a.finished.catch(()=>null))),
      new Promise((_,reject)=>setTimeout(()=>reject(new Error('ancestor animation exceeded5000ms')),5000))]);
    await frame();
  }
  throw new Error('history ancestor geometry did not settle');
} """

PAINTED = """input => {
  if(!input?.isConnected||!input.checkVisibility())return false;
  const menu=document.getElementById(input.getAttribute('aria-controls'));
  const option=menu?.querySelector('[role=option]');
  if(input?.getAttribute('aria-expanded')!=='true'||!option)return false;
  for(let p=option;p;p=p.parentElement){const s=getComputedStyle(p);
    if(Number(s.opacity)<.99||s.visibility!=='visible'||s.display==='none')return false;}
  const b=option.getBoundingClientRect();const x=b.x+b.width/2,y=b.y+b.height/2;
  if(b.width<=0||b.height<=0||y<0||y>=innerHeight||x<0||x>=innerWidth)return false;
  const hit=document.elementFromPoint(x,y);return !!hit&&option.contains(hit);
} """


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def report_rows(database):
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT report_id,created_at,json_extract(payload_json,'$.period') AS period,payload_json,markdown "
            "FROM joint_period_report WHERE user_id='local' ORDER BY created_at DESC")]


def prepare(selector, synchronized):
    evidence = []
    if synchronized:
        evidence.append(selector.evaluate(READY))
    selector.evaluate("e=>e.scrollIntoView({block:'center',behavior:'instant'})")
    if synchronized:
        evidence.append(selector.evaluate(READY))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--knowledge-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--returns", type=int, default=3)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    validate_synthetic(args.database)
    original = report_rows(args.database)
    assert len(original) >= 26, "retain the actual virtualized history-list scenario"
    folder = Path(tempfile.mkdtemp(prefix="history-interaction-"))
    database, counts = fixture_copy(args.database, folder)
    knowledge_before = shared_knowledge(args.knowledge_root)
    (folder / ".local/knowledge").symlink_to(args.knowledge_root.resolve(), target_is_directory=True)
    bootstrap = folder / "bootstrap"
    bootstrap.mkdir()
    source = args.source_root.resolve()
    (bootstrap / "src").symlink_to(source / "src", target_is_directory=True)
    (bootstrap / ".streamlit").symlink_to(source / ".streamlit", target_is_directory=True)
    (bootstrap / "app.py").write_text(
        "import runpy,importlib\nimport streamlit as st\nfrom datetime import datetime\n"
        "class RequestClock(datetime):\n @classmethod\n def now(cls,tz=None):\n"
        "  value=datetime.fromisoformat('2026-11-22T00:00:00+08:00')\n"
        "  return value.astimezone(tz) if tz else value.replace(tzinfo=None)\n"
        "for module in ('healthzip.analytics.workspaces','healthzip.analytics.workspace_summary'):\n"
        " importlib.import_module(module).datetime=RequestClock\n"
        "st.session_state.setdefault('review_period','本周')\n"
        f"runpy.run_path({str(source / 'app.py')!r},run_name='__main__')\n")
    source_hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in [source / "app.py", source / ".streamlit/config.toml",
                               *source.joinpath("src").rglob("*.py"), *source.joinpath("src").rglob("*.css")]}
    result = {"purpose": "single-attempt interaction diagnosis, not performance acceptance",
              "source_root": str(source), "source_hashes": source_hashes, "synthetic_counts": counts,
              "retained_workspace": str(folder), "cases": []}
    write(args.output / "receipt.json", result)
    shutil.copyfile(__file__, args.output / "driver-source.py")
    from healthzip.ui.review_page import report_history_labels
    labels = report_history_labels(original[:30], "Asia/Shanghai")
    with isolated_app(bootstrap, folder) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            for name in ("baseline-arrow", "synchronized-arrow", "synchronized-navigation"):
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                context.route("http**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
                page = context.new_page()
                row = {"name": name, "selections": [], "attempts_per_selection": 1}
                result["cases"].append(row)
                try:
                    page.goto(base + "/?workspace=review")
                    page.get_by_role("button", name="生成当前周期复盘", exact=True).wait_for(timeout=60000)
                    page.wait_for_function("()=>document.querySelector('[data-hz-render]')?.dataset.workspace==='review'")
                    page.get_by_test_id("stStatusWidget").wait_for(state="hidden")
                    count = args.returns + 1 if name.endswith("navigation") else 1
                    for index in range(count):
                        if index:
                            old = page.locator("[data-hz-render]").get_attribute("data-hz-render")
                            page.get_by_role("button", name="返回当前周期复盘", exact=True).click()
                            page.locator("[data-hz-report-id]").wait_for(state="detached")
                            page.wait_for_function("old=>{const e=document.querySelector('[data-hz-render]');return e&&e.dataset.hzRender!==old}", arg=old)
                            page.get_by_test_id("stStatusWidget").wait_for(state="hidden")
                        page.evaluate(TRACE)
                        selector = page.get_by_role("combobox", name="历史复盘", exact=True)
                        if not selector.is_visible():
                            page.get_by_text("已保存的复盘", exact=True).click()
                        preparation = prepare(selector, name != "baseline-arrow")
                        if name.endswith("arrow"):
                            selector.locator("xpath=..").get_by_role("button", name="Open", exact=True).click()
                            # Observe through the real expander animation, then
                            # require rendered and hit-testable options.
                            row["after_open_settle"] = selector.evaluate(READY)
                            page.wait_for_function(PAINTED, arg=selector.element_handle(), timeout=2000)
                            page.screenshot(path=str(args.output / (name + ".png")))
                            assert selector.evaluate(PAINTED)
                            row["painted_options"] = page.get_by_role("option").all_text_contents()
                            row["complete"] = True
                            break
                        requested = original[index % 2]["report_id"]
                        label = labels[requested]
                        selected_before = selector.input_value()
                        old = page.locator("[data-hz-render]").get_attribute("data-hz-render")
                        selector.click()
                        selector.press("Control+a")
                        selector.press_sequentially(label.rsplit(" ", 1)[-1])
                        page.get_by_role("option", name=label, exact=True).click(timeout=2000)
                        if selected_before != label:
                            page.wait_for_function("old=>{const e=document.querySelector('[data-hz-render]');return e&&e.dataset.hzRender!==old}", arg=old)
                        page.get_by_test_id("stStatusWidget").wait_for(state="hidden")
                        assert selector.input_value() == label
                        selection_events = page.evaluate("window.__historyTrace")
                        page.evaluate("window.__historyStop()")
                        old = page.locator("[data-hz-render]").get_attribute("data-hz-render")
                        page.get_by_role("button", name="打开这份复盘", exact=True).click()
                        page.wait_for_function("id=>document.querySelector('[data-hz-report-id]')?.dataset.hzReportId===id", arg=requested, timeout=30000)
                        page.wait_for_function("old=>{const e=document.querySelector('[data-hz-render]');return e&&e.dataset.hzRender!==old}", arg=old)
                        page.get_by_test_id("stStatusWidget").wait_for(state="hidden")
                        row["selections"].append({"requested": requested, "opened": page.locator("[data-hz-report-id]").get_attribute("data-hz-report-id"),
                                                  "label": label, "preparation": preparation, "events": selection_events})
                    else:
                        row["complete"] = True
                except Exception as exc:
                    row["failure"] = str(exc)
                    page.screenshot(path=str(args.output / (name + "-failure.png")), full_page=True)
                    (args.output / (name + "-failure.html")).write_text(page.content())
                finally:
                    row["events"] = page.evaluate("window.__historyTrace??[]")
                    row["last_state"] = page.evaluate("window.__historySnapshot?.()??null")
                    write(args.output / "receipt.json", result)
                    context.close()
        finally:
            browser.close()
    shutil.copyfile(folder / "synthetic-streamlit.log", args.output / "streamlit.txt")
    result["source_unchanged"] = all(hashlib.sha256((source / name).read_bytes()).hexdigest() == digest for name, digest in source_hashes.items())
    result["authority_unchanged"] = shared_knowledge(args.knowledge_root) == knowledge_before
    result["original_reports_unchanged"] = report_rows(args.database) == original
    result["copied_reports_unchanged"] = report_rows(database) == original
    assert result["source_unchanged"] and result["authority_unchanged"] and result["original_reports_unchanged"] and result["copied_reports_unchanged"]
    write(args.output / "receipt.json", result)


if __name__ == "__main__":
    main()
