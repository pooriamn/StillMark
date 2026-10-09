from __future__ import annotations

"""Static and runtime thread-safety helpers for the Qt control panel.

Qt requires widgets and QPixmap work to stay on the GUI/main thread. The runtime
assertion is opt-in and the static scan is used by diagnostics and smoke tests.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ThreadSafetyIssue:
    severity: str
    check: str
    detail: str
    path: str = ""
    line: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "check": self.check,
            "detail": self.detail,
            "path": self.path,
            "line": self.line,
        }


def assert_gui_thread(label: str = "UI update") -> None:
    """Raise RuntimeError when called off the QApplication main thread.

    The function imports PySide lazily so non-GUI verification remains possible.
    """
    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
    except Exception:
        return
    app = QApplication.instance()
    if app is None:
        return
    if QThread.currentThread() is not app.thread():
        raise RuntimeError(f"{label} must run on the Qt GUI thread")


def _inside_class_or_method(line: str, markers: tuple[str, ...]) -> bool:
    stripped = line.strip()
    return any(marker in stripped for marker in markers)


def scan_thread_safety_source(root: Path | str) -> list[dict[str, Any]]:
    """Return static warnings for obvious Qt-thread misuse patterns."""
    root_path = Path(root)
    issues: list[ThreadSafetyIssue] = []
    panel = root_path / "scripts" / "control_panel.py"
    if panel.exists():
        try:
            lines = panel.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            issues.append(ThreadSafetyIssue("error", "source readable", str(exc), panel.as_posix()))
            return [issue.as_dict() for issue in issues]
        in_thumbnail_run = False
        in_function_worker_run = False
        for number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("class ThumbnailLoader"):
                in_thumbnail_run = False
            if stripped.startswith("def run(self)"):
                # Limited heuristic: within the thumbnail worker block until the next class.
                in_thumbnail_run = number > 430 and number < 520
                in_function_worker_run = number > 520 and number < 560
            if stripped.startswith("class ") and "ThumbnailLoader" not in stripped and number > 520:
                in_thumbnail_run = False
                in_function_worker_run = False
            if in_thumbnail_run and "QPixmap(" in line:
                issues.append(ThreadSafetyIssue("error", "worker QPixmap", "QPixmap construction detected inside ThumbnailLoader.run; worker should return QImage/data only.", panel.relative_to(root_path).as_posix(), number))
            if in_function_worker_run and ("setText(" in line or "setPixmap(" in line or "QMessageBox" in line):
                issues.append(ThreadSafetyIssue("error", "worker widget update", "Widget mutation detected inside FunctionWorker.run.", panel.relative_to(root_path).as_posix(), number))
    components = root_path / "scripts" / "control_panel_components.py"
    if components.exists():
        text = components.read_text(encoding="utf-8", errors="replace")
        if "QPixmap(str(" in text:
            line = text[: text.index("QPixmap(str(")].count("\n") + 1
            issues.append(ThreadSafetyIssue("warning", "sync pixmap load", "Synchronous QPixmap disk load remains in components; acceptable only for small already-cached images.", components.relative_to(root_path).as_posix(), line))
    return [issue.as_dict() for issue in issues]


def thread_safety_summary(root: Path | str) -> dict[str, Any]:
    issues = scan_thread_safety_source(root)
    errors = [issue for issue in issues if issue.get("severity") == "error"]
    warnings = [issue for issue in issues if issue.get("severity") == "warning"]
    return {
        "ok": not errors,
        "errors": len(errors),
        "warnings": len(warnings),
        "issues": issues,
    }
