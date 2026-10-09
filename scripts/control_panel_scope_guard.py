from __future__ import annotations

"""Scope and package hygiene guard for Stillmark control-panel work.

This module is deliberately standard-library only. It protects the website UI
and content from accidental control-panel-only edits, and it gives release
packages a repeatable, auditable boundary.
"""

import argparse
import fnmatch
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
PROTECTED_SNAPSHOT_NAME = "protected-scope-snapshot.json"
CORRUPTED_FILENAME_MARKERS: tuple[str, ...] = (
    "Pooria#U2019s MacBook Pro",
    "Pooria’s MacBook Pro",
    "Pooria's MacBook Pro",
)

EDITABLE_PATH_PREFIXES: tuple[str, ...] = (
    "scripts/control_panel.py",
    "scripts/qt_backend.py",
    "scripts/control_panel_",
    "scripts/control_panel_tabs/",
    "scripts/services/",
    "scripts/_legacy_tk/",
    "scripts/package_control_panel_release.py",
    "scripts/verify_control_panel_package.py",
    "scripts/control_panel_scope_guard.py",
    "scripts/control_panel_smoke_tests.py",
    "scripts/control_panel_error_policy.py",
    "scripts/control_panel_io.py",
    "requirements-qt.txt",
    "launch_control_panel.bat",
    "launch_control_panel.sh",
    "CONTROL_PANEL_SCOPE.md",
    "CONTROL_PANEL_CHANGELOG.md",
)

PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    "content/",
    "public_upload/",
    "assets/css/",
    "assets/js/",
    "assets/icons/",
    "assets/documents/",
)

PROTECTED_EXACT_FILES: frozenset[str] = frozenset({
    "index.html",
    "about.html",
    "portfolio.html",
    "series.html",
    "contact.html",
    "styles.css",
    "app.js",
    "data.js",
    "robots.txt",
    "sitemap.xml",
    "site.webmanifest",
})

RUNTIME_PATH_PREFIXES: tuple[str, ...] = (
    ".stillmrk-build/",
    ".quietlens-build/",
)

IGNORED_DIR_NAMES: frozenset[str] = frozenset({
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "control-panel-release-packages",
})

PACKAGE_EXCLUDE_GLOBS: tuple[str, ...] = (
    "*.pyc",
    "*.pyo",
    "*.bak",
    "*.orig",
    "*.before_layout2",
    ".DS_Store",
)

@dataclass(frozen=True)
class ScopeCheckResult:
    changed: tuple[str, ...]
    missing: tuple[str, ...]
    added: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.changed and not self.missing and not self.added

    def as_dict(self) -> dict[str, list[str] | bool]:
        return {
            "ok": self.ok,
            "changed": list(self.changed),
            "missing": list(self.missing),
            "added": list(self.added),
        }


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def normalize_rel(path: Path | str) -> str:
    value = path if isinstance(path, str) else _rel(path)
    return str(value).replace("\\", "/").lstrip("./")


def is_ignored(path: Path) -> bool:
    try:
        parts = path.relative_to(ROOT).parts
    except ValueError:
        return True
    return bool(set(parts) & set(IGNORED_DIR_NAMES))


def has_corrupted_filename_marker(path: Path | str) -> bool:
    rel = normalize_rel(path)
    return any(marker in rel for marker in CORRUPTED_FILENAME_MARKERS)


def is_runtime_path(path: Path | str) -> bool:
    rel = normalize_rel(path)
    return any(rel.startswith(prefix) for prefix in RUNTIME_PATH_PREFIXES)


def is_protected_path(path: Path | str) -> bool:
    rel = normalize_rel(path)
    return rel in PROTECTED_EXACT_FILES or any(rel.startswith(prefix) for prefix in PROTECTED_PATH_PREFIXES)


def is_control_panel_path(path: Path | str) -> bool:
    rel = normalize_rel(path)
    return any(rel == prefix or rel.startswith(prefix) for prefix in EDITABLE_PATH_PREFIXES)


