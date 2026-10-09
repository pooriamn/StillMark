from __future__ import annotations

"""Versioned, defensive UI-state helpers for the Stillmark Qt control panel.

The helpers stay pure-Python so they can be verified without launching PySide6.
They protect the Qt shell from restoring old/corrupt geometry or collapsed
splitter values after layout migrations.
"""

from dataclasses import dataclass
from typing import Any

CONTROL_PANEL_STATE_SCHEMA_VERSION = 3
MIN_WINDOW_WIDTH = 1060
MIN_WINDOW_HEIGHT = 700
MAX_SAVED_NOTIFICATIONS = 80
MIN_SPLITTER_PANE = 32
EXPECTED_SPLITTER_PANE_COUNTS: dict[str, int] = {
    "control-panel-main-splitter": 3,
    "dashboard-main-splitter": 2,
    "dashboard-right-splitter": 2,
    "works-main-splitter": 2,
    "series-main-splitter": 2,
    "series-sequence-splitter": 2,
    "relationships-main-splitter": 2,
    "pages-main-splitter": 2,
    "pages-editor-splitter": 2,
    "pages-review-splitter": 2,
    "authority-review-splitter": 2,
    "validation-main-splitter": 2,
    "studio-sequence-pages-splitter": 2,
    "studio-assets-splitter": 2,
    "studio-release-validation-splitter": 2,
}


@dataclass(frozen=True)
class StateSanityReport:
    ok: bool
    migrated: bool
    warnings: tuple[str, ...]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp_geometry(values: Any, *, minimum_width: int = MIN_WINDOW_WIDTH, minimum_height: int = MIN_WINDOW_HEIGHT) -> list[int] | None:
    """Return a safe [x, y, w, h] geometry list or None if unusable."""
    if not isinstance(values, (list, tuple)) or len(values) != 4:
        return None
    x, y, width, height = [_int(item) for item in values]
    width = max(int(minimum_width), width)
    height = max(int(minimum_height), height)
    # Avoid restoring wildly off-screen positions from older machines. Qt still
    # gets a chance to clamp to the actual screen later.
    x = max(-200, min(x, 8000))
    y = max(-200, min(y, 8000))
    return [x, y, width, height]


def normalise_splitter_sizes(name: str, values: Any, *, minimum: int = MIN_SPLITTER_PANE, expected_count: int | None = None) -> list[int] | None:
    """Clean saved splitter sizes without allowing collapsed panes.

    Qt persists exact pixel sizes. After a redesign, those old sizes can restore
    zero-width panes. This helper keeps proportions but clamps each visible pane
    to a safe lower bound.
    """
    if not isinstance(values, (list, tuple)) or not values:
        return None
    if expected_count is not None and len(values) != int(expected_count):
        return None
    cleaned = [_int(value, minimum) for value in values]
    if any(value < 0 for value in cleaned):
        return None
    # Allow the intentionally hidden inspector pane in the main splitter, but do
    # not allow every other pane to collapse to zero.
    allow_trailing_zero = str(name) == "control-panel-main-splitter" and len(cleaned) >= 3
    normalised: list[int] = []
    for index, value in enumerate(cleaned):
        if allow_trailing_zero and index == len(cleaned) - 1 and value == 0:
            normalised.append(0)
        else:
            normalised.append(max(minimum, value))
    if sum(normalised) <= 0:
        return None
    return normalised


def normalise_splitter_state(splitters: Any, *, expected_pane_counts: dict[str, int] | None = None) -> dict[str, list[int]]:
    if not isinstance(splitters, dict):
        return {}
    result: dict[str, list[int]] = {}
    for raw_name, raw_sizes in splitters.items():
        name = str(raw_name or "").strip()
        if not name:
            continue
        expected_count = (expected_pane_counts or EXPECTED_SPLITTER_PANE_COUNTS).get(name)
        sizes = normalise_splitter_sizes(name, raw_sizes, expected_count=expected_count)
        if sizes:
            result[name] = sizes
    return result


def normalise_control_panel_state(state: Any, *, layout_version: str, max_tab_index: int = 9) -> tuple[dict[str, Any], StateSanityReport]:
    """Migrate persisted state to the current schema and discard unsafe values."""
    warnings: list[str] = []
    migrated = False
    if not isinstance(state, dict):
        state = {}
        migrated = True
        warnings.append("State payload was not an object and was reset.")
    clean = dict(state)
    if int(clean.get("state_schema_version") or 0) != CONTROL_PANEL_STATE_SCHEMA_VERSION:
        migrated = True
        warnings.append("State schema was upgraded; risky layout values were revalidated.")
    clean["state_schema_version"] = CONTROL_PANEL_STATE_SCHEMA_VERSION
    geometry = clamp_geometry(clean.get("geometry"))
    if geometry is None:
        clean.pop("geometry", None)
    else:
        clean["geometry"] = geometry
    if clean.get("layout_polish_version") == layout_version:
        clean["splitters"] = normalise_splitter_state(clean.get("splitters"))
    else:
        clean.pop("splitters", None)
    notifications = clean.get("notifications")
    if isinstance(notifications, list):
        clean["notifications"] = notifications[:MAX_SAVED_NOTIFICATIONS]
    else:
        clean["notifications"] = []
    safe_max_tab_index = max(0, int(max_tab_index or 0))
    for key in ("active_tab", "last_active_tab_index"):
        if key in clean:
            value = _int(clean.get(key), 0)
            clamped = max(0, min(value, safe_max_tab_index))
            if value != clamped:
                migrated = True
                warnings.append(f"Tab index {value} was out of range; clamped to {clamped}.")
            clean[key] = clamped
    if not isinstance(clean.get("custom_work_filter_presets"), dict):
        clean["custom_work_filter_presets"] = {}
    if not isinstance(clean.get("work_filters"), dict):
        clean.pop("work_filters", None)
    return clean, StateSanityReport(ok=True, migrated=migrated, warnings=tuple(warnings))


def state_diagnostics(state: Any, *, layout_version: str, max_tab_index: int = 9) -> dict[str, Any]:
    clean, report = normalise_control_panel_state(state, layout_version=layout_version, max_tab_index=max_tab_index)
    return {
        "ok": report.ok,
        "migrated": report.migrated,
        "warnings": list(report.warnings),
        "schema_version": clean.get("state_schema_version"),
        "splitter_count": len(clean.get("splitters") or {}),
        "notification_count": len(clean.get("notifications") or []),
    }
