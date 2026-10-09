from __future__ import annotations

from .base import WindowDelegatingTabController


class PagesTabController(WindowDelegatingTabController):
    """Phase 11 controller seam for structured pages and advanced YAML workflows."""

    tab_key = "pages"
    tab_label = "Content Builder"
    legacy_builder_name = "build_pages_tab"


PagesTabBoundary = PagesTabController
