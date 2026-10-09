from __future__ import annotations

"""Performance budget policy, profiling helpers, and smoke checks for the control panel.

This module is GUI-free. It can be used by the Qt shell, backend diagnostics,
doctor, and standalone profiling scripts without launching PySide6 or changing
public website output.
"""

import argparse
import cProfile
import io
import json
import pstats
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    from control_panel_io import append_jsonl, rotate_jsonl_log
except Exception:  # pragma: no cover
    from scripts.control_panel_io import append_jsonl, rotate_jsonl_log  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
META_DIR = ROOT / ".stillmrk-build" / "meta"
BUDGET_LOG_PATH = META_DIR / "control-panel-performance-budget-events.jsonl"
PROFILE_DIR = META_DIR / "profiles"

PERFORMANCE_BUDGETS_MS: dict[str, int] = {
    "cached dashboard refresh": 200,
    "dashboard refresh": 500,
    "dashboard deep health": 5000,
    "dashboard summary fast path": 500,
    "works selection": 100,
    "works filter": 250,
    "works refresh": 1200,
    "works load entries": 500,
    "visible asset-health batch": 250,
    "thumbnail batch": 400,
    "metadata save": 300,
    "structural work save": 3000,
    "publish tab cached refresh": 600,
    "release artifact scan": 5000,
    "startup": 2500,
    "startup-frame": 2500,
}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalise_action_name(name: str) -> str:
    return " ".join(str(name or "").strip().lower().replace("_", " ").split())


def budget_for(name: str) -> int | None:
    label = normalise_action_name(name)
    if label in PERFORMANCE_BUDGETS_MS:
        return PERFORMANCE_BUDGETS_MS[label]
    for key, value in PERFORMANCE_BUDGETS_MS.items():
        if key in label:
            return int(value)
    return None


def classify_budget(name: str, elapsed_ms: float) -> dict[str, Any]:
    label = normalise_action_name(name)
    budget = budget_for(label)
    status = "unbudgeted" if budget is None else ("ok" if float(elapsed_ms) <= budget else "slow")
    return {
        "name": label,
        "elapsed_ms": round(float(elapsed_ms), 3),
        "budget_ms": budget,
        "status": status,
        "over_by_ms": None if budget is None else max(0.0, round(float(elapsed_ms) - budget, 3)),
    }


def budget_rows() -> list[dict[str, str]]:
    return [{"status": "budget", "check": name, "detail": f"≤ {budget} ms"} for name, budget in sorted(PERFORMANCE_BUDGETS_MS.items())]


def record_budget_event(name: str, elapsed_ms: float, **extra: Any) -> dict[str, Any]:
    row = dict(classify_budget(name, elapsed_ms), **extra, timestamp=utc_stamp())
    try:
        META_DIR.mkdir(parents=True, exist_ok=True)
        rotate_jsonl_log(BUDGET_LOG_PATH, max_bytes=2 * 1024 * 1024)
        append_jsonl(BUDGET_LOG_PATH, row)
    except Exception:
        pass
    return row


@contextmanager
def budget_timer(name: str, **extra: Any) -> Iterator[dict[str, Any]]:
    started = time.perf_counter()
    row: dict[str, Any] = {"name": normalise_action_name(name), "elapsed_ms": 0.0, "status": "running"}
    try:
        yield row
    finally:
        row.update(record_budget_event(name, (time.perf_counter() - started) * 1000.0, **extra))


def recent_budget_events(limit: int = 50) -> list[dict[str, Any]]:
    if not BUDGET_LOG_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = BUDGET_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, int(limit or 50)):]
    except OSError:
        return []
    for line in lines:
        try:
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
        except Exception:
            continue
    return list(reversed(rows))


def _time_call(name: str, fn: Callable[[], Any]) -> dict[str, Any]:
    started = time.perf_counter()
    error = ""
    result_summary: Any = None
    try:
        result = fn()
        result_summary = len(result) if isinstance(result, (list, tuple, set, dict)) else type(result).__name__
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {**record_budget_event(name, elapsed_ms, source="smoke", result=result_summary, error=error), "error": error, "result": result_summary}


