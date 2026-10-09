from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from control_panel_scope_guard import scope_summary

ROOT = Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class DiagnosticsService:
    """Diagnostics boundary used by the control panel and verifier."""

    root: Path = ROOT

    def scope_row(self) -> dict[str, Any]:
        summary = scope_summary()
        active_tk = summary.get("active_tk_files") or []
        return {
            "area": "Scope guard",
            "status": "ok" if not active_tk else "error",
            "detail": f"{summary.get('protected_file_count', 0)} protected public/content file(s); active Tk files={len(active_tk)}",
        }
