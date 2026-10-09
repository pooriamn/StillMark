#!/usr/bin/env python3
from __future__ import annotations

"""Regression contracts for control-panel phases 20-25.

These tests stay non-GUI. They prove launch doctor availability, data integrity,
bulk-operation safety reports, accessibility scan coverage, performance budgets,
and final release gate scaffolding without touching website UI/content.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_phase_20_launcher_doctor() -> None:
    doctor = SCRIPTS / "control_panel_doctor.py"
    require(doctor.exists(), "control_panel_doctor.py missing")
    ast.parse(doctor.read_text(encoding="utf-8"))
    panel = read("scripts/control_panel.py")
    require("--doctor" in panel and "control_panel_doctor" in panel.split("try:\n    from PySide6", 1)[0], "control_panel.py doctor path must run before PySide6 import")
    require("--launcher-check" in read("launch_control_panel.bat"), "Windows launcher does not run doctor")
    require("--launcher-check" in read("launch_control_panel.sh"), "Shell launcher does not run doctor")


def test_phase_21_data_integrity() -> None:
    from control_panel_data_integrity import validate_work_id_slug, build_reference_index, data_integrity_report
    require(validate_work_id_slug("valid-work-01")["ok"], "valid work id rejected")
    require(not validate_work_id_slug("Bad ID/unsafe")["ok"], "unsafe work id accepted")
    index = build_reference_index(ROOT)
    require("references" in index and "work_count" in index, "reference index shape invalid")
    report = data_integrity_report(ROOT)
    require("rows" in report and "errors" in report, "data integrity report shape invalid")


def test_phase_22_bulk_safety() -> None:
    from control_panel_bulk_ops import plan_bulk_operation, confirmation_phrase
    plan = plan_bulk_operation("bulk-edit", ["a", "b"], changes=[{"work_id": "a", "fields": ["published"]}], skipped=["b"], destructive=True)
    require(plan["confirmation_required"], "destructive bulk operation must require confirmation")
    require(plan["rollback"]["available"], "bulk operation must expose rollback hint")
    require(plan["per_item_results"][0]["status"] == "would-change", "per-item result missing")
    require(confirmation_phrase("bulk-edit", 2) == "APPLY BULK-EDIT 2", "confirmation phrase changed unexpectedly")


def test_phase_23_accessibility_scan() -> None:
    from control_panel_accessibility_audit import static_accessibility_rows
    rows = static_accessibility_rows(ROOT)
    checks = {row["check"] for row in rows}
    for required in {"Keyboard navigation", "Shortcut discoverability", "Visible focus", "Reduced motion", "No hover-only actions"}:
        require(required in checks, f"accessibility check missing: {required}")


def test_phase_24_performance_budgets() -> None:
    from control_panel_performance_budgets import PERFORMANCE_BUDGETS_MS, classify_budget, budget_rows
    require(PERFORMANCE_BUDGETS_MS["works filter"] <= 150, "works filter budget is too loose")
    require(PERFORMANCE_BUDGETS_MS["cached dashboard refresh"] <= 200, "cached dashboard budget is too loose")
    require(classify_budget("works filter", 200)["status"] == "slow", "slow budget classification failed")
    require(len(budget_rows()) >= 8, "budget rows incomplete")


def test_phase_25_release_gate_scaffold() -> None:
    gate = SCRIPTS / "control_panel_release_gate.py"
    require(gate.exists(), "control_panel_release_gate.py missing")
    ast.parse(gate.read_text(encoding="utf-8"))
    package_source = read("scripts/package_control_panel_release.py")
    require("run_final_release_gate" in package_source, "package script does not call final release gate")
    require((ROOT / "CONTROL_PANEL_RELEASE_CHECKLIST.md").exists(), "release checklist missing")
    require((ROOT / "CONTROL_PANEL_KNOWN_ISSUES.md").exists(), "known issues file missing")


def main() -> None:
    sys.path.insert(0, str(SCRIPTS))
    tests = [
        test_phase_20_launcher_doctor,
        test_phase_21_data_integrity,
        test_phase_22_bulk_safety,
        test_phase_23_accessibility_scan,
        test_phase_24_performance_budgets,
        test_phase_25_release_gate_scaffold,
    ]
    for test in tests:
        test()
    print("control_panel_phase_20_25_regression_tests: OK")


if __name__ == "__main__":
    main()
