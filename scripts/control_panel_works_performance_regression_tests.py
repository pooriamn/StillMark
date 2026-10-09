#!/usr/bin/env python3
from __future__ import annotations

"""Works-tab performance regression markers plus backend fixture checks."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
IGNORE_NAMES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "deploy", "dist", "dist", ".stillmrk-build", ".quietlens-build"}


def _enable_venv_site_packages() -> None:
    base = Path(sys.executable).resolve().parents[1]
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        base / "lib" / version / "site-packages",
        base / "lib64" / version / "site-packages",
        Path("/usr/local/lib") / version / "site-packages",
        Path("/usr/local/lib") / version / "dist-packages",
        Path("/usr/lib") / version / "site-packages",
        Path("/usr/lib") / version / "dist-packages",
        Path("/usr/lib/python3/dist-packages"),
    ]
    for candidate in candidates:
        text = str(candidate)
        if candidate.exists() and text not in sys.path:
            sys.path.append(text)


def _hash_website_tree(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        parts = set(rel.split("/"))
        if "scripts" in parts or parts & IGNORE_NAMES:
            continue
        if rel.startswith(("CONTROL_PANEL", "PHASE_", "GUI_")):
            continue
        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _copy_fixture() -> Path:
    temp_root = Path(tempfile.mkdtemp(prefix="stillmark-works-perf-"))
    fixture = temp_root / "site"
    def ignore(_: str, names: list[str]) -> set[str]:
        return {name for name in names if name in IGNORE_NAMES or name.endswith((".tar.gz", ".zip"))}
    shutil.copytree(ROOT, fixture, ignore=ignore)
    return fixture


def _first_work(qb: Any) -> dict[str, Any]:
    for payload in qb.load_work_entries():
        if str(payload.get("id") or "").strip() and str(payload.get("series") or "").strip():
            return dict(payload)
    raise RuntimeError("No fixture work with both id and series.")


def _make_fixture_image(path: Path) -> None:
    try:
        from PIL import Image
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (180, 120), (116, 116, 116))
        image.save(path, "JPEG", quality=88)
    except Exception:
        path.write_bytes(bytes.fromhex("ffd8ffe000104a46494600010101006000600000ffdb004300" + "08" * 64 + "ffc00011080001000103012200021101031101ffc40014000100000000000000000000000000000000000000ffda0008010100003f00d2cf20ffd9"))


def _inside_fixture() -> dict[str, Any]:
    _enable_venv_site_packages()
    sys.path.insert(0, str(SCRIPTS))
    import qt_backend as qb  # type: ignore
    tests: list[dict[str, Any]] = []
    def record(name: str, ok: bool, detail: str = "") -> None:
        tests.append({"name": name, "ok": bool(ok), "detail": detail})

    control_source = (SCRIPTS / "control_panel.py").read_text(encoding="utf-8")
    backend_source = (SCRIPTS / "qt_backend.py").read_text(encoding="utf-8")
    models_source = (SCRIPTS / "control_panel_models.py").read_text(encoding="utf-8")
    build_source = (ROOT / "build_site.py").read_text(encoding="utf-8")
    record("normal work save uses local row patch", "work save local patch" in control_source and "_patch_work_tree_row_after_save" in control_source)
    record("work form payload avoids disk read dirty checks", "_current_work_image_block" in control_source and '"image": dict(getattr(self, "_current_work_image_block", {}) or {})' in control_source)
    record("dependent tabs marked dirty", "_mark_work_save_dependents_dirty" in control_source and "self._mark_dirty(scopes)" in control_source)
    save_block = control_source.split("    def save_current_work(self) -> None:", 1)[1].split("    def reload_current_work", 1)[0]
    record("old global work-save refresh removed", "refresh_all_context" not in save_block and "_patch_work_tree_row_after_save" in save_block)
    record("works list uses fast backend query", "load_works_filtered(" in control_source and "fast=True" in control_source)
    record("backend has mtime work repository cache", "class WorkRepository" in backend_source and "invalidate_work_cache" in backend_source)
    record("works list avoids source scan in fast mode", "fast_work_completeness_score" in backend_source and "No source-tree scan" in backend_source)
    record("work validation is debounced", "schedule_work_validation" in control_source and "_work_validation_timer" in control_source)
    record("work preview pixmaps are cached", "_work_preview_pixmap_cache" in control_source and "_scaled_work_preview_pixmap" in control_source)
    record("dist data.js is written by the build and integrity-checked", "write_dist_file('assets/js/data.js'" in build_source and "Build integrity failed" in build_source)
    record("preview verification enforces live data.js path", 'PUBLIC_UPLOAD_DIR / "assets" / "js" / "data.js"' in backend_source and 'Build output integrity failed' in backend_source)

    record("works list uses QTableView model path", "QTableView" in control_source and "self.work_table.setModel(self._works_model)" in control_source and "_works_model_view_enabled" in control_source)
    record("legacy tree remains fallback only", "self.work_tree.hide()" in control_source and "_using_work_model_view" in control_source)
    record("model supports row patching without reset", "def replace_or_insert_row" in models_source and "def update_row" in models_source and "dataChanged.emit" in models_source)
    record("model supports table sorting", "def sort(self, column" in models_source and "layoutAboutToBeChanged" in models_source)
    record("model quick edit path exists", "quick_edit_work_model_cell" in control_source and "_quick_edit_work_cell" in control_source)
    record("phase4 has manifest-backed fast preview lookup", "def fast_preview_path_for_work" in backend_source and "_cached_fast_preview_paths_by_work_id" in backend_source)
    record("phase4 thumbnails use debounced visible loader", "_work_thumbnail_timer" in control_source and "_schedule_visible_thumbnail_load" in control_source and "fast_preview_path_for_work(payload)" in control_source)
    record("phase4 asset health is deferred off the main refresh", "_work_asset_health_timer" in control_source and "_start_visible_work_asset_health_check" in control_source and "works deferred asset health" in control_source)
    record("phase4 visible rows patched after asset health", "_apply_work_asset_health_rows" in control_source and "_works_model.update_row(work_id, payload)" in control_source)

    qb.invalidate_work_cache()
    fast_rows = qb.load_works_filtered(fast=True)
    record("fixture fast filtered rows include row annotations", bool(fast_rows) and all("_completeness_score" in row and "_source_status" in row for row in fast_rows[:5]), f"rows={len(fast_rows)}")

    original = _first_work(qb)
    work_id = str(original["id"]).strip()
    before = qb.load_work_payload(work_id)
    edited = dict(before)
    edited["title"] = f"{before.get('title') or work_id} Fixture Metadata Edit"
    edited["caption"] = (str(before.get("caption") or "") + "\nFixture metadata-only edit.").strip()
    save_result = qb.save_work_from_payload(work_id, edited)
    after = qb.load_work_payload(work_id)
    record("fixture metadata-only save keeps same id", save_result.get("work_id") == work_id and after and after.get("title") == edited["title"], json.dumps(save_result, default=str)[:500])

    new_id = f"{work_id}-works-perf-fixture"
    existing_ids = {str(row.get("id") or "") for row in qb.load_work_entries()}
    suffix = 2
    while new_id in existing_ids:
        new_id = f"{work_id}-works-perf-fixture-{suffix}"
        suffix += 1
    first_image = ROOT / "_works_perf_fixture_source.jpg"
    _make_fixture_image(first_image)
    qb.replace_work_image(work_id, first_image)
    renamed = dict(qb.load_work_payload(work_id) or edited)
    renamed["id"] = new_id
    rename_result = qb.save_work_from_payload(work_id, renamed)
    stale_refs = qb.scan_stale_references(work_id, new_id, include_runtime=False)
    record("fixture rename updates YAML and exact refs", rename_result.get("work_id") == new_id and qb.load_work_payload(new_id) and not qb.work_file_for_id(work_id).exists() and not stale_refs, json.dumps({"rename": rename_result, "stale": stale_refs}, default=str)[:700])

    second_image = ROOT / "_works_perf_fixture_replacement.jpg"
    _make_fixture_image(second_image)
    replace_result = qb.replace_work_image(new_id, second_image)
    replaced_payload = qb.load_work_payload(new_id) or {}
    master = str((replaced_payload.get("image") or {}).get("master") or "")
    record("fixture replace image verifies current master", master.startswith(new_id) and not (replace_result.get("verification") or {}).get("errors"), json.dumps(replace_result, default=str)[:700])

    remove_result = qb.safe_remove_work(new_id, archive_only=False, remove_assets=True, force=True)
    record("fixture cleanup removes renamed work", not qb.load_work_payload(new_id) and not qb.work_file_for_id(new_id).exists() and not remove_result.get("remaining_references"), json.dumps(remove_result, default=str)[:700])
    return {"ok": all(row["ok"] for row in tests), "tests": tests, "root": str(ROOT)}


def main() -> int:
    if "--inside-fixture" in sys.argv:
        print(json.dumps(_inside_fixture(), sort_keys=True))
        return 0
    before_hash = _hash_website_tree(ROOT)
    fixture = _copy_fixture()
    try:
        return _run_fixture(fixture, before_hash)
    finally:
        # The fixture is a full copy of the project (~450 MB); never leave it behind.
        shutil.rmtree(fixture.parent, ignore_errors=True)


def _run_fixture(fixture: Path, before_hash: dict[str, str]) -> int:
    cmd = [sys.executable, "-S", "scripts/control_panel_works_performance_regression_tests.py", "--inside-fixture"]
    env = dict(os.environ, PYTHONSAFEPATH="1", PYTHONNOUSERSITE="1")
    completed = subprocess.run(cmd, cwd=fixture, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180, env=env)
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        result = json.loads(lines[-1]) if lines else {"ok": False, "error": completed.stdout}
    except Exception:
        result = {"ok": False, "error": completed.stdout[-4000:]}
    result["subprocess_returncode"] = completed.returncode
    after_hash = _hash_website_tree(ROOT)
    result["website_content_ui_unchanged"] = before_hash == after_hash
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") and result.get("website_content_ui_unchanged") and completed.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
