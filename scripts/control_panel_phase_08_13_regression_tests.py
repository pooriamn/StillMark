from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def assert_contains(path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    if needle not in text:
        raise AssertionError(f"Missing marker in {path.relative_to(ROOT)}: {needle}")


def assert_not_contains(path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    if needle in text:
        raise AssertionError(f"Unexpected marker in {path.relative_to(ROOT)}: {needle}")


def main() -> None:
    control_panel = ROOT / "scripts" / "control_panel.py"
    assert_contains(ROOT / "scripts" / "control_panel_tasking.py", "class TaskContext")
    assert_contains(ROOT / "scripts" / "control_panel_tasking.py", "class CancelledTask")
    assert_contains(ROOT / "scripts" / "control_panel_tasking.py", "def run_staged_build")
    assert_contains(ROOT / "scripts" / "control_panel_tasking.py", "def run_staged_publish_package")
    assert_contains(ROOT / "scripts" / "services" / "refresh_service.py", "class RefreshEvent")
    assert_contains(ROOT / "scripts" / "control_panel_models.py", "class WorksTableModel")
    assert_contains(ROOT / "scripts" / "control_panel_media_cache.py", "def thumbnail_signature")
    assert_contains(control_panel, "cancel_current_task")
    assert_contains(control_panel, "run_staged_build(run_build_with_preflight")
    assert_contains(control_panel, "run_staged_publish_package(prepare_publish_package")
    assert_contains(control_panel, "request_refresh_event")
    assert_contains(control_panel, "self._tab_boundaries")
    assert_contains(control_panel, "self._works_model.set_rows")
    assert_contains(control_panel, "thumbnail_signature(work_id")
    assert_contains(control_panel, "ThumbnailBatchToken")
    assert_not_contains(control_panel, "processEvents")
    print("Phase 8-13 control-panel regression markers passed.")


if __name__ == "__main__":
    main()
