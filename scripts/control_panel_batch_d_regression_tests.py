#!/usr/bin/env python3
from __future__ import annotations
import ast, json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def require(c: bool, m: str) -> None:
    if not c: raise AssertionError(m)
def text(rel: str) -> str: return (ROOT / rel).read_text(encoding="utf-8")
def test_static_contracts() -> None:
    panel=text("scripts/control_panel.py"); budgets=text("scripts/control_panel_performance_budgets.py"); tasking=text("scripts/control_panel_tasking.py"); doctor=text("scripts/control_panel_doctor.py")
    for source in (panel,budgets,tasking,doctor): ast.parse(source)
    require("action_registry" in panel and "action_binding_report" in panel, "canonical action registry missing")
    require("_show_command_error" in panel, "unified command error reporting missing")
    require("record_budget_event" in panel, "UI performance events are not routed through budget logger")
    require("ProgressEvent" in tasking and "emit_progress" in tasking, "structured task progress missing")
    require("performance_smoke_check" in budgets and "profile_hotpaths" in budgets, "profiling/smoke budget helpers missing")
    require("performance_smoke_check(root)" in doctor, "doctor does not run performance smoke check")
    require((ROOT/"CONTROL_PANEL_PERFORMANCE_NOTES.md").exists(), "performance notes missing")
def test_smoke_cli() -> None:
    result=subprocess.run([sys.executable,"scripts/control_panel_profile_hotpaths.py","--smoke","--json"],cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
    try: payload=json.loads(result.stdout)
    except Exception: payload=json.loads(result.stdout.strip().splitlines()[-1] if result.stdout.strip().splitlines() else "{}")
    require("rows" in payload, f"smoke CLI did not return rows: {result.stdout[:500]}")
    require(any(str(row.get("name"))=="works filter" for row in payload.get("rows",[])), "works filter budget row missing")
def main() -> None:
    test_static_contracts(); test_smoke_cli(); print("control_panel_batch_d_regression_tests: OK")
if __name__=="__main__": main()
