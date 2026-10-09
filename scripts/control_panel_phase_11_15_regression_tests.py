#!/usr/bin/env python3
"""Static regression contracts for control-panel phases 11-15.

These tests avoid launching Qt. They verify that the high-risk UI/refactor
contracts remain present in the source after future edits.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "scripts" / "control_panel.py"
TABS = ROOT / "scripts" / "control_panel_tabs"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_phase_11_controller_boundaries() -> None:
    panel = read(PANEL)
    base = read(TABS / "base.py")
    works = read(TABS / "works.py")
    series = read(TABS / "series.py")
    pages = read(TABS / "pages.py")
    require("class TabControllerBase(QObject)" in base, "tab controller base missing")
    require("class WorksTabController" in works, "works controller missing")
    require("class SeriesTabController" in series, "series controller missing")
    require("class PagesTabController" in pages, "pages controller missing")
    require("self.tab_controllers =" in panel, "ControlPanelWindow controller registry missing")
    require("_handle_tab_controller_select" in panel, "controller select signal handler missing")
    require("_handle_tab_controller_save" in panel, "controller save signal handler missing")


def test_phase_12_progressive_disclosure() -> None:
    panel = read(PANEL)
    require("Phase 12: focused, progressive-disclosure work editor" in panel, "work editor disclosure marker missing")
    require('CollapsibleSection("More fields"' in panel, "more-fields disclosure missing")
    require("workPublishStrip" in panel, "collapsed publishing strip missing")
    require("self.work_editor_steps = QTabWidget()" not in panel, "old five-tab works editor still active")
    require("Advanced YAML" in panel and "set_page_advanced_yaml_mode" in panel, "pages advanced YAML toggle missing")


def test_phase_13_command_palette_primary_navigation() -> None:
    panel = read(PANEL)
    require("commandPaletteSearchBar" in panel, "side-nav command search bar missing")
    require("Search works, series, commands… ⌘K" in panel, "command search placeholder missing")
    require("def _run_current_item" in panel, "command palette Enter activation missing")
    require("for work in list(load_work_entries()):" in panel, "all works are not registered dynamically")
    require("command_usage(f\"work:{work_id}\")" in panel, "dynamic work usage sorting not keyed correctly")
    require("increment_command_usage(key)" in panel, "dynamic command usage tracking missing")


def test_phase_14_publish_three_step_flow() -> None:
    panel = read(PANEL)
    require("WorkflowStepper([\"Check\", \"Package\", \"Upload\"])" in panel, "publish stepper must be Check/Package/Upload")
    require("def run_publish_check_step" in panel, "publish Check step handler missing")
    require("def copy_public_upload_path" in panel, "copy upload path action missing")
    require("self.publish_package_btn.setEnabled(check_passed)" in panel, "package button not gated by Check")
    require("Run Check before Package" in panel, "package guard message missing")
    require("Advanced release workspace…" in panel, "advanced release workspace link missing")


def test_phase_15_dashboard_fast_path() -> None:
    panel = read(PANEL)
    require('"deep_pending": False' in panel, "dashboard still schedules deep health automatically")
    require("def run_dashboard_health_check" in panel, "manual dashboard health check missing")
    require("dashboard_health_detail_section" in panel, "dashboard health disclosure missing")
    require("visible_actions = visible_actions[:3]" in panel, "dashboard action list not limited to top 3")
    require("_add_side_nav_header(\"Quick Access\")" not in panel, "duplicate Quick Access nav still present")


def main() -> None:
    test_phase_11_controller_boundaries()
    test_phase_12_progressive_disclosure()
    test_phase_13_command_palette_primary_navigation()
    test_phase_14_publish_three_step_flow()
    test_phase_15_dashboard_fast_path()
    print("control_panel_phase_11_15_regression_tests: OK")


if __name__ == "__main__":
    main()
