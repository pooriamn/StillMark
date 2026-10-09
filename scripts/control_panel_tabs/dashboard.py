from __future__ import annotations

from typing import Any


class DashboardTabBoundary:
    """Migration boundary for the Dashboard tab.

    The current release keeps behaviour delegated to ControlPanelWindow to avoid
    a risky rewrite. Future phases can move handlers here one workflow at a time
    while the public website remains untouched.
    """

    tab_key = "dashboard"
    tab_label = "Dashboard"

    def __init__(self, window: Any) -> None:
        self.window = window

    def build(self) -> Any:
        builder = getattr(self.window, "build_dashboard_tab")
        return builder()
