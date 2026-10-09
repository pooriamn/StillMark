from __future__ import annotations

import json
import re
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

import yaml

try:
    from control_panel_io import atomic_write_text, atomic_write_json
except ImportError:  # pragma: no cover
    from scripts.control_panel_io import atomic_write_text, atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content"
BACKUP_DIR = ROOT / ".stillmrk-build" / "backups"
TRANSACTION_LOG = BACKUP_DIR / "transactions.json"
_ACTIVE_TRANSACTION: dict[str, Any] | None = None


def _path_to_txn_ref(path: Path | str) -> str:
    candidate = Path(path)
    try:
        resolved = candidate.resolve(strict=False)
    except Exception:
        resolved = candidate
    try:
        rel = resolved.relative_to(ROOT)
        return f"REL::{rel.as_posix()}"
    except Exception:
        return f"ABS::{resolved.as_posix()}"


def _txn_ref_to_path(ref: str) -> Path:
    text = str(ref or "")
    if text.startswith("REL::"):
        return ROOT / text[5:]
    if text.startswith("ABS::"):
        return Path(text[5:])
    path = Path(text)
    return path if path.is_absolute() else ROOT / path


def yaml_glob(folder: Path) -> list[Path]:
    return sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")])


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _now_stamp() -> str:
    """UTC stamp with microseconds so rapid transaction backups never collide."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _load_transactions() -> list[dict[str, Any]]:
    if not TRANSACTION_LOG.exists():
        return []
    try:
        data = json.loads(TRANSACTION_LOG.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _save_transactions(data: list[dict[str, Any]]) -> None:
    atomic_write_json(TRANSACTION_LOG, data)


def _active_ops() -> list[dict[str, Any]]:
    global _ACTIVE_TRANSACTION
    if _ACTIVE_TRANSACTION is None:
        raise RuntimeError("No active transaction")
    return _ACTIVE_TRANSACTION.setdefault("ops", [])


def record_transaction_step(step_type: str, *, target: Path | str | None = None, detail: str = "", **extra: Any) -> None:
    global _ACTIVE_TRANSACTION
    if _ACTIVE_TRANSACTION is None:
        return
    op: dict[str, Any] = {"type": str(step_type or "step"), "detail": str(detail or "")}
    if target is not None:
        op["target"] = _path_to_txn_ref(target)
        _record_target(Path(target))
    for key, value in extra.items():
        if isinstance(value, Path):
            op[key] = _path_to_txn_ref(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            op[key] = value
        else:
            op[key] = str(value)
    _active_ops().append(op)


def _finish_transaction(status: str, *, error: str = "") -> None:
    global _ACTIVE_TRANSACTION
    if _ACTIVE_TRANSACTION is None:
        return
    payload = dict(_ACTIVE_TRANSACTION)
    payload["status"] = status
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    if error:
        payload["error"] = str(error)
    rows = _load_transactions()
    rows.append(payload)
    _save_transactions(rows)
    _ACTIVE_TRANSACTION = None


def begin_transaction(label: str) -> None:
    global _ACTIVE_TRANSACTION
    if _ACTIVE_TRANSACTION is not None:
        raise RuntimeError("A transaction is already active")
    _ACTIVE_TRANSACTION = {
        "id": _now_stamp(),
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
        "ops": [],
        "targets": [],
    }


def _persist_active_transaction(status: str) -> None:
    _finish_transaction(status)


def commit_transaction() -> None:
    _persist_active_transaction("completed")


def cancel_transaction() -> None:
    global _ACTIVE_TRANSACTION
    _ACTIVE_TRANSACTION = None


@contextmanager
def transaction(label: str):
    """Transaction wrapper that preserves both the primary and rollback failure."""
    begin_transaction(label)
    try:
        yield
    except Exception as exc:
        rollback_error = ""
        try:
            rollback_active_transaction()
        except Exception as rollback_exc:
            rollback_error = f"; rollback failed: {rollback_exc}"
        finally:
            _finish_transaction("rolled_back", error=f"{exc}{rollback_error}")
        if rollback_error:
            raise RuntimeError(f"{exc}{rollback_error}") from exc
        raise
    else:
        commit_transaction()


def _record_target(path: Path) -> None:
    global _ACTIVE_TRANSACTION
    if _ACTIVE_TRANSACTION is None:
        return
    ref = _path_to_txn_ref(path)
    targets = _ACTIVE_TRANSACTION.setdefault("targets", [])
    if ref not in targets:
        targets.append(ref)


def _has_backup_for(path: Path) -> bool:
    global _ACTIVE_TRANSACTION
    if _ACTIVE_TRANSACTION is None:
        return False
    target = _path_to_txn_ref(path)
    for op in _ACTIVE_TRANSACTION.get("ops", []):
        if op.get("type") in {"file_backup", "dir_backup"} and op.get("target") == target:
            return True
    return False


def backup_file(path: Path) -> Path:
    timestamp = _now_stamp()
    backup_dir = BACKUP_DIR / "files"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}.{timestamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path


def snapshot_path(path: Path) -> Path | None:
    path = path.resolve() if path.exists() else path
    if not path.exists():
        return None
    if _ACTIVE_TRANSACTION is not None and _has_backup_for(path):
        return None
    timestamp = _now_stamp()
    if path.is_dir():
        backup_dir = BACKUP_DIR / "dirs" / f"{path.name}.{timestamp}"
        suffix = 1
        while backup_dir.exists():
            suffix += 1
            backup_dir = BACKUP_DIR / "dirs" / f"{path.name}.{timestamp}.{suffix}"
        shutil.copytree(path, backup_dir)
        if _ACTIVE_TRANSACTION is not None:
            _active_ops().append({
                "type": "dir_backup",
                "target": _path_to_txn_ref(path),
                "backup": _path_to_txn_ref(backup_dir),
            })
            _record_target(path)
        return backup_dir
    backup_path = backup_file(path)
    if _ACTIVE_TRANSACTION is not None:
        _active_ops().append({
            "type": "file_backup",
            "target": _path_to_txn_ref(path),
            "backup": _path_to_txn_ref(backup_path),
        })
        _record_target(path)
    return backup_path


def register_created_path(path: Path) -> None:
    global _ACTIVE_TRANSACTION
    if _ACTIVE_TRANSACTION is None:
        return
    ref = _path_to_txn_ref(path)
    for op in _ACTIVE_TRANSACTION.get("ops", []):
        if op.get("type") == "created" and op.get("target") == ref:
            return
    _active_ops().append({"type": "created", "target": ref, "kind": "dir" if path.is_dir() else "file"})
    _record_target(path if path.is_absolute() else ROOT / path)


def rollback_active_transaction() -> None:
    global _ACTIVE_TRANSACTION
    if _ACTIVE_TRANSACTION is None:
        return
    ops = list(_ACTIVE_TRANSACTION.get("ops", []))
    for op in reversed(ops):
        target = _txn_ref_to_path(op["target"])
        if op["type"] == "created":
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    try:
                        target.unlink()
                    except FileNotFoundError:
                        pass
        elif op["type"] == "file_backup":
            backup = _txn_ref_to_path(op["backup"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                shutil.copy2(backup, target)
        elif op["type"] == "dir_backup":
            backup = _txn_ref_to_path(op["backup"])
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            if backup.exists():
                shutil.copytree(backup, target)


def restore_last_transaction() -> dict[str, Any] | None:
    rows = _load_transactions()
    target_txn = None
    for txn in reversed(rows):
        if txn.get("status") == "completed":
            target_txn = txn
            break
    if not target_txn:
        return None
    for op in reversed(target_txn.get("ops", [])):
        target = _txn_ref_to_path(op["target"])
        if op["type"] == "created":
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    try:
                        target.unlink()
                    except FileNotFoundError:
                        pass
        elif op["type"] == "file_backup":
            backup = _txn_ref_to_path(op["backup"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists():
                shutil.copy2(backup, target)
        elif op["type"] == "dir_backup":
            backup = _txn_ref_to_path(op["backup"])
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            if backup.exists():
                shutil.copytree(backup, target)
    target_txn["status"] = "undone"
    target_txn["undone_at"] = datetime.now(timezone.utc).isoformat()
    _save_transactions(rows)
    return target_txn


def recent_transactions(limit: int = 10) -> list[dict[str, Any]]:
    rows = _load_transactions()
    return list(reversed(rows[-limit:]))


def write_yaml(path: Path, data: Any) -> None:
    path = Path(path)
    existed = path.exists()
    if existed:
        snapshot_path(path)
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    atomic_write_text(path, rendered)
    try:
        rel_parent = path.parent.resolve(strict=False).relative_to(CONTENT_DIR.resolve(strict=False))
        scope = rel_parent.parts[0] if rel_parent.parts else ""
        if scope:
            invalidate_content_entry_cache(scope)
    except Exception:
        invalidate_content_entry_cache()
    record_transaction_step("yaml_write", target=path, detail="atomic YAML save", existed_before=existed)
    if not existed:
        register_created_path(path)



def guarded_unlink(path: Path | str, *, detail: str = "") -> None:
    target = Path(path)
    if not target.exists():
        return
    snapshot_path(target)
    target.unlink()
    record_transaction_step("unlink", target=target, detail=detail or "file removed")


def guarded_rmtree(path: Path | str, *, detail: str = "") -> None:
    target = Path(path)
    if not target.exists():
        return
    snapshot_path(target)
    shutil.rmtree(target, ignore_errors=True)
    record_transaction_step("rmtree", target=target, detail=detail or "directory removed")


def guarded_move(source: Path | str, destination: Path | str, *, detail: str = "") -> None:
    src = Path(source)
    dst = Path(destination)
    if dst.exists():
        snapshot_path(dst)
    snapshot_path(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    record_transaction_step("move", target=dst, detail=detail or "file moved", source=_path_to_txn_ref(src))


def guarded_copy2(source: Path | str, destination: Path | str, *, detail: str = "") -> None:
    src = Path(source)
    dst = Path(destination)
    existed = dst.exists()
    if existed:
        snapshot_path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if not existed:
        register_created_path(dst)
    record_transaction_step("copy", target=dst, detail=detail or "file copied", source=_path_to_txn_ref(src), existed_before=existed)


class _ContentDirCacheEntry(NamedTuple):
    signature: tuple[tuple[str, int, int], ...]
    rows: tuple[dict[str, Any], ...]


_CONTENT_DIR_CACHE: dict[str, _ContentDirCacheEntry] = {}


def _content_dir_signature(folder: Path) -> tuple[tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = []
    for path in yaml_glob(folder):
        try:
            stat = path.stat()
        except OSError:
            continue
        signature.append((path.name, int(stat.st_mtime_ns), int(stat.st_size)))
    return tuple(signature)


def _load_content_dir_cached(cache_key: str, folder: Path) -> list[dict[str, Any]]:
    signature = _content_dir_signature(folder)
    cached = _CONTENT_DIR_CACHE.get(cache_key)
    if cached and cached.signature == signature:
        return [dict(row) for row in cached.rows]
    rows: list[dict[str, Any]] = []
    for path in yaml_glob(folder):
        payload = load_yaml(path)
        if isinstance(payload, dict):
            rows.append(dict(payload))
    _CONTENT_DIR_CACHE[cache_key] = _ContentDirCacheEntry(signature=signature, rows=tuple(dict(row) for row in rows))
    return [dict(row) for row in rows]


def invalidate_content_entry_cache(scope: str | None = None) -> None:
    """Clear cached YAML directory reads after saves/imports/renames.

    The cache is signature-based, so normal file changes are detected
    automatically. Explicit invalidation keeps save/transaction paths honest and
    gives the Qt backend a cheap hook when it performs structural edits.
    """
    key = str(scope or "").strip().lower()
    if not key:
        _CONTENT_DIR_CACHE.clear()
        return
    aliases = {
        "work": "works",
        "works": "works",
        "series": "series",
        "page": "pages",
        "pages": "pages",
    }
    normalized = aliases.get(key, key)
    _CONTENT_DIR_CACHE.pop(normalized, None)


def load_series_entries() -> list[dict[str, Any]]:
    return _load_content_dir_cached("series", CONTENT_DIR / "series")


def load_work_entries() -> list[dict[str, Any]]:
    return _load_content_dir_cached("works", CONTENT_DIR / "works")


def series_file_for_slug(series_slug: str) -> Path:
    return CONTENT_DIR / "series" / f"{series_slug}.yaml"


def work_file_for_id(work_id: str) -> Path:
    return CONTENT_DIR / "works" / f"{work_id}.yaml"


def page_file_for_key(page_key: str) -> Path:
    return CONTENT_DIR / "pages" / f"{page_key}.yaml"


def available_page_keys() -> list[str]:
    return [path.stem for path in yaml_glob(CONTENT_DIR / "pages")]


def load_page_payload(page_key: str) -> dict[str, Any]:
    payload = load_yaml(page_file_for_key(page_key))
    return payload if isinstance(payload, dict) else {}


def save_page_payload(page_key: str, payload: dict[str, Any]) -> None:
    write_yaml(page_file_for_key(page_key), payload)


def site_file() -> Path:
    return CONTENT_DIR / 'site.yaml'


def artist_file() -> Path:
    return CONTENT_DIR / 'artist.yaml'


def navigation_file() -> Path:
    return CONTENT_DIR / 'navigation.yaml'


def resources_file() -> Path:
    return CONTENT_DIR / 'resources.yaml'


def load_site_settings() -> dict[str, Any]:
    payload = load_yaml(site_file())
    return payload if isinstance(payload, dict) else {}


def save_site_settings(payload: dict[str, Any]) -> None:
    write_yaml(site_file(), payload)
    mark_unpublished_changes()


def load_artist_profile() -> dict[str, Any]:
    payload = load_yaml(artist_file())
    return payload if isinstance(payload, dict) else {}


def save_artist_profile(payload: dict[str, Any]) -> None:
    write_yaml(artist_file(), payload)
    mark_unpublished_changes()


def load_navigation_payload() -> dict[str, Any]:
    payload = load_yaml(navigation_file())
    return payload if isinstance(payload, dict) else {'items': []}


def save_navigation_payload(payload: dict[str, Any]) -> None:
    write_yaml(navigation_file(), payload)
    mark_unpublished_changes()


def load_resources_payload() -> dict[str, Any]:
    payload = load_yaml(resources_file())
    return payload if isinstance(payload, dict) else {'downloads': []}


def save_resources_payload(payload: dict[str, Any]) -> None:
    write_yaml(resources_file(), payload)
    mark_unpublished_changes()


def slugify_work_id(value: str) -> str:
    raw = str(value or "").strip()
    # Defend against cross-machine sync suffixes such as
    # "-Pooria#U2019s MacBook Pro" being folded into real work IDs.
    raw = re.sub(
        r"[-\s]+Pooria(?:#U2019|%E2%80%99|’|'|\u2019)s[-\s]+MacBook[-\s]+Pro$",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return text


def ensure_unique_work_id(work_id: str, allow_existing: bool = False) -> None:
    path = work_file_for_id(work_id)
    if path.exists() and not allow_existing:
        raise ValueError(f"Work id '{work_id}' already exists")


class SeriesIndex(NamedTuple):
    entries: tuple[dict[str, Any], ...]
    slug_map: dict[str, dict[str, Any]]
    folded_slug_map: dict[str, str]
    safe_slug_map: dict[str, str]
    title_map: dict[str, str]

    @property
    def valid_slugs(self) -> set[str]:
        return set(self.slug_map)

    def resolve(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text in self.slug_map:
            return text
        folded = text.casefold()
        if folded in self.folded_slug_map:
            return self.folded_slug_map[folded]
        safe = slugify_work_id(text)
        if safe in self.safe_slug_map:
            return self.safe_slug_map[safe]
        return self.title_map.get(folded, "")


def build_series_index(entries: list[dict[str, Any]] | None = None) -> SeriesIndex:
    clean_entries = tuple(dict(entry) for entry in (entries if entries is not None else load_series_entries()) if isinstance(entry, dict))
    slug_map: dict[str, dict[str, Any]] = {}
    folded_slug_map: dict[str, str] = {}
    safe_slug_map: dict[str, str] = {}
    title_map: dict[str, str] = {}
    for entry in clean_entries:
        slug = str(entry.get("slug") or "").strip()
        if not slug:
            continue
        slug_map[slug] = entry
        folded_slug_map.setdefault(slug.casefold(), slug)
        safe_slug_map.setdefault(slugify_work_id(slug), slug)
        title = str(entry.get("title") or "").strip()
        if title:
            title_map.setdefault(title.casefold(), slug)
            safe_slug_map.setdefault(slugify_work_id(title), slug)
    return SeriesIndex(
        entries=clean_entries,
        slug_map=slug_map,
        folded_slug_map=folded_slug_map,
        safe_slug_map=safe_slug_map,
        title_map=title_map,
    )

def resolve_series_slug(value: Any) -> str:
    """Return the canonical series slug for a slug, title, or imported label."""
    return build_series_index().resolve(value)


def work_to_series_map(
    works: list[dict[str, Any]] | None = None,
    series_entries: list[dict[str, Any]] | None = None,
    series_index: SeriesIndex | None = None,
) -> dict[str, str]:
    index = series_index or build_series_index(series_entries)
    mapping: dict[str, str] = {}
    for series in index.entries:
        slug = str(series.get("slug") or "").strip()
        if not slug:
            continue
        for work_id in series.get("work_ids", []) or []:
            work_text = str(work_id or "").strip()
            if work_text:
                mapping[work_text] = slug
    work_rows = works if works is not None else load_work_entries()
    for work in work_rows:
        if not isinstance(work, dict):
            continue
        work_id = str(work.get("id") or "").strip()
        if not work_id or work_id in mapping:
            continue
        series_slug = index.resolve(work.get("series"))
        if series_slug in index.valid_slugs:
            mapping[work_id] = series_slug
    return mapping


def available_series_slugs() -> list[str]:
    return [str(entry.get("slug") or "").strip() for entry in load_series_entries() if str(entry.get("slug") or "").strip()]


def available_work_ids() -> list[str]:
    return sorted([str(entry.get("id") or "").strip() for entry in load_work_entries() if str(entry.get("id") or "").strip()])


def available_download_ids() -> list[str]:
    resources = load_resources_payload()
    downloads = resources.get('downloads') if isinstance(resources.get('downloads'), list) else []
    return sorted([str(item.get('id') or '').strip() for item in downloads if isinstance(item, dict) and str(item.get('id') or '').strip()])


def load_series_payload(series_slug: str) -> dict[str, Any]:
    payload = load_yaml(series_file_for_slug(series_slug))
    return payload if isinstance(payload, dict) else {}


def save_series_payload(series_slug: str, payload: dict[str, Any]) -> None:
    path = series_file_for_slug(series_slug)
    write_yaml(path, payload)
    mark_unpublished_changes(path)


def load_work_payload(work_id: str) -> dict[str, Any]:
    payload = load_yaml(work_file_for_id(work_id))
    return payload if isinstance(payload, dict) else {}


def save_work_payload(work_id: str, payload: dict[str, Any]) -> None:
    path = work_file_for_id(work_id)
    write_yaml(path, payload)
    mark_unpublished_changes(path)


def series_lookup_by_slug() -> dict[str, dict[str, Any]]:
    return {str(item.get('slug') or '').strip(): item for item in load_series_entries() if str(item.get('slug') or '').strip()}


def work_lookup_by_id() -> dict[str, dict[str, Any]]:
    return {str(item.get('id') or '').strip(): item for item in load_work_entries() if str(item.get('id') or '').strip()}


def series_membership_map() -> dict[str, list[str]]:
    membership: dict[str, list[str]] = {}
    for series in load_series_entries():
        slug = str(series.get('slug') or '').strip()
        if not slug:
            continue
        membership[slug] = [str(item).strip() for item in (series.get('work_ids') or []) if str(item).strip()]
    return membership


def load_home_relationships() -> dict[str, list[str]]:
    model = load_page_model('home')
    featured_series: list[str] = []
    featured_works: list[str] = []
    for section in model.sections:
        if section.type == 'featured_series':
            featured_series = [str(item).strip() for item in (section.data.get('series_slugs') or []) if str(item).strip()]
        elif section.type == 'featured_works':
            featured_works = [str(item).strip() for item in (section.data.get('work_ids') or []) if str(item).strip()]
    return {'featured_series': featured_series, 'featured_works': featured_works}


def save_home_relationships(*, featured_series: list[str] | None = None, featured_works: list[str] | None = None) -> None:
    model = load_page_model('home')
    for section in model.sections:
        if section.type == 'featured_series' and featured_series is not None:
            section.data['series_slugs'] = [str(item).strip() for item in featured_series if str(item).strip()]
        elif section.type == 'featured_works' and featured_works is not None:
            section.data['work_ids'] = [str(item).strip() for item in featured_works if str(item).strip()]
    save_page_model('home', model, validate=False)


def series_position_for_work(work_id: str) -> tuple[str | None, int | None]:
    for series in load_series_entries():
        slug = str(series.get('slug') or '').strip()
        work_ids = [str(item).strip() for item in (series.get('work_ids') or []) if str(item).strip()]
        if work_id in work_ids:
            return slug, work_ids.index(work_id) + 1
    return None, None


def work_relationship_refs(work_id: str) -> dict[str, Any]:
    refs = {'series': None, 'position': None, 'is_cover_for': [], 'homepage_featured': False, 'hero_pages': []}
    series_slug, position = series_position_for_work(work_id)
    refs['series'] = series_slug
    refs['position'] = position
    home = load_home_relationships()
    refs['homepage_featured'] = work_id in home['featured_works']
    for series in load_series_entries():
        slug = str(series.get('slug') or '').strip()
        if str(series.get('cover_work_id') or '').strip() == work_id and slug:
            refs['is_cover_for'].append(slug)
    for page_key in available_page_keys():
        payload = load_page_payload(page_key)
        hero = payload.get('hero') if isinstance(payload.get('hero'), dict) else {}
        hero_work_id = str(hero.get('feature_work_id') or '').strip()
        if hero_work_id == work_id:
            refs['hero_pages'].append(page_key)
    return refs


def series_relationship_refs(series_slug: str) -> dict[str, Any]:
    payload = load_series_payload(series_slug)
    return {
        'related_series_slugs': [str(item).strip() for item in (payload.get('related_series_slugs') or []) if str(item).strip()],
        'download_ids': [str(item).strip() for item in (payload.get('download_ids') or []) if str(item).strip()],
        'home_featured': series_slug in load_home_relationships()['featured_series'],
    }


def series_payload_default(title: str, slug: str, years: str, mood: str, description: str, order: int, visibility: str = "public") -> dict[str, Any]:
    public = visibility == "public"
    return {
        "slug": slug,
        "title": title,
        "years": years,
        "mood": mood,
        "description": description,
        "cover_work_id": None,
        "work_ids": [],
        "order": order,
        "visibility": visibility,
        "review_mode": not public,
        "allow_favorites": True,
        "allow_inquiry_basket": True,
        "project_type": "fine-art",
        "download_ids": [],
    }


def create_series_file(series_slug: str, title: str, years: str, mood: str, description: str, order: int | None = None, visibility: str = "public") -> Path:
    path = series_file_for_slug(series_slug)
    if path.exists():
        raise ValueError(f"Series slug '{series_slug}' already exists")
    used_orders = [int(entry.get("order", 0) or 0) for entry in load_series_entries()]
    next_order = max(used_orders, default=0) + 1
    payload = series_payload_default(title=title, slug=series_slug, years=years, mood=mood, description=description, order=order or next_order, visibility=visibility)
    write_yaml(path, payload)
    mark_unpublished_changes()
    return path


def insert_work_into_series(series_slug: str, work_id: str, position: int | None = None) -> None:
    path = series_file_for_slug(series_slug)
    if not path.exists():
        raise FileNotFoundError(f"Series file not found: {path}")
    payload = load_yaml(path)
    work_ids = [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]
    if work_id in work_ids:
        work_ids.remove(work_id)
    if position is None or position <= 0 or position > len(work_ids) + 1:
        work_ids.append(work_id)
    else:
        work_ids.insert(position - 1, work_id)
    seen: set[str] = set()
    work_ids = [wid for wid in work_ids if not (wid in seen or seen.add(wid))]
    payload["work_ids"] = work_ids
    if not payload.get("cover_work_id"):
        payload["cover_work_id"] = work_ids[0] if work_ids else None
    write_yaml(path, payload)
    mark_unpublished_changes()


def remove_work_from_series(series_slug: str, work_id: str) -> None:
    path = series_file_for_slug(series_slug)
    if not path.exists():
        return
    payload = load_yaml(path)
    work_ids = [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip() and str(item).strip() != work_id]
    payload["work_ids"] = work_ids
    if str(payload.get("cover_work_id") or "").strip() == work_id:
        payload["cover_work_id"] = work_ids[0] if work_ids else None
    write_yaml(path, payload)
    mark_unpublished_changes()


def set_series_cover_work(series_slug: str, work_id: str) -> None:
    path = series_file_for_slug(series_slug)
    payload = load_yaml(path)
    work_ids = [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]
    if work_id not in work_ids:
        raise ValueError(f"Work '{work_id}' is not inside series '{series_slug}'")
    payload["cover_work_id"] = work_id
    write_yaml(path, payload)
    mark_unpublished_changes()


def set_page_feature_work(page_key: str, work_id: str) -> None:
    path = page_file_for_key(page_key)
    payload = load_yaml(path)
    hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else None
    if not hero or "feature_work_id" not in hero:
        raise ValueError(f"Page '{page_key}' does not have a hero.feature_work_id field")
    hero["feature_work_id"] = work_id
    payload["hero"] = hero
    write_yaml(path, payload)


def get_page_feature_work(page_key: str) -> str | None:
    payload = load_yaml(page_file_for_key(page_key))
    hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else None
    if not hero:
        return None
    value = str(hero.get("feature_work_id") or "").strip()
    return value or None


def edit_work_payload(work_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    path = work_file_for_id(work_id)
    if not path.exists():
        raise FileNotFoundError(f"Work file not found: {path}")
    payload = load_yaml(path) or {}
    payload.update({key: value for key, value in updates.items() if value is not None})
    write_yaml(path, payload)
    mark_unpublished_changes()
    return payload


def move_work_to_series(work_id: str, target_series_slug: str, position: int | None = None) -> tuple[str | None, str]:
    current_series_slug = work_to_series_map().get(work_id)
    if current_series_slug == target_series_slug:
        insert_work_into_series(target_series_slug, work_id, position=position)
        return current_series_slug, target_series_slug
    if current_series_slug:
        remove_work_from_series(current_series_slug, work_id)
    insert_work_into_series(target_series_slug, work_id, position=position)
    path = work_file_for_id(work_id)
    payload = load_yaml(path) or {}
    payload["series"] = target_series_slug
    write_yaml(path, payload)
    mark_unpublished_changes()
    return current_series_slug, target_series_slug


def reorder_homepage_featured(*, featured_series: list[str] | None = None, selected_works: list[str] | None = None) -> None:
    path = page_file_for_key("home")
    payload = load_yaml(path) or {}
    if featured_series is not None:
        payload.setdefault("featured_series", {})["series_slugs"] = featured_series
    if selected_works is not None:
        payload.setdefault("selected_works", {})["work_ids"] = selected_works
    write_yaml(path, payload)
    mark_unpublished_changes()


def search_library(query: str) -> list[dict[str, str]]:
    query_text = query.strip().lower()
    results: list[dict[str, str]] = []
    work_series = work_to_series_map()
    for path in yaml_glob(CONTENT_DIR / "works"):
        payload = load_yaml(path) or {}
        haystack = " ".join([
            str(payload.get("id") or ""),
            str(payload.get("title") or ""),
            str(payload.get("alt") or ""),
            str(payload.get("caption") or ""),
            str(payload.get("location") or ""),
            ", ".join(payload.get("tags") or []),
            str(work_series.get(str(payload.get("id") or ""), "")),
        ]).lower()
        if not query_text or query_text in haystack:
            results.append({
                "type": "work",
                "id": str(payload.get("id") or ""),
                "title": str(payload.get("title") or ""),
                "series": work_series.get(str(payload.get("id") or ""), ""),
            })
    for path in yaml_glob(CONTENT_DIR / "series"):
        payload = load_yaml(path) or {}
        haystack = " ".join([
            str(payload.get("slug") or ""),
            str(payload.get("title") or ""),
            str(payload.get("description") or ""),
        ]).lower()
        if not query_text or query_text in haystack:
            results.append({
                "type": "series",
                "id": str(payload.get("slug") or ""),
                "title": str(payload.get("title") or ""),
                "series": str(payload.get("slug") or ""),
            })
    return results


def placeholder_warnings(text: str, label: str) -> list[str]:
    lowered = text.strip().lower()
    warnings: list[str] = []
    bad_fragments = ["test", "placeholder", "lorem", "just to see", "caption for caption", "alt text"]
    if any(fragment in lowered for fragment in bad_fragments):
        warnings.append(f"{label} looks like placeholder text")
    if len(lowered.split()) < 2:
        warnings.append(f"{label} is very short")
    return warnings


def validate_work_input(*, work_id: str, title: str, alt: str, caption: str, tags: list[str], hero_safe: bool, social_safe: bool) -> list[str]:
    warnings: list[str] = []
    if len(alt.split()) < 5:
        warnings.append("Alt text should have at least 5 words")
    if len(title.split()) < 2:
        warnings.append("Title is very short")
    warnings.extend(placeholder_warnings(title, "Title"))
    if caption:
        warnings.extend(placeholder_warnings(caption, "Caption"))
        if len(caption.split()) < 4:
            warnings.append("Caption is very short")
    if not tags:
        warnings.append("Tags are empty (editorial metadata only)")
    if not hero_safe:
        warnings.append("Hero safe is off (editorial warning only; not an automatic public exclusion)")
    if social_safe and not hero_safe:
        warnings.append("Social safe is on while hero safe is off; review the crop manually if you plan to use the work in wide formats")
    if any(tag.lower() in {"test", "sample", "pooria", "temp", "tmp"} for tag in tags):
        warnings.append("Some tags look temporary or non-descriptive")
    if work_id != slugify_work_id(work_id):
        warnings.append("Work id should stay lowercase with hyphens only")
    return warnings


def validate_page_payload(page_key: str, payload: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
    for field in ["title", "description", "og_description", "og_image_alt"]:
        value = str(meta.get(field) or "").strip()
        if value:
            warnings.extend(placeholder_warnings(value, f"Meta {field}"))
    for field in ["eyebrow", "title", "lead"]:
        value = str(hero.get(field) or "").strip()
        if value:
            warnings.extend(placeholder_warnings(value, f"Hero {field}"))
    if page_key == "home":
        featured = payload.get("featured_series") if isinstance(payload.get("featured_series"), dict) else {}
        selected = payload.get("selected_works") if isinstance(payload.get("selected_works"), dict) else {}
        if not (featured.get("series_slugs") or []):
            warnings.append("Homepage featured series list is empty")
        if not (selected.get("work_ids") or []):
            warnings.append("Homepage selected works list is empty")
    return warnings


def create_work_payload(
    *,
    work_id: str,
    title: str,
    series_slug: str,
    year: str,
    location: str,
    alt: str,
    caption: str,
    tags: list[str],
    published: bool,
    hero_safe: bool,
    grid_safe: bool,
    social_safe: bool,
    focal_x: int,
    focal_y: int,
    master_filename: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": work_id,
        "title": title,
        "series": series_slug,
        "year": year,
        "location": location,
        "alt": alt,
        "caption": caption,
        "published": published,
        "hero_safe": hero_safe,
        "grid_safe": grid_safe,
        "social_safe": social_safe,
        "tags": tags,
        "focal_point": {"x": int(focal_x), "y": int(focal_y)},
    }
    if master_filename and Path(master_filename).stem != work_id:
        payload["image"] = {"master": master_filename, "render_name": work_id}
    return payload


# --- Phase 11 content builder helpers ---
try:
    from content_models import PageModel, PublishState, ValidationIssue
    from page_blocks import ensure_required_system_sections, normalize_legacy_page_payload, page_model_to_payload
except ImportError:  # pragma: no cover
    from scripts.content_models import PageModel, PublishState, ValidationIssue  # type: ignore
    from scripts.page_blocks import ensure_required_system_sections, normalize_legacy_page_payload, page_model_to_payload  # type: ignore

PUBLISH_STATE_PATH = ROOT / '.stillmrk-build' / 'meta' / 'publish-state.json'


def load_page_model(page_key: str) -> PageModel:
    payload = load_page_payload(page_key)
    model = normalize_legacy_page_payload(page_key, payload)
    return ensure_required_system_sections(model)


def normalize_page_payload(page_key: str, payload: dict) -> PageModel:
    return ensure_required_system_sections(normalize_legacy_page_payload(page_key, payload))


def save_page_model(page_key: str, model: PageModel, *, validate: bool = True) -> list[ValidationIssue]:
    original = load_page_payload(page_key)
    payload = page_model_to_payload(model, original)
    issues: list[ValidationIssue] = []
    if validate:
        try:
            from helpers_validation import ContentValidator
        except ImportError:  # pragma: no cover
            from scripts.helpers_validation import ContentValidator  # type: ignore
        validator = ContentValidator(ROOT)
        issues = validator.validate_page_model(page_key, model)
        if any(item.severity == 'error' for item in issues):
            return issues
    save_page_payload(page_key, payload)
    mark_unpublished_changes()
    return issues


def page_model_to_payload_dict(model: PageModel) -> dict:
    return page_model_to_payload(model, {})


def diff_page_payloads(before: dict, after: dict) -> list[str]:
    lines: list[str] = []

    def _walk(prefix: str, old: Any, new: Any) -> None:
        if type(old) != type(new):
            lines.append(f"{prefix or '<root>'}: {old!r} → {new!r}")
            return
        if isinstance(old, dict):
            keys = sorted(set(old.keys()) | set(new.keys()))
            for key in keys:
                _walk(f"{prefix}.{key}" if prefix else str(key), old.get(key), new.get(key))
            return
        if isinstance(old, list):
            if old != new:
                lines.append(f"{prefix or '<root>'}: {old!r} → {new!r}")
            return
        if old != new:
            lines.append(f"{prefix or '<root>'}: {old!r} → {new!r}")

    _walk('', before or {}, after or {})
    return lines


def load_global_authority_bundle() -> dict[str, dict]:
    return {
        'site': load_site_settings(),
        'artist': load_artist_profile(),
        'navigation': load_navigation_payload(),
        'resources': load_resources_payload(),
    }


def save_global_authority_bundle(bundle: dict[str, dict], *, validate: bool = True) -> list[ValidationIssue]:
    save_site_settings(bundle.get('site') or {})
    save_artist_profile(bundle.get('artist') or {})
    save_navigation_payload(bundle.get('navigation') or {'items': []})
    save_resources_payload(bundle.get('resources') or {'downloads': []})
    mark_unpublished_changes()
    return []


def load_publish_state() -> PublishState:
    if not PUBLISH_STATE_PATH.exists():
        return PublishState()
    try:
        data = json.loads(PUBLISH_STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return PublishState()
    return PublishState.from_dict(data if isinstance(data, dict) else {})


def save_publish_state(state: PublishState) -> None:
    atomic_write_json(PUBLISH_STATE_PATH, state.to_dict())


def compute_content_hash() -> str:
    import hashlib
    digest = hashlib.sha256()
    for path in sorted((CONTENT_DIR).rglob('*.yaml')):
        digest.update(path.relative_to(ROOT).as_posix().encode('utf-8'))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _changed_path_signature(path: Path | str | None) -> str:
    if path is None:
        return compute_content_hash()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        rel = candidate.resolve(strict=False).relative_to(ROOT).as_posix()
    except Exception:
        rel = str(candidate)
    try:
        stat = candidate.stat()
        return f"dirty:{rel}:{int(stat.st_mtime_ns)}:{int(stat.st_size)}"
    except Exception:
        return f"dirty:{rel}:missing"


def mark_unpublished_changes(changed_path: Path | str | None = None) -> None:
    state = load_publish_state()
    # Full content hashing is useful after builds and broad imports, but it is
    # unnecessarily expensive for the hot path of editing one work YAML file.
    # A targeted dirty signature is enough to mark publish state as changed;
    # clear_unpublished_changes() still computes the authoritative full hash.
    state.content_hash = _changed_path_signature(changed_path)
    state.has_unpublished_changes = True
    save_publish_state(state)


def clear_unpublished_changes(*, built_at: str) -> None:
    state = load_publish_state()
    state.content_hash = compute_content_hash()
    state.last_build_at = built_at
    state.last_publish_at = built_at
    state.has_unpublished_changes = False
    save_publish_state(state)
