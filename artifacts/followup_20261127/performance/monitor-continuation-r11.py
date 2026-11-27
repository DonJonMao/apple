"""Read-only RSS sampling of the existing sequential browser/page jobs."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path('/home/sn_maozhifang/apple')
sys.path.insert(0, str(ROOT / 'tools'))
from repair_measure_run import processes

BASE = ROOT / 'artifacts/followup_20261127/performance'
RUNNER_PID = 3703084
RECEIPT = BASE / 'continuation-r11-runner.json'
STARTED = time.time()
HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def main():
    observed = {}
    expected_cmdline = (Path('/proc') / str(RUNNER_PID) / 'cmdline').read_bytes()
    while True:
        try:
            current_cmdline = (Path('/proc') / str(RUNNER_PID) / 'cmdline').read_bytes()
        except OSError:
            current_cmdline = b''
        alive = current_cmdline == expected_cmdline
        try:
            entries = json.loads(RECEIPT.read_text())
        except (OSError, ValueError):
            time.sleep(.1)
            continue
        if entries:
            entry = entries[-1]
            label = entry['label']
            if label.startswith(('browser-', 'page-')) and 'exit_code' not in entry:
                record = observed.setdefault(label, {
                    'label': label, 'command': entry['command'], 'environment': entry['environment'],
                    'monitor_started_unix': STARTED, 'job_started_unix': entry['started_unix'],
                    'monitor_sha256': HASH, 'measurement': '0.1s live process-tree RSS and CPU samples; short peaks may be missed; includes isolated Streamlit and Chromium',
                    'samples': []})
                rows = processes(RUNNER_PID)
                job_pids = [pid for pid, row in rows.items() if row['ppid'] == RUNNER_PID]
                job_rows = {pid: row for root_pid in job_pids for pid, row in processes(root_pid).items()}
                record['samples'].append({'seconds': time.time() - entry['started_unix'],
                    'rss_kib': sum(row['rss_kib'] for row in job_rows.values()),
                    'cpu_seconds': sum(row['cpu_seconds'] for row in job_rows.values()),
                    'process_count': len(job_rows), 'host_load': os.getloadavg()})
        for entry in entries:
            label = entry['label']
            if label not in observed:
                continue
            record = observed[label]
            if 'finished_unix' in record or ('exit_code' not in entry and alive):
                continue
            record.update(exit_code=entry.get('exit_code'), finished_unix=entry.get('finished_unix', time.time()),
                complete='exit_code' in entry, peak_tree_rss_kib=max((s['rss_kib'] for s in record['samples']), default=0),
                maximum_live_cpu_seconds=max((s['cpu_seconds'] for s in record['samples']), default=0))
            path = BASE / f'continuation-{label}-r11-resources.json'
            assert not path.exists(), 'Preserve original resource samples'
            path.write_text(json.dumps(record, indent=2) + '\n')
            print(label, record['peak_tree_rss_kib'], 'KiB', flush=True)
        if not alive:
            break
        time.sleep(.1)


if __name__ == '__main__':
    main()
