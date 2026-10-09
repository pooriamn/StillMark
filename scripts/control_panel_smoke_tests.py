from __future__ import annotations

"""Smoke tests for the Stillmark Qt control panel.

These checks are intentionally small. They prove the package boundary, import
surface, launch command wiring, and optional offscreen Qt GUI path without
modifying website UI/content files.
"""

import argparse
import importlib
import json
import os
import py_compile
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image

from control_panel_scope_guard import protected_scope, write_scope_report

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / ".stillmrk-build" / "meta" / "control-panel-smoke-report.json"


def _result(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def syntax_probe(paths: list[Path]) -> dict[str, Any]:
    rows = []
    for path in paths:
        try:
            py_compile.compile(str(path), doraise=True)
            rows.append(_result(path.relative_to(ROOT).as_posix(), True, "compiled"))
        except py_compile.PyCompileError as exc:
            rows.append(_result(path.relative_to(ROOT).as_posix(), False, str(exc)))
        except Exception as exc:
            rows.append(_result(path.relative_to(ROOT).as_posix(), False, f"{exc.__class__.__name__}: {exc}"))
    return {"name": "syntax-probe", "ok": all(row["ok"] for row in rows), "rows": rows}


def import_probe() -> dict[str, Any]:
    modules = [
        "control_panel_scope_guard",
        "control_panel_error_policy",
        "control_panel_io",
        "control_panel_runtime",
        "control_panel_tasking",
        "control_panel_layout_state",
        "control_panel_thread_safety",
        "control_panel_behavior_tests",
        "control_panel_tabs.registry",
    ]
    rows = []
    sys.path.insert(0, str(ROOT / "scripts"))
    for name in modules:
        try:
            importlib.import_module(name)
            rows.append(_result(name, True, "imported"))
        except Exception as exc:
            rows.append(_result(name, False, f"{exc.__class__.__name__}: {exc}"))
    return {"name": "import-probe", "ok": all(row["ok"] for row in rows), "rows": rows}


def offscreen_gui_probe(timeout_seconds: int = 20) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    command = [sys.executable, str(ROOT / "scripts" / "control_panel.py"), "--safe-mode", "--smoke-test"]
    try:
        completed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=timeout_seconds)
    except FileNotFoundError as exc:
        return _result("offscreen-gui-probe", False, f"Python executable not found: {exc}")
    except subprocess.TimeoutExpired:
        return _result("offscreen-gui-probe", False, f"Timed out after {timeout_seconds}s")
    output = (completed.stdout + "\n" + completed.stderr).strip()
    ok = completed.returncode == 0 and "GUI smoke test passed" in output
    return _result("offscreen-gui-probe", ok, output[-4000:])


