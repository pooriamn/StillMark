#!/usr/bin/env python3
"""Fixture-based regression gates for STILLMRK control panel phases 14-20.

The tests intentionally run against a temporary copy of the portfolio so the real
website content and website UI are not mutated. They verify behavioral workflows
that marker-only checks miss: work-id rename, image replacement, safe remove,
source preflight blockers, raw editor safety, workbook dry-run preview, and the
lazy-tab/minimum-window UI smoke markers.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _enable_venv_site_packages() -> None:
    base = Path(sys.executable).resolve().parents[1]
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for candidate in (base / "lib" / version / "site-packages", base / "lib64" / version / "site-packages"):
        text = str(candidate)
        if candidate.exists() and text not in sys.path:
            sys.path.append(text)


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
IGNORE_NAMES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "deploy", "dist", "public_upload", ".stillmrk-build", ".quietlens-build",
}


def _hash_public_tree(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith("scripts/") or rel.startswith("CONTROL_PANEL") or "PHASE" in path.name:
            continue
        if any(part in IGNORE_NAMES for part in rel.split("/")):
            continue
        try:
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            pass
    return hashes


def _copy_fixture() -> Path:
    temp_root = Path(tempfile.mkdtemp(prefix="stillmark-cp-p14p20-"))
    fixture = temp_root / "site"

    def ignore(_: str, names: list[str]) -> set[str]:
        return {name for name in names if name in IGNORE_NAMES or name.endswith((".tar.gz", ".zip"))}

    shutil.copytree(ROOT, fixture, ignore=ignore)
    return fixture


def _run_inside_fixture(fixture: Path) -> dict[str, Any]:
    cmd = [sys.executable, "-S", "scripts/control_panel_phase_14_20_regression_tests.py", "--inside-fixture"]
    env = dict(os.environ)
    env["PYTHONSAFEPATH"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    completed = subprocess.run(cmd, cwd=fixture, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, env=env)
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except Exception:
        payload = {"ok": False, "tests": [], "error": completed.stdout}
    payload["subprocess_returncode"] = completed.returncode
    return payload


def _first_work_with_series(qb: Any) -> dict[str, Any]:
    for payload in qb.load_work_entries():
        if str(payload.get("id") or "").strip() and str(payload.get("series") or "").strip():
            return dict(payload)
    raise RuntimeError("Fixture has no work with an id and series; cannot run control-panel workflow tests.")


def _make_fixture_image(path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (160, 96), (128, 128, 128))
    image.save(path, "JPEG", quality=90)


def _inside_fixture() -> dict[str, Any]:
    _enable_venv_site_packages()
    sys.path.insert(0, str(SCRIPTS))
    import qt_backend as qb  # type: ignore

    tests: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str = "", **extra: Any) -> None:
        row = {"name": name, "ok": bool(ok), "detail": detail, **extra}
        tests.append(row)
        print(json.dumps({"progress": name, "ok": bool(ok)}), flush=True)

    # Syntax/AST smoke before any behavior.
    control_panel_source = (SCRIPTS / "control_panel.py").read_text(encoding="utf-8")
    qt_backend_source = (SCRIPTS / "qt_backend.py").read_text(encoding="utf-8")
    ast.parse(control_panel_source, filename="scripts/control_panel.py")
    ast.parse(qt_backend_source, filename="scripts/qt_backend.py")
    smoke_markers = [
        "dashboard_activity_strip",
        "workbook_preview_tree",
        "minimum_window_smoke_test",
        "install_accessibility_shortcuts",
        "Restore last valid",
        "review_authority_yaml_text",
        "preview_workbook_import",
    ]
    missing_markers = [marker for marker in smoke_markers if marker not in (control_panel_source + qt_backend_source)]
    record("UI smoke markers for lazy tabs, dashboard triage, accessibility, and safety", not missing_markers, ", ".join(missing_markers))

    original = _first_work_with_series(qb)
    old_id = str(original["id"]).strip()
    new_id = f"{old_id}-fixture-p14p20"
    suffix = 1
    existing_ids = {str(row.get("id") or "") for row in qb.load_work_entries()}
    while new_id in existing_ids:
        suffix += 1
        new_id = f"{old_id}-fixture-p14p20-{suffix}"

    image_path = ROOT / "_fixture_replace_image.jpg"
    _make_fixture_image(image_path)
    normalize_result = qb.replace_work_image(old_id, image_path)
    record("Fixture setup normalized source image to a small test asset", not normalize_result.get("verification", {}).get("errors"), json.dumps(normalize_result, default=str)[:400])

    refreshed_original = qb.load_work_payload(old_id) or original
    renamed_payload = dict(refreshed_original)
    renamed_payload["id"] = new_id
    rename_result = qb.save_work_from_payload(old_id, renamed_payload)
    renamed_source = qb.source_path_for_work((qb.load_work_payload(new_id) or {}).get("series"), new_id, pipeline=qb.load_pipeline())
    rename_ok = (
        rename_result.get("work_id") == new_id
        and qb.load_work_payload(new_id)
        and not qb.work_file_for_id(old_id).exists()
        and (not renamed_source or Path(renamed_source).exists())
        and not qb.scan_stale_references(old_id, new_id, include_runtime=False)
    )
    record("Fixture rename work ID updates metadata, references, and assets", rename_ok, json.dumps(rename_result, default=str)[:500])

    image_path = ROOT / "_fixture_replace_image_again.jpg"
    _make_fixture_image(image_path)
    replace_result = qb.replace_work_image(new_id, image_path)
    payload_after_replace = qb.load_work_payload(new_id)
    replace_ok = (
        payload_after_replace
        and str((payload_after_replace.get("image") or {}).get("master") or "").startswith(new_id)
        and not replace_result.get("verification", {}).get("errors")
    )
    record("Fixture replace image removes stale originals and verifies no fake presence", replace_ok, json.dumps(replace_result, default=str)[:600])

    # Missing-source build/publish gate. Move the source away and require a blocker.
    pipeline = qb.load_pipeline()
    active_payload = qb.load_work_payload(new_id)
    source_path = qb.source_path_for_work(active_payload.get("series"), new_id, pipeline=pipeline)
    blocker_ok = False
    source_backup = None
    if source_path and Path(source_path).exists():
        source_path = Path(source_path)
        source_backup = source_path.with_suffix(source_path.suffix + ".missing-fixture")
        shutil.move(str(source_path), str(source_backup))
        try:
            try:
                qb.preflight_build_sources(allow_recovery=False, strict=True)
            except Exception:
                pass
            issue_ids = {str(row.get("id") or "") for row in qb.source_asset_issues(use_cache=False)}
            blocker_ok = new_id in issue_ids
        finally:
            if source_backup and source_backup.exists():
                shutil.move(str(source_backup), str(source_path))
    record("Fixture build/publish preflight blocks missing original sources", blocker_ok, f"source={source_path}")

    archive_result = qb.safe_remove_work(new_id, archive_only=True)
    archived = qb.load_work_payload(new_id)
    archive_ok = bool(archived and not archived.get("published") and archived.get("review_status") == "archived")
    record("Fixture archive work unpublishes without fake public presence", archive_ok, json.dumps(archive_result, default=str)[:400])

    remove_result = qb.safe_remove_work(new_id, archive_only=False, remove_assets=True, force=True)
    remove_ok = (
        not qb.load_work_payload(new_id)
        and not qb.work_file_for_id(new_id).exists()
        and not remove_result.get("remaining_references")
    )
    record("Fixture delete/remove work clears metadata, refs, and optional assets", remove_ok, json.dumps(remove_result, default=str)[:600])
    known_after_delete = {str(row.get("id") or "").strip() for row in qb.load_work_entries() if str(row.get("id") or "").strip()}
    bad_series_refs = []
    for series_payload in qb.load_series_entries():
        slug = str(series_payload.get("slug") or "").strip()
        for referenced_id in [str(item).strip() for item in (series_payload.get("work_ids") or []) if str(item).strip()]:
            if referenced_id not in known_after_delete:
                bad_series_refs.append(f"{slug}:{referenced_id}")
    record("Fixture delete leaves no series-to-missing-work references", not bad_series_refs, ", ".join(bad_series_refs[:8]))

    # Page/authority YAML validation and restore APIs should fail safely on invalid raw text.
    page_key = qb.available_page_keys()[0]
    page_review = qb.review_page_yaml_text(page_key, "title: [unterminated")
    page_safety_ok = any(str(row.get("severity")) == "error" and "line" in str(row.get("field")) for row in page_review.get("issues") or [])
    record("Raw page YAML reports field-level parse errors before save", page_safety_ok, json.dumps(page_review.get("issues"), default=str)[:500])

    authority_review = qb.review_authority_yaml_text("site", "name: [unterminated")
    authority_safety_ok = any(str(row.get("severity")) == "error" and "line" in str(row.get("field")) for row in authority_review.get("issues") or [])
    record("Raw authority YAML reports field-level parse errors before save", authority_safety_ok, json.dumps(authority_review.get("issues"), default=str)[:500])

    # Workbook dry-run preview should exist and return a structured response. Use an exported workbook as a no-op fixture.
    workbook_path = qb.export_workbook_bundle()
    preview = qb.preview_workbook_import(workbook_path)
    preview_ok = isinstance(preview.get("changes"), list) and isinstance(preview.get("risk_counts"), dict) and preview.get("dry_run_required") is True
    record("Workbook import is dry-run-first with structured risk preview", preview_ok, json.dumps({k: preview.get(k) for k in ("risk_counts", "affected_files", "dry_run_required")}, default=str))

    ok = all(row["ok"] for row in tests)
    return {"ok": ok, "tests": tests, "root": str(ROOT)}


def main() -> None:
    if "--inside-fixture" in sys.argv:
        payload = _inside_fixture()
        print(json.dumps(payload, sort_keys=True))
        sys.stdout.flush()
        os._exit(0 if payload.get("ok") else 1)

    before = _hash_public_tree(ROOT)
    fixture = _copy_fixture()
    result = _run_inside_fixture(fixture)
    after = _hash_public_tree(ROOT)
    untouched = before == after
    result["website_content_ui_untouched"] = untouched
    result["fixture_path"] = str(fixture)
    result["ok"] = bool(result.get("ok")) and untouched and int(result.get("subprocess_returncode", 1)) == 0
    print(json.dumps(result, indent=2, sort_keys=True))
    sys.stdout.flush()
    os._exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
