#!/usr/bin/env python3
"""Static regression contracts for control-panel phases 21-25.

These checks avoid launching Qt. They protect the performance architecture:
health cache, lazy startup, debounced Works refreshes, priority thumbnails, and
batched QSS application.
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "scripts" / "control_panel.py"
BACKEND = ROOT / "scripts" / "qt_backend.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_phase_21_cached_health_fast_path() -> None:
    panel = read(PANEL)
    backend = read(BACKEND)
    require("HEALTH_CACHE_MAX_AGE_SECONDS = 30 * 60" in backend, "30-minute health cache TTL missing")
    require("CONTROL_PANEL_STATE_PATH" in backend and "control-panel-state.json" in backend, "persistent health state missing")
    require("load_cached_portfolio_health_report(max_age_seconds=30 * 60)" in panel, "dashboard does not use long cached health fast path")
    require("def patch_cached_health_for_work" in backend, "single-work health cache patch missing")
    require("patch_cached_health_for_work(new_work_id)" in backend, "metadata-only work save does not patch cached health")
    require("timeout_seconds: float = 10.0" in backend and 'report["incomplete"]' in backend, "health scan timeout/partial reporting missing")


def test_phase_22_lazy_startup() -> None:
    panel = read(PANEL)
    init_block = panel.split("    def __init__(self) -> None:", 1)[1].split("    # ---------- shell ----------", 1)[0]
    require("run_startup_guard(ROOT)" not in init_block, "startup guard still runs synchronously in __init__")
    require("refresh_all_context(force=True, scope={\"dashboard\"})" not in init_block, "dashboard still eagerly refreshes in __init__")
    require("QTimer.singleShot(100, self._first_load)" in panel, "post-show first-load timer missing")
    require("def _run_startup_guard_async" in panel and "FunctionWorker(self._collect_startup_preflight_async)" in panel, "startup guard/preflight not moved to worker")
    require("def _first_load" in panel and "self.refresh_dashboard()" in panel, "dashboard-only first-load method missing")


def test_phase_23_debounced_works_refresh() -> None:
    panel = read(PANEL)
    require("self._work_list_debounce = QTimer(self)" in panel and "setInterval(150)" in panel, "150ms Works debounce timer missing")
    require("def refresh_work_list(self, *, force: bool = False" in panel, "refresh_work_list is not a debounce wrapper")
    require("def _refresh_work_list_now" in panel, "actual Works refresh implementation missing")
    require("self._works_model.set_rows(list(works))" in panel, "WorksTableModel no longer drives Works rows")
    require("replace_or_insert_row" in panel and "dataChanged.emit" in read(ROOT / "scripts" / "control_panel_models.py"), "single-row model patch path missing")
    require("_work_gallery_initial_limit = 50" in panel and "gallery_works = list(works)[:initial_limit]" in panel, "initial Works gallery cap missing")


def test_phase_24_priority_thumbnail_queue() -> None:
    panel = read(PANEL)
    require("from collections import OrderedDict, deque" in panel, "thumbnail queue deque import missing")
    require("self._gallery_thumbnail_max_concurrent = 2" in panel, "thumbnail concurrency limit missing")
    require("def _thumbnail_disk_cache_path" in panel and '"meta" / "thumbnails"' in panel, "disk thumbnail cache missing")
    require("from PIL import Image" in panel and ".thumbnail((max(1, self.size.width())" in panel, "PIL worker resize missing")
    require("popleft()" in panel and "_reprioritise_gallery_thumbnail_queue" in panel, "priority thumbnail queue missing")
    require("ThumbnailLoader(work_id, path, cache_key, size, str(disk_cache_path))" in panel, "thumbnail loader not using disk cache path")


def test_phase_25_qss_cache_batching() -> None:
    panel = read(PANEL)
    require("self._qss_cache: dict[tuple[str, bool], str]" in panel, "QSS cache is not keyed by density/reduced-motion tuple")
    require("qss_key = (str(density), bool(getattr(self, \"_reduced_motion\", False)))" in panel, "QSS key tuple missing")
    require("if cached is not None and self._last_applied_qss_key == qss_key:\n            return" in panel, "identical QSS application is not skipped")
    require("self.setUpdatesEnabled(False)" in panel and "self.setUpdatesEnabled(True)" in panel, "QSS repaint batching missing")
    inline_styles = [line for line in panel.splitlines() if ".setStyleSheet(" in line and "self.setStyleSheet(combined)" not in line and "_status_dot" not in line]
    require(not inline_styles, f"inline child setStyleSheet calls remain: {inline_styles[:3]}")


def main() -> None:
    test_phase_21_cached_health_fast_path()
    test_phase_22_lazy_startup()
    test_phase_23_debounced_works_refresh()
    test_phase_24_priority_thumbnail_queue()
    test_phase_25_qss_cache_batching()
    print("control_panel_phase_21_25_regression_tests: OK")


if __name__ == "__main__":
    main()
