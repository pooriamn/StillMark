from __future__ import annotations

from typing import Any


class PublishTabBoundary:
    """Migration boundary for the Publish tab.

    The current release keeps behaviour delegated to ControlPanelWindow to avoid
    a risky rewrite. Future phases can move handlers here one workflow at a time
    while the public website remains untouched.
    """

    tab_key = "publish"
    tab_label = "Publish"

    def __init__(self, window: Any) -> None:
        self.window = window

    def build(self) -> Any:
        builder = getattr(self.window, "build_publish_tab")
        return builder()