def phase_21_25_backend_probe() -> dict[str, Any]:
    """Exercise the final audit hardening without touching website UI/content."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import qt_backend as qb  # type: ignore

    rows: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        rows.append(_result(name, ok, detail))

    started = time.perf_counter()
    preflight = qb.startup_preflight_checks()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    deferred = any(row.get("check") == "source asset truth" and row.get("status") == "warning" for row in preflight.get("rows", []))
    record("startup_preflight_checks defaults to fast source scan deferral", elapsed_ms <= 1500 and deferred, f"{elapsed_ms}ms · deferred={deferred}")

    try:
        story_rows = qb.series_story_rows()
        record("series_story_rows does not raise AttributeError", isinstance(story_rows, list), f"{len(story_rows)} row(s)")
    except AttributeError as exc:
        record("series_story_rows does not raise AttributeError", False, str(exc))
    except Exception as exc:
        record("series_story_rows does not raise AttributeError", False, f"{exc.__class__.__name__}: {exc}")

    temp_dir = ROOT / ".stillmrk-build" / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    palette_path = temp_dir / "smoke-palette-mode.png"
    im = Image.new("P", (8, 8))
    im.putpalette([0, 0, 0, 255, 255, 255] + [0, 0, 0] * 254)
    im.save(palette_path)
    try:
        digest = qb._stable_image_hash(palette_path)
        record("_stable_image_hash handles palette PNG", isinstance(digest, str) and len(digest) == 16, digest)
    except Exception as exc:
        record("_stable_image_hash handles palette PNG", False, f"{exc.__class__.__name__}: {exc}")
    finally:
        try:
            palette_path.unlink()
        except FileNotFoundError:
            pass

    works = qb.load_work_entries()
    if works:
        work_id = str(works[0].get("id") or "")
        old_invalidate = qb.invalidate_control_panel_caches
        old_mark = qb.mark_portfolio_health_dirty
        old_patch = qb.patch_cached_health_for_work
        calls: list[str] = []
        qb.invalidate_control_panel_caches = lambda *a, **k: calls.append("invalidate")  # type: ignore[assignment]
        qb.mark_portfolio_health_dirty = lambda *a, **k: calls.append("mark")  # type: ignore[assignment]
        qb.patch_cached_health_for_work = lambda *a, **k: calls.append("patch")  # type: ignore[assignment]
        try:
            qb.work_lineage_report(work_id)
            record("work_lineage_report is read-only", not calls, ", ".join(calls) or "no mutation calls")
        except Exception as exc:
            record("work_lineage_report is read-only", False, f"{exc.__class__.__name__}: {exc}")
        finally:
            qb.invalidate_control_panel_caches = old_invalidate  # type: ignore[assignment]
            qb.mark_portfolio_health_dirty = old_mark  # type: ignore[assignment]
            qb.patch_cached_health_for_work = old_patch  # type: ignore[assignment]
    else:
        record("work_lineage_report is read-only", True, "skipped: no works available")

    sequence = [f"smoke-work-{idx:03d}" for idx in range(100)]
    old_load_sequence = qb.load_series_sequence
    old_load_payload = qb.load_work_payload
    old_safe_preview = qb._safe_preview_path
    old_completeness = qb.fast_work_completeness_score
    qb.load_series_sequence = lambda slug: list(sequence)  # type: ignore[assignment]
    qb.load_work_payload = lambda work_id: {"id": work_id, "series": "smoke-series"}  # type: ignore[assignment]
    qb._safe_preview_path = lambda payload: None  # type: ignore[assignment]
    qb.fast_work_completeness_score = lambda payload, series_map=None: {"score": 100, "status": "ready"}  # type: ignore[assignment]
    try:
        started = time.perf_counter()
        suggested = qb.suggest_series_order("smoke-series")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        record("suggest_series_order handles 100 works quickly", elapsed_ms < 100 and sorted(suggested) == sorted(sequence), f"{elapsed_ms}ms")
    except Exception as exc:
        record("suggest_series_order handles 100 works quickly", False, f"{exc.__class__.__name__}: {exc}")
    finally:
        qb.load_series_sequence = old_load_sequence  # type: ignore[assignment]
        qb.load_work_payload = old_load_payload  # type: ignore[assignment]
        qb._safe_preview_path = old_safe_preview  # type: ignore[assignment]
        qb.fast_work_completeness_score = old_completeness  # type: ignore[assignment]

    return {"name": "phase-21-25-backend-probe", "ok": all(row["ok"] for row in rows), "rows": rows}


def run_smoke_tests(*, gui: bool = False, timeout_seconds: int = 20) -> dict[str, Any]:
    with protected_scope("control-panel-smoke-tests"):
        script_paths = [
            ROOT / "scripts" / "control_panel_scope_guard.py",
            ROOT / "scripts" / "control_panel_error_policy.py",
            ROOT / "scripts" / "control_panel_io.py",
            ROOT / "scripts" / "package_control_panel_release.py",
            ROOT / "scripts" / "verify_control_panel_package.py",
            ROOT / "scripts" / "control_panel_smoke_tests.py",
            ROOT / "scripts" / "control_panel_layout_state.py",
            ROOT / "scripts" / "control_panel_thread_safety.py",
            ROOT / "scripts" / "control_panel_behavior_tests.py",
            ROOT / "scripts" / "control_panel_tabs" / "registry.py",
        ]
        from control_panel_behavior_tests import run_behavior_tests
        checks: list[dict[str, Any]] = [syntax_probe(script_paths), import_probe(), {"name": "behavior-tests", **run_behavior_tests()}, phase_21_25_backend_probe()]
        if gui:
            checks.append(offscreen_gui_probe(timeout_seconds=timeout_seconds))
        report = {"ok": all(bool(check.get("ok")) for check in checks), "gui_requested": bool(gui), "checks": checks}
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        write_scope_report(ROOT / ".stillmrk-build" / "meta" / "control-panel-scope-report.json")
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stillmark control-panel smoke tests.")
    parser.add_argument("--gui", action="store_true", help="Also launch the Qt app offscreen with --smoke-test.")
    parser.add_argument("--timeout", type=int, default=20, help="GUI smoke-test timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()
    report = run_smoke_tests(gui=args.gui, timeout_seconds=max(5, args.timeout))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for check in report["checks"]:
            print(f"{'PASS' if check.get('ok') else 'FAIL'} {check.get('name')}")
        print(f"Report: {REPORT_PATH.relative_to(ROOT).as_posix()}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    code = main()
    import sys as _sys
    _sys.stdout.flush()
    _sys.stderr.flush()
    try:
        import os as _os
        _os._exit(int(code))
    except Exception:
        raise SystemExit(code)
