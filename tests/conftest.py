"""Shared fixtures: one real build per test session, into the real dist/."""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'

# Source files the build must never modify (it used to rewrite all of them).
GUARDED_SOURCES = [
    'assets/js/app.js',
    'assets/js/home.js',
    'assets/js/portfolio.js',
    'assets/js/series.js',
    'assets/js/consent.js',
    'assets/css/styles.css',
    'README.md',
    'start-local-server.sh',
    'start-local-server.bat',
    'prepare-host-upload.sh',
    'prepare-host-upload.bat',
]


def file_hashes(paths: list[str]) -> dict[str, str]:
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths if (ROOT / p).exists()}


def run_build(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, 'build_site.py', *args],
        cwd=ROOT, text=True, capture_output=True, encoding='utf-8', errors='replace',
    )


@pytest.fixture(scope='session')
def build():
    """Build twice: the first may render images, the second must hit the cache."""
    before = file_hashes(GUARDED_SOURCES)
    first = run_build()
    assert first.returncode == 0, first.stdout[-3000:] + first.stderr[-3000:]
    second = run_build()
    assert second.returncode == 0, second.stdout[-3000:] + second.stderr[-3000:]
    after = file_hashes(GUARDED_SOURCES)
    return {'first': first, 'second': second, 'before': before, 'after': after}
