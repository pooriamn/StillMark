from __future__ import annotations

"""Structured error utilities for the Stillmark control panel.

The goal is not to hide failures. User-fixable failures should be reported
clearly, expected filesystem/data failures should be typed, and last-resort
logging failures must not crash the editor.
"""

import json
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ControlPanelError(RuntimeError):
    """Base class for control-panel errors that should be shown or logged."""


class ControlPanelUserError(ControlPanelError):
    """A recoverable error the user can fix in content or inputs."""


class ControlPanelFileError(ControlPanelError):
    """A filesystem failure, usually permission/path/disk related."""


class ControlPanelIntegrityError(ControlPanelError):
    """A consistency failure after save/rename/replace/remove operations."""


@dataclass(frozen=True)
class ErrorRecord:
    timestamp: str
    operation: str
    severity: str
    exception_type: str
    message: str
    path: str = ""
    scope: str = "control-panel"
    traceback: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def exception_path(exc: BaseException) -> str:
    for attr in ("filename", "filename2", "path"):
        value = getattr(exc, attr, None)
        if value:
            return str(value)
    return ""


def classify_exception(exc: BaseException) -> str:
    if isinstance(exc, (ControlPanelUserError, ValueError, KeyError)):
        return "user-fixable"
    if isinstance(exc, (ControlPanelFileError, OSError, PermissionError, FileNotFoundError)):
        return "filesystem"
    if isinstance(exc, ControlPanelIntegrityError):
        return "integrity"
    return "unexpected"


def make_error_record(operation: str, exc: BaseException, *, severity: str = "error", include_traceback: bool = True) -> ErrorRecord:
    return ErrorRecord(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        operation=str(operation or "control-panel"),
        severity=str(severity or "error"),
        exception_type=exc.__class__.__name__,
        message=str(exc),
        path=exception_path(exc),
        scope=classify_exception(exc),
        traceback=traceback.format_exc() if include_traceback else "",
    )


def safe_json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n"
