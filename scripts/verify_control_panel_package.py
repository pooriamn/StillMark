from __future__ import annotations

"""Local sanity checks for Stillmark control-panel packages.

The verifier intentionally avoids launching PySide6. Full GUI launch is handled
by scripts/control_panel_smoke_tests.py --gui.
"""

from pathlib import Path
import os
import json
import py_compile
import sys
import hashlib

from control_panel_scope_guard import find_corrupted_filename_artifacts, package_hygiene_issues, scope_summary

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    ROOT / "scripts" / "control_panel.py",
    ROOT / "scripts" / "qt_backend.py",
    ROOT / "scripts" / "control_panel_components.py",
    ROOT / "scripts" / "control_panel_design.py",
    ROOT / "scripts" / "control_panel.py",
    ROOT / "scripts" / "control_panel_scope_guard.py",
    ROOT / "scripts" / "control_panel_error_policy.py",
    ROOT / "scripts" / "control_panel_io.py",
    ROOT / "scripts" / "control_panel_behavior_tests.py",
    ROOT / "scripts" / "control_panel_thread_safety.py",
    ROOT / "scripts" / "control_panel_layout_state.py",
    ROOT / "scripts" / "control_panel_smoke_tests.py",
    ROOT / "scripts" / "control_panel_doctor.py",
    ROOT / "scripts" / "control_panel_data_integrity.py",
    ROOT / "scripts" / "control_panel_bulk_ops.py",
    ROOT / "scripts" / "control_panel_accessibility_audit.py",
    ROOT / "scripts" / "control_panel_performance_budgets.py",
    ROOT / "scripts" / "control_panel_release_gate.py",
    ROOT / "scripts" / "package_control_panel_release.py",
    ROOT / "scripts" / "verify_control_panel_package.py",
    ROOT / "scripts" / "control_panel_backend_regression_tests.py",
    ROOT / "scripts" / "services" / "content_service.py",
    ROOT / "scripts" / "services" / "asset_service.py",
    ROOT / "scripts" / "services" / "publish_service.py",
    ROOT / "scripts" / "services" / "diagnostics_service.py",
    ROOT / "scripts" / "services" / "health_service.py",
    ROOT / "scripts" / "services" / "refresh_service.py",
    ROOT / "scripts" / "control_panel_tabs" / "dashboard.py",
    ROOT / "scripts" / "control_panel_tabs" / "works.py",
    ROOT / "scripts" / "control_panel_tabs" / "series.py",
    ROOT / "scripts" / "control_panel_tabs" / "pages.py",
    ROOT / "scripts" / "control_panel_tabs" / "publish.py",
    ROOT / "scripts" / "control_panel_tabs" / "registry.py",
    ROOT / "requirements-qt.txt",
]

COMPILE_REQUIRED = [
    ROOT / "scripts" / "control_panel_scope_guard.py",
    ROOT / "scripts" / "control_panel_error_policy.py",
    ROOT / "scripts" / "control_panel_io.py",
    ROOT / "scripts" / "control_panel_smoke_tests.py",
    ROOT / "scripts" / "package_control_panel_release.py",
    ROOT / "scripts" / "verify_control_panel_package.py",
    ROOT / "scripts" / "control_panel_runtime.py",
    ROOT / "scripts" / "control_panel_tasking.py",
    ROOT / "scripts" / "control_panel_doctor.py",
    ROOT / "scripts" / "control_panel_data_integrity.py",
    ROOT / "scripts" / "control_panel_bulk_ops.py",
    ROOT / "scripts" / "control_panel_accessibility_audit.py",
    ROOT / "scripts" / "control_panel_performance_budgets.py",
    ROOT / "scripts" / "control_panel_release_gate.py",
    ROOT / "scripts" / "control_panel_tabs" / "registry.py",
]

LEGACY_STUBS: list[Path] = []  # the archived Tk modules were deleted; git history keeps them

