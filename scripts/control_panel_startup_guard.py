from __future__ import annotations

"""Cheap startup guard for the Stillmark Qt control panel.

Runs before heavy UI/data work. Keep this module free of PySide imports so it can
be verified in headless environments and used by launcher/doctor checks.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - dependency row reports this later
    yaml = None  # type: ignore[assignment]


REQUIRED_FOLDERS = [
    ("scripts folder", "scripts"),
    ("content folder", "content"),
    ("works folder", "content/works"),
    ("series folder", "content/series"),
    ("pages folder", "content/pages"),
]
REQUIRED_FILES = [
    ("control panel script", "scripts/control_panel.py"),
    ("backend script", "scripts/qt_backend.py"),
    ("Qt requirements", "requirements-qt.txt"),
    ("site metadata", "content/site.yaml"),
]


def _row(status: str, check: str, detail: str) -> dict[str, str]:
    return {"status": status, "check": check, "detail": detail}


def _brace_balance(text: str) -> tuple[bool, str]:
    balance = 0
    line_no = 1
    for index, char in enumerate(text):
        if char == "\n":
            line_no += 1
        elif char == "{":
            balance += 1
        elif char == "}":
            balance -= 1
            if balance < 0:
                return False, f"Unmatched closing brace near line {line_no}, offset {index}."
    if balance:
        return False, f"Unmatched opening brace count: {balance}."
    return True, "QSS brace balance is valid."


def _quarantine_state_file(path: Path, reason: str) -> dict[str, str]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.stem}.quarantined-{stamp}{path.suffix}")
    try:
        os.replace(path, backup)
        return _row("warning", "UI state", f"Reset corrupt state file ({reason}). Backup: {backup.name}")
    except OSError as exc:
        return _row("error", "UI state", f"State file is corrupt and could not be quarantined: {exc}")


def _invalid_yaml_filenames(root_path: Path) -> list[str]:
    invalid: list[str] = []
    for rel in ("content/works", "content/series"):
        folder = root_path / rel
        if not folder.exists():
            continue
        for path in sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]):
            if "#" in path.name or " " in path.name or "Pooria" in path.name:
                try:
                    invalid.append(path.relative_to(root_path).as_posix())
                except ValueError:
                    invalid.append(str(path))
    return invalid


def _fallback_yaml_mapping(text: str) -> dict[str, Any]:
    """Tiny fallback for startup preflight when PyYAML is unavailable.

    It understands the simple top-level ``key: value`` pairs needed for ID
    uniqueness checks. Full schema validation still reports dependency status.
    """
    payload: dict[str, Any] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or key.startswith("-"):
            continue
        value = value.strip().strip("'\"")
        payload[key] = value
    return payload


def _load_yaml_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"{exc.__class__.__name__}: {exc}"
    if yaml is None:
        return _fallback_yaml_mapping(text), None
    try:
        payload = yaml.safe_load(text)
    except Exception as exc:
        return None, f"{exc.__class__.__name__}: {exc}"
    if payload is None:
        return {}, None
    if not isinstance(payload, dict):
        return None, "top-level YAML value is not an object"
    return payload, None


def _scan_yaml_integrity(root_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    problems: list[str] = []
    checked = 0
    for folder_rel in ("content/works", "content/series", "content/pages"):
        folder = root_path / folder_rel
        if not folder.exists():
            continue
        for path in sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]):
            checked += 1
            payload, error = _load_yaml_file(path)
            if error:
                problems.append(f"{path.relative_to(root_path).as_posix()}: {error}")
            elif folder_rel == "content/works" and not str((payload or {}).get("id") or "").strip():
                problems.append(f"{path.relative_to(root_path).as_posix()}: missing work id")
    if problems:
        sample = "; ".join(problems[:6])
        suffix = f"; +{len(problems) - 6} more" if len(problems) > 6 else ""
        rows.append(_row("error", "YAML integrity", f"{sample}{suffix}"))
    else:
        rows.append(_row("ok", "YAML integrity", f"{checked} YAML file(s) parsed successfully."))
    return rows


def _duplicate_work_id_rows(root_path: Path) -> list[dict[str, str]]:
    folder = root_path / "content" / "works"
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    if not folder.exists():
        return [_row("error", "Work ID uniqueness", "content/works is missing.")]
    for path in sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]):
        payload, error = _load_yaml_file(path)
        if error or not isinstance(payload, dict):
            continue
        work_id = str(payload.get("id") or path.stem).strip()
        if not work_id:
            continue
        rel = path.relative_to(root_path).as_posix()
        if work_id in seen:
            duplicates.append(f"Duplicate work id '{work_id}' in {seen[work_id]} and {rel}")
        else:
            seen[work_id] = rel
    if duplicates:
        return [_row("error", "Work ID uniqueness", "; ".join(duplicates[:5]))]
    return [_row("ok", "Work ID uniqueness", f"{len(seen)} unique work ID(s) found.")]



def _duplicate_render_name_rows(root_path: Path) -> list[dict[str, str]]:
    folder = root_path / "content" / "works"
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    if not folder.exists():
        return [_row("error", "Render name uniqueness", "content/works is missing.")]
    for path in sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]):
        payload, error = _load_yaml_file(path)
        if error or not isinstance(payload, dict):
            continue
        work_id = str(payload.get("id") or path.stem).strip()
        image = payload.get("image") if isinstance(payload.get("image"), dict) else {}
        render_name = str(image.get("render_name") or image.get("renderName") or work_id).strip()
        if not render_name:
            continue
        rel = path.relative_to(root_path).as_posix()
        if render_name in seen:
            duplicates.append(f"Duplicate render_name '{render_name}' in {seen[render_name]} and {rel}")
        else:
            seen[render_name] = rel
    if duplicates:
        return [_row("error", "Render name uniqueness", "; ".join(duplicates[:5]))]
    return [_row("ok", "Render name uniqueness", f"{len(seen)} unique render name(s) found.")]


def _dependency_rows() -> list[dict[str, str]]:
    missing: list[str] = []
    versions: list[str] = [f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"]
    try:
        import PIL
        versions.append(f"Pillow {getattr(PIL, '__version__', 'installed')}")
    except Exception as exc:
        missing.append(f"Pillow: {exc}")
    if yaml is None:
        missing.append("PyYAML: not importable")
    else:
        versions.append(f"PyYAML {getattr(yaml, '__version__', 'installed')}")
    try:
        import PySide6
        versions.append(f"PySide6 {getattr(PySide6, '__version__', 'installed')}")
    except Exception as exc:
        # Warning rather than error here because non-GUI verification machines may
        # intentionally lack PySide6. The real launcher still needs it.
        return [_row("warning", "Python dependencies", f"PySide6 unavailable in this environment: {exc}; {'; '.join(versions)}")]
    return [_row("error" if missing else "ok", "Python dependencies", "; ".join(missing) if missing else "; ".join(versions))]


def run_startup_guard(root: Path | str) -> dict[str, Any]:
    root_path = Path(root)
    rows: list[dict[str, str]] = []
    for label, rel in REQUIRED_FOLDERS:
        path = root_path / rel
        rows.append(_row("ok" if path.exists() else "error", label, rel if path.exists() else f"Missing: {rel}"))
    for label, rel in REQUIRED_FILES:
        path = root_path / rel
        rows.append(_row("ok" if path.exists() else "error", label, rel if path.exists() else f"Missing: {rel}"))

    invalid_yaml = _invalid_yaml_filenames(root_path)
    if invalid_yaml:
        sample = ", ".join(invalid_yaml[:6])
        suffix = f"; +{len(invalid_yaml) - 6} more" if len(invalid_yaml) > 6 else ""
        rows.append(_row("error", "YAML filename slug gate", f"Invalid content YAML filename(s) contain #, spaces, or legacy machine markers: {sample}{suffix}. Run scripts/migrate_corrupted_yaml_filenames.py before opening the panel."))
    else:
        rows.append(_row("ok", "YAML filename slug gate", "All work/series YAML filenames are URL-safe."))

    rows.extend(_scan_yaml_integrity(root_path))
    rows.extend(_duplicate_work_id_rows(root_path))
    rows.extend(_duplicate_render_name_rows(root_path))

    qss = root_path / "scripts" / "control_panel_theme.qss"
    if qss.exists():
        try:
            ok, detail = _brace_balance(qss.read_text(encoding="utf-8", errors="replace"))
            rows.append(_row("ok" if ok else "error", "QSS syntax guard", detail))
        except OSError as exc:
            rows.append(_row("error", "QSS syntax guard", str(exc)))
    else:
        rows.append(_row("warning", "QSS syntax guard", "Base QSS file is missing; dynamic fallback theme will be used."))

    state_path = root_path / ".stillmrk-build" / "meta" / "qt-control-panel-state.json"
    if state_path.exists():
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                rows.append(_row("ok", "UI state", "State file is readable."))
            else:
                rows.append(_quarantine_state_file(state_path, "top-level JSON was not an object"))
        except Exception as exc:
            rows.append(_quarantine_state_file(state_path, str(exc)))
    else:
        rows.append(_row("ok", "UI state", "No previous state file yet."))

    meta_dir = root_path / ".stillmrk-build" / "meta"
    try:
        meta_dir.mkdir(parents=True, exist_ok=True)
        probe = meta_dir / ".startup-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        rows.append(_row("ok", "metadata write gate", ".stillmrk-build/meta is writable."))
    except OSError as exc:
        rows.append(_row("error", "metadata write gate", str(exc)))

    rows.extend(_dependency_rows())
    errors = sum(1 for row in rows if row.get("status") == "error")
    warnings = sum(1 for row in rows if row.get("status") == "warning")
    return {"ok": errors == 0, "errors": errors, "warnings": warnings, "rows": rows}
