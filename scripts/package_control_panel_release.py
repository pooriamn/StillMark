from __future__ import annotations

"""Package a verified Stillmark control-panel release.

Default output is a full clean project package with website UI/content preserved
but local runtime bloat excluded. Use --patch-only for a control-panel patch.
"""

import argparse
import json
import subprocess
import hashlib
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from control_panel_release_gate import run_final_release_gate, verify_zip_integrity

from control_panel_scope_guard import (
    CORRUPTED_FILENAME_MARKERS,
    assert_no_protected_changes,
    is_control_panel_path,
    is_package_hygiene_excluded,
    is_protected_path,
    is_runtime_path,
    protected_file_snapshot,
    scope_summary,
    write_scope_report,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / ".stillmrk-build" / "control-panel-release-packages"
SKIP_DIR_NAMES = {"__pycache__", ".git", ".venv", "node_modules", "control-panel-release-packages"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".before_layout2", ".bak", ".orig"}
RUNTIME_KEEP_EXACT = {
    ".stillmrk-build/meta/control-panel-scope-report.json",
    ".stillmrk-build/meta/control-panel-smoke-report.json",
}

PATCH_INCLUDE_EXACT = {
    "CONTROL_PANEL_SCOPE.md",
    "RUN_QT_CONTROL_PANEL.txt",
    "requirements-qt.txt",
    "launch_control_panel.bat",
    "launch_control_panel.sh",
    "CONTROL_PANEL_CHANGELOG.md",
}
PATCH_INCLUDE_PREFIXES = (
    "scripts/control_panel",
    "scripts/qt_backend.py",
    "scripts/services/",
    "scripts/_legacy_tk/",
    "scripts/package_control_panel_release.py",
    "scripts/verify_control_panel_package.py",
    "scripts/control_panel_scope_guard.py",
    "scripts/control_panel_smoke_tests.py",
    "scripts/control_panel_error_policy.py",
    "scripts/control_panel_io.py",
)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def should_skip(path: Path) -> bool:
    if not path.is_file():
        return True
    item = rel(path)
    parts = set(path.relative_to(ROOT).parts)
    if parts & SKIP_DIR_NAMES:
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    if item in {"CONTROL_PANEL_RELEASE_MANIFEST.json", "CONTROL_PANEL_RELEASE_MANIFEST.txt"}:
        return True
    if is_package_hygiene_excluded(item):
        return True
    if is_runtime_path(item) and item not in RUNTIME_KEEP_EXACT:
        return True
    return False


def should_include_patch(path: Path) -> bool:
    item = rel(path)
    if should_skip(path) or is_protected_path(item):
        return False
    return item in PATCH_INCLUDE_EXACT or any(item.startswith(prefix) for prefix in PATCH_INCLUDE_PREFIXES) or is_control_panel_path(item)


def should_include_full_project(path: Path, target: Path) -> bool:
    if path == target or should_skip(path):
        return False
    return True


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
    return {rel(path): sha256_file(path) for path in CRITICAL_HASH_FILES if path.exists()}


def compile_source(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    compile(source, str(path), "exec")


def run_gate(*, gui_smoke: bool = False) -> None:
    report = run_final_release_gate(gui_smoke=gui_smoke, write_report=True)
    if not report.get("ok"):
        raise SystemExit("Final control-panel release gate failed; see .stillmrk-build/meta/control-panel-final-release-gate.json")


def write_manifest(archive: zipfile.ZipFile, *, stamp: str, package_type: str, members: list[str], before_hashes: dict[str, str]) -> None:
    summary = scope_summary()
    manifest = {
        "created_utc": stamp,
        "package_type": package_type,
        "gate": "passed",
        "member_count": len(members),
        "protected_file_count": len(before_hashes),
        "protected_digest": summary.get("protected_digest"),
        "critical_file_hashes": critical_file_hashes(),
        "active_tk_files": summary.get("active_tk_files", []),
        "hygiene_policy": {
            "excluded_directories": sorted(SKIP_DIR_NAMES),
            "excluded_suffixes": sorted(SKIP_SUFFIXES),
            "excluded_filename_markers": list(CORRUPTED_FILENAME_MARKERS),
            "runtime_policy": "exclude generated .stillmrk-build/.quietlens-build logs, backups, caches, and local state",
        },
        "members": members,
    }
    archive.writestr("CONTROL_PANEL_RELEASE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    archive.writestr(
        "CONTROL_PANEL_RELEASE_MANIFEST.txt",
        "\n".join([
            f"Created UTC: {stamp}",
            f"Package type: {package_type}",
            "Gate: passed",
            f"Members: {len(members)}",
            f"Protected public/content files tracked: {len(before_hashes)}",
            f"Protected digest: {summary.get('protected_digest')}",
            f"Active Tk files: {len(summary.get('active_tk_files', []))}",
            "Excluded: .venv, __pycache__, generated build caches/logs/backups, corrupted legacy filename artifacts.",
            "Website UI/content files are included only in full-clean-project packages and are hash-protected during packaging.",
            "",
        ]) + "\n",
    )


def create_zip(*, patch_only: bool = False) -> Path:
    before_hashes = protected_file_snapshot()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_scope_report(ROOT / ".stillmrk-build" / "meta" / "control-panel-scope-report.json", before=before_hashes)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    package_type = "control-panel-patch" if patch_only else "full-clean-project"
    target = OUT_DIR / f"stillmark-{package_type}-{stamp}.zip"
    members: list[str] = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            include = should_include_patch(path) if patch_only else should_include_full_project(path, target)
            if not include:
                continue
            item = rel(path)
            archive.write(path, item)
            members.append(item)
        write_manifest(archive, stamp=stamp, package_type=package_type, members=members, before_hashes=before_hashes)
    assert_no_protected_changes(before_hashes)
    integrity = verify_zip_integrity(target)
    if not integrity.get("ok"):
        raise SystemExit(f"ZIP integrity failed: {integrity}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Stillmark control-panel release package.")
    parser.add_argument("--patch-only", action="store_true", help="Create a control-panel-only patch instead of a full clean project package.")
    parser.add_argument("--gui-smoke", action="store_true", help="Also launch the Qt GUI in offscreen smoke-test mode during the gate.")
    args = parser.parse_args()
    before_hashes = protected_file_snapshot()
    run_gate(gui_smoke=args.gui_smoke)
    assert_no_protected_changes(before_hashes)
    target = create_zip(patch_only=args.patch_only)
    print(target.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
