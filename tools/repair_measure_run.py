"""Capture process-tree resource samples around an existing acceptance command."""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def processes(root_pid):
    rows = {}
    queue = [root_pid]
    while queue:
        pid = queue.pop()
        if pid in rows:
            continue
        path = Path('/proc')/str(pid)
        try:
            stat = (path/'stat').read_text()
            after = stat.rsplit(')',1)[1].split()
            rows[pid] = {'ppid':int(after[1]), 'rss_kib':int(after[21])*os.sysconf('SC_PAGE_SIZE')/1024,
                'cpu_seconds':(int(after[11])+int(after[12]))/os.sysconf('SC_CLK_TCK')}
            for task in (path/'task').iterdir():
                try:
                    queue.extend(int(child) for child in (task/'children').read_text().split())
                except OSError:
                    pass
        except (OSError,ValueError,IndexError):
            continue
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    start = time.monotonic()
    report = {'started_at':datetime.now(timezone.utc).isoformat(),'command':command,
        'platform':platform.platform(),'cpu_count':os.cpu_count(),
        'meminfo':{line.split(':')[0]:line.split(':')[1].strip() for line in Path('/proc/meminfo').read_text().splitlines()
                   if line.startswith(('MemTotal:','MemAvailable:'))},
        'measurement':'0.1s process-tree RSS samples, aggregate live CPU seconds; short peaks may be missed',
        'physical_device':'shared Kunpeng-920 server, not ordinary-device acceptance','samples':[]}
    process = subprocess.Popen(command)
    while True:
        all_rows = processes(process.pid)
        included = {process.pid}
        while True:
            new = {pid for pid,row in all_rows.items() if row['ppid'] in included}
            if new <= included:
                break
            included |= new
        rows = [all_rows[pid] for pid in included if pid in all_rows]
        report['samples'].append({'seconds':time.monotonic()-start,'rss_kib':sum(row['rss_kib'] for row in rows),
            'cpu_seconds':sum(row['cpu_seconds'] for row in rows),'process_count':len(rows),'host_load_average':os.getloadavg()})
        if process.poll() is not None:
            break
        time.sleep(.1)
    report['exit_code'] = process.returncode
    report['wall_seconds'] = time.monotonic()-start
    report['peak_tree_rss_kib'] = max(row['rss_kib'] for row in report['samples'])
    report['maximum_live_cpu_seconds'] = max(row['cpu_seconds'] for row in report['samples'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    raise SystemExit(process.returncode)


if __name__ == '__main__':
    main()
