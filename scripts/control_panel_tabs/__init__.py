from __future__ import annotations

"""Tab controllers and compatibility boundaries for the Qt control panel."""

from .base import TabControllerBase, WindowDelegatingTabController
from .dashboard import DashboardTabBoundary
from .works import WorksTabController, WorksTabBoundary
from .series import SeriesTabController, SeriesTabBoundary
from .pages import PagesTabController, PagesTabBoundary
from .publish import PublishTabBoundary
from .registry import PHASE14_TAB_BOUNDARIES, TabBoundarySpec, boundary_report, build_compatibility_specs

__all__ = [
    "TabControllerBase",
    "WindowDelegatingTabController",
    "DashboardTabBoundary",
    "WorksTabController",
    "WorksTabBoundary",
    "SeriesTabController",
    "SeriesTabBoundary",
    "PagesTabController",
    "PagesTabBoundary",
    "PublishTabBoundary",
    "PHASE14_TAB_BOUNDARIES",
    "TabBoundarySpec",
    "boundary_report",
    "build_compatibility_specs",
]
