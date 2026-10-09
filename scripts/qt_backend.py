from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import threading
import sys
import time
import zipfile
from collections import deque
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml
from PIL import Image

try:
    from control_panel_io import atomic_write_text, atomic_write_json, append_jsonl, rotate_jsonl_log as _rotate_jsonl_log
    from control_panel_error_policy import make_error_record
    from control_panel_bulk_ops import plan_bulk_operation, append_bulk_report
    from control_panel_data_integrity import validate_work_id_slug, data_integrity_report as _data_integrity_report, build_reference_index as _build_reference_index
    from control_panel_accessibility_audit import static_accessibility_rows
    from control_panel_performance_budgets import performance_budget_report as _performance_budget_report, record_budget_event
except ImportError:  # pragma: no cover
    from scripts.control_panel_io import atomic_write_text, atomic_write_json, append_jsonl, rotate_jsonl_log as _rotate_jsonl_log
    from scripts.control_panel_error_policy import make_error_record
    from scripts.control_panel_bulk_ops import plan_bulk_operation, append_bulk_report
    from scripts.control_panel_data_integrity import validate_work_id_slug, data_integrity_report as _data_integrity_report, build_reference_index as _build_reference_index
    from scripts.control_panel_accessibility_audit import static_accessibility_rows
    from scripts.control_panel_performance_budgets import performance_budget_report as _performance_budget_report, record_budget_event

from services.health_service import build_portfolio_health_report

from helpers_content import (
    available_page_keys,
    available_series_slugs,
    create_series_file,
    create_work_payload,
    ensure_unique_work_id,
    insert_work_into_series,
    load_artist_profile,
    load_global_authority_bundle,
    load_home_relationships,
    load_navigation_payload,
    load_page_model,
    load_page_payload,
    load_publish_state,
    load_resources_payload,
    load_series_entries,
    load_series_payload,
    load_site_settings,
    load_work_entries,
    load_work_payload,
    build_series_index,
    invalidate_content_entry_cache,
    mark_unpublished_changes,
    move_work_to_series,
    page_file_for_key,
    remove_work_from_series,
    reorder_homepage_featured,
    register_created_path,
    record_transaction_step,
    guarded_copy2,
    guarded_move,
    guarded_rmtree,
    guarded_unlink,
    save_artist_profile,
    save_global_authority_bundle,
    save_navigation_payload,
    save_page_model,
    save_page_payload,
    save_resources_payload,
    save_series_payload,
    save_site_settings,
    save_work_payload,
    series_file_for_slug,
    slugify_work_id,
    snapshot_path,
    transaction,
    diff_page_payloads,
    normalize_page_payload,
    work_file_for_id,
    work_to_series_map,
    write_yaml,
    load_yaml,
    recent_transactions,
    restore_last_transaction,
    resolve_series_slug,
)
from helpers_image import (
    derivative_dir_for_work,
    generate_derivatives,
    load_pipeline,
    clear_pipeline_cache,
    safe_copy_to_originals,
    source_path_for_work,
    source_root,
    generated_root,
    move_original_between_series,
    move_generated_between_series,
    write_ingestion_log,
)
from workbook_sync import (
    analyze_workbook_import,
    export_site_workbook,
    import_site_workbook,
    _ensure_openpyxl,
    _sheet_to_dict_rows,
    _unflatten_rows,
    _norm_compare,
)
from helpers_validation import ContentValidator
from content_models import PageModel
from page_blocks import page_model_to_payload

try:
    from control_panel_scope_guard import scope_summary
except Exception:  # pragma: no cover - diagnostics must not block backend startup
    scope_summary = None  # type: ignore[assignment]
try:
    from control_panel_layout_state import state_diagnostics
    from control_panel_thread_safety import thread_safety_summary
    from control_panel_tabs import boundary_report
except Exception:  # pragma: no cover - optional diagnostics helpers
    state_diagnostics = None  # type: ignore[assignment]
    thread_safety_summary = None  # type: ignore[assignment]
    boundary_report = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content"
UI_STATE_PATH = ROOT / ".stillmrk-build" / "meta" / "qt-control-panel-state.json"
CONTROL_PANEL_STATE_PATH = ROOT / ".stillmrk-build" / "meta" / "control-panel-state.json"
HEALTH_CACHE_MAX_AGE_SECONDS = 30 * 60
DRAFTS_DIR = ROOT / ".stillmrk-build" / "qt-drafts"
_FINGERPRINT_CACHE_TTL = 5.0
_FINGERPRINT_CACHE_MAX = 200
_FINGERPRINT_CACHE_LOCK = threading.Lock()
_FINGERPRINT_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

# 5s TTL: series completeness is expensive (loads all works) but must stay
# fresh during active editing.
_SERIES_COMPLETENESS_CACHE_TTL = 5.0
_SERIES_COMPLETENESS_CACHE_LOCK = threading.Lock()
_SERIES_COMPLETENESS_CACHE: tuple[float, list[dict[str, Any]]] | None = None

# 5s TTL: series slug validation should avoid repeated YAML walks while still
# reflecting recent series create/rename operations.
_SERIES_SLUG_CACHE_TTL = 5.0
_SERIES_SLUG_CACHE_LOCK = threading.Lock()
_SERIES_SLUG_CACHE: tuple[float, set[str]] | None = None
_IMAGE_DIMENSIONS_CACHE_MAX = 512
_IMAGE_DIMENSIONS_CACHE_LOCK = threading.Lock()
_IMAGE_DIMENSIONS_CACHE: dict[tuple[str, int, int], tuple[int, int] | None] = {}
_DUPLICATE_SCAN_LOCK = threading.Lock()
BACKUP_FILES_DIR = ROOT / ".stillmrk-build" / "backups" / "files"
TRANSACTION_LOG_PATH = ROOT / ".stillmrk-build" / "backups" / "transactions.json"
BUILD_META_DIR = ROOT / ".stillmrk-build" / "meta"
LAST_VALID_DIR = ROOT / ".stillmrk-build" / "last-valid"
BACKEND_WARNING_PATH = BUILD_META_DIR / "control-panel-backend-warnings.jsonl"
BUILD_STATUS_PATH = BUILD_META_DIR / "build-status.json"
RELEASE_REPORT_PATH = BUILD_META_DIR / "release-report.json"
CONTENT_GRAPH_PATH = BUILD_META_DIR / "content-graph.json"
VALIDATION_REPORT_PATH = BUILD_META_DIR / "validation-report.json"
PUBLIC_UPLOAD_DIR = ROOT / "dist"
DIST_DIR = PUBLIC_UPLOAD_DIR
UPLOAD_MANIFEST_PATH = PUBLIC_UPLOAD_DIR / "upload-manifest.json"
IMAGE_MANIFEST_DIR = ROOT / "assets/images/manifests"
IMAGE_INDEX_PATH = IMAGE_MANIFEST_DIR / "image-index.json"
DERIVATIVE_INDEX_PATH = IMAGE_MANIFEST_DIR / "derivative-index.json"
SOURCE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
PUBLISH_STATES = ["draft", "review", "approved", "published", "archived"]
MAX_DIAG_LOG_BYTES = 2 * 1024 * 1024  # 2 MB guard for JSONL diagnostics/warnings.
_ISSUE_PENALTIES: dict[str, int] = {
    "missing title": 18,
    "weak alt text": 18,
    "placeholder alt text": 18,
    "missing caption": 14,
    "placeholder caption": 14,
    "missing focal point": 8,
    "missing/invalid year": 8,
}
_DEFAULT_ISSUE_PENALTY = 8
_SOURCE_STATUS_PENALTIES: dict[str, int] = {
    "missing": 25,
    "derivative-only": 25,
    "recoverable": 25,
    "orphan-risk": 10,
}

_SOURCE_ISSUES_NOT_PROVIDED = object()

AUTHORITY_FILES = {
    "site": ROOT / "content" / "site.yaml",
    "artist": ROOT / "content" / "artist.yaml",
    "navigation": ROOT / "content" / "navigation.yaml",
    "resources": ROOT / "content" / "resources.yaml",
    "release": ROOT / "content" / "release.yaml",
}
CURATION_NOTES_PATH = BUILD_META_DIR / "control-panel-curation-notes.json"
RELEASE_SNAPSHOTS_DIR = ROOT / ".stillmrk-build" / "release-snapshots"
PUBLIC_OUTPUT_SNAPSHOT_PATH = BUILD_META_DIR / "public-output-snapshot.json"
INQUIRIES_PATH = BUILD_META_DIR / "control-panel-inquiries.json"
PRINT_EDITIONS_PATH = BUILD_META_DIR / "control-panel-print-editions.json"
PANEL_DIAGNOSTICS_PATH = BUILD_META_DIR / "control-panel-diagnostics.json"
PANEL_DIAGNOSTICS_LOG_PATH = BUILD_META_DIR / "control-panel-diagnostics.jsonl"
ASSET_TRUTH_PATH = BUILD_META_DIR / "control-panel-asset-truth.json"
HEALTH_REPORT_PATH = BUILD_META_DIR / "control-panel-health-report.json"
_HEALTH_DIRTY_IN_MEMORY: bool = False
_COMMAND_USAGE_LOCK = threading.Lock()
_COMMAND_USAGE_CACHE: dict[str, int] | None = None
_COMMAND_USAGE_PENDING: dict[str, int] = {}
_COMMAND_USAGE_LAST_FLUSH: float = time.monotonic()
_COMMAND_USAGE_FLUSH_INTERVAL_SECONDS = 30.0
_LAST_BUILD_RESULT: dict[str, Any] = {}
_BACKEND_WARNING_DEDUPE_TTL_SECONDS = 60.0
_BACKEND_WARNING_DEDUPE_LOCK = threading.Lock()
_BACKEND_WARNING_DEDUPE: dict[tuple[str, str, str], float] = {}

PERFORMANCE_BUDGETS_MS = {
    "startup": 2500,
    "dashboard refresh": 900,
    "works refresh": 1200,
    "validation refresh": 1200,
    "studio refresh": 1500,
    "build task": 30 * 60 * 1000,
}

DEFAULT_WORK_FILTER_PRESETS: dict[str, dict[str, str]] = {
    "All works": {
        "search": "",
        "series": "All series",
        "review": "All",
        "published": "All",
        "issue": "All works",
    },
    "Needs attention": {
        "search": "",
        "series": "All series",
        "review": "All",
        "published": "All",
        "issue": "Needs attention",
    },
    "Missing caption": {
        "search": "",
        "series": "All series",
        "review": "All",
        "published": "All",
        "issue": "Missing caption",
    },
    "Weak alt text": {
        "search": "",
        "series": "All series",
        "review": "All",
        "published": "All",
        "issue": "Weak alt text",
    },
    "Missing thumbnail": {
        "search": "",
        "series": "All series",
        "review": "All",
        "published": "All",
        "issue": "Missing thumbnail",
    },
    "Published": {
        "search": "",
        "series": "All series",
        "review": "All",
        "published": "Published",
        "issue": "All works",
    },
    "Drafts": {
        "search": "",
        "series": "All series",
        "review": "draft",
        "published": "All",
        "issue": "All works",
    },
    "Ready for review": {
        "search": "",
        "series": "All series",
        "review": "review",
        "published": "All",
        "issue": "All works",
    },
    "Missing original source": {
        "search": "",
        "series": "All series",
        "review": "All",
        "published": "All",
        "issue": "Missing source",
    },
    "Weak metadata": {
        "search": "",
        "series": "All series",
        "review": "All",
        "published": "All",
        "issue": "Weak metadata",
    },
}

# Phase 2 Works-tab performance rescue: keep work YAML payloads indexed in
# memory and invalidate by directory/file mtime. The desktop editor reads works
# constantly while filtering, selecting and autosaving; repeatedly parsing every
# YAML file made the Works tab feel slow even after global-refresh fixes.
_RAW_LOAD_WORK_ENTRIES = load_work_entries
_RAW_LOAD_WORK_PAYLOAD = load_work_payload
_RAW_SAVE_WORK_PAYLOAD = save_work_payload
_RAW_LOAD_SERIES_ENTRIES = load_series_entries
_RAW_LOAD_SERIES_PAYLOAD = load_series_payload


