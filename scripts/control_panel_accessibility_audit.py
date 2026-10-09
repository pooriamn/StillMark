from __future__ import annotations

"""Static and runtime accessibility checks for the Qt control panel."""

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def static_accessibility_rows(root: Path = ROOT) -> list[dict[str, str]]:
    panel_path = root / "scripts" / "control_panel.py"
    qss_path = root / "scripts" / "control_panel_theme.qss"
    source = panel_path.read_text(encoding="utf-8", errors="replace") if panel_path.exists() else ""
    qss = qss_path.read_text(encoding="utf-8", errors="replace") if qss_path.exists() else ""
    rows = [
        {"status": "ok" if "QShortcut" in source else "warning", "check": "Keyboard navigation", "detail": "Shortcut map is installed." if "QShortcut" in source else "No shortcut map found."},
        {"status": "ok" if "show_shortcuts" in source else "warning", "check": "Shortcut discoverability", "detail": "Help & Shortcuts dialog is present." if "show_shortcuts" in source else "Shortcut help dialog missing."},
        {"status": "ok" if (":focus" in source or ":focus" in qss) else "warning", "check": "Visible focus", "detail": "Focus selectors are present." if (":focus" in source or ":focus" in qss) else "No explicit focus selectors found."},
        {"status": "ok" if "setToolTip" in source else "watch", "check": "Control descriptions", "detail": "Tooltips exist for compact controls." if "setToolTip" in source else "Few or no tooltips detected."},
        {"status": "ok" if "_reduced_motion" in source and "toggle_reduced_motion" in source else "watch", "check": "Reduced motion", "detail": "Reduced-motion control exists." if "_reduced_motion" in source else "Reduced-motion control missing."},
        {"status": "ok" if "WidgetWithChildrenShortcut" in source else "watch", "check": "Widget-level shortcuts", "detail": "Important lists have local keyboard actions." if "WidgetWithChildrenShortcut" in source else "Local list shortcuts not detected."},
        {"status": "ok" if "contextMenuEvent" in source or "customContextMenuRequested" in source else "watch", "check": "No hover-only actions", "detail": "Context-menu/action alternatives are present." if ("contextMenuEvent" in source or "customContextMenuRequested" in source) else "Hover-only alternatives are not obvious from static scan."},
    ]
    return rows


def runtime_focus_order_hint(widget_names: list[str]) -> dict[str, Any]:
    return {"status": "ok" if widget_names else "watch", "count": len(widget_names), "sequence": widget_names[:80]}
