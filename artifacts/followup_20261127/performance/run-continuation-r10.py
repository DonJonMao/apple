"""Sequential acceptance of frozen source against unchanged synthetic fixtures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/home/sn_maozhifang/apple')
TEMPORARY = Path('/home/sn_maozhifang/healthzip-followup-validation-tmp')
SOURCE = TEMPORARY / 'source-continuation-r10'
KNOWLEDGE = TEMPORARY / 'healthzip-followup-report-btuh0x66/knowledge'
OUTPUT = ROOT / 'artifacts/followup_20261127/performance'
PYTHON = ROOT / '.venv/bin/python'
CUTOFF = '2026-11-21T16:00:00+00:00'
LOAD = 'Sequential task-owned validation; user Streamlit PID 431790 retained; external shared-host load uncontrolled; OS caches retained'
FIXTURES = {
    'personal': '/tmp/healthzip-repair-personal/synthetic-two-year.sqlite3',
    '100k': '/tmp/healthzip-product-benchmark/synthetic-100000.sqlite3',
    '1m': '/tmp/healthzip-product-benchmark/synthetic-1000000.sqlite3',
}
ENVIRONMENT = {
    'TMPDIR': str(TEMPORARY),
    'PYTHONPATH': str(SOURCE / 'src') + ':' + str(SOURCE),
    'PLAYWRIGHT_BROWSERS_PATH': '/tmp/healthzip-browser-bin',
    'LD_LIBRARY_PATH': '/tmp/healthzip-browser-libs/extracted/usr/lib/aarch64-linux-gnu',
}


def main():
    regression = json.loads((ROOT / 'artifacts/followup_20261127/validation/continuation-full-r10/results.json').read_text())
    assert regression['status'] == 'passed'
    jobs = []
    for name in ('100k', 'personal', '1m'):
        jobs.append((f'backend-{name}', 'followup_report_benchmark.py',
                     ['--synthetic', FIXTURES[name], '--shared-knowledge-root', str(KNOWLEDGE)]))
    for name in ('100k', 'personal', '1m'):
        jobs.append((f'browser-report-{name}', 'followup_report_browser_benchmark.py',
                     ['--database', FIXTURES[name], '--shared-knowledge-root', str(KNOWLEDGE), '--source-root', str(SOURCE)]))
    for name in ('100k', 'personal', '1m'):
        for page in ('detail', 'preview'):
            jobs.append((f'page-{page}-{name}', 'followup_page_benchmark.py',
                         ['--database', FIXTURES[name], '--page', page]))
    records = []
    receipt = OUTPUT / 'continuation-r10-runner.json'
    assert not receipt.exists(), 'Preserve prior validation runs'
    for label, script, arguments in jobs:
        destination = OUTPUT / f'continuation-{label}-r10'
        command = [str(PYTHON), str(SOURCE / 'tools' / script), *arguments,
                   '--output', str(destination), '--cutoff', CUTOFF, '--warm', '30', '--concurrent-load', LOAD]
        entry = {'label': label, 'command': command, 'environment': ENVIRONMENT,
                 'cwd': str(ROOT), 'script_sha256': hashlib.sha256((SOURCE / 'tools' / script).read_bytes()).hexdigest(),
                 'started_unix': time.time()}
        records.append(entry)
        receipt.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
        print('START', label, flush=True)
        with (OUTPUT / f'continuation-{label}-r10-command.txt').open('w') as log:
            process = subprocess.run(command, cwd=ROOT, env={**os.environ, **ENVIRONMENT}, stdout=log, stderr=subprocess.STDOUT)
        entry.update(exit_code=process.returncode, finished_unix=time.time())
        receipt.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
        print('END', label, 'exit', process.returncode, flush=True)
        if process.returncode:
            raise SystemExit(process.returncode)


if __name__ == '__main__':
    main()
