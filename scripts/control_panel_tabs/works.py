from __future__ import annotations

from .base import WindowDelegatingTabController


class WorksTabController(WindowDelegatingTabController):
    """Phase 11 controller seam for the Works editor and gallery."""

    tab_key = "works"
    tab_label = "Works"
    legacy_builder_name = "build_works_tab"


# Backward-compatible import used by older packages/tests.
WorksTabBoundary = WorksTabController
