#!/usr/bin/env python3
from __future__ import annotations

"""Static regression checks for Works preview loading pipeline.

These stay non-GUI so they can run without PySide6. They guard the bug where
most Works gallery cards stayed on "Loading preview…" even after the layout was
stable.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "scripts" / "control_panel.py"
BACKEND = ROOT / "scripts" / "qt_backend.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    panel = PANEL.read_text(encoding="utf-8")
    backend = BACKEND.read_text(encoding="utf-8")
    require("self._gallery_thumbnail_workers[cache_key] = loader" in panel, "thumbnail QRunnables must be retained while running")
    require("_gallery_thumbnail_workers.pop(cache_key, None)" in panel, "thumbnail QRunnable references must be released")
    require("_ensure_gallery_thumbnail_pipeline_running" in panel, "gallery refresh must be able to nudge a stalled pipeline")
    require("_gallery_thumbnail_watchdog_timer" in panel and "_gallery_thumbnail_watchdog_tick" in panel, "gallery pipeline must have a watchdog")
    require("Loading preview" in panel, "pipeline guard must inspect loading-card state")
    require("project_candidate = ROOT / clean_value.lstrip('/')" in backend, "site-root /assets preview paths must resolve inside the package")
    require("if project_candidate.exists() or not raw.exists()" in backend, "real absolute paths must still be respected when they exist")
    print("control_panel_preview_pipeline_regression_tests: OK")


if __name__ == "__main__":
    main()
