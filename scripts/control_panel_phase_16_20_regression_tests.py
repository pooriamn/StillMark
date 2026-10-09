#!/usr/bin/env python3
"""Static regression contracts for control-panel phases 16-20.

These checks intentionally avoid launching Qt. They protect the UI architecture
contracts introduced for the style/UI pass: stacked shell navigation, image-first
Works grid, skeleton loading, theme-owned spacing, and contextual inspection.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "scripts" / "control_panel.py"
COMPONENTS = ROOT / "scripts" / "control_panel_components.py"
THEME = ROOT / "scripts" / "control_panel_theme.qss"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_phase_16_stacked_side_nav_shell() -> None:
    panel = read(PANEL)
    shell_slice = panel[panel.find("def _build_ui"):panel.find("def _handle_tab_controller_select")]
    require("class NavStackedWidget(QStackedWidget)" in panel, "top-level stacked navigation shim missing")
    require("self.tabs = NavStackedWidget()" in shell_slice, "shell still does not instantiate stacked navigation")
    require("self.tabs = QTabWidget()" not in shell_slice, "top-level shell still instantiates QTabWidget")
    require("primaryNavStack" in panel, "stacked shell objectName missing")
    require("self.series_workspace_tabs = QTabWidget()" not in panel, "Series editor still uses a visible tab stack")
    require("series_editor_scroll" in panel and "series_sequence_section" in panel, "Series editor was not flattened into collapsible sections")


def test_phase_17_image_first_works_grid() -> None:
    panel = read(PANEL)
    components = read(COMPONENTS)
    require("self._works_model_view_enabled = False" in panel, "Works list still defaults to table/model view")
    require("self._gallery_mode = True" in panel, "Works gallery mode is not the default")
    require('QPushButton("List view")' in panel, "List view was not demoted to a secondary toolbar control")
    require("self.work_gallery_scroll.show()" in panel, "Works gallery is not visible by default")
    require("self.work_table.hide()" in panel, "Works table is not hidden by default")
    require("self.setMinimumSize(220, 218)" in components, "WorkGalleryCard is not sized as a premium image card")
    require("workGalleryStatusDot" in components, "WorkGalleryCard missing status dot")


def test_phase_18_loading_and_motion_feedback() -> None:
    panel = read(PANEL)
    theme = read(THEME)
    require("def _show_work_gallery_skeletons" in panel, "gallery skeleton method missing")
    require("workGallerySkeletonCard" in panel and "workGallerySkeletonCard" in theme, "skeleton card style missing")
    require("QPropertyAnimation(effect, b\"opacity\"" in panel, "opacity micro-transition missing")
    require("def _fade_in_work_editor" in panel, "work editor fade-in missing")
    require("def _set_tab_loading(self, tab_widget: QWidget | None, loading: bool, message:" in panel, "loading overlay not generalized")
    require("lastRefreshedLabel" in panel, "last-refreshed footer label missing")
    require("reduced_motion" in panel, "reduced-motion hook missing from animation paths")


def test_phase_19_theme_owned_spacing() -> None:
    panel = read(PANEL)
    theme = read(THEME)
    inline_styles = [line.strip() for line in panel.splitlines() if ".setStyleSheet(" in line and "self.setStyleSheet(combined)" not in line and "_status_dot" not in line]
    require(not inline_styles, f"inline stylesheet calls remain: {inline_styles[:5]}")
    require("QScrollArea::widget" in theme, "scroll-area background rule missing")
    require("font-size: 14px; font-weight: 700" in theme, "section heading type scale missing")
    require("font-size: 11px; font-weight: 400" in theme, "hint/refresh type scale missing")
    forbidden_off_grid = ["padding: 9px", "padding: 14px", "border-radius: 14px"]
    offenders = [token for token in forbidden_off_grid if token in theme]
    require(not offenders, f"off-grid spacing tokens remain: {offenders}")


def test_phase_20_contextual_inspector() -> None:
    panel = read(PANEL)
    theme = read(THEME)
    require("contextInspectorPreview" in panel and "contextInspectorPreview" in theme, "inspector preview missing")
    require("contextInspectorActions" in panel, "inspector quick actions missing")
    require("self.context_inspector_replace_btn" in panel, "work replace quick action missing")
    require("self.context_inspector_lineage_btn" in panel, "lineage quick action missing")
    require("def _inspector_edit_current" in panel, "inspector edit action missing")
    require("self.work_inspector_toggle_btn" in panel, "Works inspector toggle missing")
    require("self.series_inspector_toggle_btn" in panel, "Series inspector toggle missing")
    require("Completeness:" in panel and "Sequence:" in panel, "Series inspector completeness/sequence summary missing")


def main() -> None:
    test_phase_16_stacked_side_nav_shell()
    test_phase_17_image_first_works_grid()
    test_phase_18_loading_and_motion_feedback()
    test_phase_19_theme_owned_spacing()
    test_phase_20_contextual_inspector()
    print("control_panel_phase_16_20_regression_tests: OK")


if __name__ == "__main__":
    main()
