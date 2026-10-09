from __future__ import annotations

"""Regression checks for the Stillmark control-panel package.

The file intentionally avoids launching PySide6. It performs syntax checks and
static contract checks for the risky behaviours that phases 16-20 hardened:
non-blocking feedback, command-palette navigation targets, adaptive layout reset,
runtime accessibility audit hooks, and density-control removal.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _compile(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    compile(source, str(path), "exec")
    return source


def _function_names(source: str) -> set[str]:
    tree = ast.parse(source)
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def main() -> int:
    panel_path = ROOT / "scripts" / "control_panel.py"
    backend_path = ROOT / "scripts" / "qt_backend.py"
    verifier_path = ROOT / "scripts" / "verify_control_panel_package.py"
    scope_guard_path = ROOT / "scripts" / "control_panel_scope_guard.py"
    package_path = ROOT / "scripts" / "package_control_panel_release.py"
    for path in [panel_path, backend_path, verifier_path, scope_guard_path, package_path]:
        _compile(path)

    panel = panel_path.read_text(encoding="utf-8")
    backend = backend_path.read_text(encoding="utf-8")
    packager = package_path.read_text(encoding="utf-8")
    functions = _function_names(panel)

    required_functions = {
        "safe_remove_current_work",
        "export_panel_diagnostic_bundle",
        "show_stale_asset_cleanup_report",
        "_confirm_restore_editor_draft",
        "_notify_nonblocking",
        "_critical_modal",
        "_dynamic_command_target_rows",
        "_run_dynamic_command_target",
        "reset_adaptive_layout",
        "_runtime_accessibility_rows",
        "run_control_panel_regression_checks",
    }
    missing_functions = sorted(required_functions - functions)
    if missing_functions:
        raise AssertionError(f"Missing phase 16-20 function(s): {missing_functions}")

    panel_markers = [
        "FIXED_CONTROL_PANEL_DENSITY",
        "Type a command, work title, series, or page",
        "work:",
        "series:",
        "page:",
        "Target size",
        "Drag alternatives",
        "Layout reset",
        "Run regression checks",
    ]
    backend_markers = [
        "safe_remove_work(",
        "stale_asset_cleanup_report",
        "export_control_panel_diagnostic_bundle",
        "BackendIntegrityError",
        "qt-remove-work",
        "portfolio_health_report",
        "missing_source_recovery_rows",
        "Scope guard",
        "Backend services",
        "Tab boundaries",
    ]
    packager_markers = ["control-panel-only", "full-clean-project", "protected"]
    removed_markers = ["density" + "_combo", "set_density" + "_mode", "DENSITY" + "_ORDER"]

    forbidden = [marker for marker in removed_markers if marker in panel]
    if forbidden:
        raise AssertionError(f"Removed density feature marker(s) still present: {forbidden}")

    missing = [marker for marker in panel_markers if marker not in panel]
    missing += [marker for marker in backend_markers if marker not in backend]
    missing += [marker for marker in packager_markers if marker not in packager]
    if missing:
        raise AssertionError(f"Missing regression marker(s): {missing}")

    # Phase 16: success diagnostics must not end in a modal success box.
    if "Diagnostic bundle exported\", f\"Saved diagnostic bundle" in panel:
        raise AssertionError("Diagnostic bundle success still uses a blocking message box.")

    # Phase 18: layout state should persist the active responsive profile.
    if '"layout_profile"' not in panel:
        raise AssertionError("Adaptive layout profile is not persisted in UI state.")



    # Phase 1-5 hardening: preview paths must be normalised before filesystem
    # operations, work lineage must stay read-only, rename cleanup must compare
    # resolved path identity through _same_path(), batch source moves must be
    # transaction-aware, and duplicated works must immediately patch health.
    phase_1_5_backend_markers = [
        "def _safe_preview_path",
        "with Image.open(Path(preview))",
        "not _same_path(old_generated, new_generated)",
        "guarded_move(source_path_obj, destination, detail=\"batch-series-move\")",
        "batch_series_move",
        "patch_cached_health_for_work(candidate)",
        "mark_portfolio_health_dirty(\"work\", candidate)",
    ]
    missing_phase_1_5 = [marker for marker in phase_1_5_backend_markers if marker not in backend]
    if missing_phase_1_5:
        raise AssertionError(f"Missing phase 1-5 backend hardening marker(s): {missing_phase_1_5}")

    lineage_block = backend.split("def work_lineage_report", 1)[1].split("def _load_curation_notes", 1)[0]
    forbidden_lineage_side_effects = [
        "invalidate_control_panel_caches()",
        "mark_portfolio_health_dirty(\"work\", work_id)",
        "patch_cached_health_for_work(work_id)",
    ]
    leaked = [marker for marker in forbidden_lineage_side_effects if marker in lineage_block]
    if leaked:
        raise AssertionError(f"work_lineage_report is no longer read-only: {leaked}")

    # Rename path-safety regression note: on case-insensitive or mixed
    # absolute/relative path filesystems, derivative cleanup must use _same_path
    # semantics instead of direct Path equality.
    if "old_generated != new_generated" in backend or "old_derivative_dir != derivative_dir" in backend:
        raise AssertionError("Rename derivative cleanup still uses direct Path inequality.")

    if "THEME_ALIASES" not in panel or "resolved_control_panel_theme" not in panel:
        raise AssertionError("Theme aliases are not resolved through a single deterministic map.")
    if "Phase 06-10 hotfix" in panel or "THEME.setdefault" in panel:
        raise AssertionError("Legacy QSS token setdefault hotfix still exists.")
    required_theme_tokens = ["bg_window", "text", "font_family", "font_size", "border_focus", "radius_pill", "accent_green"]
    for token in required_theme_tokens:
        if f"theme['{token}']" in panel and token not in panel:
            raise AssertionError(f"QSS token {token} is not represented in the resolved theme source.")
    design = (ROOT / "scripts" / "control_panel_design.py").read_text(encoding="utf-8")
    for canonical in ["bg_primary", "text_primary", "success", "font_family", "font_size"]:
        if f'"{canonical}"' not in design:
            raise AssertionError(f"Canonical theme token missing from control_panel_design.py: {canonical}")


    phase_6_10_markers = [
        "self._dirty_tabs: dict[str, float]",
        "self._last_scope_refresh_at",
        "previous_key = self._tab_key_for_index(previous) or \"dashboard\"",
        "self._mark_dirty({previous_key})",
        "skipped duplicate dashboard refresh while one is already running",
        "ThumbnailLoader(QRunnable)",
        "QTimer.singleShot(50, self._load_next_gallery_thumbnail_batch)",
        "_gallery_thumbnail_queue",
        "_qt_object_alive(card)",
        "with signals_blocked(self):",
        "reset_snapshot: bool = True",
        "self._draft_payload_hash(current_payload) == self._draft_payload_hash(loaded_snapshot)",
        "_structured_worker_error",
        "control-panel-diagnostics.jsonl",
        "View detail",
    ]
    missing_phase_6_10 = [marker for marker in phase_6_10_markers if marker not in panel]
    if missing_phase_6_10:
        raise AssertionError(f"Missing phase 6-10 hardening marker(s): {missing_phase_6_10}")

    components = (ROOT / "scripts" / "control_panel_components.py").read_text(encoding="utf-8")
    if "QPixmap(str(image_path))" in components:
        raise AssertionError("WorkGalleryCard still loads QPixmap synchronously from disk.")
    if "Loading preview…" not in components or "def set_pixmap" not in components:
        raise AssertionError("WorkGalleryCard does not expose deferred thumbnail population.")

    on_tab_changed_block = panel.split("    def on_tab_changed", 1)[1].split("    def open_authority_panel", 1)[0]
    if "refresh_all_context(force=True" in on_tab_changed_block:
        raise AssertionError("Tab switch handler still schedules a forced refresh while leaving a tab.")
    if "_dirty_tabs.add" in panel or "_dirty_tabs.discard" in panel:
        raise AssertionError("Dirty tab registry still uses unbounded set-style add/discard calls.")

    task_error_block = panel.split("    def _parse_worker_error", 1)[1].split("    def _task_finished", 1)[0]
    if "json.loads" not in task_error_block or "QPlainTextEdit" not in task_error_block:
        raise AssertionError("Task errors are not parsed as structured diagnostics with a detail viewer.")


    # Audit Phases 6-10: thread-safe bounded caches, canonical JSONL rotation,
    # timer diagnostics, fast Works filtering, and duplicate-scan image safety.
    audit_phase_6_10_backend_markers = [
        "_IMAGE_DIMENSIONS_CACHE_LOCK",
        "_IMAGE_DIMENSIONS_CACHE_MAX",
        "_FINGERPRINT_CACHE_LOCK",
        "_FINGERPRINT_CACHE_MAX",
        "rotate_jsonl_log as _rotate_jsonl_log",
        "fast: bool = True",
        "series_map = work_to_series_map() if fast_mode else {}",
        "fast_work_completeness_score(payload, series_map=series_map)",
        "Full completeness score including filesystem source-asset scan",
        "im.mode in (\"P\", \"PA\")",
        "len(pixels) != 64",
        "_DUPLICATE_SCAN_LOCK.acquire(timeout=60)",
        "progress_callback(total, total)",
    ]
    missing_audit_phase_6_10_backend = [marker for marker in audit_phase_6_10_backend_markers if marker not in backend]
    if missing_audit_phase_6_10_backend:
        raise AssertionError(f"Missing audit phase 6-10 backend marker(s): {missing_audit_phase_6_10_backend}")

    io_source = (ROOT / "scripts" / "control_panel_io.py").read_text(encoding="utf-8")
    timer_source = (ROOT / "scripts" / "control_panel_timer.py").read_text(encoding="utf-8")
    audit_phase_6_10_io_timer_markers = [
        "def rotate_jsonl_log",
        "_JSONL_LOCKS_MAX",
        "def _prune_jsonl_locks",
        "lock_key, lock = _lock_for(target)",
        "def subscriber_count",
        "RuntimeError as exc",
        "TimerBus subscriber callback failed",
        "_record_timer_warning",
    ]
    joined_io_timer = io_source + "\n" + timer_source
    missing_audit_phase_6_10_io_timer = [marker for marker in audit_phase_6_10_io_timer_markers if marker not in joined_io_timer]
    if missing_audit_phase_6_10_io_timer:
        raise AssertionError(f"Missing audit phase 6-10 IO/timer marker(s): {missing_audit_phase_6_10_io_timer}")




    # Audit Phases 11-15: efficient series-order suggestion, bounded UI state,
    # buffered command usage, guarded lineage social refs, and precise batch results.
    audit_phase_11_15_backend_markers = [
        "low = deque(",
        "seen: set[str]",
        "suggest_series_order called on very large sequence",
        "def flush_command_usage",
        "_COMMAND_USAGE_PENDING",
        "pending_count = int(_COMMAND_USAGE_PENDING.get(label_text, 0))",
        "social_candidates = sorted(social_dir.glob('*')) if social_dir.exists() else []",
        "presence = {\"status\": \"error\", \"message\": str(exc)}",
        "derivative_failures: list[str]",
        "actual_per_item_results.append",
        "patch_cached_health_for_work(row[\"work_id\"])",
    ]
    missing_audit_phase_11_15_backend = [marker for marker in audit_phase_11_15_backend_markers if marker not in backend]
    if missing_audit_phase_11_15_backend:
        raise AssertionError(f"Missing audit phase 11-15 backend marker(s): {missing_audit_phase_11_15_backend}")

    layout_source = (ROOT / "scripts" / "control_panel_layout_state.py").read_text(encoding="utf-8")
    panel_phase_11_15_markers = [
        "max_tab_index: int = 9",
        "EXPECTED_SPLITTER_PANE_COUNTS",
        "expected_count is not None",
        "MAX_SAVED_NOTIFICATIONS",
        "command-usage-flush",
        "flush_command_usage()",
    ]
    joined_phase_11_15 = layout_source + "\n" + panel
    missing_panel_phase_11_15 = [marker for marker in panel_phase_11_15_markers if marker not in joined_phase_11_15]
    if missing_panel_phase_11_15:
        raise AssertionError(f"Missing audit phase 11-15 UI-state marker(s): {missing_panel_phase_11_15}")



    # Audit Phases 16-20: preview/source path exception hygiene, canonical
    # JSONL rotation, page-builder indentation sanity, series-cache locks, and
    # build-timeout diagnostics.
    audit_phase_16_20_backend_markers = [
        "def _resolve_source_path",
        "Only expected I/O/value failures are softened into diagnostics",
        "except (OSError, FileNotFoundError, ValueError) as exc",
        "No preview path could be resolved for work",
        "rotate_jsonl_log as _rotate_jsonl_log",
        "_SERIES_COMPLETENESS_CACHE_LOCK",
        "_SERIES_SLUG_CACHE_LOCK",
        "with _SERIES_COMPLETENESS_CACHE_LOCK:",
        "with _SERIES_SLUG_CACHE_LOCK:",
        "Build timed out after {build_result.get('timeout_seconds', '?')} seconds",
        "_record_diagnostic_event(\n            \"build\",\n            \"timeout\"",
        "refresh_image_manifests(line_callback=line_callback)",
        "Build process finished with exit code",
    ]
    missing_audit_phase_16_20_backend = [marker for marker in audit_phase_16_20_backend_markers if marker not in backend]
    if missing_audit_phase_16_20_backend:
        raise AssertionError(f"Missing audit phase 16-20 backend marker(s): {missing_audit_phase_16_20_backend}")

    if "def _rotate_jsonl_log" in backend:
        raise AssertionError("qt_backend.py reintroduced a duplicate _rotate_jsonl_log implementation.")

    for function_name in [
        "available_document_ids",
        "_page_issue_rows",
        "_page_model_from_payload",
        "review_page_builder_model",
        "review_page_yaml_text",
        "load_page_builder_bundle",
        "save_page_builder_model",
    ]:
        if f"\n        def {function_name}" in backend:
            raise AssertionError(f"{function_name} is indented as though it were nested.")
        if f"\ndef {function_name}" not in backend:
            raise AssertionError(f"{function_name} is missing as a module-level function.")




    # Audit Phases 21-25: public-output verification, CSV import guards,
    # source-scan reuse, reversible quarantine, fast startup diagnostics, and
    # smoke coverage for the final hardening pass.
    audit_phase_21_25_backend_markers = [
        "Missing CSS assets directory",
        "Missing or empty generated images directory",
        "data_js.stat().st_size > 100",
        "published_work_count > 0 and len(html_files) <= 3",
        "CSV file is unusually large (>10MB)",
        "CSV tag is too long (>50 characters)",
        "_WORK_REPOSITORY.reset()  # Full reset is cheaper",
        "# NOTE: 6s TTL. Extended by invalidate_control_panel_caches() after any mutation.",
        "def quarantine_orphaned_assets(paths: list[str], *, dry_run: bool = False)",
        "quarantine-manifest.json",
        "def restore_from_quarantine",
        "guarded_move(source_path, target, detail=\"quarantine orphaned asset\")",
        "asset-quarantine",
        "def startup_preflight_checks(*, fast: bool = True)",
        "qt_backend_version",
        "audit-phase-25",
    ]
    missing_audit_phase_21_25_backend = [marker for marker in audit_phase_21_25_backend_markers if marker not in backend]
    if missing_audit_phase_21_25_backend:
        raise AssertionError(f"Missing audit phase 21-25 backend marker(s): {missing_audit_phase_21_25_backend}")

    release_gate_block = panel.split("    def show_release_gate_summary", 1)[1].split("    def show_public_output_diff", 1)[0]
    for marker in ["portfolio_health_report(force=False", "source_asset_issues(rows=list(health.get(\"source_rows\")", "release_gate_summary("]:
        if marker not in release_gate_block:
            raise AssertionError(f"Release gate summary no longer reuses health/source rows: {marker}")

    smoke_source = (ROOT / "scripts" / "control_panel_smoke_tests.py").read_text(encoding="utf-8")
    smoke_markers = [
        "phase_21_25_backend_probe",
        "series_story_rows does not raise AttributeError",
        "work_lineage_report is read-only",
        "_stable_image_hash handles palette PNG",
        "suggest_series_order handles 100 works quickly",
        "startup_preflight_checks defaults to fast source scan deferral",
    ]
    missing_smoke_markers = [marker for marker in smoke_markers if marker not in smoke_source]
    if missing_smoke_markers:
        raise AssertionError(f"Missing phase 21-25 smoke marker(s): {missing_smoke_markers}")

    print("Control-panel regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
