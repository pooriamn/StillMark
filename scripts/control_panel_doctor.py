from __future__ import annotations

"""Command-line doctor for launching the Stillmark Qt control panel safely."""

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _dependency_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    required = [("yaml", "PyYAML"), ("PIL", "Pillow")]
    for module, label in required:
        try:
            __import__(module)
            rows.append({"status": "ok", "check": label, "detail": "available"})
        except Exception as exc:
            rows.append({"status": "error", "check": label, "detail": str(exc)})
    try:
        import PySide6  # type: ignore
        rows.append({"status": "ok", "check": "PySide6", "detail": getattr(PySide6, "__version__", "available")})
    except Exception as exc:
        rows.append({"status": "warning", "check": "PySide6", "detail": f"GUI launch requires PySide6: {exc}"})
    return rows


def run_doctor(root: Path = ROOT) -> dict[str, Any]:
    from control_panel_startup_guard import run_startup_guard
    from control_panel_scope_guard import package_hygiene_issues, scope_summary
    from control_panel_data_integrity import data_integrity_report
    from control_panel_performance_budgets import performance_budget_report, performance_smoke_check

    startup = run_startup_guard(root)
    integrity = data_integrity_report(root)
    rows = []
    rows.extend(_dependency_rows())
    rows.extend(startup.get("rows") or [])
    try:
        smoke = performance_smoke_check(root)
        for smoke_row in smoke.get("rows") or []:
            status = "ok" if smoke_row.get("status") == "ok" else ("warning" if not smoke_row.get("error") else "error")
            rows.append({"status": status, "check": f"Performance smoke · {smoke_row.get('name')}", "detail": f"{smoke_row.get('elapsed_ms')} ms / budget {smoke_row.get('budget_ms')} ms" + (f" · {smoke_row.get('error')}" if smoke_row.get('error') else "")})
    except Exception as exc:
        smoke = {"ok": False, "errors": 0, "warnings": 1, "rows": [], "error": str(exc)}
        rows.append({"status": "warning", "check": "Performance smoke", "detail": f"Skipped: {exc}"})
    hygiene = package_hygiene_issues()
    rows.append({"status": "ok" if not hygiene else "warning", "check": "Package hygiene", "detail": "clean" if not hygiene else f"{len(hygiene)} excluded/generated artifact(s) found in working tree"})
    errors = sum(1 for row in rows if str(row.get("status")) == "error") + int(integrity.get("errors") or 0)
    warnings = sum(1 for row in rows if str(row.get("status")) in {"warning", "watch"}) + int(integrity.get("warnings") or 0)
    return {
        "ok": errors == 0,
        "errors": errors,
        "warnings": warnings,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "startup": startup,
        "integrity": {k: v for k, v in integrity.items() if k != "reference_index"},
        "performance": {**performance_budget_report(), "smoke": smoke},
        "scope": scope_summary(),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether the Stillmark control panel can launch safely.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    parser.add_argument("--launcher-check", action="store_true", help="Use launcher-friendly output and exit code.")
    args = parser.parse_args(argv)
    report = run_doctor(ROOT)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    else:
        status = "OK" if report.get("ok") else "BLOCKED"
        print(f"Stillmark control-panel doctor: {status}")
        print(f"Python {report.get('python')} · {report.get('platform')}")
        print(f"Errors: {report.get('errors')} · warnings: {report.get('warnings')}")
        for row in report.get("rows", [])[:40]:
            print(f"[{row.get('status')}] {row.get('check')}: {row.get('detail')}")
        if int(report.get("errors") or 0):
            print("\nFix the error rows before launching the control panel.")
    return 2 if int(report.get("errors") or 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
