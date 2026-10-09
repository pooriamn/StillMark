from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTROL_PANEL = ROOT / "scripts" / "control_panel.py"
QT_BACKEND = ROOT / "scripts" / "qt_backend.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    pattern = rf"^    def {re.escape(name)}\(.*?\n(?=    def |\nclass |\Z)"
    match = re.search(pattern, source, flags=re.M | re.S)
    if not match:
        raise AssertionError(f"Missing function: {name}")
    return match.group(0)


def check_preview_repaint_guards(source: str) -> None:
    required = [
        "_work_main_preview_signature",
        "_work_side_preview_signature",
        "def _preview_file_signature",
        "self._work_preview_timer.stop()",
    ]
    missing = [item for item in required if item not in source]
    if missing:
        raise AssertionError(f"Missing Batch E preview guard(s): {missing}")
    update_body = _function_body(source, "update_work_preview")
    if "_preview_file_signature(" not in update_body or "_work_main_preview_signature" not in update_body:
        raise AssertionError("update_work_preview does not gate pixmap repaint through a stable signature")
    pane_body = _function_body(source, "_update_work_preview_pane")
    if "_work_side_preview_signature" not in pane_body:
        raise AssertionError("side preview pane does not gate redundant repaint")


def check_asset_health_no_selection_steal(source: str) -> None:
    body = _function_body(source, "_patch_work_asset_health_row")
    forbidden = ["select_work(", "refresh_work_list(", "_populate_work_gallery(", "setCurrentItem(", "scrollToItem("]
    hits = [token for token in forbidden if token in body]
    if hits:
        raise AssertionError(f"asset-health patch still owns selection/view rebuild: {hits}")
    apply_body = _function_body(source, "_apply_work_asset_health_rows")
    if "_asset_health_payload_changed" not in apply_body:
        raise AssertionError("asset-health application still patches rows without comparing visible changes")


def check_warning_dedupe(source: str) -> None:
    required = [
        "_BACKEND_WARNING_DEDUPE_TTL_SECONDS",
        "def _should_suppress_duplicate_backend_warning",
        "_should_suppress_duplicate_backend_warning(context, path, error)",
    ]
    missing = [item for item in required if item not in source]
    if missing:
        raise AssertionError(f"Missing backend warning dedupe guard(s): {missing}")


def main() -> int:
    control_source = _read(CONTROL_PANEL)
    backend_source = _read(QT_BACKEND)
    check_preview_repaint_guards(control_source)
    check_asset_health_no_selection_steal(control_source)
    check_warning_dedupe(backend_source)
    print("Batch E stabilization regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
