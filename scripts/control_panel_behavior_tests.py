from __future__ import annotations

"""Non-GUI behavior tests for Phase 14-19 hardening.

These tests avoid PySide imports and never touch website output. They validate
that the new safety boundaries, state migration, startup preflight, diagnostics,
and thread-safety scanners behave like real code rather than marker checks.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from control_panel_layout_state import CONTROL_PANEL_STATE_SCHEMA_VERSION, normalise_control_panel_state
from control_panel_startup_guard import run_startup_guard
from control_panel_thread_safety import thread_safety_summary
from control_panel_io import append_jsonl
from control_panel_scope_guard import protected_scope

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / ".stillmrk-build" / "meta" / "control-panel-behavior-report.json"


def _row(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def test_state_migration() -> dict[str, Any]:
    dirty = {
        "state_schema_version": 1,
        "geometry": [99999, -99999, 100, 100],
        "splitters": {"works-main-splitter": [0, -4, 100], "control-panel-main-splitter": [10, 20, 0]},
        "layout_polish_version": "phase-test",
        "notifications": list(range(120)),
    }
    clean, report = normalise_control_panel_state(dirty, layout_version="phase-test")
    ok = (
        clean.get("state_schema_version") == CONTROL_PANEL_STATE_SCHEMA_VERSION
        and clean["geometry"][2] >= 1060
        and clean["geometry"][3] >= 700
        and "works-main-splitter" not in clean.get("splitters", {})
        and clean.get("splitters", {}).get("control-panel-main-splitter", [])[-1] == 0
        and len(clean.get("notifications") or []) <= 80
        and report.migrated
    )
    return _row("versioned UI-state migration clamps unsafe values", ok, json.dumps(clean, sort_keys=True))


def test_jsonl_append_rotation() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        append_jsonl(path, {"event": "one"})
        append_jsonl(path, {"event": "two"})
        lines = path.read_text(encoding="utf-8").splitlines()
        ok = len(lines) == 2 and all(json.loads(line).get("event") for line in lines)
        return _row("locked JSONL append writes valid rows", ok, f"rows={len(lines)}")


def test_startup_preflight_duplicate_ids() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel in ["scripts", "content/works", "content/series", "content/pages", ".stillmrk-build/meta"]:
            (root / rel).mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "control_panel_theme.qss").write_text("QWidget { color: #fff; }", encoding="utf-8")
        (root / "content" / "works" / "a.yaml").write_text("id: same\ntitle: A\n", encoding="utf-8")
        (root / "content" / "works" / "b.yaml").write_text("id: same\ntitle: B\n", encoding="utf-8")
        report = run_startup_guard(root)
        details = "\n".join(str(row.get("detail")) for row in report.get("rows", []))
        ok = not report.get("ok") and "Duplicate work id" in details
        return _row("startup preflight blocks duplicate work IDs", ok, details)


def test_thread_safety_scan() -> dict[str, Any]:
    summary = thread_safety_summary(ROOT)
    ok = bool(summary.get("ok"))
    detail = f"errors={summary.get('errors')} warnings={summary.get('warnings')}"
    return _row("Qt thread-safety scanner reports no worker GUI errors", ok, detail)


def run_behavior_tests() -> dict[str, Any]:
    with protected_scope("control-panel-behavior-tests"):
        checks = [
            test_state_migration(),
            test_jsonl_append_rotation(),
            test_startup_preflight_duplicate_ids(),
            test_thread_safety_scan(),
        ]
        report = {"ok": all(check["ok"] for check in checks), "checks": checks}
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report


def main() -> int:
    report = run_behavior_tests()
    for check in report["checks"]:
        print(f"{'PASS' if check['ok'] else 'FAIL'} {check['name']} — {check.get('detail', '')}")
    print(f"Report: {REPORT_PATH.relative_to(ROOT).as_posix()}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    code = main()
    # Some headless verification environments keep optional importer cleanup
    # hooks alive after tests finish. This CLI is side-effect-contained and has
    # already flushed its JSON report, so exit deterministically.
    import sys
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(int(code))
