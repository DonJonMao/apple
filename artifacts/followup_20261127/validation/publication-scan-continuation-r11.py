"""Scan only the explicitly selected continuation delivery for publication."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path('/home/sn_maozhifang/apple')
sys.path.insert(0, str(ROOT))
from tools.followup_knowledge_publication_scan import (
    EXCLUDED_SUFFIXES, RAW_CONTAINER, json_payloads, originals, raw_payloads, source_hits,
)

OUTPUT = ROOT / 'artifacts/followup_20261127/validation/continuation-publication-scan-r11.json'


def selection():
    names = set()
    for args in [('diff', '--name-only', '-z'), ('ls-files', '--others', '--exclude-standard', '-z')]:
        names.update(n for n in subprocess.check_output(['git', *args], cwd=ROOT).decode().split('\0') if n)
    names = {n for n in names if n.startswith(('src/', 'tests/', 'tools/', 'docs/', 'artifacts/followup_20261127/'))}
    # Include ignored synthetic logs in directories containing this delivery's
    # new artifacts; do not sweep runtime .local or unrelated historical folders.
    for parent in {str(Path(n).parent) for n in names if n.startswith('artifacts/')}:
        names.update(str(p.relative_to(ROOT)) for p in (ROOT / parent).glob('*.log') if p.is_file())
    names.discard(str(OUTPUT.relative_to(ROOT)))
    return sorted(names)


def main():
    assert not OUTPUT.exists(), 'Preserve prior scan'
    patterns = originals(ROOT / '.local/knowledge')
    selected = selection()
    files = []
    for name in selected:
        p = ROOT / name
        row = {'path': name}
        if p.is_symlink() or p.suffix.lower() in EXCLUDED_SUFFIXES:
            row.update(classification='exclude', reason='database_archive_original_or_symlink')
            files.append(row)
            continue
        data = p.read_bytes()
        row.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            allowed = name.startswith('artifacts/followup_20261127/') and p.suffix.lower() in {'.png', '.prof'}
            row.update(classification='publish' if allowed else 'exclude',
                reason='synthetic_screenshot_or_code_profile_with_separate_provenance' if allowed else 'unknown_binary',
                text_scan=False)
        else:
            hits = source_hits(text, patterns)
            raw = [item for _, value in json_payloads(text) for item in raw_payloads(value)]
            lexical = [{'key': m.group(1), 'offset': m.start()} for m in RAW_CONTAINER.finditer(text)]
            invalid = False
            if p.suffix.lower() == '.json':
                try:
                    json.loads(text)
                except ValueError:
                    invalid = True
            row.update(classification='exclude' if hits or raw or lexical or invalid else 'publish',
                E7_original_hits=hits, raw_payloads=raw, literal_nonempty_containers=lexical,
                invalid_json=invalid, text_scan=True)
        files.append(row)
    changed = [r['path'] for r in files if r.get('sha256') and hashlib.sha256((ROOT / r['path']).read_bytes()).hexdigest() != r['sha256']]
    membership = sorted(set(selected) ^ set(selection()))
    report = {'scope': 'Only changed/new source, tests, tools, docs and synthetic continuation artifacts, including selected ignored logs',
        'at_utc': datetime.now(timezone.utc).isoformat(), 'files': files,
        'excluded': [r['path'] for r in files if r['classification'] != 'publish'],
        'changed_during_scan': changed, 'membership_changes': membership,
        'source_read_only': 'Public SourceLibrary E7 retained original-prefix/escaped forms only; no health database opened',
        'limitations': ['Exact source-prefix/raw-payload scan does not establish rights for every paraphrase.',
            'PNG and cProfile files use synthetic provenance and direct visual/source review; no OCR.',
            'Original PDFs, runtime databases, backups and full audit bundles are excluded.'],
        'all_selected_publishable': not any(r['classification'] != 'publish' for r in files) and not changed and not membership}
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'files': len(files), 'excluded': report['excluded'], 'stable': not changed and not membership}))


if __name__ == '__main__':
    main()