def performance_smoke_check(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or ROOT)
    scripts_dir = root / "scripts"
    import sys
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import qt_backend as qb  # type: ignore
    # Warm repository: this smoke checks interactive refresh paths, not import/cold-disk startup.
    try:
        qb.load_work_entries(); qb.load_works_filtered(fast=True)
    except Exception:
        pass
    rows = [
        _time_call("works load entries", lambda: qb.load_work_entries()),
        _time_call("works filter", lambda: qb.load_works_filtered(fast=True)),
        _time_call("dashboard summary fast path", lambda: qb.dashboard_summary(include_deep=False)),
    ]
    errors = [row for row in rows if row.get("error")]
    slow = [row for row in rows if row.get("status") == "slow"]
    status = "error" if errors else ("warning" if slow else "ok")
    return {"ok": not errors and not slow, "status": status, "rows": rows, "errors": len(errors), "warnings": len(slow), "generated_at": utc_stamp()}


def profile_callable(name: str, fn: Callable[[], Any], *, limit: int = 30) -> dict[str, Any]:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    profile = cProfile.Profile()
    started = time.perf_counter()
    error = ""
    result_summary: Any = None
    try:
        result = profile.runcall(fn)
        result_summary = len(result) if isinstance(result, (list, tuple, set, dict)) else type(result).__name__
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    stream = io.StringIO()
    pstats.Stats(profile, stream=stream).strip_dirs().sort_stats("cumtime").print_stats(max(1, int(limit or 30)))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_name = normalise_action_name(name).replace(" ", "-") or "profile"
    txt_path = PROFILE_DIR / f"{stamp}-{safe_name}.txt"
    json_path = PROFILE_DIR / f"{stamp}-{safe_name}.json"
    txt_path.write_text(stream.getvalue(), encoding="utf-8")
    row = record_budget_event(name, elapsed_ms, source="profile", profile=str(txt_path), result=result_summary, error=error)
    json_path.write_text(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {**row, "profile_txt": str(txt_path), "profile_json": str(json_path), "error": error}


def profile_hotpaths(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or ROOT)
    scripts_dir = root / "scripts"
    import sys
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import qt_backend as qb  # type: ignore
    rows = [
        profile_callable("works load entries", lambda: qb.load_work_entries()),
        profile_callable("works filter", lambda: qb.load_works_filtered(fast=True)),
        profile_callable("dashboard summary fast path", lambda: qb.dashboard_summary(include_deep=False)),
        profile_callable("publish tab cached refresh", lambda: qb.source_asset_report_rows(force=False)),
    ]
    return {"ok": not any(row.get("error") for row in rows), "rows": rows, "generated_at": utc_stamp()}


def performance_budget_report() -> dict[str, Any]:
    events = recent_budget_events()
    slow = [row for row in events if row.get("status") == "slow"]
    return {"ok": not slow, "budgets_ms": PERFORMANCE_BUDGETS_MS, "recent_events": events, "slow_events": slow, "generated_at": utc_stamp()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile and smoke-test Stillmark control-panel backend hot paths.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--profile", action="store_true", help="Write cProfile reports for hot paths.")
    parser.add_argument("--smoke", action="store_true", help="Run budget smoke checks. Default if --profile is omitted.")
    args = parser.parse_args(argv)
    payload = profile_hotpaths(ROOT) if args.profile else performance_smoke_check(ROOT)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    else:
        print("Control-panel performance " + ("profile" if args.profile else "smoke") + (": OK" if payload.get("ok") else ": ATTENTION"))
        for row in payload.get("rows", []):
            print(f"[{row.get('status')}] {row.get('name')}: {row.get('elapsed_ms')} ms · budget={row.get('budget_ms')} · {row.get('error') or row.get('profile_txt') or ''}")
    return 0 if payload.get("ok") else 1

if __name__ == "__main__":
    raise SystemExit(main())