def is_package_hygiene_excluded(path: Path | str) -> bool:
    rel = normalize_rel(path)
    name = Path(rel).name
    if has_corrupted_filename_marker(rel):
        return True
    if any(fnmatch.fnmatch(name, pattern) for pattern in PACKAGE_EXCLUDE_GLOBS):
        return True
    return False


def iter_project_files(*, include_protected_only: bool = False) -> Iterable[Path]:
    """Yield project files with explicit directory pruning.

    ``Path.rglob`` is convenient, but generated runtime/release folders can make
    scope checks slower than necessary. ``os.walk`` lets us prune ignored
    directories before descending, keeping protected-file hash checks fast and
    deterministic.
    """
    for dirpath, dirnames, filenames in os.walk(ROOT):
        current = Path(dirpath)
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_DIR_NAMES)
        if include_protected_only:
            pruned: list[str] = []
            for name in dirnames:
                rel_dir = normalize_rel(current / name)
                if (
                    rel_dir in {"content", "public_upload", "assets", "assets/css", "assets/js", "assets/icons", "assets/documents"}
                    or rel_dir.startswith("content/")
                    or rel_dir.startswith("public_upload/")
                    or rel_dir.startswith("assets/css/")
                    or rel_dir.startswith("assets/js/")
                    or rel_dir.startswith("assets/icons/")
                    or rel_dir.startswith("assets/documents/")
                ):
                    pruned.append(name)
            dirnames[:] = pruned
        for name in sorted(filenames):
            path = current / name
            if not path.is_file() or is_ignored(path):
                continue
            if include_protected_only and not is_protected_path(path):
                continue
            yield path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_file_snapshot() -> dict[str, str]:
    return {_rel(path): sha256_file(path) for path in iter_project_files(include_protected_only=True)}


def compare_snapshots(before: dict[str, str], after: dict[str, str] | None = None) -> ScopeCheckResult:
    after = protected_file_snapshot() if after is None else after
    before_keys = set(before)
    after_keys = set(after)
    changed = sorted(rel for rel in before_keys & after_keys if before[rel] != after[rel])
    missing = sorted(before_keys - after_keys)
    added = sorted(after_keys - before_keys)
    return ScopeCheckResult(tuple(changed), tuple(missing), tuple(added))


def assert_no_protected_changes(before: dict[str, str]) -> ScopeCheckResult:
    result = compare_snapshots(before)
    if not result.ok:
        details = "; ".join(
            part for part in [
                f"changed={list(result.changed)}" if result.changed else "",
                f"missing={list(result.missing)}" if result.missing else "",
                f"added={list(result.added)}" if result.added else "",
            ] if part
        )
        raise RuntimeError(f"Protected website/content files changed during a control-panel-only operation: {details}")
    return result


@contextmanager
def protected_scope(label: str = "control-panel-operation"):
    """Context manager used by tests and release tooling around control-panel work."""
    before = protected_file_snapshot()
    try:
        yield before
    finally:
        assert_no_protected_changes(before)


def assert_write_allowed(path: Path | str, *, operation: str = "write") -> None:
    """Fail fast if a control-panel-only operation tries to write website UI/content."""
    rel = normalize_rel(path if isinstance(path, str) else Path(path))
    if is_protected_path(rel):
        raise PermissionError(f"Blocked {operation}: protected website/content path is outside control-panel scope: {rel}")


def find_corrupted_filename_artifacts() -> list[str]:
    rows: list[str] = []
    for path in iter_project_files():
        if has_corrupted_filename_marker(path):
            rows.append(_rel(path))
    return sorted(rows)


def package_hygiene_issues() -> dict[str, list[str]]:
    issues: dict[str, list[str]] = {"virtualenv": [], "corrupted_filenames": [], "bytecode_or_backup": [], "runtime_metadata": []}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        current = Path(dirpath)
        dirnames[:] = sorted(name for name in dirnames if name not in {".git", "node_modules", "control-panel-release-packages"})
        for name in sorted(filenames):
            path = current / name
            if not path.is_file():
                continue
            rel = _rel(path)
            parts = set(path.relative_to(ROOT).parts)
            if ".venv" in parts:
                issues["virtualenv"].append(rel)
            if has_corrupted_filename_marker(rel):
                issues["corrupted_filenames"].append(rel)
            if any(fnmatch.fnmatch(path.name, pattern) for pattern in PACKAGE_EXCLUDE_GLOBS):
                issues["bytecode_or_backup"].append(rel)
            if is_runtime_path(rel) and not rel.startswith(".stillmrk-build/control-panel-release-packages/"):
                issues["runtime_metadata"].append(rel)
    return {key: value for key, value in issues.items() if value}