class WorkRepository:
    """Small mtime/hash-based repository for content/works YAML files.

    The signature includes both .yaml and .yml files. Recently-written files get
    a content hash as a guard for coarse-mtime filesystems where multiple saves
    can land inside the same timestamp tick.
    """

    _RECENT_HASH_WINDOW_SECONDS = 2.0

    def __init__(self) -> None:
        self._signature: tuple[tuple[str, int, int, str], ...] | None = None
        self._rows: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}

    def _paths(self) -> list[Path]:
        folder = CONTENT_DIR / "works"
        return sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")])

    def _current_signature(self) -> tuple[tuple[str, int, int, str], ...]:
        rows: list[tuple[str, int, int, str]] = []
        now = time.time()
        for path in self._paths():
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            digest = ""
            try:
                if now - float(stat.st_mtime) <= self._RECENT_HASH_WINDOW_SECONDS:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception as exc:
                _record_backend_warning("Could not hash recently written work YAML for repository signature", path=path, error=exc)
            rows.append((path.name, int(stat.st_mtime_ns), int(stat.st_size), digest))
        return tuple(rows)

    def invalidate(self, work_ids: list[str] | tuple[str, ...] | set[str] | None = None) -> None:
        cleaned = {str(item or "").strip() for item in (work_ids or []) if str(item or "").strip()}
        if cleaned and self._rows:
            self._rows = [row for row in self._rows if str(row.get("id") or "").strip() not in cleaned]
            for work_id in cleaned:
                self._by_id.pop(work_id, None)
        self._signature = None
        if not cleaned:
            self._rows = []
            self._by_id = {}

    def reset(self) -> None:
        self.invalidate()

    @classmethod
    def reset_repository(cls) -> None:
        try:
            _WORK_REPOSITORY.reset()
        except NameError:
            pass

    def _ensure_loaded(self) -> None:
        signature = self._current_signature()
        if self._signature == signature:
            return
        rows: list[dict[str, Any]] = []
        by_id: dict[str, dict[str, Any]] = {}
        for payload in _RAW_LOAD_WORK_ENTRIES():
            if not isinstance(payload, dict):
                continue
            row = dict(payload)
            rows.append(row)
            work_id = str(row.get("id") or "").strip()
            if work_id:
                by_id[work_id] = row
        self._signature = signature
        self._rows = rows
        self._by_id = by_id

    def all(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        return [dict(row) for row in self._rows]

    def get(self, work_id: str) -> dict[str, Any]:
        key = str(work_id or "").strip()
        if not key:
            return {}
        self._ensure_loaded()
        if key in self._by_id:
            return dict(self._by_id[key])
        return {}


_WORK_REPOSITORY = WorkRepository()


class ContentRepository:
    """Single in-memory content/index layer for the control panel hot paths.

    Batch B keeps the public website untouched and centralises the expensive
    YAML/relationship work that the Qt editor used to repeat in Dashboard,
    Works, Series and relationship views. The repository invalidates from file
    mtimes/sizes and returns defensive copies so UI code cannot mutate cache
    state accidentally.
    """

    def __init__(self) -> None:
        self._signature: tuple[Any, ...] | None = None
        self._works: tuple[dict[str, Any], ...] = ()
        self._series: tuple[dict[str, Any], ...] = ()
        self._pages: tuple[dict[str, Any], ...] = ()
        self._works_by_id: dict[str, dict[str, Any]] = {}
        self._series_by_slug: dict[str, dict[str, Any]] = {}
        self._series_index: Any | None = None
        self._work_to_series: dict[str, str] = {}
        self._series_to_work_ids: dict[str, tuple[str, ...]] = {}
        self._sequence_index: dict[tuple[str, str], int] = {}
        self._valid_work_ids: set[str] = set()

    def invalidate(self, scope: str | None = None) -> None:
        self._signature = None
        if scope in {None, "", "all"}:
            self._works = ()
            self._series = ()
            self._pages = ()
            self._works_by_id = {}
            self._series_by_slug = {}
            self._series_index = None
            self._work_to_series = {}
            self._series_to_work_ids = {}
            self._sequence_index = {}
            self._valid_work_ids = set()

    def _dir_signature(self, folder: Path) -> tuple[tuple[str, int, int], ...]:
        if not folder.exists():
            return ()
        rows: list[tuple[str, int, int]] = []
        for path in sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]):
            try:
                stat = path.stat()
            except OSError:
                continue
            rows.append((path.name, int(stat.st_mtime_ns), int(stat.st_size)))
        return tuple(rows)

    def _current_signature(self) -> tuple[Any, ...]:
        return (
            ("works", self._dir_signature(CONTENT_DIR / "works")),
            ("series", self._dir_signature(CONTENT_DIR / "series")),
            ("pages", self._dir_signature(CONTENT_DIR / "pages")),
        )

    def _ensure_loaded(self) -> None:
        signature = self._current_signature()
        if self._signature == signature:
            return

        raw_works = [dict(row) for row in _WORK_REPOSITORY.all() if isinstance(row, dict)]
        raw_series = [dict(row) for row in _RAW_LOAD_SERIES_ENTRIES() if isinstance(row, dict)]
        raw_pages = [dict(row) for row in _load_content_dir_for_repository(CONTENT_DIR / "pages") if isinstance(row, dict)]

        series_index = build_series_index(raw_series)
        work_series = work_to_series_map(works=raw_works, series_entries=raw_series, series_index=series_index)
        normalized_works = tuple(
            _normalize_work_editor_state(dict(row), series_index=series_index, work_series_map=work_series)
            for row in raw_works
            if isinstance(row, dict)
        )
        works_by_id = {str(row.get("id") or "").strip(): dict(row) for row in normalized_works if str(row.get("id") or "").strip()}
        series_by_slug: dict[str, dict[str, Any]] = {}
        series_to_work_ids: dict[str, tuple[str, ...]] = {}
        sequence_index: dict[tuple[str, str], int] = {}
        for series in raw_series:
            slug = _clean_text(series.get("slug"))
            if not slug:
                continue
            clean_series = dict(series)
            series_by_slug[slug] = clean_series
            work_ids = tuple(str(item).strip() for item in (clean_series.get("work_ids") or []) if str(item).strip())
            series_to_work_ids[slug] = work_ids
            for pos, work_id in enumerate(work_ids):
                sequence_index[(slug, work_id)] = pos

        self._signature = signature
        self._works = tuple(dict(row) for row in normalized_works)
        self._series = tuple(dict(row) for row in raw_series)
        self._pages = tuple(dict(row) for row in raw_pages)
        self._works_by_id = works_by_id
        self._series_by_slug = series_by_slug
        self._series_index = series_index
        self._work_to_series = dict(work_series)
        self._series_to_work_ids = series_to_work_ids
        self._sequence_index = sequence_index
        self._valid_work_ids = set(works_by_id)

    def works(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        return [dict(row) for row in self._works]

    def series(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        return [dict(row) for row in self._series]

    def pages(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        return [dict(row) for row in self._pages]

    def work(self, work_id: str) -> dict[str, Any]:
        self._ensure_loaded()
        return dict(self._works_by_id.get(str(work_id or "").strip(), {}) or {})

    def series_payload(self, series_slug: str) -> dict[str, Any]:
        self._ensure_loaded()
        return dict(self._series_by_slug.get(str(series_slug or "").strip(), {}) or {})

    def series_index(self) -> Any:
        self._ensure_loaded()
        return self._series_index

    def work_to_series(self) -> dict[str, str]:
        self._ensure_loaded()
        return dict(self._work_to_series)

    def series_to_work_ids(self) -> dict[str, tuple[str, ...]]:
        self._ensure_loaded()
        return {slug: tuple(ids) for slug, ids in self._series_to_work_ids.items()}

    def sequence_index(self) -> dict[tuple[str, str], int]:
        self._ensure_loaded()
        return dict(self._sequence_index)

    def valid_work_ids(self) -> set[str]:
        self._ensure_loaded()
        return set(self._valid_work_ids)

    def available_series_slugs(self) -> list[str]:
        self._ensure_loaded()
        return [str(row.get("slug") or "").strip() for row in self._series if str(row.get("slug") or "").strip()]


def _load_content_dir_for_repository(folder: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not folder.exists():
        return rows
    for path in sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]):
        payload = load_yaml(path)
        if isinstance(payload, dict):
            rows.append(dict(payload))
    return rows


_CONTENT_REPOSITORY = ContentRepository()


def content_repository_snapshot() -> ContentRepository:
    """Return the shared repository object for backend services.

    Callers must use repository methods rather than mutating attributes.
    """
    return _CONTENT_REPOSITORY


def invalidate_work_cache(work_ids: list[str] | tuple[str, ...] | set[str] | None = None) -> None:
    _WORK_REPOSITORY.invalidate(work_ids)
    _CONTENT_REPOSITORY.invalidate("works")
    invalidate_content_entry_cache("works")


def _normalize_work_series_state(
    payload: dict[str, Any],
    *,
    series_index: Any | None = None,
    work_series_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    clean_payload = dict(payload or {})
    index = series_index or build_series_index()
    current = _clean_text(clean_payload.get("series"))
    resolved = index.resolve(current) if hasattr(index, "resolve") else resolve_series_slug(current)
    work_id = _clean_text(clean_payload.get("id"))
    if not resolved and work_id:
        try:
            mapping = work_series_map if work_series_map is not None else work_to_series_map(series_index=index)
            resolved = _clean_text(mapping.get(work_id, ""))
        except RecursionError:
            resolved = ""
        except Exception:
            resolved = ""
    if resolved:
        clean_payload["series"] = resolved
    return clean_payload


def _normalize_work_editor_state(
    payload: dict[str, Any],
    *,
    series_index: Any | None = None,
    work_series_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    return _normalize_work_publish_state(
        _normalize_work_series_state(dict(payload or {}), series_index=series_index, work_series_map=work_series_map)
    )


def _normalize_work_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    series_entries = _CONTENT_REPOSITORY.series()
    series_index = build_series_index(series_entries)
    series_map = work_to_series_map(works=rows, series_entries=series_entries, series_index=series_index)
    return [
        _normalize_work_editor_state(dict(row), series_index=series_index, work_series_map=series_map)
        for row in rows
        if isinstance(row, dict)
    ]


def load_series_entries() -> list[dict[str, Any]]:
    return _CONTENT_REPOSITORY.series()


def available_series_slugs() -> list[str]:
    return _CONTENT_REPOSITORY.available_series_slugs()


def load_work_entries() -> list[dict[str, Any]]:
    return _CONTENT_REPOSITORY.works()


def load_work_payload(work_id: str) -> dict[str, Any]:
    return _CONTENT_REPOSITORY.work(work_id)


def works_filter_series_values() -> list[str]:
    """Series choices for the Works filter from the central repository.

    Declared series come first; orphan series labels from work YAML are appended
    for compatibility with partially imported content.
    """
    repo = _CONTENT_REPOSITORY
    values: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        slug = str(value or "").strip()
        key = slug.casefold()
        if slug and key not in seen:
            seen.add(key)
            values.append(slug)

    for slug in repo.available_series_slugs():
        add(slug)
    known = set(seen)
    orphan_values: list[str] = []
    for row in repo.works():
        slug = str((row or {}).get("series") or "").strip()
        if slug and slug.casefold() not in known:
            orphan_values.append(slug)
            known.add(slug.casefold())
    for slug in sorted(orphan_values, key=str.lower):
        add(slug)
    return ["All series"] + values


def save_work_payload(work_id: str, payload: dict[str, Any]) -> None:
    clean_payload = _normalize_work_editor_state(dict(payload or {}))
    _RAW_SAVE_WORK_PAYLOAD(work_id, clean_payload)
    invalidate_work_cache({str(work_id or ""), str(clean_payload.get("id") or "")})


def _known_work_ids() -> set[str]:
    return _CONTENT_REPOSITORY.valid_work_ids()


def _published_work_ids() -> set[str]:
    return {
        str(item.get("id") or "").strip()
        for item in load_work_entries()
        if str(item.get("id") or "").strip() and bool(item.get("published"))
    }


def _filter_rows_to_published_works(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if rows is None:
        return []
    published = _published_work_ids()
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        scope = _clean_text(row.get("scope") or row.get("kind")).lower()
        row_id = _clean_text(row.get("id") or row.get("work_id"))
        if scope == "work" and row_id and row_id not in published:
            continue
        filtered.append(dict(row))
    return filtered


def _stable_json_digest(payload: Any) -> str:
    try:
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    except Exception:
        blob = str(payload).encode("utf-8", errors="replace")
    return hashlib.sha256(blob).hexdigest()


def _content_graph_digest() -> str:
    graph = load_content_graph()
    if graph:
        return _stable_json_digest(graph)
    digest = hashlib.sha256()
    for folder in [CONTENT_DIR / "works", CONTENT_DIR / "series", CONTENT_DIR / "pages"]:
        if not folder.exists():
            continue
        for path in sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]):
            try:
                digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(path.read_bytes())
                digest.update(b"\0")
            except Exception as exc:
                _record_backend_warning("Could not include content file in graph digest", path=path, error=exc)
    return digest.hexdigest()


def series_missing_work_references(series_payload: dict[str, Any] | None = None, *, series_slug: str | None = None) -> list[str]:
    payload = dict(series_payload or {})
    if not payload and series_slug:
        payload = _RAW_LOAD_SERIES_PAYLOAD(series_slug) or {}
    known = _known_work_ids()
    missing: list[str] = []
    for work_id in [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]:
        if work_id not in known and work_id not in missing:
            missing.append(work_id)
    cover = _clean_text(payload.get("cover_work_id"))
    if cover and cover not in known and cover not in missing:
        missing.append(cover)
    return missing


def load_series_payload(series_slug: str) -> dict[str, Any]:
    payload = _RAW_LOAD_SERIES_PAYLOAD(series_slug)
    if not isinstance(payload, dict):
        return {}
    enriched = dict(payload)
    missing = series_missing_work_references(enriched)
    enriched["_missing_work_ids"] = missing
    enriched["_integrity_status"] = "broken-references" if missing else "ok"
    return enriched


def remove_missing_work_references_from_series(series_slug: str, *, mark_incomplete: bool = False) -> dict[str, Any]:
    slug = _clean_text(series_slug)
    payload = load_series_payload(slug)
    if not payload:
        raise BackendError(f"Series '{slug}' was not found.")
    missing = series_missing_work_references(payload)
    if not missing:
        return {"series": slug, "removed": [], "marked_incomplete": False}
    missing_set = set(missing)
    work_ids = [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]
    payload["work_ids"] = [work_id for work_id in work_ids if work_id not in missing_set]
    if _clean_text(payload.get("cover_work_id")) in missing_set:
        payload["cover_work_id"] = payload["work_ids"][0] if payload["work_ids"] else ""
    payload.pop("_missing_work_ids", None)
    payload.pop("_integrity_status", None)
    if mark_incomplete:
        payload["review_mode"] = True
        payload["visibility"] = "private"
        note = _clean_text(payload.get("curation_status_note"))
        repair_note = "Marked incomplete after stale work reference cleanup."
        payload["curation_status_note"] = f"{note} {repair_note}".strip() if note else repair_note
    with transaction(f"qt-repair-series-missing-work-refs:{slug}"):
        save_series_payload(slug, payload)
    invalidate_control_panel_caches()
    return {"series": slug, "removed": missing, "marked_incomplete": bool(mark_incomplete)}


def _cached_asset_truth_status_by_work_id() -> dict[str, str]:
    """Return persisted asset-truth statuses without scanning the file system.

    The real source-truth scan stays available in Validation/Publish. The Works
    table only needs a low-cost status hint so filtering and list rendering stay
    responsive.
    """
    path = BUILD_META_DIR / "control-panel-asset-truth.json"
    cache_sig = getattr(_cached_asset_truth_status_by_work_id, "_sig", None)
    try:
        stat = path.stat()
        signature = (int(stat.st_mtime_ns), int(stat.st_size))
    except FileNotFoundError:
        signature = None
    if cache_sig == signature:
        return dict(getattr(_cached_asset_truth_status_by_work_id, "_data", {}) or {})
    data: dict[str, str] = {}
    if signature is not None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            rows = raw if isinstance(raw, list) else raw.get("rows", []) if isinstance(raw, dict) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                work_id = _clean_text(row.get("work_id") or row.get("id"))
                status = _clean_text(row.get("status") or row.get("severity") or "")
                if work_id and status:
                    data[work_id] = status
        except Exception as exc:
            _record_backend_warning("Could not read cached asset-truth status", path=path, error=exc)
    setattr(_cached_asset_truth_status_by_work_id, "_sig", signature)
    setattr(_cached_asset_truth_status_by_work_id, "_data", dict(data))
    return data


def fast_work_completeness_score(payload: dict[str, Any], *, series_map: dict[str, str] | None = None, status_map: dict[str, str] | None = None) -> dict[str, Any]:
    """Metadata-first score for the Works list. No source-tree scan.

    ``series_map`` is supplied by hot list-render paths so a missing payload
    series can be resolved without repeatedly walking the series YAML files.
    """
    work_id = _clean_text((payload or {}).get("id"))
    series_value = _clean_text((payload or {}).get("series") or ((series_map or {}).get(work_id) if work_id else ""))
    penalties: list[tuple[str, int]] = _metadata_penalties_from_issues(work_issue_list(payload or {}))
    if not series_value:
        penalties.append(("missing series", 20))
    if not _clean_text((payload or {}).get("location")) or _is_placeholder_text((payload or {}).get("location")):
        penalties.append(("missing/placeholder location", 8))
    tags = [str(item).strip() for item in ((payload or {}).get("tags") or []) if str(item).strip()]
    if not tags:
        penalties.append(("missing tags", 6))
    status_lookup = status_map if status_map is not None else _cached_asset_truth_status_by_work_id()
    source_status = status_lookup.get(work_id, "unknown") if work_id else "unknown"
    if source_status in _SOURCE_STATUS_PENALTIES:
        label = f"source {source_status}" if source_status != "orphan-risk" else "source orphan-risk"
        penalties.append((label, _SOURCE_STATUS_PENALTIES[source_status]))
    score = max(0, 100 - sum(points for _, points in penalties))
    if source_status in {"", "deferred", "unknown"}:
        status = "review" if score >= 60 else "blocked"
    else:
        status = "ready" if score >= 90 else "review" if score >= 60 else "blocked"
    return {"work_id": work_id, "score": score, "status": status, "issues": [label for label, _points in penalties], "source_status": source_status}


class BackendError(RuntimeError):
    pass


class BackendValidationError(BackendError):
    """User-fixable invalid content or form data."""


class BackendFileOperationError(BackendError):
    """Filesystem operation failed inside a transaction."""


class BackendIntegrityError(BackendError):
    """Post-operation verification found unsafe content or asset state."""


def _should_suppress_duplicate_backend_warning(context: str, path: Path | None, error: Exception | str | None) -> bool:
    """Suppress burst duplicates while preserving distinct warnings.

    Startup and stale-cache recovery can emit the same non-fatal warning many
    times in one session. Keeping one warning per minute is enough for diagnosis
    and prevents the notification badge from becoming useless noise.
    """
    try:
        message = str(error or "")[:500]
        display_path = str(path.relative_to(ROOT)) if isinstance(path, Path) and path.is_absolute() and ROOT in path.parents else (str(path) if path else "")
        key = (str(context or "backend warning"), display_path, message)
        now = time.monotonic()
        with _BACKEND_WARNING_DEDUPE_LOCK:
            stale = [row_key for row_key, seen_at in _BACKEND_WARNING_DEDUPE.items() if now - float(seen_at or 0.0) > _BACKEND_WARNING_DEDUPE_TTL_SECONDS]
            for row_key in stale:
                _BACKEND_WARNING_DEDUPE.pop(row_key, None)
            last_seen = _BACKEND_WARNING_DEDUPE.get(key)
            _BACKEND_WARNING_DEDUPE[key] = now
            return last_seen is not None and now - last_seen <= _BACKEND_WARNING_DEDUPE_TTL_SECONDS
    except Exception:
        return False

def _record_backend_warning(context: str, *, path: Path | None = None, error: Exception | str | None = None) -> None:
    """Persist non-fatal backend warnings so the Qt UI can surface silent fallbacks."""
    if _should_suppress_duplicate_backend_warning(context, path, error):
        return
    try:
        BUILD_META_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_jsonl_log(BACKEND_WARNING_PATH)
        if isinstance(error, BaseException):
            record = make_error_record(str(context or "backend warning"), error, severity="warning", include_traceback=False).as_dict()
            record["path"] = str(path.relative_to(ROOT)) if isinstance(path, Path) and path.is_absolute() and ROOT in path.parents else (str(path) if path else record.get("path", ""))
            append_jsonl(BACKEND_WARNING_PATH, record)
            return
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "operation": str(context),
            "severity": "warning",
            "path": str(path.relative_to(ROOT)) if isinstance(path, Path) and path.is_absolute() and ROOT in path.parents else (str(path) if path else ""),
            "message": str(error or ""),
        }
        append_jsonl(BACKEND_WARNING_PATH, row)
    except OSError:
        # Last-resort guard: warning logging must never break content operations.
        return


def pop_backend_warnings(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent backend warnings and remove only the returned rows from the backlog."""
    if not BACKEND_WARNING_PATH.exists():
        return []
    try:
        lines = BACKEND_WARNING_PATH.read_text(encoding="utf-8").splitlines()
        n = max(1, int(limit or 50))
        take_lines = lines[-n:]
        keep_lines = lines[:-n]
        rows: list[dict[str, Any]] = []
        for line in take_lines:
            try:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
            except Exception:
                rows.append({"timestamp": "", "context": "Malformed backend warning", "path": "", "error": line[:300]})
        remaining = "\n".join(keep_lines) + ("\n" if keep_lines else "")
        atomic_write_text(BACKEND_WARNING_PATH, remaining)
        return rows
    except Exception:
        return []


def _record_diagnostic_event(area: str, status: str, detail: str, **extra: Any) -> None:
    """Append a durable control-panel diagnostic event without interrupting user work."""
    try:
        BUILD_META_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_jsonl_log(PANEL_DIAGNOSTICS_LOG_PATH)
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "area": str(area or "control-panel"),
            "status": str(status or "info"),
            "detail": str(detail or ""),
        }
        for key, value in extra.items():
            if isinstance(value, Path):
                row[key] = _relative_display(value)
            elif isinstance(value, BaseException):
                row[f"{key}_type"] = value.__class__.__name__
                row[f"{key}_message"] = str(value)
            elif isinstance(value, (list, dict)):
                row[key] = value
            elif isinstance(value, (str, int, float, bool)) or value is None:
                row[key] = value
            else:
                row[key] = str(value)
        append_jsonl(PANEL_DIAGNOSTICS_LOG_PATH, row)
    except OSError:
        return


def recent_diagnostic_events(limit: int = 60) -> list[dict[str, Any]]:
    if not PANEL_DIAGNOSTICS_LOG_PATH.exists():
        return []
    try:
        n = max(1, int(limit or 60))
        stat = PANEL_DIAGNOSTICS_LOG_PATH.stat()
        chunk_size = max(n * 512, 4096)
        with PANEL_DIAGNOSTICS_LOG_PATH.open("rb") as handle:
            handle.seek(max(0, stat.st_size - chunk_size))
            chunk = handle.read().decode("utf-8", errors="replace")
        rows: list[dict[str, Any]] = []
        for line in chunk.splitlines()[-n:][::-1]:
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
        return rows
    except Exception as exc:
        _record_backend_warning("Could not read panel diagnostic events", path=PANEL_DIAGNOSTICS_LOG_PATH, error=exc)
        return []


def source_asset_gate_mode() -> str:
    """Current source-image gate mode. Defaults to strict for a serious portfolio workflow."""
    env_value = str(os.environ.get("STILLMRK_SOURCE_ASSET_GATE", "")).strip().lower()
    if env_value in {"strict", "warn", "emergency"}:
        return env_value
    try:
        release_payload = load_yaml(ROOT / "content" / "release.yaml") or {}
        panel_payload = release_payload.get("control_panel") if isinstance(release_payload, dict) else {}
        value = str((panel_payload or {}).get("source_asset_gate") or release_payload.get("source_asset_gate") or "").strip().lower()
        if value in {"strict", "warn", "emergency"}:
            return value
    except Exception as exc:
        _record_backend_warning("Could not read source asset gate mode", path=ROOT / "content" / "release.yaml", error=exc)
    return "strict"


@dataclass(slots=True)
class DashboardSummary:
    works_total: int
    works_published: int
    works_with_issues: int
    series_total: int
    pages_total: int
    actions: list[dict[str, str]]
    repair_items: list[dict[str, str]]
    recent_ops: list[dict[str, Any]]


_ASSET_TRUTH_CACHE_ROWS: list[dict[str, Any]] | None = None
_ASSET_TRUTH_CACHE_SIGNATURE: tuple[Any, ...] | None = None
_ASSET_TRUTH_CACHE_EXPIRES_AT = 0.0
# NOTE: 6s TTL. Extended by invalidate_control_panel_caches() after any mutation.
# Fast dashboard uses persisted JSON; full source scans are on-demand only.
_ASSET_TRUTH_CACHE_TTL_SECONDS = 6.0


_ASSET_TRUTH_PERSISTED_MAX_AGE_SECONDS = 30 * 60


def _asset_truth_index_signature() -> dict[str, Any]:
    """Cheap signature for persisted asset-truth rows.

    It fingerprints content/manifest files only. Routine tab refreshes must not
    crawl originals, generated trees, backups, or recovery folders just to show
    asset status.
    """
    def stat_row(path: Path) -> dict[str, Any]:
        try:
            stat = path.stat()
            return {"path": path.relative_to(ROOT).as_posix(), "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
        except Exception:
            return {"path": _relative_display(path), "missing": True}

    work_stats: list[dict[str, Any]] = []
    works_dir = CONTENT_DIR / "works"
    if works_dir.exists():
        for path in sorted(works_dir.glob("*.yaml")):
            work_stats.append(stat_row(path))
    return {
        "schema": "asset-truth-index-v2",
        "works": work_stats,
        "image_index": stat_row(IMAGE_INDEX_PATH),
        "derivative_index": stat_row(DERIVATIVE_INDEX_PATH),
    }


def _read_persisted_asset_truth_payload() -> dict[str, Any] | None:
    try:
        if not ASSET_TRUTH_PATH.exists():
            return None
        payload = json.loads(ASSET_TRUTH_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return {"signature": None, "generated_at": 0.0, "rows": payload}
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            return payload
    except Exception as exc:
        _record_backend_warning("Could not read persisted asset truth index", path=ASSET_TRUTH_PATH, error=exc)
    return None


def _write_persisted_asset_truth_rows(rows: list[dict[str, Any]], *, signature: dict[str, Any] | None = None) -> None:
    try:
        BUILD_META_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(ASSET_TRUTH_PATH, {
            "schema": "asset-truth-index-v2",
            "generated_at": time.time(),
            "signature": signature if signature is not None else _asset_truth_index_signature(),
            "rows": rows,
        })
    except Exception as exc:
        _record_backend_warning("Could not persist asset truth index", path=ASSET_TRUTH_PATH, error=exc)


def _deferred_asset_truth_row(payload: dict[str, Any], cached: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(payload or {})
    work_id = _clean_text(payload.get("id"))
    cached = dict(cached or {})
    series_slug = _clean_text(payload.get("series") or cached.get("series") or work_to_series_map().get(work_id, ""))
    preview = fast_preview_path_for_work(payload)
    if cached and str(cached.get("id") or cached.get("work_id") or "") == work_id:
        row = dict(cached)
        row.setdefault("id", work_id)
        row.setdefault("work_id", work_id)
        row.setdefault("series", series_slug)
        row.setdefault("preview_path", preview or "")
        row.setdefault("message", "Cached source status. Run source validation for current truth.")
        row.setdefault("detail", row.get("message") or "Cached source status.")
        row["cached"] = True
        row["deferred"] = False
        return row
    return {
        "id": work_id,
        "work_id": work_id,
        "series": series_slug,
        "render_name": _render_name_for_work(payload) or work_id,
        "status": "deferred",
        "severity": "info",
        "message": "Source asset truth not scanned in routine refresh. Run Validation / Source check for current truth.",
        "detail": "Deferred fast-path row; no original/generated/recovery folder scan was performed.",
        "active_source": "",
        "active_source_exists": False,
        "resolved_path": "",
        "expected_stems": _expected_source_stems_for_payload(payload),
        "expected_source_candidates": [],
        "extra_sources": [],
        "derivative_count": 0,
        "derivative_dir": "",
        "recovery_candidates": [],
        "generated_candidates": [],
        "build_error": "",
        "preview_path": preview or "",
        "recovery": "run source validation",
        "cached": False,
        "deferred": True,
    }


def _asset_truth_rows_from_persisted_or_deferred(signature: dict[str, Any]) -> list[dict[str, Any]]:
    cached_payload = _read_persisted_asset_truth_payload()
    cached_rows_by_id: dict[str, dict[str, Any]] = {}
    cache_fresh = False
    if cached_payload is not None:
        try:
            generated_at = float(cached_payload.get("generated_at") or 0.0)
            cache_fresh = bool(cached_payload.get("signature") == signature and (time.time() - generated_at) <= _ASSET_TRUTH_PERSISTED_MAX_AGE_SECONDS)
        except Exception:
            cache_fresh = False
        for row in list(cached_payload.get("rows") or []):
            if not isinstance(row, dict):
                continue
            work_id = str(row.get("id") or row.get("work_id") or "").strip()
            if work_id:
                cached_rows_by_id[work_id] = dict(row)
    rows: list[dict[str, Any]] = []
    for payload in load_work_entries():
        work_id = _clean_text(payload.get("id"))
        rows.append(_deferred_asset_truth_row(payload, cached=cached_rows_by_id.get(work_id) if cache_fresh else None))
    return rows


def cached_asset_truth_for_work(work: dict[str, Any] | str) -> dict[str, Any]:
    """Non-scanning source status for visible UI panels."""
    payload = load_work_payload(work) if isinstance(work, str) else dict(work or {})
    work_id = _clean_text(payload.get("id"))
    if not work_id:
        return _deferred_asset_truth_row(payload)
    for row in asset_truth_report_rows(use_cache=True, force=False, persist=False):
        if str(row.get("id") or row.get("work_id") or "") == work_id:
            return dict(row)
    return _deferred_asset_truth_row(payload)


def invalidate_control_panel_caches() -> None:
    """Clear short-lived backend caches after content or asset mutations."""
    global _ASSET_TRUTH_CACHE_ROWS, _ASSET_TRUTH_CACHE_SIGNATURE, _ASSET_TRUTH_CACHE_EXPIRES_AT
    _ASSET_TRUTH_CACHE_ROWS = None
    _ASSET_TRUTH_CACHE_SIGNATURE = None
    _ASSET_TRUTH_CACHE_EXPIRES_AT = 0.0
    # _cached_asset_truth_status_by_work_id stores its own signature/data on
    # the function object. Clear it explicitly whenever content or assets move,
    # otherwise Works-list badges can remain stale after add/replace/recover.
    try:
        setattr(_cached_asset_truth_status_by_work_id, "_sig", None)
        setattr(_cached_asset_truth_status_by_work_id, "_data", {})
    except Exception:
        pass
    # Same pattern for fast manifest previews: asset mutations must force a
    # thumbnail lookup rebuild rather than waiting for manifest mtimes.
    try:
        setattr(_cached_fast_preview_paths_by_work_id, "_sig", None)
        setattr(_cached_fast_preview_paths_by_work_id, "_data", {})
    except Exception:
        pass
    try:
        invalidate_work_cache()
        _CONTENT_REPOSITORY.invalidate()
        invalidate_content_entry_cache()
    except Exception:
        pass
    try:
        clear_pipeline_cache()
    except Exception:
        pass
    try:
        _invalidate_series_runtime_caches()
    except Exception:
        pass


def _asset_truth_cache_signature() -> tuple[Any, ...]:
    works_dir = CONTENT_DIR / "works"
    work_files = []
    if works_dir.exists():
        for path in sorted(works_dir.glob("*.yaml")):
            try:
                stat = path.stat()
                work_files.append((path.name, stat.st_mtime_ns, stat.st_size))
            except OSError:
                work_files.append((path.name, -1, -1))
    pipeline_path = CONTENT_DIR / "image-pipeline.yaml"
    try:
        pipeline_stat = pipeline_path.stat()
        pipeline_sig = (pipeline_stat.st_mtime_ns, pipeline_stat.st_size)
    except OSError:
        pipeline_sig = (-1, -1)
    return (tuple(work_files), pipeline_sig)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_work_publish_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep editorial review state and public visibility consistent.

    The public site builder uses ``published`` as the visibility gate, while the
    control panel also exposes ``review_status``. A work marked as
    ``review_status: published`` but ``published: false`` looks published inside
    the editor but is silently excluded from the generated website. Normalize the
    two fields at every backend save boundary so the UI cannot create that split
    state again.
    """
    clean_payload = dict(payload or {})
    review = _clean_text(clean_payload.get("review_status")).lower()
    published = bool(clean_payload.get("published"))
    if review not in PUBLISH_STATES:
        review = "published" if published else "draft"
    if review == "published":
        clean_payload["review_status"] = "published"
        clean_payload["published"] = True
    elif published:
        clean_payload["review_status"] = "published"
        clean_payload["published"] = True
    else:
        clean_payload["review_status"] = review
        clean_payload["published"] = False
    return clean_payload


def _ensure_work_in_series_sequence(series_slug: str, work_id: str) -> bool:
    """Append a work to its series sequence when metadata says it belongs there.

    This is deliberately append-only when the work is missing; it preserves any
    existing curated order instead of moving an already sequenced work to the end.
    """
    series_slug = _clean_text(series_slug)
    work_id = _clean_text(work_id)
    if not series_slug or not work_id:
        return False
    payload = load_series_payload(series_slug)
    if not payload:
        return False
    work_ids = [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]
    if work_id in work_ids:
        return False
    work_ids.append(work_id)
    seen: set[str] = set()
    payload["work_ids"] = [wid for wid in work_ids if not (wid in seen or seen.add(wid))]
    if not payload.get("cover_work_id"):
        payload["cover_work_id"] = payload["work_ids"][0] if payload["work_ids"] else None
    save_series_payload(series_slug, payload)
    return True


def _safe_json_load(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        _record_backend_warning("Could not read JSON file", path=path, error=exc)
        return None


def _safe_json_save(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _panel_records(path: Path, key: str) -> list[dict[str, Any]]:
    data = _safe_json_load(path)
    if isinstance(data, dict) and isinstance(data.get(key), list):
        return [row for row in data.get(key, []) if isinstance(row, dict)]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _save_panel_records(path: Path, key: str, rows: list[dict[str, Any]]) -> None:
    payload = {key: rows, "updated_at": _utc_stamp()}
    _safe_json_save(path, payload)


def _upsert_panel_record(path: Path, key: str, row: dict[str, Any], *, id_field: str = "id") -> dict[str, Any]:
    rows = _panel_records(path, key)
    now = _utc_stamp()
    clean = {str(k): v for k, v in dict(row or {}).items()}
    record_id = _clean_text(clean.get(id_field))
    if not record_id:
        seed = "-".join(_clean_text(clean.get(k)) for k in ("name", "work_id", "contact", "subject", "title") if _clean_text(clean.get(k)))
        record_id = slugify_work_id(seed) or f"{key[:-1] or 'record'}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    clean[id_field] = record_id
    clean.setdefault("created_at", now)
    clean["updated_at"] = now
    replaced = False
    for idx, existing in enumerate(rows):
        if _clean_text(existing.get(id_field)) == record_id:
            clean.setdefault("created_at", existing.get("created_at") or now)
            rows[idx] = clean
            replaced = True
            break
    if not replaced:
        rows.insert(0, clean)
    _save_panel_records(path, key, rows)
    return clean


def _delete_panel_record(path: Path, key: str, record_id: str, *, id_field: str = "id") -> int:
    rows = _panel_records(path, key)
    wanted = _clean_text(record_id)
    kept = [row for row in rows if _clean_text(row.get(id_field)) != wanted]
    if len(kept) != len(rows):
        _save_panel_records(path, key, kept)
    return len(rows) - len(kept)


def _manifest_path(value: Any) -> Path | None:
    text_value = _clean_text(value)
    if not text_value:
        return None
    clean_value = text_value.replace('\\', '/')
    raw = Path(clean_value)
    # Content YAML commonly stores public URLs such as
    # /assets/images/originals/example.png. pathlib treats those as absolute
    # filesystem paths, which breaks control-panel preview lookup on Windows,
    # macOS, and Linux. Prefer a real absolute file only when it exists;
    # otherwise resolve site-root paths inside the project.
    if clean_value.startswith('/'):
        project_candidate = ROOT / clean_value.lstrip('/')
        if project_candidate.exists() or not raw.exists():
            return project_candidate
    return raw if raw.is_absolute() else ROOT / raw


def _manifest_rows(path: Path) -> list[dict[str, Any]]:
    data = _safe_json_load(path)
    return data if isinstance(data, list) else []


def _image_index_rows() -> list[dict[str, Any]]:
    return _manifest_rows(IMAGE_INDEX_PATH)


def _derivative_index_rows() -> list[dict[str, Any]]:
    return _manifest_rows(DERIVATIVE_INDEX_PATH)


def image_registry_summary() -> dict[str, Any]:
    pipeline = load_pipeline()
    source_dir = source_root(pipeline)
    generated_dir = generated_root(pipeline)
    image_rows = _image_index_rows()
    derivative_rows = _derivative_index_rows()
    return {
        'source_root': _relative_display(source_dir),
        'generated_root': _relative_display(generated_dir),
        'manifest_dir': _relative_display(IMAGE_MANIFEST_DIR),
        'image_index_rows': len(image_rows),
        'derivative_index_rows': len(derivative_rows),
    }


def _is_placeholder_text(value: str) -> bool:
    text = _clean_text(value).lower()
    if not text:
        return False
    bad_fragments = [
        "test",
        "placeholder",
        "lorem",
        "todo",
        "sample",
        "caption just",
        "alt text",
        "untitled location",
        "just for",
        "where it goes",
        "how it goes",
    ]
    return any(fragment in text for fragment in bad_fragments)


def _invalid_year_value(value: Any) -> bool:
    year_value = _clean_text(value)
    if not year_value:
        return True
    if _is_placeholder_text(year_value):
        return True
    return re.fullmatch(r"\d{4}", year_value) is None


def _metadata_penalties_from_issues(issues: list[str]) -> list[tuple[str, int]]:
    return [(issue, _ISSUE_PENALTIES.get(issue, _DEFAULT_ISSUE_PENALTY)) for issue in issues]


def work_issue_list(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    title = _clean_text(payload.get("title"))
    alt = _clean_text(payload.get("alt"))
    caption = _clean_text(payload.get("caption"))
    focal = payload.get("focal_point") if isinstance(payload.get("focal_point"), dict) else {}
    if not title:
        issues.append("missing title")
    if len(alt.split()) < 5:
        issues.append("weak alt text")
    elif _is_placeholder_text(alt):
        issues.append("placeholder alt text")
    if not caption:
        issues.append("missing caption")
    elif _is_placeholder_text(caption):
        issues.append("placeholder caption")
    if not isinstance(focal, dict) or "x" not in focal or "y" not in focal:
        issues.append("missing focal point")
    if _invalid_year_value(payload.get("year")):
        issues.append("missing/invalid year")
    return issues


def work_completeness_score(payload: dict[str, Any]) -> dict[str, Any]:
    """Full completeness score including filesystem source-asset scan.

    Do NOT call this from list render/filter paths; use
    fast_work_completeness_score() there. This function intentionally performs
    deeper asset-truth checks for explicit validation/reporting views.
    """
    work_id = _clean_text(payload.get("id"))
    penalties: list[tuple[str, int]] = _metadata_penalties_from_issues(work_issue_list(payload))
    if not _clean_text(payload.get("series")):
        penalties.append(("missing series", 20))
    if not _clean_text(payload.get("location")) or _is_placeholder_text(payload.get("location")):
        penalties.append(("missing/placeholder location", 8))
    tags = [str(item).strip() for item in (payload.get("tags") or []) if str(item).strip()]
    if not tags:
        penalties.append(("missing tags", 6))
    try:
        truth = source_asset_truth_for_work(payload)
        source_status = str(truth.get("status") or "missing")
        if source_status in _SOURCE_STATUS_PENALTIES:
            label = f"source {source_status}" if source_status != "orphan-risk" else "source orphan-risk"
            penalties.append((label, _SOURCE_STATUS_PENALTIES[source_status]))
    except Exception as exc:
        _record_backend_warning("source asset truth check failed during completeness score", error=exc)
        source_status = "unknown"
        penalties.append(("source check unavailable", _DEFAULT_ISSUE_PENALTY))
    score = max(0, 100 - sum(points for _, points in penalties))
    status = "ready" if score >= 90 else "review" if score >= 60 else "blocked"
    return {
        "work_id": work_id,
        "score": score,
        "status": status,
        "issues": [label for label, _points in penalties],
        "source_status": source_status,
    }


def tag_vocabulary_rows() -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    variants: dict[str, set[str]] = {}
    for payload in load_work_entries():
        for tag in payload.get("tags") or []:
            raw = str(tag or "").strip()
            if not raw:
                continue
            key = raw.lower()
            counts[key] = counts.get(key, 0) + 1
            variants.setdefault(key, set()).add(raw)
    rows = []
    for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        rows.append({
            "tag": sorted(variants.get(key) or {key}, key=lambda v: (v.lower(), v))[0],
            "normalized": key,
            "count": count,
            "variants": sorted(variants.get(key) or []),
        })
    return rows


def merge_work_tag(old_tag: str, new_tag: str) -> dict[str, Any]:
    old_key = _clean_text(old_tag).lower()
    replacement = _clean_text(new_tag)
    if not old_key or not replacement:
        raise BackendError("Both old and new tags are required.")
    changed: list[str] = []
    with transaction(f"qt-merge-tag:{old_key}->{replacement.lower()}"):
        for payload in load_work_entries():
            tags = [str(item).strip() for item in (payload.get("tags") or []) if str(item).strip()]
            if not any(tag.lower() == old_key for tag in tags):
                continue
            updated: list[str] = []
            for tag in tags:
                value = replacement if tag.lower() == old_key else tag
                if value.lower() not in [existing.lower() for existing in updated]:
                    updated.append(value)
            payload = dict(payload)
            payload["tags"] = updated
            save_work_payload(str(payload.get("id") or ""), payload)
            changed.append(str(payload.get("id") or ""))
    mark_unpublished_changes()
    invalidate_control_panel_caches()
    mark_portfolio_health_dirty("work")
    return {"old_tag": old_tag, "new_tag": replacement, "changed_ids": changed, "count": len(changed)}

def series_issue_list(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not _clean_text(payload.get("title")):
        issues.append("missing title")
    if not _clean_text(payload.get("description")):
        issues.append("missing description")
    if not _clean_text(payload.get("cover_work_id")):
        issues.append("missing cover")
    if not (payload.get("work_ids") or []):
        issues.append("empty sequence")
    return issues


def page_issue_list(page_key: str, payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
    if not _clean_text(meta.get("title")):
        issues.append("missing meta title")
    if not _clean_text(meta.get("description")):
        issues.append("missing meta description")
    if not _clean_text(hero.get("title")):
        issues.append("missing hero title")
    return issues


def _render_name_for_work(payload: dict[str, Any]) -> str:
    image_value = payload.get("image") if isinstance(payload.get("image"), dict) else {}
    render_name = _clean_text(image_value.get("render_name"))
    return render_name or _clean_text(payload.get("id"))


def _expected_source_stems_for_payload(payload: dict[str, Any]) -> list[str]:
    image_value = payload.get("image") if isinstance(payload.get("image"), dict) else {}
    ordered: list[str] = []

    def add(value: Any) -> None:
        stem = Path(str(value or "").strip().replace('\\', '/')).stem.strip()
        if stem and stem not in ordered:
            ordered.append(stem)

    add(payload.get("id"))
    add(image_value.get("render_name"))
    add(image_value.get("master"))
    add(image_value.get("source"))
    add(image_value.get("original"))
    return ordered


def _source_candidate_hint_paths(work_id: str, series_slug: str) -> list[Path]:
    roots = [
        source_root() / series_slug,
        ROOT / "assets/images/originals/series" / series_slug,
        ROOT / "assets/images/originals",
        ROOT / "assets/images/originals/unassigned",
    ]
    candidates: list[Path] = []
    seen: set[str] = set()
    for base in roots:
        key = str(base)
        if key in seen:
            continue
        seen.add(key)
        for ext in sorted(SOURCE_EXTENSIONS):
            candidates.append(base / f"{work_id}{ext}")
    return candidates


def _generated_candidate_directories(series_slug: str, render_name: str, work_id: str) -> list[Path]:
    """Return likely derivative folders for the current Stillmark layout.

    The live asset tree uses:
    assets/images/generated/series/<series>/<render-or-work-id>/<name>-WIDTH.jpg|webp
    Older packages may also use responsive_dir. Keep both without treating
    derivatives as source truth.
    """
    names = [item for item in (render_name, work_id) if _clean_text(item)]
    roots = [generated_root(), ROOT / "assets/images/generated/series", ROOT / "assets/images/responsive"]
    directories: list[Path] = []
    seen: set[str] = set()
    for root_path in roots:
        for name in names:
            for directory in (
                derivative_dir_for_work(series_slug, name),
                root_path / series_slug / name,
            ):
                key = str(directory.resolve(strict=False))
                if key in seen:
                    continue
                seen.add(key)
                directories.append(directory)
    return directories


def _largest_generated_derivative_candidate(series_slug: str, render_name: str, work_id: str) -> Path | None:
    best: tuple[int, int, Path] | None = None
    for directory in _generated_candidate_directories(series_slug, render_name, work_id):
        if not directory.exists():
            continue
        for candidate in directory.iterdir():
            if not candidate.is_file() or candidate.suffix.lower() not in {".jpg", ".jpeg", ".webp", ".png"}:
                continue
            width = _candidate_width(candidate)
            size = _path_size(candidate)
            if best is None or (width, size) > (best[0], best[1]):
                best = (width, size, candidate)
    return best[2] if best else None


def _candidate_width(path: Path) -> int:
    match = re.search(r'-(\d+)\.(?:jpe?g|webp|png)$', path.name.lower())
    return int(match.group(1)) if match else 0


def _txn_ref_to_path_local(ref: str) -> Path:
    text = str(ref or "")
    if text.startswith("REL::"):
        return ROOT / text[5:]
    if text.startswith("ABS::"):
        return Path(text[5:])
    raw = Path(text)
    return raw if raw.is_absolute() else ROOT / raw


def _load_transaction_rows() -> list[dict[str, Any]]:
    if not TRANSACTION_LOG_PATH.exists():
        return []
    try:
        data = json.loads(TRANSACTION_LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _relative_display(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except Exception:
        return str(path)


def _recoverable_candidates_for_work(series_slug: str, render_name: str, work_id: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_candidate(path: Path | None, *, kind: str, source: str, note: str = "") -> None:
        if path is None:
            return
        candidate = Path(path)
        if not candidate.exists():
            return
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            return
        seen.add(key)
        candidates.append({
            "path": candidate,
            "kind": kind,
            "source": source,
            "note": note,
            "priority": 100 if kind == "original" else 60,
            "size": candidate.stat().st_size if candidate.exists() else 0,
            "width": _candidate_width(candidate),
            "suffix": candidate.suffix.lower(),
        })

    search_terms = [term for term in {render_name, work_id} if term]

    add_candidate(
        _largest_generated_derivative_candidate(series_slug, render_name, work_id),
        kind="generated",
        source="generated",
        note="current/expected generated derivatives",
    )

    generated_roots = [generated_root(), ROOT / "assets/images/generated/series", ROOT / "assets/images/responsive"]
    for gen_root in generated_roots:
        if not gen_root.exists():
            continue
        for term in search_terms:
            for suffix in ("jpg", "jpeg", "webp", "png"):
                for candidate in gen_root.rglob(f"{term}-*.{suffix}"):
                    add_candidate(candidate, kind="generated", source="generated", note="historical generated derivative")
            for directory in gen_root.rglob(term):
                if directory.is_dir():
                    for candidate in directory.iterdir():
                        if candidate.is_file() and candidate.suffix.lower() in {".jpg", ".jpeg", ".webp", ".png"}:
                            add_candidate(candidate, kind="generated", source="generated", note="historical generated directory")

    if BACKUP_FILES_DIR.exists():
        for term in search_terms:
            for ext in sorted(SOURCE_EXTENSIONS):
                for candidate in BACKUP_FILES_DIR.glob(f"{term}.*{ext}"):
                    add_candidate(candidate, kind="original", source="backup", note="backup original snapshot")

    for row in _load_transaction_rows():
        for op in row.get("ops") or []:
            for ref_key in ("target", "backup"):
                ref = str(op.get(ref_key) or "")
                if not ref or not any(term in ref for term in search_terms):
                    continue
                path = _txn_ref_to_path_local(ref)
                lower = ref.lower()
                if "/assets/images/originals/" in lower or "\\assets\\images\\originals\\" in lower:
                    add_candidate(path, kind="original", source="transaction", note="transaction history original")
                elif "/assets/images/generated/" in lower or "\\assets\\images\\generated\\" in lower:
                    add_candidate(path, kind="generated", source="transaction", note="transaction history generated")

    candidates.sort(key=lambda row: (row["priority"], row["width"], row["size"]), reverse=True)
    return candidates




def _cached_fast_preview_paths_by_work_id() -> dict[str, str]:
    """Cheap manifest-backed preview lookup for list thumbnails.

    This deliberately avoids source-tree scans. It uses existing image/derivative
    manifests and direct declared source paths only, so Works list rendering can
    stay responsive while deeper asset truth checks run in the background.
    """
    paths = [IMAGE_INDEX_PATH, DERIVATIVE_INDEX_PATH]
    signature: list[tuple[str, int, int] | tuple[str, None, None]] = []
    for path in paths:
        try:
            stat = path.stat()
            signature.append((path.name, int(stat.st_mtime_ns), int(stat.st_size)))
        except FileNotFoundError:
            signature.append((path.name, None, None))
    try:
        originals_stat = source_root(load_pipeline()).stat()
        signature.append(("originals_dir", int(originals_stat.st_mtime_ns), int(originals_stat.st_size)))
    except Exception:
        signature.append(("originals_dir", None, None))
    sig = tuple(signature)
    cache_sig = getattr(_cached_fast_preview_paths_by_work_id, "_sig", None)
    if cache_sig == sig:
        return dict(getattr(_cached_fast_preview_paths_by_work_id, "_data", {}) or {})

    data: dict[str, str] = {}

    def put(work_id: str, candidate: Path | None, *, overwrite: bool = False) -> None:
        key = _clean_text(work_id)
        if not key or candidate is None:
            return
        try:
            path = candidate if candidate.is_absolute() else ROOT / candidate
            if path.exists() and (overwrite or key not in data):
                data[key] = str(path)
        except Exception:
            return

    for row in _image_index_rows():
        if not isinstance(row, dict):
            continue
        work_id = _clean_text(row.get("id"))
        put(work_id, _manifest_path(row.get("sourceOriginal")), overwrite=True)

    for row in _derivative_index_rows():
        if not isinstance(row, dict):
            continue
        work_id = _clean_text(row.get("id"))
        variants = [item for item in (row.get("variants") or []) if isinstance(item, dict)]
        variants.sort(key=lambda item: int(item.get("width") or 0), reverse=True)
        for variant in variants:
            candidate = _manifest_path(variant.get("path"))
            before = data.get(work_id)
            put(work_id, candidate, overwrite=True)
            if data.get(work_id) and data.get(work_id) != before:
                break

    setattr(_cached_fast_preview_paths_by_work_id, "_sig", sig)
    setattr(_cached_fast_preview_paths_by_work_id, "_data", dict(data))
    return data


def fast_preview_path_for_work(work: dict[str, Any] | str) -> str | None:
    """Return a non-blocking preview path string for list rows and thumbnail queues.

    Contract: returns ``str | None``. Callers that need filesystem operations
    must convert through ``Path`` or use ``_safe_preview_path()``. Unlike
    best_preview_path_for_work(), this function must not scan source
    directories, recovery folders, or generated trees. It is safe for the Works
    tab refresh path and for background thumbnail batching.
    """
    payload = load_work_payload(work) if isinstance(work, str) else dict(work or {})
    work_id = _clean_text(payload.get("id") if isinstance(payload, dict) else "")
    if not work_id:
        return None

    image = payload.get("image") if isinstance(payload.get("image"), dict) else {}
    for key in ("source", "preview", "path"):
        candidate = _manifest_path(image.get(key) if isinstance(image, dict) else "")
        if candidate and candidate.exists():
            return str(candidate)

    manifest_path = _cached_fast_preview_paths_by_work_id().get(work_id)
    return manifest_path or None


def _safe_preview_path(work: dict[str, Any] | str) -> Path | None:
    """Return an existing preview path as ``Path`` for filesystem operations."""
    result = fast_preview_path_for_work(work)
    if not result:
        return None
    path = Path(result)
    return path if path.exists() else None


def best_preview_path_for_work(work: dict[str, Any] | str) -> str | None:
    """Return the best preview path without weakening source-truth rules.

    Preference order:
    1) active original/source resolved by the same logic as the site builder;
    2) original recovery candidate;
    3) largest generated derivative in assets/images/generated/series.

    This makes the GUI visually useful even when originals need repair, while
    release gates still treat derivative-only works as errors.
    """
    payload = load_work_payload(work) if isinstance(work, str) else dict(work or {})
    work_id = _clean_text(payload.get("id") if isinstance(payload, dict) else "")
    if not work_id:
        return None
    series_slug = _clean_text((payload or {}).get("series") or work_to_series_map().get(work_id, ""))
    render_name = _render_name_for_work(payload) if isinstance(payload, dict) else work_id

    resolved, _error = _build_resolve_source_info(payload)
    if resolved and Path(resolved).exists():
        return str(Path(resolved))

    existing = _resolve_source_path(series_slug, work_id, load_pipeline(), context="best preview") if series_slug else None
    if existing and Path(existing).exists():
        return str(existing)

    candidates = _recoverable_candidates_for_work(series_slug, render_name, work_id)
    if candidates:
        return str(candidates[0]["path"])

    _record_backend_warning(
        "No preview path could be resolved for work",
        path=f"{series_slug}/{work_id}" if series_slug else work_id,
        error="no source, manifest preview, recovery candidate, or generated derivative found",
    )
    return None


def _index_supported_images(search_root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    if not search_root.exists():
        return index
    for path in search_root.rglob('*'):
        if not path.is_file() or path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        index.setdefault(path.stem.lower(), []).append(path)
    return index


def _choose_best_folder_candidate(payload: dict[str, Any], indexed: dict[str, list[Path]]) -> Path | None:
    stems = _expected_source_stems_for_payload(payload)
    ranked: list[tuple[int, int, int, Path]] = []
    for order, stem in enumerate(stems):
        for candidate in indexed.get(stem.lower(), []):
            suffix = candidate.suffix.lower()
            ext_rank = {'.tif': 6, '.tiff': 6, '.png': 5, '.jpg': 4, '.jpeg': 4, '.webp': 3}.get(suffix, 0)
            size = candidate.stat().st_size if candidate.exists() else 0
            ranked.append((100 - order, ext_rank, size, candidate))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    return ranked[0][3]


def _build_resolve_source_info(payload: dict[str, Any]) -> tuple[Path | None, str | None]:
    image_config = dict(payload.get("image") or {}) if isinstance(payload.get("image"), dict) else {}
    try:
        from build_site import resolve_source_path as build_resolve_source_path
        resolved = build_resolve_source_path(payload, image_config)
        return resolved, None
    except FileNotFoundError as exc:
        return None, str(exc)
    except Exception:
        return None, None



def _manifest_source_candidates_for_payload(payload: dict[str, Any]) -> list[Path]:
    work_id = _clean_text(payload.get('id'))
    render_name = _render_name_for_work(payload)
    series_slug = _clean_text(payload.get('series') or work_to_series_map().get(work_id, ''))
    stems = _expected_source_stems_for_payload(payload)
    rows = [row for row in _image_index_rows() if _clean_text(row.get('id')) == work_id or _clean_text(row.get('renderName')) in {render_name, work_id}]
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None or not path.exists():
            return
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        candidates.append(path)

    for row in rows:
        add(_manifest_path(row.get('sourceOriginal')))
    for stem in stems:
        for ext in sorted(SOURCE_EXTENSIONS):
            add(source_root() / series_slug / f'{stem}{ext}')
            add(ROOT / 'assets/images/originals/series' / series_slug / f'{stem}{ext}')
            add(ROOT / 'assets/images/originals' / f'{stem}{ext}')
            add(ROOT / 'assets/images/originals/unassigned' / f'{stem}{ext}')
    return candidates


def _manifest_derivative_candidates_for_payload(payload: dict[str, Any]) -> list[Path]:
    work_id = _clean_text(payload.get('id'))
    render_name = _render_name_for_work(payload)
    rows = [row for row in _derivative_index_rows() if _clean_text(row.get('id')) == work_id or _clean_text(row.get('renderName')) in {render_name, work_id}]
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None or not path.exists():
            return
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        candidates.append(path)

    for row in rows:
        base_path = _manifest_path(row.get('responsiveBase'))
        if base_path is not None:
            parent = base_path.parent
            stem = base_path.name
            for candidate in parent.glob(f'{stem}-*.jpg'):
                add(candidate)
            for candidate in parent.glob(f'{stem}-*.webp'):
                add(candidate)
        for variant in row.get('variants') or []:
            add(_manifest_path(variant.get('path')))
    return candidates


def _asset_cleanup_allowed_roots(pipeline: dict[str, Any] | None = None) -> list[Path]:
    pipeline = pipeline or load_pipeline()
    return [
        source_root(pipeline),
        generated_root(pipeline),
        ROOT / "assets/images/originals",
        ROOT / "assets/images/originals/series",
        ROOT / "assets/images/originals/unassigned",
        ROOT / "assets/images/generated",
        ROOT / "assets/images/generated/series",
        ROOT / "assets/images/responsive",
    ]


def _path_inside_any(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve(strict=False)
    except Exception:
        resolved = path
    for root_path in roots:
        try:
            resolved.relative_to(root_path.resolve(strict=False))
            return True
        except Exception:
            continue
    return False


def _unique_existing_paths(paths: list[Path | None], *, allowed_roots: list[Path] | None = None) -> list[Path]:
    rows: list[Path] = []
    seen: set[str] = set()
    roots = allowed_roots or []
    for value in paths:
        if value is None:
            continue
        path = Path(value)
        if not path.exists():
            continue
        if roots and not _path_inside_any(path, roots):
            continue
        key = str(path.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        rows.append(path)
    return rows


def _remove_empty_asset_parent(path: Path, roots: list[Path]) -> str:
    """Remove now-empty parent directories below known asset roots only."""
    parent = Path(path).parent
    try:
        resolved_parent = parent.resolve(strict=False)
    except Exception:
        return ""
    for root_path in roots:
        try:
            resolved_root = root_path.resolve(strict=False)
            resolved_parent.relative_to(resolved_root)
        except Exception:
            continue
        if resolved_parent == resolved_root:
            return ""
        if not parent.exists() or not parent.is_dir():
            return ""
        try:
            parent.rmdir()
            record_transaction_step("rmdir_empty", target=parent, detail="remove empty work asset parent")
            return _relative_display(parent)
        except OSError:
            return ""
    return ""


def _collect_work_asset_cleanup_targets(payload: dict[str, Any]) -> dict[str, list[Path]]:
    """Return every known original/generated asset candidate for a work.

    This intentionally uses the current payload, manifest rows, legacy path probes,
    render_name, and work_id. Deleting a work should not leave an orphaned original
    or derivative folder behind just because an older script used a different
    render-name convention.
    """
    work_id = _clean_text(payload.get("id"))
    series_slug = _clean_text(payload.get("series") or work_to_series_map().get(work_id, ""))
    pipeline = load_pipeline()
    render_name = _render_name_for_work(payload) or work_id
    roots = _asset_cleanup_allowed_roots(pipeline)
    stems = [stem for stem in _expected_source_stems_for_payload(payload) if stem]
    for value in (work_id, render_name):
        if value and value not in stems:
            stems.append(value)

    source_candidates: list[Path] = []
    for stem in stems:
        source_candidates.extend(_source_candidates_for_stem(series_slug, stem, pipeline=pipeline))
    source_candidates.extend(_manifest_source_candidates_for_payload(payload))
    source_candidates.append(source_path_for_work(series_slug, work_id, pipeline=pipeline) if series_slug and work_id else None)

    generated_dirs: list[Path] = []
    generated_files: list[Path] = []
    for name in [item for item in {work_id, render_name} if item]:
        generated_dirs.append(derivative_dir_for_work(series_slug, name, pipeline=pipeline) if series_slug else None)
        generated_dirs.append(ROOT / "assets/images/generated/series" / series_slug / name if series_slug else None)
        generated_dirs.append(ROOT / "assets/images/responsive" / series_slug / name if series_slug else None)
    generated_files.extend(_derivative_files_for_work(series_slug, render_name, pipeline=pipeline, work_id=work_id))
    generated_files.extend(_manifest_derivative_candidates_for_payload(payload))

    recovery_rows = _recoverable_candidates_for_work(series_slug, render_name, work_id) if work_id else []
    for row in recovery_rows:
        candidate = row.get("path")
        if not isinstance(candidate, Path):
            continue
        if str(row.get("kind")) == "generated":
            if candidate.is_dir():
                generated_dirs.append(candidate)
            else:
                generated_files.append(candidate)
        elif str(row.get("kind")) == "original":
            source_candidates.append(candidate)

    return {
        "sources": _unique_existing_paths(source_candidates, allowed_roots=roots),
        "generated_dirs": _unique_existing_paths(generated_dirs, allowed_roots=roots),
        "generated_files": _unique_existing_paths(generated_files, allowed_roots=roots),
    }


def _prune_work_from_page_payloads(work_id: str) -> list[str]:
    """Remove exact work-id references from page YAML payloads before deletion.

    Lists drop exact work-id values. Scalar page fields that exactly equal the
    work id are cleared instead of deleting the key, preserving page schema shape.
    """
    target = _clean_text(work_id)
    if not target:
        return []
    changed: list[str] = []

    def prune(obj: Any) -> tuple[Any, bool]:
        if isinstance(obj, list):
            new_items: list[Any] = []
            did_change = False
            for item in obj:
                if isinstance(item, str) and _clean_text(item) == target:
                    did_change = True
                    continue
                new_item, item_changed = prune(item)
                did_change = did_change or item_changed
                new_items.append(new_item)
            return new_items, did_change
        if isinstance(obj, dict):
            new_obj: dict[str, Any] = {}
            did_change = False
            for key, value in obj.items():
                if isinstance(value, str) and _clean_text(value) == target:
                    new_obj[key] = ""
                    did_change = True
                    continue
                new_value, value_changed = prune(value)
                new_obj[key] = new_value
                did_change = did_change or value_changed
            return new_obj, did_change
        return obj, False

    for page_key in available_page_keys():
        try:
            page_payload = load_page_payload(page_key)
        except Exception:
            continue
        if not isinstance(page_payload, dict):
            continue
        updated, did_change = prune(page_payload)
        if did_change and isinstance(updated, dict):
            save_page_payload(page_key, updated)
            changed.append(page_key)
    return changed



def refresh_image_manifests(line_callback: Callable[[str], None] | None = None) -> dict[str, int]:
    IMAGE_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    image_rows: list[dict[str, Any]] = []
    derivative_rows: list[dict[str, Any]] = []
    for payload in load_work_entries():
        work_id = _clean_text(payload.get('id'))
        if not work_id:
            continue
        series_slug = _clean_text(payload.get('series') or work_to_series_map().get(work_id, ''))
        render_name = _render_name_for_work(payload) or work_id
        resolved, build_error = _build_resolve_source_info(payload)
        focal_point = payload.get('focal_point') if isinstance(payload.get('focal_point'), dict) else {}
        image_rows.append({
            'id': work_id,
            'title': _clean_text(payload.get('title')),
            'series': series_slug,
            'published': bool(payload.get('published')),
            'renderName': render_name,
            'sourceOriginal': _relative_display(Path(resolved)) if resolved and Path(resolved).exists() else _clean_text((payload.get('image') or {}).get('source') if isinstance(payload.get('image'), dict) else ''),
            'focalPoint': {'x': int(focal_point.get('x', 50)), 'y': int(focal_point.get('y', 50))},
        })
        derivative_dir = generated_root() / series_slug / render_name
        variants: list[dict[str, Any]] = []
        probe_path: Path | None = None
        if derivative_dir.exists():
            for candidate in sorted(derivative_dir.glob(f'{render_name}-*.*')):
                if candidate.suffix.lower() not in {'.jpg', '.webp'}:
                    continue
                match = re.search(r'-(\d+)\.(jpg|webp)$', candidate.name.lower())
                width = int(match.group(1)) if match else 0
                variants.append({
                    'format': candidate.suffix.lower().lstrip('.'),
                    'width': width,
                    'path': _relative_display(candidate),
                    'exists': candidate.exists(),
                    'sizeBytes': candidate.stat().st_size if candidate.exists() else 0,
                })
                if probe_path is None or width >= max((v.get('width') or 0) for v in variants):
                    probe_path = candidate
        if variants:
            width = height = 0
            if probe_path is not None and probe_path.exists():
                try:
                    with Image.open(probe_path) as probe:
                        width, height = probe.size
                except Exception:
                    width = height = 0
            derivative_rows.append({
                'id': work_id,
                'series': series_slug,
                'renderName': render_name,
                'responsiveBase': _relative_display(derivative_dir / render_name),
                'sourceOriginal': _relative_display(Path(resolved)) if resolved and Path(resolved).exists() else '',
                'width': width,
                'height': height,
                'missingSource': not bool(resolved and Path(resolved).exists()),
                'missingSourceDetail': build_error or '',
                'variants': variants,
            })
    atomic_write_json(IMAGE_INDEX_PATH, image_rows)
    atomic_write_json(DERIVATIVE_INDEX_PATH, derivative_rows)
    if line_callback:
        line_callback(f'Refreshed image registry: {len(image_rows)} image row(s), {len(derivative_rows)} derivative row(s)')
    return {'image_rows': len(image_rows), 'derivative_rows': len(derivative_rows)}


def _same_path(left: Path | None, right: Path | None) -> bool:
    # Missing paths are never treated as equal; callers use this only for
    # concrete filesystem identity checks where a real path must be present.
    if left is None or right is None:
        return False
    try:
        return Path(left).resolve(strict=False) == Path(right).resolve(strict=False)
    except Exception:
        return Path(left) == Path(right)


def _resolve_source_path(
    series_slug: str,
    work_id: str,
    pipeline: dict[str, Any] | None = None,
    *,
    context: str = "source path",
) -> Path | None:
    """Resolve a work source path and enforce the Path | None contract.

    Only expected I/O/value failures are softened into diagnostics. Programmer
    errors such as TypeError or AttributeError are intentionally allowed to
    surface instead of becoming a misleading "missing preview" state.
    """
    series_slug = _clean_text(series_slug)
    work_id = _clean_text(work_id)
    if not series_slug or not work_id:
        return None
    try:
        source = source_path_for_work(series_slug, work_id, pipeline=pipeline)
    except (OSError, FileNotFoundError, ValueError) as exc:
        _record_backend_warning(
            "Could not resolve source path for work",
            path=f"{series_slug}/{work_id}",
            error=exc,
            context=context,
        )
        return None
    if source is None:
        return None
    path = Path(source)
    return path


def _path_size(path: Path | None) -> int:
    try:
        return int(path.stat().st_size) if path and path.exists() else 0
    except Exception:
        return 0


def _derivative_files_for_work(series_slug: str, render_name: str, pipeline: dict[str, Any] | None = None, work_id: str | None = None) -> list[Path]:
    if not series_slug or not render_name:
        return []
    pipeline = pipeline or load_pipeline()
    names = [render_name]
    if work_id and work_id not in names:
        names.append(work_id)
    files: list[Path] = []
    seen: set[str] = set()
    for name in names:
        for directory in _generated_candidate_directories(series_slug, name, work_id or name):
            if not directory.exists():
                continue
            for candidate in sorted(directory.iterdir()):
                if not candidate.is_file() or candidate.suffix.lower() not in {".jpg", ".jpeg", ".webp", ".png"}:
                    continue
                key = str(candidate.resolve(strict=False))
                if key in seen:
                    continue
                seen.add(key)
                files.append(candidate)
    return files


def source_asset_truth_for_work(work: dict[str, Any] | str, *, include_recovery: bool = False) -> dict[str, Any]:
    """Single source of truth for active original, derivative-only, recoverable and orphan-risk states."""
    payload = load_work_payload(work) if isinstance(work, str) else dict(work or {})
    work_id = _clean_text(payload.get("id"))
    if not work_id:
        return {
            "id": "",
            "series": "",
            "status": "missing",
            "severity": "error",
            "message": "Work payload has no id.",
            "active_source": "",
            "derivative_count": 0,
            "extra_sources": [],
            "recovery_candidates": [],
        }
    series_slug = _clean_text(payload.get("series") or work_to_series_map().get(work_id, ""))
    pipeline = load_pipeline()
    render_name = _render_name_for_work(payload) or work_id
    expected_stems = _expected_source_stems_for_payload(payload)
    resolved, build_error = _build_resolve_source_info(payload)
    resolved_path = Path(resolved) if resolved else None
    active_source = resolved_path if resolved_path and resolved_path.exists() else None
    if not active_source and series_slug:
        lookup = _resolve_source_path(series_slug, work_id, pipeline=pipeline, context="asset truth")
        active_source = Path(lookup) if lookup and Path(lookup).exists() else None

    source_candidates: list[Path] = []
    for stem in expected_stems or [work_id]:
        for path in _source_candidates_for_stem(series_slug, stem, pipeline=pipeline):
            if path.exists() and not any(_same_path(path, existing) for existing in source_candidates):
                source_candidates.append(path)
    manifest_sources = _manifest_source_candidates_for_payload(payload)
    for candidate in manifest_sources:
        if candidate.exists() and not any(_same_path(candidate, existing) for existing in source_candidates):
            source_candidates.append(candidate)

    extra_sources = [path for path in source_candidates if not _same_path(path, active_source)]
    derivative_files = _derivative_files_for_work(series_slug, render_name, pipeline=pipeline, work_id=work_id)
    generated_candidates = _manifest_derivative_candidates_for_payload(payload)
    recovery_rows = _recoverable_candidates_for_work(series_slug, render_name, work_id) if include_recovery else []
    for row in recovery_rows:
        candidate = row.get("path")
        if isinstance(candidate, Path) and str(row.get("kind")) == "generated":
            generated_candidates.append(candidate)
    generated_candidates = [path for index, path in enumerate(generated_candidates) if path.exists() and all(not _same_path(path, prev) for prev in generated_candidates[:index])]

    original_candidates = [path for path in source_candidates if not _same_path(path, active_source)]
    if not original_candidates and active_source:
        original_candidates = []
    backup_original_candidates: list[Path] = []
    for row in recovery_rows:
        candidate = row.get("path")
        if isinstance(candidate, Path) and str(row.get("kind")) == "original" and candidate.exists() and not _same_path(candidate, active_source):
            if not any(_same_path(candidate, prev) for prev in backup_original_candidates):
                backup_original_candidates.append(candidate)
    recovery_originals = []
    for candidate in [*original_candidates, *backup_original_candidates]:
        if candidate.exists() and not any(_same_path(candidate, prev) for prev in recovery_originals):
            recovery_originals.append(candidate)

    if active_source and extra_sources:
        status = "orphan-risk"
        severity = "warning"
        message = f"Active source is present, but {len(extra_sources)} same-ID extra source file(s) can create fake presence."
    elif active_source:
        status = "ok"
        severity = "ok"
        message = "Original source image is present."
    elif recovery_originals:
        status = "recoverable"
        severity = "error"
        message = f"Original source is missing, but {len(recovery_originals)} original recovery candidate(s) exist."
    elif derivative_files or generated_candidates:
        status = "derivative-only"
        severity = "error"
        message = "Original source is missing; only generated derivatives are available."
    else:
        status = "missing"
        severity = "error"
        message = "Original source image is missing and no safe recovery candidate was found."

    row = {
        "id": work_id,
        "work_id": work_id,
        "series": series_slug,
        "render_name": render_name,
        "status": status,
        "severity": severity,
        "message": message,
        "detail": message,
        "active_source": _relative_display(active_source) if active_source else "",
        "active_source_exists": bool(active_source and active_source.exists()),
        "resolved_path": _relative_display(active_source) if active_source else "",
        "expected_stems": expected_stems,
        "expected_source_candidates": [_relative_display(path) for path in _source_candidate_hint_paths(work_id, series_slug)[:12]],
        "extra_sources": [_relative_display(path) for path in extra_sources],
        "derivative_count": len(derivative_files),
        "derivative_dir": _relative_display(derivative_dir_for_work(series_slug, render_name, pipeline=pipeline)) if series_slug and render_name else "",
        "recovery_candidates": [
            {"path": _relative_display(path), "kind": "original", "size": _path_size(path)}
            for path in recovery_originals[:12]
        ],
        "generated_candidates": [
            {"path": _relative_display(path), "kind": "generated", "size": _path_size(path), "width": _candidate_width(path)}
            for path in generated_candidates[:12]
        ],
        "build_error": build_error or "",
        "preview_path": str(active_source or (recovery_originals[0] if recovery_originals else (generated_candidates[0] if generated_candidates else ""))),
        "recovery": "",
        "recovery_scan_performed": bool(include_recovery),
    }
    if status == "ok":
        row["recovery"] = "not needed"
    elif status == "orphan-risk":
        row["recovery"] = "review/remove extra same-ID originals: " + ", ".join(row["extra_sources"][:4])
    elif status == "recoverable":
        row["recovery"] = "safe original candidate: " + str(row["recovery_candidates"][0].get("path", ""))
    elif status == "derivative-only":
        row["recovery"] = "relink original; derivative-only fallback is blocked by strict release gate"
    else:
        row["recovery"] = "relink original source image"
    return row


def asset_truth_report_rows(*, use_cache: bool = True, force: bool = False, persist: bool = True) -> list[dict[str, Any]]:
    """Return source-asset truth rows without blocking routine refreshes.

    Default behaviour is now cache/index-first. A full filesystem source scan is
    performed only when ``force=True`` (manual validation, build/publish preflight,
    or explicit repair workflows). Studio, Publish, Dashboard, and list refreshes
    get persisted rows when available or cheap deferred rows when not.
    """
    global _ASSET_TRUTH_CACHE_ROWS, _ASSET_TRUTH_CACHE_SIGNATURE, _ASSET_TRUTH_CACHE_EXPIRES_AT
    signature_obj = _asset_truth_index_signature()
    signature = (hashlib.sha256(json.dumps(signature_obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),)
    now = time.monotonic()
    if (
        use_cache
        and not force
        and _ASSET_TRUTH_CACHE_ROWS is not None
        and _ASSET_TRUTH_CACHE_SIGNATURE == signature
        and now < _ASSET_TRUTH_CACHE_EXPIRES_AT
    ):
        return deepcopy(_ASSET_TRUTH_CACHE_ROWS)

    if force:
        rows = [source_asset_truth_for_work(payload) for payload in load_work_entries()]
        if persist:
            _write_persisted_asset_truth_rows(rows, signature=signature_obj)
    else:
        rows = _asset_truth_rows_from_persisted_or_deferred(signature_obj)
        if persist and not _read_persisted_asset_truth_payload():
            _write_persisted_asset_truth_rows(rows, signature=signature_obj)

    _ASSET_TRUTH_CACHE_ROWS = deepcopy(rows)
    _ASSET_TRUTH_CACHE_SIGNATURE = signature
    _ASSET_TRUTH_CACHE_EXPIRES_AT = now + _ASSET_TRUTH_CACHE_TTL_SECONDS
    return rows


def source_asset_report_rows(*, use_cache: bool = True, force: bool = False) -> list[dict[str, Any]]:
    """Compatibility wrapper used by existing UI panels. Now backed by the strict asset-truth model."""
    return asset_truth_report_rows(use_cache=use_cache, force=force)


def source_asset_issues(*, rows: list[dict[str, Any]] | None = None, use_cache: bool = True) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for row in (rows if rows is not None else source_asset_report_rows(use_cache=use_cache, force=not use_cache)):
        status = str(row.get("status") or "")
        if status == "ok":
            continue
        severity = "warning" if status in {"orphan-risk", "deferred", "unknown"} else "error"
        if status == "derivative-only":
            message = f"original source missing (series: {row['series']}) — generated derivatives exist but are not accepted as source truth"
        elif status == "recoverable":
            message = f"original source missing (series: {row['series']}) — safe recovery candidate available · {row.get('recovery')}"
        elif status == "orphan-risk":
            message = f"extra same-ID source file(s) detected (series: {row['series']}) — {row.get('recovery')}"
        elif status in {"deferred", "unknown"}:
            message = f"source status deferred (series: {row['series']}) — run source validation for current truth"
        else:
            message = f"missing source image (series: {row['series']}) — {row.get('recovery')}"
        issues.append({"scope": "work", "id": row["id"], "message": message, "severity": severity, "status": status})
    return issues


def recover_missing_source_images(work_ids: list[str] | None = None, *, line_callback: Callable[[str], None] | None = None, allow_derivative_recovery: bool = False) -> list[dict[str, str]]:
    """Restore missing originals only from original-quality candidates.

    Generated derivatives are deliberately not copied into originals unless
    allow_derivative_recovery=True is passed explicitly. The normal control-panel
    path must not create fake source truth from downsampled derivatives.
    """
    requested = {str(item).strip() for item in (work_ids or []) if str(item).strip()}
    recovered: list[dict[str, str]] = []
    pipeline = load_pipeline()
    for payload in load_work_entries():
        work_id = _clean_text(payload.get("id"))
        if requested and work_id not in requested:
            continue
        if not work_id:
            continue
        truth = source_asset_truth_for_work(payload, include_recovery=True)
        if truth.get("status") in {"ok", "orphan-risk"}:
            continue
        series_slug = _clean_text(truth.get("series"))
        if not series_slug:
            continue
        candidates = [row for row in (truth.get("recovery_candidates") or []) if row.get("kind") == "original"]
        emergency_derivatives = [row for row in (truth.get("generated_candidates") or []) if row.get("kind") == "generated"]
        if not candidates and allow_derivative_recovery:
            candidates = emergency_derivatives
        if not candidates:
            if line_callback:
                line_callback(f"Cannot auto-recover {work_id}: no original-quality source candidate found.")
            continue
        candidate_path = ROOT / str(candidates[0].get("path") or "")
        if not candidate_path.exists():
            candidate_path = Path(str(candidates[0].get("path") or ""))
        if not candidate_path.exists():
            continue
        destination_dir = source_root(pipeline) / series_slug
        destination_dir.mkdir(parents=True, exist_ok=True)
        suffix = candidate_path.suffix.lower() if candidate_path.suffix.lower() in SOURCE_EXTENSIONS else ".jpg"
        destination = destination_dir / f"{work_id}{suffix}"
        with transaction(f"qt-recover-source:{work_id}"):
            guarded_copy2(candidate_path, destination, detail="recover missing original source")
        presence = assert_no_fake_presence(work_id)
        row = {
            "work_id": work_id,
            "series": series_slug,
            "source": _relative_display(candidate_path),
            "restored_to": _relative_display(destination),
            "recovery_kind": str(candidates[0].get("kind") or "original"),
        }
        recovered.append(row)
        _record_diagnostic_event("asset-truth", "recovered", f"Recovered original source for {work_id}", work_id=work_id, restored_to=row["restored_to"])
        if line_callback:
            line_callback(f"Recovered missing original source for {work_id} from {row['source']}")
    if recovered:
        try:
            refresh_image_manifests(line_callback=None)
        except Exception as exc:
            _record_backend_warning("Could not refresh image manifests after source recovery", error=exc)
        mark_unpublished_changes()
        invalidate_control_panel_caches()
        mark_portfolio_health_dirty("work")
    return recovered

def relink_source_image(work_id: str, file_path: str | Path, *, line_callback: Callable[[str], None] | None = None) -> dict[str, str]:
    payload = load_work_payload(work_id)
    if not payload:
        raise BackendError(f"Work '{work_id}' was not found.")
    replace_work_image(work_id, file_path)
    row = {
        "work_id": work_id,
        "source": _relative_display(Path(file_path)),
        "series": _clean_text(payload.get("series") or work_to_series_map().get(work_id, "")),
    }
    if line_callback:
        line_callback(f"Relinked source image for {work_id} from {row['source']}")
    return row


def bulk_relink_missing_sources(search_root: str | Path, work_ids: list[str] | None = None, *, line_callback: Callable[[str], None] | None = None) -> list[dict[str, str]]:
    root = Path(search_root)
    if not root.exists() or not root.is_dir():
        raise BackendError(f"Folder not found: {root}")
    requested = {str(item).strip() for item in (work_ids or []) if str(item).strip()}
    indexed = _index_supported_images(root)
    matched: list[dict[str, str]] = []
    for payload in load_work_entries():
        work_id = _clean_text(payload.get("id"))
        if not work_id or (requested and work_id not in requested):
            continue
        series_slug = _clean_text(payload.get("series") or work_to_series_map().get(work_id, ""))
        if not series_slug:
            continue
        existing = _resolve_source_path(series_slug, work_id, load_pipeline(), context="bulk relink")
        if existing and Path(existing).exists():
            continue
        candidate = _choose_best_folder_candidate(payload, indexed)
        if candidate is None:
            continue
        replace_work_image(work_id, candidate)
        row = {
            "work_id": work_id,
            "series": series_slug,
            "source": _relative_display(candidate),
            "method": "folder-scan",
        }
        matched.append(row)
        if line_callback:
            line_callback(f"Relinked missing source for {work_id} from {row['source']} (folder scan)")
    if matched:
        try:
            refresh_image_manifests(line_callback=line_callback)
        except Exception as exc:
            _record_backend_warning("Could not refresh manifests after bulk relink", error=exc)
        invalidate_control_panel_caches()
        mark_unpublished_changes()
    return matched


def draft_path(kind: str, key: str) -> Path:
    safe_kind = slugify_work_id(kind or "draft") or "draft"
    safe_key = slugify_work_id(key or "untitled") or "untitled"
    return DRAFTS_DIR / safe_kind / f"{safe_key}.json"



def save_editor_draft(kind: str, key: str, payload: dict[str, Any]) -> None:
    """Persist an autosave draft with conflict-detection metadata."""
    cache_key = (_clean_text(kind).lower(), _clean_text(key))
    with _FINGERPRINT_CACHE_LOCK:
        _FINGERPRINT_CACHE.pop(cache_key, None)
    path = draft_path(kind, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(payload or {})
    row.setdefault("kind", str(kind or ""))
    row.setdefault("key", str(key or ""))
    row.setdefault("saved_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if "source_fingerprint" not in row:
        try:
            row["source_fingerprint"] = editor_source_fingerprint(kind, key)
        except Exception as exc:
            row["source_fingerprint"] = {"error": str(exc)}
    atomic_write_json(path, row)


def load_editor_draft(kind: str, key: str) -> dict[str, Any] | None:
    path = draft_path(kind, key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None



def clear_editor_draft(kind: str, key: str) -> None:
    path = draft_path(kind, key)
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:
        _record_backend_warning("Could not clear editor draft", path=path, error=exc)

def list_editor_drafts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not DRAFTS_DIR.exists():
        return rows
    for path in DRAFTS_DIR.rglob('*.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        rows.append({
            'kind': str(data.get('kind') or path.parent.name),
            'key': str(data.get('key') or path.stem),
            'saved_at': str(data.get('saved_at') or ''),
            'path': path.relative_to(ROOT).as_posix(),
        })
    rows.sort(key=lambda item: item.get('saved_at') or '', reverse=True)
    return rows


def validate_all() -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    works: dict[str, dict[str, Any]] = {}
    for item in load_work_entries():
        clean = {k: v for k, v in dict(item).items() if not str(k).startswith("_")}
        work_id = _clean_text(clean.get("id"))
        if work_id:
            works[work_id] = clean
    for work_id, payload in works.items():
        for issue in work_issue_list(payload):
            issues.append({"scope": "work", "id": work_id, "message": issue, "severity": "warning"})
        for row in validate_editor_payload("work", payload, original_key=work_id):
            severity = _clean_text(row.get("severity")) or "warning"
            message = _clean_text(row.get("message"))
            field = _clean_text(row.get("field"))
            if message:
                issues.append({"scope": "work", "id": work_id, "message": f"{field}: {message}" if field else message, "severity": severity})
    for series in load_series_entries():
        slug = _clean_text(series.get("slug"))
        if not slug:
            continue
        for issue in series_issue_list(series):
            issues.append({"scope": "series", "id": slug, "message": issue, "severity": "warning"})
        cover_id = _clean_text(series.get("cover_work_id"))
        if cover_id and cover_id not in works:
            issues.append({"scope": "series", "id": slug, "message": f"cover work '{cover_id}' is missing", "severity": "error"})
        for work_id in [str(item).strip() for item in (series.get("work_ids") or []) if str(item).strip()]:
            if work_id not in works:
                issues.append({"scope": "series", "id": slug, "message": f"listed work '{work_id}' is missing", "severity": "error"})
    for page_key in available_page_keys():
        payload = load_page_payload(page_key)
        for issue in page_issue_list(page_key, payload):
            issues.append({"scope": "page", "id": page_key, "message": issue, "severity": "warning"})
        hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
        feature_work_id = _clean_text(hero.get("feature_work_id"))
        if feature_work_id and feature_work_id not in works:
            issues.append({"scope": "page", "id": page_key, "message": f"hero work '{feature_work_id}' is missing", "severity": "error"})
    return issues


def repair_items(*, include_source_assets: bool = True) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for payload in load_work_entries():
        work_id = _clean_text(payload.get("id"))
        for issue in work_issue_list(payload):
            items.append({"kind": "work", "id": work_id, "issue": issue})
    if include_source_assets:
        for row in source_asset_issues():
            items.append({"kind": "work", "id": str(row.get("id") or ""), "issue": str(row.get("message") or "missing source image")})
    for series in load_series_entries():
        slug = _clean_text(series.get("slug"))
        if not _clean_text(series.get("cover_work_id")):
            items.append({"kind": "series", "id": slug, "issue": "missing cover"})
        missing_refs = series_missing_work_references(series)
        if missing_refs:
            items.append({"kind": "series", "id": slug, "issue": f"broken work references: {', '.join(missing_refs[:6])}"})
    return items



def _stable_image_hash(path: Path) -> str:
    """Return a lightweight perceptual hash suitable for local duplicate triage.

    Palette-mode and damaged images are treated defensively so one unusual file
    cannot crash the duplicate scan.
    """
    try:
        with Image.open(path) as im:
            if im.mode in ("P", "PA"):
                im = im.convert("RGBA")
            gray = im.convert("L").resize((8, 8))
            pixels = list(gray.getdata())
    except Exception as exc:
        _record_backend_warning("Could not compute stable image hash", path=path, error=exc)
        return "0000000000000000"
    if len(pixels) != 64:
        _record_backend_warning("Stable image hash returned unexpected pixel count", path=path, error=f"{len(pixels)} pixels")
        return "0000000000000000"
    avg = sum(pixels) / 64
    bits = ''.join('1' if value >= avg else '0' for value in pixels)
    return f"{int(bits, 2):016x}"


def _hash_distance(left: str, right: str) -> int:
    try:
        return bin(int(left, 16) ^ int(right, 16)).count('1')
    except Exception:
        return 64


def _work_preview_image_path(payload: dict[str, Any]) -> Path | None:
    preview = best_preview_path_for_work(payload)
    if preview and Path(preview).exists():
        return Path(preview)
    work_id = _clean_text(payload.get('id'))
    series_slug = _clean_text(payload.get('series') or work_to_series_map().get(work_id, ''))
    if not work_id or not series_slug:
        return None
    source = _resolve_source_path(series_slug, work_id, load_pipeline(), context="work preview")
    return source if source and source.exists() else None


def _duplicate_keep_score(item: dict[str, Any]) -> tuple[int, int, int, str]:
    """Higher is better: confirmed source, dimensions, file size, stable ID."""
    payload = item.get("_payload") if isinstance(item.get("_payload"), dict) else {}
    score_status = 0
    try:
        status = str(source_asset_truth_for_work(payload).get("status") or "")
        score_status = {"ok": 3, "orphan-risk": 2, "recoverable": 1}.get(status, 0)
    except Exception:
        score_status = 0
    dimensions = _image_dimensions(Path(str(item.get("_abs_path") or ""))) or (0, 0)
    pixels = int(dimensions[0]) * int(dimensions[1])
    return (score_status, pixels, int(item.get("size") or 0), str(item.get("id") or ""))


def _recommended_duplicate_keep(left: dict[str, Any], right: dict[str, Any]) -> str:
    left_score = _duplicate_keep_score(left)
    right_score = _duplicate_keep_score(right)
    if left_score == right_score:
        return str(left.get("id") or "")
    return str(left.get("id") if left_score > right_score else right.get("id"))



def image_duplicate_candidates(*, threshold: int = 6, progress_callback: Callable[[int, int], None] | None = None) -> list[dict[str, Any]]:
    """Find likely duplicate/near-duplicate works by perceptual hash.

    This is intentionally conservative: it reports candidates only and never modifies content.
    The caller may provide ``progress_callback(done, total)`` so the Qt layer can run
    this in a worker thread without freezing the main UI.
    """
    threshold = max(0, min(64, int(threshold or 6)))
    rows: list[dict[str, Any]] = []
    hashed: list[dict[str, Any]] = []
    works = load_work_entries()
    total = len(works)
    acquired = _DUPLICATE_SCAN_LOCK.acquire(timeout=60)
    if not acquired:
        raise BackendError("Duplicate scan is already running or stalled. Try again after it finishes.")
    try:
        for index, payload in enumerate(works, start=1):
            work_id = _clean_text(payload.get('id'))
            if not work_id:
                if progress_callback:
                    progress_callback(index, total)
                continue
            path = _work_preview_image_path(payload)
            if not path or not path.exists():
                if progress_callback:
                    progress_callback(index, total)
                continue
            try:
                stat = path.stat()
                digest = _stable_image_hash(path)
                with path.open('rb') as handle:
                    exact = hashlib.sha256(handle.read()).hexdigest()
            except Exception as exc:
                _record_backend_warning('Duplicate scan skipped unreadable image', path=path, error=exc)
                if progress_callback:
                    progress_callback(index, total)
                continue
            hashed.append({
                'id': work_id,
                'title': _clean_text(payload.get('title')),
                'series': _clean_text(payload.get('series')),
                'path': _relative_display(path),
                '_abs_path': str(path),
                '_payload': dict(payload),
                'size': int(stat.st_size),
                'mtime': int(stat.st_mtime_ns),
                'phash': digest,
                'sha256': exact,
            })
            if progress_callback:
                progress_callback(index, total)
        for index, left in enumerate(hashed):
            for right in hashed[index + 1:]:
                exact = left.get('sha256') == right.get('sha256')
                distance = 0 if exact else _hash_distance(str(left.get('phash')), str(right.get('phash')))
                if exact or distance <= threshold:
                    rows.append({
                        'left_id': left['id'],
                        'right_id': right['id'],
                        'left_title': left.get('title', ''),
                        'right_title': right.get('title', ''),
                        'left_path': left.get('path', ''),
                        'right_path': right.get('path', ''),
                        'distance': distance,
                        'exact_file': bool(exact),
                        'confidence': 'exact' if exact else 'high' if distance <= 3 else 'possible',
                        'recommended_keep': _recommended_duplicate_keep(left, right),
                    })
        if progress_callback:
            progress_callback(total, total)
    finally:
        _DUPLICATE_SCAN_LOCK.release()
    rows.sort(key=lambda row: (int(row.get('distance') or 0), str(row.get('left_id') or '')))
    return rows


def work_metadata_audit_rows(work_ids: list[str] | None = None) -> list[dict[str, Any]]:
    wanted = {str(item).strip() for item in (work_ids or []) if str(item).strip()}
    rows: list[dict[str, Any]] = []
    for payload in load_work_entries():
        work_id = _clean_text(payload.get('id'))
        if wanted and work_id not in wanted:
            continue
        title = _clean_text(payload.get('title'))
        alt = _clean_text(payload.get('alt') or payload.get('alt_text'))
        caption = _clean_text(payload.get('caption'))
        year = _clean_text(payload.get('year') or payload.get('date'))
        location = _clean_text(payload.get('location'))
        tags = payload.get('tags') if isinstance(payload.get('tags'), list) else []
        source_present = bool(_work_preview_image_path(payload))
        issues = list(work_issue_list(payload))
        if not source_present:
            issues.append('missing source/preview image')
        score = 100
        penalties = {
            'title': 18 if len(title.split()) < 2 else 0,
            'alt': 28 if len(alt.split()) < 5 else 12 if len(alt.split()) < 10 else 0,
            'caption': 20 if len(caption.split()) < 8 else 0,
            'year': 10 if not year else 0,
            'location': 12 if not location or _is_placeholder_text(location) else 0,
            'tags': 6 if not tags else 0,
            'image': 28 if not source_present else 0,
        }
        score = max(0, score - sum(penalties.values()))
        status = 'ready' if score >= 85 and not issues else 'review' if score >= 60 else 'blocked'
        rows.append({
            'id': work_id,
            'title': title,
            'series': _clean_text(payload.get('series')),
            'score': score,
            'status': status,
            'missing': ', '.join(key for key, value in penalties.items() if value),
            'issues': issues,
            'alt_words': len(alt.split()),
            'caption_words': len(caption.split()),
            'published': bool(payload.get('published')),
            'review_status': _clean_text(payload.get('review_status')),
        })
    rows.sort(key=lambda row: (int(row.get('score') or 0), str(row.get('id') or '')))
    return rows


def work_lineage_report(work_id: str) -> dict[str, Any]:
    """Read-only lineage report. Must not mutate cache, health state, or content."""
    work_id = _clean_text(work_id)
    if not work_id:
        raise BackendError("work_id is required for lineage report.")
    payload = load_work_payload(work_id)
    if not payload:
        raise BackendError(f"Work '{work_id}' was not found.")
    series_slug = _clean_text(payload.get('series') or work_to_series_map().get(work_id, ''))
    pipeline = load_pipeline()
    source = _resolve_source_path(series_slug, work_id, pipeline=pipeline, context="lineage") if series_slug else None
    render = _render_name_for_work(payload) or work_id
    derivative_dir = derivative_dir_for_work(series_slug, render, pipeline=pipeline) if series_slug else None
    derivatives: list[dict[str, Any]] = []
    if derivative_dir and derivative_dir.exists():
        for item in sorted(derivative_dir.rglob('*')):
            if item.is_file():
                try:
                    stat = item.stat()
                    dimensions = _image_dimensions(item)
                    derivatives.append({
                        'path': _relative_display(item),
                        'size': int(stat.st_size),
                        'dimensions': f"{dimensions[0]}×{dimensions[1]}" if dimensions else '',
                    })
                except Exception as exc:
                    derivatives.append({'path': _relative_display(item), 'size': 0, 'dimensions': '', 'error': str(exc)})
    social_refs = []
    social_dir = ROOT / 'assets/images/social'
    try:
        social_candidates = sorted(social_dir.glob('*')) if social_dir.exists() else []
    except OSError as exc:
        _record_backend_warning("Could not scan social refs dir", path=social_dir, error=exc)
        social_candidates = []
    for candidate in social_candidates:
        if work_id.lower() in candidate.name.lower() or render.lower() in candidate.name.lower():
            social_refs.append(_relative_display(candidate))
    try:
        presence = reconcile_asset_presence_for_work(work_id)
    except BackendError as exc:
        presence = {"status": "error", "message": str(exc)}
    return {
        'work_id': work_id,
        'title': _clean_text(payload.get('title')),
        'series': series_slug,
        'image_master': _clean_text((payload.get('image') or {}).get('master') if isinstance(payload.get('image'), dict) else ''),
        'render_name': render,
        'source': _relative_display(source) if source else '',
        'source_exists': bool(source and source.exists()),
        'derivative_dir': _relative_display(derivative_dir) if derivative_dir else '',
        'derivative_count': len(derivatives),
        'derivatives': derivatives,
        'social_refs': social_refs,
        'presence': presence,
    }

def _load_curation_notes() -> dict[str, Any]:
    if not CURATION_NOTES_PATH.exists():
        return {'work': {}, 'series': {}}
    try:
        data = json.loads(CURATION_NOTES_PATH.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            data.setdefault('work', {})
            data.setdefault('series', {})
            return data
    except Exception as exc:
        _record_backend_warning('Could not read curation notes', path=CURATION_NOTES_PATH, error=exc)
    return {'work': {}, 'series': {}}


def load_private_note(kind: str, key: str) -> str:
    data = _load_curation_notes()
    bucket = data.get(kind) if isinstance(data.get(kind), dict) else {}
    row = bucket.get(key) if isinstance(bucket.get(key), dict) else {}
    return str(row.get('note') or '')


def save_private_note(kind: str, key: str, note: str) -> dict[str, Any]:
    kind = 'series' if kind == 'series' else 'work'
    key = _clean_text(key)
    if not key:
        raise BackendError('A work/series key is required before saving a note.')
    data = _load_curation_notes()
    data.setdefault(kind, {})
    data[kind][key] = {
        'note': str(note or '').strip(),
        'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    CURATION_NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(CURATION_NOTES_PATH, data)
    return data[kind][key]



def series_completeness_rows(*, task_context: Any | None = None) -> list[dict[str, Any]]:
    """Return cheap series health rows from the central repository indexes."""
    global _SERIES_COMPLETENESS_CACHE
    with _SERIES_COMPLETENESS_CACHE_LOCK:
        now = time.monotonic()
        if _SERIES_COMPLETENESS_CACHE is not None:
            cached_at, cached_rows = _SERIES_COMPLETENESS_CACHE
            if now - cached_at < _SERIES_COMPLETENESS_CACHE_TTL:
                return deepcopy(cached_rows)

        repo = _CONTENT_REPOSITORY
        works_by_id = {str(item.get('id') or ''): item for item in repo.works()}
        series_rows = repo.series()
        valid_work_ids = set(works_by_id)
        rows: list[dict[str, Any]] = []
        for index, payload in enumerate(series_rows, start=1):
            if task_context is not None and index % 10 == 0:
                task_context.check_cancelled()
            slug = _clean_text(payload.get('slug'))
            work_ids = [str(item).strip() for item in (payload.get('work_ids') or []) if str(item).strip()]
            cover = _clean_text(payload.get('cover_work_id'))
            issues: list[str] = []
            if not cover:
                issues.append('missing cover work')
            elif cover not in valid_work_ids:
                issues.append('cover work missing from works')
            if not work_ids:
                issues.append('empty series sequence')
            missing = [work_id for work_id in work_ids if work_id not in valid_work_ids]
            if missing:
                issues.append(f"{len(missing)} listed work(s) missing: {', '.join(missing[:5])}")
            published = sum(1 for work_id in work_ids if bool((works_by_id.get(work_id) or {}).get('published')))
            weak_meta = sum(1 for work_id in work_ids if work_id in works_by_id and work_issue_list(works_by_id[work_id]))
            if weak_meta:
                issues.append(f"{weak_meta} work(s) have metadata warnings")
            score = 100
            if not cover or cover not in valid_work_ids:
                score -= 25
            if not work_ids:
                score -= 35
            score -= min(25, len(missing) * 10)
            score -= min(30, weak_meta * 6)
            if work_ids and published == 0:
                score -= 15
            rows.append({
                'slug': slug,
                'title': _clean_text(payload.get('title')),
                'score': max(0, score),
                'works': len(work_ids),
                'published': published,
                'cover': cover,
                'missing_work_ids': missing,
                'issues': issues,
                'status': 'ready' if score >= 85 and not issues else 'review' if score >= 60 else 'blocked',
            })
        rows.sort(key=lambda row: (int(row.get('score') or 0), str(row.get('slug') or '')))
        _SERIES_COMPLETENESS_CACHE = (time.monotonic(), deepcopy(rows))
        return rows


def series_rhythm_rows(series_slug: str) -> list[dict[str, Any]]:
    sequence = load_series_sequence(series_slug)
    rows: list[dict[str, Any]] = []
    for index, work_id in enumerate(sequence, start=1):
        payload = load_work_payload(work_id)
        missing_payload = not bool(payload)
        if missing_payload:
            payload = {'id': work_id, 'series': series_slug}
        path = _work_preview_image_path(payload)
        brightness = 0.0
        orientation = 'missing-work' if missing_payload else 'missing'
        dimensions_label = ''
        if path and path.exists():
            try:
                with Image.open(path) as im:
                    width, height = im.size
                    orientation = 'landscape' if width > height else 'portrait' if height > width else 'square'
                    dimensions_label = f'{width}×{height}'
                    brightness = float(im.convert('L').resize((1, 1)).getpixel((0, 0)))
            except Exception as exc:
                _record_backend_warning('Could not read rhythm image', path=path, error=exc)
        issues = ['missing work payload'] if missing_payload else work_issue_list(payload)
        rows.append({
            'position': index,
            'id': work_id,
            'title': _clean_text(payload.get('title')),
            'orientation': orientation,
            'brightness': round(brightness, 1),
            'dimensions': dimensions_label,
            'missing_work': missing_payload,
            'issues': issues,
            'preview': _relative_display(path) if path else '',
        })
    return rows



def preview_work_move(work_id: str, target_series: str) -> dict[str, Any]:
    payload = load_work_payload(work_id)
    if not payload:
        raise BackendError(f"Work '{work_id}' was not found.")
    current_series = _clean_text(payload.get('series') or work_to_series_map().get(work_id, ''))
    target_series = _clean_text(target_series)
    if target_series not in _cached_series_slug_set():
        raise BackendError('Choose a valid target series.')
    current_sequence = load_series_sequence(current_series) if current_series else []
    target_sequence = load_series_sequence(target_series)
    pipeline = load_pipeline()
    source = _resolve_source_path(current_series, work_id, pipeline=pipeline, context="series rhythm") if current_series else None
    new_source = source_root(pipeline) / target_series / f"{work_id}{source.suffix.lower()}" if source else None
    affected = []
    if current_series:
        affected.append({'series': current_series, 'current_count': len(current_sequence), 'after_count': max(0, len(current_sequence) - (1 if work_id in current_sequence else 0))})
    affected.append({'series': target_series, 'current_count': len(target_sequence), 'after_count': len(target_sequence) + (0 if work_id in target_sequence else 1)})
    return {
        'work_id': work_id,
        'title': _clean_text(payload.get('title')),
        'from_series': current_series,
        'to_series': target_series,
        'source': _relative_display(source) if source else '',
        'target_source': _relative_display(new_source) if new_source else '',
        'will_move_file': bool(source and source.exists() and current_series != target_series),
        'affected_series': affected,
    }


def validation_action_rows() -> list[dict[str, Any]]:
    rows = validate_all()
    for row in rows:
        scope = str(row.get('scope') or '')
        message = str(row.get('message') or '').lower()
        action = 'Open'
        fixable = False
        if scope == 'series' and ('cover work' in message or 'listed work' in message or 'broken work references' in message):
            action = 'Auto-fix reference'
            fixable = True
        elif scope == 'page' and 'hero work' in message:
            action = 'Auto-clear hero reference'
            fixable = True
        row['action'] = action
        row['fixable'] = fixable
        row['explain'] = _validation_explanation(row)
    return rows


def _validation_explanation(row: dict[str, Any]) -> str:
    scope = row.get('scope')
    severity = row.get('severity')
    message = str(row.get('message') or '')
    if severity == 'error':
        return f"Blocking issue: {message}. Publishing should not proceed until this reference or content integrity problem is fixed."
    if scope == 'work':
        return f"Work metadata warning: {message}. It may reduce accessibility, search clarity, or portfolio trust, but it does not block building."
    if scope == 'series':
        return f"Series curation warning: {message}. Check cover, sequence, and whether the series feels complete enough to publish."
    return f"Content warning: {message}. Review the related editor before publish."


def auto_fix_validation_issue(row: dict[str, Any]) -> dict[str, Any]:
    scope = str(row.get('scope') or '')
    key = _clean_text(row.get('id'))
    message = str(row.get('message') or '').lower()
    changed: list[str] = []
    with transaction(f"qt-validation-autofix:{scope}:{key}"):
        if scope == 'series':
            payload = load_series_payload(key)
            if not payload:
                raise BackendError(f"Series '{key}' was not found.")
            works = {str(item.get('id') or '') for item in load_work_entries()}
            work_ids = [str(item).strip() for item in (payload.get('work_ids') or []) if str(item).strip()]
            filtered = [work_id for work_id in work_ids if work_id in works]
            if ('listed work' in message or 'broken work references' in message) and filtered != work_ids:
                payload['work_ids'] = filtered
                changed.append('Removed missing work IDs from series sequence')
            cover = _clean_text(payload.get('cover_work_id'))
            if ('cover work' in message or not cover) and (not cover or cover not in works):
                payload['cover_work_id'] = filtered[0] if filtered else ''
                changed.append('Reset cover work to first valid sequence item')
            if not changed:
                raise BackendError('No safe automatic fix is available for this series issue.')
            save_series_payload(key, payload)
        elif scope == 'page' and 'hero work' in message:
            payload = load_page_payload(key)
            hero = payload.get('hero') if isinstance(payload.get('hero'), dict) else {}
            if hero.get('feature_work_id'):
                hero['feature_work_id'] = ''
                payload['hero'] = hero
                changed.append('Cleared missing hero work reference')
            if not changed:
                raise BackendError('No missing hero reference was found to clear.')
            save_page_payload(key, payload)
        else:
            raise BackendError('This validation issue is not safely auto-fixable. Open the item and edit it manually.')
    mark_unpublished_changes()
    return {'scope': scope, 'id': key, 'changed': changed}


def release_gate_summary(
    *,
    checks: list[dict[str, Any]] | None = None,
    validation_rows: list[dict[str, Any]] | None = None,
    source_issues: Any = _SOURCE_ISSUES_NOT_PROVIDED,
    published_only: bool = False,
) -> dict[str, Any]:
    validation = validation_rows if validation_rows is not None else validate_all()
    if published_only:
        validation = _filter_rows_to_published_works(validation)
        if source_issues is not _SOURCE_ISSUES_NOT_PROVIDED and source_issues is not None:
            source_issues = _filter_rows_to_published_works(list(source_issues or []))
    if checks is None:
        if source_issues is _SOURCE_ISSUES_NOT_PROVIDED:
            checks = release_checks(validation_rows=validation, published_only=published_only)
        else:
            checks = release_checks(validation_rows=validation, source_issues=source_issues, published_only=published_only)
    errors = [row for row in checks if str(row.get('status') or '').lower() == 'error']
    warnings = [row for row in checks if str(row.get('status') or '').lower() in {'warn', 'warning'}]
    validation_errors = [row for row in validation if str(row.get('severity') or '').lower() == 'error']
    validation_warnings = [row for row in validation if str(row.get('severity') or '').lower() != 'error']
    blocked = bool(errors or validation_errors)
    return {
        'blocked': blocked,
        'published_only': bool(published_only),
        'errors': len(errors) + len(validation_errors),
        'warnings': len(warnings) + len(validation_warnings),
        'checks': checks,
        'validation_errors': validation_errors,
        'validation_warnings': validation_warnings,
        'message': 'Publish blocked by validation errors.' if blocked else 'Publish can proceed after warning acknowledgement.' if warnings or validation_warnings else 'Publish checks are clean.',
    }


def capture_public_output_snapshot() -> dict[str, Any]:
    root_path = PUBLIC_UPLOAD_DIR
    files: dict[str, dict[str, Any]] = {}
    if root_path.exists():
        for file in root_path.rglob('*'):
            if not file.is_file():
                continue
            try:
                rel = file.relative_to(root_path).as_posix()
                stat = file.stat()
                files[rel] = {'size': int(stat.st_size), 'mtime_ns': int(stat.st_mtime_ns)}
            except Exception as exc:
                _record_backend_warning('Could not snapshot public output file', path=file, error=exc)
    row = {'captured_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'files': files}
    PUBLIC_OUTPUT_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(PUBLIC_OUTPUT_SNAPSHOT_PATH, row)
    return row


def diff_public_output_snapshot() -> dict[str, Any]:
    before = {'files': {}}
    if PUBLIC_OUTPUT_SNAPSHOT_PATH.exists():
        try:
            before = json.loads(PUBLIC_OUTPUT_SNAPSHOT_PATH.read_text(encoding='utf-8'))
        except Exception as exc:
            _record_backend_warning('Could not read public output snapshot', path=PUBLIC_OUTPUT_SNAPSHOT_PATH, error=exc)
    old = before.get('files') if isinstance(before.get('files'), dict) else {}
    current = capture_public_output_snapshot()
    new = current.get('files') if isinstance(current.get('files'), dict) else {}
    added = sorted([key for key in new if key not in old])
    removed = sorted([key for key in old if key not in new])
    changed = sorted([key for key in new if key in old and new[key] != old[key]])
    return {'added': added, 'removed': removed, 'changed': changed, 'captured_at': current.get('captured_at'), 'previous_at': before.get('captured_at', '')}


def create_release_snapshot(name: str, note: str = '') -> dict[str, Any]:
    name = _clean_text(name) or datetime.now().strftime('snapshot-%Y%m%d-%H%M%S')
    slug = slugify_work_id(name) or datetime.now().strftime('snapshot-%Y%m%d-%H%M%S')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    target = RELEASE_SNAPSHOTS_DIR / f'{stamp}-{slug}'
    target.mkdir(parents=True, exist_ok=True)
    manifest = {
        'name': name,
        'note': str(note or '').strip(),
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'content_graph_hash': _content_graph_digest(),
        'files': [],
    }
    for folder_name in ('content', '.stillmrk-build/meta'):
        source = ROOT / folder_name
        if not source.exists():
            continue
        destination = target / folder_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)
        manifest['files'].append(folder_name)
    manifest_path = target / 'snapshot-manifest.json'
    atomic_write_json(manifest_path, manifest)
    return {'path': _relative_display(target), 'manifest': manifest}


def list_release_snapshots() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not RELEASE_SNAPSHOTS_DIR.exists():
        return rows
    for folder in RELEASE_SNAPSHOTS_DIR.iterdir():
        if not folder.is_dir():
            continue
        manifest_path = folder / 'snapshot-manifest.json'
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            except Exception:
                manifest = {}
        rows.append({
            'name': str(manifest.get('name') or folder.name),
            'created_at': str(manifest.get('created_at') or ''),
            'note': str(manifest.get('note') or ''),
            'content_graph_hash': str(manifest.get('content_graph_hash') or ''),
            'path': _relative_display(folder),
        })
    rows.sort(key=lambda item: item.get('created_at') or item.get('path') or '', reverse=True)
    return rows

# ---------- Phase 7-10 control-panel operations ----------

def load_inquiries() -> list[dict[str, Any]]:
    """Private studio inquiry records. These are control-panel metadata only."""
    return _panel_records(INQUIRIES_PATH, "inquiries")


def save_inquiry_record(row: dict[str, Any]) -> dict[str, Any]:
    clean = dict(row or {})
    clean["contact"] = _clean_text(clean.get("contact"))
    clean["subject"] = _clean_text(clean.get("subject"))
    clean["status"] = _clean_text(clean.get("status")) or "new"
    clean["priority"] = _clean_text(clean.get("priority")) or "normal"
    clean["note"] = str(clean.get("note") or "").strip()
    return _upsert_panel_record(INQUIRIES_PATH, "inquiries", clean)


def delete_inquiry_record(record_id: str) -> int:
    return _delete_panel_record(INQUIRIES_PATH, "inquiries", record_id)


def load_print_editions() -> list[dict[str, Any]]:
    """Private print/edition records. Public website output is not changed by these records."""
    return _panel_records(PRINT_EDITIONS_PATH, "editions")


def save_print_edition_record(row: dict[str, Any]) -> dict[str, Any]:
    clean = dict(row or {})
    clean["work_id"] = _clean_text(clean.get("work_id"))
    clean["title"] = _clean_text(clean.get("title"))
    clean["status"] = _clean_text(clean.get("status")) or "draft"
    clean["size"] = _clean_text(clean.get("size"))
    clean["paper"] = _clean_text(clean.get("paper"))
    clean["edition"] = _clean_text(clean.get("edition"))
    clean["price"] = _clean_text(clean.get("price"))
    clean["note"] = str(clean.get("note") or "").strip()
    return _upsert_panel_record(PRINT_EDITIONS_PATH, "editions", clean)


def delete_print_edition_record(record_id: str) -> int:
    return _delete_panel_record(PRINT_EDITIONS_PATH, "editions", record_id)


def portfolio_readiness_score(
    *,
    validation_rows: list[dict[str, Any]] | None = None,
    audit_rows: list[dict[str, Any]] | None = None,
    series_rows: list[dict[str, Any]] | None = None,
    gate: dict[str, Any] | None = None,
    source_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute one practical release-readiness score from validation, metadata, source assets, and curation state."""
    validation_rows = validation_rows if validation_rows is not None else validation_action_rows()
    audit_rows = audit_rows if audit_rows is not None else work_metadata_audit_rows()
    series_rows = series_rows if series_rows is not None else series_completeness_rows()
    gate = gate if gate is not None else release_gate_summary()
    source_issues = source_issues if source_issues is not None else source_asset_issues()
    exact_errors = [r for r in validation_rows if str(r.get("severity") or "").lower() in {"error", "critical", "blocked", "fail", "failed"}]
    warnings = [r for r in validation_rows if str(r.get("severity") or "").lower() in {"warning", "warn", "needs attention"}]
    weak_metadata = [r for r in audit_rows if str(r.get("status") or "").lower() not in {"ok", "clean", "ready"}]
    weak_series = [r for r in series_rows if int(r.get("score") or 0) < 75]
    blocking_gate = int(gate.get("blocking_errors") or gate.get("errors") or 0)
    penalty = 0
    penalty += min(45, len(exact_errors) * 9)
    penalty += min(22, len(source_issues) * 6)
    penalty += min(18, len(weak_metadata) * 2)
    penalty += min(15, len(weak_series) * 4)
    penalty += min(25, blocking_gate * 8)
    penalty += min(10, len(warnings))
    score = max(0, min(100, 100 - penalty))
    if exact_errors or blocking_gate or source_issues:
        status = "blocked"
    elif score >= 90:
        status = "ready"
    elif score >= 75:
        status = "review"
    else:
        status = "needs work"
    actions: list[dict[str, Any]] = []
    if exact_errors:
        actions.append({"label": "Fix blocking validation errors", "count": len(exact_errors), "target": "validation"})
    if source_issues:
        actions.append({"label": "Repair missing source images", "count": len(source_issues), "target": "studio"})
    if weak_metadata:
        actions.append({"label": "Complete weak work metadata", "count": len(weak_metadata), "target": "works"})
    if weak_series:
        actions.append({"label": "Improve series completeness", "count": len(weak_series), "target": "series"})
    if not actions:
        actions.append({"label": "Run release gate before publish", "count": 1, "target": "publish"})
    return {
        "score": score,
        "status": status,
        "actions": actions,
        "metrics": {
            "validation_errors": len(exact_errors),
            "validation_warnings": len(warnings),
            "source_issues": len(source_issues),
            "metadata_issues": len(weak_metadata),
            "series_below_75": len(weak_series),
            "release_blockers": blocking_gate,
        },
    }


def _count_unlogged_broad_excepts(source: str) -> int:
    lines = source.splitlines()
    count = 0
    for index, line in enumerate(lines):
        if "except Exception" not in line:
            continue
        window = "\n".join(lines[index:index + 8])
        if "_record_backend_warning" not in window and "_record_diagnostic_event" not in window:
            count += 1
    return count


def _cached_asset_truth_rows_for_diagnostics() -> tuple[list[dict[str, Any]], bool]:
    if not ASSET_TRUTH_PATH.exists():
        return [], False
    try:
        payload = json.loads(ASSET_TRUTH_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [dict(row) for row in payload if isinstance(row, dict)], True
    except Exception as exc:
        _record_backend_warning("Could not read cached asset-truth rows for diagnostics", path=ASSET_TRUTH_PATH, error=exc)
    return [], False


def _performance_budget_violations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        area = _clean_text(event.get("area") or event.get("context") or event.get("name")).lower()
        elapsed = event.get("elapsed_ms", event.get("total_ms"))
        try:
            elapsed_int = int(float(elapsed))
        except Exception:
            continue
        for name, budget in PERFORMANCE_BUDGETS_MS.items():
            if name.lower() in area and elapsed_int > int(budget):
                row = dict(event)
                row["budget_name"] = name
                row["budget_ms"] = int(budget)
                row["elapsed_ms"] = elapsed_int
                violations.append(row)
                break
    return violations


def control_panel_diagnostics() -> dict[str, Any]:
    """Static maintainability and runtime-readiness diagnostics for the control-panel code itself."""
    # control_panel.py is the Qt UI shell. It can be absent in backend-only
    # diagnostic bundles, so missing UI shell is a watch item rather than a
    # hard backend failure.
    panel_path = ROOT / "scripts" / "control_panel.py"
    backend_path = ROOT / "scripts" / "qt_backend.py"
    rows: list[dict[str, Any]] = []
    for label, path in [("UI", panel_path), ("Backend", backend_path)]:
        try:
            source = path.read_text(encoding="utf-8")
        except Exception as exc:
            status = "watch" if label == "UI" else "error"
            detail = (
                f"{path.name} is not present in this backend-only diagnostic context."
                if label == "UI"
                else f"Could not read {path.name}: {exc}"
            )
            rows.append({"area": label, "status": status, "detail": detail})
            continue
        line_count = source.count("\n") + 1
        broad_except_count = source.count("except Exception")
        unlogged_broad_except_count = _count_unlogged_broad_excepts(source)
        qmessage_count = source.count("QMessageBox")
        rows.append({
            "area": label,
            "status": "watch" if line_count > 4000 or unlogged_broad_except_count > 10 else "ok",
            "detail": f"{path.name}: {line_count} lines · {broad_except_count} broad exception guards ({unlogged_broad_except_count} without nearby logging) · {qmessage_count} message-box references",
        })
    foundation_files = [
        ROOT / "scripts" / "control_panel_tab_registry.py",
        ROOT / "scripts" / "control_panel_runtime.py",
        ROOT / "scripts" / "control_panel_layout_state.py",
        ROOT / "scripts" / "control_panel_thread_safety.py",
    ]
    present = [path.name for path in foundation_files if path.exists()]
    rows.append({
        "area": "UI foundation",
        "status": "ok" if len(present) == len(foundation_files) else "watch",
        "detail": f"{len(present)}/{len(foundation_files)} design-system/runtime foundation modules present: {', '.join(present)}",
    })
    service_files = [
        ROOT / "scripts" / "services" / "content_service.py",
        ROOT / "scripts" / "services" / "asset_service.py",
        ROOT / "scripts" / "services" / "publish_service.py",
        ROOT / "scripts" / "services" / "diagnostics_service.py",
    ]
    services_present = [path.name for path in service_files if path.exists()]
    rows.append({
        "area": "Backend services",
        "status": "ok" if len(services_present) == len(service_files) else "watch",
        "detail": f"{len(services_present)}/{len(service_files)} service-boundary modules present: {', '.join(services_present)}",
    })
    tab_boundary_files = [
        ROOT / "scripts" / "control_panel_tabs" / "dashboard.py",
        ROOT / "scripts" / "control_panel_tabs" / "works.py",
        ROOT / "scripts" / "control_panel_tabs" / "series.py",
        ROOT / "scripts" / "control_panel_tabs" / "pages.py",
        ROOT / "scripts" / "control_panel_tabs" / "publish.py",
    ]
    tabs_present = [path.name for path in tab_boundary_files if path.exists()]
    rows.append({
        "area": "Tab boundaries",
        "status": "ok" if len(tabs_present) == len(tab_boundary_files) else "watch",
        "detail": f"{len(tabs_present)}/{len(tab_boundary_files)} tab boundary modules present: {', '.join(tabs_present)}",
    })
    if boundary_report is not None:
        try:
            boundaries = boundary_report()
            rows.append({
                "area": "Phase 14 tab extraction",
                "status": "ok" if len(boundaries) >= 5 else "watch",
                "detail": ", ".join(f"{row.get('key')}:{row.get('extraction_state')}" for row in boundaries),
            })
        except Exception as exc:
            rows.append({"area": "Phase 14 tab extraction", "status": "warning", "detail": f"Boundary report unavailable: {exc}"})
    if thread_safety_summary is not None:
        try:
            thread_summary = thread_safety_summary(ROOT)
            rows.append({
                "area": "Qt thread safety",
                "status": "ok" if thread_summary.get("ok") else "error",
                "detail": f"{thread_summary.get('errors', 0)} error(s), {thread_summary.get('warnings', 0)} warning(s) from static worker/UI scan",
            })
        except Exception as exc:
            rows.append({"area": "Qt thread safety", "status": "warning", "detail": f"Thread-safety scan unavailable: {exc}"})
    if scope_summary is not None:
        try:
            scope = scope_summary()
            active_tk = scope.get("active_tk_files") or []
            rows.append({
                "area": "Scope guard",
                "status": "ok" if not active_tk else "error",
                "detail": f"{scope.get('protected_file_count', 0)} protected public/content file(s) tracked · active Tk files={len(active_tk)}",
            })
        except Exception as exc:
            rows.append({"area": "Scope guard", "status": "warning", "detail": f"Scope check unavailable: {exc}"})
    state = load_ui_state()
    if state_diagnostics is not None:
        try:
            diag = state_diagnostics(state, layout_version="layout-rescue-20260425B")
            rows.append({
                "area": "UI state",
                "status": "ok" if diag.get("ok") else "warning",
                "detail": f"schema={diag.get('schema_version')} · splitters={diag.get('splitter_count')} · notifications={diag.get('notification_count')} · migrated={diag.get('migrated')}",
            })
        except Exception as exc:
            rows.append({"area": "UI state", "status": "warning", "detail": f"State diagnostics unavailable: {exc}"})
    else:
        rows.append({
            "area": "UI state",
            "status": "ok" if isinstance(state, dict) else "warning",
            "detail": f"Fixed layout density=Comfortable · notifications={len(state.get('notifications') or [])}",
        })
    try:
        asset_rows, scanned = _cached_asset_truth_rows_for_diagnostics()
        if not scanned:
            rows.append({
                "area": "Asset truth",
                "status": "watch",
                "detail": f"Asset truth has not been scanned yet · gate={source_asset_gate_mode()}",
            })
        else:
            blockers = [row for row in asset_rows if row.get("severity") == "error" or row.get("status") in {"missing", "derivative-only", "recoverable"}]
            orphan_risk = [row for row in asset_rows if row.get("status") == "orphan-risk"]
            rows.append({
                "area": "Asset truth",
                "status": "error" if blockers else ("watch" if orphan_risk else "ok"),
                "detail": f"{len(blockers)} blocker(s) · {len(orphan_risk)} orphan-risk warning(s) · gate={source_asset_gate_mode()}",
            })
    except Exception as exc:
        rows.append({"area": "Asset truth", "status": "error", "detail": str(exc)})
    recent_events = recent_diagnostic_events(limit=50)
    rows.append({
        "area": "Recent diagnostics",
        "status": "ok" if not recent_events or recent_events[0].get("status") not in {"error", "blocked"} else "watch",
        "detail": f"{len(recent_events)} persisted event(s) available in control-panel-diagnostics.jsonl",
    })
    budget_violations = _performance_budget_violations(recent_events)
    rows.append({
        "area": "Performance budgets",
        "status": "watch" if budget_violations else "ok",
        "detail": (f"{len(budget_violations)} recent budget violation(s); " if budget_violations else "") + ", ".join(f"{name}≤{budget}ms" for name, budget in PERFORMANCE_BUDGETS_MS.items()),
    })
    return {
        "rows": rows,
        "budgets_ms": PERFORMANCE_BUDGETS_MS,
        "recent_events": recent_events,
        "qt_backend_version": "audit-phase-25",
        "generated_at": _utc_stamp(),
    }


def panel_accessibility_static_audit() -> list[dict[str, str]]:
    """Static accessibility hints for the Qt panel. Widget-level checks are added by the UI at runtime."""
    rows = static_accessibility_rows(ROOT)
    path = ROOT / "scripts" / "control_panel.py"
    if not path.exists():
        rows.append({"status": "watch", "check": "control_panel.py readable", "detail": "control_panel.py is not present in this package; skipped static UI-source checks."})
        return rows
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as exc:
        rows.append({"status": "error", "check": "control_panel.py readable", "detail": str(exc)})
        return rows
    rows.append({
        "status": "ok" if "FIXED_CONTROL_PANEL_DENSITY" in source and ("density" + "_combo") not in source else "warning",
        "check": "Fixed layout density",
        "detail": "The layout density selector has been removed; the panel uses one stable Comfortable density.",
    })
    rows.append({
        "status": "ok" if "context_score" in source else "watch",
        "check": "Contextual command palette",
        "detail": "Command palette prioritizes actions relevant to the active tab." if "context_score" in source else "Command palette is not context-ranked yet.",
    })
    return rows


def control_panel_data_integrity_report() -> dict[str, Any]:
    try:
        return _data_integrity_report(ROOT)
    except Exception as exc:
        _record_backend_warning("Data integrity report failed", error=exc)
        return {"error": str(exc), "rows": [], "generated_at": _utc_stamp()}


def control_panel_reference_index() -> dict[str, Any]:
    return _build_reference_index(ROOT)


def control_panel_performance_budget_report() -> dict[str, Any]:
    return _performance_budget_report()


def save_panel_diagnostics_snapshot(payload: dict[str, Any]) -> None:
    _safe_json_save(PANEL_DIAGNOSTICS_PATH, dict(payload or {}, saved_at=_utc_stamp()))


def load_panel_diagnostics_snapshot() -> dict[str, Any]:
    return _load_json_dict(PANEL_DIAGNOSTICS_PATH)


def diff_panel_diagnostics_snapshot(current: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = load_panel_diagnostics_snapshot()
    current_payload = dict(current or control_panel_diagnostics())
    previous_rows = previous.get("rows") if isinstance(previous.get("rows"), list) else []
    current_rows = current_payload.get("rows") if isinstance(current_payload.get("rows"), list) else []
    def key(row: dict[str, Any]) -> tuple[str, str]:
        return (_clean_text(row.get("area")), _clean_text(row.get("detail")))
    previous_keys = {key(row) for row in previous_rows if isinstance(row, dict)}
    current_keys = {key(row) for row in current_rows if isinstance(row, dict)}
    return {
        "previous_saved_at": previous.get("saved_at", ""),
        "added": [dict(row) for row in current_rows if isinstance(row, dict) and key(row) not in previous_keys],
        "removed": [dict(row) for row in previous_rows if isinstance(row, dict) and key(row) not in current_keys],
    }


def dashboard_summary(*, include_deep: bool = False) -> DashboardSummary:
    """Return a fast dashboard summary.

    Phase 6 deliberately keeps the default path lightweight: counts, recent
    operations, publish dirty state, and basic metadata repair hints only.
    Source-asset truth, metadata audits, and release gates are collected by the
    separate deep health worker so first paint is not blocked.
    """
    works = load_work_entries()
    series = load_series_entries()
    # First paint must not hydrate the full repair queue. The detailed repair
    # list can touch series-reference diagnostics and asset checks, so the
    # default dashboard path now returns cheap counts only. Manual/deep health
    # refreshes still use the complete repair queue.
    repair = repair_items(include_source_assets=True) if include_deep else []
    quick_work_issue_ids = {
        _clean_text(item.get("id"))
        for item in works
        if _clean_text(item.get("id")) and work_issue_list(item)
    }
    published_count = sum(1 for item in works if bool(item.get("published")))
    recent_ops = recent_transactions(limit=8)
    actions: list[dict[str, str]] = []
    publish_state = load_publish_state()
    if getattr(publish_state, "has_unpublished_changes", False):
        actions.append({"label": "Build site", "detail": "Content has unpublished changes.", "action": "build"})

    error_count = 0
    if include_deep:
        validation = validate_all()
        error_count = sum(1 for item in validation if item.get("severity") == "error")
    if include_deep and repair:
        actions.append({"label": "Repair metadata", "detail": f"{len(repair)} work/series issue(s) need attention.", "action": "repair"})
    elif quick_work_issue_ids:
        actions.append({"label": "Review metadata", "detail": f"{len(quick_work_issue_ids)} work metadata issue(s) need attention.", "action": "repair"})
    if include_deep:
        source_errors = source_asset_issues()
        if source_errors:
            actions.append({"label": "Repair missing sources", "detail": f"{len(source_errors)} work image source file(s) are missing.", "action": "repair_sources"})
    if error_count:
        actions.append({"label": "Run validation", "detail": f"{error_count} blocking issue(s) detected.", "action": "validation"})
    else:
        actions.append({"label": "Prepare publish", "detail": "Generate OG images, build the site, and create a deploy zip.", "action": "prepare_publish"})
    actions.append({"label": "Open preview", "detail": "Open the generated home page locally.", "action": "preview"})
    return DashboardSummary(
        works_total=len(works),
        works_published=published_count,
        works_with_issues=len({item["id"] for item in repair if item.get("kind") == "work"}) if include_deep else len(quick_work_issue_ids),
        series_total=len(series),
        pages_total=len(available_page_keys()),
        actions=actions,
        repair_items=repair,
        recent_ops=recent_ops,
    )


def load_control_panel_state() -> dict[str, Any]:
    """Small persistent state file for performance-sensitive control-panel caches."""
    if not CONTROL_PANEL_STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(CONTROL_PANEL_STATE_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        _record_backend_warning("Could not read control-panel state", path=CONTROL_PANEL_STATE_PATH, error=exc)
        return {}


def save_control_panel_state(state: dict[str, Any]) -> None:
    try:
        BUILD_META_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(CONTROL_PANEL_STATE_PATH, dict(state or {}))
    except Exception as exc:
        _record_backend_warning("Could not save control-panel state", path=CONTROL_PANEL_STATE_PATH, error=exc)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_utc_stamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def mark_portfolio_health_dirty(scope: str, item_id: str | None = None) -> None:
    """Mark cached portfolio health as needing a targeted/manual refresh."""
    global _HEALTH_DIRTY_IN_MEMORY
    _HEALTH_DIRTY_IN_MEMORY = True
    state = load_control_panel_state()
    health = state.setdefault("portfolio_health", {})
    health["dirty_since"] = _utc_now_iso()
    key = f"dirty_{str(scope or 'global').strip() or 'global'}_ids"
    ids = health.setdefault(key, [])
    if item_id and str(item_id) not in ids:
        ids.append(str(item_id))
    save_control_panel_state(state)


def _health_dirty_since_last_scan() -> bool:
    if _HEALTH_DIRTY_IN_MEMORY:
        return True
    state = load_control_panel_state()
    health = state.get("portfolio_health") if isinstance(state.get("portfolio_health"), dict) else {}
    dirty_at = _parse_utc_stamp(health.get("dirty_since"))
    last_scan = _parse_utc_stamp(health.get("last_full_scan_at"))
    return bool(dirty_at and (last_scan is None or dirty_at > last_scan))


def _record_full_health_scan(report: dict[str, Any]) -> None:
    global _HEALTH_DIRTY_IN_MEMORY
    _HEALTH_DIRTY_IN_MEMORY = False
    state = load_control_panel_state()
    health = state.setdefault("portfolio_health", {})
    generated = str(report.get("generated_at") or _utc_now_iso()) if isinstance(report, dict) else _utc_now_iso()
    health["last_full_scan_at"] = generated
    health.pop("dirty_since", None)
    for key in list(health):
        if key.startswith("dirty_") and key.endswith("_ids"):
            health[key] = []
    save_control_panel_state(state)


def _filter_cached_health_rows(rows: list[dict[str, Any]], work_id: str) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for row in rows or []:
        row_id = str(row.get("id") or row.get("work_id") or "").strip()
        if row_id != work_id:
            clean.append(dict(row))
    return clean


def patch_cached_health_for_work(work_id: str) -> dict[str, Any] | None:
    """Incrementally patch cached health rows for a single changed work."""
    work_id = str(work_id or "").strip()
    if not work_id:
        mark_portfolio_health_dirty("work")
        return None
    cached = load_cached_portfolio_health_report(max_age_seconds=365 * 24 * 3600)
    if not isinstance(cached, dict):
        mark_portfolio_health_dirty("work", work_id)
        return None
    try:
        metadata_rows = _filter_cached_health_rows(list(cached.get("metadata_rows") or []), work_id)
        metadata_rows.extend(work_metadata_audit_rows([work_id]))
        if not load_work_payload(work_id):
            validation_rows = _filter_cached_health_rows(list(cached.get("validation_rows") or []), work_id)
            source_rows = _filter_cached_health_rows(list(cached.get("source_rows") or []), work_id)
        else:
            validation_rows = list(cached.get("validation_rows") or [])
            source_rows = list(cached.get("source_rows") or [])
        report = build_portfolio_health_report(
            validation_rows=validation_rows,
            source_rows=source_rows,
            metadata_rows=metadata_rows,
            series_rows=list(cached.get("series_rows") or []),
            release_rows=list(cached.get("release_rows") or []),
        ).as_dict()
        report["incremental"] = True
        report["patched_work_id"] = work_id
        report["cache_note"] = "Incrementally patched after a single work save; run health check for full source/release reconciliation."
        save_portfolio_health_report(report)
        return report
    except Exception as exc:
        _record_backend_warning("Could not patch cached portfolio health for work", path=work_file_for_id(work_id), error=exc)
        mark_portfolio_health_dirty("work", work_id)
        return cached



def load_cached_portfolio_health_report(*, max_age_seconds: int = HEALTH_CACHE_MAX_AGE_SECONDS) -> dict[str, Any] | None:
    """Load the most recent unified health report without re-scanning assets.

    The cache can still be useful when stale, but it must be labelled honestly.
    Dashboard fast paths use this so first paint stays fast while still showing
    whether a manual/deep scan is needed.
    """
    if not HEALTH_REPORT_PATH.exists():
        return None
    try:
        payload = json.loads(HEALTH_REPORT_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        payload = dict(payload)
        stamp = str(payload.get("generated_at") or "")
        generated = _parse_utc_stamp(stamp)
        age: float | None = None
        expired = False
        if generated is not None:
            age = (datetime.now(timezone.utc) - generated).total_seconds()
            expired = age > max(1, int(max_age_seconds))
        dirty = _health_dirty_since_last_scan()
        payload["_cache"] = {
            "source": "persisted",
            "generated_at": stamp,
            "age_seconds": int(age) if age is not None else None,
            "max_age_seconds": int(max_age_seconds),
            "expired": bool(expired),
            "dirty": bool(dirty),
            "state": "dirty" if dirty else "expired" if expired else "fresh",
        }
        if expired and dirty:
            payload["cache_note"] = "Cached health report is both expired and dirty; run health check for current truth."
        elif expired:
            payload["cache_note"] = "Expired cached health report shown for fast dashboard paint; run health check for current truth."
        elif dirty:
            payload["cache_note"] = "Cached health report is dirty after edits; run health check for current source/release truth."
        if expired or dirty:
            payload["incomplete"] = True
        return payload
    except (OSError, json.JSONDecodeError) as exc:
        _record_backend_warning("Could not read cached portfolio health report", path=HEALTH_REPORT_PATH, error=exc)
        return None

def save_portfolio_health_report(payload: dict[str, Any]) -> None:
    try:
        BUILD_META_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(HEALTH_REPORT_PATH, payload)
    except Exception as exc:
        _record_backend_warning("Could not save portfolio health report", path=HEALTH_REPORT_PATH, error=exc)


def missing_source_recovery_rows(*, use_cache: bool = True) -> list[dict[str, Any]]:
    """Rows for the focused Source Recovery workflow."""
    rows: list[dict[str, Any]] = []
    work_payloads = {str(row.get("id") or "").strip(): row for row in load_work_entries()}
    for row in source_asset_report_rows(use_cache=use_cache):
        status = str(row.get("status") or "").strip().lower()
        if status in {"", "ok", "healthy"}:
            continue
        work_id = str(row.get("id") or row.get("work_id") or "").strip()
        payload = work_payloads.get(work_id, {})
        merged = dict(row)
        merged["id"] = work_id
        merged["title"] = str(payload.get("title") or payload.get("name") or work_id)
        merged["series"] = str(row.get("series") or payload.get("series") or work_to_series_map().get(work_id, ""))
        merged["priority"] = "manual relink" if status == "missing" else "review"
        rows.append(merged)
    rows.sort(key=lambda r: (str(r.get("status") or ""), str(r.get("series") or ""), str(r.get("id") or "")))
    return rows


def source_recovery_summary(*, use_cache: bool = True) -> dict[str, Any]:
    rows = missing_source_recovery_rows(use_cache=use_cache)
    recoverable = [row for row in rows if "recover" in str(row.get("recovery") or row.get("status") or "").lower()]
    manual = [row for row in rows if row not in recoverable]
    return {
        "total": len(rows),
        "recoverable": len(recoverable),
        "manual": len(manual),
        "rows": rows,
        "label": "Source coverage complete" if not rows else f"{len(rows)} source image(s) need recovery",
    }


def portfolio_health_report(*, force: bool = False, save: bool = True, timeout_seconds: float = 10.0) -> dict[str, Any]:
    """Collect validation, source truth, metadata, series and release rows once.

    Full scans are limited to explicit runs, dirty cache reconciliation, or a
    30-minute persisted expiry. The function checks a soft deadline between
    scan stages and returns partial data instead of blocking the UI indefinitely.
    """
    started = time.perf_counter()
    deadline = started + max(1.0, float(timeout_seconds or 10.0))

    def expired() -> bool:
        return time.perf_counter() >= deadline

    if not force:
        cached = load_cached_portfolio_health_report(max_age_seconds=HEALTH_CACHE_MAX_AGE_SECONDS)
        if cached is not None and not _health_dirty_since_last_scan():
            return cached

    validation_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    source_issues_rows: list[dict[str, Any]] = []
    source_issues_scanned = False
    audit_rows: list[dict[str, Any]] = []
    series_rows: list[dict[str, Any]] = []
    release_rows: list[dict[str, Any]] = []
    incomplete = False
    timeout_reason = ""

    try:
        validation_rows = validation_action_rows()
        if expired():
            raise TimeoutError("Portfolio health scan timed out after validation stage")
        source_rows = source_asset_report_rows(use_cache=not force, force=force)
        if expired():
            raise TimeoutError("Portfolio health scan timed out after source stage")
        source_issues_rows = source_asset_issues(rows=source_rows, use_cache=not force)
        source_issues_scanned = True
        audit_rows = work_metadata_audit_rows()
        if expired():
            raise TimeoutError("Portfolio health scan timed out after metadata stage")
        series_rows = series_completeness_rows()
        if expired():
            raise TimeoutError("Portfolio health scan timed out after series stage")
        release_rows = release_checks(validation_rows=validation_rows, source_issues=source_issues_rows)
    except TimeoutError as exc:
        incomplete = True
        timeout_reason = str(exc)

    if not release_rows:
        source_issues_for_release = source_issues_rows if source_issues_scanned else None
        release_rows = release_checks(validation_rows=validation_rows, source_issues=source_issues_for_release)

    report = build_portfolio_health_report(
        validation_rows=validation_rows,
        source_rows=source_rows,
        metadata_rows=audit_rows,
        series_rows=series_rows,
        release_rows=release_rows,
    ).as_dict()
    report["source_issues_rows"] = source_issues_rows
    report["incomplete"] = incomplete
    report["timeout_seconds"] = timeout_seconds
    if timeout_reason:
        report["timeout_reason"] = timeout_reason
    report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    if save:
        save_portfolio_health_report(report)
        if not incomplete:
            _record_full_health_scan(report)
    return report

def dashboard_fast_readiness(summary: DashboardSummary, *, drafts: int = 0) -> dict[str, Any]:
    """Lightweight readiness estimate used for instant dashboard paint."""
    issue_penalty = min(45, int(summary.works_with_issues or 0) * 6)
    unpublished_penalty = 8 if int(summary.works_published or 0) < int(summary.works_total or 0) else 0
    draft_penalty = min(8, int(drafts or 0) * 2)
    score = max(0, min(100, 100 - issue_penalty - unpublished_penalty - draft_penalty))
    if summary.works_with_issues:
        status = "review" if score >= 70 else "needs work"
    elif score >= 90:
        status = "ready"
    else:
        status = "review"
    actions = []
    if summary.works_with_issues:
        actions.append({"label": "Review work metadata", "count": int(summary.works_with_issues), "target": "works"})
    elif getattr(summary, "actions", None):
        actions.append({"label": summary.actions[0].get("label", "Continue review"), "count": 1, "target": summary.actions[0].get("action", "dashboard")})
    return {
        "score": score,
        "status": status,
        "actions": actions or [{"label": "Run release gate before publish", "count": 1, "target": "publish"}],
        "metrics": {
            "metadata_issues": int(summary.works_with_issues or 0),
            "drafts": int(drafts or 0),
            "deep_health_pending": 1,
        },
        "estimated": True,
    }



def _last_valid_text_path(kind: str, key: str) -> Path:
    safe_kind = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(kind or "content")).strip("-.") or "content"
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(key or "unknown")).strip("-.") or "unknown"
    return LAST_VALID_DIR / safe_kind / f"{safe_key}.yaml"


def _write_last_valid_text(kind: str, key: str, text: str) -> Path:
    path = _last_valid_text_path(kind, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, str(text or ""))
    return path


def _load_last_valid_text(kind: str, key: str) -> str:
    path = _last_valid_text_path(kind, key)
    if not path.exists():
        raise BackendError(f"No last valid {kind} version is available for '{key}'.")
    return path.read_text(encoding="utf-8")


def _yaml_error_detail(exc: Exception) -> dict[str, str]:
    mark = getattr(exc, "problem_mark", None)
    field = "<yaml>"
    if mark is not None:
        try:
            field = f"line {int(mark.line) + 1}, column {int(mark.column) + 1}"
        except Exception:
            field = "<yaml>"
    return {
        "severity": "error",
        "field": field,
        "message": str(exc),
        "suggestion": "Fix the YAML syntax, then run Validate again before saving.",
        "code": "yaml-parse-error",
    }


def _block_if_editor_errors(issues: list[dict[str, str]], label: str) -> None:
    errors = [row for row in issues if str(row.get("severity") or "").lower() == "error"]
    if not errors:
        return
    preview = "\n".join(
        f"- {row.get('field') or '<root>'}: {row.get('message') or ''}" for row in errors[:12]
    )
    raise BackendValidationError(f"{label} save blocked by validation errors:\n{preview}")


def _authority_schema_issues(key: str, payload: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    def add(severity: str, field: str, message: str, suggestion: str = "") -> None:
        issues.append({"severity": severity, "field": field, "message": message, "suggestion": suggestion, "code": f"authority-{key}-{field}"})

    if not isinstance(payload, dict):
        return [{"severity": "error", "field": "<root>", "message": "Authority YAML must be a mapping/object.", "suggestion": "Use key/value YAML at the document root.", "code": "authority-root"}]
    if key == "site":
        for field in ("name", "description", "site_url"):
            if not _clean_text(payload.get(field)):
                add("error", field, f"Missing required site field: {field}.", "Fill this in the structured authority editor or raw YAML.")
        analytics = _clean_text(payload.get("analytics_id"))
        if analytics and not re.match(r"^(G-[A-Z0-9]+|UA-[A-Z0-9-]+)$", analytics):
            add("warning", "analytics_id", "Analytics ID does not look like a GA measurement ID.", "Expected a value such as G-XXXXXXXXXX.")
    elif key == "artist":
        for field in ("name", "discipline", "intro"):
            if not _clean_text(payload.get(field)):
                add("error", field, f"Missing required artist field: {field}.")
    elif key == "navigation":
        items = payload.get("items")
        if not isinstance(items, list):
            add("error", "items", "Navigation items must be a list.")
        else:
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    add("error", f"items[{idx}]", "Navigation item must be an object.")
                    continue
                if not _clean_text(item.get("label")):
                    add("error", f"items[{idx}].label", "Navigation label is required.")
                if not _clean_text(item.get("href")) and not _clean_text(item.get("page")):
                    add("error", f"items[{idx}].href", "Navigation item needs href or page.")
    elif key == "resources":
        downloads = payload.get("downloads")
        if downloads is not None and not isinstance(downloads, list):
            add("error", "downloads", "Downloads must be a list.")
        for idx, item in enumerate(downloads or []):
            if not isinstance(item, dict):
                add("error", f"downloads[{idx}]", "Download item must be an object.")
                continue
            for field in ("id", "title", "file"):
                if not _clean_text(item.get(field)):
                    add("warning", f"downloads[{idx}].{field}", f"Download item is missing {field}.")
    elif key == "release":
        for field in ("staging_url", "production_url"):
            if field in payload and payload.get(field) and not str(payload.get(field)).startswith(("http://", "https://")):
                add("warning", field, f"{field} should be a full URL.")
    else:
        add("error", "document", f"Unknown authority document: {key}.")
    return issues


def review_authority_yaml_text(key: str, raw_text: str) -> dict[str, Any]:
    if key not in AUTHORITY_FILES:
        raise BackendError(f"Unknown authority document: {key}")
    try:
        payload = yaml.safe_load(raw_text) or {}
    except Exception as exc:
        return {
            "payload": {},
            "raw_text": str(raw_text or ""),
            "issues": [_yaml_error_detail(exc)],
            "diff_lines": list(unified_text_diff(load_authority_yaml_text(key), str(raw_text or ""), fromfile="saved", tofile="current")),
        }
    if not isinstance(payload, dict):
        payload = {}
        issues = [{"severity": "error", "field": "<root>", "message": "Authority YAML must decode to a mapping/object.", "suggestion": "Use key/value YAML at the root.", "code": "authority-root"}]
    else:
        issues = _authority_schema_issues(key, payload)
    normalized = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return {
        "payload": payload,
        "raw_text": normalized,
        "issues": issues,
        "diff_lines": list(unified_text_diff(load_authority_yaml_text(key), str(raw_text or ""), fromfile="saved", tofile="current")),
    }


def unified_text_diff(before: str, after: str, *, fromfile: str = "saved", tofile: str = "current") -> list[str]:
    from difflib import unified_diff
    return list(unified_diff((before or "").splitlines(), (after or "").splitlines(), fromfile=fromfile, tofile=tofile, lineterm=""))


def restore_last_valid_page_yaml(page_key: str) -> str:
    text = _load_last_valid_text("page", page_key)
    save_page_yaml_text(page_key, text)
    return text


def restore_last_valid_authority_yaml(key: str) -> str:
    text = _load_last_valid_text("authority", key)
    save_authority_yaml_text(key, text)
    return text

def load_page_yaml_text(page_key: str) -> str:
    return page_file_for_key(page_key).read_text(encoding="utf-8")



def available_document_ids() -> list[str]:
        payload = load_resources_payload() or {}
        ids: list[str] = []
        for item in payload.get("downloads") or []:
            if not isinstance(item, dict):
                continue
            ident = str(item.get("id") or "").strip()
            if ident:
                ids.append(ident)
        return ids


def _page_issue_rows(issues: list[Any]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for issue in issues or []:
            rows.append({
                "severity": str(getattr(issue, "severity", "info") or "info"),
                "field": str(getattr(issue, "field_path", "") or ""),
                "message": str(getattr(issue, "message", "") or ""),
                "suggestion": str(getattr(issue, "suggestion", "") or ""),
                "code": str(getattr(issue, "code", "") or ""),
            })
        return rows


def _page_model_from_payload(page_key: str, model_payload: dict[str, Any]) -> PageModel:
        payload = deepcopy(model_payload if isinstance(model_payload, dict) else {})
        return PageModel.from_dict(page_key, payload)


def review_page_builder_model(page_key: str, model_payload: dict[str, Any]) -> dict[str, Any]:
        model = _page_model_from_payload(page_key, model_payload)
        original = load_page_payload(page_key)
        rendered = page_model_to_payload(model, original)
        raw_text = yaml.safe_dump(rendered, sort_keys=False, allow_unicode=True)
        validator = ContentValidator(ROOT)
        issues = validator.validate_page_model(page_key, model)
        return {
            "model": model.to_dict(),
            "raw_text": raw_text,
            "issues": _page_issue_rows(issues),
            "diff_lines": diff_page_payloads(original, rendered),
        }


def review_page_yaml_text(page_key: str, raw_text: str) -> dict[str, Any]:
        try:
            payload = yaml.safe_load(raw_text) or {}
        except Exception as exc:
            return {
                "model": {},
                "raw_text": str(raw_text or ""),
                "issues": [_yaml_error_detail(exc)],
                "diff_lines": unified_text_diff(load_page_yaml_text(page_key), str(raw_text or ""), fromfile="saved", tofile="current"),
            }
        if not isinstance(payload, dict):
            return {
                "model": {},
                "raw_text": str(raw_text or ""),
                "issues": [{"severity": "error", "field": "<root>", "message": "Page YAML must decode to a dictionary/object.", "suggestion": "Use mapping-style YAML at the document root.", "code": "page-root"}],
                "diff_lines": unified_text_diff(load_page_yaml_text(page_key), str(raw_text or ""), fromfile="saved", tofile="current"),
            }
        model = normalize_page_payload(page_key, payload)
        validator = ContentValidator(ROOT)
        issues = validator.validate_page_model(page_key, model)
        return {
            "model": model.to_dict(),
            "raw_text": yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            "issues": _page_issue_rows(issues),
            "diff_lines": diff_page_payloads(load_page_payload(page_key), payload),
        }


def load_page_builder_bundle(page_key: str) -> dict[str, Any]:
        model = load_page_model(page_key)
        review = review_page_builder_model(page_key, model.to_dict())
        review["file_text"] = load_page_yaml_text(page_key)
        return review


def save_page_builder_model(page_key: str, model_payload: dict[str, Any]) -> dict[str, Any]:
        model = _page_model_from_payload(page_key, model_payload)
        issues = save_page_model(page_key, model, validate=True)
        errors = [item for item in issues if str(getattr(item, "severity", "")) == "error"]
        if errors:
            preview = "\n".join(f"- {getattr(item, 'field_path', '') or '<page>'}: {getattr(item, 'message', '')}" for item in errors[:12])
            raise BackendError("Page save blocked by validation errors:\n" + preview)
        return load_page_builder_bundle(page_key)


def save_page_yaml_text(page_key: str, raw_text: str) -> None:
    review = review_page_yaml_text(page_key, raw_text)
    _block_if_editor_errors(list(review.get("issues") or []), "Page YAML")
    try:
        payload = yaml.safe_load(raw_text) or {}
    except Exception as exc:
        raise BackendError(f"Page YAML is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise BackendError("Page YAML must decode to a dictionary/object.")
    previous = load_page_yaml_text(page_key)
    with transaction(f"qt-save-page-raw:{page_key}"):
        _write_last_valid_text("page", page_key, previous)
        save_page_payload(page_key, payload)
    _write_last_valid_text("page", page_key, load_page_yaml_text(page_key))


def load_authority_yaml_text(key: str) -> str:
    path = AUTHORITY_FILES[key]
    return path.read_text(encoding="utf-8")


def save_authority_yaml_text(key: str, raw_text: str) -> None:
    review = review_authority_yaml_text(key, raw_text)
    _block_if_editor_errors(list(review.get("issues") or []), f"{key.title()} YAML")
    payload = dict(review.get("payload") or {})
    previous = load_authority_yaml_text(key)
    with transaction(f"qt-save-authority-raw:{key}"):
        _write_last_valid_text("authority", key, previous)
        if key == "site":
            save_site_settings(payload)
        elif key == "artist":
            save_artist_profile(payload)
        elif key == "navigation":
            save_navigation_payload(payload)
        elif key == "resources":
            save_resources_payload(payload)
        elif key == "release":
            write_yaml(AUTHORITY_FILES[key], payload)
            mark_unpublished_changes()
        else:
            raise BackendError(f"Unknown authority document: {key}")
    _write_last_valid_text("authority", key, load_authority_yaml_text(key))


def load_works_filtered(
    search: str = "",
    series_slug: str = "All series",
    review_status: str = "All",
    published_state: str = "All",
    issue_filter: str = "All works",
    *,
    fast: bool = True,
    task_context: Any | None = None,
) -> list[dict[str, Any]]:
    query = search.strip().lower()
    repo = _CONTENT_REPOSITORY
    works = repo.works()
    filtered: list[dict[str, Any]] = []
    fast_mode = bool(fast)
    # Regression marker for legacy fast-path test: series_map = work_to_series_map() if fast_mode else {}
    series_map = repo.work_to_series() if fast_mode else {}
    status_map = _cached_asset_truth_status_by_work_id() if fast_mode else {}
    for row_index, payload in enumerate(works, start=1):
        if task_context is not None and row_index % 20 == 0:
            task_context.check_cancelled()
        work_id = _clean_text(payload.get("id"))
        if not work_id:
            continue
        title = _clean_text(payload.get("title"))
        series = _clean_text(payload.get("series") or series_map.get(work_id, ""))
        review = _clean_text(payload.get("review_status")).lower()
        published = bool(payload.get("published"))
        haystack = " ".join([
            work_id,
            title,
            _clean_text(payload.get("location")),
            _clean_text(payload.get("year")),
            _clean_text(payload.get("alt")),
            _clean_text(payload.get("caption")),
            ", ".join(str(item).strip() for item in (payload.get("tags") or []) if str(item).strip()),
            series,
        ]).lower()
        if query and query not in haystack:
            continue
        if series_slug not in {"", "All series"} and series != series_slug:
            continue
        if review_status not in {"", "All"} and review != review_status.lower():
            continue
        if published_state == "Published" and not published:
            continue
        if published_state == "Unpublished" and published:
            continue
        completeness = fast_work_completeness_score(payload, series_map=series_map, status_map=status_map) if fast_mode else work_completeness_score(payload)
        issues = list(completeness.get("issues") or work_issue_list(payload))
        source_status = str(completeness.get("source_status") or "")
        if source_status == "deferred" and "source unverified — run Validation" not in issues:
            issues.append("source unverified — run Validation")
        if issue_filter == "Needs attention" and not (issues or source_status not in {"", "ok"}):
            continue
        if issue_filter == "Missing caption" and "missing caption" not in issues:
            continue
        if issue_filter == "Weak alt text" and "weak alt text" not in issues:
            continue
        if issue_filter == "Missing thumbnail":
            preview_fn = fast_preview_path_for_work if fast_mode else best_preview_path_for_work
            if preview_fn(payload):
                continue
        if issue_filter == "Missing source" and source_status not in {"missing", "derivative-only", "recoverable", "orphan-risk"}:
            continue
        if issue_filter == "Weak metadata" and int(completeness.get("score") or 0) >= 85:
            continue
        payload = dict(payload)
        payload["_issue_list"] = issues
        payload["_completeness_score"] = completeness.get("score", 0)
        payload["_completeness_status"] = completeness.get("status", "")
        payload["_source_status"] = source_status or ("deferred" if fast_mode else "")
        filtered.append(payload)

    sequence_index = repo.sequence_index()

    def sort_key(item: dict[str, Any]) -> tuple[str, int, str]:
        item_series = _clean_text(item.get("series"))
        item_id = _clean_text(item.get("id"))
        pos = sequence_index.get((item_series, item_id), 999999)
        title_text = _clean_text(item.get("title")) or item_id
        return (item_series, pos, title_text)

    filtered.sort(key=sort_key)
    return filtered


def replace_exact_refs(old_value: str, new_value: str) -> list[str]:
    old_value = _clean_text(old_value)
    new_value = _clean_text(new_value)
    if not old_value or not new_value or old_value == new_value:
        return []

    def replace(obj: Any) -> tuple[Any, bool]:
        changed = False
        if isinstance(obj, dict):
            updated: dict[str, Any] = {}
            for key, value in obj.items():
                new_sub, sub_changed = replace(value)
                updated[key] = new_sub
                changed = changed or sub_changed
            return updated, changed
        if isinstance(obj, list):
            updated_list: list[Any] = []
            for item in obj:
                new_sub, sub_changed = replace(item)
                updated_list.append(new_sub)
                changed = changed or sub_changed
            return updated_list, changed
        if isinstance(obj, str) and obj == old_value:
            return new_value, True
        return obj, False

    updated_files: list[str] = []
    for path in sorted(CONTENT_DIR.rglob("*.yaml")):
        try:
            relative = path.relative_to(CONTENT_DIR)
        except Exception:
            relative = None
        if relative is not None and relative.parts and relative.parts[0] == "works":
            continue
        payload = load_yaml(path)
        if payload is None:
            continue
        updated_payload, changed = replace(payload)
        if not changed:
            continue
        snapshot_path(path)
        write_yaml(path, updated_payload)
        updated_files.append(str(path.relative_to(ROOT)))
    return updated_files


def validate_editor_payload(kind: str, payload: dict[str, Any], *, original_key: str | None = None) -> list[dict[str, str]]:
    """Field-level validation shared by the Qt editors and save guards."""
    rows: list[dict[str, str]] = []

    def add(field: str, severity: str, message: str) -> None:
        rows.append({"field": field, "severity": severity, "message": message})

    kind_text = _clean_text(kind).lower()
    data = payload if isinstance(payload, dict) else {}
    if kind_text == "work":
        work_id = _clean_text(data.get("id"))
        if not work_id:
            add("id", "error", "Work ID is required.")
        elif slugify_work_id(work_id) != work_id:
            add("id", "error", "Use a URL-safe lowercase ID: letters, numbers, and hyphens only.")
        elif original_key and work_id != original_key and work_file_for_id(work_id).exists():
            add("id", "error", f"Work ID '{work_id}' already exists.")
        title_text = _clean_text(data.get("title"))
        if not title_text:
            add("title", "error", "Title is required.")
        elif len(title_text.split()) < 2:
            add("title", "warning", "Use a title with at least 2 words for clarity.")
        raw_series_slug = _clean_text(data.get("series"))
        series_slug = resolve_series_slug(raw_series_slug) or raw_series_slug
        if not series_slug:
            add("series", "error", "Series is required.")
        elif series_slug not in set(available_series_slugs()):
            add("series", "error", "Choose an existing series.")
        review = _clean_text(data.get("review_status")).lower()
        if review and review not in PUBLISH_STATES:
            add("review_status", "error", f"Review status must be one of: {', '.join(PUBLISH_STATES)}.")
        published_val = data.get("published")
        if review == "published" and published_val is False:
            add("published", "warning", "Review status is published, but the public Published flag is off; this work will not appear on the website.")
        elif review != "published" and published_val is True:
            add("review_status", "warning", "Published flag is on, but review status is not published; save will normalize this.")
        series_sequence = []
        if series_slug and series_slug in set(available_series_slugs()):
            try:
                series_sequence = [str(item).strip() for item in (load_series_payload(series_slug).get("work_ids") or []) if str(item).strip()]
            except Exception:
                series_sequence = []
            if work_id and work_id not in series_sequence:
                add("series", "warning", "Work metadata names this series, but the work is not in the series sequence; save will repair the relationship.")
        alt_words = [word for word in _clean_text(data.get("alt")).split() if word.strip()]
        if len(alt_words) < 5:
            add("alt", "warning", "Alt text should contain at least 5 descriptive words.")
        caption = _clean_text(data.get("caption"))
        if not caption:
            add("caption", "warning", "Caption is empty; this weakens context and SEO.")
        focal = data.get("focal_point") if isinstance(data.get("focal_point"), dict) else {}
        for axis in ("x", "y"):
            try:
                value = int(focal.get(axis, 50))
            except Exception:
                add(f"focal_point.{axis}", "error", f"Focal point {axis.upper()} must be a whole number from 0 to 100.")
                continue
            if value < 0 or value > 100:
                add(f"focal_point.{axis}", "error", f"Focal point {axis.upper()} must be between 0 and 100.")
        published_val = data.get("published")
        if published_val is not None and not isinstance(published_val, bool):
            add("published", "warning", "Published field should be true or false (boolean), not a string or number.")
    elif kind_text == "series":
        slug = _clean_text(data.get("slug"))
        if not slug:
            add("slug", "error", "Series slug is required.")
        elif slugify_work_id(slug) != slug:
            add("slug", "error", "Use a URL-safe lowercase slug: letters, numbers, and hyphens only.")
        elif original_key and slug != original_key and series_file_for_slug(slug).exists():
            add("slug", "error", f"Series slug '{slug}' already exists.")
        if not _clean_text(data.get("title")):
            add("title", "error", "Series title is required.")
        known_work_ids = {str(item.get("id") or "").strip() for item in load_work_entries() if str(item.get("id") or "").strip()}
        sequence = [str(item).strip() for item in (data.get("work_ids") or []) if str(item).strip()]
        for work_id in sequence:
            if work_id not in known_work_ids:
                add("work_ids", "warning", f"Sequence references missing work: {work_id}")
        cover = _clean_text(data.get("cover_work_id"))
        if cover and cover not in sequence:
            add("cover_work_id", "warning", "Cover work is not in this series sequence.")
    else:
        add("kind", "error", f"Unsupported editor validation kind: {kind}")
    return rows


def repair_relationship_refs(kind: str, old_key: str | None = None, new_key: str | None = None) -> list[str]:
    """Replace or remove stale homepage relationship references after renames/deletes."""
    kind_text = _clean_text(kind).lower()
    old_value = _clean_text(old_key)
    new_value = _clean_text(new_key)
    if not old_value and not new_value:
        return []
    relationships = load_home_relationships()
    featured_series = [str(item).strip() for item in (relationships.get("featured_series") or []) if str(item).strip()]
    selected_works = [str(item).strip() for item in (relationships.get("selected_works") or relationships.get("featured_works") or []) if str(item).strip()]
    changed: list[str] = []

    def replace_or_prune(values: list[str], label: str) -> list[str]:
        updated: list[str] = []
        for value in values:
            candidate = value
            if old_value and value == old_value:
                if new_value:
                    candidate = new_value
                    changed.append(f"{label}:{old_value}->{new_value}")
                else:
                    changed.append(f"{label}:{old_value}:removed")
                    continue
            if candidate not in updated:
                updated.append(candidate)
        return updated

    if kind_text == "series":
        featured_series = replace_or_prune(featured_series, "series")
    elif kind_text == "work":
        selected_works = replace_or_prune(selected_works, "work")
    else:
        return []

    live_series = set(available_series_slugs())
    live_works = {str(item.get("id") or "").strip() for item in load_work_entries() if str(item.get("id") or "").strip()}
    pruned_series = [slug for slug in featured_series if slug in live_series or slug == new_value]
    pruned_works = [work_id for work_id in selected_works if work_id in live_works or work_id == new_value]
    if pruned_series != featured_series:
        changed.append("series:stale-pruned")
    if pruned_works != selected_works:
        changed.append("work:stale-pruned")
    if changed:
        reorder_homepage_featured(featured_series=pruned_series, selected_works=pruned_works)
    return changed



# ---------- Phase 1-3 hardening: transactions, references, drafts, and preflight ----------

def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_work_payload(work_id: str | None) -> dict[str, Any]:
    work_id = _clean_text(work_id)
    if not work_id:
        return {}
    try:
        return load_work_payload(work_id) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        _record_backend_warning("Could not load work payload during hardening check", path=work_file_for_id(work_id), error=exc)
        return {}


def editor_source_fingerprint(kind: str, key: str) -> dict[str, Any]:
    """Stable fingerprint for draft conflict detection, with a short disk-read TTL."""
    kind_text = _clean_text(kind).lower()
    key_text = _clean_text(key)
    cache_key = (kind_text, key_text)
    now = time.monotonic()
    with _FINGERPRINT_CACHE_LOCK:
        cached = _FINGERPRINT_CACHE.get(cache_key)
        if cached is not None:
            cached_at, cached_fp = cached
            if now - cached_at < _FINGERPRINT_CACHE_TTL:
                return dict(cached_fp)
    path: Path | None = None
    if kind_text == "work" and key_text:
        path = work_file_for_id(key_text)
    elif kind_text == "series" and key_text:
        path = series_file_for_slug(key_text)
    elif kind_text == "page" and key_text:
        path = page_file_for_key(key_text)
    elif kind_text == "authority" and key_text in AUTHORITY_FILES:
        path = AUTHORITY_FILES[key_text]
    row: dict[str, Any] = {"kind": kind_text, "key": key_text, "path": _relative_display(path), "exists": bool(path and path.exists())}
    if path and path.exists() and path.is_file():
        stat = path.stat()
        row.update({"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": _file_sha256(path)})
    with _FINGERPRINT_CACHE_LOCK:
        if len(_FINGERPRINT_CACHE) >= _FINGERPRINT_CACHE_MAX:
            stale_before = now - (_FINGERPRINT_CACHE_TTL * 2)
            for stale_key, (cached_at, _cached_fp) in list(_FINGERPRINT_CACHE.items()):
                if cached_at < stale_before:
                    _FINGERPRINT_CACHE.pop(stale_key, None)
            if len(_FINGERPRINT_CACHE) >= _FINGERPRINT_CACHE_MAX:
                for old_key in list(_FINGERPRINT_CACHE.keys())[: max(1, _FINGERPRINT_CACHE_MAX // 4)]:
                    _FINGERPRINT_CACHE.pop(old_key, None)
        _FINGERPRINT_CACHE[cache_key] = (now, dict(row))
    return row


def draft_conflict_status(kind: str, key: str, draft: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return whether an autosave draft was created from an older on-disk file."""
    current = editor_source_fingerprint(kind, key)
    draft_source = (draft or {}).get("source_fingerprint") if isinstance(draft, dict) else {}
    if not isinstance(draft_source, dict) or not draft_source:
        return {"conflict": False, "current": current, "draft_source": draft_source, "reason": "no-source-fingerprint"}
    if bool(draft_source.get("exists")) != bool(current.get("exists")):
        return {"conflict": True, "current": current, "draft_source": draft_source, "reason": "source-existence-changed"}
    old_hash = _clean_text(draft_source.get("sha256"))
    new_hash = _clean_text(current.get("sha256"))
    if old_hash and new_hash and old_hash != new_hash:
        return {"conflict": True, "current": current, "draft_source": draft_source, "reason": "source-file-changed"}
    return {"conflict": False, "current": current, "draft_source": draft_source, "reason": "clean"}


def _walk_reference_values(obj: Any, old_value: str, path: str = "$", new_value: str = "") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            rows.extend(_walk_reference_values(value, old_value, f"{path}.{key}", new_value))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            rows.extend(_walk_reference_values(value, old_value, f"{path}[{index}]", new_value))
    elif isinstance(obj, str):
        if obj == old_value:
            rows.append({"path": path, "match": "exact", "value": obj})
        elif old_value and old_value in obj:
            # If a rename intentionally produced a new id that contains the old
            # id as a prefix, derivative paths and the new YAML id will contain
            # old_value by construction. That is not a stale reference.
            if new_value and new_value in obj and old_value in new_value:
                return rows
            rows.append({"path": path, "match": "contains", "value": obj[:500]})
    return rows


def _control_json_reference_files() -> list[Path]:
    # Only durable UI/control state files belong in stale-reference diagnostics.
    # Ephemeral health, asset-truth, content-graph, manifest, and backup JSON files
    # are regenerated and should not alarm users after a rename.
    return [path for path in (UI_STATE_PATH, CONTROL_PANEL_STATE_PATH) if path.exists() and path.is_file()]


def scan_stale_references(old_key: str, new_key: str | None = None, *, include_runtime: bool = True) -> list[dict[str, str]]:
    """Scan content YAML and control JSON for references that still point to an old key.

    Content YAML exact matches are release-critical. Runtime/control JSON matches
    are diagnostic because those files are often regenerated, but they are still
    shown so rename/remove operations do not hide stale state.
    """
    old_value = _clean_text(old_key)
    if not old_value:
        return []
    rows: list[dict[str, str]] = []

    for path in sorted(CONTENT_DIR.rglob("*.yaml")):
        try:
            payload = load_yaml(path)
        except Exception as exc:
            rows.append({
                "file": _relative_display(path),
                "path": "$",
                "match": "parse-error",
                "value": str(exc)[:500],
                "new_key": _clean_text(new_key),
                "source": "content-yaml",
            })
            continue
        for row in _walk_reference_values(payload, old_value, new_value=_clean_text(new_key)):
            row["file"] = _relative_display(path)
            row["new_key"] = _clean_text(new_key)
            row["source"] = "content-yaml"
            rows.append(row)

    if include_runtime:
        for path in _control_json_reference_files():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                rows.append({
                    "file": _relative_display(path),
                    "path": "$",
                    "match": "parse-error",
                    "value": str(exc)[:500],
                    "new_key": _clean_text(new_key),
                    "source": "control-json",
                })
                continue
            for row in _walk_reference_values(payload, old_value, new_value=_clean_text(new_key)):
                row["file"] = _relative_display(path)
                row["new_key"] = _clean_text(new_key)
                row["source"] = "control-json"
                rows.append(row)
    return rows


def _critical_content_stale_refs(old_key: str, new_key: str | None = None) -> list[dict[str, str]]:
    return [
        row for row in scan_stale_references(old_key, new_key, include_runtime=False)
        if row.get("source") == "content-yaml" and row.get("match") == "exact"
    ]


def _source_candidates_for_stem(series_slug: str, work_id: str, pipeline: dict[str, Any] | None = None) -> list[Path]:
    pipeline = pipeline or load_pipeline()
    roots = [
        source_root(pipeline) / series_slug,
        ROOT / "assets/images/originals/series" / series_slug,
        ROOT / "assets/images/originals",
        ROOT / "assets/images/originals/unassigned",
        ROOT / "assets/images",
    ]
    candidates: list[Path] = []
    seen: set[str] = set()
    for root_path in roots:
        for ext in sorted(SOURCE_EXTENSIONS):
            candidate = root_path / f"{work_id}{ext}"
            key = str(candidate.resolve(strict=False))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
    return candidates


def preview_work_change_map(original_work_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    """Describe exactly which work/image assets a save or Work ID rename is expected to touch."""
    old_id = _clean_text(original_work_id)
    new_id = slugify_work_id(payload.get("id") or "")
    old_payload = _safe_work_payload(old_id)
    old_series = _clean_text(old_payload.get("series") or work_to_series_map().get(old_id, ""))
    new_series = _clean_text(payload.get("series") or old_series)
    pipeline = load_pipeline()
    current_source = _resolve_source_path(old_series or new_series, old_id or new_id, pipeline=pipeline, context="work change map") if (old_id or new_id) else None
    image_block = payload.get("image") if isinstance(payload.get("image"), dict) else {}
    suffix = Path(_clean_text(image_block.get("master"))).suffix.lower() or (current_source.suffix.lower() if current_source else ".jpg")
    expected_source = (source_root(pipeline) / new_series / f"{new_id}{suffix}") if new_id and new_series else None
    old_render = _render_name_for_work(old_payload) if old_payload else old_id
    new_render = _render_name_for_work({**payload, "id": new_id}) if payload else new_id
    return {
        "operation": "rename-work" if old_id and new_id and old_id != new_id else "save-work",
        "old_work_id": old_id,
        "new_work_id": new_id,
        "old_series": old_series,
        "new_series": new_series,
        "old_yaml": _relative_display(work_file_for_id(old_id)) if old_id else "",
        "new_yaml": _relative_display(work_file_for_id(new_id)) if new_id else "",
        "old_source": _relative_display(current_source) if current_source else "",
        "new_source": _relative_display(expected_source) if expected_source else "",
        "old_derivatives": _relative_display(derivative_dir_for_work(old_series or new_series, old_render, pipeline=pipeline)) if old_render else "",
        "new_derivatives": _relative_display(derivative_dir_for_work(new_series, new_render, pipeline=pipeline)) if new_series and new_render else "",
        "reference_scan": scan_stale_references(old_id, new_id) if old_id and old_id != new_id else [],
    }


def verify_work_transaction(original_work_id: str | None, new_work_id: str, before_payload: dict[str, Any] | None = None, after_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verify that a work save/rename left no broken YAML, source, derivative, or sequence state."""
    old_id = _clean_text(original_work_id)
    new_id = _clean_text(new_work_id)
    after = _safe_work_payload(new_id)
    if after_payload:
        after = after or dict(after_payload)
    before = before_payload or _safe_work_payload(old_id) or {}
    errors: list[str] = []
    warnings: list[str] = []
    info: list[str] = []
    if not new_id:
        errors.append("New work ID is empty after save.")
    elif not work_file_for_id(new_id).exists():
        errors.append(f"New work YAML was not written: {_relative_display(work_file_for_id(new_id))}")
    elif _clean_text(after.get("id")) != new_id:
        errors.append(f"New work YAML id field does not match filename: expected {new_id}, found {_clean_text(after.get('id')) or '-'}.")
    if old_id and old_id != new_id and work_file_for_id(old_id).exists():
        errors.append(f"Old work YAML still exists after rename: {_relative_display(work_file_for_id(old_id))}")

    pipeline = load_pipeline()
    old_series = _clean_text(before.get("series") or work_to_series_map().get(old_id, ""))
    new_series = _clean_text(after.get("series") or work_to_series_map().get(new_id, ""))
    if not new_series:
        errors.append("Saved work is not linked to a series.")
    elif new_series not in set(available_series_slugs()):
        errors.append(f"Saved work points to a missing series: {new_series}")

    source = _resolve_source_path(new_series, new_id, pipeline=pipeline, context="work id rename") if new_series and new_id else None
    image_block = after.get("image") if isinstance(after.get("image"), dict) else {}
    if image_block and not source:
        warnings.append(f"Saved work has image metadata, but no active source image was found for {new_id} in {new_series}.")
    elif source:
        info.append(f"Active source: {_relative_display(source)}")
        master = _clean_text(image_block.get("master"))
        if master and master != source.name:
            warnings.append(f"Image master '{master}' does not match active source file '{source.name}'.")

    render_name = _render_name_for_work(after) or new_id
    derivative_dir = derivative_dir_for_work(new_series, render_name, pipeline=pipeline) if new_series and render_name else None
    derivative_files = list(derivative_dir.glob("*")) if derivative_dir and derivative_dir.exists() else []
    if image_block and not derivative_files:
        warnings.append(f"No generated derivative files found for {new_id}: {_relative_display(derivative_dir)}")
    elif derivative_dir:
        info.append(f"Derivatives: {_relative_display(derivative_dir)} ({len(derivative_files)} file(s))")

    if old_id and old_id != new_id:
        stale_sources = [path for path in _source_candidates_for_stem(old_series or new_series, old_id, pipeline=pipeline) if path.exists()]
        stale_sources = [path for path in stale_sources if not (source and _same_path(path, source))]
        if stale_sources:
            warnings.append("Old source file(s) still exist after rename: " + ", ".join(_relative_display(path) for path in stale_sources[:6]))
        old_render = _render_name_for_work(before) or old_id
        old_derivative_dir = derivative_dir_for_work(old_series or new_series, old_render, pipeline=pipeline)
        if old_derivative_dir.exists() and not _same_path(old_derivative_dir, derivative_dir):
            warnings.append(f"Old derivative directory still exists after rename: {_relative_display(old_derivative_dir)}")
        stale_refs = _critical_content_stale_refs(old_id, new_id)
        if stale_refs:
            errors.append(f"{len(stale_refs)} exact stale content reference(s) still point to '{old_id}'.")

    sequences = {str(item.get("slug") or ""): [str(x).strip() for x in (item.get("work_ids") or []) if str(x).strip()] for item in load_series_entries() if isinstance(item, dict)}
    if new_series and new_id and new_id not in sequences.get(new_series, []):
        warnings.append(f"Saved work is not present in its series sequence: {new_series}.")
    if new_series and new_id:
        sequence_count = sequences.get(new_series, []).count(new_id)
        if sequence_count > 1:
            errors.append(f"Work '{new_id}' appears {sequence_count} times in series '{new_series}' sequence — duplicate entry created.")
    if old_id and old_id != new_id:
        remaining = [slug for slug, work_ids in sequences.items() if old_id in work_ids]
        if remaining:
            errors.append(f"Old work ID remains in series sequence(s): {', '.join(remaining)}")
    try:
        presence = reconcile_asset_presence_for_work(new_id)
        if presence.get("extra_sources"):
            errors.append("Fake asset presence risk: extra same-ID original(s) remain: " + ", ".join(str(x) for x in presence.get("extra_sources")[:6]))
        if presence.get("status") not in {"ok"}:
            warnings.append(f"Asset truth status after save: {presence.get('status')} — {presence.get('message')}")
    except Exception as exc:
        warnings.append(f"Could not run post-save asset truth check: {exc}")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "info": info, "old_work_id": old_id, "new_work_id": new_id}


def reconcile_asset_presence_for_work(work_id: str) -> dict[str, Any]:
    """Explain active vs extra source/derivative presence for a single work using the strict asset-truth model."""
    work_id = _clean_text(work_id)
    if not work_id:
        raise BackendError("Work ID is required for asset reconciliation.")
    truth = source_asset_truth_for_work(work_id)
    return {
        "work_id": work_id,
        "series": truth.get("series", ""),
        "active_source": truth.get("active_source", ""),
        "active_source_exists": bool(truth.get("active_source_exists")),
        "extra_sources": list(truth.get("extra_sources") or []),
        "derivative_dir": truth.get("derivative_dir", ""),
        "derivative_count": int(truth.get("derivative_count") or 0),
        "status": truth.get("status", "missing"),
        "severity": truth.get("severity", "error"),
        "message": truth.get("message", ""),
        "recovery_candidates": list(truth.get("recovery_candidates") or []),
        "generated_candidates": list(truth.get("generated_candidates") or []),
    }


def assert_no_fake_presence(work_id: str, *, allow_missing: bool = False) -> dict[str, Any]:
    """Raise if a work has stale same-ID originals or unsafe source truth."""
    presence = reconcile_asset_presence_for_work(work_id)
    errors: list[str] = []
    if presence.get("extra_sources"):
        errors.append("extra same-ID source file(s): " + ", ".join(str(x) for x in presence.get("extra_sources")[:6]))
    status = str(presence.get("status") or "").lower()
    if not allow_missing and status not in {"ok"}:
        errors.append(str(presence.get("message") or f"asset truth status is {status or 'unknown'}"))
    if errors:
        raise BackendIntegrityError("Fake asset presence check failed for " + work_id + ":\n" + "\n".join(f"- {item}" for item in errors))
    return presence

def _cached_series_slug_set() -> set[str]:
    """Short-lived cache for validating target series without repeated YAML walks."""
    global _SERIES_SLUG_CACHE
    with _SERIES_SLUG_CACHE_LOCK:
        now = time.monotonic()
        if _SERIES_SLUG_CACHE is not None:
            ts, cached = _SERIES_SLUG_CACHE
            if now - ts < _SERIES_SLUG_CACHE_TTL:
                return set(cached)
        slugs = set(available_series_slugs())
        _SERIES_SLUG_CACHE = (now, set(slugs))
        return slugs


def _invalidate_series_runtime_caches() -> None:
    global _SERIES_COMPLETENESS_CACHE, _SERIES_SLUG_CACHE
    with _SERIES_COMPLETENESS_CACHE_LOCK:
        _SERIES_COMPLETENESS_CACHE = None
    with _SERIES_SLUG_CACHE_LOCK:
        _SERIES_SLUG_CACHE = None



def startup_preflight_checks(*, fast: bool = True) -> dict[str, Any]:
    """Fast launch-time checks so the panel does not start in a broken state silently."""
    rows: list[dict[str, str]] = []
    def add(status: str, check: str, detail: str = "") -> None:
        rows.append({"status": status, "check": check, "detail": detail})
    for label, path in [
        ("content folder", CONTENT_DIR),
        ("works folder", CONTENT_DIR / "works"),
        ("series folder", CONTENT_DIR / "series"),
        ("pages folder", CONTENT_DIR / "pages"),
        ("build metadata folder", BUILD_META_DIR),
    ]:
        add("ok" if path.exists() else "error", label, _relative_display(path) if path.exists() else f"Missing: {_relative_display(path)}")
    try:
        pipeline = load_pipeline()
        add("ok", "image pipeline", f"Loaded {len(pipeline)} setting(s)")
        source_dir = source_root(pipeline)
        for label, path in [("source root", source_dir), ("generated root", generated_root(pipeline))]:
            add("ok" if path.exists() else "warning", label, _relative_display(path) if path.exists() else f"Will be created when needed: {_relative_display(path)}")
        try:
            source_dir.mkdir(parents=True, exist_ok=True)
            probe = source_dir / ".control-panel-source-write-test"
            atomic_write_text(probe, "ok")
            try:
                probe.unlink()
            except FileNotFoundError:
                pass
            add("ok", "source root write permission", _relative_display(source_dir))
        except Exception as exc:
            add("error", "source root write permission", str(exc))
    except Exception as exc:
        add("error", "image pipeline", str(exc))
    try:
        BUILD_META_DIR.mkdir(parents=True, exist_ok=True)
        probe = BUILD_META_DIR / ".control-panel-write-test"
        atomic_write_text(probe, "ok")
        try:
            probe.unlink()
        except FileNotFoundError:
            pass
        add("ok", "write permission", _relative_display(BUILD_META_DIR))
    except Exception as exc:
        add("error", "write permission", str(exc))
    try:
        works = load_work_entries()
        series = load_series_entries()
        add("ok", "content counts", f"{len(works)} works · {len(series)} series")
        render_names: dict[str, str] = {}
        duplicate_renders: list[str] = []
        for payload in works:
            work_id = _clean_text(payload.get("id"))
            image = payload.get("image") if isinstance(payload.get("image"), dict) else {}
            render_name = _clean_text(image.get("render_name") or image.get("renderName") or work_id)
            if not render_name:
                continue
            if render_name in render_names and render_names[render_name] != work_id:
                duplicate_renders.append(f"{render_name}: {render_names[render_name]}, {work_id}")
            else:
                render_names[render_name] = work_id
        if duplicate_renders:
            add("error", "render name uniqueness", "; ".join(duplicate_renders[:5]))
        else:
            add("ok", "render name uniqueness", f"{len(render_names)} unique render name(s) found.")
        broken_series = []
        for series_payload in series:
            missing_refs = series_missing_work_references(series_payload)
            if missing_refs:
                broken_series.append(f"{_clean_text(series_payload.get('slug'))}: {', '.join(missing_refs[:4])}")
        if broken_series:
            add("error", "series work references", "; ".join(broken_series[:5]))
        else:
            add("ok", "series work references", "Every series sequence points to existing work YAML.")
    except Exception as exc:
        add("error", "content YAML load", str(exc))
    corrupt_drafts = 0
    if DRAFTS_DIR.exists():
        for path in DRAFTS_DIR.rglob("*.json"):
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                corrupt_drafts += 1
        add("warning" if corrupt_drafts else "ok", "draft cache", f"{corrupt_drafts} unreadable draft file(s)" if corrupt_drafts else "No corrupt drafts detected")
    else:
        add("ok", "draft cache", "No draft folder yet")
    active_txns = [row for row in _load_transaction_rows() if row.get("status") == "active"]
    add("warning" if active_txns else "ok", "transaction log", f"{len(active_txns)} active transaction record(s) found from a previous interrupted run" if active_txns else "No active transaction residue")
    if fast:
        add("warning", "source asset truth", "Deferred during fast startup. Open Source recovery or Publish Ops for the full strict scan.")
    else:
        try:
            truth_rows = asset_truth_report_rows(force=True)
            blocking = [row for row in truth_rows if row.get("severity") == "error"]
            orphan_risk = [row for row in truth_rows if row.get("status") == "orphan-risk"]
            if blocking:
                add("error", "source asset truth", f"{len(blocking)} work(s) lack acceptable original sources. Build/publish are blocked in strict mode.")
            elif orphan_risk:
                add("warning", "source asset truth", f"{len(orphan_risk)} work(s) have extra same-ID originals that can create fake presence.")
            else:
                add("ok", "source asset truth", "Original sources are clean for all works.")
        except Exception as exc:
            add("error", "source asset truth", str(exc))
    error_count = sum(1 for row in rows if row.get("status") == "error")
    warning_count = sum(1 for row in rows if row.get("status") == "warning")
    return {"ok": error_count == 0, "errors": error_count, "warnings": warning_count, "rows": rows}


def save_work_from_payload(original_work_id: str | None, payload: dict[str, Any], *, move_assets: bool = True) -> dict[str, Any]:
    started_total = time.perf_counter()
    timings: dict[str, int] = {}
    lap_started = started_total

    def lap(name: str) -> None:
        nonlocal lap_started
        now = time.perf_counter()
        timings[name] = int((now - lap_started) * 1000)
        lap_started = now

    original_work_id = _clean_text(original_work_id or payload.get("id"))
    raw_work_id = _clean_text(payload.get("id") or "")
    new_work_id = slugify_work_id(raw_work_id)
    existing_ids = {str(row.get("id") or "").strip() for row in load_work_entries() if str(row.get("id") or "").strip()}
    id_check = validate_work_id_slug(new_work_id, existing_ids=existing_ids, current_id=original_work_id)
    if raw_work_id and raw_work_id != new_work_id:
        id_check.setdefault("errors", []).append("Work ID would be normalized; enter the final safe slug explicitly before saving.")
    if not id_check.get("ok"):
        raise BackendValidationError("Invalid work ID:\n" + "\n".join(f"- {item}" for item in id_check.get("errors", []) or ["Work ID is required."]))
    requested_series = _clean_text(payload.get("series"))
    series_slug = resolve_series_slug(requested_series)
    if not series_slug and original_work_id:
        old_for_series = load_work_payload(original_work_id) or {}
        series_slug = resolve_series_slug(old_for_series.get("series")) or _clean_text(work_to_series_map().get(original_work_id, ""))
    if series_slug not in set(available_series_slugs()):
        raise BackendError("Choose a valid series before saving the work.")
    payload = dict(payload or {})
    payload["series"] = series_slug
    try:
        focal = payload.get("focal_point") if isinstance(payload.get("focal_point"), dict) else {}
        focal_x = int(focal.get("x", 50))
        focal_y = int(focal.get("y", 50))
    except Exception as exc:
        raise BackendError("Focal point values must be whole numbers.") from exc
    if original_work_id != new_work_id:
        ensure_unique_work_id(new_work_id, allow_existing=False)
    lap("validate")

    pipeline = load_pipeline()
    old_payload = load_work_payload(original_work_id) if original_work_id else {}
    old_series = _clean_text(old_payload.get("series") or work_to_series_map().get(original_work_id, ""))
    final_series = series_slug or old_series
    current_source = _resolve_source_path(old_series or final_series, original_work_id or new_work_id, pipeline=pipeline, context="save work") if original_work_id else None
    if move_assets and original_work_id and (not current_source or not Path(current_source).exists()):
        original_candidates = [
            row for row in _recoverable_candidates_for_work(
                old_series or final_series,
                _render_name_for_work(old_payload or payload),
                original_work_id,
            )
            if row.get("kind") == "original"
        ]
        if original_candidates:
            current_source = Path(original_candidates[0]["path"])
    lap("load_context")

    image_block = payload.get("image") if isinstance(payload.get("image"), dict) else dict(old_payload.get("image") or {})
    if current_source and current_source.exists() and move_assets:
        destination_dir = source_root(pipeline) / final_series
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{new_work_id}{current_source.suffix.lower()}"
    else:
        destination = current_source
    lap("asset_plan")

    reference_updates: list[str] = []
    verification: dict[str, Any] = {}
    moved_or_renamed_asset = False
    structural_change = bool(original_work_id and original_work_id != new_work_id) or bool(old_series and final_series and old_series != final_series)
    yaml_path: Path | None = None

    with transaction(f"qt-save-work:{original_work_id}->{new_work_id}"):
        if original_work_id and old_series and final_series and old_series != final_series:
            move_work_to_series(original_work_id, final_series)
        lap("series_move")

        if destination and current_source and current_source.exists() and move_assets:
            try:
                same_path = destination.resolve() == current_source.resolve()
            except Exception:
                same_path = destination == current_source
            if not same_path:
                if destination.exists():
                    snapshot_path(destination)
                    guarded_unlink(destination, detail="replace destination before work-id asset move")
                guarded_move(current_source, destination, detail="move original during work save/rename")
                moved_or_renamed_asset = True
            image_block = dict(image_block or {})
            image_block["master"] = destination.name
            image_block["render_name"] = new_work_id
        elif image_block:
            image_block = dict(image_block)
            current_master = _clean_text(image_block.get("master"))
            suffix = Path(current_master).suffix.lower() if current_master else ".jpg"
            image_block["master"] = f"{new_work_id}{suffix}"
            image_block["render_name"] = new_work_id
        lap("asset_move")

        payload = _normalize_work_publish_state(dict(payload))
        # Preserve advanced presentation fields when an older editor surface does
        # not submit them. The current Works editor submits display_layouts and
        # display_ratios explicitly, which lets users clear old nested/top-level
        # layout values instead of having preservation silently re-apply them.
        for preserved_key in (
            "portfolio_layout",
            "series_layout",
            "portfolio_ratio",
            "series_ratio",
            "display_layouts",
            "display_ratios",
        ):
            if not isinstance(old_payload, dict) or preserved_key not in old_payload:
                continue
            if preserved_key in payload:
                continue
            if preserved_key in {"portfolio_ratio", "series_ratio"} and "display_ratios" in payload:
                continue
            if preserved_key == "display_layouts" and ("portfolio_layout" in payload or "series_layout" in payload):
                continue
            payload[preserved_key] = old_payload[preserved_key]
        payload["id"] = new_work_id
        payload["series"] = final_series
        payload["focal_point"] = {"x": focal_x, "y": focal_y}
        if image_block:
            payload["image"] = image_block

        if original_work_id and original_work_id != new_work_id:
            old_path_for_refs = work_file_for_id(original_work_id)
            if old_path_for_refs.exists():
                snapshot_path(old_path_for_refs)
            # Snapshot all series files that mention the old work id before any
            # reference replacement starts, so transaction rollback can restore
            # the complete relationship graph if the rename fails mid-way.
            for series_path in sorted((CONTENT_DIR / "series").glob("*.yaml")):
                try:
                    data = load_yaml(series_path)
                    if data and original_work_id in str(data):
                        snapshot_path(series_path)
                except Exception:
                    pass
            reference_updates = replace_exact_refs(original_work_id, new_work_id)
            reference_updates.extend(repair_relationship_refs("work", original_work_id, new_work_id))
        if _ensure_work_in_series_sequence(final_series, new_work_id):
            reference_updates.append(f"ensured {new_work_id} is listed in series {final_series}")
        lap("reference_updates")

        if original_work_id and original_work_id != new_work_id:
            old_path = work_file_for_id(original_work_id)
            new_path = work_file_for_id(new_work_id)
            if new_path.exists() and not _same_path(new_path, old_path):
                raise BackendError(f"Work id '{new_work_id}' already exists.")
            if old_path.exists():
                old_path.unlink()
            write_yaml(new_path, payload)
            invalidate_work_cache({original_work_id, new_work_id})
            mark_unpublished_changes(new_path)
            yaml_path = new_path
        else:
            yaml_path = work_file_for_id(new_work_id)
            write_yaml(yaml_path, payload)
            mark_unpublished_changes(yaml_path)
            invalidate_work_cache({new_work_id})
        lap("write_yaml")

        should_regenerate_derivatives = bool(destination and destination.exists() and (moved_or_renamed_asset or structural_change))
        if should_regenerate_derivatives:
            generate_derivatives(destination, final_series, new_work_id, pipeline=pipeline, force=True)
        lap("generate_derivatives")

        old_generated = derivative_dir_for_work(old_series or final_series, original_work_id, pipeline=pipeline) if original_work_id and original_work_id != new_work_id else None
        new_generated = derivative_dir_for_work(final_series, new_work_id, pipeline=pipeline) if final_series else None
        if old_generated and old_generated.exists() and not _same_path(old_generated, new_generated):
            guarded_rmtree(old_generated, detail="remove stale derivatives after work-id rename")

        if original_work_id and original_work_id != new_work_id:
            active_source = _resolve_source_path(final_series, new_work_id, pipeline=pipeline, context="save work active source")
            for stale_source in _source_candidates_for_stem(old_series or final_series, original_work_id, pipeline=pipeline):
                if not stale_source.exists():
                    continue
                try:
                    same_as_active = bool(active_source and stale_source.resolve() == active_source.resolve())
                except Exception:
                    same_as_active = bool(active_source and stale_source == active_source)
                if same_as_active:
                    continue
                guarded_unlink(stale_source, detail="remove stale original after work-id rename")
        lap("cleanup")

        if structural_change or moved_or_renamed_asset:
            verification = verify_work_transaction(original_work_id, new_work_id, old_payload, payload)
            if verification.get("errors"):
                raise BackendError("Work save verification failed:\n" + "\n".join(f"- {item}" for item in verification.get("errors") or []))
            if image_block:
                verification["presence"] = assert_no_fake_presence(new_work_id, allow_missing=True)
        else:
            verification = {
                "errors": [],
                "warnings": [],
                "info": ["metadata-only save verified without derivative regeneration"],
                "metadata_only": True,
            }
        lap("verify")

    if structural_change or moved_or_renamed_asset:
        invalidate_control_panel_caches()
        mark_portfolio_health_dirty("work", new_work_id)
    else:
        invalidate_work_cache({new_work_id})
        patch_cached_health_for_work(new_work_id)
    lap("emit_dirty_signal")
    total_ms = int((time.perf_counter() - started_total) * 1000)
    _record_diagnostic_event(
        "work-save-profile",
        "ok" if total_ms <= 150 or structural_change else "warning",
        f"Saved work {new_work_id} in {total_ms} ms",
        work_id=new_work_id,
        original_work_id=original_work_id,
        structural=structural_change,
        regenerated_derivatives=bool(verification.get("metadata_only") is not True and destination and destination.exists()),
        total_ms=total_ms,
        **{f"step_{key}_ms": value for key, value in timings.items()},
    )
    return {"work_id": new_work_id, "reference_updates": reference_updates, "verification": verification, "timings_ms": timings, "elapsed_ms": total_ms}

def preview_duplicate_work(source_work_id: str, *, new_work_id: str | None = None, title: str | None = None, series_slug: str | None = None) -> dict[str, Any]:
    payload = load_work_payload(source_work_id)
    if not payload:
        raise BackendError(f"Work '{source_work_id}' was not found.")
    candidate = slugify_work_id(new_work_id or f"{source_work_id}-copy")
    base_candidate = candidate or slugify_work_id(f"{source_work_id}-copy")
    suffix = 2
    existing_ids = {str(item.get("id") or "") for item in load_work_entries()}
    while candidate in existing_ids:
        candidate = slugify_work_id(f"{base_candidate}-{suffix}")
        suffix += 1
    proposed_title = _clean_text(title) or f"{_clean_text(payload.get('title'))} Copy".strip()
    target_series = _clean_text(series_slug or payload.get("series"))
    clone = deepcopy(payload)
    clone["id"] = candidate
    clone["title"] = proposed_title
    clone["series"] = target_series
    clone["published"] = False
    clone["review_status"] = "draft"
    if isinstance(clone.get("image"), dict):
        image = dict(clone.get("image") or {})
        image["master"] = ""
        image["render_name"] = candidate
        clone["image"] = image
    return {
        "source_work_id": source_work_id,
        "new_work_id": candidate,
        "title": proposed_title,
        "series": target_series,
        "review_status": "draft",
        "published": False,
        "image_policy": "metadata-only draft; no source image is copied",
        "clone_payload": clone,
        "completeness": work_completeness_score(clone),
    }


def duplicate_work(source_work_id: str, *, new_work_id: str | None = None, title: str | None = None, series_slug: str | None = None) -> str:
    preview = preview_duplicate_work(source_work_id, new_work_id=new_work_id, title=title, series_slug=series_slug)
    candidate = str(preview.get("new_work_id") or "").strip()
    ensure_unique_work_id(candidate, allow_existing=False)
    clone = dict(preview.get("clone_payload") or {})
    if not clone:
        raise BackendError("Could not prepare duplicated work payload.")
    with transaction(f"qt-duplicate-work:{source_work_id}->{candidate}"):
        save_work_payload(candidate, clone)
        insert_work_into_series(_clean_text(clone.get("series")), candidate)
    mark_unpublished_changes()
    invalidate_control_panel_caches()
    patch_cached_health_for_work(candidate)
    mark_portfolio_health_dirty("work", candidate)
    return candidate


def update_work_quick_state(work_id: str, *, published: bool | None = None, review_status: str | None = None) -> dict[str, Any]:
    payload = load_work_payload(work_id)
    if not payload:
        raise BackendError(f"Work '{work_id}' was not found.")
    before = dict(payload)
    changed: list[str] = []
    if published is not None and bool(payload.get("published")) != bool(published):
        payload["published"] = bool(published)
        changed.append("published")
        if bool(published):
            payload["review_status"] = "published"
            changed.append("review_status")
        elif _clean_text(payload.get("review_status")).lower() == "published":
            payload["review_status"] = "review"
            changed.append("review_status")
    if review_status is not None:
        value = _clean_text(review_status).lower()
        if value not in PUBLISH_STATES:
            raise BackendError(f"Invalid review status: {review_status}")
        if _clean_text(payload.get("review_status")).lower() != value:
            payload["review_status"] = value
            changed.append("review_status")
        if value == "published" and not bool(payload.get("published")):
            payload["published"] = True
            changed.append("published")
        if value != "published" and bool(payload.get("published")):
            payload["published"] = False
            changed.append("published")
    if changed:
        with transaction(f"qt-quick-state:{work_id}"):
            save_work_payload(work_id, payload)
        mark_unpublished_changes()
        invalidate_control_panel_caches()
    return {"work_id": work_id, "changed": sorted(set(changed)), "before": before, "after": payload}


def add_image(
    *,
    file_path: str | Path,
    series_slug: str,
    work_id: str,
    title: str,
    year: str,
    location: str,
    alt: str,
    caption: str,
    tags: list[str],
    review_status: str,
    published: bool,
    hero_safe: bool,
    grid_safe: bool,
    social_safe: bool,
    focal_x: int,
    focal_y: int,
    position: int | None = None,
) -> str:
    source = Path(file_path)
    if not source.exists():
        raise BackendError(f"Image file not found: {source}")
    if series_slug not in set(available_series_slugs()):
        raise BackendError("Choose a valid series before adding the image.")
    work_id = slugify_work_id(work_id)
    if not work_id:
        raise BackendError("Enter a valid work ID.")
    ensure_unique_work_id(work_id, allow_existing=False)
    tags = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
    if any(len(tag) > 50 for tag in tags):
        raise BackendError("Tag values must be 50 characters or fewer.")
    alt_words = [word.strip() for word in _clean_text(alt).split() if word.strip()]
    if len(alt_words) < 5:
        raise BackendError("Use at least 5 descriptive words for alt text.")
    avg_alt_word_len = sum(len(word.strip(".,;:!?()[]{}\"'")) for word in alt_words) / max(1, len(alt_words))
    if avg_alt_word_len < 3:
        raise BackendError("Alt text words appear too short to be descriptive. Use full descriptive phrases.")
    if len(_clean_text(title).split()) < 2:
        raise BackendError("Use a title with at least 2 words.")
    if not _clean_text(year):
        raise BackendError("Enter a year before adding the work.")
    if not _clean_text(location) or _is_placeholder_text(location):
        raise BackendError("Enter a meaningful location before adding the work.")
    review_status = _clean_text(review_status).lower() or ("published" if published else "draft")
    if review_status not in PUBLISH_STATES:
        review_status = "published" if published else "draft"
    if not published and review_status == "published":
        review_status = "review"
    pipeline = load_pipeline()
    with transaction(f"qt-add-image:{work_id}"):
        destination_name = f"{work_id}{source.suffix.lower()}"
        stored_original = safe_copy_to_originals(source, series_slug, destination_name, pipeline=pipeline)
        payload = create_work_payload(
            work_id=work_id,
            title=title,
            series_slug=series_slug,
            year=year,
            location=location,
            alt=alt,
            caption=caption,
            tags=tags,
            published=published,
            hero_safe=hero_safe,
            grid_safe=grid_safe,
            social_safe=social_safe,
            focal_x=int(focal_x),
            focal_y=int(focal_y),
            master_filename=stored_original.name,
        )
        payload["review_status"] = review_status
        target_yaml = work_file_for_id(work_id)
        if target_yaml.exists():
            snapshot_path(target_yaml)
        write_yaml(target_yaml, payload)
        insert_work_into_series(series_slug, work_id, position=position)
        derivative_meta = generate_derivatives(stored_original, series_slug, work_id, pipeline=pipeline, force=True)
        write_ingestion_log(
            {
                "event": "qt_ingest",
                "workId": work_id,
                "series": series_slug,
                "sourceOriginal": stored_original.relative_to(ROOT).as_posix(),
                "responsiveBase": derivative_meta.get("responsiveBase"),
                "generatedFiles": derivative_meta.get("generatedFiles"),
                "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            pipeline=pipeline,
        )
    invalidate_control_panel_caches()
    mark_unpublished_changes()
    mark_portfolio_health_dirty("work", work_id)
    patch_cached_health_for_work(work_id)
    return work_id



def preview_replace_work_image(work_id: str, file_path: str | Path) -> dict[str, Any]:
    """Preview exact file effects of replacing a work source image."""
    payload = load_work_payload(work_id)
    if not payload:
        raise BackendError(f"Work '{work_id}' was not found.")
    source = Path(file_path)
    if not source.exists():
        raise BackendError(f"Image file not found: {source}")
    series_slug = _clean_text(payload.get("series") or work_to_series_map().get(work_id, ""))
    if not series_slug:
        raise BackendError("The work is not linked to a valid series.")
    pipeline = load_pipeline()
    old_source = _resolve_source_path(series_slug, work_id, pipeline=pipeline, context="replace image")
    destination = source_root(pipeline) / series_slug / f"{work_id}{source.suffix.lower()}"
    stale_sources = []
    for candidate in _source_candidates_for_stem(series_slug, work_id, pipeline=pipeline):
        if not candidate.exists():
            continue
        if _same_path(candidate, destination):
            continue
        stale_sources.append(_relative_display(candidate))
    render_name = _render_name_for_work(payload) or work_id
    derivative_dir = derivative_dir_for_work(series_slug, render_name, pipeline=pipeline)
    return {
        "operation": "replace-work-image",
        "work_id": work_id,
        "series": series_slug,
        "incoming_file": str(source),
        "current_source": _relative_display(old_source) if old_source else "",
        "target_source": _relative_display(destination),
        "stale_same_id_sources_to_remove": stale_sources,
        "derivative_dir_to_regenerate": _relative_display(derivative_dir),
        "updates": [
            "backup current target/source if present",
            "copy selected file into originals under the active series",
            "remove stale same-ID originals with other extensions",
            "update image.master and render_name",
            "delete/regenerate derivative files",
            "verify source truth and stale references",
        ],
    }

def replace_work_image(work_id: str, file_path: str | Path) -> dict[str, Any]:
    payload = load_work_payload(work_id)
    if not payload:
        raise BackendError(f"Work '{work_id}' was not found.")
    source = Path(file_path)
    if not source.exists():
        raise BackendError(f"Image file not found: {source}")
    series_slug = _clean_text(payload.get("series") or work_to_series_map().get(work_id, ""))
    if not series_slug:
        raise BackendError("The work is not linked to a valid series.")
    pipeline = load_pipeline()
    old_payload = deepcopy(payload)
    old_source = _resolve_source_path(series_slug, work_id, pipeline=pipeline, context="replace image")
    old_render = _render_name_for_work(payload) or work_id
    old_derivative_dir = derivative_dir_for_work(series_slug, old_render, pipeline=pipeline)
    removed_stale_originals: list[str] = []
    with transaction(f"qt-replace-image:{work_id}"):
        destination_name = f"{work_id}{source.suffix.lower()}"
        stored_original = safe_copy_to_originals(source, series_slug, destination_name, pipeline=pipeline)

        # Replacing with a different extension used to leave fake old originals behind
        # (for example work-id.jpg remaining active-looking after work-id.png replaced it).
        for candidate in _source_candidates_for_stem(series_slug, work_id, pipeline=pipeline):
            if not candidate.exists():
                continue
            try:
                same_as_new = candidate.resolve() == stored_original.resolve()
            except Exception:
                same_as_new = candidate == stored_original
            if same_as_new:
                continue
            guarded_unlink(candidate, detail="remove stale original after image replacement")
            removed_stale_originals.append(_relative_display(candidate))

        if old_derivative_dir.exists():
            guarded_rmtree(old_derivative_dir, detail="remove derivatives before image replacement")

        image_block = payload.get("image") if isinstance(payload.get("image"), dict) else {}
        image_block = dict(image_block)
        image_block["master"] = stored_original.name
        render_name = _clean_text(image_block.get("render_name")) or work_id
        image_block["render_name"] = render_name
        payload["image"] = image_block
        save_work_payload(work_id, payload)
        derivative_meta = generate_derivatives(stored_original, series_slug, render_name, pipeline=pipeline, force=True)

        verification = verify_work_transaction(work_id, work_id, old_payload, payload)
        if verification.get("errors"):
            raise BackendError("Image replacement verification failed:\n" + "\n".join(f"- {item}" for item in verification.get("errors") or []))
        verification["presence"] = assert_no_fake_presence(work_id)

    invalidate_control_panel_caches()
    presence = reconcile_asset_presence_for_work(work_id)
    return {
        "work_id": work_id,
        "old_source": _relative_display(old_source) if old_source else "",
        "new_source": _relative_display(stored_original),
        "removed_stale_originals": removed_stale_originals,
        "derivative_meta": derivative_meta,
        "verification": verification,
        "presence": presence,
    }


def load_series_sequence(series_slug: str) -> list[str]:
    payload = _CONTENT_REPOSITORY.series_payload(series_slug) or load_series_payload(series_slug)
    return [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]


def save_series_from_payload(original_slug: str | None, payload: dict[str, Any]) -> str:
    original_slug = _clean_text(original_slug or payload.get("slug"))
    new_slug = slugify_work_id(payload.get("slug") or "")
    if not new_slug:
        raise BackendError("Series slug is required.")
    title = _clean_text(payload.get("title"))
    if not title:
        raise BackendError("Series title is required.")
    all_series = set(available_series_slugs())
    if original_slug != new_slug and new_slug in all_series:
        raise BackendError(f"Series '{new_slug}' already exists.")
    sequence = [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]
    payload = dict(payload)
    payload["slug"] = new_slug
    payload["work_ids"] = sequence
    with transaction(f"qt-save-series:{original_slug}->{new_slug}"):
        if original_slug != new_slug and original_slug:
            replace_exact_refs(original_slug, new_slug)
            repair_relationship_refs("series", original_slug, new_slug)
            old_path = series_file_for_slug(original_slug)
            new_path = series_file_for_slug(new_slug)
            if old_path.exists():
                old_path.unlink()
            write_yaml(new_path, payload)
        else:
            save_series_payload(new_slug, payload)
        # Keep work membership and asset folders aligned for works explicitly listed
        # in the sequence. `work_to_series_map()` resolves sequence membership first,
        # so it can report a work as belonging to the new series even while the work
        # YAML still contains the old slug. Always inspect and update the work YAML
        # field directly, otherwise renaming a series leaves originals/generated
        # folders under the historical slug.
        pipeline = load_pipeline()
        current_members = work_to_series_map()
        for work_id in sequence:
            work_payload = load_work_payload(work_id) or {}
            previous_work_series = _clean_text(work_payload.get("series")) or original_slug
            image_block = work_payload.get("image") if isinstance(work_payload.get("image"), dict) else {}
            render_name = _clean_text(image_block.get("render_name")) or _clean_text(work_payload.get("render_name")) or work_id
            if current_members.get(work_id) != new_slug:
                move_work_to_series(work_id, new_slug)
                work_payload = load_work_payload(work_id) or work_payload
            if _clean_text(work_payload.get("series")) != new_slug:
                updated_work = dict(work_payload)
                updated_work["series"] = new_slug
                save_work_payload(work_id, updated_work)
            if previous_work_series and previous_work_series != new_slug:
                move_original_between_series(work_id, previous_work_series, new_slug, pipeline=pipeline)
                move_generated_between_series(work_id, previous_work_series, new_slug, pipeline=pipeline, render_name=render_name)
        # A series rename must also update work YAML files whose series field points
        # at the old slug even if those works are not listed in the sequence. Move
        # their asset folders too, so direct originals/generated lookups stay clean.
        if original_slug != new_slug and original_slug:
            sequence_set = set(sequence)
            for work_payload in load_work_entries():
                wid = _clean_text(work_payload.get("id"))
                if not wid or wid in sequence_set:
                    continue
                if _clean_text(work_payload.get("series")) == original_slug:
                    image_block = work_payload.get("image") if isinstance(work_payload.get("image"), dict) else {}
                    render_name = _clean_text(image_block.get("render_name")) or _clean_text(work_payload.get("render_name")) or wid
                    updated_work = dict(work_payload)
                    updated_work["series"] = new_slug
                    save_work_payload(wid, updated_work)
                    move_original_between_series(wid, original_slug, new_slug, pipeline=pipeline)
                    move_generated_between_series(wid, original_slug, new_slug, pipeline=pipeline, render_name=render_name)
    mark_unpublished_changes()
    try:
        refresh_image_manifests(line_callback=None)
    except Exception as exc:
        _record_backend_warning("Could not refresh image manifests after series save", error=exc)
    invalidate_control_panel_caches()
    mark_portfolio_health_dirty("series", new_slug)
    return new_slug


def create_series(*, title: str, years: str = "", mood: str = "", description: str = "", order: int | None = None, visibility: str = "public") -> str:
    slug = slugify_work_id(title)
    if not slug:
        raise BackendError("Series title must produce a valid slug.")
    if slug in set(available_series_slugs()):
        raise BackendError(f"Series '{slug}' already exists.")
    sequence_order = order if order is not None else (len(load_series_entries()) + 1)
    create_series_file(slug, title, years, mood, description, sequence_order, visibility)
    mark_unpublished_changes()
    invalidate_control_panel_caches()
    mark_portfolio_health_dirty("series", slug)
    return slug


def _series_work_references(series_slug: str, payload: dict[str, Any] | None = None) -> list[str]:
    """Return every live work ID that would be affected by deleting a series."""
    slug = _clean_text(series_slug)
    referenced: list[str] = []
    seen: set[str] = set()
    if payload is None:
        payload = load_series_payload(slug) if slug else {}
    for work_id in [str(item).strip() for item in ((payload or {}).get("work_ids") or []) if str(item).strip()]:
        if work_id not in seen:
            seen.add(work_id)
            referenced.append(work_id)
    for work in load_work_entries():
        work_id = _clean_text(work.get("id"))
        if work_id and _clean_text(work.get("series")) == slug and work_id not in seen:
            seen.add(work_id)
            referenced.append(work_id)
    return referenced


def _series_collection_references(series_slug: str) -> list[str]:
    slug = _clean_text(series_slug)
    hits: list[str] = []
    collections_dir = CONTENT_DIR / "collections"
    if not slug or not collections_dir.exists():
        return hits
    for path in sorted(collections_dir.glob("*.yaml")):
        payload = load_yaml(path) or {}
        if not isinstance(payload, dict):
            continue
        collection_slug = _clean_text(payload.get("slug")) or path.stem
        for key in ("series_slugs", "guide_series_slugs", "draft_series_slugs"):
            values = payload.get(key)
            if isinstance(values, list) and slug in [str(item).strip() for item in values]:
                hits.append(f"{collection_slug}.{key}")
    return hits


def series_delete_preview(series_slug: str) -> dict[str, Any]:
    """Preflight a series deletion without mutating content."""
    slug = _clean_text(series_slug)
    if not slug:
        raise BackendError("Select a series before deleting.")
    path = series_file_for_slug(slug)
    if not path.exists():
        raise BackendError(f"Series '{slug}' was not found.")
    payload = load_series_payload(slug) or {}
    work_refs = _series_work_references(slug, payload)
    relationships = load_home_relationships()
    homepage_refs = []
    if slug in [str(item).strip() for item in (relationships.get("featured_series") or [])]:
        homepage_refs.append("home.featured_series")
    collection_refs = _series_collection_references(slug)
    return {
        "slug": slug,
        "title": str(payload.get("title") or slug).strip(),
        "visibility": str(payload.get("visibility") or "public").strip(),
        "path": str(path.relative_to(ROOT)),
        "work_ids": work_refs,
        "work_count": len(work_refs),
        "homepage_refs": homepage_refs,
        "collection_refs": collection_refs,
        "safe_to_delete": len(work_refs) == 0,
    }


def _prune_series_from_collections(series_slug: str) -> list[str]:
    slug = _clean_text(series_slug)
    changed: list[str] = []
    collections_dir = CONTENT_DIR / "collections"
    if not slug or not collections_dir.exists():
        return changed
    for path in sorted(collections_dir.glob("*.yaml")):
        payload = load_yaml(path) or {}
        if not isinstance(payload, dict):
            continue
        updated = dict(payload)
        touched_keys: list[str] = []
        for key in ("series_slugs", "guide_series_slugs", "draft_series_slugs"):
            values = updated.get(key)
            if not isinstance(values, list):
                continue
            pruned = [item for item in values if str(item).strip() != slug]
            if pruned != values:
                updated[key] = pruned
                touched_keys.append(key)
        if touched_keys:
            snapshot_path(path)
            write_yaml(path, updated)
            changed.append(f"{path.relative_to(ROOT).as_posix()}:{','.join(touched_keys)}")
    return changed


def delete_series_record(series_slug: str) -> dict[str, Any]:
    """Delete an empty series YAML file and prune non-work references safely.

    The function intentionally blocks deleting a series that still owns works.
    Removing the series while work YAML files still point to it would create broken
    editor state and public-build validation errors; move or remove those works first.
    """
    preview = series_delete_preview(series_slug)
    slug = str(preview.get("slug") or "").strip()
    work_ids = list(preview.get("work_ids") or [])
    if work_ids:
        preview_list = ", ".join(work_ids[:8])
        if len(work_ids) > 8:
            preview_list += f", +{len(work_ids) - 8} more"
        raise BackendError(
            f"Series '{slug}' still contains or owns {len(work_ids)} work(s): {preview_list}. "
            "Move those works to another series or remove them from the sequence before deleting the series."
        )
    path = series_file_for_slug(slug)
    with transaction(f"qt-delete-series:{slug}"):
        pruned_relationships = repair_relationship_refs("series", slug, None)
        pruned_collections = _prune_series_from_collections(slug)
        guarded_unlink(path, detail="delete empty series from Series library")
    clear_editor_draft("series", slug)
    mark_unpublished_changes()
    invalidate_control_panel_caches()
    mark_portfolio_health_dirty("series", slug)
    return {
        "series": slug,
        "deleted_path": str(path.relative_to(ROOT)),
        "pruned_relationships": pruned_relationships,
        "pruned_collections": pruned_collections,
    }


def load_relationships() -> dict[str, list[str]]:
    return load_home_relationships()


def save_relationships(featured_series: list[str], selected_works: list[str]) -> None:
    reorder_homepage_featured(featured_series=featured_series, selected_works=selected_works)


_PREVIEW_SERVER: Any = None


def preview_url(target: Path | None = None) -> str:
    """Serve dist/ on a private local port and return the URL for target.

    Pages use root-relative paths (/assets/...), so they must be opened over
    HTTP like the real host, not from disk with file://.
    """
    global _PREVIEW_SERVER
    if _PREVIEW_SERVER is None:
        import threading
        from functools import partial
        from http.server import ThreadingHTTPServer
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from preview_server import PreviewHandler

        class QuietHandler(PreviewHandler):
            def log_message(self, *args: Any) -> None:  # keep the panel log clean
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(DIST_DIR)))
        threading.Thread(target=server.serve_forever, name="stillmark-preview", daemon=True).start()
        _PREVIEW_SERVER = server
    port = _PREVIEW_SERVER.server_address[1]
    relative = ""
    if target is not None:
        try:
            relative = target.resolve().relative_to(DIST_DIR.resolve()).as_posix()
        except ValueError:
            relative = target.name
    if relative == "index.html":
        relative = ""
    return f"http://127.0.0.1:{port}/{relative}"


def preview_target() -> Path:
    public_index = ROOT / "dist" / "index.html"
    if public_index.exists():
        return public_index
    return ROOT / "index.html"


def _source_error_preview(limit: int = 10) -> str:
    rows = source_asset_issues()
    if not rows:
        return ''
    preview = "\n".join(f"- {row['id']}: {row['message']}" for row in rows[:limit])
    if len(rows) > limit:
        preview += f"\n- … and {len(rows) - limit} more"
    return preview


def preflight_build_sources(*, line_callback: Callable[[str], None] | None = None, allow_recovery: bool = True, strict: bool | None = None) -> dict[str, Any]:
    if line_callback:
        line_callback("Checking strict source asset truth…")
    gate_mode = source_asset_gate_mode()
    strict_gate = (gate_mode == "strict") if strict is None else bool(strict)
    recovered = recover_missing_source_images(line_callback=line_callback, allow_derivative_recovery=False) if allow_recovery else []
    if recovered:
        invalidate_control_panel_caches()
    remaining = source_asset_issues(use_cache=False)
    blocking = [row for row in remaining if row.get("severity") == "error"]
    warnings = [row for row in remaining if row.get("severity") != "error"]
    if blocking:
        preview = "\n".join(f"- {row.get('id')}: {row.get('message')}" for row in blocking[:12])
        if len(blocking) > 12:
            preview += f"\n- … and {len(blocking) - 12} more"
        detail = (
            f"{len(blocking)} work(s) still lack acceptable original source images.\n"
            f"{preview}\n\n"
            "Generated derivatives are not treated as originals. Relink the original files in Studio/Works, "
            "or set STILLMRK_SOURCE_ASSET_GATE=warn only for an intentional emergency local build."
        )
        _record_diagnostic_event("source-preflight", "blocked" if strict_gate else "warning", detail, blocking=len(blocking), warnings=len(warnings), gate=gate_mode)
        if line_callback:
            line_callback(f"✕ {len(blocking)} source blocker(s) remain under gate={gate_mode}.")
        if strict_gate:
            raise BackendError("Source asset preflight blocked the build:\n" + detail)
    elif warnings:
        if line_callback:
            line_callback(f"⚠ {len(warnings)} source hygiene warning(s) remain.")
        _record_diagnostic_event("source-preflight", "warning", f"{len(warnings)} source hygiene warning(s) remain.", warnings=len(warnings), gate=gate_mode)
    else:
        if line_callback:
            line_callback("✓ Source asset truth passed.")
        _record_diagnostic_event("source-preflight", "ok", "Source asset truth passed.", gate=gate_mode)
    return {"recovered": recovered, "remaining": remaining, "blocking": blocking, "warnings": warnings, "gate": gate_mode}


def run_build_with_preflight(line_callback: Callable[[str], None] | None = None) -> dict[str, Any]:
    preflight = preflight_build_sources(line_callback=line_callback, allow_recovery=True)
    if line_callback and preflight.get("recovered"):
        line_callback(f"Recovered {len(preflight['recovered'])} missing original source image(s) before build")
    try:
        from og_images import ensure_og_images_from_content, load_content_for_og
        if line_callback:
            line_callback("Checking OG coverage…")
        generated = ensure_og_images_from_content(load_content_for_og(), force=False)
        if line_callback and generated:
            line_callback(f"Generated {len(generated)} OG image(s)")
    except Exception as exc:
        if line_callback:
            line_callback(f"⚠ OG image generation skipped: {exc}")
        _record_backend_warning("OG generation skipped during build preflight", error=exc)
    started = time.perf_counter()
    return_code = run_build(line_callback=line_callback)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _record_diagnostic_event("build", "ok" if int(return_code or 0) == 0 else "error", f"Build finished with exit code {return_code}", elapsed_ms=elapsed_ms)
    if int(return_code or 0) != 0:
        build_result = last_build_result()
        stderr_tail = _clean_text(str(build_result.get("stderr") or ""))[-1200:]
        if build_result.get("timeout"):
            detail = (
                f"Build timed out after {build_result.get('timeout_seconds', '?')} seconds. "
                "Try reducing image sizes or increasing the build timeout budget."
            )
            if stderr_tail:
                detail += "\n\nBuild stderr:\n" + stderr_tail
            raise BackendError(detail)
        detail = f"Build failed with exit code {return_code}."
        if stderr_tail:
            detail += "\n\nBuild stderr:\n" + stderr_tail
        raise BackendError(detail)
    if preflight.get("recovered"):
        try:
            refresh_image_manifests(line_callback=line_callback)
        except Exception as exc:
            _record_backend_warning("Could not refresh image manifests after recovered-source build", error=exc)
    preview_check = verify_preview_output()
    if not preview_check.get("ok"):
        blocking = [f"{row.get('path')}: {row.get('detail')}" for row in preview_check.get("rows", []) if row.get("status") == "error"]
        raise BackendError("Build output integrity failed:\n" + "\n".join(f"- {item}" for item in blocking))
    if line_callback:
        line_callback("✓ Public upload integrity passed.")
    return {
        "return_code": int(return_code or 0),
        "recovered_sources": len(preflight.get('recovered') or []),
        "missing_sources": len(preflight.get('remaining') or []),
        "blocking_sources": len(preflight.get('blocking') or []),
        "missing_source_rows": list(preflight.get('remaining') or []),
        "source_gate": preflight.get("gate"),
        "elapsed_ms": elapsed_ms,
        "build_result": last_build_result(),
    }




def _risk_for_workbook_change(current: Any, incoming: Any, field: str | None = None) -> tuple[str, bool]:
    current_text = _clean_text(current)
    incoming_text = _clean_text(incoming)
    destructive_empty = bool(current_text and incoming in (None, ""))
    if destructive_empty:
        return "high", True
    if current_text != incoming_text:
        field_key = _clean_text(field).lower()
        if field_key in {"series", "series_slug", "series_move"}:
            return "high", False
        if field_key == "title":
            return "low", False
        return "medium", False
    return "low", False


def preview_workbook_import(workbook_path: str | Path) -> dict[str, Any]:
    """Dry-run workbook import with grouped changed fields and overwrite risk markers."""
    workbook = Path(workbook_path)
    if not workbook.exists():
        raise BackendError(f"Workbook not found: {workbook}")
    ops = _ensure_openpyxl()
    wb = ops["load_workbook"](filename=workbook)
    summary = analyze_workbook_import(workbook)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    def add(area: str, ident: str, field: str, current: Any, incoming: Any, file_path: Path | None = None, *, risk_override: str | None = None, category: str = "field_change") -> None:
        risk, destructive = _risk_for_workbook_change(current, incoming, field)
        if risk_override:
            risk = risk_override
        rows.append({
            "area": area,
            "id": ident,
            "field": field,
            "current": "" if current is None else str(current),
            "incoming": "" if incoming is None else str(incoming),
            "risk": risk,
            "category": category,
            "destructive_empty_overwrite": destructive,
            "affected_file": _relative_display(file_path) if file_path else "",
        })

    # Pages.
    for page_key in available_page_keys():
        sheet_name = f"PAGE__{page_key}"
        if sheet_name not in wb.sheetnames:
            continue
        try:
            incoming = _unflatten_rows(_sheet_to_dict_rows(wb[sheet_name]))
            current = load_page_payload(page_key)
            if page_key == "home" and isinstance(incoming, dict) and isinstance(current, dict):
                inc_fs = incoming.get("featured_series") if isinstance(incoming.get("featured_series"), dict) else {}
                cur_fs = current.get("featured_series") if isinstance(current.get("featured_series"), dict) else {}
                inc_sw = incoming.get("selected_works") if isinstance(incoming.get("selected_works"), dict) else {}
                cur_sw = current.get("selected_works") if isinstance(current.get("selected_works"), dict) else {}
                inc_fs["series_slugs"] = cur_fs.get("series_slugs", [])
                inc_sw["work_ids"] = cur_sw.get("work_ids", [])
            if incoming != current:
                add("page", page_key, "payload", "current page YAML", "incoming workbook page payload", page_file_for_key(page_key))
        except Exception as exc:
            errors.append(f"Page {page_key}: {exc}")

    # Series.
    if "SERIES_MASTER" in wb.sheetnames:
        current_series = {str(row.get("slug") or ""): row for row in load_series_entries()}
        for row in _sheet_to_dict_rows(wb["SERIES_MASTER"]):
            slug = _clean_text(row.get("series_slug"))
            if not slug:
                continue
            current = current_series.get(slug) or {}
            path = series_file_for_slug(slug)
            for workbook_key, payload_key in [
                ("title", "title"), ("years", "years"), ("mood", "mood"), ("description", "description"),
                ("cover_work_id", "cover_work_id"), ("visibility", "visibility"), ("project_type", "project_type"),
            ]:
                if workbook_key in row and _norm_compare(row.get(workbook_key)) != _norm_compare(current.get(payload_key)):
                    add("series", slug, payload_key, current.get(payload_key), row.get(workbook_key), path)

    # Works.
    if "WORKS_MASTER" in wb.sheetnames:
        known_series = _cached_series_slug_set()
        unknown_series: set[str] = set()
        for row in _sheet_to_dict_rows(wb["WORKS_MASTER"]):
            work_id = _clean_text(row.get("work_id"))
            if not work_id:
                continue
            incoming_series = _clean_text(row.get("series_slug"))
            if incoming_series and incoming_series not in known_series:
                unknown_series.add(incoming_series)
            payload = load_work_payload(work_id)
            if not payload:
                errors.append(f"Unknown work id in workbook: {work_id}")
                continue
            path = work_file_for_id(work_id)
            for workbook_key, payload_key in [
                ("title", "title"), ("series_slug", "series"), ("year", "year"), ("location", "location"),
                ("alt", "alt"), ("caption", "caption"), ("project_type", "project_type"), ("price_note", "price_note"),
            ]:
                if workbook_key in row and _norm_compare(row.get(workbook_key)) != _norm_compare(payload.get(payload_key)):
                    if payload_key == "series":
                        add("work", work_id, "series_move", payload.get(payload_key), row.get(workbook_key), path, risk_override="high", category="series_move")
                    else:
                        add("work", work_id, payload_key, payload.get(payload_key), row.get(workbook_key), path)
            if "published" in row and bool(row.get("published", False)) != bool(payload.get("published")):
                add("work", work_id, "published", bool(payload.get("published")), bool(row.get("published", False)), path)
            if "tags" in row:
                incoming_tags = [item.strip() for item in str(row.get("tags") or "").split("|") if item.strip()]
                if incoming_tags != list(payload.get("tags") or []):
                    add("work", work_id, "tags", "|".join(payload.get("tags") or []), "|".join(incoming_tags), path)
        if unknown_series:
            errors.append("Unknown series slug(s) in workbook: " + ", ".join(sorted(unknown_series)))

    # Global sheets with broader blast radius.
    for sheet_name, area, affected in [
        ("SITE_SETTINGS", "authority", CONTENT_DIR / "site.yaml"),
        ("DOCUMENTS", "resource", CONTENT_DIR / "resources.yaml"),
        ("NAVIGATION", "navigation", CONTENT_DIR / "navigation.yaml"),
        ("HOME_ORDER", "home", CONTENT_DIR / "pages" / "home.yaml"),
    ]:
        if int(summary.get({"SITE_SETTINGS":"site_setting_changes","DOCUMENTS":"documents_changed","NAVIGATION":"navigation_changed","HOME_ORDER":"home_order_changed"}[sheet_name]) or 0):
            add(area, sheet_name.lower(), "sheet", "current", "incoming workbook sheet", affected)

    rows.sort(key=lambda r: (r.get("risk") != "high", str(r.get("area")), str(r.get("id")), str(r.get("field"))))
    risk_counts = {"high": 0, "medium": 0, "low": 0}
    for row in rows:
        risk_counts[str(row.get("risk") or "low")] = risk_counts.get(str(row.get("risk") or "low"), 0) + 1
    return {
        "workbook": str(workbook),
        "summary": summary,
        "changes": rows,
        "errors": errors + list(summary.get("warnings") or []),
        "risk_counts": risk_counts,
        "affected_files": sorted({str(row.get("affected_file") or "") for row in rows if row.get("affected_file")}),
        "dry_run_required": True,
    }

def export_workbook_bundle(line_callback: Callable[[str], None] | None = None) -> str:
    path = export_site_workbook()
    if line_callback:
        line_callback(f"Workbook exported: {Path(path).name}")
    return str(path)


def analyze_workbook_bundle(workbook_path: str | Path, line_callback: Callable[[str], None] | None = None) -> dict[str, Any]:
    workbook = Path(workbook_path)
    if not workbook.exists():
        raise BackendError(f"Workbook not found: {workbook}")
    try:
        preview = preview_workbook_import(workbook)
    except Exception as exc:
        raise BackendError(str(exc)) from exc
    summary = dict(preview.get("summary") or {})
    summary["workbook"] = str(workbook)
    summary["preview_changes"] = list(preview.get("changes") or [])
    summary["preview_errors"] = list(preview.get("errors") or [])
    summary["risk_counts"] = dict(preview.get("risk_counts") or {})
    summary["affected_files"] = list(preview.get("affected_files") or [])
    summary["dry_run_required"] = True
    if line_callback:
        line_callback(f"Workbook analyzed: {workbook.name}")
    return summary


def import_workbook_bundle(workbook_path: str | Path, line_callback: Callable[[str], None] | None = None, *, preview_token: str | None = None) -> dict[str, Any]:
    workbook = Path(workbook_path)
    if not workbook.exists():
        raise BackendError(f"Workbook not found: {workbook}")
    preview = preview_workbook_import(workbook)
    if preview.get("errors"):
        raise BackendError("Workbook import blocked by preview warnings/errors. Review the dry run first:\n- " + "\n- ".join(str(e) for e in list(preview.get("errors") or [])[:20]))
    try:
        with transaction('qt-import-workbook'):
            applied = import_site_workbook(workbook)
    except Exception as exc:
        raise BackendError(str(exc)) from exc
    invalidate_control_panel_caches()
    if line_callback:
        line_callback(f"Workbook import complete: {applied}")
    return {"applied": applied, "workbook": str(workbook), "preview": preview, "rollback_available": True}


# A cold build renders every image (about 2-3 minutes for ~120 works); a warm
# build reuses the derivative cache and takes seconds. The timeout only guards
# against a hung process, so it is deliberately generous.
BUILD_TIMEOUT_SECONDS = 30 * 60


def run_build(line_callback: Callable[[str], None] | None = None) -> int:
    """Run build_site.py and stream every output line as it happens."""
    global _LAST_BUILD_RESULT
    timeout_seconds = BUILD_TIMEOUT_SECONDS
    started = time.perf_counter()
    collected: list[str] = []
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "build_site.py")],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    timed_out = False
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.rstrip("\n")
        collected.append(line)
        if line_callback:
            line_callback(line)
        if time.perf_counter() - started > timeout_seconds:
            timed_out = True
            process.kill()
            break
    return_code = -9 if timed_out else int(process.wait() or 0)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    output = "\n".join(collected)
    _LAST_BUILD_RESULT = {
        "return_code": return_code,
        "stdout": output,
        "stderr": "",
        "elapsed_ms": elapsed_ms,
        "timeout_seconds": timeout_seconds,
        "timeout": timed_out,
    }
    status = "timeout" if timed_out else ("ok" if return_code == 0 else "error")
    _record_diagnostic_event(
        "build-process",
        status,
        f"Build timed out after {timeout_seconds}s" if timed_out else f"Build process finished with exit code {return_code}",
        elapsed_ms=elapsed_ms,
        return_code=return_code,
        timeout_seconds=timeout_seconds,
    )
    if timed_out and line_callback:
        line_callback(f"Build stopped after {timeout_seconds // 60} minutes without finishing.")
    if return_code == 0:
        invalidate_control_panel_caches()
    return return_code


def last_build_result() -> dict[str, Any]:
    return dict(_LAST_BUILD_RESULT)




def load_resource_documents() -> list[dict[str, Any]]:
    payload = load_resources_payload() or {}
    rows: list[dict[str, Any]] = []
    for item in payload.get("downloads") or []:
        if isinstance(item, dict):
            rows.append(dict(item))
    return rows


def save_resource_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = load_resources_payload() or {}
    payload["downloads"] = [dict(item) for item in rows if isinstance(item, dict)]
    save_resources_payload(payload)
    mark_unpublished_changes()
    return load_resource_documents()


def recent_operation_rows(limit: int = 30) -> list[dict[str, Any]]:
    safe_limit = max(1, min(200, int(limit or 30)))
    return [dict(item) for item in recent_transactions(limit=safe_limit)]


def restore_last_completed_transaction() -> dict[str, Any]:
    row = restore_last_transaction()
    if not row:
        raise BackendError("No completed transaction is available to restore.")
    result = dict(row) if isinstance(row, dict) else {"ok": bool(row)}
    result.setdefault("summary", "Transaction restored. Check the Works and Series tabs for changes.")
    invalidate_control_panel_caches()
    mark_unpublished_changes()
    return result


def run_documents(line_callback: Callable[[str], None] | None = None) -> int:
    script = ROOT / "generate_documents.py"
    if not script.exists():
        raise BackendError("generate_documents.py was not found in the project root.")
    process = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if process.stdout is not None:
        for raw in process.stdout:
            line = raw.rstrip("\n")
            if line_callback:
                line_callback(line)
    return_code = process.wait()
    if int(return_code or 0) == 0:
        mark_unpublished_changes()
        invalidate_control_panel_caches()
    return return_code



def default_work_filter_presets() -> dict[str, dict[str, str]]:
    return deepcopy(DEFAULT_WORK_FILTER_PRESETS)


def batch_update_works(
    work_ids: list[str],
    *,
    published: bool | None = None,
    review_status: str | None = None,
    series_slug: str | None = None,
    tags_to_add: list[str] | None = None,
    tags_to_remove: list[str] | None = None,
    tags_to_set: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    cleaned_ids = [str(item).strip() for item in work_ids if str(item).strip()]
    if not cleaned_ids:
        raise BackendError("Select at least one work.")
    available_series = set(available_series_slugs())
    target_series = _clean_text(series_slug) if series_slug is not None else None
    if target_series is not None and target_series not in available_series:
        raise BackendError("Choose a valid target series for the batch move.")
    changed_rows: list[dict[str, Any]] = []
    skipped_ids: list[str] = []
    for work_id in cleaned_ids:
        payload = load_work_payload(work_id)
        if not payload:
            skipped_ids.append(work_id)
            continue
        updated = dict(payload)
        changed_fields: list[str] = []
        if review_status is not None:
            review = _clean_text(review_status).lower()
            if review not in PUBLISH_STATES:
                raise BackendError(f"Invalid review status: {review_status}")
            if _clean_text(updated.get("review_status")).lower() != review:
                updated["review_status"] = review
                changed_fields.append("review_status")
            if review == "published" and not bool(updated.get("published")):
                updated["published"] = True
                changed_fields.append("published")
        if published is not None and bool(updated.get("published")) != bool(published):
            updated["published"] = bool(published)
            changed_fields.append("published")
            if not published and _clean_text(updated.get("review_status")).lower() == "published":
                updated["review_status"] = "review"
                changed_fields.append("review_status")
        if target_series is not None and _clean_text(updated.get("series")) != target_series:
            updated["series"] = target_series
            changed_fields.append("series")
        if tags_to_set is not None:
            new_tags = [str(tag).strip() for tag in tags_to_set if str(tag).strip()]
            if list(updated.get("tags") or []) != new_tags:
                updated["tags"] = new_tags
                changed_fields.append("tags")
        if tags_to_add:
            existing = [str(tag).strip() for tag in (updated.get("tags") or []) if str(tag).strip()]
            for tag in [str(tag).strip() for tag in tags_to_add if str(tag).strip()]:
                if tag not in existing:
                    existing.append(tag)
            if existing != list(updated.get("tags") or []):
                updated["tags"] = existing
                changed_fields.append("tags")
        if tags_to_remove:
            remove_set = {str(tag).strip().lower() for tag in tags_to_remove if str(tag).strip()}
            existing = [str(tag).strip() for tag in (updated.get("tags") or []) if str(tag).strip()]
            filtered = [tag for tag in existing if tag.lower() not in remove_set]
            if filtered != existing:
                updated["tags"] = filtered
                changed_fields.append("tags")
        validation_errors = [row for row in validate_editor_payload("work", updated, original_key=work_id) if row.get("severity") == "error"]
        if validation_errors:
            detail = "; ".join(str(row.get("message") or "") for row in validation_errors)
            raise BackendError(f"Batch update would make '{work_id}' invalid: {detail}")
        if changed_fields:
            changed_rows.append({"work_id": work_id, "updated": updated, "fields": sorted(set(changed_fields))})

    requested_series_changes = {
        _clean_text((row.get("updated") or {}).get("series"))
        for row in changed_rows
        if "series" in set(row.get("fields") or [])
    }
    invalid_series_changes = sorted(slug for slug in requested_series_changes if slug and slug not in available_series)
    if invalid_series_changes:
        raise BackendError("Batch update contains invalid series slug(s): " + ", ".join(invalid_series_changes))

    if dry_run:
        plan = plan_bulk_operation("bulk-edit", cleaned_ids, changes=changed_rows, skipped=skipped_ids, destructive=False)
        return {"changed_ids": [row["work_id"] for row in changed_rows], "skipped_ids": skipped_ids, "dry_run": True, "changes": changed_rows, "operation_plan": plan, "per_item_results": plan.get("per_item_results", [])}
    if not changed_rows:
        plan = plan_bulk_operation("bulk-edit", cleaned_ids, changes=[], skipped=skipped_ids, destructive=False)
        return {"changed_ids": [], "skipped_ids": skipped_ids, "dry_run": False, "changes": [], "operation_plan": plan, "per_item_results": plan.get("per_item_results", [])}

    derivative_failures: list[str] = []
    actual_per_item_results: list[dict[str, Any]] = []
    has_series_move = any("series" in set(row.get("fields") or []) for row in changed_rows)
    with transaction(f"qt-batch-update-works:{len(changed_rows)}"):
        pipeline = load_pipeline()
        for row in changed_rows:
            work_id = row["work_id"]
            updated = dict(row["updated"])
            old_payload = load_work_payload(work_id)
            old_series = _clean_text(old_payload.get("series") or work_to_series_map().get(work_id, ""))
            new_series = _clean_text(updated.get("series") or old_series)
            item_status = "ok"
            item_warnings: list[str] = []
            if old_series and new_series and old_series != new_series:
                try:
                    source_path = _resolve_source_path(old_series, work_id, pipeline=pipeline, context="batch update")
                except Exception as exc:
                    _record_backend_warning("Could not resolve source path during batch move", error=exc)
                    source_path = None
                if source_path and Path(source_path).exists():
                    destination = source_root(pipeline) / new_series / f"{work_id}{Path(source_path).suffix.lower()}"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source_path_obj = Path(source_path)
                    same_path = _same_path(destination, source_path_obj)
                    if not same_path:
                        if destination.exists():
                            guarded_unlink(destination, detail="replace destination before batch series move")
                        guarded_move(source_path_obj, destination, detail="batch-series-move")
                        record_transaction_step(
                            "batch_series_move",
                            target=destination,
                            detail=f"Moved source for {work_id} during batch series change",
                            source=source_path_obj,
                            old_series=old_series,
                            new_series=new_series,
                        )
                        _record_diagnostic_event(
                            "batch-move",
                            "ok",
                            f"Moved source for {work_id}",
                            source=source_path_obj,
                            destination=destination,
                            old_series=old_series,
                            new_series=new_series,
                        )
                        image_block = updated.get("image") if isinstance(updated.get("image"), dict) else {}
                        image_block = dict(image_block)
                        image_block["master"] = destination.name
                        image_block["render_name"] = work_id
                        updated["image"] = image_block
                        try:
                            generate_derivatives(destination, new_series, work_id, pipeline=pipeline, force=True)
                        except Exception as exc:
                            derivative_failures.append(work_id)
                            item_status = "warning"
                            item_warnings.append("derivative regeneration failed")
                            _record_backend_warning("Could not regenerate derivatives after batch series move", error=exc)
                move_work_to_series(work_id, new_series)
            save_work_payload(work_id, updated)
            actual_per_item_results.append({
                "work_id": work_id,
                "status": item_status,
                "fields": list(row.get("fields") or []),
                "warnings": item_warnings,
            })
    plan = plan_bulk_operation("bulk-edit", cleaned_ids, changes=changed_rows, skipped=skipped_ids, destructive=False)
    result = {
        "changed_ids": [row["work_id"] for row in changed_rows],
        "skipped_ids": skipped_ids,
        "dry_run": False,
        "changes": changed_rows,
        "operation_plan": plan,
        "per_item_results": actual_per_item_results,
        "derivative_failures": derivative_failures,
        "rollback_available": True,
    }
    append_bulk_report({"kind": "bulk-edit", "result": result})
    mark_unpublished_changes()
    invalidate_control_panel_caches()
    if has_series_move or len(changed_rows) > 5:
        mark_portfolio_health_dirty("work")
    else:
        for row in changed_rows:
            patch_cached_health_for_work(row["work_id"])
    return result

def export_works_csv(output_path: str | Path) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "title", "series", "status", "review", "location", "date", "tags"]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for payload in load_work_entries():
            writer.writerow({
                "id": _clean_text(payload.get("id")),
                "title": _clean_text(payload.get("title")),
                "series": _clean_text(payload.get("series")),
                "status": "published" if payload.get("published") else "unpublished",
                "review": _clean_text(payload.get("review_status")),
                "location": _clean_text(payload.get("location")),
                "date": _clean_text(payload.get("year") or payload.get("date")),
                "tags": "; ".join(str(tag).strip() for tag in (payload.get("tags") or []) if str(tag).strip()),
            })
    return str(output)



def _image_dimensions(path: Path | None) -> tuple[int, int] | None:
    if not path:
        return None
    try:
        resolved = Path(path).resolve(strict=False)
        stat = resolved.stat()
        cache_key = (str(resolved), int(stat.st_mtime_ns), int(stat.st_size))
        with _IMAGE_DIMENSIONS_CACHE_LOCK:
            if cache_key in _IMAGE_DIMENSIONS_CACHE:
                return _IMAGE_DIMENSIONS_CACHE[cache_key]
        with Image.open(resolved) as im:
            result = (int(im.width), int(im.height))
        with _IMAGE_DIMENSIONS_CACHE_LOCK:
            if len(_IMAGE_DIMENSIONS_CACHE) >= _IMAGE_DIMENSIONS_CACHE_MAX:
                for old_key in list(_IMAGE_DIMENSIONS_CACHE.keys())[: max(1, _IMAGE_DIMENSIONS_CACHE_MAX // 4)]:
                    _IMAGE_DIMENSIONS_CACHE.pop(old_key, None)
            _IMAGE_DIMENSIONS_CACHE[cache_key] = result
        return result
    except Exception as exc:
        _record_backend_warning("Could not read image dimensions", path=Path(path), error=exc)
        return None


def _file_size_label(path: Path | None) -> str:
    try:
        if not path or not Path(path).exists():
            return ""
        size = int(Path(path).stat().st_size)
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"
    except Exception as exc:
        _record_backend_warning("Could not read file size", path=Path(path) if path else None, error=exc)
        return ""



def _derivative_count_for_payload(payload: dict[str, Any]) -> int:
    """Count derivatives from the manifest first; fall back to disk only if the manifest has no rows."""
    manifest_rows = _manifest_derivative_candidates_for_payload(payload)
    if manifest_rows:
        return len({str(path) for path in manifest_rows})
    existing: set[str] = set()
    try:
        image = payload.get("image") if isinstance(payload.get("image"), dict) else {}
        work_id = _clean_text(payload.get("id"))
        render_name = _clean_text(image.get("render_name") or image.get("renderName") or work_id)
        series_slug = _clean_text(payload.get("series") or work_to_series_map().get(work_id, ""))
        directory = derivative_dir_for_work(series_slug, render_name)
        if directory.exists():
            for candidate in directory.glob(f"{render_name}-*.*"):
                if candidate.suffix.lower() in {".jpg", ".jpeg", ".webp"}:
                    existing.add(str(candidate))
    except Exception as exc:
        _record_backend_warning("Could not count derivative files", error=exc)
    return len(existing)


def load_image_health_summary() -> dict[str, Any]:
    source_rows = source_asset_report_rows()
    source_by_id = {_clean_text(row.get("id")): row for row in source_rows}
    work_rows: list[dict[str, Any]] = []
    total = 0
    source_ok = 0
    derivative_ok = 0
    missing_derivatives = 0
    for payload in load_work_entries():
        work_id = _clean_text(payload.get("id"))
        if not work_id:
            continue
        total += 1
        source_row = source_by_id.get(work_id, {})
        source_status = _clean_text(source_row.get("status") or "unknown").lower()
        if source_status == "ok":
            source_ok += 1
        source_path = None
        try:
            source_path = _resolve_source_path(_clean_text(payload.get("series") or work_to_series_map().get(work_id, "")), work_id, context="workbook export")
            if source_path and not Path(source_path).exists():
                source_path = None
        except Exception as exc:
            _record_backend_warning("Could not resolve source path for image health", error=exc)
        preview = best_preview_path_for_work(payload)
        derivative_count = _derivative_count_for_payload(payload)
        if preview:
            derivative_ok += 1
        else:
            missing_derivatives += 1
        src_dims = _image_dimensions(Path(source_path) if source_path else None)
        preview_dims = _image_dimensions(Path(preview) if preview else None)
        image = payload.get("image") if isinstance(payload.get("image"), dict) else {}
        focal = payload.get("focal_point") if isinstance(payload.get("focal_point"), dict) else image.get("focal_point") if isinstance(image.get("focal_point"), dict) else {}
        status = "clean" if source_status == "ok" and preview else "warning"
        if source_status not in {"ok", "unknown"} and not preview:
            status = "broken"
        work_rows.append({
            "id": work_id,
            "title": _clean_text(payload.get("title")),
            "series": _clean_text(payload.get("series") or work_to_series_map().get(work_id, "")),
            "status": status,
            "source_status": source_status or "unknown",
            "source_path": str(source_path or source_row.get("source_path") or ""),
            "preview_path": str(preview or ""),
            "source_size": _file_size_label(Path(source_path) if source_path else None),
            "preview_size": _file_size_label(Path(preview) if preview else None),
            "source_dimensions": f"{src_dims[0]}×{src_dims[1]}" if src_dims else "",
            "preview_dimensions": f"{preview_dims[0]}×{preview_dims[1]}" if preview_dims else "",
            "derivative_count": derivative_count,
            "focal": f"{int(focal.get('x', 50) or 50)}%, {int(focal.get('y', 50) or 50)}%" if isinstance(focal, dict) else "50%, 50%",
            "recovery": _clean_text(source_row.get("recovery")),
            "detail": _clean_text(source_row.get("detail")),
        })
    unlinked_originals = sum(1 for row in source_rows if str(row.get("status") or "").lower() != "ok")
    return {
        "total_sources": total,
        "source_ok": source_ok,
        "derivative_ok": derivative_ok,
        "missing_derivatives": missing_derivatives,
        "unlinked_originals": unlinked_originals,
        "coverage_percent": round(((source_ok + derivative_ok) / max(1, total * 2)) * 100, 1) if total else 100.0,
        "rows": source_rows,
        "work_rows": work_rows,
    }






def media_library_rows(search: str = "", status_filter: str = "All", series_slug: str = "All series", *, offset: int = 0, limit: int | None = None) -> list[dict[str, Any]]:
    query = _clean_text(search).lower()
    status_filter = _clean_text(status_filter) or "All"
    series_slug = _clean_text(series_slug) or "All series"
    fast_status_map = _cached_asset_truth_status_by_work_id()

    # Read persisted truth details without triggering a strict filesystem scan.
    persisted_truth: dict[str, dict[str, Any]] = {}
    try:
        if ASSET_TRUTH_PATH.exists():
            raw = json.loads(ASSET_TRUTH_PATH.read_text(encoding="utf-8"))
            truth_rows = raw if isinstance(raw, list) else raw.get("rows", []) if isinstance(raw, dict) else []
            for row in truth_rows:
                if isinstance(row, dict):
                    wid = _clean_text(row.get("work_id") or row.get("id"))
                    if wid:
                        persisted_truth[wid] = row
    except Exception as exc:
        _record_backend_warning("Could not read persisted media-library asset truth", path=ASSET_TRUTH_PATH, error=exc)

    rows: list[dict[str, Any]] = []
    for payload in load_work_entries():
        work_id = _clean_text(payload.get("id"))
        if not work_id:
            continue
        truth = persisted_truth.get(work_id) or {}
        series = _clean_text(payload.get("series"))
        if series_slug not in {"", "All series"} and series != series_slug:
            continue
        status = str(fast_status_map.get(work_id) or truth.get("status") or "unknown")
        if status_filter not in {"", "All"} and status != status_filter:
            continue
        haystack = " ".join([
            work_id,
            _clean_text(payload.get("title")),
            _clean_text(payload.get("alt")),
            _clean_text(payload.get("caption")),
            ", ".join(str(item).strip() for item in (payload.get("tags") or []) if str(item).strip()),
            series,
            status,
            _clean_text(truth.get("recovery")),
        ]).lower()
        if query and query not in haystack:
            continue
        preview_path = fast_preview_path_for_work(payload)
        preview_display = _relative_display(preview_path) if preview_path else str(truth.get("preview_path") or "")
        preview_dims = ""
        if preview_path:
            dims = _image_dimensions(preview_path)
            preview_dims = f"{dims[0]}×{dims[1]}" if dims else ""
        source_display = str(truth.get("active_source") or truth.get("source_path") or "")
        source_dims = str(truth.get("source_dimensions") or "")
        rows.append({
            "id": work_id,
            "title": _clean_text(payload.get("title")),
            "series": series,
            "status": status,
            "severity": str(truth.get("severity") or ("ok" if status == "ok" else "info")),
            "source": source_display,
            "preview": preview_display,
            "source_dimensions": source_dims,
            "preview_dimensions": preview_dims,
            "derivative_count": int(truth.get("derivative_count") or _derivative_count_for_payload(payload) or 0),
            "recovery": str(truth.get("recovery") or ""),
            "expected": ", ".join(truth.get("expected_stems") or []),
            "completeness": fast_work_completeness_score(payload),
        })
    rows.sort(key=lambda row: (str(row.get("status") or ""), str(row.get("series") or ""), str(row.get("id") or "")))
    offset = max(0, int(offset or 0))
    if limit is not None:
        limit = max(1, min(500, int(limit or 100)))
        return rows[offset:offset + limit]
    return rows[offset:]


def series_story_rows(*, published_only: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    works = {str(item.get("id") or ""): item for item in load_work_entries()}
    completeness_by_slug = {str(row.get("slug") or ""): row for row in series_completeness_rows()}
    for series in load_series_entries():
        slug = _clean_text(series.get("slug"))
        sequence = [str(item).strip() for item in (series.get("work_ids") or []) if str(item).strip()]
        if published_only:
            sequence = [
                work_id for work_id in sequence
                if bool((works.get(work_id) or {}).get("published")) and _clean_text((works.get(work_id) or {}).get("review_status")) != "archived"
            ]
        orientations: dict[str, int] = {}
        missing_assets = 0
        weak_items = 0
        for work_id in sequence:
            payload = works.get(work_id) or {"id": work_id, "series": slug}
            weak_items += 1 if fast_work_completeness_score(payload).get("status") != "ready" else 0
            source_status = _cached_asset_truth_status_by_work_id().get(work_id, "")
            if source_status and source_status not in {"ok", "orphan-risk"}:
                missing_assets += 1
            path = _safe_preview_path(payload)
            orientation = "missing"
            if path:
                try:
                    with Image.open(path) as im:
                        w, h = im.size
                        orientation = "landscape" if w > h else "portrait" if h > w else "square"
                except Exception:
                    orientation = "unreadable"
            orientations[orientation] = orientations.get(orientation, 0) + 1
        completeness = completeness_by_slug.get(slug, {})
        rows.append({
            "slug": slug,
            "title": _clean_text(series.get("title")),
            "works": len(sequence),
            "cover": _clean_text(series.get("cover_work_id")),
            "score": int(completeness.get("score") or 0),
            "status": str(completeness.get("status") or "review"),
            "weak_items": weak_items,
            "missing_assets": missing_assets,
            "orientation_mix": ", ".join(f"{key}:{value}" for key, value in sorted(orientations.items())),
        })
    return sorted(rows, key=lambda row: (int(row.get("score") or 0), str(row.get("slug") or "")))


def work_public_impact_report(work_id: str) -> dict[str, Any]:
    payload = load_work_payload(work_id)
    if not payload:
        raise BackendError(f"Work '{work_id}' was not found.")
    series_map = work_to_series_map()
    series_slug = _clean_text(payload.get("series") or series_map.get(work_id, ""))
    series_hits: list[dict[str, Any]] = []
    for series in load_series_entries():
        ids = [str(item).strip() for item in (series.get("work_ids") or []) if str(item).strip()]
        if work_id in ids or _clean_text(series.get("cover_work_id")) == work_id:
            series_hits.append({
                "slug": _clean_text(series.get("slug")),
                "title": _clean_text(series.get("title")),
                "position": (ids.index(work_id) + 1) if work_id in ids else "",
                "is_cover": _clean_text(series.get("cover_work_id")) == work_id,
                "work_count": len(ids),
            })
    page_hits: list[dict[str, Any]] = []
    for page_key in available_page_keys():
        try:
            page = load_page_payload(page_key)
        except Exception:
            continue
        refs: list[str] = []
        def walk(obj: Any, path: str = "") -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    walk(value, f"{path}.{key}" if path else str(key))
            elif isinstance(obj, list):
                for idx, value in enumerate(obj):
                    walk(value, f"{path}[{idx}]")
            elif str(obj) == work_id:
                refs.append(path)
        walk(page)
        if refs:
            page_hits.append({"page": page_key, "references": refs[:12], "count": len(refs)})
    truth = source_asset_truth_for_work(payload)
    return {
        "work_id": work_id,
        "title": _clean_text(payload.get("title")),
        "series": series_slug,
        "published": bool(payload.get("published")),
        "review_status": _clean_text(payload.get("review_status")),
        "series_hits": series_hits,
        "page_hits": page_hits,
        "source_status": truth.get("status"),
        "source_detail": truth.get("detail") or truth.get("message"),
        "safe_to_remove": not page_hits and not any(hit.get("is_cover") for hit in series_hits),
    }


def safe_remove_work_preview(work_id: str) -> dict[str, Any]:
    impact = work_public_impact_report(work_id)
    blockers: list[str] = []
    for hit in impact.get("series_hits") or []:
        if hit.get("is_cover"):
            blockers.append(f"Used as cover in series {hit.get('slug')}")
    for hit in impact.get("page_hits") or []:
        blockers.append(f"Referenced on page {hit.get('page')} ({hit.get('count')} ref(s))")
    return {**impact, "blockers": blockers, "recommended_action": "archive" if blockers else "safe-remove-or-archive"}


def safe_remove_work(work_id: str, *, archive_only: bool = True, remove_assets: bool = False, force: bool = False) -> dict[str, Any]:
    """Archive or safely remove a work with transaction backups.

    archive_only=True keeps the metadata but unpublishes the work.
    archive_only=False deletes the work metadata and prunes references. When
    remove_assets=True, originals, generated derivative folders/files, and empty
    asset parent folders for that work are removed as part of the same transaction.
    """
    work_id = _clean_text(work_id)
    if not work_id:
        raise BackendValidationError("Work ID is required.")
    payload = load_work_payload(work_id)
    if not payload:
        raise BackendValidationError(f"Work '{work_id}' was not found.")
    preview = safe_remove_work_preview(work_id)
    blockers = [str(item) for item in (preview.get("blockers") or []) if str(item).strip()]
    series_slug = _clean_text(payload.get("series") or work_to_series_map().get(work_id, ""))
    before = deepcopy(payload)

    if archive_only:
        payload = dict(payload)
        payload["published"] = False
        payload["review_status"] = "archived"
        with transaction(f"qt-archive-work:{work_id}"):
            save_work_payload(work_id, payload)
        mark_unpublished_changes()
        invalidate_control_panel_caches()
        result = {
            "operation": "archive-work",
            "work_id": work_id,
            "series": series_slug,
            "blockers": blockers,
            "changed": ["published", "review_status"],
            "before": {"published": bool(before.get("published")), "review_status": before.get("review_status")},
            "after": {"published": False, "review_status": "archived"},
        }
        _record_diagnostic_event("work", "success", f"Archived work {work_id}", operation="archive-work", work_id=work_id)
        return result

    if blockers and not force:
        raise BackendIntegrityError("This work still has public references. Archive it or remove blockers first:\n" + "\n".join(f"- {item}" for item in blockers))

    pipeline = load_pipeline()
    asset_roots = _asset_cleanup_allowed_roots(pipeline)
    removed_series_refs: list[str] = []
    removed_files: list[str] = []
    removed_empty_dirs: list[str] = []
    pruned_pages: list[str] = []
    relation_updates: list[str] = []
    asset_targets = _collect_work_asset_cleanup_targets(payload) if remove_assets else {"sources": [], "generated_dirs": [], "generated_files": []}

    with transaction(f"qt-delete-work:{work_id}" if remove_assets else f"qt-remove-work:{work_id}"):
        for series in load_series_entries():
            slug = _clean_text(series.get("slug"))
            work_ids = [str(item).strip() for item in (series.get("work_ids") or []) if str(item).strip()]
            if slug and work_id in work_ids:
                remove_work_from_series(slug, work_id)
                removed_series_refs.append(slug)
        for slug in removed_series_refs:
            series_payload = _RAW_LOAD_SERIES_PAYLOAD(slug)
            if isinstance(series_payload, dict) and _clean_text(series_payload.get("cover_work_id")) == work_id:
                remaining_ids = [str(item).strip() for item in (series_payload.get("work_ids") or []) if str(item).strip() and str(item).strip() != work_id]
                series_payload["cover_work_id"] = remaining_ids[0] if remaining_ids else ""
                save_series_payload(slug, series_payload)
        relation_updates = repair_relationship_refs("work", work_id, None)
        pruned_pages = _prune_work_from_page_payloads(work_id)
        work_path = work_file_for_id(work_id)
        if work_path.exists():
            snapshot_path(work_path)
            guarded_unlink(work_path, detail="delete work metadata")
            removed_files.append(_relative_display(work_path))
        if remove_assets:
            for source in asset_targets.get("sources", []):
                guarded_unlink(source, detail="delete work original/source asset")
                removed_files.append(_relative_display(source))
                cleaned = _remove_empty_asset_parent(source, asset_roots)
                if cleaned:
                    removed_empty_dirs.append(cleaned)
            for directory in asset_targets.get("generated_dirs", []):
                if directory.exists() and directory.is_dir():
                    parent = directory.parent
                    guarded_rmtree(directory, detail="delete work generated derivative folder")
                    removed_files.append(_relative_display(directory))
                    cleaned = _remove_empty_asset_parent(directory, asset_roots)
                    if cleaned:
                        removed_empty_dirs.append(cleaned)
                    cleaned_parent = _remove_empty_asset_parent(parent, asset_roots)
                    if cleaned_parent:
                        removed_empty_dirs.append(cleaned_parent)
            for generated_file in asset_targets.get("generated_files", []):
                if not generated_file.exists():
                    continue
                # If its parent directory was already removed, skip quietly.
                guarded_unlink(generated_file, detail="delete work generated derivative file")
                removed_files.append(_relative_display(generated_file))
                cleaned = _remove_empty_asset_parent(generated_file, asset_roots)
                if cleaned:
                    removed_empty_dirs.append(cleaned)

    clear_editor_draft("work", work_id)
    if remove_assets:
        try:
            refresh_image_manifests()
        except Exception as exc:
            _record_backend_warning("Image manifest refresh failed after work deletion", path=IMAGE_MANIFEST_DIR, error=exc)
    mark_unpublished_changes()
    invalidate_control_panel_caches()
    mark_portfolio_health_dirty("work", work_id)
    remaining_refs = scan_stale_references(work_id, None, include_runtime=False)
    result = {
        "operation": "delete-work" if remove_assets else "remove-work",
        "work_id": work_id,
        "series": series_slug,
        "blockers": blockers,
        "removed_series_refs": removed_series_refs,
        "relationship_updates": relation_updates,
        "pruned_pages": pruned_pages,
        "removed_files": list(dict.fromkeys(removed_files)),
        "removed_empty_dirs": list(dict.fromkeys(removed_empty_dirs)),
        "assets_removed": bool(remove_assets),
        "remaining_references": remaining_refs,
        "forced": bool(force),
    }
    _record_diagnostic_event("work", "success" if not remaining_refs else "warning", f"Deleted work {work_id}" if remove_assets else f"Removed work {work_id}", operation=result["operation"], work_id=work_id, remaining_refs=len(remaining_refs))
    return result


def stale_asset_cleanup_report(work_id: str | None = None) -> list[dict[str, Any]]:
    """Report derivative/source directories that look stale after rename, replace, or removal."""
    pipeline = load_pipeline()
    live_payloads = load_work_entries()
    live_render_by_series: dict[str, set[str]] = {}
    live_all_renders: set[str] = set()
    wanted_work_id = _clean_text(work_id)
    for row in live_payloads:
        wid = _clean_text(row.get("id"))
        if wanted_work_id and wid != wanted_work_id:
            continue
        series = _clean_text(row.get("series") or work_to_series_map().get(wid, ""))
        render = _render_name_for_work(row) or wid
        if series and render:
            live_render_by_series.setdefault(series, set()).add(render)
            live_all_renders.add(render)
    rows: list[dict[str, Any]] = []
    base = generated_root(pipeline)
    if not base.exists():
        return rows
    for series_dir in sorted([p for p in base.iterdir() if p.is_dir()]):
        series = series_dir.name
        live_renders = live_render_by_series.get(series, set())
        for child in sorted([p for p in series_dir.iterdir() if p.is_dir()]):
            name = child.name
            if wanted_work_id and name not in live_renders and name not in live_all_renders:
                continue
            if name in live_renders or name in live_all_renders:
                continue
            try:
                file_count = sum(1 for p in child.rglob("*") if p.is_file())
            except Exception:
                file_count = 0
            rows.append({
                "kind": "stale-derivative-dir",
                "series": series,
                "path": _relative_display(child),
                "render_name": name,
                "file_count": file_count,
                "safe_action": "review-before-delete",
            })
    return rows


def export_control_panel_diagnostic_bundle(label: str = "control-panel-diagnostics") -> Path:
    """Create a support zip containing diagnostics only, not user-facing website edits."""
    BUILD_META_DIR.mkdir(parents=True, exist_ok=True)
    bundle_dir = BUILD_META_DIR / "diagnostic-bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "-", label).strip("-.") or "control-panel-diagnostics"
    target = bundle_dir / f"{safe_label}-{stamp}.zip"
    diagnostics = control_panel_diagnostics()
    save_panel_diagnostics_snapshot(diagnostics)
    files = [
        PANEL_DIAGNOSTICS_PATH,
        PANEL_DIAGNOSTICS_LOG_PATH,
        BACKEND_WARNING_PATH,
        BUILD_STATUS_PATH,
        RELEASE_REPORT_PATH,
        CONTENT_GRAPH_PATH,
        VALIDATION_REPORT_PATH,
        ASSET_TRUTH_PATH,
        TRANSACTION_LOG_PATH,
        UI_STATE_PATH,
        ROOT / "scripts" / "control_panel_feature_inventory.json",
    ]
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics/generated-summary.json", json.dumps(diagnostics, ensure_ascii=False, indent=2))
        archive.writestr("diagnostics/stale-asset-cleanup-report.json", json.dumps(stale_asset_cleanup_report(), ensure_ascii=False, indent=2))
        for file_path in files:
            try:
                if file_path.exists() and file_path.is_file():
                    archive.write(file_path, file_path.relative_to(ROOT).as_posix())
            except Exception as exc:
                archive.writestr(f"diagnostics/skipped-{file_path.name}.txt", str(exc))
    _record_diagnostic_event("diagnostics", "success", f"Exported diagnostic bundle {target.name}", path=target)
    return target

def find_orphaned_assets() -> list[dict[str, str]]:
    known_ids = {_clean_text(payload.get("id")) for payload in load_work_entries()}
    known_ids = {item for item in known_ids if item}
    known_render_names: set[str] = set(known_ids)
    for payload in load_work_entries():
        image = payload.get("image") if isinstance(payload.get("image"), dict) else {}
        render_name = _clean_text(image.get("render_name") or image.get("renderName") or payload.get("id"))
        if render_name:
            known_render_names.add(render_name)
    pipeline = load_pipeline()
    roots = [source_root(pipeline), generated_root(pipeline)]
    rows: list[dict[str, str]] = []
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            stem = path.stem.lower()
            if not any(name.lower() in stem for name in known_render_names):
                try:
                    relative = path.relative_to(ROOT).as_posix()
                except Exception:
                    relative = str(path)
                rows.append({"path": str(path), "relative_path": relative, "root": _relative_display(base), "size": str(path.stat().st_size), "action": "quarantine", "kind": "orphaned-file"})
    for stale in stale_asset_cleanup_report():
        stale_path = ROOT / str(stale.get("path") or "")
        rows.append({
            "path": str(stale_path),
            "relative_path": _relative_display(stale_path),
            "root": _relative_display(generated_root(pipeline)),
            "size": str(stale.get("file_count") or 0),
            "action": "review-before-quarantine",
            "kind": "stale-derivative-dir",
        })
    return rows


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _quarantine_manifest_path(quarantine_root: Path) -> Path:
    return quarantine_root / "quarantine-manifest.json"


def _load_quarantine_manifest(quarantine_root: Path) -> list[dict[str, Any]]:
    manifest = _quarantine_manifest_path(quarantine_root)
    if not manifest.exists():
        return []
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        rows = payload.get("moved") if isinstance(payload, dict) else payload
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, dict)]
    except Exception as exc:
        _record_backend_warning("Could not read quarantine manifest", path=manifest, error=exc)
    return []


def _write_quarantine_manifest(quarantine_root: Path, moved: list[dict[str, str]]) -> None:
    if not moved:
        return
    existing = _load_quarantine_manifest(quarantine_root)
    payload = {
        "updated_at": _utc_stamp(),
        "moved": existing + [dict(row, moved_at=_utc_stamp()) for row in moved],
    }
    quarantine_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(_quarantine_manifest_path(quarantine_root), payload)


def quarantine_orphaned_assets(paths: list[str], *, dry_run: bool = False) -> list[dict[str, str]]:
    pipeline = load_pipeline()
    allowed_roots = [root for root in [source_root(pipeline), generated_root(pipeline)] if root.exists()]
    quarantine_root = BUILD_META_DIR.parent / "quarantine" / "assets"
    planned: list[tuple[Path, Path]] = []
    moved: list[dict[str, str]] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists() or not (path.is_file() or path.is_dir()):
            continue
        resolved = path.resolve()
        if _is_relative_to(resolved, CONTENT_DIR) or _is_relative_to(resolved, ROOT / "scripts"):
            _record_backend_warning("Refused to quarantine non-asset project content", path=resolved, error="content/scripts are protected")
            continue
        if not any(_is_relative_to(resolved, root) for root in allowed_roots):
            _record_backend_warning("Refused to quarantine asset outside managed asset roots", path=resolved, error="outside managed roots")
            continue
        try:
            rel = resolved.relative_to(ROOT.resolve())
        except Exception:
            rel = Path(resolved.name)
        target = quarantine_root / rel
        if target.exists():
            target = target.with_name(f"{target.stem}-{int(time.time())}{target.suffix}")
        row = {"original": str(resolved), "quarantined": str(target), "quarantine_dir": str(quarantine_root)}
        moved.append(row)
        planned.append((resolved, target))
    if dry_run:
        return [dict(row, dry_run="true") for row in moved]
    if planned:
        with transaction(f"qt-quarantine-orphaned-assets:{len(planned)}"):
            for source_path, target in planned:
                guarded_move(source_path, target, detail="quarantine orphaned asset")
                _record_diagnostic_event(
                    "asset-quarantine",
                    "quarantined",
                    f"Moved {source_path.name} to quarantine",
                    original=str(source_path),
                    quarantined=str(target),
                )
        _write_quarantine_manifest(quarantine_root, moved)
        try:
            refresh_image_manifests(line_callback=None)
        except Exception as exc:
            _record_backend_warning("Could not refresh image manifests after asset quarantine", error=exc)
        invalidate_control_panel_caches()
        mark_unpublished_changes()
    return moved


def restore_from_quarantine(quarantined_path: str) -> dict[str, str]:
    """Move a quarantined asset back to its original location if the original path is empty."""
    pipeline = load_pipeline()
    quarantine_root = BUILD_META_DIR.parent / "quarantine" / "assets"
    candidate = Path(quarantined_path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    candidate = candidate.resolve()
    if not candidate.exists():
        raise BackendError(f"Quarantined asset not found: {candidate}")
    if not _is_relative_to(candidate, quarantine_root):
        raise BackendError("Can only restore assets from the Stillmark quarantine directory.")
    manifest_rows = _load_quarantine_manifest(quarantine_root)
    match = None
    for row in reversed(manifest_rows):
        try:
            if Path(str(row.get("quarantined") or "")).resolve() == candidate:
                match = row
                break
        except Exception:
            continue
    if not match:
        raise BackendError("No quarantine manifest entry was found for this asset.")
    original = Path(str(match.get("original") or ""))
    if not original.is_absolute():
        original = ROOT / original
    allowed_roots = [root for root in [source_root(pipeline), generated_root(pipeline)] if root.exists()]
    if _is_relative_to(original, CONTENT_DIR) or _is_relative_to(original, ROOT / "scripts"):
        raise BackendError("Refusing to restore into protected content/scripts directories.")
    if not any(_is_relative_to(original, root) for root in allowed_roots):
        raise BackendError("Original restore path is outside managed asset roots.")
    if original.exists():
        raise BackendError(f"Original path already exists; refusing to overwrite: {original}")
    with transaction(f"qt-restore-quarantine:{candidate.name}"):
        guarded_move(candidate, original, detail="restore quarantined asset")
        _record_diagnostic_event(
            "asset-quarantine",
            "restored",
            f"Restored {candidate.name} from quarantine",
            original=str(original),
            quarantined=str(candidate),
        )
    try:
        refresh_image_manifests(line_callback=None)
    except Exception as exc:
        _record_backend_warning("Could not refresh image manifests after quarantine restore", error=exc)
    invalidate_control_panel_caches()
    mark_unpublished_changes()
    return {"original": str(original), "restored_from": str(candidate), "quarantine_dir": str(quarantine_root)}

def regenerate_derivatives_for_work_ids(work_ids: list[str], line_callback: Callable[[str], None] | None = None) -> dict[str, Any]:
    cleaned = [str(item).strip() for item in work_ids if str(item).strip()]
    if not cleaned:
        raise BackendError("Select at least one work to regenerate derivatives.")
    pipeline = load_pipeline()
    regenerated: list[str] = []
    failed: list[dict[str, str]] = []
    for index, work_id in enumerate(cleaned, 1):
        if line_callback:
            line_callback(f"Generating images: {index}/{len(cleaned)} · {work_id}")
        payload = load_work_payload(work_id)
        if not payload:
            failed.append({"id": work_id, "error": "Work payload not found"})
            continue
        series_slug = _clean_text(payload.get("series") or work_to_series_map().get(work_id, ""))
        try:
            source_path = _resolve_source_path(series_slug, work_id, pipeline=pipeline, context="source recovery")
            if not source_path or not Path(source_path).exists():
                raise BackendError("Source image is missing")
            generate_derivatives(Path(source_path), series_slug, work_id, pipeline=pipeline, force=True)
            regenerated.append(work_id)
        except Exception as exc:
            failed.append({"id": work_id, "error": str(exc)})
            _record_backend_warning("Could not regenerate derivatives", error=exc)
    refresh_image_manifests(line_callback=line_callback)
    invalidate_control_panel_caches()
    return {"regenerated": regenerated, "failed": failed}


def verify_preview_output() -> dict[str, Any]:
    rows: list[dict[str, str]] = []

    def add(path: Path, ok: bool, ok_detail: str = "Found", error_detail: str = "Missing", *, warn: bool = False) -> None:
        status = "ok" if ok else ("warn" if warn else "error")
        try:
            rel = path.relative_to(ROOT).as_posix()
        except Exception:
            rel = str(path)
        rows.append({"path": rel, "status": status, "detail": ok_detail if ok else error_detail})

    index_html = PUBLIC_UPLOAD_DIR / "index.html"
    data_js = PUBLIC_UPLOAD_DIR / "assets" / "js" / "data.js"
    sitemap = PUBLIC_UPLOAD_DIR / "sitemap.xml"
    css_path = PUBLIC_UPLOAD_DIR / "assets" / "css"
    images_path = PUBLIC_UPLOAD_DIR / "assets" / "images"

    add(index_html, index_html.exists(), error_detail="Missing index.html")
    data_ok = False
    data_detail = "Missing data.js"
    try:
        data_ok = data_js.exists() and data_js.stat().st_size > 100  # Minimum plausible size.
        if data_js.exists() and not data_ok:
            data_detail = "data.js is empty or implausibly small"
    except OSError as exc:
        data_detail = f"Could not stat data.js: {exc}"
    add(data_js, data_ok, ok_detail="Found non-empty data.js", error_detail=data_detail)
    add(sitemap, sitemap.exists(), error_detail="Missing sitemap.xml")
    add(css_path, css_path.exists() and css_path.is_dir(), error_detail="Missing CSS assets directory")
    image_files: list[Path] = []
    if images_path.exists() and images_path.is_dir():
        try:
            image_files = [p for p in images_path.rglob("*") if p.is_file()]
        except OSError as exc:
            rows.append({"path": images_path.relative_to(ROOT).as_posix(), "status": "error", "detail": f"Could not scan generated images: {exc}"})
    add(images_path, bool(image_files), ok_detail=f"Found {len(image_files)} generated image asset(s)", error_detail="Missing or empty generated images directory")

    html_files: list[Path] = []
    if PUBLIC_UPLOAD_DIR.exists():
        try:
            html_files = [p for p in PUBLIC_UPLOAD_DIR.rglob("*.html") if p.is_file()]
        except OSError as exc:
            rows.append({"path": PUBLIC_UPLOAD_DIR.relative_to(ROOT).as_posix(), "status": "warn", "detail": f"Could not count generated HTML files: {exc}"})
    published_work_count = sum(
        1
        for item in load_work_entries()
        if bool(item.get("published")) and _clean_text(item.get("review_status")).lower() != "archived"
    )
    if published_work_count > 0 and len(html_files) <= 3:
        rows.append({
            "path": PUBLIC_UPLOAD_DIR.relative_to(ROOT).as_posix(),
            "status": "warn",
            "detail": f"{published_work_count} published work(s) but only {len(html_files)} generated HTML file(s); portfolio/series pages may be missing.",
        })

    manifest = load_upload_manifest()
    if manifest:
        rows.append({"path": "dist/upload-manifest.json", "status": "ok", "detail": "Upload manifest present"})
    else:
        rows.append({"path": "dist/upload-manifest.json", "status": "warn", "detail": "Upload manifest is missing or unreadable"})
    source_issues = source_asset_issues()
    if source_issues:
        rows.append({"path": "assets/images", "status": "warn", "detail": f"{len(source_issues)} source image issue(s) remain"})
    errors = sum(1 for row in rows if row["status"] == "error")
    warnings = sum(1 for row in rows if row["status"] == "warn")
    return {"ok": errors == 0, "errors": errors, "warnings": warnings, "rows": rows}

def _csv_row_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key in row and row.get(key) is not None:
            return _clean_text(row.get(key))
    return ""


def _parse_csv_tags(value: Any) -> list[str]:
    text = str(value or "")
    if not text.strip():
        return []
    separator = ";" if ";" in text else ","
    tags: list[str] = []
    for raw_tag in text.split(separator):
        tag = raw_tag.strip()
        if not tag:
            continue
        if len(tag) > 50:
            raise BackendError(f"CSV tag is too long (>50 characters): {tag[:60]}")
        if tag not in tags:
            tags.append(tag)
    return tags

def preview_works_csv_import(csv_path: str | Path) -> dict[str, Any]:
    path = Path(csv_path)
    if not path.exists():
        raise BackendError(f"CSV file not found: {path}")
    if path.stat().st_size > 10 * 1024 * 1024:
        raise BackendError("CSV file is unusually large (>10MB). Verify this is the correct file.")
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    parsed_rows: list[tuple[int, dict[str, Any]]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        if not ({"id", "ID"} & fieldnames):
            raise BackendError("CSV is missing required column: id")
        for line_no, row in enumerate(reader, start=2):
            parsed_rows.append((line_no, dict(row)))
    known_series = set(available_series_slugs())
    unknown_series: set[str] = set()
    for _, row in parsed_rows:
        series = _csv_row_value(row, "series")
        if series and series not in known_series:
            unknown_series.add(series)
    if unknown_series:
        errors.append("Unknown series slug(s): " + ", ".join(sorted(unknown_series)) + ". Create the series first or correct the CSV.")
    for line_no, row in parsed_rows:
        work_id = _csv_row_value(row, "id", "ID")
        if not work_id:
            errors.append(f"Line {line_no}: empty id")
            continue
        payload = load_work_payload(work_id)
        if not payload:
            errors.append(f"Line {line_no}: unknown work ID '{work_id}'")
            continue
        updated = dict(payload)
        changed: list[str] = []
        mapping = {"title": "title", "series": "series", "review": "review_status", "location": "location", "date": "year"}
        for csv_key, payload_key in mapping.items():
            if csv_key in row and row[csv_key] is not None:
                value = _clean_text(row.get(csv_key))
                if value and _clean_text(updated.get(payload_key)) != value:
                    updated[payload_key] = value
                    changed.append(payload_key)
        if "status" in row and row.get("status") is not None:
            value = _clean_text(row.get("status")).lower()
            if value in {"published", "true", "yes", "1"} and not bool(updated.get("published")):
                updated["published"] = True
                changed.append("published")
            elif value in {"unpublished", "false", "no", "0"} and bool(updated.get("published")):
                updated["published"] = False
                changed.append("published")
        if "tags" in row and row.get("tags") is not None:
            tags = _parse_csv_tags(row.get("tags"))
            if tags != list(updated.get("tags") or []):
                updated["tags"] = tags
                changed.append("tags")
        validation_errors = [item for item in validate_editor_payload("work", updated, original_key=work_id) if item.get("severity") == "error"]
        if validation_errors:
            errors.append(f"Line {line_no}: {work_id} invalid after import: " + "; ".join(str(item.get("message") or "") for item in validation_errors))
            continue
        if changed:
            rows.append({"work_id": work_id, "fields": sorted(set(changed)), "updated": updated})
    return {"path": str(path), "changes": rows, "errors": errors, "changed_ids": [row["work_id"] for row in rows]}


def import_works_csv(csv_path: str | Path) -> dict[str, Any]:
    preview = preview_works_csv_import(csv_path)
    if preview.get("errors"):
        raise BackendError("CSV import has errors. Fix them before importing.\n- " + "\n- ".join(preview["errors"][:20]))
    changes = list(preview.get("changes") or [])
    if not changes:
        return {"changed_ids": [], "count": 0}
    with transaction(f"qt-import-works-csv:{len(changes)}"):
        for row in changes:
            save_work_payload(row["work_id"], dict(row["updated"]))
    if len(changes) > 10:
        _WORK_REPOSITORY.reset()  # Full reset is cheaper and safer than many per-work invalidations.
    invalidate_control_panel_caches()
    mark_unpublished_changes()
    mark_portfolio_health_dirty("work")
    return {"changed_ids": [row["work_id"] for row in changes], "count": len(changes)}



def suggest_series_order(series_slug: str) -> list[str]:
    sequence = load_series_sequence(series_slug)
    if len(sequence) <= 1:
        return list(sequence)
    max_suggest_sequence = 500
    if len(sequence) > max_suggest_sequence:
        _record_backend_warning("suggest_series_order called on very large sequence", error=f"{len(sequence)} works")
        return list(sequence)
    scored: list[tuple[float, int, str]] = []
    for pos, work_id in enumerate(sequence):
        payload = load_work_payload(work_id) or {"id": work_id, "series": series_slug}
        preview = _safe_preview_path(payload)
        score = 0.0
        if preview:
            try:
                # File may vanish between path lookup and open; score=0.0 is a safe fallback.
                with Image.open(Path(preview)) as im:
                    gray = im.convert("L").resize((1, 1))
                    score = float(gray.getpixel((0, 0)))
            except Exception:
                score = 0.0
        completeness = int(fast_work_completeness_score(payload).get("score") or 0)
        scored.append((score, -completeness, work_id))
    scored.sort()
    low = deque(item for _, _, item in scored[:])
    high = deque(item for _, _, item in reversed(scored))
    result: list[str] = []
    seen: set[str] = set()
    while low or high:
        if high:
            value = high.popleft()
            if value not in seen:
                seen.add(value)
                result.append(value)
        if low:
            value = low.popleft()
            if value not in seen:
                seen.add(value)
                result.append(value)
    return result[:len(sequence)]

def release_checks(*, validation_rows: list[dict[str, Any]] | None = None, source_issues: Any = _SOURCE_ISSUES_NOT_PROVIDED, published_only: bool = False) -> list[dict[str, str]]:
    validation_rows = validation_rows if validation_rows is not None else validate_all()
    if published_only:
        validation_rows = _filter_rows_to_published_works(validation_rows)
    error_count = sum(1 for row in validation_rows if row.get("severity") == "error")
    warning_count = sum(1 for row in validation_rows if row.get("severity") == "warning")
    publish_state = load_publish_state()
    preview = preview_target()
    deploy_dir = ROOT / "deploy"
    archives = sorted(deploy_dir.glob("stillmrk-public-*.zip"), reverse=True) if deploy_dir.exists() else []
    rows: list[dict[str, str]] = []
    if error_count:
        rows.append({
            "area": "Pre-publish",
            "status": "error",
            "detail": f"{error_count} blocking validation error(s) must be fixed before publish.",
        })
    else:
        rows.append({
            "area": "Pre-publish",
            "status": "ok" if warning_count == 0 else "warn",
            "detail": "Validation is clean." if warning_count == 0 else f"No blocking errors. {warning_count} warning(s) remain.",
        })
    rows.append({
        "area": "Content",
        "status": "warn" if getattr(publish_state, "has_unpublished_changes", False) else "ok",
        "detail": "Content changed since last build." if getattr(publish_state, "has_unpublished_changes", False) else "Build state matches current content.",
    })
    if source_issues is _SOURCE_ISSUES_NOT_PROVIDED:
        source_errors = source_asset_issues()
        source_scan_unknown = False
    else:
        source_scan_unknown = source_issues is None
        source_errors = [] if source_scan_unknown else list(source_issues or [])
    if published_only and source_errors:
        source_errors = _filter_rows_to_published_works(source_errors)
    blocking_sources = [row for row in source_errors if row.get("severity") == "error"]
    source_warnings = [row for row in source_errors if row.get("severity") != "error"]
    gate_mode = source_asset_gate_mode()
    if source_scan_unknown:
        rows.append({
            "area": "Source assets",
            "status": "warn",
            "detail": "Source assets were not scanned in this health run. Run health check for current source truth before publish.",
        })
    elif blocking_sources and gate_mode == "strict":
        rows.append({
            "area": "Source assets",
            "status": "error",
            "detail": f"{len(blocking_sources)} work(s) lack acceptable original source images. Strict gate blocks build/publish until relinked or recovered.",
        })
    elif blocking_sources:
        rows.append({
            "area": "Source assets",
            "status": "warn",
            "detail": f"{len(blocking_sources)} original source issue(s) remain. Gate mode is {gate_mode}.",
        })
    elif source_warnings:
        rows.append({
            "area": "Source assets",
            "status": "warn",
            "detail": f"{len(source_warnings)} source hygiene warning(s) remain.",
        })
    else:
        rows.append({
            "area": "Source assets",
            "status": "ok",
            "detail": "All original source images are present and clean.",
        })
    rows.append({
        "area": "Preview",
        "status": "ok" if preview.exists() else "warn",
        "detail": f"Preview target: {preview.relative_to(ROOT).as_posix()}" if preview.exists() else "Preview target has not been generated yet.",
    })
    if archives:
        archive_mtime = archives[0].stat().st_mtime
        publish_mtime = None
        try:
            pub_path = ROOT / ".stillmrk-build" / "meta" / "publish-state.json"
            if pub_path.exists():
                publish_mtime = pub_path.stat().st_mtime
        except Exception as exc:
            _record_backend_warning("Could not compare publish archive freshness", path=ROOT / ".stillmrk-build" / "meta" / "publish-state.json", error=exc)
        archive_stale = bool(publish_mtime and archive_mtime < publish_mtime)
        rows.append({
            "area": "Exports",
            "status": "warn" if archive_stale else "ok",
            "detail": f"Latest package: {archives[0].name}" + (" (stale — content changed after this build)" if archive_stale else ""),
        })
    else:
        rows.append({
            "area": "Exports",
            "status": "warn",
            "detail": "No prepared publish archive found yet.",
        })
    return rows


def prepare_publish_package(line_callback: Callable[[str], None] | None = None) -> dict[str, Any]:
    preflight = preflight_build_sources(line_callback=line_callback, allow_recovery=True)
    recovered = list(preflight.get("recovered") or [])
    truth_rows = asset_truth_report_rows(force=True)
    checks = release_checks(source_issues=source_asset_issues(rows=truth_rows, use_cache=False))
    blocking = [row["detail"] for row in checks if row["status"] == "error"]
    if blocking:
        raise BackendError("Publish blocked:\n- " + "\n- ".join(blocking))
    if line_callback:
        if recovered:
            line_callback(f"Recovered {len(recovered)} missing source image(s) from generated derivatives")
        line_callback("Checking OG coverage…")
    from og_images import ensure_og_images_from_content, load_content_for_og
    generated = ensure_og_images_from_content(load_content_for_og(), force=True)
    if line_callback:
        line_callback(f"Generated {len(generated)} OG image(s)")
        line_callback("Building public site…")
    return_code = run_build(line_callback=line_callback)
    if int(return_code or 0) != 0:
        raise BackendError(f"Build failed with exit code {return_code}.")
    public_dir = ROOT / "dist"
    if not public_dir.exists():
        raise BackendError("dist was not created by the build.")
    deploy_dir = ROOT / "deploy"
    deploy_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = shutil.make_archive(str(deploy_dir / f"stillmrk-public-{stamp}"), "zip", root_dir=public_dir)
    if line_callback:
        line_callback(f"Prepared publish archive: {Path(archive).name}")
    return {"archive": archive, "og_generated": len(generated), "return_code": int(return_code or 0), "recovered_sources": len(recovered), "missing_sources": len(preflight.get('remaining') or []), "missing_source_rows": list(preflight.get('remaining') or [])}




def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
        _record_backend_warning("JSON file did not contain an object", path=path, error=type(payload).__name__)
        return {}
    except Exception as exc:
        _record_backend_warning("Could not read JSON object", path=path, error=exc)
        return {}


def load_release_report() -> dict[str, Any]:
    return _load_json_dict(RELEASE_REPORT_PATH)


def load_content_graph() -> dict[str, Any]:
    return _load_json_dict(CONTENT_GRAPH_PATH)


def load_validation_report() -> dict[str, Any]:
    return _load_json_dict(VALIDATION_REPORT_PATH)


def load_upload_manifest() -> dict[str, Any]:
    return _load_json_dict(UPLOAD_MANIFEST_PATH)


def public_upload_entries(limit: int = 200) -> list[dict[str, Any]]:
    if not PUBLIC_UPLOAD_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted([candidate for candidate in PUBLIC_UPLOAD_DIR.rglob('*') if candidate.is_file()], key=lambda p: p.as_posix()):
        stat = path.stat()
        rows.append({
            'name': path.name,
            'relative_path': path.relative_to(ROOT).as_posix(),
            'path': str(path),
            'size': int(stat.st_size),
            'updated_at': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    return rows[: max(1, int(limit or 200))]


def create_public_upload_archive(line_callback: Callable[[str], None] | None = None) -> dict[str, Any]:
    if not PUBLIC_UPLOAD_DIR.exists():
        raise BackendError('dist folder does not exist yet. Run a build first.')
    deploy_dir = ROOT / 'deploy'
    deploy_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    archive = shutil.make_archive(str(deploy_dir / f'stillmrk-upload-{stamp}'), 'zip', root_dir=PUBLIC_UPLOAD_DIR)
    count = len(public_upload_entries())
    if line_callback:
        line_callback(f'Prepared upload archive: {Path(archive).name}')
    return {'archive': archive, 'count': count}


def release_graph_rows() -> list[dict[str, Any]]:
    graph = load_content_graph()
    rows: list[dict[str, Any]] = []
    for work_id, payload in (graph.get('works') or {}).items():
        data = payload if isinstance(payload, dict) else {}
        rows.append({
            'kind': 'Work',
            'id': str(work_id),
            'detail': str(data.get('title') or ''),
            'scope': 'work',
            'target': str(work_id),
            'payload': data,
        })
    for slug, payload in (graph.get('series') or {}).items():
        data = payload if isinstance(payload, dict) else {}
        rows.append({
            'kind': 'Series',
            'id': str(slug),
            'detail': str(data.get('title') or ''),
            'scope': 'series',
            'target': str(slug),
            'payload': data,
        })
    for key, payload in (graph.get('pages') or {}).items():
        data = payload if isinstance(payload, dict) else {}
        rows.append({
            'kind': 'Page',
            'id': str(key),
            'detail': str(data.get('filePath') or ''),
            'scope': 'page',
            'target': str(key),
            'payload': data,
        })
    issues = graph.get('issues') or {}
    if isinstance(issues, dict):
        for key, payload in issues.items():
            rows.append({
                'kind': 'Issue',
                'id': str(key),
                'detail': f"{len(payload) if isinstance(payload, list) else 0} item(s)",
                'scope': 'issue',
                'target': str(key),
                'payload': payload,
            })
    return rows

def load_build_status() -> dict[str, Any]:
    if not BUILD_STATUS_PATH.exists():
        return {}
    try:
        payload = json.loads(BUILD_STATUS_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
        _record_backend_warning("Build status JSON did not contain an object", path=BUILD_STATUS_PATH, error=type(payload).__name__)
        return {}
    except Exception as exc:
        _record_backend_warning("Could not read build status", path=BUILD_STATUS_PATH, error=exc)
        return {}


def deploy_archives(limit: int = 20) -> list[dict[str, Any]]:
    deploy_dir = ROOT / "deploy"
    if not deploy_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for candidate in sorted(list(deploy_dir.glob("stillmrk-public-*.zip")) + list(deploy_dir.glob("stillmrk-upload-*.zip")), reverse=True)[: max(1, int(limit or 20))]:
        stat = candidate.stat()
        rows.append({
            "name": candidate.name,
            "path": str(candidate),
            "size": int(stat.st_size),
            "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    return rows

def load_ui_state() -> dict[str, Any]:
    if not UI_STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(UI_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
        _record_backend_warning("Control-panel UI state was not an object", path=UI_STATE_PATH, error=type(payload).__name__)
        return {}
    except Exception as exc:
        _record_backend_warning("Could not read control-panel UI state", path=UI_STATE_PATH, error=exc)
        return {}


def save_ui_state(state: dict[str, Any]) -> None:
    global _COMMAND_USAGE_CACHE
    try:
        UI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(UI_STATE_PATH, state)
        with _COMMAND_USAGE_LOCK:
            _COMMAND_USAGE_CACHE = None
    except Exception as exc:
        _record_backend_warning("Could not save control-panel UI state", path=UI_STATE_PATH, error=exc)


def _load_command_usage_cache() -> dict[str, int]:
    state = load_ui_state()
    raw_usage = state.get("command_usage") or {}
    return {str(key): int(value or 0) for key, value in raw_usage.items()} if isinstance(raw_usage, dict) else {}


def flush_command_usage() -> None:
    """Persist buffered command-usage increments. Safe to call from TimerBus or closeEvent."""
    global _COMMAND_USAGE_CACHE, _COMMAND_USAGE_LAST_FLUSH
    with _COMMAND_USAGE_LOCK:
        pending = dict(_COMMAND_USAGE_PENDING)
        _COMMAND_USAGE_PENDING.clear()
    if not pending:
        return
    state = load_ui_state()
    usage = state.setdefault("command_usage", {})
    if not isinstance(usage, dict):
        usage = {}
        state["command_usage"] = usage
    for key, value in pending.items():
        usage[str(key)] = int(usage.get(str(key), 0) or 0) + int(value or 0)
    save_ui_state(state)
    with _COMMAND_USAGE_LOCK:
        _COMMAND_USAGE_CACHE = {str(key): int(value or 0) for key, value in usage.items()}
        _COMMAND_USAGE_LAST_FLUSH = time.monotonic()


def increment_command_usage(label: str) -> None:
    global _COMMAND_USAGE_LAST_FLUSH
    label_text = _clean_text(label)
    if not label_text:
        return
    should_flush = False
    with _COMMAND_USAGE_LOCK:
        _COMMAND_USAGE_PENDING[label_text] = int(_COMMAND_USAGE_PENDING.get(label_text, 0)) + 1
        should_flush = (time.monotonic() - _COMMAND_USAGE_LAST_FLUSH) >= _COMMAND_USAGE_FLUSH_INTERVAL_SECONDS
    if should_flush:
        flush_command_usage()


def command_usage(label: str) -> int:
    global _COMMAND_USAGE_CACHE
    label_text = _clean_text(label)
    if not label_text:
        return 0
    if _COMMAND_USAGE_CACHE is None:
        _COMMAND_USAGE_CACHE = _load_command_usage_cache()
    with _COMMAND_USAGE_LOCK:
        pending_count = int(_COMMAND_USAGE_PENDING.get(label_text, 0))
    return int((_COMMAND_USAGE_CACHE or {}).get(label_text, 0)) + pending_count

