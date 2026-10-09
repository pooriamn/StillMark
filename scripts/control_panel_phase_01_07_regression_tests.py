from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def assert_contains(path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    if needle not in text:
        raise AssertionError(f"Missing marker in {path.relative_to(ROOT)}: {needle}")


def main() -> None:
    assert_contains(ROOT / "scripts" / "control_panel_io.py", "def atomic_write_text")
    assert_contains(ROOT / "scripts" / "control_panel_startup_guard.py", "def run_startup_guard")
    assert_contains(ROOT / "scripts" / "helpers_content.py", "def guarded_unlink")
    assert_contains(ROOT / "scripts" / "helpers_content.py", "rolled_back")
    assert_contains(ROOT / "scripts" / "qt_backend.py", "def assert_no_fake_presence")
    assert_contains(ROOT / "scripts" / "qt_backend.py", "startup_preflight_checks(*, fast")
    assert_contains(ROOT / "scripts" / "control_panel.py", "run_startup_guard(ROOT)")
    assert_contains(ROOT / "scripts" / "control_panel.py", "_context_refresh_inflight")
    panel = (ROOT / "scripts" / "control_panel.py").read_text(encoding="utf-8")
    if "processEvents" in panel:
        raise AssertionError("QApplication.processEvents() reentrancy marker still exists in control_panel.py")
    print("Phase 1-7 control-panel regression markers passed.")


if __name__ == "__main__":
    main()
