from __future__ import annotations

import time

from conftest import ROOT, run_build


def test_validate_only_passes_quickly_and_writes_nothing():
    watched = [ROOT / 'dist', ROOT / 'assets' / 'images' / 'generated', ROOT / 'assets' / 'images' / 'social']
    before = {p: p.stat().st_mtime_ns for root in watched if root.exists() for p in root.rglob('*')}
    started = time.perf_counter()
    result = run_build('--validate-only')
    elapsed = time.perf_counter() - started
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert 'Content validation passed' in result.stdout
    assert elapsed < 60, f'validation took {elapsed:.1f}s; it must not render images'
    after = {p: p.stat().st_mtime_ns for root in watched if root.exists() for p in root.rglob('*')}
    assert after == before, 'validate-only changed files on disk'


def test_no_access_codes_in_content():
    import yaml
    offenders = []
    for path in (ROOT / 'content').rglob('*.yaml'):
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        if isinstance(data, dict) and str(data.get('access_code') or '').strip():
            offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders, f'plain-text access codes are public in the repo: {offenders}'


def test_content_doctor_finds_no_errors():
    import subprocess, sys
    result = subprocess.run([sys.executable, 'scripts/content_doctor.py', '--strict'], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-3000:]
