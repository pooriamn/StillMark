from __future__ import annotations

"""Typed tab-controller registry for staged monolith extraction.

The registry makes the Phase 14 split explicit without forcing a risky rewrite of
all 16k lines. It records ownership, builder compatibility, and safe migration
order so later extraction can be tested one tab at a time.
"""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class TabBoundarySpec:
    key: str
    label: str
    attr: str
    builder_name: str
    owner_module: str
    extraction_state: str


PHASE14_TAB_BOUNDARIES: tuple[TabBoundarySpec, ...] = (
    TabBoundarySpec("dashboard", "Dashboard", "dashboard_tab", "build_dashboard_tab", "control_panel_tabs.dashboard", "boundary-delegated"),
    TabBoundarySpec("works", "Works", "works_tab", "build_works_tab", "control_panel_tabs.works", "controller-delegated"),
    TabBoundarySpec("series", "Series", "series_tab", "build_series_tab", "control_panel_tabs.series", "controller-delegated"),
    TabBoundarySpec("pages", "Content Builder", "pages_tab", "build_pages_tab", "control_panel_tabs.pages", "controller-delegated"),
    TabBoundarySpec("publish", "Publish", "publish_tab", "build_publish_tab", "control_panel_tabs.publish", "boundary-delegated"),
)


def boundary_report() -> list[dict[str, str]]:
    return [spec.__dict__.copy() for spec in PHASE14_TAB_BOUNDARIES]


def build_compatibility_specs(window: Any, boundaries: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for boundary in PHASE14_TAB_BOUNDARIES:
        controller = boundaries.get(boundary.key)
        builder: Callable[[], Any] | None = getattr(controller, "build", None) if controller is not None else None
        if not callable(builder):
            legacy = getattr(window, boundary.builder_name)
            builder = legacy
        specs.append({
            "key": boundary.key,
            "label": boundary.label,
            "attr": boundary.attr,
            "builder": builder,
            "owner_module": boundary.owner_module,
            "extraction_state": boundary.extraction_state,
        })
    return specs