def scope_summary() -> dict[str, object]:
    protected = protected_file_snapshot()
    active_tk_files = []
    scripts_dir = ROOT / "scripts"
    if scripts_dir.exists():
        for path in sorted(scripts_dir.glob("control_panel_*.py")):
            try:
                source = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            legacy_import = "import " + "tkinter"
            legacy_from = "from " + "tkinter"
            if legacy_import in source or legacy_from in source:
                active_tk_files.append(_rel(path))
    digest = hashlib.sha256("\n".join(f"{k}:{v}" for k, v in sorted(protected.items())).encode("utf-8")).hexdigest()
    hygiene = package_hygiene_issues()
    return {
        "root": str(ROOT),
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "protected_file_count": len(protected),
        "protected_digest": digest,
        "active_tk_files": active_tk_files,
        "hygiene_issue_counts": {key: len(value) for key, value in hygiene.items()},
        "corrupted_filename_artifacts": find_corrupted_filename_artifacts(),
        "editable_prefixes": list(EDITABLE_PATH_PREFIXES),
        "protected_prefixes": list(PROTECTED_PATH_PREFIXES),
        "protected_exact_files": sorted(PROTECTED_EXACT_FILES),
    }


def write_scope_report(path: Path | str, *, before: dict[str, str] | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    snapshot = before or protected_file_snapshot()
    result = compare_snapshots(snapshot)
    payload = {
        "summary": scope_summary(),
        "protected_check": result.as_dict(),
        "protected_files": sorted(snapshot),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Stillmark control-panel scope boundaries and package hygiene.")
    parser.add_argument("--json", action="store_true", help="Print a JSON summary.")
    parser.add_argument("--snapshot", type=Path, help="Write protected-file hash snapshot to this path.")
    parser.add_argument("--verify", type=Path, help="Verify current protected files against a prior snapshot JSON file.")
    parser.add_argument("--report", type=Path, help="Write a scope report JSON file.")
    parser.add_argument("--fail-on-hygiene", action="store_true", help="Return failure when package-hygiene issues are present.")
    args = parser.parse_args()

    if args.snapshot:
        snapshot = protected_file_snapshot()
        args.snapshot.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote protected snapshot: {args.snapshot}")
        return 0

    if args.verify:
        before = json.loads(args.verify.read_text(encoding="utf-8"))
        result = compare_snapshots(before)
        if args.json:
            print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        elif result.ok:
            print("Protected website/content files unchanged.")
        else:
            print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0 if result.ok else 1

    if args.report:
        write_scope_report(args.report)
        print(f"Wrote scope report: {args.report}")
        return 0

    summary = scope_summary()
    hygiene = package_hygiene_issues()
    if args.json:
        print(json.dumps({"summary": summary, "hygiene": hygiene}, indent=2, sort_keys=True))
    else:
        print(f"Protected files: {summary['protected_file_count']}")
        print(f"Protected digest: {summary['protected_digest']}")
        if summary["active_tk_files"]:
            print("Active Tkinter files detected:")
            for item in summary["active_tk_files"]:
                print(f"- {item}")
            return 1
        if hygiene:
            print("Package hygiene findings:")
            for key, rows in hygiene.items():
                print(f"- {key}: {len(rows)}")
        print("Control-panel scope guard passed.")
    if args.fail_on_hygiene and hygiene:
        return 1
    return 0


if __name__ == "__main__":
    code = main()
    import sys as _sys
    _sys.stdout.flush()
    _sys.stderr.flush()
    os._exit(int(code))