CRITICAL_HASH_FILES = [
    ROOT / "scripts" / "control_panel.py",
    ROOT / "scripts" / "qt_backend.py",
    ROOT / "scripts" / "helpers_content.py",
    ROOT / "scripts" / "control_panel_release_gate.py",
    ROOT / "scripts" / "verify_control_panel_package.py",
    ROOT / "scripts" / "package_control_panel_release.py",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def critical_file_hashes() -> dict[str, str]:
    return {path.relative_to(ROOT).as_posix(): sha256_file(path) for path in CRITICAL_HASH_FILES if path.exists()}


def verify_manifest_hashes(current_hashes: dict[str, str]) -> list[str]:
    manifest_path = ROOT / "CONTROL_PANEL_RELEASE_MANIFEST.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    expected = manifest.get("critical_file_hashes")
    if not isinstance(expected, dict):
        return []
    problems: list[str] = []
    for rel_path, expected_hash in expected.items():
        current = current_hashes.get(str(rel_path))
        if current and str(expected_hash) and current != str(expected_hash):
            problems.append(f"Hash mismatch for {rel_path}: manifest={expected_hash} current={current}")
    return problems


def compile_path(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    compile(source, str(path), "exec")


def source_sanity(path: Path, *, required_markers: list[str]) -> list[str]:
    source = path.read_text(encoding="utf-8", errors="replace")
    problems: list[str] = []
    if source.count('\"\"\"') % 2:
        problems.append(f"Unbalanced triple double-quoted string markers in {path.relative_to(ROOT)}")
    if source.count("'''" ) % 2:
        problems.append(f"Unbalanced triple single-quoted string markers in {path.relative_to(ROOT)}")
    for marker in required_markers:
        if marker not in source:
            problems.append(f"Expected marker missing from {path.relative_to(ROOT)}: {marker}")
    return problems


def main() -> int:
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED if not path.exists()]
    if missing:
        print("Missing required files:")
        for item in missing:
            print(f"- {item}")
        return 1

    for path in COMPILE_REQUIRED:
        if path.suffix == ".py":
            try:
                print(f"Checking syntax: {path.relative_to(ROOT)}", flush=True)
                compile_path(path)
            except Exception as exc:
                print(f"Compile failed: {path.relative_to(ROOT)}\n{exc}")
                return 1

    # Service/tab modules are import-boundary checked by required-file presence here;
    # behavior-level coverage belongs in the dedicated regression suites.

    print("Checking legacy stubs", flush=True)
    for path in LEGACY_STUBS:
        print(f"Checking legacy stub: {path.relative_to(ROOT)}", flush=True)
        if not path.exists():
            print(f"Missing legacy compatibility stub: {path.relative_to(ROOT)}")
            return 1
        source = path.read_text(encoding="utf-8")
        legacy_import = "import " + "tkinter"
        legacy_from = "from " + "tkinter"
        if legacy_import in source or legacy_from in source:
            print(f"Legacy Tkinter import still active: {path.relative_to(ROOT)}")
            return 1
        if "ARCHIVED_MODULE" not in source:
            print(f"Legacy stub marker missing: {path.relative_to(ROOT)}")
            return 1

    print("Checking corrupted filename artifacts", flush=True)
    corrupted = find_corrupted_filename_artifacts()
    if corrupted:
        print("Corrupted legacy filename artifacts are present in the working tree. They are excluded from clean release packages:")
        for item in corrupted[:20]:
            print(f"- {item}")
        if len(corrupted) > 20:
            print(f"... {len(corrupted) - 20} more")

    print("Building scope summary", flush=True)
    scope = scope_summary()
    active_tk = scope.get("active_tk_files") or []
    if active_tk:
        print("Active Tkinter files detected:")
        for item in active_tk:
            print(f"- {item}")
        return 1

    print("Checking critical script hashes", flush=True)
    hashes = critical_file_hashes()
    if len(hashes) < 4:
        print("Critical script hash coverage is incomplete.")
        return 1
    hash_problems = verify_manifest_hashes(hashes)
    if hash_problems:
        print("Critical script hash verification failed:")
        for item in hash_problems:
            print(f"- {item}")
        return 1

    print("Reading marker files", flush=True)
    panel = (ROOT / "scripts" / "control_panel.py").read_text(encoding="utf-8", errors="replace")
    backend = (ROOT / "scripts" / "qt_backend.py").read_text(encoding="utf-8", errors="replace")
    current_markers = [
        "WorkflowStepper",
        "--safe-mode",
        "build_dashboard_tab",
        "build_publish_tab",
        "populate_work_form",
        "populate_series_form",
        "_start_dashboard_deep_health_refresh",
        "open_source_recovery_dialog",
        "RefreshCoordinator",
        "normalise_control_panel_state",
        "build_compatibility_specs",
        "_sync_publish_review_panels",
        "toggle_reduced_motion",
        "run_control_panel_regression_checks",
        "safe_remove_current_work",
        "export_panel_diagnostic_bundle",
        "FIXED_CONTROL_PANEL_DENSITY",
        "Type a command, work title, series, or page",
    ]
    for needle in current_markers:
        if needle not in panel:
            print(f"Expected current GUI marker missing: {needle}")
            return 1

    backend_markers = [
        "dashboard_fast_readiness",
        "portfolio_health_report",
        "source_recovery_summary",
        "asset_truth_report_rows",
        "invalidate_control_panel_caches",
        "safe_remove_work",
        "export_control_panel_diagnostic_bundle",
        "stale_asset_cleanup_report",
        "thread_safety_summary",
        "state_diagnostics",
        "control_panel_data_integrity_report",
        "control_panel_performance_budget_report",
    ]
    for needle in backend_markers:
        if needle not in backend:
            print(f"Expected backend marker missing: {needle}")
            return 1

    report_path = ROOT / ".stillmrk-build" / "meta" / "control-panel-verification-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "ok": True,
        "compiled": [path.relative_to(ROOT).as_posix() for path in COMPILE_REQUIRED],
        "scope": scope,
        "critical_file_hashes": hashes,
        "package_hygiene_counts": {},
        "note": "GUI launch is covered by optional smoke test; this verifier uses py_compile plus critical SHA-256 hashes for syntax/content checks.",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Control-panel package sanity checks passed.")
    return 0


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
