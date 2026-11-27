"""Supplemental R07 browser check: real report, no selected goal/action."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
import followup_knowledge_browser as browser_check  # noqa: E402

OUTPUT = Path(__file__).resolve().parent
BaseCheck = browser_check.Check


class GoalCheck(BaseCheck):
    def __init__(self, page, output, result):
        super().__init__(page, output, result)
        result['knowledge'] = 'actual_local_public_library'
        result['scenario'] = 'synthetic rich body/training/events, no selected goal or action'
        result['harness_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def record(self, key, **details):
        super().record(key, **details)
        if key != 'real-report-actions-freeze-reopen-audit':
            return
        body = (OUTPUT / 'report.md').read_text()
        assert '当前目标：尚未选择目标' in body
        assert '本期没有截止时点可见的已选行动' in body
        assert '用先前选择的动作和目标尺度复评' not in body
        steps = body.split('## 下一步\n\n', 1)[1].split('\n\n## 冻结依据与明细', 1)[0]
        lines = steps.splitlines()
        assert len(lines) == 3
        assert all(line.startswith('- 核对 2026-11-20 合成长时段手表 的') for line in lines)
        assert all('health_sample:' in line for line in lines)
        assert any('已记录跌倒次数' in line for line in lines)
        w4_step = '在体重、日静息心率明细中核对本期与前期的来源、日期覆盖和测量条件；如需行动复评，先明确要观察的结果与时间窗。'
        assert w4_step in body
        assert w4_step in self.text()
        assert all(line[2:] in self.text() for line in lines)
        heading = self.page.get_by_role('heading', name='下一步', exact=True).last
        geometry = {}
        for width in (390, 1440):
            self.page.set_viewport_size({'width': width, 'height': 844 if width == 390 else 1000})
            heading.scroll_into_view_if_needed()
            browser_check.settle(self.page)
            dim = browser_check.geometry(self.page)
            assert dim['document'] <= dim['viewport'] and dim['main'] <= dim['main_client'], dim
            geometry[str(width)] = dim
            self.page.screenshot(path=str(OUTPUT / f'no-goal-next-steps-{width}.png'))
        self.page.set_viewport_size({'width': 1440, 'height': 1000})
        self.page.get_by_role('heading', name='本期主要变化', exact=True).last.scroll_into_view_if_needed()
        browser_check.settle(self.page)
        super().record('no-goal-real-events-prioritized', next_steps=lines,
                       w4_step=w4_step, no_selected_goal=True, no_selected_action=True,
                       browser_text_matches_download=True, geometry=geometry)


browser_check.Check = GoalCheck
browser_check.run(OUTPUT, (ROOT / '.local/knowledge').resolve(), report_only=True)
receipt = json.loads((OUTPUT / 'browser.json').read_text())
assert not receipt['errors']
assert not receipt['files_changed_during_run']
