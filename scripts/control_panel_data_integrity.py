from __future__ import annotations

"""Control-panel data-integrity helpers for Phases 20-25.

These helpers are intentionally backend-safe and do not mutate website UI/content.
They give the control panel a stricter integrity layer around work identifiers,
references, and asset truth before destructive or publish-adjacent operations.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except Exception:  # pragma: no cover - startup doctor reports dependency problems
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content"
WORKS_DIR = CONTENT / "works"
SERIES_DIR = CONTENT / "series"
PAGES_DIR = CONTENT / "pages"
META_DIR = ROOT / ".stillmrk-build" / "meta"

STRICT_WORK_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".avif"}
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IntegrityRow:
    status: str
    check: str
    detail: str
    target: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"status": self.status, "check": self.check, "detail": self.detail, "target": self.target}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_yaml(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is not available")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _safe_read_yaml(path: Path) -> Any:
    try:
        return _read_yaml(path)
    except Exception:
        return None


def _clean(value: Any) -> str:
    return str(value or "").strip()


def iter_work_payloads(root: Path = ROOT) -> Iterable[tuple[Path, dict[str, Any]]]:
    works_dir = root / "content" / "works"
    if not works_dir.exists():
        return
    for path in sorted(works_dir.glob("*.yaml")):
        payload = _safe_read_yaml(path)
        if isinstance(payload, dict):
            yield path, payload


def validate_work_id_slug(value: Any, *, existing_ids: Iterable[str] = (), current_id: str | None = None) -> dict[str, Any]:
    """Validate a work id using strict slug rules before writing files.

    The existing content uses lower-case slugs/UUID-like ids. Allowing spaces,
    slashes, dots, unicode punctuation, or mixed case creates path and URL risks.
    """
    work_id = _clean(value)
    current = _clean(current_id)
    errors: list[str] = []
    warnings: list[str] = []
    if not work_id:
        errors.append("Work ID is required.")
    if work_id != work_id.lower():
        errors.append("Work ID must be lowercase.")
    if not STRICT_WORK_ID_RE.fullmatch(work_id):
        errors.append("Work ID must use only lowercase letters, numbers, and single hyphens between tokens.")
    if "--" in work_id or work_id.startswith("-") or work_id.endswith("-"):
        errors.append("Work ID cannot begin/end with a hyphen or contain repeated hyphens.")
    reserved = {"admin", "assets", "api", "content", "scripts", "public", "portfolio", "series", "contact", "about"}
    if work_id in reserved:
        errors.append(f"Work ID '{work_id}' is reserved for site/control-panel routing.")
    existing = {_clean(item) for item in existing_ids if _clean(item)}
    if work_id and work_id in existing and work_id != current:
        errors.append(f"Work ID '{work_id}' already exists.")
    if len(work_id) > 96:
        warnings.append("Work ID is unusually long; keep it short for URLs and filenames.")
    return {"ok": not errors, "id": work_id, "errors": errors, "warnings": warnings}


def work_id_integrity_rows(root: Path = ROOT) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    for path, payload in iter_work_payloads(root) or []:
        work_id = _clean(payload.get("id") or path.stem)
        result = validate_work_id_slug(work_id)
        status = "ok" if result["ok"] else "error"
        detail = "; ".join(result["errors"] or result["warnings"] or ["safe slug"])
        rows.append(IntegrityRow(status, "Work ID slug", detail, path.relative_to(root).as_posix()).as_dict())
        if work_id in seen:
            rows.append(IntegrityRow("error", "Duplicate work ID", f"Also found in {seen[work_id]}", path.relative_to(root).as_posix()).as_dict())
        seen[work_id] = path.relative_to(root).as_posix()
        if path.stem != work_id:
            rows.append(IntegrityRow("warning", "Filename/id mismatch", f"Filename stem '{path.stem}' differs from id '{work_id}'.", path.relative_to(root).as_posix()).as_dict())
    return rows


def build_reference_index(root: Path = ROOT) -> dict[str, Any]:
    """Build a lightweight index of references to works from series/pages/content text."""
    work_ids = {_clean(payload.get("id") or path.stem) for path, payload in iter_work_payloads(root) or []}
    references: dict[str, list[dict[str, str]]] = {work_id: [] for work_id in sorted(work_ids)}

    # Series sequences are structured and should be exact.
    for path in sorted((root / "content" / "series").glob("*.yaml")):
        payload = _safe_read_yaml(path)
        if not isinstance(payload, dict):
            continue
        slug = _clean(payload.get("slug") or path.stem)
        for index, item in enumerate(payload.get("work_ids") or []):
            work_id = _clean(item)
            if work_id:
                references.setdefault(work_id, []).append({"kind": "series", "source": path.relative_to(root).as_posix(), "field": f"work_ids[{index}]", "series": slug})
        cover_id = _clean(payload.get("cover_work_id") or payload.get("cover") or "")
        if cover_id:
            references.setdefault(cover_id, []).append({"kind": "series-cover", "source": path.relative_to(root).as_posix(), "field": "cover_work_id", "series": slug})

    # Pages and authority files are scanned textually because they may contain
    # nested page-block structures. This is used as a safety index, not a parser.
    content_roots = [root / "content" / "pages", root / "content"]
    scanned: set[Path] = set()
    for folder in content_roots:
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.yaml")):
            if path in scanned or path.parent.name in {"works", "series", "templates", "schema"}:
                continue
            scanned.add(path)
            text = path.read_text(encoding="utf-8", errors="replace")
            for work_id in work_ids:
                if re.search(rf"(?<![a-zA-Z0-9_-]){re.escape(work_id)}(?![a-zA-Z0-9_-])", text):
                    references.setdefault(work_id, []).append({"kind": "content-text", "source": path.relative_to(root).as_posix(), "field": "text-match"})

    missing_refs = []
    for work_id, hits in references.items():
        if work_id not in work_ids:
            missing_refs.append({"work_id": work_id, "references": hits})
    return {
        "generated_at": _utc(),
        "work_count": len(work_ids),
        "reference_count": sum(len(v) for v in references.values()),
        "references": references,
        "missing_references": missing_refs,
    }


def _known_asset_stems(root: Path) -> set[str]:
    stems = set()
    for _, payload in iter_work_payloads(root) or []:
        work_id = _clean(payload.get("id"))
        if work_id:
            stems.add(work_id)
        image = payload.get("image") if isinstance(payload.get("image"), dict) else {}
        for key in ("master", "render_name", "renderName"):
            value = _clean(image.get(key))
            if value:
                stems.add(Path(value).stem)
    return stems


def detect_orphaned_assets(root: Path = ROOT) -> list[dict[str, str]]:
    """Find likely image assets in source/generated folders with no active work stem."""
    known = _known_asset_stems(root)
    candidates: list[Path] = []
    for base_name in ("assets", "public_upload", ".stillmrk-build"):
        base = root / base_name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                candidates.append(path)
    rows: list[dict[str, str]] = []
    for path in sorted(candidates):
        stem = path.stem
        # Generated variants often use work-id-size suffixes. Remove one suffix token.
        prefix = stem.rsplit("-", 1)[0] if "-" in stem else stem
        if stem not in known and prefix not in known:
            rows.append({"status": "warning", "check": "Orphan asset", "detail": "Image-like asset has no matching active work id/render stem.", "target": path.relative_to(root).as_posix()})
    return rows


def schema_version_rows(root: Path = ROOT) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path, payload in iter_work_payloads(root) or []:
        version = payload.get("schema_version", payload.get("schemaVersion"))
        if version is None:
            rows.append(IntegrityRow("watch", "Work schema version", "No schema_version field yet; migration should add this non-destructively when content writes are allowed.", path.relative_to(root).as_posix()).as_dict())
        elif int(version or 0) < SCHEMA_VERSION:
            rows.append(IntegrityRow("warning", "Work schema version", f"Older schema version {version}; current is {SCHEMA_VERSION}.", path.relative_to(root).as_posix()).as_dict())
        else:
            rows.append(IntegrityRow("ok", "Work schema version", f"schema_version={version}", path.relative_to(root).as_posix()).as_dict())
    return rows


def data_integrity_report(root: Path = ROOT) -> dict[str, Any]:
    rows = []
    rows.extend(work_id_integrity_rows(root))
    index = build_reference_index(root)
    if index.get("missing_references"):
        rows.append({"status": "error", "check": "Reference index", "detail": f"{len(index['missing_references'])} missing referenced work id(s).", "target": "content"})
    else:
        rows.append({"status": "ok", "check": "Reference index", "detail": f"{index.get('reference_count', 0)} references indexed across {index.get('work_count', 0)} work(s).", "target": "content"})
    orphan_rows = detect_orphaned_assets(root)
    rows.extend(orphan_rows[:25])
    rows.extend(schema_version_rows(root)[:25])
    errors = sum(1 for row in rows if row.get("status") == "error")
    warnings = sum(1 for row in rows if row.get("status") in {"warning", "watch"})
    report = {"ok": errors == 0, "errors": errors, "warnings": warnings, "rows": rows, "reference_index": index, "generated_at": _utc()}
    try:
        META_DIR.mkdir(parents=True, exist_ok=True)
        (META_DIR / "control-panel-data-integrity-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass
    return report
