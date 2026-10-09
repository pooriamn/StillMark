from __future__ import annotations

"""Fixture-safe backend regression contracts for Stillmark control-panel hardening.

These tests are designed for local developer runs. They avoid mutating the real
portfolio by checking callable contracts and transaction markers statically.
For full mutation tests, copy the project to a temporary fixture folder first.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    compile(source, str(path), "exec")
    return source


def _functions(source: str) -> set[str]:
    tree = ast.parse(source)
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def main() -> int:
    backend_path = ROOT / "scripts" / "qt_backend.py"
    panel_path = ROOT / "scripts" / "control_panel.py"
    backend = _source(backend_path)
    panel = _source(panel_path)
    backend_functions = _functions(backend)
    panel_functions = _functions(panel)

    required_backend = {
        "safe_remove_work_preview",
        "safe_remove_work",
        "preview_replace_work_image",
        "replace_work_image",
        "relink_source_image",
        "bulk_relink_missing_sources",
        "portfolio_health_report",
        "missing_source_recovery_rows",
        "export_control_panel_diagnostic_bundle",
        "stale_asset_cleanup_report",
    }
    required_panel = {
        "unlock_current_work_id_for_safe_rename",
        "safe_remove_current_work",
        "clear_work_icon_cache",
        "_dynamic_command_target_rows",
        "_runtime_accessibility_rows",
        "reset_adaptive_layout",
        "run_control_panel_regression_checks",
    }

    missing = sorted(required_backend - backend_functions)
    missing += sorted(required_panel - panel_functions)
    if missing:
        raise AssertionError(f"Missing backend/panel regression contract(s): {missing}")

    contract_markers = [
        "qt-remove-work",
        "BackendIntegrityError",
        "invalidate_control_panel_caches",
        "source_asset_issues",
        "release_gate_summary",
        "save_ui_state",
        "recent_commands",
        "splitters",
    ]
    for marker in contract_markers:
        if marker not in backend and marker not in panel:
            raise AssertionError(f"Expected regression marker missing: {marker}")

    forbidden_panel_markers = ["density" + "_combo", "set_density" + "_mode", "DENSITY" + "_ORDER"]
    found_forbidden = [marker for marker in forbidden_panel_markers if marker in panel]
    if found_forbidden:
        raise AssertionError(f"Removed density controls still present: {found_forbidden}")

    print("Backend regression contracts passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
