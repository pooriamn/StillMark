from __future__ import annotations

"""Final release gate for control-panel packages."""

import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from control_panel_scope_guard import package_hygiene_issues, protected_file_snapshot, assert_no_protected_changes, scope_summary

ROOT = Path(__file__).resolve().parents[1]
META_DIR = ROOT / ".stillmrk-build" / "meta"
REPORT_PATH = META_DIR / "control-panel-final-release-gate.json"
CHECKLIST_PATH = ROOT / "CONTROL_PANEL_RELEASE_CHECKLIST.md"
KNOWN_ISSUES_PATH = ROOT / "CONTROL_PANEL_KNOWN_ISSUES.md"
CHANGELOG_PATH = ROOT / "CONTROL_PANEL_CHANGELOG.md"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _python_command(*args: str) -> list[str]:
    command = [sys.executable]
    if getattr(sys.flags, "no_site", 0):
        command.append("-S")
    command.extend(args)
    return command


def _run(command: list[str], *, timeout: int = 120) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=env)
    return {"command": command, "returncode": completed.returncode, "ok": completed.returncode == 0, "output_tail": completed.stdout[-4000:]}


def _remove_generated_bytecode(root: Path = ROOT) -> list[str]:
    removed: list[str] = []
    for cache_dir in sorted(root.rglob("__pycache__")):
        if cache_dir.is_dir():
            removed.append(cache_dir.relative_to(root).as_posix())
            shutil.rmtree(cache_dir, ignore_errors=True)
    for path in sorted(root.rglob("*.py[co]")):
        if path.is_file():
            removed.append(path.relative_to(root).as_posix())
            try:
                path.unlink()
            except OSError:
                pass
    return removed


def ensure_release_docs() -> None:
    if not CHECKLIST_PATH.exists():
        CHECKLIST_PATH.write_text(
            "# Control Panel Release Checklist\n\n"
            "- [ ] Syntax/source verification passed.\n"
            "- [ ] Non-GUI smoke tests passed.\n"
            "- [ ] Behavior tests passed.\n"
            "- [ ] Phase 20-25 regression tests passed.\n"
            "- [ ] Works gallery card stability regression test passed.\n"
            "- [ ] Protected website UI/content hash comparison passed.\n"
            "- [ ] Package hygiene check passed.\n"
            "- [ ] ZIP integrity check passed.\n"
            "- [ ] Known issues reviewed before release.\n",
            encoding="utf-8",
        )
    if not KNOWN_ISSUES_PATH.exists():
        KNOWN_ISSUES_PATH.write_text(
            "# Control Panel Known Issues\n\n"
            "- Full live Qt GUI smoke testing requires a local environment with PySide6 installed.\n"
            "- Website UI/content are intentionally excluded from control-panel mutation tests.\n",
            encoding="utf-8",
        )
    if CHANGELOG_PATH.exists():
        text = CHANGELOG_PATH.read_text(encoding="utf-8", errors="replace")
    else:
        text = "# Control Panel Changelog\n"
    marker = "## Phases 20-25"
    if marker not in text:
        text = text.rstrip() + "\n\n## Phases 20-25\n\n- Added launcher doctor checks, data-integrity reports, safer bulk-operation reporting, accessibility audit rows, hard performance budgets, and a final release gate.\n"
        CHANGELOG_PATH.write_text(text + "\n", encoding="utf-8")


def run_final_release_gate(*, gui_smoke: bool = False, write_report: bool = True) -> dict[str, Any]:
    ensure_release_docs()
    before = protected_file_snapshot()
    checks = []
    commands = [
        _python_command("scripts/verify_control_panel_package.py"),
        _python_command("scripts/control_panel_smoke_tests.py"),
        _python_command("scripts/control_panel_behavior_tests.py"),
        [sys.executable, "-m", "pytest", "-q"],
        _python_command("scripts/control_panel_work_gallery_stability_tests.py"),
    ]
    if gui_smoke:
        commands.append(_python_command("scripts/control_panel_smoke_tests.py", "--gui"))
    for command in commands:
        checks.append(_run(command))
    removed_bytecode = _remove_generated_bytecode(ROOT)
    hygiene = package_hygiene_issues()
    severe_hygiene = {key: value for key, value in hygiene.items() if key != "runtime_metadata" and value}
    scope = scope_summary()
    protected_result = assert_no_protected_changes(before).as_dict()
    ok = all(row.get("ok") for row in checks) and not severe_hygiene and bool(protected_result.get("ok"))
    report = {
        "ok": ok,
        "generated_at": utc_stamp(),
        "checks": checks,
        "package_hygiene_issues": hygiene,
        "removed_generated_bytecode": removed_bytecode,
        "severe_package_hygiene_issues": severe_hygiene,
        "protected_scope": protected_result,
        "scope_summary": scope,
        "known_issues_file": KNOWN_ISSUES_PATH.relative_to(ROOT).as_posix(),
        "checklist_file": CHECKLIST_PATH.relative_to(ROOT).as_posix(),
    }
    if write_report:
        META_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def published_only_release_gate(validation_rows: list[dict[str, Any]], published_work_ids: set[str]) -> dict[str, Any]:
    """Summarise content validation while ignoring draft/archived work rows.

    The final package gate still checks every control-panel script. This helper is
    for content publish gates that should not be blocked by archived/draft work
    rows that are not part of the public release.
    """
    filtered: list[dict[str, Any]] = []
    for row in validation_rows:
        if not isinstance(row, dict):
            continue
        scope = str(row.get("scope") or "").strip().lower()
        row_id = str(row.get("id") or row.get("work_id") or "").strip()
        if scope == "work" and row_id and row_id not in published_work_ids:
            continue
        filtered.append(dict(row))
    errors = [row for row in filtered if str(row.get("severity") or "").lower() == "error"]
    warnings = [row for row in filtered if str(row.get("severity") or "").lower() == "warning"]
    return {"blocked": bool(errors), "errors": len(errors), "warnings": len(warnings), "rows": filtered, "published_only": True}


def verify_zip_integrity(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as archive:
        bad = archive.testzip()
        return {"ok": bad is None, "bad_member": bad, "member_count": len(archive.namelist())}


if __name__ == "__main__":
    payload = run_final_release_gate()
    print(json.dumps(payload, indent=2, sort_keys=True))
    raise SystemExit(0 if payload.get("ok") else 1)
