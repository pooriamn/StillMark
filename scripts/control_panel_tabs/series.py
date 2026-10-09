from __future__ import annotations

from .base import WindowDelegatingTabController


class SeriesTabController(WindowDelegatingTabController):
    """Phase 11 controller seam for Series identity, story, and sequence workflows."""

    tab_key = "series"
    tab_label = "Series"
    legacy_builder_name = "build_series_tab"


SeriesTabBoundary = SeriesTabController
