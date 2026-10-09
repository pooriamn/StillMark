#!/usr/bin/env python3
from __future__ import annotations

"""One-time cleanup for hostname-corrupted YAML filenames.

This removes/renames files produced by macOS/iCloud conflict suffixes such as
"-Pooria#U2019s MacBook Pro". Only content/works and content/series are touched.
The script uses PyYAML when available and falls back to conservative text-level
id/slug extraction so it can still run during broken-environment recovery.
"""

import difflib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - fallback exists for recovery environments
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
CORRUPT_MARKERS = ("#U2019", "%E2%80%99", "Pooria#U2019s MacBook Pro")
HOST_SUFFIX_RE = re.compile(r"[-\s]+Pooria(?:#U2019|%E2%80%99|’|'|\\u2019)s[-\s]+MacBook[-\s]+Pro$", re.IGNORECASE)
REPORT_DIR = ROOT / ".stillmrk-build" / "meta"
QUARANTINE_ROOT = ROOT / ".stillmrk-build" / "backups" / "corrupted-yaml-filenames"
TRANSACTION_LOG = ROOT / ".stillmrk-build" / "backups" / "transactions.json"


def _slugify(value: str) -> str:
    raw = HOST_SUFFIX_RE.sub("", str(value or "").strip())
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")


def _is_corrupted_name(path: Path) -> bool:
    name = path.name
    return any(marker in name for marker in CORRUPT_MARKERS) or (" " in name and path.parent.name in {"works", "series"})


def _read_payload(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text) or {}
    payload: dict[str, Any] = {}
    for line in text.splitlines():
        match = re.match(r"^(id|slug)\s*:\s*(.*?)\s*$", line)
        if match:
            payload[match.group(1)] = match.group(2).strip().strip('"\'')
    return payload


def _write_payload(path: Path, payload: Any, original_text: str) -> None:
    if yaml is not None:
        path.write_text(yaml.safe_dump(payload if isinstance(payload, dict) else {}, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return
    # Text fallback only needs to update top-level id/slug values.
    text = original_text
    for key in ("id", "slug"):
        if isinstance(payload, dict) and key in payload:
            text = re.sub(rf"^{key}\s*:\s*.*$", f"{key}: {payload[key]}", text, count=1, flags=re.MULTILINE)
    path.write_text(text, encoding="utf-8")


def _clean_stem_from_filename(path: Path) -> str:
    return _slugify(path.stem)


def _target_slug(path: Path, payload: Any) -> str:
    data = payload if isinstance(payload, dict) else {}
    key = "slug" if path.parent.name == "series" else "id"
    return _slugify(str(data.get(key) or "").strip() or _clean_stem_from_filename(path))


def _normalise_for_compare(path: Path) -> str:
    try:
        payload = _read_payload(path)
        if yaml is not None:
            return yaml.safe_dump(payload if payload is not None else {}, sort_keys=True, allow_unicode=True)
    except Exception:
        pass
    return path.read_text(encoding="utf-8", errors="replace")


def _diff_summary(left_path: Path, right_path: Path, *, limit: int = 12) -> list[str]:
    left_lines = _normalise_for_compare(left_path).splitlines()
    right_lines = _normalise_for_compare(right_path).splitlines()
    diff = list(difflib.unified_diff(left_lines, right_lines, fromfile="corrupted", tofile="clean", lineterm=""))
    return diff[:limit]


def _append_transaction(label: str, rows: list[dict[str, Any]]) -> None:
    TRANSACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(TRANSACTION_LOG.read_text(encoding="utf-8")) if TRANSACTION_LOG.exists() else []
        if not isinstance(existing, list):
            existing = []
    except Exception:
        existing = []
    now = datetime.now(timezone.utc).isoformat()
    existing.append({"id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "label": label, "created_at": now, "updated_at": now, "status": "completed", "ops": rows})
    TRANSACTION_LOG.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def migrate_corrupted_yaml_filenames() -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rows: list[dict[str, Any]] = []
    scanned: list[Path] = []
    for folder_name in ("works", "series"):
        folder = ROOT / "content" / folder_name
        if folder.exists():
            scanned.extend(sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]))

    for path in scanned:
        if not _is_corrupted_name(path):
            continue
        source_rel = path.relative_to(ROOT).as_posix()
        try:
            original_text = path.read_text(encoding="utf-8")
            payload = _read_payload(path)
        except Exception as exc:
            rows.append({"type": "migrate-corrupted-yaml", "source": source_rel, "action": "error", "detail": f"Could not read YAML: {exc}"})
            continue
        clean_slug = _target_slug(path, payload)
        if not clean_slug:
            rows.append({"type": "migrate-corrupted-yaml", "source": source_rel, "action": "error", "detail": "No usable id/slug found"})
            continue
        target = path.with_name(f"{clean_slug}{path.suffix}")
        target_rel = target.relative_to(ROOT).as_posix()
        if target.exists() and target.resolve() != path.resolve():
            quarantine_dir = QUARANTINE_ROOT / stamp / path.parent.name
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            quarantine = quarantine_dir / path.name
            diff = _diff_summary(path, target)
            shutil.move(str(path), str(quarantine))
            rows.append({
                "type": "migrate-corrupted-yaml",
                "source": source_rel,
                "target": target_rel,
                "quarantine": quarantine.relative_to(ROOT).as_posix(),
                "action": "discarded-duplicate",
                "same_payload": not diff,
                "diff": diff,
            })
            continue
        if isinstance(payload, dict):
            if path.parent.name == "series":
                payload["slug"] = clean_slug
            else:
                payload["id"] = clean_slug
            _write_payload(path, payload, original_text)
        target.parent.mkdir(parents=True, exist_ok=True)
        path.rename(target)
        rows.append({"type": "migrate-corrupted-yaml", "source": source_rel, "target": target_rel, "action": "renamed"})

    _append_transaction(f"migrate-corrupted-yaml-filenames:{stamp}", rows)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "rows": rows, "count": len(rows)}
    (REPORT_DIR / "corrupted-yaml-filename-migration.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    report = migrate_corrupted_yaml_filenames()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not any(row.get("action") == "error" for row in report.get("rows", [])) else 1


if __name__ == "__main__":
    raise SystemExit(main())
