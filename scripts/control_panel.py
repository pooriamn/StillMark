from __future__ import annotations

import json
import hashlib
import html
from collections import OrderedDict, deque
from datetime import datetime
import sys
import re

# Phase 20: allow `python scripts/control_panel.py --doctor` to run before importing PySide6/PyYAML.
# This keeps dependency/path diagnostics usable even when a GUI/runtime dependency is missing.
if "--doctor" in sys.argv:
    from control_panel_doctor import main as _control_panel_doctor_main
    _doctor_args = [arg for arg in sys.argv[1:] if arg != "--doctor"]
    raise SystemExit(_control_panel_doctor_main(_doctor_args))

import yaml
import subprocess
import traceback
import time
import shlex
from difflib import unified_diff
import webbrowser
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Any, Callable

try:
    from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, Signal, QSize, QTimer, QPropertyAnimation, QEasingCurve
    from PySide6.QtGui import QAction, QCloseEvent, QColor, QFont, QIcon, QImage, QKeySequence, QShortcut, QPainter, QPen, QPixmap, QTextCharFormat, QTextCursor
    from PySide6.QtWidgets import (
        QApplication,
        QBoxLayout,
        QCheckBox,
        QComboBox,
        QDialog,
        QAbstractItemView,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGroupBox,
        QGraphicsOpacityEffect,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QSizePolicy,
        QSplitter,
        QStatusBar,
        QStackedWidget,
        QTabWidget,
        QTextEdit,
        QToolBar,
        QTreeWidget,
        QTreeWidgetItem,
        QTableView,
        QVBoxLayout,
        QWidget,
        QInputDialog,
    )
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "PySide6 is required for the Qt control panel. Install it with: pip install PySide6"
    ) from exc

try:  # PySide6 object-lifetime guard used by async thumbnail delivery.
    from shiboken6 import isValid as _qt_is_valid
except Exception:  # pragma: no cover - binding compatibility fallback
    _qt_is_valid = None

try:  # Optional PyQt/sip compatibility for older local environments.
    import sip as _qt_sip  # type: ignore
except Exception:  # pragma: no cover - PySide6 normally has no sip module
    _qt_sip = None


class _HiddenTabBar:
    """Compatibility shim for legacy callers after replacing the shell tabs with QStackedWidget."""

    def hide(self) -> None:
        return None


class NavStackedWidget(QStackedWidget):
    """QStackedWidget with the small QTabWidget API surface the legacy shell uses.

    Phase 16 removes the visible top-level tab bar without forcing a risky
    one-pass rewrite of every navigation call. Inner mode tabs that represent
    genuine editor modes can remain QTabWidget instances.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels: list[str] = []
        self._tooltips: list[str] = []
        self._hidden_tab_bar = _HiddenTabBar()

    def addTab(self, widget: QWidget, label: str) -> int:
        index = self.addWidget(widget)
        self._labels.insert(index, str(label or ""))
        self._tooltips.insert(index, "")
        return index

    def insertTab(self, index: int, widget: QWidget, label: str) -> int:
        index = max(0, min(int(index), self.count()))
        self.insertWidget(index, widget)
        self._labels.insert(index, str(label or ""))
        self._tooltips.insert(index, "")
        return index

    def removeTab(self, index: int) -> None:
        widget = self.widget(index)
        if widget is not None:
            self.removeWidget(widget)
        if 0 <= index < len(self._labels):
            self._labels.pop(index)
        if 0 <= index < len(self._tooltips):
            self._tooltips.pop(index)

    def tabText(self, index: int) -> str:
        return self._labels[index] if 0 <= index < len(self._labels) else ""

    def setTabText(self, index: int, label: str) -> None:
        if 0 <= index < len(self._labels):
            self._labels[index] = str(label or "")

    def tabToolTip(self, index: int) -> str:
        return self._tooltips[index] if 0 <= index < len(self._tooltips) else ""

    def setTabToolTip(self, index: int, tooltip: str) -> None:
        if 0 <= index < len(self._tooltips):
            self._tooltips[index] = str(tooltip or "")

    def tabBar(self) -> _HiddenTabBar:
        return self._hidden_tab_bar


from qt_backend import (
    AUTHORITY_FILES,
    PUBLISH_STATES,
    ROOT,
    BackendError,
    add_image,
    analyze_workbook_bundle,
    available_page_keys,
    available_series_slugs,
    command_usage,
    create_series,
    dashboard_summary,
    dashboard_fast_readiness,
    default_work_filter_presets,
    delete_series_record,
    duplicate_work,
    batch_update_works,
    best_preview_path_for_work,
    fast_preview_path_for_work,
    source_asset_truth_for_work,
    cached_asset_truth_for_work,
    bulk_relink_missing_sources,
    clear_editor_draft,
    list_editor_drafts,
    deploy_archives,
    load_build_status,
    load_release_report,
    load_content_graph,
    load_validation_report,
    load_upload_manifest,
    public_upload_entries,
    create_public_upload_archive,
    release_graph_rows,
    load_editor_draft,
    recover_missing_source_images,
    relink_source_image,
    save_editor_draft,
    source_asset_issues,
    source_asset_report_rows,
    increment_command_usage,
    flush_command_usage,
    export_workbook_bundle,
    available_document_ids,
    load_page_builder_bundle,
    review_page_builder_model,
    review_page_yaml_text,
    review_authority_yaml_text,
    save_page_builder_model,
    import_workbook_bundle,
    preview_workbook_import,
    restore_last_valid_page_yaml,
    restore_last_valid_authority_yaml,
    load_authority_yaml_text,
    load_page_yaml_text,
    load_relationships,
    load_series_entries,
    load_series_payload,
    load_series_sequence,
    remove_missing_work_references_from_series,
    load_ui_state,
    pop_backend_warnings,
    validate_editor_payload,
    load_work_entries,
    load_work_payload,
    load_works_filtered,
    works_filter_series_values,
    preview_target,
    prepare_publish_package,
    refresh_image_manifests,
    release_checks,
    image_registry_summary,
    load_image_health_summary,
    export_works_csv,
    preview_works_csv_import,
    import_works_csv,
    find_orphaned_assets,
    quarantine_orphaned_assets,
    regenerate_derivatives_for_work_ids,
    verify_preview_output,
    suggest_series_order,
    repair_items,
    recent_operation_rows,
    replace_work_image,
    run_build_with_preflight,
    run_documents,
    load_resource_documents,
    save_resource_documents,
    restore_last_completed_transaction,
    save_authority_yaml_text,
    save_page_yaml_text,
    save_relationships,
    save_series_from_payload,
    save_ui_state,
    save_work_from_payload,
    validate_all,
    work_issue_list,
    draft_conflict_status,
    editor_source_fingerprint,
    preview_work_change_map,
    preview_replace_work_image,
    reconcile_asset_presence_for_work,
    scan_stale_references,
    startup_preflight_checks,
    verify_work_transaction,
    image_duplicate_candidates,
    work_metadata_audit_rows,
    work_lineage_report,
    load_private_note,
    save_private_note,
    series_completeness_rows,
    series_rhythm_rows,
    preview_work_move,
    validation_action_rows,
    auto_fix_validation_issue,
    release_gate_summary,
    diff_public_output_snapshot,
    create_release_snapshot,
    list_release_snapshots,
    portfolio_readiness_score,
    portfolio_health_report,
    load_cached_portfolio_health_report,
    source_recovery_summary,
    missing_source_recovery_rows,
    load_inquiries,
    save_inquiry_record,
    delete_inquiry_record,
    load_print_editions,
    save_print_edition_record,
    delete_print_edition_record,
    control_panel_diagnostics,
    panel_accessibility_static_audit,
    save_panel_diagnostics_snapshot,
    preview_duplicate_work,
    update_work_quick_state,
    media_library_rows,
    tag_vocabulary_rows,
    merge_work_tag,
    series_story_rows,
    work_public_impact_report,
    safe_remove_work_preview,
    safe_remove_work,
    series_delete_preview,
    stale_asset_cleanup_report,
    export_control_panel_diagnostic_bundle,
)

from page_blocks import allowed_block_types, block_spec, default_section, friendly_block_name, next_section_id
from control_panel_design import CONTROL_PANEL_THEME, density_profile, status_accent
from control_panel_runtime import CONTROL_PANEL_NAV_GROUPS, performance_budget_status
from control_panel_timer import TimerBus
from control_panel_io import append_jsonl
from control_panel_performance_budgets import record_budget_event
from control_panel_layout_state import CONTROL_PANEL_STATE_SCHEMA_VERSION, MAX_SAVED_NOTIFICATIONS, StateSanityReport, normalise_control_panel_state, normalise_splitter_sizes
from control_panel_thread_safety import assert_gui_thread
from control_panel_tab_registry import tab_group, tab_purpose
from control_panel_components import AssetHealthBar, FormRow, PremiumCard, ReadinessGauge, SideNavDelegate, StatusBadge, TagInputWidget, ToastLabel, WorkGalleryCard, WorkListDelegate, WorkflowStepper, PanelDialog
from services.refresh_service import RefreshCoordinator, RefreshEvent
from control_panel_startup_guard import run_startup_guard
from control_panel_tasking import CancelledTask, TaskContext, run_staged_build, run_staged_publish_package
from control_panel_models import WorksTableModel, work_filter_summary as works_model_summary
from control_panel_media_cache import ThumbnailBatchToken, thumbnail_signature
from control_panel_tabs import DashboardTabBoundary, PagesTabController, PublishTabBoundary, SeriesTabController, WorksTabController, build_compatibility_specs

LAYOUT_CONTROL_VALUES = ["auto", "quiet", "standard", "medium", "large", "wide", "full"]
LAYOUT_CONTROL_DESCRIPTIONS = {
    "auto": "Keep the site-generated rhythm.",
    "quiet": "Smaller supporting image/card.",
    "standard": "Normal card/story beat.",
    "medium": "Gentle emphasis.",
    "large": "Strong feature without dominating the page.",
    "wide": "Cinematic horizontal emphasis.",
    "full": "Full-row pause / major story beat.",
}
LAYOUT_CONTROL_ALIASES = {
    "small": "quiet",
    "compact": "quiet",
    "normal": "standard",
    "default": "standard",
    "regular": "standard",
    "feature": "large",
    "featured": "large",
    "hero": "wide",
    "cinematic": "wide",
    "span": "wide",
}


def normalise_layout_control_value(value: Any, fallback: str = "auto") -> str:
    token = str(value or "").strip().lower().replace("_", "-")
    token = LAYOUT_CONTROL_ALIASES.get(token, token or fallback)
    return token if token in LAYOUT_CONTROL_VALUES else fallback


def ratio_text_is_valid(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return True
    if "/" not in value:
        return False
    left, right, *_rest = [part.strip() for part in value.split("/")]
    if not left or not right or _rest:
        return False
    try:
        return float(left) > 0 and float(right) > 0
    except Exception:
        return False


THEME_ALIASES = {
    "bg_window": "bg_primary",
    "text": "text_primary",
    "accent_green": "success",
}
THEME_LITERAL_TOKENS = {
    "font_family": "Inter, Segoe UI, Arial, sans-serif",
    "font_size": "13px",
    "radius_pill": "99px",
}


def resolved_control_panel_theme() -> dict[str, str]:
    resolved = dict(CONTROL_PANEL_THEME)
    for alias, source in THEME_ALIASES.items():
        if source not in CONTROL_PANEL_THEME or not str(CONTROL_PANEL_THEME.get(source) or "").strip():
            raise KeyError(f"Theme alias '{alias}' points to missing token '{source}'")
        resolved[alias] = CONTROL_PANEL_THEME[source]
    for key, value in THEME_LITERAL_TOKENS.items():
        resolved[key] = str(CONTROL_PANEL_THEME.get(key) or value)
    resolved["border_focus"] = str(CONTROL_PANEL_THEME.get("border_focus") or f"2px solid {resolved['accent']}")
    return resolved


THEME = resolved_control_panel_theme()
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
LAYOUT_POLISH_VERSION = "layout-rescue-20260425B"
FIXED_CONTROL_PANEL_DENSITY = "Comfortable"



class LRUIconCache:
    """Tiny ordered LRU cache for QIcon thumbnails; prevents unbounded QPixmap growth."""
    def __init__(self, max_entries: int = 80) -> None:
        self.max_entries = max(1, int(max_entries or 80))
        self._data: OrderedDict[str, QIcon] = OrderedDict()

    def get(self, key: str, default: Any = None) -> Any:
        key = str(key)
        if key not in self._data:
            return default
        value = self._data.pop(key)
        self._data[key] = value
        return value

    def put(self, key: str, value: QIcon) -> None:
        key = str(key)
        if key in self._data:
            self._data.pop(key)
        self._data[key] = value
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def pop(self, key: str, default: Any = None) -> Any:
        return self._data.pop(str(key), default)

    def clear(self) -> None:
        self._data.clear()

    def __contains__(self, key: object) -> bool:
        return str(key) in self._data

    def __setitem__(self, key: str, value: QIcon) -> None:
        self.put(key, value)

    def __len__(self) -> int:
        return len(self._data)

def _qt_object_alive(obj: QObject | None) -> bool:
    if obj is None:
        return False
    try:
        if _qt_sip is not None and hasattr(_qt_sip, "isdeleted"):
            return not bool(_qt_sip.isdeleted(obj))
    except Exception:
        return False
    try:
        if _qt_is_valid is not None:
            return bool(_qt_is_valid(obj))
    except Exception:
        return False
    return True


def _diagnostics_jsonl_path() -> Path:
    path = ROOT / ".stillmrk-build" / "meta" / "control-panel-diagnostics.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _append_control_panel_diagnostic_event(event: dict[str, Any]) -> None:
    try:
        payload = dict(event or {})
        payload.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
        append_jsonl(_diagnostics_jsonl_path(), payload)
    except Exception:
        # Diagnostics must never crash a user-facing task.
        return


def _exception_path(exc: BaseException) -> str:
    for attr in ("filename", "filename2", "path"):
        value = getattr(exc, attr, None)
        if value:
            return str(value)
    return str(exc)


def _structured_worker_error(kind: str, exc: BaseException) -> str:
    detail = traceback.format_exc()
    payload = {
        "kind": kind,
        "exception": exc.__class__.__name__,
        "summary": f"{kind.upper()} error ({exc.__class__.__name__}): {exc}",
        "path": _exception_path(exc),
        "detail": detail,
    }
    _append_control_panel_diagnostic_event({"event": "worker-error", **payload})
    return json.dumps(payload, ensure_ascii=False, default=str)


@contextmanager
def signals_blocked(widget: QObject):
    """Temporarily block Qt signals on a widget and its descendants, then restore state."""
    targets: list[QObject] = []
    if widget is not None:
        targets.append(widget)
        try:
            targets.extend(widget.findChildren(QObject))
        except Exception:
            pass
    previous: list[tuple[QObject, bool]] = []
    for target in targets:
        try:
            if _qt_object_alive(target):
                previous.append((target, target.blockSignals(True)))
        except RuntimeError:
            continue
    try:
        yield
    finally:
        for target, state in reversed(previous):
            try:
                if _qt_object_alive(target):
                    target.blockSignals(state)
            except RuntimeError:
                continue


class ThumbnailLoaderSignals(QObject):
    loaded = Signal(str, str, QImage)
    error = Signal(str, str)


class ThumbnailLoader(QRunnable):
    """Load one gallery thumbnail off the UI thread and return a scaled QImage.

    Phase 24 writes a small JPEG cache before the QImage is returned so revisits
    avoid repeatedly opening full-resolution source files.
    """

    def __init__(self, work_id: str, path: str, cache_key: str, size: QSize, disk_cache_path: str | None = None) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.work_id = str(work_id or "")
        self.path = str(path or "")
        self.cache_key = str(cache_key or "")
        self.size = QSize(size)
        self.disk_cache_path = str(disk_cache_path or "")
        self.signals = ThumbnailLoaderSignals()

    def run(self) -> None:  # pragma: no cover - worker orchestration
        try:
            cache_path = Path(self.disk_cache_path) if self.disk_cache_path else None
            if cache_path and cache_path.exists():
                image = QImage(str(cache_path))
            else:
                image = QImage()
            if image.isNull():
                # Prefer PIL in the worker for resizing; it avoids expensive
                # main-thread QPixmap scaling and is faster for large JPEGs.
                try:
                    from PIL import Image  # type: ignore
                    with Image.open(self.path) as source:
                        source = source.convert("RGB")
                        source.thumbnail((max(1, self.size.width()), max(1, self.size.height())))
                        if cache_path is not None:
                            cache_path.parent.mkdir(parents=True, exist_ok=True)
                            source.save(cache_path, "JPEG", quality=82, optimize=True)
                            image = QImage(str(cache_path))
                except Exception:
                    image = QImage(self.path)
            if image.isNull():
                raise OSError(f"Could not load thumbnail image: {self.path}")
            scaled = image.scaled(self.size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.signals.loaded.emit(self.work_id, self.cache_key, scaled)
        except Exception as exc:
            _append_control_panel_diagnostic_event({
                "event": "thumbnail-error",
                "kind": "thumbnail",
                "path": self.path,
                "summary": str(exc),
                "detail": traceback.format_exc(),
            })
            self.signals.error.emit(self.work_id, str(exc))


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    cancelled = Signal(str)
    finished = Signal()


class FunctionWorker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, task_context: TaskContext | None = None, **kwargs: Any) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.task_context = task_context
        self.signals = WorkerSignals()

    def _call(self) -> Any:
        if self.task_context is not None:
            self.task_context.check_cancelled()
            try:
                return self.fn(*self.args, task_context=self.task_context, **self.kwargs)
            except TypeError as exc:
                # Backward compatibility: most existing control-panel lambdas do not
                # accept task_context yet. Only retry for that specific argument.
                if "task_context" not in str(exc):
                    raise
        return self.fn(*self.args, **self.kwargs)

    def run(self) -> None:  # pragma: no cover - UI thread orchestration
        try:
            result = self._call()
            if self.task_context is not None:
                self.task_context.check_cancelled()
        except CancelledTask as exc:
            self.signals.cancelled.emit(str(exc))
        except BackendError as exc:
            self.signals.error.emit(_structured_worker_error("backend", exc))
        except OSError as exc:
            self.signals.error.emit(_structured_worker_error("os", exc))
        except yaml.YAMLError as exc:
            self.signals.error.emit(_structured_worker_error("yaml", exc))
        except Exception as exc:
            self.signals.error.emit(_structured_worker_error("unexpected", exc))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class ReorderListWidget(QListWidget):
    """QListWidget tuned for safe internal reordering.

    Qt's InternalMove mode handles the item move, while rowsMoved/dropEvent are
    coalesced into a single orderChanged signal so downstream save/autosave
    handlers do not fire twice on one drag.
    """
    orderChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._order_emit_pending = False
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)
        try:
            self.setSupportedDragActions(Qt.DropAction.MoveAction)
        except AttributeError:
            # Older Qt bindings do not expose setSupportedDragActions.
            pass
        self.model().rowsMoved.connect(lambda *_args: self._emit_order_changed_coalesced())

    def _emit_order_changed_coalesced(self) -> None:
        if self._order_emit_pending:
            return
        self._order_emit_pending = True
        QTimer.singleShot(0, self._flush_order_changed)

    def _flush_order_changed(self) -> None:
        self._order_emit_pending = False
        self.orderChanged.emit()

    def dropEvent(self, event) -> None:  # pragma: no cover - UI interaction
        before = [self.item(index).text() for index in range(self.count())]
        super().dropEvent(event)
        after = [self.item(index).text() for index in range(self.count())]
        if before != after:
            self._emit_order_changed_coalesced()


class NotificationCenterDialog(QDialog):
    def __init__(self, parent: "ControlPanelWindow") -> None:
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle("Notification center")
        self.resize(760, 520)
        self.setModal(True)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        mark_read = QPushButton("Mark all read")
        mark_read.clicked.connect(self.mark_all_read)
        clear_all = QPushButton("Clear all")
        clear_all.clicked.connect(self.clear_all)
        open_target = QPushButton("Open selected target")
        open_target.clicked.connect(self.open_selected_target)
        self.error_only_check = QCheckBox("Errors only")
        self.error_only_check.setToolTip("Show only error/warning notifications — the control-panel error inbox.")
        self.error_only_check.toggled.connect(lambda _checked: self.refresh())
        toolbar.addWidget(mark_read)
        toolbar.addWidget(clear_all)
        toolbar.addWidget(open_target)
        toolbar.addWidget(self.error_only_check)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.listing = QListWidget()
        self.listing.itemSelectionChanged.connect(self.update_detail)
        self.listing.itemDoubleClicked.connect(lambda _item: self.open_selected_target())
        split.addWidget(self.listing)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        split.addWidget(self.detail)
        split.setSizes([320, 420])
        layout.addWidget(split, 1)
        self.refresh()

    def refresh(self) -> None:
        current = None
        item = self.listing.currentItem()
        if item is not None:
            current = item.data(Qt.ItemDataRole.UserRole)
        self.listing.clear()
        for row in self.window.notifications():
            if getattr(self, "error_only_check", None) is not None and self.error_only_check.isChecked() and str(row.get("level") or "").lower() not in {"error", "warning"}:
                continue
            prefix = "● " if not row.get("read") else ""
            title = f"{prefix}{row.get('timestamp','')[-8:]} · {row.get('level','info').upper()} · {row.get('title','')}"
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, row.get("id"))
            self.listing.addItem(item)
            if current and row.get("id") == current:
                self.listing.setCurrentItem(item)
        if self.listing.count() and self.listing.currentRow() < 0:
            self.listing.setCurrentRow(0)
        self.update_detail()

    def _selected_notification(self) -> dict[str, Any] | None:
        item = self.listing.currentItem()
        if item is None:
            return None
        notif_id = item.data(Qt.ItemDataRole.UserRole)
        for row in self.window.notifications():
            if row.get("id") == notif_id:
                return row
        return None

    def update_detail(self) -> None:
        row = self._selected_notification()
        if not row:
            self.detail.setPlainText("Select a notification to inspect its detail.")
            return
        self.window.mark_notification_read(row.get("id"))
        lines = [
            f"When: {row.get('timestamp') or '-'}",
            f"Level: {row.get('level') or '-'}",
            f"Title: {row.get('title') or '-'}",
            "",
            str(row.get("detail") or "No additional detail."),
        ]
        target_scope = row.get("target_scope")
        target_id = row.get("target_id")
        if target_scope and target_id:
            lines.extend(["", f"Target: {target_scope} · {target_id}"])
        self.detail.setPlainText("\n".join(lines))
        self.window.update_notification_badge()

    def mark_all_read(self) -> None:
        self.window.mark_all_notifications_read()
        self.refresh()

    def clear_all(self) -> None:
        self.window.clear_notifications()
        self.refresh()

    def open_selected_target(self) -> None:
        row = self._selected_notification()
        if not row:
            return
        self.window.open_notification_target(row)


class MetricCard(QFrame):
    def __init__(self, label: str, value: str = "0", on_click: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._on_click = on_click
        self.setObjectName("metricCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor if on_click else Qt.CursorShape.ArrowCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.label_label = QLabel(label)
        self.label_label.setObjectName("metricLabel")
        layout.addWidget(self.value_label)
        layout.addWidget(self.label_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def mousePressEvent(self, event) -> None:  # pragma: no cover - UI interaction
        if self._on_click and event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
            event.accept()
            return
        super().mousePressEvent(event)


class InlineStat(QFrame):
    """Compact dashboard stat: one line, one value, no card clutter."""
    def __init__(self, label: str, value: str = "—", on_click: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._on_click = on_click
        self.setObjectName("inlineStat")
        self.setCursor(Qt.CursorShape.PointingHandCursor if on_click else Qt.CursorShape.ArrowCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)
        self.label_label = QLabel(label)
        self.label_label.setObjectName("inlineStatLabel")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("inlineStatValue")
        layout.addWidget(self.label_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(str(value))

    def mousePressEvent(self, event) -> None:  # pragma: no cover - UI interaction
        if self._on_click and event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
            event.accept()
            return
        super().mousePressEvent(event)



class CollapsibleSection(QFrame):
    """Reusable disclosure panel for dense editors."""
    def __init__(self, title: str, subtitle: str = "", *, expanded: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("collapsibleSection")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("sectionToggle")
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(bool(expanded))
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._title = str(title or "Section")
        self._subtitle = str(subtitle or "")
        self.toggle_button.toggled.connect(self._sync_expanded)
        root.addWidget(self.toggle_button)
        self.body = QWidget()
        self.body.setObjectName("sectionBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(12, 10, 12, 12)
        self.body_layout.setSpacing(8)
        root.addWidget(self.body)
        self._sync_expanded(bool(expanded))

    def _sync_expanded(self, expanded: bool) -> None:
        arrow = "▾" if expanded else "▸"
        subtitle = f"  ·  {self._subtitle}" if self._subtitle else ""
        self.toggle_button.setText(f"{arrow}  {self._title}{subtitle}")
        self.body.setVisible(bool(expanded))

    def add_layout(self, layout: QVBoxLayout | QHBoxLayout | QFormLayout) -> None:
        self.body_layout.addLayout(layout)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.body_layout.addWidget(widget, stretch)

    def setTitle(self, title: str) -> None:
        self._title = str(title or self._title)
        self._sync_expanded(self.toggle_button.isChecked())

    def setExpanded(self, expanded: bool) -> None:
        self.toggle_button.setChecked(bool(expanded))

class FocalPointLabel(QLabel):
    def __init__(self, text: str = "No image") -> None:
        super().__init__(text)
        self._x_spin: QSpinBox | None = None
        self._y_spin: QSpinBox | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Focal point preview")

    def set_focal_controls(self, x_spin: QSpinBox, y_spin: QSpinBox) -> None:
        self._x_spin = x_spin
        self._y_spin = y_spin
        x_spin.valueChanged.connect(lambda _value=None: self.update())
        y_spin.valueChanged.connect(lambda _value=None: self.update())

    def _display_rect(self):
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return self.rect()
        label_w = max(1, self.width())
        label_h = max(1, self.height())
        pix_w = max(1, pix.width())
        pix_h = max(1, pix.height())
        scale = min(label_w / pix_w, label_h / pix_h)
        w = pix_w * scale
        h = pix_h * scale
        x = (label_w - w) / 2
        y = (label_h - h) / 2
        return x, y, w, h

    def paintEvent(self, event) -> None:  # pragma: no cover - UI rendering
        super().paintEvent(event)
        if self._x_spin is None or self._y_spin is None:
            return
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return
        x0, y0, w, h = self._display_rect()
        cx = x0 + (self._x_spin.value() / 100.0) * w
        cy = y0 + (self._y_spin.value() / 100.0) * h
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#ffcf74"), 2)
        painter.setPen(pen)
        painter.drawLine(int(cx - 16), int(cy), int(cx + 16), int(cy))
        painter.drawLine(int(cx), int(cy - 16), int(cx), int(cy + 16))
        painter.drawEllipse(int(cx - 8), int(cy - 8), 16, 16)
        painter.end()

    def mousePressEvent(self, event) -> None:  # pragma: no cover - UI interaction
        if self._x_spin is None or self._y_spin is None:
            return super().mousePressEvent(event)
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return super().mousePressEvent(event)
        x0, y0, w, h = self._display_rect()
        px = min(max(event.position().x(), x0), x0 + w)
        py = min(max(event.position().y(), y0), y0 + h)
        self._x_spin.setValue(int(round(((px - x0) / max(1, w)) * 100)))
        self._y_spin.setValue(int(round(((py - y0) / max(1, h)) * 100)))
        self.update()

class CommandPaletteDialog(QDialog):
    def __init__(self, parent: "ControlPanelWindow") -> None:
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle("Command palette")
        self.resize(680, 520)
        self.setModal(True)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a command, work title, series, or page…")
        self.listing = QListWidget()
        layout.addWidget(self.search)
        layout.addWidget(self.listing)
        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self._run_current_item)
        self.listing.itemActivated.connect(self._run_item)
        QShortcut(QKeySequence("Esc"), self).activated.connect(self.reject)
        QShortcut(QKeySequence("Down"), self.search).activated.connect(lambda: self.listing.setFocus())
        self.refresh()
        self.search.setFocus()

    def _fuzzy_score(self, query: str, text: str) -> int:
        """Return score > 0 when query characters appear in order in text."""
        q = str(query or "").lower().strip()
        t = str(text or "").lower()
        if not q:
            return 1
        qi = 0
        score = 0
        for ci, ch in enumerate(t):
            if qi < len(q) and ch == q[qi]:
                score += max(1, len(t) - ci)
                qi += 1
        return score if qi == len(q) else 0

    def _add_section_header(self, label: str) -> None:
        item = QListWidgetItem(label.upper())
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(QColor("#5a7a9a"))
        font = item.font()
        font.setPointSize(9)
        font.setWeight(QFont.Weight.Bold)
        item.setFont(font)
        self.listing.addItem(item)

    def _add_command_item(self, row: dict[str, str]) -> None:
        shortcut = str(row.get("shortcut") or "").strip()
        prefix = "› " if row.get("tier") == "advanced" else ""
        title = f"{prefix}{row['label']}    [{shortcut}]" if shortcut else f"{prefix}{row['label']}"
        item = QListWidgetItem(f"{title}\n{row['detail']}")
        if row.get("tier") == "advanced":
            item.setForeground(QColor("#94a8bf"))
        item.setData(Qt.ItemDataRole.UserRole, row["key"])
        self.listing.addItem(item)

    def refresh(self) -> None:
        raw_query = self.search.text().strip()
        advanced_mode = raw_query.startswith(">")
        query = raw_query[1:].strip().lower() if advanced_mode else raw_query.lower()
        commands = self.window.command_rows()
        by_key = {row["key"]: row for row in commands}
        self.listing.clear()
        if not raw_query:
            hint = QListWidgetItem("Type > to access advanced commands")
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            hint.setForeground(QColor("#6f86a0"))
            self.listing.addItem(hint)
        recent_keys = [key for key in getattr(self.window, "_recent_command_keys", []) if key in by_key and (advanced_mode or by_key[key].get("tier") == "daily")]
        if recent_keys and not raw_query:
            self._add_section_header("Recent")
            for key in recent_keys[:5]:
                self._add_command_item(by_key[key])
            self._add_section_header("Daily commands")
        scored: list[tuple[int, dict[str, str]]] = []
        for row in commands:
            tier = row.get("tier", "daily")
            haystack = f"{row.get('key','')} {row.get('label','')} {row.get('detail','')}"
            score = self._fuzzy_score(query, haystack) if query else 1
            if tier == "advanced" and not advanced_mode:
                if not query or score <= 0:
                    continue
                score = max(1, score // 3)
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda pair: (-int(pair[1].get("usage", "0") or 0), -pair[0], pair[1]["label"].lower()) if not query else (-pair[0], pair[1]["label"].lower()))
        for _score, row in scored:
            if not raw_query and row["key"] in recent_keys:
                continue
            self._add_command_item(row)
        for row_index in range(self.listing.count()):
            item = self.listing.item(row_index)
            if item.flags() & Qt.ItemFlag.ItemIsSelectable:
                self.listing.setCurrentRow(row_index)
                break

    def _run_current_item(self) -> None:
        item = self.listing.currentItem()
        if item is not None and (item.flags() & Qt.ItemFlag.ItemIsSelectable):
            self._run_item(item)

    def _run_item(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        self.window.run_command(key)
        self.accept()


class GlobalSearchDialog(QDialog):
    def __init__(self, parent: "ControlPanelWindow") -> None:
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle("Search content")
        self.resize(760, 560)
        self.setModal(True)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search works, series, pages, authority files…")
        self.listing = QTreeWidget()
        self.listing.setHeaderLabels(["Type", "Target", "Match"])
        layout.addWidget(self.search)
        layout.addWidget(self.listing, 1)
        self._search_generation = 0
        self._latest_applied_generation = 0
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._do_search)
        self.search.textChanged.connect(lambda _text=None: self._search_timer.start())
        self.listing.itemActivated.connect(self._run_item)
        self.refresh()
        self.search.setFocus()

    def refresh(self) -> None:
        self._search_timer.start()

    def _do_search(self) -> None:
        query = self.search.text().strip().lower()
        self._search_generation += 1
        generation = self._search_generation
        self.listing.clear()
        self.listing.addTopLevelItem(QTreeWidgetItem(["Info", "Searching…", ""]))
        def run_search(q: str = query, gen: int = generation) -> dict[str, Any]:
            rows = self.window.global_search_rows(q)
            return {"generation": gen, "query": q, "rows": rows, "total": int(getattr(self.window, "_last_global_search_total", len(rows)) or len(rows))}
        worker = FunctionWorker(run_search)
        self.window._active_workers.append(worker)
        worker.signals.result.connect(self._apply_rows)
        worker.signals.error.connect(lambda tb: self.window._log_warning(f"Global search failed: {tb}"))
        worker.signals.finished.connect(lambda w=worker: self.window._forget_worker(w))
        self.window.io_thread_pool.start(worker)

    def _apply_rows(self, payload: Any) -> None:
        if isinstance(payload, dict):
            generation = int(payload.get("generation") or 0)
            if generation and generation < self._search_generation:
                return
            self._latest_applied_generation = generation
            rows = list(payload.get("rows") or [])
            total = int(payload.get("total") or len(rows))
        else:
            rows = list(payload or [])
            total = int(getattr(self.window, "_last_global_search_total", len(rows)) or len(rows))
        self.listing.clear()
        for row in rows:
            item = QTreeWidgetItem([row["kind"], row["target"], row["detail"]])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            self.listing.addTopLevelItem(item)
        if total > len(rows):
            notice = QTreeWidgetItem(["Info", "Results truncated", f"Showing {len(rows)} of {total} results — refine your search."])
            notice.setFlags(notice.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled)
            muted = QColor("#8ea2bd")
            for col in range(3):
                notice.setForeground(col, muted)
            self.listing.addTopLevelItem(notice)
        if self.listing.topLevelItemCount():
            self.listing.setCurrentItem(self.listing.topLevelItem(0))

    def _run_item(self, item: QTreeWidgetItem) -> None:
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if not row:
            return
        self.window.open_search_result(row)
        self.accept()




class BulkEditDialog(QDialog):
    """Transaction-backed bulk metadata editor with dry-run preview."""
    def __init__(self, parent: "ControlPanelWindow", work_ids: list[str]) -> None:
        super().__init__(parent)
        self.window = parent
        self.work_ids = work_ids
        self.setWindowTitle(f"Bulk edit {len(work_ids)} work(s)")
        self.resize(720, 520)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Choose only the fields you want to change. A dry-run preview is generated before anything is written."))

        form = QFormLayout()
        self.publish_check = QCheckBox("Set published")
        self.publish_value = QComboBox(); self.publish_value.addItems(["Published", "Unpublished"])
        publish_row = QHBoxLayout(); publish_row.addWidget(self.publish_check); publish_row.addWidget(self.publish_value); publish_row.addStretch(1)
        publish_wrap = QWidget(); publish_wrap.setLayout(publish_row); form.addRow("Publish", publish_wrap)

        self.review_check = QCheckBox("Set review status")
        self.review_value = QComboBox(); self.review_value.addItems(PUBLISH_STATES)
        review_row = QHBoxLayout(); review_row.addWidget(self.review_check); review_row.addWidget(self.review_value); review_row.addStretch(1)
        review_wrap = QWidget(); review_wrap.setLayout(review_row); form.addRow("Review", review_wrap)

        self.series_check = QCheckBox("Move to series")
        self.series_value = QComboBox(); self.series_value.addItems(available_series_slugs())
        series_row = QHBoxLayout(); series_row.addWidget(self.series_check); series_row.addWidget(self.series_value); series_row.addStretch(1)
        series_wrap = QWidget(); series_wrap.setLayout(series_row); form.addRow("Series", series_wrap)

        self.tags_mode = QComboBox(); self.tags_mode.addItems(["Do not change tags", "Add tags", "Remove tags", "Replace tags"])
        self.tags_value = QLineEdit(); self.tags_value.setPlaceholderText("comma-separated tags")
        tags_row = QHBoxLayout(); tags_row.addWidget(self.tags_mode); tags_row.addWidget(self.tags_value, 1)
        tags_wrap = QWidget(); tags_wrap.setLayout(tags_row); form.addRow("Tags", tags_wrap)
        root.addLayout(form)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlainText("Affected works:\n" + "\n".join(work_ids[:80]))
        root.addWidget(self.preview, 1)

        buttons = QHBoxLayout()
        preview_btn = QPushButton("Preview changes")
        preview_btn.clicked.connect(self.preview_changes)
        buttons.addWidget(preview_btn)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText("Apply transaction")
        box.accepted.connect(self.apply)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        root.addLayout(buttons)

    def _kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.publish_check.isChecked():
            kwargs["published"] = self.publish_value.currentText() == "Published"
        if self.review_check.isChecked():
            kwargs["review_status"] = self.review_value.currentText()
        if self.series_check.isChecked():
            kwargs["series_slug"] = self.series_value.currentText()
        tag_mode = self.tags_mode.currentText()
        tags = [tag.strip() for tag in self.tags_value.text().split(",") if tag.strip()]
        if tag_mode == "Add tags":
            kwargs["tags_to_add"] = tags
        elif tag_mode == "Remove tags":
            kwargs["tags_to_remove"] = tags
        elif tag_mode == "Replace tags":
            kwargs["tags_to_set"] = tags
        return kwargs

    def preview_changes(self) -> dict[str, Any] | None:
        kwargs = self._kwargs()
        if not kwargs:
            QMessageBox.information(self, "Nothing selected", "Choose at least one field to update.")
            return None
        try:
            result = batch_update_works(self.work_ids, dry_run=True, **kwargs)
        except Exception as exc:
            QMessageBox.critical(self, "Bulk edit preview failed", str(exc))
            return None
        changes = list(result.get("changes") or [])
        lines = [
            f"Dry-run: {len(changes)} work(s) would change.",
            f"Skipped: {len(result.get('skipped_ids') or [])}",
            "",
        ]
        for row in changes[:120]:
            lines.append(f"- {row.get('work_id')}: {', '.join(row.get('fields') or [])}")
        if len(changes) > 120:
            lines.append(f"- … and {len(changes) - 120} more")
        self.preview.setPlainText("\n".join(lines))
        return result

    def apply(self) -> None:
        kwargs = self._kwargs()
        if not kwargs:
            QMessageBox.information(self, "Nothing selected", "Choose at least one field to update.")
            return
        preview = self.preview_changes()
        if preview is None:
            return
        changed = len(preview.get("changes") or [])
        if not changed:
            QMessageBox.information(self, "No changes", "The selected operation would not change any selected work.")
            return
        if QMessageBox.question(self, "Apply bulk edit", f"Apply selected changes to {changed} work(s) in one transaction?") != QMessageBox.StandardButton.Yes:
            return
        try:
            result = batch_update_works(self.work_ids, **kwargs)
        except Exception as exc:
            QMessageBox.critical(self, "Bulk edit failed", str(exc))
            return
        changed = len(result.get("changed_ids") or [])
        self.window.clear_work_icon_cache()
        self.window.push_notification("success", "Bulk metadata edit complete", f"Updated {changed} work(s).", target_scope="work")
        self.window.refresh_all_context(force=True, scope={"works", "dashboard", "validation", "studio"})
        self.accept()


class PrePublishChecklistDialog(QDialog):
    """Mandatory release gate used before packaging deployable output."""
    def __init__(self, parent: "ControlPanelWindow", rows: list[dict[str, Any]]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pre-publish checklist")
        self.resize(780, 560)
        self.rows = rows
        self.warning_checks: list[QCheckBox] = []
        root = QVBoxLayout(self)
        errors = [row for row in rows if str(row.get("status") or "").lower() == "error"]
        warnings = [row for row in rows if str(row.get("status") or "").lower() in {"warn", "warning"}]
        intro = QLabel(
            "Publishing is blocked while errors exist. Warnings must be acknowledged deliberately before an upload package is created."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)
        tree = QTreeWidget()
        tree.setHeaderLabels(["Status", "Area", "Detail"])
        tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for row in rows:
            status = str(row.get("status") or "")
            symbol = "✕" if status.lower() == "error" else "⚠" if status.lower() in {"warn", "warning"} else "✓"
            item = QTreeWidgetItem([symbol + " " + status, str(row.get("area") or ""), str(row.get("detail") or "")])
            color = parent._severity_color(status)
            for col in range(3):
                item.setForeground(col, color)
            tree.addTopLevelItem(item)
        root.addWidget(tree, 1)
        if warnings:
            root.addWidget(QLabel("Acknowledge warnings:"))
            for row in warnings:
                check = QCheckBox(f"{row.get('area')}: {row.get('detail')}")
                check.toggled.connect(self._update_buttons)
                self.warning_checks.append(check)
                root.addWidget(check)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Proceed")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        if errors:
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if button is None:
            return
        has_error = any(str(row.get("status") or "").lower() == "error" for row in self.rows)
        warnings_ok = all(check.isChecked() for check in self.warning_checks)
        button.setEnabled((not has_error) and warnings_ok)


class ReleaseAdminDialog(QDialog):
    def __init__(self, parent: "ControlPanelWindow") -> None:
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle("Release workspace")
        self.resize(1040, 720)
        self.setModal(True)
        root = QVBoxLayout(self)
        tools = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_all)
        open_target_btn = QPushButton("Open selected target")
        open_target_btn.clicked.connect(self.open_selected_graph_target)
        open_file_btn = QPushButton("Open selected file")
        open_file_btn.clicked.connect(self.open_selected_upload_file)
        open_folder_btn = QPushButton("Open public_upload folder")
        open_folder_btn.clicked.connect(self.open_public_upload_folder)
        make_zip_btn = QPushButton("Create upload zip")
        make_zip_btn.clicked.connect(self.create_upload_zip)
        for widget in (refresh_btn, open_target_btn, open_file_btn, open_folder_btn, make_zip_btn):
            tools.addWidget(widget)
        tools.addStretch(1)
        root.addLayout(tools)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # release report tab
        release_tab = QWidget()
        release_layout = QHBoxLayout(release_tab)
        self.release_tree = QTreeWidget()
        self.release_tree.setHeaderLabels(["Area", "Status", "Detail"])
        self.release_tree.itemSelectionChanged.connect(self.update_release_detail)
        self.release_detail = QPlainTextEdit(); self.release_detail.setReadOnly(True)
        release_layout.addWidget(self.release_tree, 3)
        release_layout.addWidget(self.release_detail, 2)
        self.tabs.addTab(release_tab, "Release report")

        # content graph tab
        graph_tab = QWidget()
        graph_layout = QHBoxLayout(graph_tab)
        left = QVBoxLayout()
        filter_row = QHBoxLayout()
        self.graph_filter = QComboBox()
        self.graph_filter.addItems(["All", "Work", "Series", "Page", "Issue"])
        self.graph_filter.currentTextChanged.connect(self.refresh_graph_rows)
        self.graph_search = QLineEdit()
        self.graph_search.setPlaceholderText("Filter content graph…")
        self.graph_search.textChanged.connect(self.refresh_graph_rows)
        filter_row.addWidget(self.graph_filter)
        filter_row.addWidget(self.graph_search, 1)
        left.addLayout(filter_row)
        self.graph_tree = QTreeWidget()
        self.graph_tree.setHeaderLabels(["Kind", "Target", "Detail"])
        self.graph_tree.itemSelectionChanged.connect(self.update_graph_detail)
        self.graph_tree.itemDoubleClicked.connect(lambda _item, _col: self.open_selected_graph_target())
        left.addWidget(self.graph_tree, 1)
        left_wrap = QWidget(); left_wrap.setLayout(left)
        self.graph_detail = QPlainTextEdit(); self.graph_detail.setReadOnly(True)
        graph_layout.addWidget(left_wrap, 3)
        graph_layout.addWidget(self.graph_detail, 2)
        self.tabs.addTab(graph_tab, "Content graph")

        # upload workspace tab
        upload_tab = QWidget()
        upload_layout = QVBoxLayout(upload_tab)
        self.upload_manifest_text = QPlainTextEdit(); self.upload_manifest_text.setReadOnly(True); self.upload_manifest_text.setFixedHeight(150)
        upload_layout.addWidget(self.upload_manifest_text)
        self.upload_tree = QTreeWidget()
        self.upload_tree.setHeaderLabels(["File", "Updated", "Size"])
        self.upload_tree.itemSelectionChanged.connect(self.update_upload_detail)
        self.upload_tree.itemDoubleClicked.connect(lambda _item, _col: self.open_selected_upload_file())
        upload_layout.addWidget(self.upload_tree, 1)
        self.upload_detail = QPlainTextEdit(); self.upload_detail.setReadOnly(True); self.upload_detail.setFixedHeight(120)
        upload_layout.addWidget(self.upload_detail)
        self.tabs.addTab(upload_tab, "Upload workspace")

        for tree, label in ((self.release_tree, "Loading release report…"), (self.graph_tree, "Loading content graph…"), (self.upload_tree, "Loading upload manifest…")):
            tree.addTopLevelItem(QTreeWidgetItem([label, "", ""]))
            tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        QTimer.singleShot(0, self.refresh_all)

    def refresh_all(self) -> None:
        self.refresh_release_rows()
        self.refresh_graph_rows()
        self.refresh_upload_rows()

    def refresh_release_rows(self) -> None:
        report = load_release_report()
        self.release_tree.clear()
        required = list(report.get('requiredChecks') or [])
        smoke = list(report.get('smokeChecks') or [])
        warnings = list(report.get('warnings') or [])
        missing = list(report.get('missingImages') or [])
        rows = [
            ('Ready', 'ok' if report.get('ready') else 'warn', f"Ready: {bool(report.get('ready'))}"),
            ('Environment', 'info', str(report.get('environment') or '-')),
            ('Missing images', 'warn' if missing else 'ok', f"{len(missing)} missing image(s)"),
            ('Warnings', 'warn' if warnings else 'ok', f"{len(warnings)} warning(s)"),
            ('Required checks', 'info', f"{len(required)} item(s)"),
            ('Smoke checks', 'info', f"{len(smoke)} item(s)"),
        ]
        for area, status, detail in rows:
            item = QTreeWidgetItem([area, status, detail])
            item.setData(0, Qt.ItemDataRole.UserRole, {'area': area, 'status': status, 'detail': detail, 'report': report})
            self.release_tree.addTopLevelItem(item)
        if self.release_tree.topLevelItemCount():
            self.release_tree.setCurrentItem(self.release_tree.topLevelItem(0))
        self.update_release_detail()

    def update_release_detail(self) -> None:
        item = self.release_tree.currentItem()
        if item is None:
            self.release_detail.setPlainText('Select a release report row to inspect it.')
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        report = row.get('report') or {}
        lines = [
            f"Area: {row.get('area') or '-'}",
            f"Status: {row.get('status') or '-'}",
            f"Detail: {row.get('detail') or '-'}",
            '',
            f"Generated: {report.get('generatedAt') or '-'}",
            f"Display URL: {report.get('stagingUrl') or report.get('productionUrl') or '-'}",
        ]
        if report.get('requiredChecks'):
            lines.extend(['', 'Required checks:'])
            lines.extend(f"- {item}" for item in report.get('requiredChecks') or [])
        if report.get('smokeChecks'):
            lines.extend(['', 'Smoke checks:'])
            lines.extend(f"- {item}" for item in report.get('smokeChecks') or [])
        if report.get('warnings'):
            lines.extend(['', 'Warnings:'])
            lines.extend(f"- {item}" for item in report.get('warnings') or [])
        self.release_detail.setPlainText("\n".join(lines))

    def refresh_graph_rows(self) -> None:
        kind_filter = self.graph_filter.currentText() if hasattr(self, 'graph_filter') else 'All'
        query = self.graph_search.text().strip().lower() if hasattr(self, 'graph_search') else ''
        self.graph_tree.clear()
        for row in release_graph_rows():
            if kind_filter != 'All' and row.get('kind') != kind_filter:
                continue
            hay = f"{row.get('kind','')} {row.get('id','')} {row.get('detail','')} {row.get('payload','')}".lower()
            if query and query not in hay:
                continue
            item = QTreeWidgetItem([str(row.get('kind') or ''), str(row.get('id') or ''), str(row.get('detail') or '')])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            self.graph_tree.addTopLevelItem(item)
        if self.graph_tree.topLevelItemCount():
            self.graph_tree.setCurrentItem(self.graph_tree.topLevelItem(0))
        self.update_graph_detail()

    def update_graph_detail(self) -> None:
        item = self.graph_tree.currentItem()
        if item is None:
            self.graph_detail.setPlainText('Select a content graph row to inspect the raw payload and jump to its editor.')
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        payload = row.get('payload')
        lines = [
            f"Kind: {row.get('kind') or '-'}",
            f"Target: {row.get('target') or row.get('id') or '-'}",
            f"Scope: {row.get('scope') or '-'}",
            f"Detail: {row.get('detail') or '-'}",
            '',
            json.dumps(payload, ensure_ascii=False, indent=2) if payload is not None else 'No payload',
        ]
        self.graph_detail.setPlainText("\n".join(lines))

    def open_selected_graph_target(self) -> None:
        item = self.graph_tree.currentItem()
        if item is None:
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        self.window.open_search_result(row)

    def refresh_upload_rows(self) -> None:
        manifest = load_upload_manifest()
        self.upload_manifest_text.setPlainText(json.dumps(manifest, ensure_ascii=False, indent=2) if manifest else 'Upload manifest not found yet. Run a build first.')
        self.upload_tree.clear()
        for row in public_upload_entries():
            size_bytes = int(row.get('size') or 0)
            size_label = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1024*1024 else f"{size_bytes / (1024*1024):.2f} MB"
            item = QTreeWidgetItem([str(row.get('relative_path') or ''), str(row.get('updated_at') or '').replace('T', ' ')[:19], size_label])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            self.upload_tree.addTopLevelItem(item)
        if self.upload_tree.topLevelItemCount():
            self.upload_tree.setCurrentItem(self.upload_tree.topLevelItem(0))
        self.update_upload_detail()

    def update_upload_detail(self) -> None:
        item = self.upload_tree.currentItem()
        if item is None:
            self.upload_detail.setPlainText('Select a public_upload file to inspect it.')
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        lines = [
            f"File: {row.get('relative_path') or '-'}",
            f"Updated: {row.get('updated_at') or '-'}",
            f"Size: {row.get('size') or 0} bytes",
            f"Path: {row.get('path') or '-'}",
        ]
        self.upload_detail.setPlainText("\n".join(lines))

    def open_selected_upload_file(self) -> None:
        item = self.upload_tree.currentItem()
        if item is None:
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        path = Path(str(row.get('path') or ''))
        if path.exists():
            webbrowser.open(path.resolve().as_uri())

    def open_public_upload_folder(self) -> None:
        path = ROOT / 'public_upload'
        path.mkdir(exist_ok=True)
        webbrowser.open(path.resolve().as_uri())

    def create_upload_zip(self) -> None:
        """Delegate upload archive creation to the main Publish controller.

        This keeps one pre-publish gate, one async task path, and one notification/log path.
        """
        if hasattr(self.window, "create_upload_zip"):
            self.window.create_upload_zip()
            QTimer.singleShot(1500, self.refresh_upload_rows)
            return
        QMessageBox.warning(self, 'Create upload zip unavailable', 'The main publish controller is not available.')



class WorkMetadataAuditDialog(PanelDialog):
    def __init__(self, parent: "ControlPanelWindow", work_ids: list[str] | None = None) -> None:
        self.window = parent
        self.work_ids = work_ids or []
        def _load() -> list[dict[str, Any]]:
            return work_metadata_audit_rows(self.work_ids or None)
        def _detail(row: dict[str, Any]) -> str:
            lines = [
                f"Work: {row.get('id') or '-'}",
                f"Title: {row.get('title') or '-'}",
                f"Series: {row.get('series') or '-'}",
                f"Readiness score: {row.get('score') or 0}",
                f"Status: {row.get('status') or '-'}",
                f"Missing / weak: {row.get('missing') or '-'}",
                f"Review status: {row.get('review_status') or '-'}",
                f"Published: {bool(row.get('published'))}",
                "",
                "Issues:",
            ]
            issues = list(row.get('issues') or [])
            lines.extend([f"- {issue}" for issue in issues] or ["- None"])
            return "\n".join(lines)
        def _open(dialog: PanelDialog, row: dict[str, Any]) -> None:
            work_id = str(row.get('id') or '')
            if work_id:
                parent._ensure_tab_built_by_key('works')
                parent.tabs.setCurrentWidget(parent.works_tab)
                parent.select_work(work_id)
                dialog.accept()
        def _copy(dialog: PanelDialog, _row: dict[str, Any]) -> None:
            lines = [f"{row.get('score')}\t{row.get('status')}\t{row.get('id')}\t{row.get('series')}\t{row.get('missing')}" for row in dialog.rows]
            QApplication.clipboard().setText("\n".join(lines))
            parent.status_message("Copied metadata audit report")
        def _color(row: dict[str, Any]) -> QColor:
            return parent._severity_color('error' if row.get('status') == 'blocked' else 'warning' if row.get('status') == 'review' else 'ok')
        super().__init__(
            parent,
            title="Work metadata audit",
            columns=[("Score", "score"), ("Status", "status"), ("Work", "id"), ("Series", "series"), ("Missing / weak", "missing"), ("Alt", "alt_words"), ("Caption", "caption_words")],
            load_fn=_load,
            detail_fn=_detail,
            actions=[("Open selected work", _open), ("Copy report", _copy)],
            size=(1120, 660),
            row_color_fn=_color,
        )


class DuplicateScanDialog(PanelDialog):
    def __init__(self, parent: "ControlPanelWindow") -> None:
        self.window = parent
        top = QWidget()
        row = QHBoxLayout(top)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Sensitivity"))
        self.threshold_spin = QSpinBox(); self.threshold_spin.setRange(0, 16); self.threshold_spin.setValue(6)
        row.addWidget(self.threshold_spin)
        row.addStretch(1)
        def _load() -> list[dict[str, Any]]:
            return image_duplicate_candidates(threshold=self.threshold_spin.value())
        def _detail(row: dict[str, Any]) -> str:
            return "\n".join([
                f"Left: {row.get('left_id')} · {row.get('left_title')}",
                f"Path: {row.get('left_path')}",
                f"Right: {row.get('right_id')} · {row.get('right_title')}",
                f"Path: {row.get('right_path')}",
                f"Distance: {row.get('distance')} · Confidence: {row.get('confidence')}",
            ])
        def _open_key(key: str):
            def _open(dialog: PanelDialog, row: dict[str, Any]) -> None:
                work_id = str(row.get(key) or '')
                if work_id:
                    parent._ensure_tab_built_by_key('works')
                    parent.tabs.setCurrentWidget(parent.works_tab)
                    parent.select_work(work_id)
                    dialog.accept()
            return _open
        def _color(row: dict[str, Any]) -> QColor:
            return parent._severity_color('error' if row.get('exact_file') else 'warning')
        super().__init__(
            parent,
            title="Duplicate / near-duplicate image scan",
            columns=[("Confidence", "confidence"), ("Distance", "distance"), ("Left work", "left_id"), ("Right work", "right_id"), ("Exact file", "exact_file")],
            load_fn=_load,
            detail_fn=_detail,
            actions=[("Open left work", _open_key('left_id')), ("Open right work", _open_key('right_id'))],
            size=(1120, 620),
            row_color_fn=_color,
            top_widget=top,
        )
        self.threshold_spin.valueChanged.connect(lambda _v=None: self.refresh())


class WorkLineageDialog(QDialog):
    def __init__(self, parent: "ControlPanelWindow", work_id: str) -> None:
        super().__init__(parent)
        self.window = parent
        self.work_id = work_id
        self.setWindowTitle(f"Image lineage · {work_id}")
        self.resize(1040, 650)
        root = QVBoxLayout(self)
        tools = QHBoxLayout()
        refresh = QPushButton("Refresh lineage")
        refresh.clicked.connect(self.refresh)
        copy_btn = QPushButton("Copy report")
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(self.detail.toPlainText()))
        tools.addWidget(refresh)
        tools.addWidget(copy_btn)
        tools.addStretch(1)
        root.addLayout(tools)
        self.detail = QPlainTextEdit(); self.detail.setReadOnly(True)
        root.addWidget(self.detail, 1)
        self.refresh()

    def refresh(self) -> None:
        try:
            report = work_lineage_report(self.work_id)
        except Exception as exc:
            QMessageBox.critical(self, "Lineage failed", str(exc))
            return
        lines = [
            f"Work: {report.get('work_id')}",
            f"Title: {report.get('title') or '-'}",
            f"Series: {report.get('series') or '-'}",
            f"Image master: {report.get('image_master') or '-'}",
            f"Render name: {report.get('render_name') or '-'}",
            f"Source: {report.get('source') or '-'}",
            f"Source exists: {bool(report.get('source_exists'))}",
            f"Derivative directory: {report.get('derivative_dir') or '-'}",
            f"Derivative count: {report.get('derivative_count') or 0}",
            "",
            "Derivatives:",
        ]
        derivatives = list(report.get('derivatives') or [])
        lines.extend([f"- {row.get('path')} · {row.get('dimensions') or '-'} · {row.get('size') or 0} bytes" for row in derivatives[:160]] or ["- None"])
        if len(derivatives) > 160:
            lines.append(f"- … and {len(derivatives) - 160} more")
        lines.extend(["", "Social references:"])
        lines.extend([f"- {item}" for item in report.get('social_refs') or []] or ["- None detected"])
        lines.extend(["", "Presence reconciliation:", json.dumps(report.get('presence') or {}, ensure_ascii=False, indent=2)])
        self.detail.setPlainText("\n".join(lines))




_METADATA_IMPORT_IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff'}


def _metadata_import_key(label: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(label or '').strip().lower()).strip('_')


def _metadata_import_bool(value: Any, default: bool = False) -> bool:
    text = str(value or '').strip().lower()
    if not text:
        return default
    return text in {'1', 'true', 'yes', 'y', 'on', 'published', 'public'}


def _metadata_import_focal(value: Any) -> tuple[int, int]:
    text = str(value or '').strip()
    parts = [part for part in re.split(r'[^0-9.]+', text) if part]
    if len(parts) >= 2:
        try:
            return max(0, min(100, int(float(parts[0])))), max(0, min(100, int(float(parts[1]))))
        except ValueError:
            return 50, 50
    return 50, 50


def _metadata_import_filename_keys(name: str) -> set[str]:
    original = Path(str(name or '').strip()).name.lower()
    stripped = re.sub(r'^\s*\d+\s*[.)_-]+\s*', '', original)
    compact = re.sub(r'[^a-z0-9.]+', '', original)
    stripped_compact = re.sub(r'[^a-z0-9.]+', '', stripped)
    return {key for key in {original, stripped, compact, stripped_compact} if key}


def _parse_metadata_import_fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in str(block or '').splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.strip() == '---':
            continue
        match = re.match(r'^([A-Za-z][A-Za-z0-9 /_-]{0,80}):\s*(.*)$', line)
        if match:
            current_key = _metadata_import_key(match.group(1))
            fields[current_key] = match.group(2).strip()
            continue
        if current_key:
            addition = line.strip()
            if addition:
                existing = fields.get(current_key, '').strip()
                fields[current_key] = f"{existing}\n{addition}" if existing else addition
    return fields


def parse_metadata_import_markdown(path: str | Path) -> dict[str, Any]:
    """Parse the Stillmark bulk metadata markdown format used by .md imports."""
    source = Path(path)
    text = source.read_text(encoding='utf-8')
    work_matches = list(re.finditer(r'(?m)^##\s+Work\s+\d+\b.*$', text))
    if not work_matches:
        raise ValueError("No '## Work NN' sections were found in the metadata import file.")
    project_block = text[:work_matches[0].start()]
    project_marker = re.search(r'(?m)^##\s+Project\b.*$', project_block)
    if project_marker:
        project_block = project_block[project_marker.end():]
    project_fields = _parse_metadata_import_fields(project_block)
    try:
        from qt_backend import slugify_work_id
    except Exception:
        slugify_work_id = lambda value: re.sub(r'[^a-z0-9]+', '-', str(value or '').lower()).strip('-')  # type: ignore
    series_title = (project_fields.get('series') or project_fields.get('project_title') or '').strip()
    series_slug = (project_fields.get('series_slug') or slugify_work_id(series_title)).strip()
    project: dict[str, Any] = {
        'series': series_title,
        'series_slug': series_slug,
        'project_type': (project_fields.get('project_type') or '').strip(),
        'project_title': (project_fields.get('project_title') or series_title).strip(),
        'years': (project_fields.get('years') or '').strip(),
        'location': (project_fields.get('location') or '').strip(),
        'mood': (project_fields.get('mood') or '').strip(),
        'visibility': (project_fields.get('visibility') or 'private').strip().lower(),
        'review_mode': _metadata_import_bool(project_fields.get('review_mode'), True),
        'cover_work_id': (project_fields.get('cover_work_id') or '').strip(),
        'opening': (project_fields.get('opening') or '').strip(),
    }
    rows: list[dict[str, Any]] = []
    for index, match in enumerate(work_matches):
        start = match.end()
        end = work_matches[index + 1].start() if index + 1 < len(work_matches) else len(text)
        fields = _parse_metadata_import_fields(text[start:end])
        file_name = (fields.get('file_name') or '').strip()
        row_series_title = (fields.get('series') or project['series'] or '').strip()
        row_series_slug = (fields.get('series_slug') or project['series_slug'] or slugify_work_id(row_series_title)).strip()
        work_id = (fields.get('work_id') or slugify_work_id(Path(file_name).stem)).strip()
        focal_x, focal_y = _metadata_import_focal(fields.get('focal_point'))
        tags = [item.strip() for item in (fields.get('tags') or '').split(',') if item.strip()]
        published = _metadata_import_bool(fields.get('published'), False)
        row = {
            'file_name': file_name,
            'file': '',
            'series': row_series_title,
            'series_slug': row_series_slug,
            'work_id': work_id,
            'title': (fields.get('title') or Path(file_name).stem.replace('-', ' ').replace('_', ' ').title()).strip(),
            'year': (fields.get('year') or project.get('years') or '').strip(),
            'location': (fields.get('location') or project.get('location') or '').strip(),
            'alt': (fields.get('alt_text') or fields.get('alt') or '').strip(),
            'caption': (fields.get('caption') or '').strip(),
            'tags': tags,
            'focal_x': focal_x,
            'focal_y': focal_y,
            'published': published,
            'review_status': (fields.get('review_status') or ('published' if published else 'draft')).strip().lower(),
            'status': 'pending',
        }
        rows.append(row)
    return {'path': str(source), 'base_dir': str(source.parent), 'project': project, 'rows': rows}

class BulkImageIngestDialog(QDialog):
    def __init__(self, parent: "ControlPanelWindow") -> None:
        super().__init__(parent)
        self.window = parent
        self.file_paths: list[str] = []
        self.metadata_path: str | None = None
        self.metadata_project: dict[str, Any] = {}
        self.metadata_rows: list[dict[str, Any]] = []
        self.setWindowTitle("Bulk image ingest")
        self.resize(1050, 720)
        root = QVBoxLayout(self)
        info = QLabel("Add multiple originals into one series. Use image files directly, or import a Stillmark .md metadata file and let the panel match the listed filenames.")
        info.setWordWrap(True)
        root.addWidget(info)
        form = QFormLayout()
        file_row = QHBoxLayout()
        self.file_summary = QLineEdit(); self.file_summary.setReadOnly(True)
        choose = QPushButton("Choose images…")
        choose.clicked.connect(self.choose_files)
        import_md = QPushButton("Import .md metadata…")
        import_md.clicked.connect(self.import_metadata_markdown)
        file_row.addWidget(self.file_summary, 1)
        file_row.addWidget(choose)
        file_row.addWidget(import_md)
        file_wrap = QWidget(); file_wrap.setLayout(file_row)
        form.addRow("Files", file_wrap)
        self.series_combo = QComboBox(); self.series_combo.addItems(available_series_slugs())
        form.addRow("Series", self.series_combo)
        self.year_edit = QLineEdit(); form.addRow("Year", self.year_edit)
        self.location_edit = QLineEdit(); form.addRow("Location", self.location_edit)
        self.tags_edit = QLineEdit(); form.addRow("Common tags", self.tags_edit)
        self.review_combo = QComboBox(); self.review_combo.addItems(PUBLISH_STATES); self.review_combo.setCurrentText('draft')
        form.addRow("Review status", self.review_combo)
        self.published_check = QCheckBox("Published")
        form.addRow("Published", self.published_check)
        root.addLayout(form)
        self.preview_tree = QTreeWidget()
        self.preview_tree.setHeaderLabels(["File", "Generated work ID", "Title", "Status"])
        root.addWidget(self.preview_tree, 1)
        self.summary = QPlainTextEdit(); self.summary.setReadOnly(True); self.summary.setFixedHeight(130)
        root.addWidget(self.summary)
        buttons = QHBoxLayout()
        preview_btn = QPushButton("Refresh preview")
        preview_btn.clicked.connect(self.refresh_preview)
        ingest_btn = QPushButton("Ingest all")
        ingest_btn.clicked.connect(self.ingest_all)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(preview_btn)
        buttons.addStretch(1)
        buttons.addWidget(ingest_btn)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)
        for widget in [self.series_combo, self.year_edit, self.location_edit, self.tags_edit, self.review_combo]:
            if isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self.refresh_preview)
            else:
                widget.textChanged.connect(self.refresh_preview)
        self.published_check.toggled.connect(self.refresh_preview)
        self.refresh_preview()

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose images", str(ROOT), "Images (*.jpg *.jpeg *.png *.webp *.tif *.tiff)")
        if not paths:
            return
        self.file_paths = list(paths)
        if self.metadata_rows:
            self._match_metadata_rows_to_files(self.file_paths)
            resolved = sum(1 for row in self.metadata_rows if str(row.get('file') or '').strip())
            self.file_summary.setText(f"{len(self.metadata_rows)} metadata row(s) · {resolved} image(s) matched")
        else:
            self.file_summary.setText(f"{len(paths)} file(s) selected")
        self.refresh_preview()

    def import_metadata_markdown(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import metadata markdown", str(ROOT), "Markdown metadata (*.md *.markdown);;All files (*)")
        if not path:
            return
        try:
            parsed = parse_metadata_import_markdown(path)
        except Exception as exc:
            QMessageBox.critical(self, "Metadata import failed", str(exc))
            return
        self.metadata_path = str(path)
        self.metadata_project = dict(parsed.get('project') or {})
        self.metadata_rows = [dict(row) for row in (parsed.get('rows') or [])]
        self._resolve_metadata_rows_from_folder(Path(parsed.get('base_dir') or Path(path).parent))
        project_slug = str(self.metadata_project.get('series_slug') or '').strip()
        if project_slug and self.series_combo.findText(project_slug) < 0:
            self.series_combo.addItem(project_slug)
        if project_slug:
            self.series_combo.setCurrentText(project_slug)
        if self.metadata_project.get('years'):
            self.year_edit.setText(str(self.metadata_project.get('years') or ''))
        if self.metadata_project.get('location'):
            self.location_edit.setText(str(self.metadata_project.get('location') or ''))
        review_values = {str(row.get('review_status') or '').strip().lower() for row in self.metadata_rows if str(row.get('review_status') or '').strip()}
        if len(review_values) == 1:
            value = next(iter(review_values))
            if value in PUBLISH_STATES:
                self.review_combo.setCurrentText(value)
        published_values = {bool(row.get('published')) for row in self.metadata_rows}
        if len(published_values) == 1:
            self.published_check.setChecked(next(iter(published_values)))
        resolved = sum(1 for row in self.metadata_rows if str(row.get('file') or '').strip())
        self.file_paths = [str(row.get('file')) for row in self.metadata_rows if str(row.get('file') or '').strip()]
        self.file_summary.setText(f"{len(self.metadata_rows)} metadata row(s) · {resolved} image(s) resolved")
        self.refresh_preview()

    def _resolve_metadata_rows_from_folder(self, folder: Path) -> None:
        if not self.metadata_rows:
            return
        try:
            existing_files = [item for item in folder.iterdir() if item.is_file()]
        except Exception:
            existing_files = []
        lookup: dict[str, Path] = {}
        for file_path in existing_files:
            if file_path.suffix.lower() not in _METADATA_IMPORT_IMAGE_SUFFIXES:
                continue
            for key in _metadata_import_filename_keys(file_path.name):
                lookup.setdefault(key, file_path)
        for row in self.metadata_rows:
            file_name = str(row.get('file_name') or '').strip()
            direct = folder / file_name if file_name else None
            match = direct if direct and direct.exists() else None
            if match is None:
                for key in _metadata_import_filename_keys(file_name):
                    if key in lookup:
                        match = lookup[key]
                        break
            row['file'] = str(match) if match else ''

    def _match_metadata_rows_to_files(self, paths: list[str]) -> None:
        lookup: dict[str, str] = {}
        for path in paths:
            file_path = Path(path)
            if file_path.suffix.lower() not in _METADATA_IMPORT_IMAGE_SUFFIXES:
                continue
            for key in _metadata_import_filename_keys(file_path.name):
                lookup.setdefault(key, str(file_path))
        for row in self.metadata_rows:
            if str(row.get('file') or '').strip() and Path(str(row.get('file'))).exists():
                continue
            for key in _metadata_import_filename_keys(str(row.get('file_name') or '')):
                if key in lookup:
                    row['file'] = lookup[key]
                    break

    def _metadata_series_payload(self) -> dict[str, Any]:
        slug = str(self.metadata_project.get('series_slug') or self.series_combo.currentText() or '').strip()
        title = str(self.metadata_project.get('project_title') or self.metadata_project.get('series') or slug).strip() or slug
        return {
            'title': title,
            'slug': slug,
            'project_type': str(self.metadata_project.get('project_type') or '').strip() or 'fine-art',
            'years': str(self.metadata_project.get('years') or self.year_edit.text() or '').strip(),
            'location': str(self.metadata_project.get('location') or self.location_edit.text() or '').strip(),
            'mood': str(self.metadata_project.get('mood') or '').strip(),
            'description': str(self.metadata_project.get('opening') or '').strip(),
            'visibility': str(self.metadata_project.get('visibility') or 'private').strip() or 'private',
            'review_mode': bool(self.metadata_project.get('review_mode', True)),
            'cover_work_id': str(self.metadata_project.get('cover_work_id') or '').strip(),
            'work_ids': [],
        }

    def _ensure_metadata_series_exists(self) -> str:
        slug = str(self.metadata_project.get('series_slug') or self.series_combo.currentText() or '').strip()
        if not slug:
            raise BackendError("Metadata import requires a series slug.")
        if slug not in set(available_series_slugs()):
            save_series_from_payload(None, self._metadata_series_payload())
            if self.series_combo.findText(slug) < 0:
                self.series_combo.addItem(slug)
        return slug

    def _row_for_path(self, path: str) -> dict[str, Any]:
        title = Path(path).stem.replace('-', ' ').replace('_', ' ').strip().title() or 'Untitled Work'
        if len(title.split()) < 2:
            title = f"{title} Photograph"
        from qt_backend import slugify_work_id, load_work_payload
        base_id = slugify_work_id(Path(path).stem)
        status = 'ready'
        if not self.year_edit.text().strip():
            status = 'missing year'
        elif not self.location_edit.text().strip():
            status = 'missing location'
        elif load_work_payload(base_id):
            status = 'ID already exists'
        return {'file': path, 'file_name': Path(path).name, 'work_id': base_id, 'title': title, 'year': self.year_edit.text().strip(), 'location': self.location_edit.text().strip(), 'alt': '', 'caption': '', 'tags': [item.strip() for item in self.tags_edit.text().split(',') if item.strip()], 'focal_x': 50, 'focal_y': 50, 'published': self.published_check.isChecked(), 'review_status': self.review_combo.currentText(), 'series_slug': self.series_combo.currentText(), 'status': status}

    def _row_for_metadata(self, row: dict[str, Any]) -> dict[str, Any]:
        from qt_backend import load_work_payload
        result = dict(row)
        result['series_slug'] = str(row.get('series_slug') or self.metadata_project.get('series_slug') or self.series_combo.currentText() or '').strip()
        result['year'] = str(row.get('year') or self.year_edit.text() or '').strip()
        result['location'] = str(row.get('location') or self.location_edit.text() or '').strip()
        file_path = str(row.get('file') or '').strip()
        work_id = str(row.get('work_id') or '').strip()
        status = 'ready'
        if not file_path or not Path(file_path).exists():
            status = 'image file not found'
        elif not work_id:
            status = 'missing work ID'
        elif not result.get('title'):
            status = 'missing title'
        elif not result['year']:
            status = 'missing year'
        elif not result['location']:
            status = 'missing location'
        elif load_work_payload(work_id):
            status = 'ID already exists'
        result['status'] = status
        return result

    def _current_rows(self) -> list[dict[str, Any]]:
        if self.metadata_rows:
            return [self._row_for_metadata(row) for row in self.metadata_rows]
        return [self._row_for_path(path) for path in self.file_paths]

    def refresh_preview(self) -> None:
        self.preview_tree.clear()
        rows = self._current_rows()
        ready = 0
        for row in rows:
            file_label = str(row.get('file_name') or Path(str(row.get('file') or '')).name or '-')
            item = QTreeWidgetItem([file_label, str(row.get('work_id') or ''), str(row.get('title') or ''), str(row.get('status') or '')])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            color = self.window._severity_color('ok' if row.get('status') == 'ready' else 'error')
            for col in range(4):
                item.setForeground(col, color)
            self.preview_tree.addTopLevelItem(item)
            ready += 1 if row.get('status') == 'ready' else 0
        self.preview_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        mode = f"Metadata: {Path(self.metadata_path).name}" if self.metadata_path else "Manual image selection"
        series_label = self.metadata_project.get('series_slug') or self.series_combo.currentText() or '-'
        self.summary.setPlainText(f"{len(rows)} selected · {ready} ready · {len(rows) - ready} blocked\nSeries: {series_label}\nMode: {mode}")

    def ingest_all(self) -> None:
        rows = self._current_rows()
        blocked = [row for row in rows if row['status'] != 'ready']
        if not rows:
            QMessageBox.information(self, "No files", "Choose images or import metadata first.")
            return
        if blocked:
            QMessageBox.warning(self, "Cannot ingest yet", "Fix blocked rows first. Common causes: missing image files, missing year/location, or duplicate work IDs.")
            return
        target_series = str(self.metadata_project.get('series_slug') or self.series_combo.currentText() or '').strip()
        if QMessageBox.question(self, "Ingest images", f"Add {len(rows)} work(s) to {target_series}?") != QMessageBox.StandardButton.Yes:
            return
        created: list[str] = []
        errors: list[str] = []
        common_tags = [item.strip() for item in self.tags_edit.text().split(',') if item.strip()]
        try:
            if self.metadata_rows:
                target_series = self._ensure_metadata_series_exists()
        except Exception as exc:
            QMessageBox.critical(self, "Series setup failed", str(exc))
            return
        for index, row in enumerate(rows, start=1):
            try:
                alt = str(row.get('alt') or '').strip() or f"Black and white photograph titled {row['title']} made in {row.get('location') or self.location_edit.text().strip()}."
                caption = str(row.get('caption') or '').strip() or f"{row['title']}, {row.get('location') or self.location_edit.text().strip()}, {row.get('year') or self.year_edit.text().strip()}."
                row_tags = list(row.get('tags') or []) if isinstance(row.get('tags'), list) else []
                tags = row_tags or common_tags
                work_id = add_image(
                    file_path=str(row['file']),
                    series_slug=str(row.get('series_slug') or target_series or self.series_combo.currentText()),
                    work_id=str(row['work_id']),
                    title=str(row['title']),
                    year=str(row.get('year') or self.year_edit.text()),
                    location=str(row.get('location') or self.location_edit.text()),
                    alt=alt,
                    caption=caption,
                    tags=tags,
                    review_status=str(row.get('review_status') or self.review_combo.currentText()),
                    published=bool(row.get('published')) if self.metadata_rows else self.published_check.isChecked(),
                    hero_safe=True,
                    grid_safe=True,
                    social_safe=False,
                    focal_x=int(row.get('focal_x', 50) or 50),
                    focal_y=int(row.get('focal_y', 50) or 50),
                    position=None,
                )
                created.append(work_id)
            except Exception as exc:
                errors.append(f"{Path(str(row.get('file') or row.get('file_name') or '')).name}: {exc}")
        self.window.clear_work_icon_cache()
        if errors:
            QMessageBox.warning(self, "Bulk ingest finished with errors", "\n".join(errors[:20]))
        if created:
            self.window.push_notification("success", "Bulk image ingest complete", f"Added {len(created)} work(s).", target_scope="work", target_id=created[0])
            self.window.refresh_all_context(activate="works", select_work=created[0], force=True, scope={"works", "series", "dashboard", "validation", "studio"})
            self.accept()


class SeriesCurationDialog(QDialog):
    def __init__(self, parent: "ControlPanelWindow", series_slug: str | None = None) -> None:
        super().__init__(parent)
        self.window = parent
        self.series_slug = series_slug or ''
        self.setWindowTitle("Series curation workspace")
        self.resize(1120, 700)
        root = QVBoxLayout(self)
        tools = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        open_series = QPushButton("Open selected series")
        open_series.clicked.connect(self.open_selected_series)
        tools.addWidget(refresh)
        tools.addWidget(open_series)
        tools.addStretch(1)
        root.addLayout(tools)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        # completeness
        complete_tab = QWidget(); complete_layout = QHBoxLayout(complete_tab)
        self.complete_tree = QTreeWidget()
        self.complete_tree.setHeaderLabels(["Score", "Status", "Series", "Works", "Published", "Cover"])
        self.complete_tree.itemSelectionChanged.connect(self.update_complete_detail)
        self.complete_tree.itemDoubleClicked.connect(lambda _item, _col: self.open_selected_series())
        self.complete_detail = QPlainTextEdit(); self.complete_detail.setReadOnly(True)
        complete_layout.addWidget(self.complete_tree, 3)
        complete_layout.addWidget(self.complete_detail, 2)
        self.tabs.addTab(complete_tab, "Completeness")
        # rhythm
        rhythm_tab = QWidget(); rhythm_layout = QVBoxLayout(rhythm_tab)
        select_row = QHBoxLayout()
        self.rhythm_series_combo = QComboBox(); self.rhythm_series_combo.addItems(available_series_slugs())
        if self.series_slug:
            self.rhythm_series_combo.setCurrentText(self.series_slug)
        self.rhythm_series_combo.currentTextChanged.connect(self.refresh_rhythm)
        apply_suggestion = QPushButton("Apply brightness rhythm suggestion")
        apply_suggestion.clicked.connect(self.apply_rhythm_suggestion)
        select_row.addWidget(QLabel("Series"))
        select_row.addWidget(self.rhythm_series_combo, 1)
        select_row.addWidget(apply_suggestion)
        rhythm_layout.addLayout(select_row)
        self.rhythm_tree = QTreeWidget()
        self.rhythm_tree.setHeaderLabels(["#", "Work", "Title", "Orientation", "Brightness", "Dimensions", "Issues"])
        rhythm_layout.addWidget(self.rhythm_tree, 1)
        self.tabs.addTab(rhythm_tab, "Rhythm")
        self.refresh()

    def refresh(self) -> None:
        self.complete_tree.clear()
        try:
            rows = series_completeness_rows()
        except Exception as exc:
            QMessageBox.critical(self, "Curation report failed", str(exc))
            return
        for row in rows:
            item = QTreeWidgetItem([
                str(row.get('score') or 0),
                str(row.get('status') or ''),
                str(row.get('slug') or ''),
                str(row.get('works') or 0),
                str(row.get('published') or 0),
                str(row.get('cover') or ''),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            color = self.window._severity_color('error' if row.get('status') == 'blocked' else 'warning' if row.get('status') == 'review' else 'ok')
            for col in range(6):
                item.setForeground(col, color)
            self.complete_tree.addTopLevelItem(item)
        self.complete_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        if self.complete_tree.topLevelItemCount():
            self.complete_tree.setCurrentItem(self.complete_tree.topLevelItem(0))
        self.update_complete_detail()
        self.refresh_rhythm()

    def update_complete_detail(self) -> None:
        item = self.complete_tree.currentItem()
        if item is None:
            self.complete_detail.setPlainText("No series found.")
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        lines = [
            f"Series: {row.get('slug')} · {row.get('title') or '-'}",
            f"Score: {row.get('score')}",
            f"Status: {row.get('status')}",
            f"Works: {row.get('works')} · Published: {row.get('published')}",
            f"Cover: {row.get('cover') or '-'}",
            "",
            "Issues:",
        ]
        lines.extend([f"- {issue}" for issue in row.get('issues') or []] or ["- None"])
        self.complete_detail.setPlainText("\n".join(lines))

    def refresh_rhythm(self) -> None:
        slug = self.rhythm_series_combo.currentText()
        self.rhythm_tree.clear()
        if not slug:
            return
        try:
            rows = series_rhythm_rows(slug)
        except Exception as exc:
            self.rhythm_tree.addTopLevelItem(QTreeWidgetItem(["", "", "", "", "", "", f"Failed: {exc}"]))
            return
        for row in rows:
            item = QTreeWidgetItem([
                str(row.get('position') or ''),
                str(row.get('id') or ''),
                str(row.get('title') or ''),
                str(row.get('orientation') or ''),
                str(row.get('brightness') or ''),
                str(row.get('dimensions') or ''),
                str(len(row.get('issues') or [])),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            if row.get('issues'):
                for col in range(7):
                    item.setForeground(col, self.window._severity_color('warning'))
            self.rhythm_tree.addTopLevelItem(item)
        self.rhythm_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

    def open_selected_series(self) -> None:
        item = self.complete_tree.currentItem()
        if item is None:
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        slug = str(row.get('slug') or '')
        if slug:
            self.window.tabs.setCurrentWidget(self.window.series_tab)
            self.window.select_series(slug)
            self.accept()

    def apply_rhythm_suggestion(self) -> None:
        slug = self.rhythm_series_combo.currentText().strip()
        if not slug:
            return
        if QMessageBox.question(self, "Apply suggested order", f"Reorder series '{slug}' using the brightness rhythm suggestion?") != QMessageBox.StandardButton.Yes:
            return
        try:
            order = suggest_series_order(slug)
            payload = load_series_payload(slug)
            payload['work_ids'] = order
            save_series_from_payload(slug, payload)
        except Exception as exc:
            QMessageBox.critical(self, "Could not apply order", str(exc))
            return
        self.window.push_notification("success", "Series rhythm order applied", slug, target_scope="series", target_id=slug)
        self.window.refresh_all_context(activate="series", select_series=slug, force=True, scope={"series", "studio", "dashboard", "validation"})
        self.refresh_rhythm()



class AddImageDialog(QDialog):
    def __init__(self, parent: "ControlPanelWindow") -> None:
        super().__init__(parent)
        self.window = parent
        self.file_path: str = ""
        self.setWindowTitle("Guided add work")
        self.resize(780, 760)
        self.setModal(True)
        root = QVBoxLayout(self)
        guide = QLabel("Guided flow: 1) choose original image · 2) assign series · 3) complete metadata · 4) set review state and focal point · 5) import with validation.")
        guide.setObjectName("missionStatus")
        guide.setWordWrap(True)
        root.addWidget(guide)
        form = QFormLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        file_row = QHBoxLayout()
        file_row.addWidget(self.file_edit)
        browse = QPushButton("Choose image…")
        browse.clicked.connect(self.choose_file)
        file_row.addWidget(browse)
        file_wrap = QWidget()
        file_wrap.setLayout(file_row)
        form.addRow("File", file_wrap)
        self.series_combo = QComboBox()
        self.series_combo.addItems(available_series_slugs())
        form.addRow("Series", self.series_combo)
        self.work_id_edit = QLineEdit()
        form.addRow("Work ID", self.work_id_edit)
        self.title_edit = QLineEdit()
        form.addRow("Title", self.title_edit)
        self.year_edit = QLineEdit()
        form.addRow("Year", self.year_edit)
        self.location_edit = QLineEdit()
        form.addRow("Location", self.location_edit)
        self.alt_edit = QPlainTextEdit()
        self.alt_edit.setFixedHeight(72)
        form.addRow("Alt text", self.alt_edit)
        self.caption_edit = QPlainTextEdit()
        self.caption_edit.setFixedHeight(96)
        form.addRow("Caption", self.caption_edit)
        self.tags_edit = QLineEdit()
        form.addRow("Tags", self.tags_edit)
        self.review_combo = QComboBox()
        self.review_combo.addItems(PUBLISH_STATES)
        form.addRow("Review status", self.review_combo)
        self.position_spin = QSpinBox()
        self.position_spin.setRange(0, 9999)
        self.position_spin.setSpecialValueText("Append")
        form.addRow("Series position", self.position_spin)
        flags = QHBoxLayout()
        self.published_check = QCheckBox("Published")
        self.hero_check = QCheckBox("Hero safe")
        self.hero_check.setChecked(True)
        self.grid_check = QCheckBox("Grid safe")
        self.grid_check.setChecked(True)
        self.social_check = QCheckBox("Social safe")
        for widget in (self.published_check, self.hero_check, self.grid_check, self.social_check):
            flags.addWidget(widget)
        flags.addStretch(1)
        flags_wrap = QWidget()
        flags_wrap.setLayout(flags)
        form.addRow("Flags", flags_wrap)
        focal_row = QHBoxLayout()
        self.focal_x = QSpinBox(); self.focal_x.setRange(0, 100); self.focal_x.setValue(50)
        self.focal_y = QSpinBox(); self.focal_y.setRange(0, 100); self.focal_y.setValue(50)
        focal_row.addWidget(QLabel("X"))
        focal_row.addWidget(self.focal_x)
        focal_row.addSpacing(12)
        focal_row.addWidget(QLabel("Y"))
        focal_row.addWidget(self.focal_y)
        focal_row.addStretch(1)
        focal_wrap = QWidget(); focal_wrap.setLayout(focal_row)
        form.addRow("Focal point", focal_wrap)
        root.addLayout(form)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setFixedHeight(180)
        root.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept_add)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.title_edit.textChanged.connect(self._sync_work_id_from_title)
        for widget in [
            self.series_combo,
            self.work_id_edit,
            self.title_edit,
            self.year_edit,
            self.location_edit,
            self.tags_edit,
            self.review_combo,
        ]:
            if isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self.update_summary)
            else:
                widget.textChanged.connect(self.update_summary)
        self.alt_edit.textChanged.connect(self.update_summary)
        self.caption_edit.textChanged.connect(self.update_summary)
        self.published_check.toggled.connect(self._sync_review_state)
        self.published_check.toggled.connect(self.update_summary)
        self.hero_check.toggled.connect(self.update_summary)
        self.grid_check.toggled.connect(self.update_summary)
        self.social_check.toggled.connect(self.update_summary)
        self.focal_x.valueChanged.connect(self.update_summary)
        self.focal_y.valueChanged.connect(self.update_summary)
        self.position_spin.valueChanged.connect(self.update_summary)
        self.review_combo.setCurrentText("draft")
        self.update_summary()

    def _sync_work_id_from_title(self) -> None:
        if self.work_id_edit.hasFocus() and self.work_id_edit.text().strip():
            self.update_summary()
            return
        stem = self.title_edit.text().strip()
        if stem:
            with signals_blocked(self.work_id_edit):
                from qt_backend import slugify_work_id
                self.work_id_edit.setText(slugify_work_id(stem))
        self.update_summary()

    def _sync_review_state(self) -> None:
        if self.published_check.isChecked() and self.review_combo.currentText() != "published":
            self.review_combo.setCurrentText("published")
        elif (not self.published_check.isChecked()) and self.review_combo.currentText() == "published":
            self.review_combo.setCurrentText("review")

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose image", str(ROOT), "Images (*.jpg *.jpeg *.png *.webp *.tif *.tiff)")
        if not path:
            return
        self.file_path = path
        self.file_edit.setText(path)
        if not self.title_edit.text().strip():
            stem = Path(path).stem.replace("-", " ").replace("_", " ").title()
            self.title_edit.setText(stem)
        if not self.work_id_edit.text().strip():
            from qt_backend import slugify_work_id
            self.work_id_edit.setText(slugify_work_id(Path(path).stem))
        self.update_summary()

    def update_summary(self) -> None:
        lines = [
            f"File: {Path(self.file_path).name if self.file_path else '-'}",
            f"Series: {self.series_combo.currentText() or '-'}",
            f"Work ID: {self.work_id_edit.text().strip() or '-'}",
            f"Title: {self.title_edit.text().strip() or '-'}",
            f"Focal point: {self.focal_x.value()}, {self.focal_y.value()}",
        ]
        warnings: list[str] = []
        if len(self.alt_edit.toPlainText().split()) < 5:
            warnings.append("Alt text should have at least 5 descriptive words.")
        if len(self.title_edit.text().split()) < 2:
            warnings.append("Title is very short.")
        if not self.year_edit.text().strip():
            warnings.append("Year is empty.")
        if not self.location_edit.text().strip():
            warnings.append("Location is empty.")
        text = "\n".join(lines)
        if warnings:
            text += "\n\nWarnings:\n- " + "\n- ".join(warnings)
        self.summary.setPlainText(text)

    def accept_add(self) -> None:
        try:
            work_id = add_image(
                file_path=self.file_path,
                series_slug=self.series_combo.currentText(),
                work_id=self.work_id_edit.text(),
                title=self.title_edit.text(),
                year=self.year_edit.text(),
                location=self.location_edit.text(),
                alt=self.alt_edit.toPlainText(),
                caption=self.caption_edit.toPlainText(),
                tags=[item.strip() for item in self.tags_edit.text().split(",") if item.strip()],
                review_status=self.review_combo.currentText(),
                published=self.published_check.isChecked(),
                hero_safe=self.hero_check.isChecked(),
                grid_safe=self.grid_check.isChecked(),
                social_safe=self.social_check.isChecked(),
                focal_x=self.focal_x.value(),
                focal_y=self.focal_y.value(),
                position=None if self.position_spin.value() == 0 else self.position_spin.value(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Add image failed", str(exc))
            return
        self.window.clear_work_icon_cache(work_id)
        self.window.status_message(f"Added image: {work_id}")
        self.window.refresh_all_context(activate="works", select_work=work_id, force=True, scope={"works", "dashboard", "validation"})
        self.accept()


class DuplicateWorkDialog(QDialog):
    def __init__(self, parent: "ControlPanelWindow", source_work_id: str) -> None:
        super().__init__(parent)
        self.window = parent
        self.source_work_id = source_work_id
        self.created_work_id = ""
        self.setWindowTitle("Duplicate work · editable draft")
        self.resize(760, 560)
        root = QVBoxLayout(self)
        note = QLabel("Duplicates metadata only, forces the new work to draft, and intentionally does not copy the source image. Add or relink the image after the draft is created.")
        note.setObjectName("missionStatus")
        note.setWordWrap(True)
        root.addWidget(note)
        form = QFormLayout()
        self.new_id_edit = QLineEdit()
        self.title_edit = QLineEdit()
        self.series_combo = QComboBox(); self.series_combo.addItems(available_series_slugs())
        form.addRow("New Work ID", self.new_id_edit)
        form.addRow("New title", self.title_edit)
        form.addRow("Series", self.series_combo)
        root.addLayout(form)
        self.preview = QPlainTextEdit(); self.preview.setReadOnly(True); self.preview.setFixedHeight(260)
        root.addWidget(self.preview)
        self.new_id_edit.textChanged.connect(self.refresh_preview)
        self.title_edit.textChanged.connect(self.refresh_preview)
        self.series_combo.currentTextChanged.connect(self.refresh_preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.create_duplicate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.refresh_preview()

    def refresh_preview(self) -> None:
        try:
            row = preview_duplicate_work(
                self.source_work_id,
                new_work_id=self.new_id_edit.text(),
                title=self.title_edit.text(),
                series_slug=self.series_combo.currentText(),
            )
        except Exception as exc:
            self.preview.setPlainText(f"Preview failed: {exc}")
            return
        with signals_blocked(self.new_id_edit):
            if not self.new_id_edit.text().strip():
                self.new_id_edit.setText(str(row.get("new_work_id") or ""))
        with signals_blocked(self.title_edit):
            if not self.title_edit.text().strip():
                self.title_edit.setText(str(row.get("title") or ""))
        score = (row.get("completeness") or {}).get("score", "-")
        issues = (row.get("completeness") or {}).get("issues") or []
        lines = [
            f"Source: {self.source_work_id}",
            f"New ID: {row.get('new_work_id') or '-'}",
            f"Title: {row.get('title') or '-'}",
            f"Series: {row.get('series') or '-'}",
            "Review state: draft · unpublished",
            f"Image policy: {row.get('image_policy')}",
            f"Completeness after duplicate: {score}/100",
            "",
            "Known follow-up:",
        ]
        lines.extend([f"- {item}" for item in issues] or ["- Add/relink a source image if this draft should become a public work."])
        self.preview.setPlainText("\n".join(lines))

    def create_duplicate(self) -> None:
        try:
            self.created_work_id = duplicate_work(
                self.source_work_id,
                new_work_id=self.new_id_edit.text(),
                title=self.title_edit.text(),
                series_slug=self.series_combo.currentText(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Duplicate failed", str(exc))
            return
        self.accept()


class MediaLibraryDialog(QDialog):
    def __init__(self, parent: "ControlPanelWindow") -> None:
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle("Media library · originals, derivatives, recovery")
        self.resize(1180, 720)
        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.search_edit = QLineEdit(); self.search_edit.setPlaceholderText("Search work, title, series, recovery…")
        self.status_combo = QComboBox(); self.status_combo.addItems(["All", "ok", "orphan-risk", "recoverable", "derivative-only", "missing", "unknown"])
        self.series_combo = QComboBox(); self.series_combo.addItems(["All series"] + available_series_slugs())
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        relink_btn = QPushButton("Relink selected…")
        relink_btn.clicked.connect(self.relink_selected)
        regen_btn = QPushButton("Regenerate selected derivatives")
        regen_btn.clicked.connect(self.regenerate_selected)
        tags_btn = QPushButton("Tag vocabulary…")
        tags_btn.clicked.connect(self.open_tag_vocabulary)
        for widget in (QLabel("Search"), self.search_edit, QLabel("Status"), self.status_combo, QLabel("Series"), self.series_combo, refresh_btn, relink_btn, regen_btn, tags_btn):
            controls.addWidget(widget)
        root.addLayout(controls)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Work ID", "Title", "Series", "Status", "Source", "Derivatives", "Recovery"])
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self.update_detail)
        split.addWidget(self.tree)
        right = QWidget(); right_layout = QVBoxLayout(right)
        self.preview = QLabel("Select a media row.")
        self.preview.setObjectName("imagePreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(320)
        right_layout.addWidget(self.preview)
        self.detail = QPlainTextEdit(); self.detail.setReadOnly(True)
        right_layout.addWidget(self.detail, 1)
        split.addWidget(right)
        split.setSizes([760, 420])
        root.addWidget(split, 1)
        self.search_edit.textChanged.connect(lambda _=None: self.refresh())
        self.status_combo.currentTextChanged.connect(lambda _=None: self.refresh())
        self.series_combo.currentTextChanged.connect(lambda _=None: self.refresh())
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject); close.accepted.connect(self.accept)
        root.addWidget(close)
        self.refresh()

    def selected_work_ids(self) -> list[str]:
        result: list[str] = []
        for item in self.tree.selectedItems():
            row = item.data(0, Qt.ItemDataRole.UserRole) or {}
            work_id = str(row.get("id") or "").strip()
            if work_id and work_id not in result:
                result.append(work_id)
        return result

    def refresh(self) -> None:
        self.tree.clear()
        try:
            rows = media_library_rows(self.search_edit.text(), self.status_combo.currentText(), self.series_combo.currentText())
        except Exception as exc:
            self.detail.setPlainText(f"Media library refresh failed: {exc}")
            return
        for row in rows:
            item = QTreeWidgetItem([
                str(row.get("id") or ""),
                str(row.get("title") or ""),
                str(row.get("series") or ""),
                str(row.get("status") or ""),
                str(row.get("source") or ""),
                str(row.get("derivative_count") or 0),
                str(row.get("recovery") or ""),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            color = self.window._severity_color("error" if row.get("severity") == "error" else "warning" if row.get("severity") == "warning" else "ok")
            for col in range(7):
                item.setForeground(col, color)
            payload = load_work_payload(str(row.get("id") or ""))
            icon = self.window.work_tree_icon(payload) if payload else QIcon()
            if not icon.isNull():
                item.setIcon(0, icon)
            self.tree.addTopLevelItem(item)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.update_detail()

    def update_detail(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            self.detail.setPlainText("No media row selected.")
            self.window._set_preview_label(self.preview, None, fallback="Select a media row.", size=QSize(420, 320))
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        completeness = row.get("completeness") or {}
        lines = [
            f"Work ID: {row.get('id') or '-'}",
            f"Title: {row.get('title') or '-'}",
            f"Series: {row.get('series') or '-'}",
            f"Status: {row.get('status') or '-'}",
            f"Source: {row.get('source') or '-'}",
            f"Source dimensions: {row.get('source_dimensions') or '-'}",
            f"Preview dimensions: {row.get('preview_dimensions') or '-'}",
            f"Derivatives: {row.get('derivative_count') or 0}",
            f"Expected stems: {row.get('expected') or '-'}",
            f"Completeness: {completeness.get('score', '-')}/100 · {completeness.get('status', '-')}",
            "",
            f"Recovery: {row.get('recovery') or '-'}",
        ]
        if completeness.get("issues"):
            lines.extend(["", "Completeness issues:"])
            lines.extend(f"- {issue}" for issue in completeness.get("issues") or [])
        self.detail.setPlainText("\n".join(lines))
        self.window._set_preview_label(self.preview, row.get("preview") or row.get("source"), fallback="No preview available.", size=QSize(420, 320))

    def relink_selected(self) -> None:
        ids = self.selected_work_ids()
        if len(ids) != 1:
            QMessageBox.information(self, "Select one row", "Select exactly one media row to relink.")
            return
        self.window.tabs.setCurrentWidget(self.window.studio_tab)
        # Reuse the proven Studio relink workflow by selecting the row there when possible.
        self.window.refresh_studio()
        for idx in range(self.window.studio_assets.topLevelItemCount()):
            item = self.window.studio_assets.topLevelItem(idx)
            if item and item.text(0) == ids[0]:
                self.window.studio_assets.setCurrentItem(item)
                break
        self.window.relink_selected_studio_asset()
        self.refresh()

    def regenerate_selected(self) -> None:
        ids = self.selected_work_ids()
        if not ids:
            QMessageBox.information(self, "No rows selected", "Select one or more media rows first.")
            return
        if QMessageBox.question(self, "Regenerate derivatives", f"Regenerate derivatives for {len(ids)} work(s)?") != QMessageBox.StandardButton.Yes:
            return
        def task() -> dict[str, Any]:
            return regenerate_derivatives_for_work_ids(ids, line_callback=self.window._emit_line)
        def done(_result: Any) -> None:
            self.window.clear_work_icon_cache()
            self.window.refresh_all_context(force=True, scope={"works", "studio", "dashboard", "validation"})
            self.refresh()
        self.window.start_task("Regenerate media-library derivatives", task, on_done=done)

    def open_tag_vocabulary(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Controlled tag vocabulary")
        dialog.resize(680, 520)
        layout = QVBoxLayout(dialog)
        tree = QTreeWidget(); tree.setHeaderLabels(["Tag", "Count", "Variants"])
        for row in tag_vocabulary_rows():
            tree.addTopLevelItem(QTreeWidgetItem([str(row.get("tag") or ""), str(row.get("count") or 0), ", ".join(row.get("variants") or [])]))
        layout.addWidget(tree, 1)
        merge_row = QHBoxLayout()
        old_edit = QLineEdit(); old_edit.setPlaceholderText("Old tag")
        new_edit = QLineEdit(); new_edit.setPlaceholderText("New/approved tag")
        merge_btn = QPushButton("Merge tag")
        merge_row.addWidget(old_edit); merge_row.addWidget(new_edit); merge_row.addWidget(merge_btn)
        layout.addLayout(merge_row)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject); close.accepted.connect(dialog.accept)
        layout.addWidget(close)
        def apply_merge() -> None:
            try:
                result = merge_work_tag(old_edit.text(), new_edit.text())
            except Exception as exc:
                QMessageBox.critical(dialog, "Tag merge failed", str(exc))
                return
            QMessageBox.information(dialog, "Tag merged", f"Updated {result.get('count', 0)} work(s).")
            dialog.accept()
            self.window.refresh_all_context(force=True, scope={"works", "studio", "dashboard", "validation"})
        merge_btn.clicked.connect(apply_merge)
        dialog.exec()




class NewSeriesDialog(QDialog):
    def __init__(self, parent: "ControlPanelWindow") -> None:
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle("New series")
        self.resize(520, 360)
        layout = QFormLayout(self)
        self.title_edit = QLineEdit()
        self.years_edit = QLineEdit()
        self.mood_edit = QLineEdit()
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setFixedHeight(140)
        self.visibility_combo = QComboBox(); self.visibility_combo.addItems(["public", "private"])
        layout.addRow("Title", self.title_edit)
        layout.addRow("Years", self.years_edit)
        layout.addRow("Mood", self.mood_edit)
        layout.addRow("Description", self.desc_edit)
        layout.addRow("Visibility", self.visibility_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept_create)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def accept_create(self) -> None:
        try:
            slug = create_series(
                title=self.title_edit.text(),
                years=self.years_edit.text(),
                mood=self.mood_edit.text(),
                description=self.desc_edit.toPlainText(),
                visibility=self.visibility_combo.currentText(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Create series failed", str(exc))
            return
        self.window.status_message(f"Created series: {slug}")
        self.window.refresh_all_context(activate="series", select_series=slug, force=True, scope={"series", "dashboard", "validation"})
        self.accept()



class JsonObjectDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, initial: dict[str, Any] | None = None, *, title: str = "JSON editor", help_text: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 560)
        layout = QVBoxLayout(self)
        if help_text:
            info = QLabel(help_text)
            info.setWordWrap(True)
            layout.addWidget(info)
        self.editor = QPlainTextEdit(json.dumps(initial or {}, ensure_ascii=False, indent=2))
        layout.addWidget(self.editor, 1)
        buttons = QHBoxLayout()
        format_btn = QPushButton("Format")
        format_btn.clicked.connect(self.format_json)
        buttons.addWidget(format_btn)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

    def format_json(self) -> None:
        try:
            payload = json.loads(self.editor.toPlainText() or '{}')
        except Exception as exc:
            QMessageBox.critical(self, 'Invalid JSON', str(exc))
            return
        self.editor.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))

    def value(self) -> dict[str, Any]:
        payload = json.loads(self.editor.toPlainText() or '{}')
        if not isinstance(payload, dict):
            raise ValueError('JSON payload must be an object.')
        return payload


class ActionItemDialog(QDialog):
    KNOWN_KEYS = {"label", "href", "style", "icon", "target", "note", "visible"}

    def __init__(self, parent: QWidget | None = None, initial: dict[str, Any] | None = None, *, title: str = "Action") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(620, 420)
        payload = dict(initial or {})
        self._initial = dict(payload)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.label_edit = QLineEdit(str(payload.get("label") or ""))
        self.href_edit = QLineEdit(str(payload.get("href") or ""))
        self.style_combo = QComboBox(); self.style_combo.setEditable(True); self.style_combo.addItems(["", "primary", "secondary", "ghost", "link"]); self.style_combo.setCurrentText(str(payload.get("style") or ""))
        self.icon_edit = QLineEdit(str(payload.get("icon") or ""))
        self.target_edit = QLineEdit(str(payload.get("target") or ""))
        self.note_edit = QPlainTextEdit(str(payload.get("note") or "")); self.note_edit.setFixedHeight(90)
        self.visible_check = QCheckBox("Visible"); self.visible_check.setChecked(bool(payload.get("visible", True)))
        form.addRow("Label", self.label_edit)
        form.addRow("Href", self.href_edit)
        form.addRow("Style", self.style_combo)
        form.addRow("Icon", self.icon_edit)
        form.addRow("Target", self.target_edit)
        form.addRow("Note", self.note_edit)
        form.addRow("State", self.visible_check)
        layout.addLayout(form)
        self.extra_edit = QPlainTextEdit(json.dumps({k: v for k, v in payload.items() if k not in self.KNOWN_KEYS}, ensure_ascii=False, indent=2))
        self.extra_edit.setPlaceholderText("Advanced JSON fields preserved on save.")
        self.extra_edit.setFixedHeight(120)
        layout.addWidget(QLabel("Advanced JSON"))
        layout.addWidget(self.extra_edit)
        buttons = QHBoxLayout()
        format_btn = QPushButton("Format JSON")
        format_btn.clicked.connect(self._format_json)
        buttons.addWidget(format_btn)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

    def _extra_payload(self) -> dict[str, Any]:
        extra_text = self.extra_edit.toPlainText().strip() or '{}'
        payload = json.loads(extra_text)
        if not isinstance(payload, dict):
            raise ValueError('Advanced JSON must be an object.')
        return payload

    def _format_json(self) -> None:
        try:
            self.extra_edit.setPlainText(json.dumps(self._extra_payload(), ensure_ascii=False, indent=2, sort_keys=True))
        except Exception as exc:
            QMessageBox.critical(self, 'Invalid JSON', str(exc))

    def value(self) -> dict[str, Any]:
        payload = dict(self._initial)
        for key in list(payload.keys()):
            if key not in self.KNOWN_KEYS:
                payload.pop(key, None)
        payload.update(self._extra_payload())
        payload["label"] = self.label_edit.text().strip()
        payload["href"] = self.href_edit.text().strip()
        style = self.style_combo.currentText().strip()
        if style:
            payload["style"] = style
        else:
            payload.pop("style", None)
        icon = self.icon_edit.text().strip()
        if icon:
            payload["icon"] = icon
        else:
            payload.pop("icon", None)
        target = self.target_edit.text().strip()
        if target:
            payload["target"] = target
        else:
            payload.pop("target", None)
        note = self.note_edit.toPlainText().strip()
        if note:
            payload["note"] = note
        else:
            payload.pop("note", None)
        payload["visible"] = bool(self.visible_check.isChecked())
        return payload


class MetricItemDialog(QDialog):
    KNOWN_KEYS = {"value", "label", "suffix", "note", "icon", "visible"}

    def __init__(self, parent: QWidget | None = None, initial: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Metric")
        self.resize(560, 360)
        payload = dict(initial or {})
        self._initial = dict(payload)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.value_edit = QLineEdit(str(payload.get("value") or ""))
        self.label_edit = QLineEdit(str(payload.get("label") or ""))
        self.suffix_edit = QLineEdit(str(payload.get("suffix") or ""))
        self.icon_edit = QLineEdit(str(payload.get("icon") or ""))
        self.note_edit = QPlainTextEdit(str(payload.get("note") or "")); self.note_edit.setFixedHeight(90)
        self.visible_check = QCheckBox("Visible")
        self.visible_check.setChecked(bool(payload.get("visible", True)))
        form.addRow("Value", self.value_edit)
        form.addRow("Label", self.label_edit)
        form.addRow("Suffix", self.suffix_edit)
        form.addRow("Icon", self.icon_edit)
        form.addRow("Note", self.note_edit)
        form.addRow("State", self.visible_check)
        layout.addLayout(form)
        self.extra_edit = QPlainTextEdit(json.dumps({k: v for k, v in payload.items() if k not in self.KNOWN_KEYS}, ensure_ascii=False, indent=2))
        self.extra_edit.setFixedHeight(120)
        layout.addWidget(QLabel("Advanced JSON"))
        layout.addWidget(self.extra_edit)
        buttons = QHBoxLayout()
        format_btn = QPushButton("Format JSON")
        format_btn.clicked.connect(self._format_json)
        buttons.addWidget(format_btn)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

    def _extra_payload(self) -> dict[str, Any]:
        payload = json.loads(self.extra_edit.toPlainText().strip() or '{}')
        if not isinstance(payload, dict):
            raise ValueError('Advanced JSON must be an object.')
        return payload

    def _format_json(self) -> None:
        try:
            self.extra_edit.setPlainText(json.dumps(self._extra_payload(), ensure_ascii=False, indent=2, sort_keys=True))
        except Exception as exc:
            QMessageBox.critical(self, 'Invalid JSON', str(exc))

    def value(self) -> dict[str, Any]:
        payload = {k: v for k, v in self._initial.items() if k in self.KNOWN_KEYS}
        payload.update(self._extra_payload())
        payload["value"] = self.value_edit.text().strip()
        payload["label"] = self.label_edit.text().strip()
        suffix = self.suffix_edit.text().strip()
        if suffix:
            payload["suffix"] = suffix
        else:
            payload.pop("suffix", None)
        icon = self.icon_edit.text().strip()
        if icon:
            payload["icon"] = icon
        else:
            payload.pop("icon", None)
        note = self.note_edit.toPlainText().strip()
        if note:
            payload["note"] = note
        else:
            payload.pop("note", None)
        payload["visible"] = bool(self.visible_check.isChecked())
        return payload


class CardItemDialog(QDialog):
    KNOWN_KEYS = {"eyebrow", "title", "text", "href", "label", "style", "image", "work_id", "series_slug", "tags", "visible", "meta"}

    def __init__(self, parent: QWidget | None = None, initial: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Card")
        self.resize(760, 620)
        payload = dict(initial or {})
        self._initial = dict(payload)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.eyebrow_edit = QLineEdit(str(payload.get("eyebrow") or ""))
        self.title_edit = QLineEdit(str(payload.get("title") or ""))
        self.text_edit = QPlainTextEdit(str(payload.get("text") or ""))
        self.text_edit.setFixedHeight(150)
        self.image_edit = QLineEdit(str(payload.get("image") or ""))
        self.href_edit = QLineEdit(str(payload.get("href") or ""))
        self.label_edit = QLineEdit(str(payload.get("label") or payload.get("button_label") or ""))
        self.style_combo = QComboBox(); self.style_combo.setEditable(True); self.style_combo.addItems(["", "primary", "secondary", "ghost", "link"]); self.style_combo.setCurrentText(str(payload.get("style") or ""))
        self.work_id_edit = QLineEdit(str(payload.get("work_id") or ""))
        self.series_slug_edit = QLineEdit(str(payload.get("series_slug") or ""))
        tag_value = payload.get('tags')
        if isinstance(tag_value, list):
            tags_text = ', '.join(str(item).strip() for item in tag_value if str(item).strip())
        else:
            tags_text = str(tag_value or '')
        self.tags_edit = QLineEdit(tags_text)
        self.meta_edit = QPlainTextEdit(str(payload.get("meta") or payload.get("note") or "")); self.meta_edit.setFixedHeight(90)
        self.visible_check = QCheckBox("Visible")
        self.visible_check.setChecked(bool(payload.get("visible", True)))
        form.addRow("Eyebrow", self.eyebrow_edit)
        form.addRow("Title", self.title_edit)
        form.addRow("Body", self.text_edit)
        form.addRow("Image", self.image_edit)
        form.addRow("Href", self.href_edit)
        form.addRow("Button label", self.label_edit)
        form.addRow("Button style", self.style_combo)
        form.addRow("Work id", self.work_id_edit)
        form.addRow("Series slug", self.series_slug_edit)
        form.addRow("Tags", self.tags_edit)
        form.addRow("Meta / note", self.meta_edit)
        form.addRow("State", self.visible_check)
        layout.addLayout(form)
        self.extra_edit = QPlainTextEdit(json.dumps({k: v for k, v in payload.items() if k not in self.KNOWN_KEYS}, ensure_ascii=False, indent=2))
        self.extra_edit.setPlaceholderText('Advanced JSON fields preserved on save.')
        self.extra_edit.setFixedHeight(150)
        layout.addWidget(QLabel("Advanced JSON"))
        layout.addWidget(self.extra_edit)
        buttons = QHBoxLayout()
        format_btn = QPushButton("Format JSON")
        format_btn.clicked.connect(self._format_json)
        buttons.addWidget(format_btn)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

    def _extra_payload(self) -> dict[str, Any]:
        payload = json.loads(self.extra_edit.toPlainText().strip() or '{}')
        if not isinstance(payload, dict):
            raise ValueError('Advanced JSON must be an object.')
        return payload

    def _format_json(self) -> None:
        try:
            self.extra_edit.setPlainText(json.dumps(self._extra_payload(), ensure_ascii=False, indent=2, sort_keys=True))
        except Exception as exc:
            QMessageBox.critical(self, 'Invalid JSON', str(exc))

    def value(self) -> dict[str, Any]:
        payload = {k: v for k, v in self._initial.items() if k in self.KNOWN_KEYS}
        payload.update(self._extra_payload())
        payload["eyebrow"] = self.eyebrow_edit.text().strip()
        payload["title"] = self.title_edit.text().strip()
        payload["text"] = self.text_edit.toPlainText().strip()
        for key, value in {
            "image": self.image_edit.text().strip(),
            "href": self.href_edit.text().strip(),
            "label": self.label_edit.text().strip(),
            "work_id": self.work_id_edit.text().strip(),
            "series_slug": self.series_slug_edit.text().strip(),
        }.items():
            if value:
                payload[key] = value
            else:
                payload.pop(key, None)
        style = self.style_combo.currentText().strip()
        if style:
            payload["style"] = style
        else:
            payload.pop("style", None)
        tags = [item.strip() for item in self.tags_edit.text().split(',') if item.strip()]
        if tags:
            payload["tags"] = tags
        else:
            payload.pop("tags", None)
        meta = self.meta_edit.toPlainText().strip()
        if meta:
            payload["meta"] = meta
        else:
            payload.pop("meta", None)
        payload["visible"] = bool(self.visible_check.isChecked())
        return payload


class NavigationItemDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, initial: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Navigation item')
        self.resize(480, 260)
        payload = dict(initial or {})
        layout = QFormLayout(self)
        self.label_edit = QLineEdit(str(payload.get('label') or ''))
        self.href_edit = QLineEdit(str(payload.get('href') or ''))
        self.page_edit = QLineEdit(str(payload.get('page') or ''))
        self.visible_check = QCheckBox('Visible')
        self.visible_check.setChecked(bool(payload.get('visible', True)))
        layout.addRow('Label', self.label_edit)
        layout.addRow('Href', self.href_edit)
        layout.addRow('Page key', self.page_edit)
        layout.addRow('State', self.visible_check)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def value(self) -> dict[str, Any]:
        return {
            'label': self.label_edit.text().strip(),
            'href': self.href_edit.text().strip(),
            'page': self.page_edit.text().strip(),
            'visible': bool(self.visible_check.isChecked()),
        }


class ResourceItemDialog(QDialog):
    KNOWN_KEYS = {"id", "title", "description", "file", "kind", "audience", "featured", "public", "label", "eyebrow", "note", "visible"}

    def __init__(self, parent: QWidget | None = None, initial: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Resource document')
        self.resize(700, 540)
        payload = dict(initial or {})
        self._initial = dict(payload)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.id_edit = QLineEdit(str(payload.get('id') or ''))
        self.title_edit = QLineEdit(str(payload.get('title') or ''))
        self.description_edit = QPlainTextEdit(str(payload.get('description') or '')); self.description_edit.setFixedHeight(110)
        file_row = QWidget(); file_layout = QHBoxLayout(file_row); file_layout.setContentsMargins(0, 0, 0, 0)
        self.file_edit = QLineEdit(str(payload.get('file') or ''))
        browse_btn = QPushButton('Browse…')
        browse_btn.clicked.connect(self._browse_file)
        file_layout.addWidget(self.file_edit, 1)
        file_layout.addWidget(browse_btn)
        self.kind_edit = QLineEdit(str(payload.get('kind') or ''))
        self.audience_edit = QLineEdit(str(payload.get('audience') or 'public'))
        self.label_edit = QLineEdit(str(payload.get('label') or ''))
        self.eyebrow_edit = QLineEdit(str(payload.get('eyebrow') or ''))
        self.note_edit = QPlainTextEdit(str(payload.get('note') or '')); self.note_edit.setFixedHeight(90)
        self.featured_check = QCheckBox('Featured'); self.featured_check.setChecked(bool(payload.get('featured', False)))
        self.public_check = QCheckBox('Public'); self.public_check.setChecked(bool(payload.get('public', payload.get('audience', 'public') == 'public')))
        self.visible_check = QCheckBox('Visible'); self.visible_check.setChecked(bool(payload.get('visible', True)))
        form.addRow('ID', self.id_edit)
        form.addRow('Title', self.title_edit)
        form.addRow('Description', self.description_edit)
        form.addRow('File', file_row)
        form.addRow('Kind', self.kind_edit)
        form.addRow('Audience', self.audience_edit)
        form.addRow('Label', self.label_edit)
        form.addRow('Eyebrow', self.eyebrow_edit)
        form.addRow('Note', self.note_edit)
        flags = QWidget(); flags_layout = QHBoxLayout(flags); flags_layout.setContentsMargins(0,0,0,0); flags_layout.addWidget(self.featured_check); flags_layout.addWidget(self.public_check); flags_layout.addWidget(self.visible_check); flags_layout.addStretch(1)
        form.addRow('Flags', flags)
        layout.addLayout(form)
        self.extra_edit = QPlainTextEdit(json.dumps({k: v for k, v in payload.items() if k not in self.KNOWN_KEYS}, ensure_ascii=False, indent=2))
        self.extra_edit.setFixedHeight(120)
        layout.addWidget(QLabel('Advanced JSON'))
        layout.addWidget(self.extra_edit)
        buttons = QHBoxLayout()
        format_btn = QPushButton('Format JSON')
        format_btn.clicked.connect(self._format_json)
        buttons.addWidget(format_btn)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, 'Choose document', str(ROOT), 'Documents (*.pdf *.doc *.docx *.txt *.rtf);;All files (*)')
        if path:
            self.file_edit.setText(path)

    def _extra_payload(self) -> dict[str, Any]:
        payload = json.loads(self.extra_edit.toPlainText().strip() or '{}')
        if not isinstance(payload, dict):
            raise ValueError('Advanced JSON must be an object.')
        return payload

    def _format_json(self) -> None:
        try:
            self.extra_edit.setPlainText(json.dumps(self._extra_payload(), ensure_ascii=False, indent=2, sort_keys=True))
        except Exception as exc:
            QMessageBox.critical(self, 'Invalid JSON', str(exc))

    def value(self) -> dict[str, Any]:
        payload = {k: v for k, v in self._initial.items() if k in self.KNOWN_KEYS}
        payload.update(self._extra_payload())
        payload['id'] = self.id_edit.text().strip()
        payload['title'] = self.title_edit.text().strip()
        payload['description'] = self.description_edit.toPlainText().strip()
        payload['file'] = self.file_edit.text().strip()
        payload['kind'] = self.kind_edit.text().strip()
        payload['audience'] = self.audience_edit.text().strip() or 'public'
        payload['featured'] = bool(self.featured_check.isChecked())
        payload['public'] = bool(self.public_check.isChecked())
        payload['visible'] = bool(self.visible_check.isChecked())
        label = self.label_edit.text().strip()
        if label:
            payload['label'] = label
        else:
            payload.pop('label', None)
        eyebrow = self.eyebrow_edit.text().strip()
        if eyebrow:
            payload['eyebrow'] = eyebrow
        else:
            payload.pop('eyebrow', None)
        note = self.note_edit.toPlainText().strip()
        if note:
            payload['note'] = note
        else:
            payload.pop('note', None)
        return payload



class ControlPanelWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("STILLMRK Control Panel · Qt")
        screen = QApplication.primaryScreen().availableGeometry() if QApplication.primaryScreen() else None
        if screen is not None:
            self.resize(max(1060, int(screen.width() * 0.85)), max(700, int(screen.height() * 0.88)))
        else:
            self.resize(1280, 800)
        self.setMinimumSize(1060, 700)
        self._safe_mode = any(arg in sys.argv for arg in ("--safe-mode", "--safe"))
        # Phase 22: startup guard now runs asynchronously after the frame is visible.
        self._startup_guard_report: dict[str, Any] = {}
        self._startup_guard_inflight = False
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(max(2, min(4, self.thread_pool.maxThreadCount())))
        self.io_thread_pool = QThreadPool(self)
        self.io_thread_pool.setMaxThreadCount(2)
        self._active_workers: list[FunctionWorker] = []
        self._active_task_context: TaskContext | None = None
        self._thumbnail_batch_token = ThumbnailBatchToken()
        self._works_model = WorksTableModel()
        self._works_model_view_enabled = False
        self._visible_work_payloads_by_id: dict[str, dict[str, Any]] = {}
        self._visible_work_id_order: list[str] = []
        self._gallery_cards_by_work_id: dict[str, WorkGalleryCard] = {}
        self._gallery_thumbnail_queue: deque[tuple[str, str, str, QSize, int]] = deque()
        self._gallery_thumbnail_loading: set[str] = set()
        # Keep QRunnable thumbnail loaders strongly referenced until their
        # signal is handled. Without this, PySide can lose the Python wrapper
        # for longer queues and many cards remain stuck on "Loading preview…".
        self._gallery_thumbnail_workers: dict[str, ThumbnailLoader] = {}
        self._gallery_thumbnail_started_at: dict[str, float] = {}
        self._gallery_thumbnail_last_progress = time.monotonic()
        self._gallery_thumbnail_max_concurrent = 2
        self._work_gallery_initial_limit = 50
        self._gallery_thumbnail_generation = 0
        # Hotfix 2026-04-27: keep Works image cards stable during resize/refresh.
        # The previous implementation rebuilt the entire gallery directly inside
        # the scroll area's resizeEvent, which caused flicker, repeated thumbnail
        # cancellation, and visible card jumping while the viewport settled.
        self._gallery_last_layout_signature: tuple[Any, ...] | None = None
        self._gallery_last_columns = 0
        self._gallery_reflow_timer = QTimer(self)
        self._gallery_reflow_timer.setSingleShot(True)
        self._gallery_reflow_timer.setInterval(140)
        self._gallery_reflow_timer.timeout.connect(self._reflow_work_gallery_after_resize)
        self._gallery_thumbnail_watchdog_timer = QTimer(self)
        self._gallery_thumbnail_watchdog_timer.setInterval(1200)
        self._gallery_thumbnail_watchdog_timer.timeout.connect(self._gallery_thumbnail_watchdog_tick)
        self._gallery_thumbnail_watchdog_timer.start()
        self._closing = False
        self._tab_switch_guard = False
        raw_state = load_ui_state()
        self.state, self._ui_state_report = normalise_control_panel_state(raw_state, layout_version=LAYOUT_POLISH_VERSION)
        self._running_tasks = 0
        self._task_queue: list[tuple[str, Callable[..., Any], Callable[[Any], None] | None]] = []
        self._active_task_label = ""
        self._dismissed_action_labels: set[str] = set()
        self._default_work_filter_presets = default_work_filter_presets()
        self._custom_work_filter_presets: dict[str, dict[str, str]] = dict(self.state.get("custom_work_filter_presets") or {})
        self._active_work_filter_preset_name: str = str(self.state.get("active_work_filter_preset") or "All works")
        self._pending_work_filter_snapshot: dict[str, str] | None = self.state.get("work_filters") if isinstance(self.state.get("work_filters"), dict) else None
        self._applying_work_filter_preset = False
        self._current_work_id: str | None = None
        self._current_series_slug: str | None = None
        self._current_page_key: str | None = None
        self._current_authority_key: str | None = None
        self._suspend_work_form = False
        self._suspend_series_form = False
        self._loaded_work_snapshot: dict[str, Any] | None = None
        self._current_work_image_block: dict[str, Any] = {}
        self._last_work_save_ms: float = 0.0
        self._work_save_refresh_policy: str = "local-patch"
        self._work_save_state: str = "clean"
        self._work_save_request_id: int = 0
        self._loaded_series_snapshot: dict[str, Any] | None = None
        self._loaded_page_text: str = ""
        self._page_builder_model: dict[str, Any] | None = None
        self._page_builder_loaded_model: dict[str, Any] | None = None
        self._page_raw_override = False
        self._suspend_page_builder_form = False
        self._suspend_page_raw_sync = False
        self._current_page_section_index: int = -1
        self._loaded_authority_text: str = ""
        self._authority_model: dict[str, Any] | None = None
        self._authority_loaded_model: dict[str, Any] | None = None
        self._suspend_authority_form = False
        self._suspend_authority_raw_sync = False
        self._last_tab_index: int = 0
        self._last_page_builder_tab_index: int = 0
        self._draft_restore_seen: set[tuple[str, str]] = set()
        self._draft_prompt_active = False
        self._work_icon_cache = LRUIconCache(max_entries=200)
        self._work_preview_pixmap_cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._work_preview_pixmap_cache_limit = 200
        # Batch E: keep preview repaint ownership explicit. These signatures
        # stop background/status refreshes from repainting the same image every
        # timer tick, which is what users experience as preview blinking.
        self._work_main_preview_signature: tuple[Any, ...] | None = None
        self._work_side_preview_signature: tuple[Any, ...] | None = None
        self._last_draft_hash: dict[tuple[str, str], str] = {}
        self._last_global_search_total = 0
        self._cached_dashboard_action_count = 0
        self._cached_work_issue_count = 0
        self._cached_series_count = 0
        self._cached_pages_count = 0
        self._cached_validation_count = 0
        self._dashboard_refresh_inflight = False
        self._dashboard_refresh_pending = False
        self._dashboard_refresh_started = 0.0
        self._dashboard_deep_refresh_inflight = False
        self._dashboard_deep_refresh_started = 0.0
        self._last_dashboard_release_rows: list[dict[str, Any]] = []
        self._studio_dirty = True
        self._publish_dirty = True
        self._relationships_dirty = False
        self._tab_built: set[int] = set()
        self._dirty_tabs: dict[str, float] = {}
        self._last_scope_refresh_at: dict[str, float] = {}
        self._refresh_coordinator = RefreshCoordinator()
        self._tab_specs: list[dict[str, Any]] = []
        self._qss_cache: dict[tuple[str, bool], str] = {}
        self._last_applied_qss_key: tuple[str, bool] | None = None
        self._studio_data_cache: dict[str, Any] | None = None
        self._studio_last_refreshed_at: datetime | None = None
        self.relationships_tab: QWidget | None = None
        self.authority_tab: QWidget | None = None
        self.validation_tab: QWidget | None = None
        self._relationships_dialog: QDialog | None = None
        self._loading_overlays: dict[QWidget, QFrame] = {}
        self._studio_refresh_inflight = False
        self._validation_refresh_inflight = False
        self._publish_source_refresh_inflight = False
        self._build_trigger_widgets: list[QPushButton] = []
        self._build_trigger_actions: list[QAction] = []
        self._public_upload_snapshot: dict[str, tuple[int, int]] = {}
        self._last_public_upload_diff: dict[str, list[str]] = {"changed": [], "removed": []}
        self._last_build_time: datetime | None = None
        self._last_build_status: str = "No build yet"
        self._publish_check_passed: bool = False
        self._last_publish_archive: str = ""
        self._active_task_started_at: float | None = None
        self._reduced_motion = bool(self.state.get("reduced_motion", False))
        self._layout_profile = str(self.state.get("layout_profile") or "Wide")
        self._primary_nav_keys: set[str] = {"dashboard", "works", "series", "pages", "publish"}
        self._last_save_time: datetime | None = None
        self._last_save_diff_lines: list[str] = []
        self._startup_preflight_report: dict[str, Any] | None = None
        self._context_refresh_inflight = False
        self._context_refresh_pending = False
        self._pending_work_change_preview: dict[str, Any] = {}
        self._gallery_mode = True
        self._perf_events: list[tuple[str, float, str]] = []
        self._build_log_buffer: list[str] = []
        self._task_animation_step = 0
        self._nav_switch_guard = False
        self._recent_command_keys: list[str] = [str(k) for k in (self.state.get("recent_commands") or [])][:5]
        self._recent_tab_indices: list[int] = [int(i) for i in (self.state.get("recent_tab_indices") or []) if isinstance(i, int) or str(i).isdigit()][:3]
        self._last_work_autosave_at: float | None = None
        self._last_series_autosave_at: float | None = None
        self._last_page_autosave_at: float | None = None
        self._last_authority_autosave_at: float | None = None
        # Fixed control-panel density: the visible density selector was removed to reduce layout complexity.
        self._density_mode = FIXED_CONTROL_PANEL_DENSITY
        self._startup_started_at = time.perf_counter()
        self._task_history: list[dict[str, Any]] = []
        self._task_cancel_requested = False
        self._task_animation_timer = QTimer(self)
        self._task_animation_timer.setInterval(400)
        self._task_animation_timer.timeout.connect(self._tick_task_activity)
        self._timer_bus = TimerBus(self, tick_ms=1000)
        self._timer_bus.register("dashboard-live-status", self.refresh_dashboard_live_status, 15000)
        self._build_log_flush_timer = QTimer(self)
        self._build_log_flush_timer.setSingleShot(True)
        self._build_log_flush_timer.setInterval(1500)
        self._build_log_flush_timer.timeout.connect(self._flush_build_log_buffer)
        self._work_filter_refresh_timer = QTimer(self)
        self._work_filter_refresh_timer.setSingleShot(True)
        self._work_filter_refresh_timer.setInterval(250)
        self._work_filter_refresh_timer.timeout.connect(self._apply_work_filter_refresh)
        self._work_list_debounce = QTimer(self)
        self._work_list_debounce.setSingleShot(True)
        self._work_list_debounce.setInterval(150)
        self._work_list_debounce.timeout.connect(self._refresh_work_list_now)
        self._pending_work_list_refresh_reason = ""
        self._state_save_timer = QTimer(self)
        self._state_save_timer.setSingleShot(True)
        self._state_save_timer.setInterval(2000)
        self._state_save_timer.timeout.connect(self.save_window_state)
        self._work_validation_timer = QTimer(self)
        self._work_validation_timer.setSingleShot(True)
        self._work_validation_timer.setInterval(280)
        self._work_validation_timer.timeout.connect(self._validate_work_form)
        self._work_preview_timer = QTimer(self)
        self._work_preview_timer.setSingleShot(True)
        self._work_preview_timer.setInterval(220)
        self._work_preview_timer.timeout.connect(self.update_work_preview)
        self._work_thumbnail_timer = QTimer(self)
        self._work_thumbnail_timer.setSingleShot(True)
        self._work_thumbnail_timer.setInterval(120)
        self._work_thumbnail_timer.timeout.connect(self._trigger_visible_thumbnail_load)
        self._work_asset_health_timer = QTimer(self)
        self._work_asset_health_timer.setSingleShot(True)
        self._work_asset_health_timer.setInterval(650)
        self._work_asset_health_timer.timeout.connect(self._start_visible_work_asset_health_check)
        self._work_asset_health_token = 0
        self._work_asset_health_inflight = False
        self._work_asset_health_cache: dict[str, dict[str, Any]] = {}
        self._work_asset_health_batch_limit = 24
        self._release_artifact_refresh_inflight = False
        self._release_artifact_cache: list[dict[str, Any]] = []
        self._publish_source_cache: dict[str, Any] | None = None
        self._keyed_background_tasks: dict[str, tuple[TaskContext, FunctionWorker]] = {}
        self.last_workbook_analysis: dict[str, Any] | None = None
        self._workbook_path: str = str(self.state.get("workbook_path") or "")
        self._notifications: list[dict[str, Any]] = list(self.state.get("notifications") or [])
        self._autosave_dirty_kinds: set[str] = set()
        self._autosave_due_at: dict[str, float] = {}
        self._timer_bus.register("autosave-coordinator", self._autosave_coordinator, 500)
        self._timer_bus.register("autosave-status", self._update_autosave_labels, 10000)
        self._timer_bus.register("command-usage-flush", flush_command_usage, 30000)
        self.command_map: dict[str, tuple[str, Callable[[], None], str]] = {}
        self.command_shortcuts: dict[str, str] = {}
        # Batch D: canonical action registry for auditing toolbar/menu/shortcut bindings.
        self.action_registry: dict[str, dict[str, Any]] = {}
        self._build_ui()
        self.state, tab_report = normalise_control_panel_state(
            self.state,
            layout_version=LAYOUT_POLISH_VERSION,
            max_tab_index=max(0, self.tabs.count() - 1),
        )
        if tab_report.warnings:
            combined_warnings = tuple(getattr(self._ui_state_report, "warnings", ()) or ()) + tuple(tab_report.warnings)
            self._ui_state_report = StateSanityReport(ok=True, migrated=True, warnings=combined_warnings)
            self._notifications = list(self.state.get("notifications") or [])[:MAX_SAVED_NOTIFICATIONS]
        self.apply_theme()
        self.apply_density_layout()
        self.install_accessibility_shortcuts()
        self.restore_state()
        if self._safe_mode:
            self.push_notification("warning", "Safe mode enabled", "Heavy review/publish refresh is deferred. Use Refresh all when ready.", target_scope="dashboard")
        self._record_perf("startup-frame", time.perf_counter() - self._startup_started_at, "lazy startup frame")

    # ---------- shell ----------
    def _build_ui(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setObjectName("mainCommandBar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setFixedHeight(52)
        toolbar.setMinimumHeight(52)
        toolbar.setIconSize(QSize(16, 16))
        self.main_toolbar = toolbar
        self.addToolBar(toolbar)

        self.add_toolbar_button(toolbar, "Save", self.save_current_tab)
        self.add_toolbar_button(toolbar, "Add image", self.open_add_image_dialog, "Ctrl+N")
        build_action = self.add_toolbar_button(toolbar, "Build site", self.run_build_site)
        self._build_trigger_actions.append(build_action)
        self.add_toolbar_button(toolbar, "Open preview", self.open_preview)
        self.add_toolbar_button(toolbar, "Search", self.open_global_search, "Ctrl+P")

        more_menu = QMenu(self)

        def add_more(label: str, slot: Callable[[], None], shortcut: str | None = None) -> QAction:
            action = QAction(label, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.setToolTip(self._tooltip_for_label(label))
            action.triggered.connect(slot)
            more_menu.addAction(action)
            return action

        add_more("Refresh all", self.refresh_all_context, "Ctrl+R")
        add_more("Prepare publish", self.run_prepare_publish)
        add_more("Readiness report", self.open_readiness_report)
        add_more("Source recovery", self.open_source_recovery_dialog)
        self.cancel_task_action = add_more("Cancel active task", self.cancel_current_task)
        self.cancel_task_action.setEnabled(False)
        add_more("Task monitor", self.open_task_monitor)
        add_more("Command palette", self.open_command_palette, "Ctrl+K")
        add_more("Toggle context inspector", self.toggle_context_inspector, "Ctrl+I")
        more_menu.addSeparator()
        add_more("Run GUI smoke test", lambda: self.run_gui_smoke_test(interactive=True))
        add_more("Help & Shortcuts", self.show_shortcuts)
        self.main_more_button = QPushButton("More ▾")
        self.main_more_button.setObjectName("moreCommandButton")
        self.main_more_button.setMenu(more_menu)
        self.main_more_button.setToolTip("Secondary tools are grouped here to keep the main command bar calm.")
        toolbar.addWidget(self.main_more_button)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 6, 10, 8)
        root.setSpacing(7)

        header = QHBoxLayout()
        title_wrap = QVBoxLayout()
        title = QLabel("STILLMRK Control Panel")
        title.setObjectName("appTitle")
        subtitle = QLabel("Premium local review console · public website output stays untouched")
        subtitle.setObjectName("appSubTitle")
        title_wrap.addWidget(title)
        title_wrap.addWidget(subtitle)
        header.addLayout(title_wrap)
        header.addStretch(1)
        self.notification_button = QPushButton("🔔 Notifications")
        self.notification_button.clicked.connect(self.open_notification_center)
        header.addWidget(self.notification_button)
        self.task_label = StatusBadge("Idle", "ok")
        self.task_label.setObjectName("taskBadge")
        header.addWidget(self.task_label)
        self.cancel_task_button = QPushButton("Cancel")
        self.cancel_task_button.setObjectName("cancelTaskButton")
        self.cancel_task_button.setToolTip("Request cancellation for the active control-panel task and clear queued follow-up tasks. Safe checkpoints decide when the running task stops.")
        self.cancel_task_button.clicked.connect(self.cancel_current_task)
        self.cancel_task_button.setEnabled(False)
        self.cancel_task_button.hide()
        header.addWidget(self.cancel_task_button)
        self.layout_profile_label = StatusBadge("Wide", "info")
        self.layout_profile_label.setObjectName("layoutProfileBadge")
        self.layout_profile_label.setToolTip("Adaptive control-panel layout profile. This changes the panel chrome only; website output is untouched.")
        header.addWidget(self.layout_profile_label)
        if self._safe_mode:
            self.safe_mode_badge = StatusBadge("Safe mode", "warning")
            self.safe_mode_badge.setToolTip("Heavy Studio/Publish refresh is deferred for recovery launches.")
            header.addWidget(self.safe_mode_badge)
        root.addLayout(header)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("control-panel-main-splitter")
        nav_shell = QFrame()
        nav_shell.setObjectName("sideNavShell")
        nav_shell.setMinimumWidth(190)
        nav_shell.setMaximumWidth(252)
        nav_shell_layout = QVBoxLayout(nav_shell)
        nav_shell_layout.setContentsMargins(0, 0, 0, 0)
        nav_shell_layout.setSpacing(8)
        self.command_search_entry = QLineEdit()
        self.command_search_entry.setObjectName("commandPaletteSearchBar")
        self.command_search_entry.setPlaceholderText("Search works, series, commands… ⌘K")
        self.command_search_entry.setReadOnly(True)
        self.command_search_entry.setCursor(Qt.CursorShape.PointingHandCursor)
        self.command_search_entry.setAccessibleName("Open command palette")
        self.command_search_entry.setToolTip("Open the command palette. Type a work, series, page, or command name.")
        self.command_search_entry.mousePressEvent = lambda event: (self.open_command_palette(), event.accept())
        nav_shell_layout.addWidget(self.command_search_entry)
        self.side_nav = QListWidget()
        self.side_nav.setObjectName("sideNav")
        self.side_nav.setItemDelegate(SideNavDelegate(self.side_nav))
        self.side_nav.setMinimumWidth(180)
        self.side_nav.setMaximumWidth(240)
        self.side_nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.side_nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.side_nav.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.side_nav.setAlternatingRowColors(False)
        self.side_nav.setAccessibleName("Primary control-panel navigation")
        self.side_nav.setToolTip("Primary workflows: Dashboard, Works, Series, Pages, and Publish. Advanced tools stay available from the command palette.")
        self.side_nav.setProperty("reducedMotion", self._reduced_motion)
        self.side_nav.currentRowChanged.connect(self._side_nav_changed)
        nav_shell_layout.addWidget(self.side_nav, 1)
        self.main_splitter.addWidget(nav_shell)

        # Phase 16: top-level navigation is a side-nav-driven QStackedWidget,
        # not a visible QTabWidget. NavStackedWidget keeps the legacy API
        # surface so tab builders and shortcuts remain compatible.
        self.tabs = NavStackedWidget()
        self.tabs.setObjectName("primaryNavStack")
        self.main_splitter.addWidget(self.tabs)

        self.context_inspector = self._build_context_inspector()
        self.context_inspector.setVisible(False)
        self.main_splitter.addWidget(self.context_inspector)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([210, 980, 0])
        root.addWidget(self.main_splitter, 1)

        # Phase 11 controller registry: the shell owns navigation/task chrome;
        # content-tab state and tab-scoped signals live in controllers. The legacy
        # builders are still delegated safely while handlers migrate in smaller passes.
        self.tab_controllers = {
            "works": WorksTabController(self),
            "series": SeriesTabController(self),
            "pages": PagesTabController(self),
        }
        for controller in self.tab_controllers.values():
            controller.refreshRequested.connect(lambda key, force=False: self._refresh_scope_now(str(key)))
            controller.selectRequested.connect(self._handle_tab_controller_select)
            controller.saveRequested.connect(self._handle_tab_controller_save)
        self._tab_boundaries = {
            "dashboard": DashboardTabBoundary(self),
            "works": self.tab_controllers["works"],
            "series": self.tab_controllers["series"],
            "pages": self.tab_controllers["pages"],
            "publish": PublishTabBoundary(self),
        }
        self._tab_specs = build_compatibility_specs(self, self._tab_boundaries)
        # Studio is intentionally kept as a legacy tab for now; it shares publish/asset
        # workflows and should be extracted after the high-risk Works/Publish split.
        self._tab_specs.insert(4, {"key": "studio", "label": "Studio", "attr": "studio_tab", "builder": self.build_studio_tab, "owner_module": "control_panel.py", "extraction_state": "legacy-shared"})
        self.dashboard_tab = self._tab_boundaries["dashboard"].build()
        self._attach_tab_refresh_footer(self.dashboard_tab, "dashboard")
        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        self._tab_built.add(0)
        for spec in self._tab_specs[1:]:
            placeholder = self._make_tab_placeholder(str(spec["label"]))
            setattr(self, str(spec["attr"]), placeholder)
            self.tabs.addTab(placeholder, str(spec["label"]))
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.configure_side_navigation()
        self._apply_layout_rescue_defaults()

        self.setCentralWidget(central)
        status = QStatusBar()
        self.setStatusBar(status)
        self.progress_hint = QLabel("")
        status.addPermanentWidget(self.progress_hint)
        self.session_health_label = QLabel("Last build: never · Clean")
        status.addPermanentWidget(self.session_health_label)
        self.status_message("Ready")
        self.update_notification_badge()
        self.bind_shortcuts()
        self.register_commands()
        self.apply_button_tooltips()
        self._update_session_health()
        self._load_persisted_build_log()
        self._consume_backend_warnings()
        if getattr(self, "_ui_state_report", None) is not None and self._ui_state_report.warnings:
            for warning in self._ui_state_report.warnings:
                self._log_warning(f"UI state migration: {warning}")
        QTimer.singleShot(50, self._run_startup_guard_async)
        QTimer.singleShot(100, self._first_load)

    def _make_tab_placeholder(self, label: str) -> QWidget:
        placeholder = QWidget()
        placeholder.setObjectName("lazyTabPlaceholder")
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addStretch(1)
        message = QLabel(f"Loading {label}…")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setObjectName("quietHint")
        layout.addWidget(message)
        layout.addStretch(1)
        return placeholder

    def _make_tab_error_widget(self, label: str, exc: Exception, traceback_text: str, retry_index: int) -> QWidget:
        widget = QWidget()
        widget.setObjectName("tabErrorState")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.addStretch(1)
        title = QLabel(f"{label} could not be opened")
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        detail = QLabel(str(exc) or "Unknown control-panel error")
        detail.setObjectName("emptyDetail")
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        layout.addWidget(detail)
        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setMaximumHeight(220)
        body.setPlainText(traceback_text.strip() or repr(exc))
        layout.addWidget(body)
        actions = QHBoxLayout()
        actions.addStretch(1)
        retry_btn = QPushButton("Retry tab")
        retry_btn.setObjectName("primaryAction")
        retry_btn.clicked.connect(lambda _checked=False, idx=retry_index: self._ensure_tab_built(idx))
        copy_btn = QPushButton("Copy diagnostic")
        copy_btn.clicked.connect(lambda _checked=False, text=body.toPlainText(): QApplication.clipboard().setText(text))
        actions.addWidget(retry_btn)
        actions.addWidget(copy_btn)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return widget

    def _first_load(self) -> None:
        """Phase 22 lazy startup: paint the shell first, then load only Dashboard."""
        if getattr(self, "_first_load_started", False):
            return
        self._first_load_started = True
        self._ensure_tab_built_by_key("dashboard")
        self.refresh_dashboard()
        self._record_perf("first dashboard load scheduled", time.perf_counter() - self._startup_started_at, "lazy dashboard-only startup")

    def _collect_startup_preflight_async(self) -> dict[str, Any]:
        guard: dict[str, Any] = {}
        try:
            guard = run_startup_guard(ROOT)
        except Exception as exc:
            guard = {"ok": False, "errors": 1, "warnings": 0, "rows": [{"status": "error", "check": "startup guard", "detail": str(exc)}]}
        try:
            report = startup_preflight_checks(fast=bool(getattr(self, "_safe_mode", False)))
        except Exception as exc:
            report = {"ok": False, "errors": 1, "warnings": 0, "rows": [{"status": "error", "check": "startup preflight", "detail": str(exc)}]}
        rows = list(guard.get("rows") or []) + list((report or {}).get("rows") or [])
        errors = sum(1 for row in rows if row.get("status") == "error")
        warnings = sum(1 for row in rows if row.get("status") == "warning")
        return {"guard": guard, "report": {**dict(report or {}), "rows": rows, "errors": errors, "warnings": warnings, "ok": errors == 0}}

    def _run_startup_guard_async(self) -> None:
        """Run startup guard/preflight off the UI thread so the window appears immediately."""
        if getattr(self, "_startup_guard_inflight", False):
            return
        self._startup_guard_inflight = True
        worker = FunctionWorker(self._collect_startup_preflight_async)
        self._active_workers.append(worker)
        worker.signals.result.connect(lambda data: self._apply_startup_preflight_async(data) if self._is_window_alive() else None)
        worker.signals.error.connect(lambda detail: self._log_warning(f"Startup guard failed: {detail}") if self._is_window_alive() else None)
        worker.signals.finished.connect(lambda w=worker: self._startup_guard_worker_finished(w) if self._is_window_alive() else self._forget_worker(w))
        self.io_thread_pool.start(worker)

    def _startup_guard_worker_finished(self, worker: FunctionWorker) -> None:
        self._startup_guard_inflight = False
        self._forget_worker(worker)

    def _apply_startup_preflight_async(self, data: dict[str, Any]) -> None:
        assert_gui_thread("startup preflight UI apply")
        guard = dict((data or {}).get("guard") or {})
        report = dict((data or {}).get("report") or {})
        self._startup_guard_report = guard
        self._startup_preflight_report = report
        if int(guard.get("errors") or 0):
            self._safe_mode = True
        rows = list(report.get("rows") or [])
        errors = int(report.get("errors") or 0)
        warnings = int(report.get("warnings") or 0)
        if errors or warnings:
            detail = f"{errors} error(s), {warnings} warning(s). Open Notifications or Publish Ops for context."
            self.push_notification("error" if errors else "warning", "Startup health check needs attention", detail, target_scope="publish")
            if hasattr(self, "build_log"):
                self.append_build_log_line("Startup health check:")
                for row in rows:
                    if row.get("status") != "ok":
                        self.append_build_log_line(f"⚠ {row.get('check')}: {row.get('detail')}")
        else:
            self.push_notification("success", "Startup health check passed", f"{len(rows)} checks completed.", target_scope="dashboard")
        self._update_session_health()


    def _tab_key_for_index(self, index: int) -> str:
        if 0 <= index < len(getattr(self, "_tab_specs", [])):
            return str(self._tab_specs[index].get("key") or "")
        return ""

    def _tab_index_for_key(self, key: str) -> int:
        key = str(key or "")
        for index, spec in enumerate(getattr(self, "_tab_specs", [])):
            if str(spec.get("key") or "") == key:
                return index
        return -1

    def _ensure_tab_built(self, index: int) -> QWidget | None:
        if not hasattr(self, "tabs") or not (0 <= index < self.tabs.count()):
            return None
        if index in getattr(self, "_tab_built", set()):
            return self.tabs.widget(index)
        specs = getattr(self, "_tab_specs", [])
        if not (0 <= index < len(specs)):
            return self.tabs.widget(index)
        spec = specs[index]
        label = str(spec.get("label") or self.tabs.tabText(index))
        builder = spec.get("builder")
        attr = str(spec.get("attr") or "")
        old_widget = self.tabs.widget(index)
        try:
            self.status_message(f"Loading {label}…")
            new_widget = builder() if callable(builder) else old_widget
        except Exception as exc:
            traceback_text = traceback.format_exc(limit=16)
            self._log_warning(f"Could not build {label}: {exc}")
            error_widget = self._make_tab_error_widget(label, exc, traceback_text, index)
            with signals_blocked(self.tabs):
                self.tabs.removeTab(index)
                self.tabs.insertTab(index, error_widget, label)
                self.tabs.setCurrentIndex(index)
            if old_widget is not None and old_widget is not error_widget:
                old_widget.deleteLater()
            return error_widget
        if new_widget is None:
            return old_widget
        self._attach_tab_refresh_footer(new_widget, str(spec.get("key") or ""))
        with signals_blocked(self.tabs):
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, new_widget, label)
            self.tabs.setCurrentIndex(index)
        if attr:
            setattr(self, attr, new_widget)
        self._tab_built.add(index)
        if old_widget is not None and old_widget is not new_widget:
            old_widget.deleteLater()
        self.apply_density_layout()
        self.apply_button_tooltips(new_widget)
        self._apply_layout_rescue_defaults()
        self.configure_side_navigation()
        return new_widget

    def _ensure_tab_built_by_key(self, key: str) -> QWidget | None:
        return self._ensure_tab_built(self._tab_index_for_key(key))

    def _handle_tab_controller_select(self, tab_key: str, item_key: str) -> None:
        tab_key = str(tab_key or "")
        item_key = str(item_key or "")
        if tab_key == "works":
            self._ensure_tab_built_by_key("works")
            if hasattr(self, "works_tab"):
                self.tabs.setCurrentWidget(self.works_tab)
            self.select_work(item_key)
        elif tab_key == "series":
            self._ensure_tab_built_by_key("series")
            if hasattr(self, "series_tab"):
                self.tabs.setCurrentWidget(self.series_tab)
            self.select_series(item_key)
        elif tab_key == "pages":
            self._ensure_tab_built_by_key("pages")
            if hasattr(self, "pages_tab"):
                self.tabs.setCurrentWidget(self.pages_tab)
            self.select_page(item_key)

    def _handle_tab_controller_save(self, tab_key: str) -> None:
        tab_key = str(tab_key or "")
        if tab_key == "works":
            self.save_current_work()
        elif tab_key == "series":
            self.save_current_series()
        elif tab_key == "pages":
            self.save_current_page()

    def _attach_tab_refresh_footer(self, tab_widget: QWidget | None, key: str) -> None:
        if tab_widget is None or not key or bool(tab_widget.property("hasRefreshFooter")):
            return
        layout = tab_widget.layout()
        if layout is None:
            return
        try:
            footer = QHBoxLayout()
            footer.setContentsMargins(0, 8, 0, 0)
            label = QLabel("Last refreshed: not yet")
            label.setObjectName("lastRefreshedLabel")
            setattr(self, f"{key}_last_refreshed_label", label)
            footer.addWidget(label)
            footer.addStretch(1)
            button = QPushButton("Refresh this tab")
            button.setObjectName("secondaryActionButton")
            button.setToolTip("Reload only this visible control-panel tab.")
            button.clicked.connect(lambda _checked=False, tab_key=str(key): self._refresh_scope_now(tab_key))
            footer.addWidget(button)
            layout.addLayout(footer)
            tab_widget.setProperty("hasRefreshFooter", True)
        except Exception as exc:
            self._log_warning(f"Could not add refresh footer for {key}: {exc}")

    def _current_tab_key(self) -> str:
        return self._tab_key_for_index(self.tabs.currentIndex()) if hasattr(self, "tabs") else ""

    def _canonical_action_key(self, label: str) -> str:
        return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(label or "")).strip("_") or "action"

    def _register_action_binding(self, key: str, label: str, handler: Callable[..., Any], *, shortcut: str | None = None, source: str = "ui", enabled_condition: Callable[[], bool] | None = None) -> None:
        registry = getattr(self, "action_registry", {})
        registry[str(key or self._canonical_action_key(label))] = {"label": str(label or key), "handler": handler, "shortcut": str(shortcut or ""), "source": str(source or "ui"), "enabled_condition": enabled_condition, "last_error": ""}
        self.action_registry = registry

    def action_binding_report(self) -> dict[str, Any]:
        rows = []
        for key, row in sorted(getattr(self, "action_registry", {}).items()):
            condition = row.get("enabled_condition"); enabled = True
            if callable(condition):
                try: enabled = bool(condition())
                except Exception as exc:
                    enabled = False; row["last_error"] = str(exc)
            rows.append({"key": key, "label": row.get("label"), "source": row.get("source"), "shortcut": row.get("shortcut"), "enabled": enabled, "last_error": row.get("last_error", "")})
        return {"ok": not any(row.get("last_error") for row in rows), "rows": rows}

    def _show_command_error(self, action: str, exc: Exception, recovery_hint: str = "") -> None:
        summary = f"{action}: {type(exc).__name__}: {exc}"
        _append_control_panel_diagnostic_event({"event": "command-error", "action": str(action or "command"), "summary": summary, "detail": traceback.format_exc()})
        self.push_notification("error", "Command failed", summary, target_scope="diagnostics")
        self.status_message((recovery_hint or summary)[:160])

    def add_toolbar_button(self, toolbar: QToolBar, label: str, slot: Callable[[], None], shortcut: str | None = None) -> QAction:
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setToolTip(self._tooltip_for_label(label))
        action_key = self._canonical_action_key(label)
        self._register_action_binding(action_key, label, slot, shortcut=shortcut, source="toolbar")
        def _safe_triggered(*_args: Any, bound_slot: Callable[[], None] = slot, bound_label: str = label) -> None:
            try: bound_slot()
            except Exception as exc: self._show_command_error(bound_label, exc)
        action.triggered.connect(_safe_triggered)
        toolbar.addAction(action)
        return action

    def _build_context_inspector(self) -> QFrame:
        """Persistent right rail: live context without adding noise to each tab."""
        panel = QFrame()
        panel.setObjectName("contextInspector")
        panel.setMinimumWidth(220)
        panel.setMaximumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        title = QLabel("Context")
        title.setObjectName("contextTitle")
        self.context_inspector_title = title
        self.context_inspector_status = StatusBadge("Ready", "ok")
        self.context_inspector_meta = QLabel("No active selection")
        self.context_inspector_meta.setObjectName("emptyDetail")
        self.context_inspector_meta.setWordWrap(True)
        self.context_inspector_detail = QLabel("Select a work, series, page, or validation item to see focused guidance here.")
        self.context_inspector_detail.setObjectName("contextDetail")
        self.context_inspector_detail.setWordWrap(True)
        self.context_inspector_next = QLabel("Next best action will appear here.")
        self.context_inspector_next.setObjectName("missionStatus")
        self.context_inspector_next.setWordWrap(True)
        self.context_inspector_preview = QLabel("No preview")
        self.context_inspector_preview.setObjectName("contextInspectorPreview")
        self.context_inspector_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.context_inspector_preview.setMinimumHeight(128)
        self.context_inspector_preview.setMaximumHeight(150)
        self.context_inspector_actions = QFrame()
        self.context_inspector_actions.setObjectName("contextInspectorActions")
        action_row = QHBoxLayout(self.context_inspector_actions)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.context_inspector_edit_btn = QPushButton("Edit")
        self.context_inspector_edit_btn.clicked.connect(self._inspector_edit_current)
        self.context_inspector_replace_btn = QPushButton("Replace image")
        self.context_inspector_replace_btn.clicked.connect(self.open_replace_image_dialog)
        self.context_inspector_lineage_btn = QPushButton("View lineage")
        self.context_inspector_lineage_btn.clicked.connect(self.open_work_lineage_dialog)
        for btn in (self.context_inspector_edit_btn, self.context_inspector_replace_btn, self.context_inspector_lineage_btn):
            btn.setObjectName("secondaryActionButton")
            action_row.addWidget(btn)
        layout.addWidget(title)
        layout.addWidget(self.context_inspector_status)
        layout.addWidget(self.context_inspector_preview)
        layout.addWidget(self.context_inspector_meta)
        layout.addWidget(self.context_inspector_detail, 1)
        layout.addWidget(self.context_inspector_next)
        layout.addWidget(self.context_inspector_actions)
        return panel


    def _inspector_edit_current(self) -> None:
        """Keep the selected item visible while focusing the relevant editor."""
        current = self.tabs.currentWidget() if hasattr(self, "tabs") else None
        if current is getattr(self, "works_tab", None):
            target = getattr(self, "work_title_edit", None)
        elif current is getattr(self, "series_tab", None):
            target = getattr(self, "series_title_edit", None)
        elif current is getattr(self, "pages_tab", None):
            target = getattr(self, "page_title_edit", None)
        else:
            target = None
        if _qt_object_alive(target):
            target.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _set_context_inspector_preview_from_path(self, path: str | Path | None) -> None:
        label = getattr(self, "context_inspector_preview", None)
        if not _qt_object_alive(label):
            return
        try:
            image_path = Path(path) if path else None
            if not image_path or not image_path.exists():
                label.setText("No preview")
                label.setPixmap(QPixmap())
                return
            pix = QPixmap(str(image_path))
            if pix.isNull():
                label.setText("No preview")
                label.setPixmap(QPixmap())
                return
            label.setText("")
            label.setPixmap(pix.scaled(QSize(250, 145), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        except Exception as exc:
            self._log_warning(f"Inspector preview failed: {exc}")

    def toggle_context_inspector(self) -> None:
        """Show/hide the optional right inspector so the main workspace stays wide and clean by default."""
        if not hasattr(self, "context_inspector"):
            return
        visible = not self.context_inspector.isVisible()
        self.context_inspector.setVisible(visible)
        try:
            if visible:
                self.main_splitter.setSizes([max(204, self.side_nav.width()), max(900, self.width() - 520), 240])
                self.refresh_context_inspector()
            else:
                self.main_splitter.setSizes([max(204, self.side_nav.width()), max(1100, self.width() - 260), 0])
            self._apply_works_responsive_layout()
        except Exception as exc:
            self._log_warning(f"Could not toggle context inspector: {exc}")
        self.status_message("Context inspector shown" if visible else "Context inspector hidden")

    def refresh_context_inspector(self) -> None:
        if not hasattr(self, "context_inspector_title") or not hasattr(self, "tabs"):
            return
        try:
            tab_label = self._clean_tab_label(self.tabs.tabText(self.tabs.currentIndex())) if self.tabs.count() else "Dashboard"
            self.context_inspector_title.setText(tab_label)
            status = "ok"
            meta = "No active selection"
            detail = tab_purpose(tab_label)
            next_action = "Use Search or the command palette for faster navigation."
            current_widget = self.tabs.currentWidget()
            if current_widget is getattr(self, "works_tab", None):
                selected_count = len(self.selected_work_ids()) if hasattr(self, "work_tree") else 0
                work_id = str(getattr(self, "_current_work_id", "") or "")
                payload = self._work_model_payload_for_id(work_id) or (load_work_payload(work_id) if work_id else {})
                issues = work_issue_list(payload) if payload else []
                status = "error" if any(str(i).lower().startswith(("error", "missing")) for i in issues) else "warning" if issues else "ok"
                meta = f"{selected_count} selected" if selected_count > 1 else (str(payload.get("title") or work_id or "No work selected"))
                image_path = best_preview_path_for_work(payload) if payload else None
                self._set_context_inspector_preview_from_path(image_path)
                modified = "—"
                try:
                    source = Path(str(image_path)) if image_path else None
                    modified = datetime.fromtimestamp(source.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if source and source.exists() else "—"
                except Exception:
                    modified = "—"
                source_health = str(payload.get("_source_status") or "deferred")
                detail = (
                    f"Series: {payload.get('series') or '—'}\n"
                    f"Status: {payload.get('review_status') or 'draft'} · {'published' if payload.get('published') else 'unpublished'}\n"
                    f"Source: {source_health} · Issues: {len(issues)}\n"
                    f"Modified: {modified}"
                ) if payload else "Choose a work to edit metadata, image readiness, and publishing state."
                next_action = "Fix the first highlighted field before saving." if issues else "Metadata looks ready. Save or move to the next work."
            elif current_widget is getattr(self, "series_tab", None):
                slug = str(getattr(self, "_current_series_slug", "") or "")
                meta = slug or "No series selected"
                self._set_context_inspector_preview_from_path(None)
                if slug:
                    payload = load_series_payload(slug) or {}
                    sequence = [str(item) for item in (payload.get("work_ids") or payload.get("sequence") or []) if str(item).strip()]
                    completeness = "ready" if sequence and str(payload.get("title") or "").strip() else "incomplete"
                    status = "ok" if completeness == "ready" else "warning"
                    detail = f"Completeness: {completeness}\nSequence: {len(sequence)} work(s)\nOrder: " + (", ".join(sequence[:6]) + ("…" if len(sequence) > 6 else "") if sequence else "No sequence yet")
                next_action = "Drag sequence items to refine the story order."
            elif current_widget is getattr(self, "pages_tab", None):
                meta = str(getattr(self, "_current_page_key", "") or "No page selected")
                next_action = "Use the structured editor first; raw YAML is the advanced fallback."
            elif current_widget is getattr(self, "validation_tab", None):
                count = int(getattr(self, "_cached_validation_count", 0) or 0)
                status = "warning" if count else "ok"
                meta = f"{count} validation issue(s)"
                next_action = "Open the highest-severity issue first." if count else "Validation is clean."
            elif current_widget is getattr(self, "publish_tab", None):
                status = "running" if getattr(self, "_running_tasks", 0) else "ok"
                meta = str(getattr(self, "_last_build_status", "No build yet"))
                next_action = "Run validation before preparing a publish package."
            if hasattr(self, "context_inspector_replace_btn"):
                is_work_context = current_widget is getattr(self, "works_tab", None) and bool(getattr(self, "_current_work_id", ""))
                self.context_inspector_replace_btn.setVisible(is_work_context)
                self.context_inspector_lineage_btn.setVisible(is_work_context)
            self.context_inspector_status.set_status(status, status.title())
            self.context_inspector_meta.setText(meta)
            self.context_inspector_detail.setText(detail)
            if getattr(self, "_safe_mode", False):
                next_action = next_action + "\n\nSafe mode is active: heavy Studio/Publish refreshes are deferred."
            self.context_inspector_next.setText(next_action)
        except Exception as exc:
            self._log_warning(f"Context inspector refresh failed: {exc}")

    def bind_shortcuts(self) -> None:
        self.command_shortcuts = {
            "save_current": "Ctrl+S",
            "refresh": "Ctrl+R",
            "add_image": "Ctrl+N",
            "search": "Ctrl+P",
            "command_palette": "Ctrl+K",
            "next_work": "Alt+Down",
            "previous_work": "Alt+Up",
            "next_series": "Alt+Right",
            "previous_series": "Alt+Left",
            "next_page": "Ctrl+Alt+Down",
            "previous_page": "Ctrl+Alt+Up",
            "clear_filters": "Ctrl+Shift+F",
            "shortcuts": "?",
            "show_last_save_diff": "Ctrl+D",
            "undo_quick_state": "Ctrl+Shift+Z",
            "toggle_reduced_motion": "Ctrl+Alt+M",
        }
        for i in range(9):
            self.command_shortcuts[f"tab_{i + 1}"] = f"Ctrl+{i + 1}"

        for i in range(9):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            shortcut.activated.connect(lambda index=i: self.tabs.setCurrentIndex(index) if index < self.tabs.count() else None)

        help_shortcut = QShortcut(QKeySequence("?"), self)
        help_shortcut.activated.connect(self.show_shortcuts)

        diff_shortcut = QShortcut(QKeySequence("Ctrl+D"), self)
        diff_shortcut.activated.connect(self.show_last_save_diff)

        save_action = QAction(self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        save_action.triggered.connect(self.save_current_tab)
        self.addAction(save_action)

        next_work = QAction(self)
        next_work.setShortcut(QKeySequence("Alt+Down"))
        next_work.triggered.connect(lambda: self.navigate_work(1))
        self.addAction(next_work)

        prev_work = QAction(self)
        prev_work.setShortcut(QKeySequence("Alt+Up"))
        prev_work.triggered.connect(lambda: self.navigate_work(-1))
        self.addAction(prev_work)

        next_series = QAction(self)
        next_series.setShortcut(QKeySequence("Alt+Right"))
        next_series.triggered.connect(lambda: self.navigate_series(1))
        self.addAction(next_series)

        prev_series = QAction(self)
        prev_series.setShortcut(QKeySequence("Alt+Left"))
        prev_series.triggered.connect(lambda: self.navigate_series(-1))
        self.addAction(prev_series)

        next_page = QAction(self)
        next_page.setShortcut(QKeySequence("Ctrl+Alt+Down"))
        next_page.triggered.connect(lambda: self.navigate_page(1))
        self.addAction(next_page)

        prev_page = QAction(self)
        prev_page.setShortcut(QKeySequence("Ctrl+Alt+Up"))
        prev_page.triggered.connect(lambda: self.navigate_page(-1))
        self.addAction(prev_page)

        clear_filters = QAction(self)
        clear_filters.setShortcut(QKeySequence("Ctrl+Shift+F"))
        clear_filters.triggered.connect(self.clear_work_filters)
        self.addAction(clear_filters)

        search_action = QAction(self)
        search_action.setShortcut(QKeySequence("Ctrl+P"))
        search_action.triggered.connect(self.open_global_search)
        self.addAction(search_action)

        undo_quick = QAction(self)
        undo_quick.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        undo_quick.triggered.connect(self.undo_last_quick_work_state)
        self.addAction(undo_quick)

        reduced_motion = QAction(self)
        reduced_motion.setShortcut(QKeySequence("Ctrl+Alt+M"))
        reduced_motion.triggered.connect(self.toggle_reduced_motion)
        self.addAction(reduced_motion)

    def _load_base_qss(self) -> str:
        qss_path = Path(__file__).with_name("control_panel_theme.qss")
        try:
            return qss_path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _dynamic_theme_qss(self) -> str:
        theme = THEME
        return f"""
        QMainWindow {{ background: {theme['bg_window']}; color: {theme['text']}; }}
        QWidget {{ color: {theme['text']}; font-family: {theme['font_family']}; font-size: {theme['font_size']}; }}
        QLabel#appTitle, QLabel#emptyTitle, QLabel#contextTitle {{ font-weight: {density_profile(FIXED_CONTROL_PANEL_DENSITY).get('weight_heading', 700)}; }}
        QLabel, QCheckBox {{ font-weight: {density_profile(FIXED_CONTROL_PANEL_DENSITY).get('weight_body', 400)}; }}
        QFormLayout QLabel, QLabel#breadcrumb {{ font-weight: {density_profile(FIXED_CONTROL_PANEL_DENSITY).get('weight_label', 500)}; }}
        QFrame#workspaceCard, QFrame#premiumCard {{ background: {theme['bg_elevated']}; border: 1px solid {theme['border_soft']}; border-radius: {theme['radius_card']}; }}
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{ background: {theme['bg_input']}; border: 1px solid {theme['border']}; border-radius: {theme['radius_input']}; color: {theme['text_strong']}; }}
        QPushButton:focus, QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QTreeWidget:focus, QListWidget:focus {{ border: {theme['border_focus']}; }}
        QFrame#tagInput {{ background: {theme['bg_input']}; border: 1px solid {theme['border']}; border-radius: {theme['radius_input']}; }}
        QFrame#workHealthRail {{ background: transparent; border: none; }}
        QToolBar#mainCommandBar {{ border: 1px solid {theme['border_soft']}; }}
        """

    def apply_theme(self) -> None:
        theme = THEME
        density = FIXED_CONTROL_PANEL_DENSITY
        density_tokens = density_profile(density)
        qss_key = (str(density), bool(getattr(self, "_reduced_motion", False)))
        cached = self._qss_cache.get(qss_key)
        if cached is not None and self._last_applied_qss_key == qss_key:
            return
        base_qss = self._load_base_qss()
        dynamic_qss = self._dynamic_theme_qss()
        legacy_qss = f"""
            QWidget {{
                background: {theme['bg_primary']};
                color: {theme['text_primary']};
                font-size: {density_tokens['font']}px;
            }}
            QMainWindow, QDialog {{ background: {theme['bg_dialog']}; }}
            QLabel#appTitle {{ font-size: 23px; font-weight: 800; padding-top: 0px; }}
            QLabel#appSubTitle {{ color: {theme['text_muted']}; padding-top: 0px; }}
            QLabel#breadcrumb {{
                color: #5a7a9a;
                font-size: 11px;
                padding: 2px 0;
            }}
            QLabel#autosaveStatus {{
                color: #8ea2bd;
                font-size: 11px;
                padding: 4px 8px;
            }}
            QLabel#toastLabel {{
                background: #1a4a2e;
                border: 1px solid #70e0a2;
                border-radius: 12px;
                color: #70e0a2;
                padding: 8px 18px;
                font-weight: 600;
            }}
            QFrame#actionCard {{
                background: #0c1a27;
                border: 1px solid #20384e;
                border-radius: 12px;
            }}
            QFrame#actionCard:hover {{
                border: 1px solid {theme['accent']};
                background: #102235;
            }}
            QLabel#taskBadge {{
                background: #0f2032;
                border: 1px solid #20384e;
                border-radius: 12px;
                padding: 7px 12px;
                color: #c7d4e3;
            }}
            QToolBar {{
                background: transparent;
                spacing: 7px;
                border: none;
                padding: 8px 8px;
            }}
            QToolButton, QPushButton {{
                background: {theme['bg_button']};
                border: 1px solid {theme['border_button']};
                border-radius: {theme['radius_input']};
                padding: 6px 12px;
                min-height: 28px;
            }}
            QPushButton:hover, QToolButton:hover {{
                background: {theme['bg_button_hover']};
            }}
            QPushButton:pressed, QToolButton:pressed {{
                background: {theme['bg_button_pressed']};
            }}
            QPushButton:focus, QToolButton:focus, QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
                border: 2px solid {theme['focus_ring']};
            }}
            QTreeWidget::item:focus, QListWidget::item:focus {{
                border: 1px solid {theme['accent']};
                background: rgba(31, 95, 147, 0.28);
            }}
            QTabBar::tab:focus {{
                border: 1px solid {theme['accent']};
            }}
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QListWidget, QTreeWidget {{
                background: {theme['bg_input']};
                border: 1px solid {theme['border']};
                border-radius: {theme['radius_input']};
                selection-background-color: {theme['accent']};
            }}
            QLineEdit, QComboBox, QSpinBox {{ min-height: 30px; padding: 4px 8px; }}
            QPlainTextEdit, QTextEdit {{ padding: 8px; }}
            QTabWidget::pane {{
                border: 1px solid {theme['border_tabs']};
                border-radius: 12px;
                top: -1px;
                background: {theme['bg_panel']};
            }}
            QTabBar::tab {{
                background: #0b1722;
                padding: 8px 14px;
                margin-right: 6px;
                border-top-left-radius: {theme['radius_input']};
                border-top-right-radius: {theme['radius_input']};
                color: #92a6bf;
            }}
            QTabBar::tab:selected {{
                background: {theme['bg_button']};
                color: {theme['text_strong']};
            }}
            QFrame#metricCard, QGroupBox {{
                background: {theme['bg_surface']};
                border: 1px solid {theme['border_soft']};
                border-radius: {theme['radius_card']};
                margin-top: 12px;
            }}
            QFrame#metricCard:hover {{
                border: 1px solid {theme['accent']};
                background: #102235;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #93a8c1;
            }}
            QLabel#metricValue {{ font-size: 24px; font-weight: 700; }}
            QLabel#metricLabel {{ color: {theme['text_muted']}; }}
            QLabel#missionStatus {{
                background: #0b1722;
                border: 1px solid {theme['border_soft']};
                border-radius: 12px;
                padding: 10px 12px;
                color: #b9c8d9;
            }}
            QHeaderView::section {{
                background: #112233;
                color: {theme['text_header']};
                padding: 6px;
                border: none;
            }}
            QStatusBar {{ background: {theme['bg_primary']}; }}
            QSplitter::handle {{
                background: #1a2f43;
                border-radius: 4px;
            }}
            QSplitter::handle:hover {{
                background: {theme['accent']};
            }}
            QSplitter[orientation="1"]::handle {{
                height: 8px;
            }}
            QSplitter[orientation="2"]::handle {{
                width: 8px;
            }}
            QTreeWidget {{
                alternate-background-color: #0d1822;
            }}
            QTreeWidget::item {{
                min-height: 28px;
                padding: 2px 4px;
            }}
            QTreeWidget::item:alternate {{
                background: #0d1822;
            }}
            QListWidget#sideNav {{
                background: #07111a;
                border: 1px solid {theme['border_soft']};
                border-radius: 16px;
                padding: 8px;
                font-size: {density_tokens['font']}px;
            }}
            QListWidget#sideNav::item {{
                min-height: {density_tokens['row']}px;
                padding: {density_tokens['nav_v']}px 12px;
                border-radius: 11px;
                color: #9fb1c8;
            }}
            QListWidget#sideNav::item:selected {{
                background: #13283d;
                color: {theme['text_strong']};
                border: 1px solid {theme['accent']};
            }}
            QListWidget#sideNav::item:hover {{
                background: #102235;
            }}
            QListWidget#seriesSequenceBoard, QListWidget#featuredSeriesRelationshipList, QListWidget#selectedWorksRelationshipList {{
                padding: 8px;
                border: 1px solid #20384e;
            }}
            QListWidget#seriesSequenceBoard::item, QListWidget#featuredSeriesRelationshipList::item, QListWidget#selectedWorksRelationshipList::item {{
                min-height: {max(30, int(density_tokens['row']))}px;
                padding: 6px 10px;
                border-bottom: 1px solid #122537;
            }}
            QListWidget#seriesSequenceBoard::item:selected, QListWidget#featuredSeriesRelationshipList::item:selected, QListWidget#selectedWorksRelationshipList::item:selected {{
                background: #13283d;
                border: 1px solid {theme['accent']};
                color: {theme['text_strong']};
            }}
            QLabel#readinessScore {{
                font-size: 34px;
                font-weight: 800;
                color: {theme['text_strong']};
            }}
            QLabel#commandPanel {{
                background: #0b1722;
                border: 1px solid {theme['border_soft']};
                border-radius: 16px;
                padding: 12px 14px;
                color: #b9c8d9;
            }}
            QProgressBar {{
                background: {theme['bg_input']};
                border: 1px solid {theme['border']};
                border-radius: 9px;
                text-align: center;
                min-height: 18px;
            }}
            QProgressBar::chunk {{
                background: {theme['accent']};
                border-radius: 8px;
            }}
            QFrame#emptyState {{
                background: #0b1722;
                border: 1px dashed {theme['border_soft']};
                border-radius: {theme['radius_card']};
            }}
            QLabel#emptyTitle {{
                font-size: 16px;
                font-weight: 700;
                color: {theme['text_strong']};
            }}
            QLabel#emptyDetail {{ color: {theme['text_muted']}; }}
            QLabel#statusBadge {{
                border: 1px solid {theme['border_soft']};
                border-radius: 10px;
                padding: 4px 8px;
                background: #0f2032;
            }}
            QLabel#statusBadge[state="error"], QLabel#statusBadge[state="blocked"], QLabel#statusBadge[state="failed"] {{ color: {theme['danger']}; }}
            QLabel#statusBadge[state="warning"], QLabel#statusBadge[state="watch"] {{ color: {theme['warning']}; }}
            QLabel#statusBadge[state="ok"], QLabel#statusBadge[state="success"], QLabel#statusBadge[state="ready"] {{ color: {theme['success']}; }}
            QLabel#statusBadge[state="info"], QLabel#statusBadge[state="running"] {{ color: {theme['accent']}; }}
            QLabel#charCounter, QLabel#fieldStats {{
                color: #8ea2bd;
                font-size: 11px;
                padding: 2px 0;
            }}
            QFrame#workPreviewPane {{
                background: #081521;
                border: 1px solid {theme['border_soft']};
                border-radius: 16px;
            }}
            QFrame#workGalleryCard {{
                background: #081521;
                border: 1px solid #20384e;
                border-radius: 16px;
            }}
            QFrame#workGalleryCard[selected="true"] {{
                border: 2px solid {theme['focus_ring']};
            }}
            QLabel#workGalleryImage {{
                background: #050c13;
                border-radius: 12px;
            }}
            QLabel#workGalleryOverlay {{
                background: rgba(3, 9, 15, 190);
                color: #eaf1f8;
                padding: 14px;
                border-radius: 16px;
            }}
            QFrame#tagInput {{
                background: {theme['bg_input']};
                border: 1px solid {theme['border']};
                border-radius: {theme['radius_input']};
            }}
            QLineEdit#tagInputEntry {{
                border: none;
                background: transparent;
                padding: 2px;
            }}
            QPushButton#tagPill {{
                color: #bfe0ff;
                background: #102235;
                border: 1px solid #284a66;
                border-radius: 12px;
                padding: 4px 8px;
            }}
            QToolBar#mainCommandBar {{
                border: 1px solid {theme['border_soft']};
                border-radius: 12px;
                margin: 4px 10px 0 10px;
                min-height: 50px;
                max-height: 54px;
            }}
            QPushButton#moreCommandButton {{
                padding-right: 18px;
            }}
            QFrame#contextInspector {{
                background: #081521;
                border: 1px solid {theme['border_soft']};
                border-radius: 16px;
            }}
            QLabel#contextTitle {{
                font-size: 16px;
                font-weight: 800;
                color: {theme['text_strong']};
            }}
            QLabel#contextDetail {{
                color: #aebed0;
                line-height: 1.3;
            }}
            QFrame#workBatchBar {{
                background: #101f30;
                border: 1px solid {theme['accent']};
                border-radius: 12px;
                padding: 6px;
            }}
            QFrame#workHealthRail {{
                background: #081521;
                border: 1px solid {theme['border_soft']};
                border-radius: 12px;
            }}
            QFrame#collapsibleSection {{
                border: 1px solid #2b3442;
                border-radius: 12px;
                background: #111821;
            }}
            QPushButton#sectionToggle {{
                text-align: left;
                padding: 10px 12px;
                border: none;
                border-bottom: 1px solid #26303d;
                border-radius: 12px;
                font-weight: 700;
            }}
            QWidget#sectionBody {{ background: transparent; }}
            QListWidget#seriesCardList::item {{
                min-height: 64px;
                padding: 8px;
                border-radius: 12px;
            }}
            QListWidget#seriesSequenceBoard::item,
            QListWidget#featuredSeriesRelationshipList::item,
            QListWidget#selectedWorksRelationshipList::item {{
                min-height: 66px;
                padding: 6px;
                border-radius: 12px;
            }}
            QCheckBox#segmentedControl {{
                padding: 6px 10px;
                border: 1px solid #2f3948;
                border-radius: 999px;
                background: #0f151d;
            }}
            QFrame#workflowStepper {{
                background: #081521;
                border: 1px solid {theme['border_soft']};
                border-radius: 16px;
            }}
            QLabel#workflowStep {{
                border-radius: 12px;
                padding: 6px 10px;
                font-weight: 700;
            }}
            QLabel#workflowStep[state="locked"] {{
                color: #617389;
                border-color: #263344;
                background: #0b121b;
            }}
            QLabel#releaseGateBadge {{
                padding: 8px 12px;
                font-weight: 800;
            }}
            QFrame#premiumCard {{
                background: {theme['bg_elevated']};
                border: 1px solid {theme['border_soft']};
                border-radius: {theme['radius_card']};
            }}
            QLabel#premiumCardTitle {{
                color: {theme['text_strong']};
                font-weight: 800;
                font-size: 15px;
            }}
            QGroupBox#buildLogDrawer {{
                background: #081521;
                border: 1px dashed {theme['border_soft']};
            }}
            QPushButton#menuActionButton {{
                padding-right: 18px;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 2px 0 2px 0;
            }}
            QScrollBar::handle:vertical {{
                background: #264158;
                border-radius: 4px;
                min-height: 36px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                height: 0px;
                background: transparent;
            }}
            QFrame#workspaceCard {{
                background: #081521;
                border: 1px solid {theme['border_soft']};
                border-radius: 16px;
            }}
            QLabel#sectionKicker {{
                color: #8ea2bd;
                font-weight: 700;
                padding: 2px 0;
            }}
            QLabel#quietHint {{
                color: #8ea2bd;
                padding: 4px 0;
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:horizontal {{ height: 0px; background: transparent; }}
            """
        combined = base_qss + "\n" + legacy_qss + "\n" + dynamic_qss
        self._qss_cache[qss_key] = combined
        if self._last_applied_qss_key == qss_key:
            return
        updates_were_enabled = bool(self.updatesEnabled())
        if updates_were_enabled:
            self.setUpdatesEnabled(False)
        try:
            self.setStyleSheet(combined)
            self._last_applied_qss_key = qss_key
        finally:
            if updates_were_enabled:
                self.setUpdatesEnabled(True)
                self.update()

    def toggle_theme(self) -> None:
        """Reserved hook for future theme switching; reapplies tokenized theme safely."""
        self.apply_theme()

    def _severity_color(self, severity: str) -> QColor:
        return QColor(status_accent(severity))

    def _show_toast(self, text: str, *, duration_ms: int = 2200) -> None:
        if bool(getattr(self, "_reduced_motion", False)):
            self.status_message(str(text))
            return
        try:
            ToastLabel(self, text, duration_ms=duration_ms)
        except Exception as exc:
            self._log_warning(f"Toast failed: {exc}")

    def _notify_nonblocking(self, level: str, title: str, detail: str = "", *, target_scope: str | None = None, target_id: str | None = None, toast: str | None = None) -> None:
        """Phase 16: use notification centre + status/toast for non-critical results.

        Modal dialogs are reserved for destructive confirmation, data-loss risk, and
        hard failures that need the user's immediate decision.
        """
        self.push_notification(level, title, detail, target_scope=target_scope, target_id=target_id)
        message = str(toast or title)
        if detail:
            self.status_message(f"{message}: {detail}")
        else:
            self.status_message(message)
        if str(level).lower() in {"success", "info"}:
            self._show_toast(message)

    def _critical_modal(self, title: str, detail: str, *, target_scope: str | None = None, target_id: str | None = None) -> None:
        """Keep hard failures visible but make long details expandable and traceable."""
        self.push_notification("error", title, detail, target_scope=target_scope, target_id=target_id)
        if len(str(detail or "")) < 420 and "\n" not in str(detail or ""):
            QMessageBox.critical(self, title, detail)
            return
        self._error_details_dialog(title, detail)

    def _error_details_dialog(self, title: str, detail: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        summary = QLabel(str(detail or "").splitlines()[0][:220] if detail else title)
        summary.setObjectName("missionStatus")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(str(detail or ""))
        details.setAccessibleName("Expanded error details")
        details.setToolTip("Long error details. Copy this text when debugging or reporting a regression.")
        layout.addWidget(details, 1)
        row = QHBoxLayout()
        copy_btn = QPushButton("Copy details")
        copy_btn.clicked.connect(lambda: (QApplication.clipboard().setText(details.toPlainText()), self.status_message("Copied error details")))
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        row.addWidget(copy_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)
        dialog.exec()

    def _info_nonblocking(self, title: str, detail: str = "", *, target_scope: str | None = None, target_id: str | None = None) -> None:
        self._notify_nonblocking("info", title, detail, target_scope=target_scope, target_id=target_id)

    def _warning_nonblocking(self, title: str, detail: str = "", *, target_scope: str | None = None, target_id: str | None = None) -> None:
        self._notify_nonblocking("warning", title, detail, target_scope=target_scope, target_id=target_id)

    def toggle_reduced_motion(self) -> None:
        self._reduced_motion = not bool(getattr(self, "_reduced_motion", False))
        if hasattr(self, "side_nav"):
            self.side_nav.setProperty("reducedMotion", self._reduced_motion)
            self.side_nav.viewport().update()
        self.state["reduced_motion"] = self._reduced_motion
        self.save_window_state()
        self.status_message("Reduced motion enabled" if self._reduced_motion else "Reduced motion disabled")
        self._show_toast("Reduced motion enabled" if self._reduced_motion else "Reduced motion disabled")

    def _remember_quick_work_state(self, work_id: str, *, published: bool | None = None, review_status: str | None = None) -> None:
        payload = load_work_payload(work_id) if work_id else {}
        self._last_quick_work_state = {
            "work_id": work_id,
            "published": bool(payload.get("published")),
            "review_status": str(payload.get("review_status") or "draft"),
            "changed_published": published is not None,
            "changed_review": review_status is not None,
        }

    def undo_last_quick_work_state(self) -> None:
        row = getattr(self, "_last_quick_work_state", None) or {}
        work_id = str(row.get("work_id") or "")
        if not work_id:
            self.status_message("No quick work-state change to undo")
            return
        try:
            kwargs: dict[str, Any] = {}
            if row.get("changed_published"):
                kwargs["published"] = bool(row.get("published"))
            if row.get("changed_review"):
                kwargs["review_status"] = str(row.get("review_status") or "draft")
            if not kwargs:
                return
            update_work_quick_state(work_id, **kwargs)
            self._patch_work_tree_row_after_quick_state(work_id, published=kwargs.get("published"), review_status=kwargs.get("review_status"))
            self._mark_work_quick_edit_dependents_dirty()
            self._last_quick_work_state = {}
            self._show_toast(f"Undid quick state change for {work_id}")
        except Exception as exc:
            QMessageBox.critical(self, "Undo quick state failed", str(exc))

    def _activity_item_key(self, row: dict[str, Any]) -> str:
        return f"{row.get('started_at') or row.get('timestamp') or row.get('created_at') or ''} {row.get('label') or row.get('id') or ''}"

    def _make_activity_item(self, row: dict[str, Any]) -> QListWidgetItem:
        status = str(row.get("status") or "").lower()
        icon = "✕" if status in {"error", "failed", "fail"} else "✓" if status in {"ok", "success", "completed", "done"} else "•"
        targets = ", ".join([str(t).replace("REL::", "") for t in list(row.get("targets") or [])[:3]])
        when = str(row.get("started_at") or row.get("timestamp") or "")[-19:]
        item = QListWidgetItem(f"{icon} {when} · {row.get('label') or 'Operation'}\n{targets or row.get('status') or 'No target detail'}")
        item.setData(Qt.ItemDataRole.UserRole, row)
        item.setData(Qt.ItemDataRole.UserRole + 1, self._activity_item_key(row))
        return item

    def _sync_activity_timeline(self, rows: list[dict[str, Any]], *, reset: bool = False) -> None:
        if not hasattr(self, "dashboard_activity"):
            return
        if reset:
            self.dashboard_activity.clear()
        existing = {str(self.dashboard_activity.item(i).data(Qt.ItemDataRole.UserRole + 1) or self.dashboard_activity.item(i).text()) for i in range(self.dashboard_activity.count())}
        new_rows = [row for row in rows if self._activity_item_key(row) not in existing]
        for row in reversed(new_rows):
            item = self._make_activity_item(row)
            self.dashboard_activity.insertItem(0, item)
            item.setBackground(QColor("#153b2c"))
            QTimer.singleShot(800, lambda it=item: it.setBackground(QColor()))
        while self.dashboard_activity.count() > 30:
            self.dashboard_activity.takeItem(self.dashboard_activity.count() - 1)

    def _release_fix_target(self, row: dict[str, Any]) -> tuple[str, QWidget] | None:
        area = str(row.get("area") or "").lower()
        detail = str(row.get("detail") or "").lower()
        if any(term in area or term in detail for term in ("source", "asset", "image", "original")):
            return ("→ Studio", self.studio_tab)
        if any(term in area or term in detail for term in ("validation", "content", "metadata", "alt", "caption")):
            return ("→ Validate", self.studio_tab)
        if any(term in area or term in detail for term in ("publish", "release", "upload")):
            return ("→ Publish", self.publish_tab)
        return None

    def _go_to_release_fix_target(self, row: dict[str, Any]) -> None:
        target = self._release_fix_target(row)
        if not target:
            return
        _label, widget = target
        self.tabs.setCurrentWidget(widget)
        if widget is getattr(self, "validation_tab", None):
            self.refresh_validation()
        elif widget is self.studio_tab:
            self.refresh_studio()
        elif widget is self.publish_tab:
            self.refresh_source_reports()
        self.status_message(f"Opened fix target for {row.get('area') or 'release check'}")

    def _action_priority_icon(self, row: dict[str, Any]) -> str:
        label = f"{row.get('label','')} {row.get('detail','')}".lower()
        if any(token in label for token in ("error", "blocked", "missing", "failed")):
            return "🛑"
        if any(token in label for token in ("warning", "review", "attention", "weak")):
            return "⚠"
        return "↳"

    def _build_action_card(self, row: dict[str, Any], item: QTreeWidgetItem) -> QFrame:
        card = QFrame()
        card.setObjectName("actionCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 7, 8, 7)
        layout.setSpacing(10)
        icon = QLabel(self._action_priority_icon(row))
        icon.setFixedWidth(26)
        label = QLabel(f"<b>{html.escape(str(row.get('label') or 'Action'))}</b><br><small>{html.escape(str(row.get('detail') or ''))}</small>")
        label.setWordWrap(True)
        dismiss_btn = QPushButton("×")
        dismiss_btn.setFixedSize(24, 24)
        dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss_btn.setToolTip("Dismiss this action until the next refresh")
        dismiss_btn.clicked.connect(lambda _checked=False, r=row, it=item: self._dismiss_action(str(r.get("label") or ""), it))
        layout.addWidget(icon)
        layout.addWidget(label, 1)
        layout.addWidget(dismiss_btn)
        return card

    def _dismiss_action(self, label: str, item: QTreeWidgetItem) -> None:
        if label:
            self._dismissed_action_labels.add(label)
        try:
            item.setSizeHint(0, QSize(0, 0))
            self.dashboard_actions.takeTopLevelItem(self.dashboard_actions.indexOfTopLevelItem(item))
        except Exception as exc:
            self._log_warning(f"Dashboard action dismiss failed: {exc}")
        self.status_message(f"Dismissed: {label or 'action'}")

    def _draft_preview_text(self, kind: str, key: str, draft: dict[str, Any]) -> str:
        try:
            if kind == "work":
                current = load_work_payload(key)
                current_text = json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
                draft_text = json.dumps(draft.get("payload") or {}, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
            elif kind == "series":
                current = load_series_payload(key)
                current_text = json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
                draft_text = json.dumps(draft.get("payload") or {}, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
            elif kind == "page":
                current_text = load_page_yaml_text(key).splitlines()
                draft_text = str(draft.get("text") or "").splitlines()
            elif kind == "authority":
                current_text = load_authority_yaml_text(key).splitlines()
                draft_text = str(draft.get("text") or "").splitlines()
            else:
                return json.dumps(draft, indent=2, ensure_ascii=False)
            diff = list(unified_diff(current_text, draft_text, fromfile="saved", tofile="draft", lineterm=""))
            return "\n".join(diff[:80]) if diff else "No visible differences between saved content and draft."
        except Exception as exc:
            return f"Draft preview failed: {exc}\n\n" + json.dumps(draft, indent=2, ensure_ascii=False)[:4000]

    def _preview_draft(self, item: QTreeWidgetItem, column: int = 0) -> None:
        del column
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        kind = str(row.get("kind") or "")
        key = str(row.get("key") or "")
        if not kind or not key or not hasattr(self, "dashboard_draft_preview"):
            return
        draft = load_editor_draft(kind, key) or {}
        self.dashboard_draft_preview.setPlainText(self._draft_preview_text(kind, key, draft))
        self.dashboard_draft_preview.show()

    # ---------- dashboard ----------
    def _persist_column_widths(self, tree: QTreeWidget, key: str) -> None:
        def on_resize(_logical_index: int, _old_size: int, _new_size: int) -> None:
            widths = [int(tree.columnWidth(i)) for i in range(tree.columnCount())]
            self.state.setdefault("column_widths", {})[key] = widths
            self._state_save_timer.start()
        try:
            tree.header().sectionResized.connect(on_resize)
        except Exception as exc:
            self._log_warning(f"Could not persist columns for {key}: {exc}")

    def _restore_column_widths(self, tree: QTreeWidget, key: str) -> None:
        widths = (self.state.get("column_widths") or {}).get(key)
        if isinstance(widths, list):
            for i, width in enumerate(widths[:tree.columnCount()]):
                try:
                    tree.setColumnWidth(i, int(width))
                except Exception as exc:
                    self._log_warning(f"State restore failed for {key} column {i}: {exc}")

    def _polish_data_tree(self, tree: QTreeWidget, key: str | None = None) -> None:
        profile = density_profile(FIXED_CONTROL_PANEL_DENSITY)
        row_h = int(profile.get("row", 30))
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(True)
        tree.setProperty("densityRowHeight", row_h)
        tree.style().unpolish(tree); tree.style().polish(tree)
        if key:
            self._persist_column_widths(tree, key)
            self._restore_column_widths(tree, key)

    def _counted_counter(self, widget: QWidget, min_len: int, max_len: int) -> QLabel:
        counter = QLabel(f"0 / {max_len}")
        counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        counter.setObjectName("charCounter")
        def text_value() -> str:
            if hasattr(widget, "text"):
                try:
                    return str(widget.text())
                except TypeError:
                    # QPlainTextEdit.textChanged has no text() API; fall back to toPlainText().
                    pass
            if hasattr(widget, "toPlainText"):
                return str(widget.toPlainText())
            return ""
        def update_counter() -> None:
            n = len(text_value())
            counter.setText(f"{n} / {max_len}")
            if n > max_len:
                state = "error"
            elif n >= min_len:
                state = "ok"
            else:
                state = "warning"
            counter.setProperty("state", state)
            counter.style().unpolish(counter)
            counter.style().polish(counter)
        if hasattr(widget, "textChanged"):
            try:
                widget.textChanged.connect(lambda *_args: update_counter())
            except Exception as exc:
                self._log_warning(f"Character counter binding failed: {exc}")
        update_counter()
        return counter

    def _work_row_severity(self, payload: dict[str, Any]) -> str:
        issues = [str(issue).lower() for issue in (payload.get("_issue_list") or payload.get("issues") or [])]
        source_status = str(payload.get("_source_status") or "").lower()
        if source_status not in {"", "-", "ok"} and ("missing" in source_status or "broken" in source_status):
            return "error"
        if any(issue.startswith(("error", "missing")) or "missing source" in issue for issue in issues):
            return "error"
        if issues or source_status in {"orphan-risk", "recoverable", "warning"}:
            return "warning"
        return "ok"

    def _sync_work_gallery_selection(self, work_id: str | None = None) -> None:
        if not hasattr(self, "work_gallery_host"):
            return
        target = str(work_id or self._current_work_id or "")
        for card in self.work_gallery_host.findChildren(WorkGalleryCard):
            card.set_selected(bool(target and card.work_id == target))

    def _scaled_work_preview_pixmap(self, image_path: Path | str | None, size: QSize) -> QPixmap:
        path = Path(image_path) if image_path else None
        if path is None or not path.exists():
            return QPixmap()
        try:
            stat = path.stat()
            cache_key = f"{path.resolve()}::{int(stat.st_mtime_ns)}::{int(stat.st_size)}::{size.width()}x{size.height()}"
        except Exception:
            cache_key = f"{path}::{size.width()}x{size.height()}"
        cache = getattr(self, "_work_preview_pixmap_cache", None)
        if isinstance(cache, OrderedDict) and cache_key in cache:
            pix = cache.pop(cache_key)
            cache[cache_key] = pix
            return pix
        pix = QPixmap(str(path))
        if pix.isNull():
            return QPixmap()
        scaled = pix.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if isinstance(cache, OrderedDict):
            cache[cache_key] = scaled
            limit = int(getattr(self, "_work_preview_pixmap_cache_limit", 40) or 40)
            while len(cache) > limit:
                cache.popitem(last=False)
        return scaled

    def _preview_file_signature(self, image_path: Path | str | None, size: QSize, *extra: Any) -> tuple[Any, ...]:
        """Stable repaint signature for Works preview panes.

        Batch E uses this to avoid repainting the same pixmap from timer-driven
        validation, context-inspector refreshes, or asset-health patches. It is
        deliberately based on path + mtime + size, so replacing an image at the
        same filename still refreshes correctly.
        """
        path = Path(image_path) if image_path else None
        if path is None or not path.exists():
            return ("missing", size.width(), size.height(), *extra)
        try:
            stat = path.stat()
            return (str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size), size.width(), size.height(), *extra)
        except Exception:
            return (str(path), size.width(), size.height(), *extra)

    def _update_work_preview_pane(self, payload: dict[str, Any] | None = None) -> None:
        if not hasattr(self, "work_preview_pane"):
            return
        payload = payload or (load_work_payload(self._current_work_id or "") if self._current_work_id else {}) or {}
        work_id = str(payload.get("id") or self._current_work_id or "")
        title = str(payload.get("title") or work_id or "No work selected")
        series = str(payload.get("series") or "—")
        review = str(payload.get("review_status") or ("published" if payload.get("published") else "draft"))
        published_text = "published" if payload.get("published") else "unpublished"
        image_path = (fast_preview_path_for_work(payload) or best_preview_path_for_work(payload)) if payload else None
        size = QSize(280, 260)
        signature = self._preview_file_signature(image_path, size, work_id, title, series, review, published_text)
        if getattr(self, "_work_side_preview_signature", None) == signature:
            return
        self._work_side_preview_signature = signature
        self.work_preview_title.setText(title)
        self.work_preview_meta.setText(f"{series}\n{review} · {published_text}")
        scaled = self._scaled_work_preview_pixmap(image_path, size) if image_path else QPixmap()
        if not scaled.isNull():
            self.work_preview_image.setText("")
            self.work_preview_image.setPixmap(scaled)
            self.work_preview_image.setToolTip(str(Path(image_path)))
            self.refresh_context_inspector()
            return
        self.work_preview_image.setPixmap(QPixmap())
        self.work_preview_image.setText("No preview")
        self.work_preview_image.setToolTip("No preview")
        self.refresh_context_inspector()

    def _set_validation_filter(self, mode: str) -> None:
        self._validation_filter_mode = mode
        for name, button in getattr(self, "_validation_filter_buttons", {}).items():
            with signals_blocked(button):
                button.setChecked(name == mode)
        self._apply_validation_filter()

    def _apply_validation_filter(self) -> None:
        rows = list(getattr(self, "_validation_rows", []))
        mode = getattr(self, "_validation_filter_mode", "all")
        if mode != "all":
            def keep(row: dict[str, Any]) -> bool:
                sev = str(row.get("severity") or "").lower()
                if mode == "errors":
                    return sev == "error"
                if mode == "warnings":
                    return sev in {"warning", "warn"}
                if mode == "advisory":
                    return sev not in {"error", "warning", "warn"}
                return True
            rows = [row for row in rows if keep(row)]
        self._rebuild_validation_tree(rows)

    def _run_auto_fix(self, row_or_key: Any) -> None:
        row = row_or_key if isinstance(row_or_key, dict) else None
        if row is None:
            key = str(row_or_key or "")
            row = next((r for r in getattr(self, "_validation_rows", []) if str(r.get("key") or r.get("id") or "") == key), {"key": key})
        try:
            result = auto_fix_validation_issue(row)
        except Exception as exc:
            self.push_notification("warning", "Auto-fix failed", str(exc), target_scope="validation")
            return
        changed = result.get("changed") if isinstance(result, dict) else []
        detail = ", ".join(changed or []) if isinstance(changed, list) else str(result)
        self.push_notification("success", "Auto-fix applied", detail or str(row.get("id") or row.get("key") or "issue"), target_scope="validation")
        self.refresh_all_context(force=True, scope={"series", "pages", "dashboard", "validation", "studio", "publish"})

    def _append_log_line(self, line: str) -> None:
        target = self.build_log if hasattr(self, "build_log") else getattr(self, "build_log_output", None)
        if target is None:
            return
        cursor = target.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        lower = line.lower()
        if "error" in lower or "fail" in lower or "✕" in line:
            fmt.setForeground(QColor("#ff7a7a"))
        elif "warn" in lower or "⚠" in line:
            fmt.setForeground(QColor("#ffcf74"))
        elif "✓" in line or "success" in lower or " ok" in lower or lower.endswith("ok"):
            fmt.setForeground(QColor("#70e0a2"))
        else:
            fmt.setForeground(QColor("#8ea2bd"))
        cursor.insertText(line + "\n", fmt)
        target.setTextCursor(cursor)
        target.ensureCursorVisible()

    def build_dashboard_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("dashboardTab")
        root = QVBoxLayout(tab)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("dashboardScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        canvas = QWidget()
        canvas.setObjectName("dashboardCanvas")
        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)
        scroll.setWidget(canvas)
        root.addWidget(scroll, 1)

        def section_label(text: str, object_name: str = "dashboardSectionTitle") -> QLabel:
            label = QLabel(text)
            label.setObjectName(object_name)
            label.setWordWrap(True)
            return label

        def section_hint(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("dashboardSectionHint")
            label.setWordWrap(True)
            return label

        def make_card(title: str = "", subtitle: str = "", object_name: str = "dashboardSectionCard") -> tuple[QFrame, QVBoxLayout]:
            card = QFrame()
            card.setObjectName(object_name)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(8)
            if title or subtitle:
                header = QVBoxLayout()
                header.setContentsMargins(0, 0, 0, 0)
                header.setSpacing(2)
                if title:
                    header.addWidget(section_label(title))
                if subtitle:
                    header.addWidget(section_hint(subtitle))
                card_layout.addLayout(header)
            return card, card_layout

        # Compatibility splitters are retained for existing layout reset calls, but the
        # dashboard is now a card-based workbench instead of a giant mostly-empty splitter.
        self.dashboard_main_splitter = QSplitter(Qt.Orientation.Horizontal, tab)
        self.dashboard_main_splitter.setObjectName("dashboard-main-splitter")
        self.dashboard_main_splitter.hide()
        self.dashboard_right_splitter = QSplitter(Qt.Orientation.Vertical, tab)
        self.dashboard_right_splitter.setObjectName("dashboard-right-splitter")
        self.dashboard_right_splitter.hide()

        hero_card = QFrame()
        hero_card.setObjectName("dashboardReadinessHero")
        hero_layout = QHBoxLayout(hero_card)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        hero_layout.setSpacing(18)
        self.readiness_gauge = ReadinessGauge()
        self.readiness_gauge.setMinimumSize(112, 112)
        self.readiness_gauge.setMaximumSize(132, 132)
        hero_layout.addWidget(self.readiness_gauge, 0, Qt.AlignmentFlag.AlignVCenter)

        readiness_text = QVBoxLayout()
        readiness_text.setContentsMargins(0, 0, 0, 0)
        readiness_text.setSpacing(7)
        readiness_label = section_label("Portfolio readiness", "dashboardEyebrow")
        self.readiness_score_label = QLabel("—")
        self.readiness_score_label.setObjectName("readinessScore")
        self.readiness_status_label = QLabel("Calculating readiness and practical blockers…")
        self.readiness_status_label.setObjectName("dashboardReadinessDetail")
        self.readiness_status_label.setWordWrap(True)
        self.dashboard_mission_status = QLabel("Loading practical health checks…")
        self.dashboard_mission_status.setObjectName("missionStatus")
        self.dashboard_mission_status.setWordWrap(True)
        readiness_text.addWidget(readiness_label)
        readiness_text.addWidget(self.readiness_score_label)
        readiness_text.addWidget(self.readiness_status_label)
        readiness_text.addWidget(self.dashboard_mission_status)
        hero_layout.addLayout(readiness_text, 1)

        hero_actions = QVBoxLayout()
        hero_actions.setContentsMargins(0, 0, 0, 0)
        hero_actions.setSpacing(8)
        add_work_btn = QPushButton("Add work")
        add_work_btn.setObjectName("dashboardPrimaryAction")
        add_work_btn.clicked.connect(self.open_guided_add_work)
        run_health_top_btn = QPushButton("Run health check")
        run_health_top_btn.setObjectName("dashboardSecondaryAction")
        run_health_top_btn.clicked.connect(self.run_dashboard_health_check)
        hero_actions.addWidget(add_work_btn)
        hero_actions.addWidget(run_health_top_btn)
        hero_actions.addStretch(1)
        hero_layout.addLayout(hero_actions, 0)
        layout.addWidget(hero_card)

        stat_strip = QFrame()
        stat_strip.setObjectName("dashboardStatStrip")
        metrics = QHBoxLayout(stat_strip)
        metrics.setContentsMargins(10, 8, 10, 8)
        metrics.setSpacing(10)
        self.metric_works = InlineStat("Works", on_click=lambda: self.open_metric_target("works"))
        self.metric_series = InlineStat("Series", on_click=lambda: self.open_metric_target("series"))
        self.metric_issues = InlineStat("Needs attention", on_click=lambda: self.open_metric_target("issues"))
        self.metric_pages = InlineStat("Pages", on_click=lambda: self.open_metric_target("pages"))
        for card in (self.metric_works, self.metric_series, self.metric_issues, self.metric_pages):
            card.setObjectName("dashboardInlineStat")
            metrics.addWidget(card, 1)
        layout.addWidget(stat_strip)

        self.readiness_action_tree = QTreeWidget(tab)
        self.readiness_action_tree.setHeaderLabels(["Next action", "Count", "Target"])
        self.readiness_action_tree.itemDoubleClicked.connect(self.open_readiness_action)
        self.readiness_action_tree.hide()

        self.dashboard_quick_recent = QTreeWidget(tab)
        self.dashboard_quick_recent.setHeaderLabels(["Kind", "Target", "From operation"])
        self.dashboard_quick_recent.itemDoubleClicked.connect(self.open_dashboard_recent_target)
        self.dashboard_actions = QTreeWidget(tab)
        self.dashboard_actions.setHeaderLabels(["Action center"])
        self._polish_data_tree(self.dashboard_actions, "dashboard_actions")
        self.dashboard_actions.itemDoubleClicked.connect(self.handle_dashboard_action)
        self.dashboard_actions.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.dashboard_actions.customContextMenuRequested.connect(self.show_dashboard_action_menu)
        self.dashboard_drafts = QTreeWidget(tab)
        self.dashboard_drafts.setObjectName("dashboardDraftTree")
        self.dashboard_drafts.setHeaderLabels(["Kind", "Key", "Saved"])
        self.dashboard_drafts.itemClicked.connect(self._preview_draft)
        self.dashboard_drafts.itemDoubleClicked.connect(self.restore_dashboard_draft)
        self.dashboard_drafts.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.dashboard_drafts.customContextMenuRequested.connect(self.show_dashboard_draft_menu)
        for tree in (self.dashboard_quick_recent, self.dashboard_actions, self.dashboard_drafts):
            tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.dashboard_quick_recent.setColumnWidth(0, 90)
        self.dashboard_quick_recent.setColumnWidth(1, 220)
        self.dashboard_actions.setColumnWidth(0, 180)
        self.dashboard_drafts.setColumnWidth(0, 90)
        self.dashboard_drafts.setColumnWidth(1, 220)
        self.dashboard_quick_recent.hide()
        self.dashboard_actions.hide()

        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(12)

        action_card, action_layout = make_card(
            "Decision queue",
            "Only the highest-value blockers stay here. Double-click an item to jump to the responsible workspace.",
            "dashboardPrimaryCard",
        )
        action_header = QHBoxLayout()
        action_header.setContentsMargins(0, 0, 0, 0)
        action_header.addStretch(1)
        self.dashboard_action_filter_combo = QComboBox()
        self.dashboard_action_filter_combo.addItems(["All actions", "Blockers", "Warnings", "Metadata", "Publish"])
        self.dashboard_action_filter_combo.setToolTip("Hidden compatibility filter. Dashboard now shows one prioritised queue; detailed filters live in Works and Publish.")
        self.dashboard_action_filter_combo.currentTextChanged.connect(lambda _value=None: self.refresh_dashboard())
        self.dashboard_action_filter_combo.hide()
        action_header.addWidget(self.dashboard_action_filter_combo)
        action_layout.addLayout(action_header)
        self.dashboard_attention_label = QLabel("Loading decision summary…")
        self.dashboard_attention_label.setObjectName("dashboardCommandSummary")
        self.dashboard_attention_label.setWordWrap(True)
        action_layout.addWidget(self.dashboard_attention_label)
        self.dashboard_focus_list = QListWidget()
        self.dashboard_focus_list.setObjectName("dashboardFocusList")
        self.dashboard_focus_list.setAccessibleName("Dashboard top three blockers and next actions")
        self.dashboard_focus_list.setToolTip("Dashboard triage queue. Double-click an action to open the owning workspace. Only the top 3 blockers are shown here.")
        self.dashboard_focus_list.itemDoubleClicked.connect(self.handle_dashboard_focus_item)
        self.dashboard_focus_list.setMinimumHeight(142)
        self.dashboard_focus_list.setMaximumHeight(220)
        action_layout.addWidget(self.dashboard_focus_list)
        dashboard_route_row = QHBoxLayout()
        dashboard_route_row.setContentsMargins(0, 2, 0, 0)
        dashboard_route_row.setSpacing(8)
        dashboard_works_btn = QPushButton("Open Works issues")
        dashboard_works_btn.clicked.connect(lambda: self.open_metric_target("issues"))
        dashboard_publish_btn = QPushButton("Open Publish gate")
        dashboard_publish_btn.clicked.connect(lambda: (self._ensure_tab_built_by_key("publish"), self.tabs.setCurrentWidget(self.publish_tab), self.publish_inner_tabs.setCurrentIndex(0) if hasattr(self, "publish_inner_tabs") else None))
        dashboard_sources_btn = QPushButton("Recover sources")
        dashboard_sources_btn.clicked.connect(self.open_source_recovery_dialog)
        for btn in (dashboard_works_btn, dashboard_publish_btn, dashboard_sources_btn):
            btn.setObjectName("dashboardSecondaryAction")
            dashboard_route_row.addWidget(btn)
        dashboard_route_row.addStretch(1)
        action_layout.addLayout(dashboard_route_row)
        main_row.addWidget(action_card, 3)

        activity_card, activity_layout = make_card(
            "Activity",
            "A compact pulse of recent control-panel actions. Full diagnostics stay in the advanced drawer.",
            "dashboardSectionCard",
        )
        self.dashboard_activity_strip = QListWidget()
        self.dashboard_activity_strip.setObjectName("dashboardActivityStrip")
        self.dashboard_activity_strip.setMaximumHeight(156)
        self.dashboard_activity_strip.setAccessibleName("Dashboard recent activity strip")
        self.dashboard_activity_strip.setToolTip("Recent control-panel activity. Full diagnostics are behind the advanced drawer.")
        activity_layout.addWidget(self.dashboard_activity_strip)
        main_row.addWidget(activity_card, 2)
        layout.addLayout(main_row)

        recovery_row = QHBoxLayout()
        recovery_row.setContentsMargins(0, 0, 0, 0)
        recovery_row.setSpacing(12)

        recovery_card, recovery_layout = make_card(
            "Recovery",
            "Drafts appear only when there is something recoverable. The panel stays quiet otherwise.",
            "dashboardSectionCard",
        )
        self.dashboard_drafts_box = CollapsibleSection("Recoverable drafts", "hidden until recovery is needed", expanded=False)
        self.dashboard_drafts_box.add_widget(self.dashboard_drafts, 1)
        self.dashboard_drafts_box.hide()
        recovery_layout.addWidget(self.dashboard_drafts_box)
        self.dashboard_draft_preview = QPlainTextEdit()
        self.dashboard_draft_preview.setObjectName("dashboardDetailBox")
        self.dashboard_draft_preview.setReadOnly(True)
        self.dashboard_draft_preview.setMaximumHeight(118)
        self.dashboard_draft_preview.setPlaceholderText("Click a draft to preview changes…")
        self.dashboard_draft_preview.hide()
        recovery_layout.addWidget(self.dashboard_draft_preview)
        recovery_row.addWidget(recovery_card, 1)

        health_card, health_layout = make_card(
            "Manual health detail",
            "Heavy checks stay manual so the dashboard stays fast.",
            "dashboardSectionCard",
        )
        self.dashboard_health_detail_section = CollapsibleSection(
            "Health detail",
            "manual; avoids the old 19-second auto-scan",
            expanded=False,
        )
        health_row = QHBoxLayout()
        health_row.setContentsMargins(0, 0, 0, 0)
        run_health_btn = QPushButton("Run health check")
        run_health_btn.setObjectName("dashboardSecondaryAction")
        run_health_btn.clicked.connect(self.run_dashboard_health_check)
        health_row.addWidget(run_health_btn)
        health_row.addStretch(1)
        self.dashboard_health_detail_section.add_layout(health_row)
        self.dashboard_health_detail = QPlainTextEdit()
        self.dashboard_health_detail.setObjectName("dashboardDetailBox")
        self.dashboard_health_detail.setReadOnly(True)
        self.dashboard_health_detail.setMaximumHeight(160)
        self.dashboard_health_detail.setPlaceholderText("Manual health results appear here. Release rows stay in the Publish tab.")
        self.dashboard_health_detail_section.add_widget(self.dashboard_health_detail)
        health_layout.addWidget(self.dashboard_health_detail_section)
        recovery_row.addWidget(health_card, 1)
        layout.addLayout(recovery_row)

        self.dashboard_repair = QTreeWidget()
        self.dashboard_repair.setObjectName("dashboardRepairTree")
        self.dashboard_repair.setHeaderLabels(["Type", "ID", "Issue"])
        self.dashboard_repair.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.dashboard_repair.setColumnWidth(0, 110)
        self.dashboard_repair.setColumnWidth(1, 190)
        self.dashboard_repair.itemDoubleClicked.connect(self.open_repair_item)
        self.dashboard_release = QTreeWidget()
        self.dashboard_release.setHeaderLabels(["Area", "Status", "Detail", "Action"])
        self._polish_data_tree(self.dashboard_release, "dashboard_release")
        self.dashboard_release.setColumnWidth(0, 130)
        self.dashboard_release.setColumnWidth(1, 85)
        self.dashboard_release.setColumnWidth(3, 92)
        self.dashboard_recent = QTreeWidget()
        self.dashboard_recent.setObjectName("dashboardRecentTree")
        self.dashboard_recent.setHeaderLabels(["When", "Label", "Status"])
        self.dashboard_recent.itemSelectionChanged.connect(self.update_dashboard_recent_detail)
        self.dashboard_recent.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.dashboard_recent.customContextMenuRequested.connect(self.show_dashboard_recent_menu)
        self.dashboard_activity = QListWidget()
        self.dashboard_activity.setObjectName("dashboardActivityTimeline")
        self.dashboard_activity.setAlternatingRowColors(True)
        self.dashboard_recent_detail = QPlainTextEdit()
        self.dashboard_recent_detail.setObjectName("dashboardDetailBox")
        self.dashboard_recent_detail.setReadOnly(True)
        self.dashboard_recent_detail.setFixedHeight(120)

        advanced = CollapsibleSection("Advanced diagnostics", "repair queue, release rows, recent operations", expanded=False)
        diagnostics_row = QHBoxLayout()
        diagnostics_row.setContentsMargins(0, 0, 0, 0)
        diagnostics_row.setSpacing(10)
        repair_card, repair_layout = make_card("Repair queue", "Double-click a row to open the affected item.", "dashboardNestedCard")
        repair_layout.addWidget(self.dashboard_repair)
        diagnostics_row.addWidget(repair_card, 1)
        release_card, release_layout = make_card("Release checks", "Detailed publish gate rows remain in Publish.", "dashboardNestedCard")
        release_layout.addWidget(self.dashboard_release)
        diagnostics_row.addWidget(release_card, 1)
        advanced.add_layout(diagnostics_row)
        recent_card, recent_layout = make_card("Recent operations", "Select an operation to inspect the stored detail.", "dashboardNestedCard")
        recent_layout.addWidget(self.dashboard_recent)
        recent_layout.addWidget(section_label("Activity timeline", "dashboardInlineTitle"))
        recent_layout.addWidget(self.dashboard_activity, 1)
        recent_layout.addWidget(self.dashboard_recent_detail)
        advanced.add_widget(recent_card)
        layout.addWidget(advanced)
        layout.addStretch(1)
        return tab

    def refresh_dashboard(self) -> None:
        if self._dashboard_refresh_inflight:
            self._dashboard_refresh_pending = False
            self._record_dirty_refresh_diagnostic("dashboard", 0.0, "skipped duplicate dashboard refresh while one is already running")
            return
        self._dashboard_refresh_inflight = True
        self._dashboard_refresh_pending = False
        self._dashboard_refresh_started = time.perf_counter()
        if hasattr(self, "metric_works"):
            self.progress_hint.setText("Refreshing dashboard…")
        worker = FunctionWorker(self._collect_dashboard_data)
        self._active_workers.append(worker)
        worker.signals.result.connect(lambda data: self._apply_dashboard_data(data) if self._is_window_alive() else None)
        worker.signals.error.connect(lambda tb: self._log_warning(f"Dashboard refresh failed: {tb}") if self._is_window_alive() else None)
        worker.signals.finished.connect(lambda w=worker: self._dashboard_worker_finished(w) if self._is_window_alive() else self._forget_worker(w))
        self.io_thread_pool.start(worker)


    def _collect_dashboard_data(self) -> dict[str, Any]:
        summary = dashboard_summary(include_deep=False)
        drafts = list_editor_drafts()
        cached_health = load_cached_portfolio_health_report(max_age_seconds=30 * 60)
        cache_state = {}
        if isinstance(cached_health, dict):
            cache_state = dict(cached_health.get("_cache") or {})
        readiness = (cached_health or {}).get("readiness") if isinstance(cached_health, dict) else None
        if not isinstance(readiness, dict):
            readiness = dashboard_fast_readiness(summary, drafts=len(drafts))
        return {
            "summary": summary,
            "release_checks": [],
            "drafts": drafts,
            "recent_targets": self.recent_target_rows(8),
            "readiness": readiness,
            "health_report": cached_health or {},
            "health_cache_state": cache_state,
            "deep_pending": bool(cache_state.get("dirty") or cache_state.get("expired")),
        }

    def run_dashboard_health_check(self) -> None:
        """Manual deep dashboard scan; keeps first dashboard paint under the fast path."""
        if hasattr(self, "dashboard_health_detail"):
            self.dashboard_health_detail.setPlainText("Running manual health check…")
        if hasattr(self, "dashboard_health_detail_section"):
            self.dashboard_health_detail_section.setExpanded(True)
        self._start_dashboard_deep_health_refresh()


    def _start_dashboard_deep_health_refresh(self) -> None:
        if getattr(self, "_dashboard_deep_refresh_inflight", False) or not self._is_window_alive():
            return
        self._dashboard_deep_refresh_inflight = True
        self._dashboard_deep_refresh_started = time.perf_counter()
        self.start_keyed_background_task(
            "dashboard-deep-health",
            self._collect_dashboard_deep_health_data,
            on_done=self._apply_dashboard_deep_health_data,
            on_error=lambda tb: self._log_warning(f"Dashboard deep health failed: {tb}"),
            label="Dashboard deep health",
            cancel_previous=False,
        )

    def _collect_dashboard_deep_health_data(self) -> dict[str, Any]:
        health = portfolio_health_report(force=True, save=True, timeout_seconds=10.0)
        summary = dashboard_summary(include_deep=False)
        return {
            "summary": summary,
            "release_checks": list(health.get("release_rows") or []),
            "readiness": dict(health.get("readiness") or {}),
            "health_report": health,
            "source_recovery": source_recovery_summary(use_cache=True),
            "deep_health": True,
        }

    def _dashboard_deep_worker_finished(self, worker: FunctionWorker) -> None:
        elapsed = time.perf_counter() - getattr(self, "_dashboard_deep_refresh_started", time.perf_counter())
        self._record_perf("dashboard deep health", elapsed)
        self._dashboard_deep_refresh_inflight = False
        self._forget_worker(worker)

    def _dashboard_worker_finished(self, worker: FunctionWorker) -> None:
        elapsed = time.perf_counter() - getattr(self, "_dashboard_refresh_started", time.perf_counter())
        self._record_perf("dashboard refresh", elapsed)
        self._dashboard_refresh_inflight = False
        self._dashboard_refresh_pending = False
        self._forget_worker(worker)

    def _dashboard_action_matches_filter(self, row: dict[str, Any]) -> bool:
        label = (self.dashboard_action_filter_combo.currentText() if hasattr(self, "dashboard_action_filter_combo") else "All actions").lower()
        if label == "all actions":
            return True
        haystack = f"{row.get('label', '')} {row.get('detail', '')} {row.get('action', '')}".lower()
        if label == "blockers":
            return any(token in haystack for token in ("blocked", "blocker", "error", "missing", "failed", "critical"))
        if label == "warnings":
            return any(token in haystack for token in ("warning", "weak", "review", "attention"))
        if label == "metadata":
            return any(token in haystack for token in ("metadata", "caption", "alt", "title", "tag"))
        if label == "publish":
            return any(token in haystack for token in ("publish", "build", "release", "preview", "upload"))
        return True

    def _apply_dashboard_data(self, data: Any) -> None:
        if not isinstance(data, dict) or not hasattr(self, "metric_works"):
            return
        summary = data.get("summary")
        if summary is None:
            return
        self.metric_works.set_value(str(summary.works_total))
        self.metric_series.set_value(str(summary.series_total))
        self.metric_issues.set_value(str(summary.works_with_issues))
        self.metric_pages.set_value(str(summary.pages_total))
        self._cached_dashboard_action_count = len(summary.actions)
        self._cached_work_issue_count = int(summary.works_with_issues)
        self._cached_series_count = int(summary.series_total)
        self._cached_pages_count = int(summary.pages_total)
        self._apply_readiness_widget(data.get("readiness") or {})
        self.dashboard_quick_recent.clear()
        for row in list(data.get("recent_targets") or []):
            item = QTreeWidgetItem([row["kind"], row["target"], row["label"]])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            self.dashboard_quick_recent.addTopLevelItem(item)
        self.dashboard_actions.clear()
        visible_actions = []
        for row in summary.actions:
            if row["label"] in self._dismissed_action_labels:
                continue
            if not self._dashboard_action_matches_filter(row):
                continue
            visible_actions.append(row)
            item = QTreeWidgetItem([""])
            item.setData(0, Qt.ItemDataRole.UserRole, row.get("action"))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, row)
            item.setSizeHint(0, QSize(0, 58))
            self.dashboard_actions.addTopLevelItem(item)
            self.dashboard_actions.setItemWidget(item, 0, self._build_action_card(row, item))
        if hasattr(self, "dashboard_attention_label"):
            if visible_actions:
                first = visible_actions[0]
                self.dashboard_attention_label.setText(f"Next best action: {first.get('label') or 'Review'} · {first.get('detail') or 'Open the card for details'}")
            else:
                self.dashboard_attention_label.setText("No urgent blockers in the command queue. Continue with Works, Series, Pages, or run the Publish gate.")
        if hasattr(self, "dashboard_focus_list"):
            self.dashboard_focus_list.clear()
            header = QListWidgetItem("NEXT ACTIONS")
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setForeground(QColor("#6f86a0"))
            self.dashboard_focus_list.addItem(header)
            visible_actions = visible_actions[:3]
            if visible_actions:
                for row in visible_actions:
                    item = QListWidgetItem(f"{row.get('label') or 'Review'}\n{row.get('detail') or row.get('action') or ''}")
                    item.setData(Qt.ItemDataRole.UserRole, {"kind": "action", "action": row.get("action"), "row": row})
                    self.dashboard_focus_list.addItem(item)
            else:
                empty = QListWidgetItem("No blockers in the current filter")
                empty.setFlags(Qt.ItemFlag.NoItemFlags)
                self.dashboard_focus_list.addItem(empty)
            if len(summary.actions or []) > len(visible_actions):
                drill = QListWidgetItem("Advanced diagnostics hidden — open Publish, Validation, or Readiness report for the full queue")
                drill.setFlags(Qt.ItemFlag.NoItemFlags)
                drill.setForeground(QColor("#6f86a0"))
                self.dashboard_focus_list.addItem(drill)
        self.dashboard_repair.clear()
        for row in summary.repair_items:
            item = QTreeWidgetItem([row["kind"], row["id"], row["issue"]])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            self.dashboard_repair.addTopLevelItem(item)
        release_rows: list[dict[str, Any]] = []
        self.dashboard_recent.clear()
        activity_rows = []
        for row in summary.recent_ops:
            recent_item = QTreeWidgetItem([
                str(row.get("started_at") or row.get("timestamp") or "")[-19:],
                str(row.get("label") or ""),
                str(row.get("status") or ""),
            ])
            recent_item.setData(0, Qt.ItemDataRole.UserRole, row)
            self.dashboard_recent.addTopLevelItem(recent_item)
            activity_rows.append(row)
        if hasattr(self, "dashboard_activity"):
            self._sync_activity_timeline(activity_rows, reset=self.dashboard_activity.count() == 0)
        if hasattr(self, "dashboard_activity_strip"):
            self.dashboard_activity_strip.clear()
            for row in activity_rows[:5]:
                item = QListWidgetItem(f"{str(row.get('started_at') or row.get('timestamp') or '')[-19:]} · {row.get('label') or 'Operation'} · {row.get('status') or ''}")
                item.setData(Qt.ItemDataRole.UserRole, {"kind": "activity", "row": row})
                self.dashboard_activity_strip.addItem(item)
            if not activity_rows:
                empty = QListWidgetItem("No recent activity in this session")
                empty.setFlags(Qt.ItemFlag.NoItemFlags)
                self.dashboard_activity_strip.addItem(empty)
        self.dashboard_drafts.clear()
        draft_rows = list(data.get("drafts") or [])
        for row in draft_rows:
            draft_item = QTreeWidgetItem([str(row.get("kind") or ""), str(row.get("key") or ""), str(row.get("saved_at") or "")])
            draft_item.setData(0, Qt.ItemDataRole.UserRole, row)
            self.dashboard_drafts.addTopLevelItem(draft_item)
        if hasattr(self, "dashboard_drafts_box"):
            self.dashboard_drafts_box.setVisible(bool(draft_rows))
            self.dashboard_drafts_box.setTitle(f"Recoverable drafts · {len(draft_rows)}" if draft_rows else "Recoverable drafts")
            if hasattr(self.dashboard_drafts_box, "setExpanded"):
                self.dashboard_drafts_box.setExpanded(bool(draft_rows))
        if hasattr(self, "dashboard_mission_status"):
            error_count = sum(1 for row in release_rows if str(row.get("status") or "").lower() == "error")
            warning_count = sum(1 for row in release_rows if str(row.get("status") or "").lower() in {"warn", "warning"})
            draft_text = f" · {len(draft_rows)} recoverable draft(s)" if draft_rows else ""
            release_text = "release blocked" if error_count else f"{warning_count} release warning(s)" if warning_count else "release ready"
            if error_count:
                prefix = "🛑"
                state = "error"
            elif warning_count:
                prefix = "⚠"
                state = "warning"
            else:
                prefix = "✦"
                state = "ok"
            self.dashboard_mission_status.setProperty("state", state)
            self.dashboard_mission_status.style().unpolish(self.dashboard_mission_status)
            self.dashboard_mission_status.style().polish(self.dashboard_mission_status)
            cache_state = dict(data.get("health_cache_state") or {})
            cache_note = ""
            if cache_state.get("dirty"):
                cache_note = " · cached health is dirty"
            elif cache_state.get("expired"):
                cache_note = " · cached health expired"
            self.dashboard_mission_status.setText(
                f"{prefix} Command centre: {summary.works_total} works · {summary.works_with_issues} needing attention · {release_text}{draft_text}{cache_note}. Details stay in the relevant workspace."
            )
        self.update_dashboard_recent_detail()
        self.update_tab_badges()
        # Dashboard refresh must not trigger heavy Studio/Media refreshes.
        # Dedicated Studio/Publish tabs refresh themselves when opened or explicitly requested.
        self._studio_dirty = True
        # Release rows are owned by the Publish tab; dashboard stays fast and summary-only.
        self.progress_hint.setText("")
        # Deep health is manual only; use Run health check in the collapsed detail section.

    def _render_dashboard_release_rows(self, release_rows: list[dict[str, Any]]) -> None:
        if not hasattr(self, "dashboard_release"):
            return
        self._last_dashboard_release_rows = list(release_rows or [])
        self.dashboard_release.clear()
        if not release_rows:
            item = QTreeWidgetItem(["Release", "pending", "Deep publish checks are running in the background.", ""])
            item.setForeground(1, self._severity_color("warn"))
            self.dashboard_release.addTopLevelItem(item)
            return
        for row in release_rows:
            release_item = QTreeWidgetItem([
                str(row.get("area") or ""),
                str(row.get("status") or ""),
                str(row.get("detail") or ""),
                "",
            ])
            release_item.setData(0, Qt.ItemDataRole.UserRole, row)
            color = self._severity_color(str(row.get("status") or "info"))
            for col in range(4):
                release_item.setForeground(col, color)
            self.dashboard_release.addTopLevelItem(release_item)
            target = self._release_fix_target(row)
            if target:
                btn = QPushButton(target[0])
                btn.setFixedWidth(86)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _checked=False, r=row: self._go_to_release_fix_target(r))
                self.dashboard_release.setItemWidget(release_item, 3, btn)

    def _apply_dashboard_deep_health_data(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        release_rows = list(data.get("release_checks") or [])
        self._last_dashboard_release_rows = release_rows
        self._apply_readiness_widget(data.get("readiness") or {})
        summary = data.get("summary")
        if summary is not None:
            self._cached_dashboard_action_count = len(getattr(summary, "actions", []) or [])
            self._cached_work_issue_count = int(getattr(summary, "works_with_issues", 0) or 0)
        error_count = sum(1 for row in release_rows if str(row.get("status") or "").lower() == "error")
        warning_count = sum(1 for row in release_rows if str(row.get("status") or "").lower() in {"warn", "warning"})
        state = "error" if error_count else "warning" if warning_count else "ok"
        release_text = "release blocked" if error_count else f"{warning_count} release warning(s)" if warning_count else "release ready"
        if hasattr(self, "dashboard_health_detail"):
            source_recovery = data.get("source_recovery") if isinstance(data.get("source_recovery"), dict) else {}
            total_sources = int(source_recovery.get("total") or 0) if source_recovery else 0
            lines = [
                f"Manual health check finished: {release_text}",
                f"Release rows: {len(release_rows)}",
                f"Source recovery items: {total_sources}",
                "",
                "Top release rows:",
            ]
            lines.extend(f"- {row.get('area') or 'Release'}: {row.get('status') or '-'} — {row.get('detail') or ''}" for row in release_rows[:20])
            if not release_rows:
                lines.append("- No release rows reported.")
            self.dashboard_health_detail.setPlainText("\n".join(lines))
        if hasattr(self, "dashboard_health_detail_section"):
            self.dashboard_health_detail_section.setExpanded(True)
        if hasattr(self, "dashboard_mission_status"):
            self.dashboard_mission_status.setProperty("state", state)
            self.dashboard_mission_status.style().unpolish(self.dashboard_mission_status)
            self.dashboard_mission_status.style().polish(self.dashboard_mission_status)
            self.dashboard_mission_status.setText(f"Manual health finished · {release_text}. Detailed release checks stay in Publish.")
        if hasattr(self, "publish_summary"):
            lines = [f"{row.get('area')}: {row.get('status')} — {row.get('detail')}" for row in release_rows]
            self.publish_summary.setPlainText("\n".join(lines))
        self.update_tab_badges()

    def handle_dashboard_focus_item(self, item: QListWidgetItem) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole) or {}
        if not isinstance(payload, dict):
            return
        if payload.get("kind") == "recent":
            row = payload.get("row") or {}
            shim = QTreeWidgetItem([str(row.get("kind") or ""), str(row.get("target") or ""), str(row.get("label") or "")])
            shim.setData(0, Qt.ItemDataRole.UserRole, row)
            self.open_dashboard_recent_target(shim)
            return
        if payload.get("kind") == "action":
            row = payload.get("row") or {}
            shim = QTreeWidgetItem([str(row.get("label") or "")])
            shim.setData(0, Qt.ItemDataRole.UserRole, payload.get("action"))
            shim.setData(0, Qt.ItemDataRole.UserRole + 1, row)
            self.handle_dashboard_action(shim)

    def open_metric_target(self, target: str) -> None:
        if target == "works":
            self.tabs.setCurrentWidget(self.works_tab)
        elif target == "issues":
            self.tabs.setCurrentWidget(self.works_tab)
            self.work_issue_filter_combo.setCurrentText("Needs attention")
            self.refresh_work_list()
        elif target == "series":
            self.tabs.setCurrentWidget(self.series_tab)
        elif target == "pages":
            self.tabs.setCurrentWidget(self.pages_tab)

    def recent_target_rows(self, limit: int = 10) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for txn in recent_operation_rows(20):
            label = str(txn.get("label") or txn.get("id") or "recent")
            for target in txn.get("targets") or []:
                target_text = str(target).replace("REL::", "")
                kind = ""
                key = ""
                if target_text.startswith("content/works/") and target_text.endswith((".yaml", ".yml")):
                    kind, key = "Work", Path(target_text).stem
                elif target_text.startswith("content/series/") and target_text.endswith((".yaml", ".yml")):
                    kind, key = "Series", Path(target_text).stem
                elif target_text.startswith("content/pages/") and target_text.endswith((".yaml", ".yml")):
                    kind, key = "Page", Path(target_text).stem
                if not kind or not key or (kind, key) in seen:
                    continue
                seen.add((kind, key))
                rows.append({"kind": kind, "target": key, "label": label})
                if len(rows) >= limit:
                    return rows
        return rows

    def open_dashboard_recent_target(self, item: QTreeWidgetItem) -> None:
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        kind = str(row.get("kind") or "").lower()
        target = str(row.get("target") or "")
        if kind == "work":
            self.tabs.setCurrentWidget(self.works_tab)
            self.select_work(target)
        elif kind == "series":
            self.tabs.setCurrentWidget(self.series_tab)
            self.select_series(target)
        elif kind == "page":
            self.tabs.setCurrentWidget(self.pages_tab)
            self.select_page(target)

    def _selected_dashboard_draft(self) -> dict[str, Any]:
        item = self.dashboard_drafts.currentItem() if hasattr(self, "dashboard_drafts") else None
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None else {}

    def restore_dashboard_draft(self, item: QTreeWidgetItem | None = None) -> None:
        row = (item.data(0, Qt.ItemDataRole.UserRole) if item is not None else self._selected_dashboard_draft()) or {}
        kind = str(row.get("kind") or "")
        key = str(row.get("key") or "")
        if not kind or not key:
            return
        self._draft_restore_seen.discard((kind, key))
        if kind == "work":
            self.tabs.setCurrentWidget(self.works_tab)
            self.select_work(key, restore_draft=True)
        elif kind == "series":
            self.tabs.setCurrentWidget(self.series_tab)
            self.select_series(key, restore_draft=True)
        elif kind == "page":
            self.tabs.setCurrentWidget(self.pages_tab)
            self.select_page(key, restore_draft=True)
        elif kind == "authority":
            self.open_authority_panel()
            self.select_authority(key, restore_draft=True)

    def discard_dashboard_draft(self) -> None:
        row = self._selected_dashboard_draft()
        kind = str(row.get("kind") or "")
        key = str(row.get("key") or "")
        if not kind or not key:
            return
        if QMessageBox.question(self, "Discard draft", f"Discard draft for {kind} '{key}'?") != QMessageBox.StandardButton.Yes:
            return
        clear_editor_draft(kind, key)
        self._draft_restore_seen.discard((kind, key))
        self._last_draft_hash.pop((kind, key), None)
        self.refresh_dashboard()
        self.status_message(f"Discarded draft for {kind}: {key}")

    def show_dashboard_draft_menu(self, position) -> None:
        item = self.dashboard_drafts.itemAt(position)
        if item is None:
            return
        self.dashboard_drafts.setCurrentItem(item)
        menu = QMenu(self)
        preview = menu.addAction("Preview")
        restore = menu.addAction("Restore")
        discard = menu.addAction("Discard")
        action = menu.exec(self.dashboard_drafts.viewport().mapToGlobal(position))
        if action == preview:
            self._preview_draft(item)
        elif action == restore:
            self.restore_dashboard_draft(item)
        elif action == discard:
            self.discard_dashboard_draft()

    def show_dashboard_action_menu(self, position) -> None:
        item = self.dashboard_actions.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        dismiss = menu.addAction("Dismiss until next refresh")
        action = menu.exec(self.dashboard_actions.viewport().mapToGlobal(position))
        if action == dismiss:
            row = item.data(0, Qt.ItemDataRole.UserRole + 1) or {}
            self._dismiss_action(str(row.get("label") or item.text(0)), item)

    def update_dashboard_recent_detail(self) -> None:
        item = self.dashboard_recent.currentItem()
        if item is None:
            self.dashboard_recent_detail.setPlainText("Select a recent operation to inspect its detail.")
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        ops = row.get("ops") or []
        targets = row.get("targets") or []
        lines = [
            f"ID: {row.get('id') or '-'}",
            f"Label: {row.get('label') or '-'}",
            f"Status: {row.get('status') or '-'}",
            f"Created: {row.get('created_at') or row.get('started_at') or '-'}",
            f"Updated: {row.get('updated_at') or '-'}",
            "",
            "Targets:",
        ]
        if targets:
            lines.extend([f"- {target}" for target in targets])
        else:
            lines.append("- None")
        lines.extend(["", "Operations:"])
        if ops:
            for op in ops:
                op_type = str(op.get('type') or 'op')
                target = str(op.get('target') or '')
                backup = str(op.get('backup') or '')
                detail = f"- {op_type}"
                if target:
                    detail += f" · {target}"
                if backup:
                    detail += f" · backup {backup}"
                lines.append(detail)
        else:
            lines.append("- No operation detail recorded")
        self.dashboard_recent_detail.setPlainText("\n".join(lines))

    def show_dashboard_recent_menu(self, position) -> None:
        item = self.dashboard_recent.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        undo_batch = menu.addAction("Undo last batch operation")
        menu.addSeparator()
        copy_summary = menu.addAction("Copy summary")
        copy_detail = menu.addAction("Copy detail")
        action = menu.exec(self.dashboard_recent.viewport().mapToGlobal(position))
        if action == undo_batch:
            self.restore_last_completed_operation()
        elif action == copy_summary:
            QApplication.clipboard().setText(f"{item.text(0)} | {item.text(1)} | {item.text(2)}")
            self.status_message("Copied recent operation summary")
        elif action == copy_detail:
            self.update_dashboard_recent_detail()
            QApplication.clipboard().setText(self.dashboard_recent_detail.toPlainText())
            self.status_message("Copied recent operation detail")

    def handle_dashboard_action(self, item: QTreeWidgetItem) -> None:
        action = item.data(0, Qt.ItemDataRole.UserRole)
        if action == "build":
            self.run_build_site()
        elif action == "prepare_publish":
            self.run_prepare_publish()
        elif action == "repair":
            self.tabs.setCurrentWidget(self.works_tab)
            self.work_issue_filter_combo.setCurrentText("Needs attention")
            self.refresh_work_list()
        elif action == "validation":
            self.open_validation_panel()
            self.refresh_validation()
        elif action == "preview":
            self.open_preview()
        elif action == "repair_sources":
            self.run_repair_missing_sources()

    def open_repair_item(self, item: QTreeWidgetItem) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if payload.get("kind") == "work":
            self.tabs.setCurrentWidget(self.works_tab)
            self.select_work(payload.get("id") or "")
        elif payload.get("kind") == "series":
            self.tabs.setCurrentWidget(self.series_tab)
            self.select_series(payload.get("id") or "")

    # ---------- works ----------
    def build_works_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        smart_row = QHBoxLayout()
        self.work_smart_filter = QLineEdit()
        self.work_smart_filter.setPlaceholderText("Search works…  Use series:name, status:draft, tag:landscape, published:yes, issue:missing")
        self.work_search = self.work_smart_filter
        smart_row.addWidget(self.work_smart_filter, 1)

        self.work_gallery_grid_btn = QPushButton("Gallery")
        self.work_gallery_grid_btn.setCheckable(True)
        self.work_gallery_grid_btn.setToolTip("Image-first gallery view is the default Works workspace.")
        self.work_gallery_grid_btn.setAccessibleName("Switch to gallery view")
        self.work_gallery_list_btn = QPushButton("List view")
        self.work_gallery_list_btn.setToolTip("Secondary text-table view for bulk inspection.")
        self.work_gallery_list_btn.setAccessibleName("Switch to list view")
        self.work_gallery_toggle_btn = self.work_gallery_grid_btn
        self.work_gallery_grid_btn.clicked.connect(self.toggle_work_gallery_view)
        self.work_gallery_list_btn.clicked.connect(lambda: self.toggle_work_gallery_view(False))
        smart_row.addWidget(self.work_gallery_grid_btn)
        smart_row.addWidget(self.work_gallery_list_btn)
        self.work_inspector_toggle_btn = QPushButton("Inspector")
        self.work_inspector_toggle_btn.setToolTip("Open the contextual inspector on the right edge of the workspace.")
        self.work_inspector_toggle_btn.clicked.connect(self.toggle_context_inspector)
        smart_row.addWidget(self.work_inspector_toggle_btn)

        self.work_filter_preset_combo = QComboBox()
        self.work_filter_preset_combo.setEditable(True)
        self.work_filter_preset_combo.lineEdit().setReadOnly(True)
        self.work_filter_preset_combo.setMinimumWidth(150)
        self.work_filter_preset_combo.setToolTip("Apply saved Works filter presets.")
        self.work_filter_preset_combo.currentTextChanged.connect(self.on_work_filter_preset_selected)
        saved_filters_menu = QMenu(self)
        saved_filters_action = saved_filters_menu.addAction("Apply selected saved filter")
        saved_filters_action.triggered.connect(lambda: self.on_work_filter_preset_selected(self.work_filter_preset_combo.currentText()))
        saved_filters_menu.addSeparator()
        save_filter_action = saved_filters_menu.addAction("Save current filter…")
        save_filter_action.triggered.connect(self.save_current_work_filter_preset)
        delete_filter_action = saved_filters_menu.addAction("Delete selected saved filter…")
        delete_filter_action.triggered.connect(self.delete_current_work_filter_preset)
        self.work_save_preset_btn = QPushButton("Save filter")
        self.work_save_preset_btn.setToolTip("Save the current search and facet filters as a reusable Works preset.")
        self.work_save_preset_btn.clicked.connect(self.save_current_work_filter_preset)
        self.work_delete_preset_btn = QPushButton("Delete")
        self.work_delete_preset_btn.setToolTip("Delete the selected custom Works preset.")
        self.work_delete_preset_btn.clicked.connect(self.delete_current_work_filter_preset)
        saved_filters_btn = QPushButton("Saved Filters ▾")
        saved_filters_btn.setMenu(saved_filters_menu)
        saved_filters_btn.setToolTip("Saved filter presets are secondary. Use the visible filters for daily review work.")
        smart_row.addWidget(self.work_filter_preset_combo)
        smart_row.addWidget(saved_filters_btn)

        self.work_clear_filters_btn = QPushButton("Clear filters")
        self.work_clear_filters_btn.clicked.connect(self.clear_work_filters)
        smart_row.addWidget(self.work_clear_filters_btn)
        layout.addLayout(smart_row)

        filter_bar = QFrame()
        filter_bar.setObjectName("worksFilterBar")
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.setSpacing(8)
        filter_label = QLabel("Filters")
        filter_label.setObjectName("sectionLabel")
        filter_layout.addWidget(filter_label)

        self.work_series_filter_combo = QComboBox()
        self.work_series_filter_combo.addItems(self._all_work_series_filter_values())
        self.work_series_filter_combo.setMinimumWidth(190)
        self.work_series_filter_combo.setToolTip("Filter works by editorial series.")
        self.work_review_filter_combo = QComboBox()
        self.work_review_filter_combo.addItems(["All"] + PUBLISH_STATES)
        self.work_review_filter_combo.setMinimumWidth(120)
        self.work_review_filter_combo.setToolTip("Filter works by review status: draft, review, published, archived.")
        self.work_pub_filter_combo = QComboBox()
        self.work_pub_filter_combo.addItems(["All", "Published", "Unpublished"])
        self.work_pub_filter_combo.setMinimumWidth(130)
        self.work_pub_filter_combo.setToolTip("Filter works by the public published flag.")
        self.work_issue_filter_combo = QComboBox()
        self.work_issue_filter_combo.addItems(["All works", "Needs attention", "Missing source", "Weak metadata", "Missing caption", "Weak alt text", "Missing thumbnail"])
        self.work_issue_filter_combo.setMinimumWidth(160)
        self.work_issue_filter_combo.setToolTip("Filter works by source, metadata, caption, alt-text, and thumbnail health.")

        def add_filter(label: str, widget: QWidget, stretch: int = 0) -> None:
            filter_layout.addWidget(QLabel(label))
            filter_layout.addWidget(widget, stretch)

        add_filter("Series", self.work_series_filter_combo, 1)
        add_filter("Review", self.work_review_filter_combo)
        add_filter("Published", self.work_pub_filter_combo)
        add_filter("Issues", self.work_issue_filter_combo)
        filter_layout.addStretch(1)
        filter_layout.addWidget(self.work_save_preset_btn)
        filter_layout.addWidget(self.work_delete_preset_btn)
        layout.addWidget(filter_bar)

        self.work_filter_summary = QLabel("All works · type to filter, or use Series / Review / Published / Issues facets")
        self.work_filter_summary.setObjectName("quietHint")
        self.work_filter_summary.setWordWrap(True)
        layout.addWidget(self.work_filter_summary)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setObjectName("works-main-splitter")
        self.works_main_splitter = split
        layout.addWidget(split, 1)
        left = QWidget(); left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.work_tree = QTreeWidget()
        self.work_tree.setHeaderLabels(["ID", "Title", "Series", "Review", "Published", "Score", "Source", "Issues"])
        self.work_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.work_tree.setColumnWidth(0, 180)
        self.work_tree.setColumnWidth(1, 280)
        self.work_tree.setColumnWidth(2, 150)
        self.work_tree.setColumnWidth(3, 110)
        self.work_tree.setColumnWidth(4, 95)
        self.work_tree.setColumnWidth(5, 70)
        self.work_tree.setColumnWidth(6, 115)
        self.work_tree.setColumnWidth(7, 110)
        self.work_tree.setSortingEnabled(True)
        self.work_tree.setUniformRowHeights(True)
        self.work_tree.setIconSize(QSize(52, 52))
        self.work_tree.itemSelectionChanged.connect(self.on_work_selection_changed)
        self.work_tree.itemDoubleClicked.connect(self.quick_edit_work_list_cell)
        self.work_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.work_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.work_tree.customContextMenuRequested.connect(self.show_work_tree_menu)
        self.work_tree.verticalScrollBar().valueChanged.connect(lambda _value=None: self._schedule_visible_thumbnail_load())
        self.work_tree.setItemDelegate(WorkListDelegate(self.work_tree))
        self._polish_data_tree(self.work_tree, "works")
        self.work_tree.hide()

        self.work_table = QTableView()
        self.work_table.setObjectName("worksModelTable")
        self.work_table.setModel(self._works_model)
        self.work_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.work_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.work_table.setSortingEnabled(True)
        self.work_table.setAlternatingRowColors(True)
        self.work_table.setIconSize(QSize(52, 52))
        self.work_table.verticalHeader().hide()
        self.work_table.verticalHeader().setDefaultSectionSize(58)
        self.work_table.horizontalHeader().setStretchLastSection(False)
        self.work_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, width in enumerate((180, 300, 160, 110, 95, 75, 120, 115)):
            self.work_table.setColumnWidth(col, width)
        self.work_table.setItemDelegate(WorkListDelegate(self.work_table))
        self.work_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.work_table.customContextMenuRequested.connect(self.show_work_table_menu)
        self.work_table.hide()
        self.work_table.doubleClicked.connect(self.quick_edit_work_model_cell)
        self.work_table.verticalScrollBar().valueChanged.connect(lambda _value=None: self._schedule_visible_thumbnail_load())
        if self.work_table.selectionModel() is not None:
            self.work_table.selectionModel().selectionChanged.connect(lambda *_args: self.on_work_selection_changed())
        left_layout.addWidget(self.work_table)
        self.work_gallery_scroll = QScrollArea()
        self.work_gallery_scroll.setWidgetResizable(True)
        self.work_gallery_host = QWidget()
        self.work_gallery_grid = QGridLayout(self.work_gallery_host)
        self.work_gallery_grid.setContentsMargins(10, 10, 10, 10)
        self.work_gallery_grid.setSpacing(10)
        self.work_gallery_scroll.setWidget(self.work_gallery_host)
        self.work_gallery_scroll.show()
        self._work_gallery_scroll_resize_event = self.work_gallery_scroll.resizeEvent
        def _gallery_resize(event):
            self._work_gallery_scroll_resize_event(event)
            self._schedule_work_gallery_reflow()
        self.work_gallery_scroll.resizeEvent = _gallery_resize
        left_layout.addWidget(self.work_gallery_scroll)
        button_row = QHBoxLayout()
        add_btn = QPushButton("Add image…")
        add_btn.clicked.connect(self.open_add_image_dialog)
        replace_btn = QPushButton("Replace image…")
        replace_btn.clicked.connect(self.open_replace_image_dialog)
        duplicate_btn = QPushButton("Duplicate")
        duplicate_btn.clicked.connect(self.duplicate_selected_work)
        delete_btn = QPushButton("Delete image…")
        delete_btn.setObjectName("destructiveButton")
        delete_btn.setToolTip("Delete the selected work and its original/generated image assets after confirmation.")
        delete_btn.clicked.connect(self.safe_remove_current_work)
        select_visible = QPushButton("Select visible")
        select_visible.clicked.connect(self.select_all_visible_works)
        deselect_visible = QPushButton("Deselect")
        deselect_visible.clicked.connect(self.deselect_all_visible_works)
        library_more_menu = QMenu(self)
        for label, slot in (
            ("Bulk ingest…", self.open_bulk_image_ingest_dialog),
            ("Metadata audit…", self.open_metadata_audit_dialog),
            ("Duplicate scan…", self.open_duplicate_scan_dialog),
            ("Public impact preview…", self.show_current_work_impact_report),
            ("Delete selected image…", self.safe_remove_current_work),
        ):
            action = QAction(label, self)
            action.triggered.connect(slot)
            library_more_menu.addAction(action)
        library_more_btn = QPushButton("Library tools ▾")
        library_more_btn.setMenu(library_more_menu)
        library_more_btn.setToolTip("Secondary library tools are grouped here to reduce visual load.")
        for widget in (add_btn, replace_btn, duplicate_btn, delete_btn, select_visible, deselect_visible, library_more_btn):
            button_row.addWidget(widget)
        button_row.addStretch(1)
        left_layout.addLayout(button_row)

        self.work_batch_bar = QFrame()
        self.work_batch_bar.setObjectName("workBatchBar")
        batch_row = QHBoxLayout(self.work_batch_bar)
        batch_row.setContentsMargins(8, 6, 8, 6)
        self.work_batch_label = QLabel("Batch · 0 selected")
        batch_row.addWidget(self.work_batch_label)
        batch_publish_btn = QPushButton("Publish")
        batch_publish_btn.clicked.connect(self.batch_publish_selected_works)
        batch_unpublish_btn = QPushButton("Unpublish")
        batch_unpublish_btn.clicked.connect(self.batch_unpublish_selected_works)
        batch_review_btn = QPushButton("Mark review")
        batch_review_btn.clicked.connect(self.batch_mark_review_selected_works)
        self.batch_move_series_combo = QComboBox()
        move_btn = QPushButton("Move")
        move_btn.clicked.connect(self.batch_move_selected_works)
        bulk_edit_btn = QPushButton("Bulk edit…")
        bulk_edit_btn.clicked.connect(self.open_bulk_edit_dialog)
        for widget in (batch_publish_btn, batch_unpublish_btn, batch_review_btn, self.batch_move_series_combo, move_btn, bulk_edit_btn):
            batch_row.addWidget(widget)
        batch_row.addStretch(1)
        self.work_batch_bar.hide()
        left_layout.addWidget(self.work_batch_bar)
        split.addWidget(left)

        # Redundant middle preview removed: the Works workspace already has
        # the editor image preview and the right-side context inspector preview.
        # Keeping one image focal surface avoids wasting horizontal space and
        # eliminates the duplicate preview column.

        right_panel = QWidget(); self.work_editor_panel = right_panel; right_panel_layout = QVBoxLayout(right_panel); right_panel_layout.setContentsMargins(0, 0, 0, 0)
        work_header = QHBoxLayout()
        self.work_breadcrumb = QLabel("Works  ›  No work selected")
        self.work_breadcrumb.setObjectName("breadcrumb")
        self.work_autosave_status = QLabel("")
        self.work_autosave_status.setObjectName("autosaveStatus")
        work_header.addWidget(self.work_breadcrumb, 1)
        work_header.addWidget(self.work_autosave_status)
        right_panel_layout.addLayout(work_header)
        self.work_health_rail = QFrame()
        self.work_health_rail.setObjectName("workHealthRail")
        health_layout = QHBoxLayout(self.work_health_rail)
        health_layout.setContentsMargins(8, 6, 8, 6)
        health_layout.setSpacing(6)
        self.work_health_chips = {
            "series": StatusBadge("Series", "info"),
            "alt": StatusBadge("Alt", "info"),
            "caption": StatusBadge("Caption", "info"),
            "asset": StatusBadge("Asset", "info"),
            "publish": StatusBadge("Publish", "info"),
        }
        for chip in self.work_health_chips.values():
            health_layout.addWidget(chip)
        health_layout.addStretch(1)
        self.work_health_section = CollapsibleSection("Asset Health", "metadata, source and publish checks", expanded=False)
        self.work_health_section.add_widget(self.work_health_rail)
        right_panel_layout.addWidget(self.work_health_section)
        editor = QScrollArea(); editor.setWidgetResizable(True)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.work_editor_scroll = editor
        editor_host = QWidget(); self.work_editor_host = editor_host; editor_layout = QVBoxLayout(editor_host)
        editor_layout.setContentsMargins(8, 8, 8, 8)
        editor_layout.setSpacing(10)
        editor.setWidget(editor_host)
        # Phase 12: focused, progressive-disclosure work editor.
        # Daily editing is a two-column surface: core metadata on the left,
        # image preview and rare fields behind explicit disclosure on the right.
        work_editor_grid = QHBoxLayout()
        self.work_editor_grid = work_editor_grid
        work_editor_grid.setSpacing(14)
        editor_layout.addLayout(work_editor_grid)

        core_column = QFrame()
        self.work_core_column = core_column
        core_column.setObjectName("workspaceCard")
        core_column.setMinimumWidth(320)
        core_column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        core_layout = QVBoxLayout(core_column)
        core_layout.setContentsMargins(14, 14, 14, 14)
        core_layout.setSpacing(10)
        core_title = QLabel("Core work fields")
        core_title.setObjectName("sectionLabel")
        core_layout.addWidget(core_title)
        core_hint = QLabel("Edit the few fields used most often: title, series, review state, tags, and year.")
        core_hint.setObjectName("quietHint")
        core_hint.setWordWrap(True)
        core_layout.addWidget(core_hint)

        identity_form = QFormLayout()
        identity_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.work_id_edit = QLineEdit()
        self.work_id_edit.setReadOnly(True)
        self.work_id_edit.setToolTip("Locked by default. Use the safe rename control so related references and assets are updated together.")
        id_row = QHBoxLayout()
        id_row.addWidget(self.work_id_edit, 1)
        self.work_unlock_id_btn = QPushButton("Rename ID safely…")
        self.work_unlock_id_btn.setToolTip("Unlocks the Work ID field for this selection only. Saving still runs the rename transaction preview.")
        self.work_unlock_id_btn.clicked.connect(self.unlock_current_work_id_for_safe_rename)
        id_row.addWidget(self.work_unlock_id_btn)
        id_wrap = QWidget(); id_wrap.setLayout(id_row); identity_form.addRow("Work ID", id_wrap)
        core_layout.addLayout(identity_form)

        self.work_title_edit = QLineEdit()
        self.work_title_counter = self._counted_counter(self.work_title_edit, 12, 80)
        self.work_series_combo = QComboBox()
        self.work_year_edit = QLineEdit()
        self.work_review_combo = QComboBox(); self.work_review_combo.addItems(PUBLISH_STATES)
        self.work_published_check = QCheckBox("Published")
        self.work_tags_edit = TagInputWidget()
        try:
            self.work_tags_edit.set_vocabulary([str(row.get("tag") or "") for row in tag_vocabulary_rows()])
        except Exception as exc:
            self._log_warning(f"Could not load tag vocabulary: {exc}")
        core_layout.addWidget(FormRow("Title", self.work_title_edit, "Public title used across gallery, series, and SEO metadata.", required=True, annotation=self.work_title_counter))
        core_layout.addWidget(FormRow("Series", self.work_series_combo, "Choose the editorial series this work belongs to.", required=True))
        publish_strip = QFrame()
        publish_strip.setObjectName("workPublishStrip")
        publish_strip_layout = QHBoxLayout(publish_strip)
        publish_strip_layout.setContentsMargins(10, 8, 10, 8)
        publish_strip_layout.addWidget(QLabel("Status"))
        publish_strip_layout.addWidget(self.work_review_combo, 1)
        publish_strip_layout.addWidget(self.work_published_check)
        publish_strip_layout.addWidget(QLabel("Last saved:"))
        self.work_last_saved_inline = QLabel("—")
        self.work_last_saved_inline.setObjectName("quietHint")
        publish_strip_layout.addWidget(self.work_last_saved_inline)
        core_layout.addWidget(publish_strip)
        core_layout.addWidget(FormRow("Tags", self.work_tags_edit, "Comma/Enter creates curated tag chips. Keep tags editorial, not noisy."))
        core_layout.addWidget(FormRow("Year", self.work_year_edit, "Displayed in metadata and series contexts."))
        core_layout.addStretch(1)
        work_editor_grid.addWidget(core_column, 3)

        detail_column = QFrame()
        self.work_detail_column = detail_column
        detail_column.setObjectName("workspaceCard")
        detail_column.setMinimumWidth(360)
        detail_column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        detail_layout = QVBoxLayout(detail_column)
        detail_layout.setContentsMargins(14, 14, 14, 14)
        detail_layout.setSpacing(10)
        image_section = CollapsibleSection("Image preview", "focal point and source status", expanded=True)
        focal_form = QFormLayout()
        focal_row = QHBoxLayout()
        self.work_focal_x = QSpinBox(); self.work_focal_x.setRange(0, 100); self.work_focal_x.setSuffix("% X")
        self.work_focal_y = QSpinBox(); self.work_focal_y.setRange(0, 100); self.work_focal_y.setSuffix("% Y")
        focal_row.addWidget(QLabel("X")); focal_row.addWidget(self.work_focal_x); focal_row.addSpacing(12); focal_row.addWidget(QLabel("Y")); focal_row.addWidget(self.work_focal_y); focal_row.addStretch(1)
        focal_wrap = QWidget(); focal_wrap.setLayout(focal_row); focal_form.addRow("Focal point", focal_wrap)
        image_section.add_layout(focal_form)
        self.work_image_preview = FocalPointLabel("No image")
        self.work_image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.work_image_preview.setMinimumHeight(220)
        self.work_image_preview.setMaximumHeight(360)
        self.work_image_preview.setObjectName("imagePreview")
        self.work_image_preview.set_focal_controls(self.work_focal_x, self.work_focal_y)
        image_section.add_widget(self.work_image_preview)
        self.work_image_status_label = QLabel("Source status appears after a work is selected.")
        self.work_image_status_label.setObjectName("quietHint")
        self.work_image_status_label.setWordWrap(True)
        image_section.add_widget(self.work_image_status_label)
        detail_layout.addWidget(image_section)

        more_section = CollapsibleSection("More fields", "narrative, usage flags, quality notes and technical metadata", expanded=False)
        advanced_form = QFormLayout()
        advanced_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.work_location_edit = QLineEdit(); advanced_form.addRow("Location", self.work_location_edit)
        flags_row = QHBoxLayout()
        self.work_hero_check = QCheckBox("Hero safe"); self.work_hero_check.setChecked(True)
        self.work_grid_check = QCheckBox("Grid safe"); self.work_grid_check.setChecked(True)
        self.work_social_check = QCheckBox("Social safe")
        for flag in (self.work_hero_check, self.work_grid_check, self.work_social_check):
            flag.setObjectName("segmentedControl")
            flags_row.addWidget(flag)
        flags_row.addStretch(1)
        flags_wrap = QWidget(); flags_wrap.setLayout(flags_row); advanced_form.addRow("Usage eligibility", flags_wrap)
        more_section.add_layout(advanced_form)
        self.work_alt_edit = QPlainTextEdit(); self.work_alt_edit.setMinimumHeight(86); self.work_alt_edit.setMaximumHeight(150)
        self.work_alt_stats = self._counted_counter(self.work_alt_edit, 40, 125)
        more_section.add_widget(FormRow("Alt text", self.work_alt_edit, "Accessible description; concrete, visual, and concise.", required=True, annotation=self.work_alt_stats))
        self.work_caption_edit = QPlainTextEdit(); self.work_caption_edit.setMinimumHeight(126); self.work_caption_edit.setMaximumHeight(220)
        self.work_caption_stats = self._counted_counter(self.work_caption_edit, 50, 300)
        more_section.add_widget(FormRow("Caption", self.work_caption_edit, "Public caption; avoid explaining the photograph too heavily.", annotation=self.work_caption_stats))

        layout_section = CollapsibleSection("Presentation layout", "per-image Portfolio / Series size and crop controls", expanded=False)
        layout_form = QFormLayout()
        layout_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.work_portfolio_layout_combo = QComboBox(); self.work_portfolio_layout_combo.addItems(LAYOUT_CONTROL_VALUES)
        self.work_portfolio_layout_combo.setToolTip("Portfolio card size token. Use auto for the site-generated rhythm.")
        self.work_series_layout_combo = QComboBox(); self.work_series_layout_combo.addItems(LAYOUT_CONTROL_VALUES)
        self.work_series_layout_combo.setToolTip("Series story-frame size token. Use full/wide sparingly for important story beats.")
        self.work_portfolio_ratio_edit = QLineEdit()
        self.work_portfolio_ratio_edit.setPlaceholderText("optional, e.g. 4 / 3")
        self.work_portfolio_ratio_edit.setToolTip("Optional Portfolio crop ratio. Leave blank to use the image/default ratio.")
        self.work_series_ratio_edit = QLineEdit()
        self.work_series_ratio_edit.setPlaceholderText("optional, e.g. 16 / 9")
        self.work_series_ratio_edit.setToolTip("Optional Series crop ratio. Leave blank to use the image/default ratio.")
        layout_form.addRow("Portfolio card", self.work_portfolio_layout_combo)
        layout_form.addRow("Series frame", self.work_series_layout_combo)
        layout_form.addRow("Portfolio ratio", self.work_portfolio_ratio_edit)
        layout_form.addRow("Series ratio", self.work_series_ratio_edit)
        layout_section.add_layout(layout_form)
        layout_hint = QLabel("Use constrained tokens only. This gives image-by-image control while keeping the site consistent. Ratios use width / height, for example 4 / 3 or 16 / 9.")
        layout_hint.setObjectName("quietHint")
        layout_hint.setWordWrap(True)
        layout_section.add_widget(layout_hint)
        self.work_layout_summary = QLabel("Layout: auto · Ratios: intrinsic")
        self.work_layout_summary.setObjectName("quietHint")
        self.work_layout_summary.setWordWrap(True)
        layout_section.add_widget(self.work_layout_summary)
        detail_layout.addWidget(layout_section)

        self.work_issue_hint = QPlainTextEdit(); self.work_issue_hint.setReadOnly(True); self.work_issue_hint.setMinimumHeight(96); self.work_issue_hint.setMaximumHeight(160)
        more_section.add_widget(self.work_issue_hint)
        more_section.add_widget(QLabel("Private curation note · not published"))
        self.work_private_note_edit = QPlainTextEdit(); self.work_private_note_edit.setMinimumHeight(80); self.work_private_note_edit.setMaximumHeight(160); more_section.add_widget(self.work_private_note_edit)
        save_work_note_btn = QPushButton("Save private work note")
        save_work_note_btn.clicked.connect(self.save_current_work_private_note)
        more_section.add_widget(save_work_note_btn)
        detail_layout.addWidget(more_section, 1)
        work_editor_grid.addWidget(detail_column, 3)
        editor_layout.addStretch(1)
        right_panel_layout.addWidget(editor, 1)
        actions = QHBoxLayout()
        self.work_save_btn = QPushButton("Save work · Ctrl+S")
        save_btn = self.work_save_btn
        save_btn.clicked.connect(self.save_current_work)
        refresh_btn = QPushButton("Reload")
        refresh_btn.clicked.connect(self.reload_current_work)
        work_more_menu = QMenu(self)
        for label, slot in (
            ("Compare derivatives…", self.open_derivative_compare_dialog),
            ("Lineage…", self.open_work_lineage_dialog),
            ("Verify assets", self.verify_current_work_assets),
            ("Preview payload", self.show_current_work_payload_preview),
            ("Save template", self.save_current_work_template),
            ("Use template…", self.apply_work_template_to_current),
        ):
            action = QAction(label, self)
            action.triggered.connect(slot)
            work_more_menu.addAction(action)
        work_more_btn = QPushButton("More work actions ▾")
        work_more_btn.setMenu(work_more_menu)
        work_more_btn.setToolTip("Rare work diagnostics and template tools live here to keep the editor focused.")
        nav_hint = QLabel("Prev / Next work · Alt+Up / Alt+Down")
        actions.addWidget(save_btn); actions.addWidget(refresh_btn); actions.addWidget(work_more_btn); actions.addStretch(1); actions.addWidget(nav_hint)
        right_panel_layout.addLayout(actions)
        split.addWidget(right_panel)
        split.setHandleWidth(8)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 2)
        split.setSizes([480, 1120])
        QTimer.singleShot(0, self._apply_works_responsive_layout)

        self.work_search.textChanged.connect(self.on_work_filters_changed)
        for widget in [self.work_series_filter_combo, self.work_review_filter_combo, self.work_pub_filter_combo, self.work_issue_filter_combo]:
            widget.currentTextChanged.connect(self.on_work_facet_filters_changed)
        self.work_series_combo.currentTextChanged.connect(lambda _value=None: self.schedule_work_preview_update())
        self.work_id_edit.textChanged.connect(lambda _value=None: self.schedule_work_preview_update())
        for widget in [self.work_id_edit, self.work_title_edit, self.work_year_edit, self.work_location_edit, self.work_tags_edit]:
            widget.textChanged.connect(lambda _value=None: self.schedule_editor_autosave("work"))
            widget.textChanged.connect(lambda _value=None: self.schedule_work_validation())
        for widget in [self.work_alt_edit, self.work_caption_edit]:
            widget.textChanged.connect(lambda: self.schedule_editor_autosave("work"))
            widget.textChanged.connect(lambda: self.schedule_work_validation())
        self.work_alt_edit.textChanged.connect(self.update_work_text_stats)
        self.work_caption_edit.textChanged.connect(self.update_work_text_stats)
        for widget in [self.work_portfolio_ratio_edit, self.work_series_ratio_edit]:
            widget.textChanged.connect(lambda _value=None: self.schedule_editor_autosave("work"))
            widget.textChanged.connect(lambda _value=None: self.schedule_work_validation())
            widget.textChanged.connect(lambda _value=None: self.update_work_layout_summary())
        for widget in [self.work_series_combo, self.work_review_combo, self.work_portfolio_layout_combo, self.work_series_layout_combo]:
            widget.currentTextChanged.connect(lambda _value=None: self.schedule_editor_autosave("work"))
            widget.currentTextChanged.connect(lambda _value=None: self.schedule_work_validation())
        self.work_portfolio_layout_combo.currentTextChanged.connect(lambda _value=None: self.update_work_layout_summary())
        self.work_series_layout_combo.currentTextChanged.connect(lambda _value=None: self.update_work_layout_summary())
        self.work_review_combo.currentTextChanged.connect(self._sync_work_publish_controls_from_review)
        self.work_published_check.toggled.connect(self._sync_work_publish_controls_from_checkbox)
        for widget in [self.work_published_check, self.work_hero_check, self.work_grid_check, self.work_social_check]:
            widget.toggled.connect(lambda _state=None: self.schedule_editor_autosave("work"))
        for widget in [self.work_focal_x, self.work_focal_y]:
            widget.valueChanged.connect(lambda _value=None: self.schedule_editor_autosave("work"))
            widget.valueChanged.connect(lambda _value=None: self.schedule_work_validation())
        self.refresh_work_filter_preset_options()
        pending_filters = getattr(self, "_pending_work_filter_snapshot", None)
        if isinstance(pending_filters, dict):
            self.set_work_filter_snapshot(pending_filters, refresh=False)
        self.update_work_filter_preset_indicator()
        self._apply_works_tab_order()
        return tab

    def _apply_works_tab_order(self) -> None:
        order = [
            getattr(self, "work_title_edit", None),
            getattr(self, "work_id_edit", None),
            getattr(self, "work_series_combo", None),
            getattr(self, "work_review_combo", None),
            getattr(self, "work_alt_edit", None),
            getattr(self, "work_caption_edit", None),
            getattr(self, "work_tags_edit", None),
            getattr(self, "work_portfolio_layout_combo", None),
            getattr(self, "work_series_layout_combo", None),
            getattr(self, "work_portfolio_ratio_edit", None),
            getattr(self, "work_series_ratio_edit", None),
            getattr(self, "work_focal_x", None),
            getattr(self, "work_focal_y", None),
        ]
        widgets = [widget for widget in order if widget is not None]
        for left, right in zip(widgets, widgets[1:]):
            self.setTabOrder(left, right)

    def _sync_work_publish_controls_from_review(self, value: str) -> None:
        if getattr(self, "_suspend_work_form", False) or not hasattr(self, "work_published_check"):
            return
        review = str(value or "").strip().lower()
        target = review == "published"
        if self.work_published_check.isChecked() != target:
            with signals_blocked(self.work_published_check):
                self.work_published_check.setChecked(target)
        self.schedule_work_validation()

    def _sync_work_publish_controls_from_checkbox(self, checked: bool) -> None:
        if getattr(self, "_suspend_work_form", False) or not hasattr(self, "work_review_combo"):
            return
        current = str(self.work_review_combo.currentText() or "").strip().lower()
        target = "published" if checked else ("review" if current == "published" else current or "draft")
        if current != target:
            with signals_blocked(self.work_review_combo):
                self.work_review_combo.setCurrentText(target)
        self.schedule_work_validation()

    def unlock_current_work_id_for_safe_rename(self) -> None:
        if not hasattr(self, "work_id_edit"):
            return
        current = str(getattr(self, "_current_work_id", "") or "")
        if not current:
            QMessageBox.information(self, "No work selected", "Select a saved work before renaming its Work ID.")
            return
        if not self.work_id_edit.isReadOnly():
            self.work_id_edit.setReadOnly(True)
            if hasattr(self, "work_unlock_id_btn"):
                self.work_unlock_id_btn.setText("Rename ID safely…")
            self.status_message("Work ID locked again")
            return
        reply = QMessageBox.question(
            self,
            "Unlock Work ID rename",
            "Work IDs are connected to YAML, source images, derivatives, relationships, drafts, and runtime references. Unlock only when you intend to run the safe rename transaction on Save.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.work_id_edit.setReadOnly(False)
        if hasattr(self, "work_unlock_id_btn"):
            self.work_unlock_id_btn.setText("Lock ID")
        self.work_id_edit.setFocus()
        self.work_id_edit.selectAll()
        self.status_message("Work ID unlocked · saving will show the rename transaction preview")

    def _all_work_series_filter_values(self) -> list[str]:
        """Series choices for the Works filter: declared series first, then any orphan work series."""
        values: list[str] = []
        seen: set[str] = set()

        def add(value: Any) -> None:
            slug = str(value or "").strip()
            if slug and slug.casefold() not in seen:
                seen.add(slug.casefold())
                values.append(slug)

        try:
            for slug in available_series_slugs():
                add(slug)
        except Exception as exc:
            self._log_warning(f"Could not load declared series for Works filter: {exc}")
        try:
            orphan_values: list[str] = []
            known = {item.casefold() for item in values}
            for row in load_work_entries():
                slug = str((row or {}).get("series") or "").strip()
                if slug and slug.casefold() not in known:
                    orphan_values.append(slug)
                    known.add(slug.casefold())
            for slug in sorted(orphan_values, key=str.lower):
                add(slug)
        except Exception as exc:
            self._log_warning(f"Could not load work series values for Works filter: {exc}")
        return ["All series"] + values

    def _valid_work_series_filter_value(self, value: str) -> str:
        value = str(value or "").strip()
        values = self._all_work_series_filter_values()
        return value if value in values else "All series"

    def _commit_pending_editor_edits(self, kind: str = "") -> None:
        """Flush small composite editor widgets before manual Save/Ctrl+S reads the form."""
        kind = str(kind or "")
        changed = False
        tag_widgets: list[TagInputWidget] = []
        if kind in {"", "work"} and hasattr(self, "work_tags_edit"):
            tag_widgets.append(self.work_tags_edit)
        for widget in tag_widgets:
            try:
                if widget.commit_pending_text():
                    changed = True
            except Exception as exc:
                self._log_warning(f"Could not commit pending tag input before save: {exc}")
        if changed and kind == "work":
            self.schedule_editor_autosave("work")
            self.update_work_text_stats()

    def _parse_work_smart_filter(self, value: str) -> dict[str, str]:
        """Parse one search box into backend filters.

        Supported tokens: series:name, status:draft, review:approved,
        tag:landscape, published:yes/no, issue:missing. Unknown tokens remain
        part of full-text search so the control stays forgiving.
        """
        snapshot = dict(self._default_work_filter_presets.get("All works", {}))
        snapshot.setdefault("search", "")
        snapshot.setdefault("series", "All series")
        snapshot.setdefault("review", "All")
        snapshot.setdefault("published", "All")
        snapshot.setdefault("issue", "All works")
        free: list[str] = []
        try:
            parts = shlex.split(str(value or ""))
        except Exception:
            parts = str(value or "").split()
        for part in parts:
            if ":" not in part:
                free.append(part)
                continue
            key, raw = part.split(":", 1)
            key = key.strip().lower()
            raw = raw.strip()
            if not raw:
                continue
            normalized = raw.replace("_", " ").strip()
            if key in {"series", "s"}:
                snapshot["series"] = normalized
            elif key in {"status", "review", "state"}:
                snapshot["review"] = normalized
            elif key in {"published", "pub", "visible"}:
                snapshot["published"] = "Published" if normalized.lower() in {"yes", "true", "1", "published", "visible"} else "Unpublished" if normalized.lower() in {"no", "false", "0", "unpublished", "hidden"} else "All"
            elif key in {"issue", "issues", "health"}:
                snapshot["issue"] = normalized.title() if normalized.lower() != "all" else "All works"
            elif key in {"tag", "tags"}:
                free.append(normalized)
            else:
                free.append(part)
        snapshot["search"] = " ".join(free).strip()
        return snapshot

    def _compose_work_smart_filter(self, snapshot: dict[str, str]) -> str:
        parts: list[str] = []
        search = str(snapshot.get("search") or "").strip()
        if search:
            parts.append(search)
        series = str(snapshot.get("series") or "All series").strip()
        if series and series != "All series":
            parts.append(f"series:{shlex.quote(series)}")
        review = str(snapshot.get("review") or "All").strip()
        if review and review != "All":
            parts.append(f"status:{shlex.quote(review)}")
        published = str(snapshot.get("published") or "All").strip()
        if published and published != "All":
            parts.append("published:yes" if published == "Published" else "published:no")
        issue = str(snapshot.get("issue") or "All works").strip()
        if issue and issue != "All works":
            parts.append(f"issue:{shlex.quote(issue.lower())}")
        return " ".join(parts)

    def _work_filter_widgets_ready(self) -> bool:
        return all(hasattr(self, name) for name in (
            "work_search",
            "work_series_filter_combo",
            "work_review_filter_combo",
            "work_pub_filter_combo",
            "work_issue_filter_combo",
            "work_filter_preset_combo",
            "work_save_preset_btn",
            "work_clear_filters_btn",
        ))

    def current_work_filter_snapshot(self) -> dict[str, str]:
        if not self._work_filter_widgets_ready():
            pending = getattr(self, "_pending_work_filter_snapshot", None)
            if isinstance(pending, dict):
                return {
                    "search": str(pending.get("search") or ""),
                    "series": str(pending.get("series") or "All series"),
                    "review": str(pending.get("review") or "All"),
                    "published": str(pending.get("published") or "All"),
                    "issue": str(pending.get("issue") or "All works"),
                }
            return dict(self._default_work_filter_presets.get("All works", {}))
        if hasattr(self, "work_smart_filter"):
            return self._parse_work_smart_filter(self.work_smart_filter.text())
        return {
            "search": self.work_search.text().strip(),
            "series": self.work_series_filter_combo.currentText().strip() or "All series",
            "review": self.work_review_filter_combo.currentText().strip() or "All",
            "published": self.work_pub_filter_combo.currentText().strip() or "All",
            "issue": self.work_issue_filter_combo.currentText().strip() or "All works",
        }

    def set_work_filter_snapshot(self, snapshot: dict[str, str], *, refresh: bool = True) -> None:
        normalised = {
            "search": str(snapshot.get("search") or ""),
            "series": self._valid_work_series_filter_value(str(snapshot.get("series") or "All series")),
            "review": str(snapshot.get("review") or "All"),
            "published": str(snapshot.get("published") or "All"),
            "issue": str(snapshot.get("issue") or "All works"),
        }
        if not self._work_filter_widgets_ready():
            self._pending_work_filter_snapshot = normalised
            return
        self._applying_work_filter_preset = True
        try:
            if hasattr(self, "work_smart_filter"):
                self.work_smart_filter.setText(self._compose_work_smart_filter(normalised))
            else:
                self.work_search.setText(normalised["search"])
            self.work_series_filter_combo.setCurrentText(normalised["series"])
            self.work_review_filter_combo.setCurrentText(normalised["review"])
            self.work_pub_filter_combo.setCurrentText(normalised["published"])
            self.work_issue_filter_combo.setCurrentText(normalised["issue"])
            self._pending_work_filter_snapshot = None
        finally:
            self._applying_work_filter_preset = False
        if refresh:
            self.refresh_work_list()
            self.update_work_filter_preset_indicator()

    def all_work_filter_presets(self) -> dict[str, dict[str, str]]:
        presets = dict(self._default_work_filter_presets)
        for name, snapshot in (self._custom_work_filter_presets or {}).items():
            if not isinstance(snapshot, dict):
                continue
            presets[str(name)] = {
                "search": str(snapshot.get("search") or ""),
                "series": str(snapshot.get("series") or "All series"),
                "review": str(snapshot.get("review") or "All"),
                "published": str(snapshot.get("published") or "All"),
                "issue": str(snapshot.get("issue") or "All works"),
            }
        return presets

    def refresh_work_filter_preset_options(self) -> None:
        if not hasattr(self, "work_filter_preset_combo"):
            return
        names = list(self._default_work_filter_presets.keys()) + sorted([name for name in self._custom_work_filter_presets.keys() if name not in self._default_work_filter_presets])
        with signals_blocked(self.work_filter_preset_combo):
            self.work_filter_preset_combo.clear()
            self.work_filter_preset_combo.addItems(names)
        self.update_work_filter_preset_indicator()

    def on_work_filter_preset_selected(self, label: str) -> None:
        if self._applying_work_filter_preset:
            return
        name = str(label or "").replace(" (modified)", "").strip()
        preset = self.all_work_filter_presets().get(name)
        if not preset:
            return
        self._active_work_filter_preset_name = name
        self.set_work_filter_snapshot(preset, refresh=True)
        self.status_message(f"Applied works preset: {name}")

    def save_current_work_filter_preset(self) -> None:
        current_name = self._active_work_filter_preset_name or "Custom view"
        name, ok = QInputDialog.getText(self, "Save works preset", "Preset name", text=current_name if current_name != "All works" else "")
        if not ok or not str(name).strip():
            return
        preset_name = str(name).strip()
        if preset_name in self._default_work_filter_presets:
            QMessageBox.warning(self, "Preset locked", "Built-in presets cannot be overwritten. Use a new name.")
            return
        self._custom_work_filter_presets[preset_name] = self.current_work_filter_snapshot()
        self._active_work_filter_preset_name = preset_name
        self.refresh_work_filter_preset_options()
        self.save_window_state()
        self.status_message(f"Saved works preset: {preset_name}")

    def delete_current_work_filter_preset(self) -> None:
        label = self.work_filter_preset_combo.currentText().replace(" (modified)", "").strip()
        if not label or label in self._default_work_filter_presets:
            QMessageBox.information(self, "Preset locked", "Select a custom works preset to delete it.")
            return
        if QMessageBox.question(self, "Delete works preset", f"Delete preset '{label}'?") != QMessageBox.StandardButton.Yes:
            return
        self._custom_work_filter_presets.pop(label, None)
        self._active_work_filter_preset_name = "All works"
        self.refresh_work_filter_preset_options()
        self.set_work_filter_snapshot(self._default_work_filter_presets["All works"], refresh=True)
        self.save_window_state()
        self.status_message(f"Deleted works preset: {label}")

    def update_work_filter_preset_indicator(self) -> None:
        if not self._work_filter_widgets_ready():
            return
        presets = self.all_work_filter_presets()
        current = self.current_work_filter_snapshot()
        active_name = self._active_work_filter_preset_name if self._active_work_filter_preset_name in presets else "All works"
        display_name = active_name
        modified = presets.get(active_name) != current
        for name, snapshot in presets.items():
            if snapshot == current:
                display_name = name
                modified = False
                self._active_work_filter_preset_name = name
                break
        with signals_blocked(self.work_filter_preset_combo):
            index = self.work_filter_preset_combo.findText(display_name)
            if index >= 0:
                self.work_filter_preset_combo.setCurrentIndex(index)
            suffix = " (modified)" if modified else ""
            try:
                self.work_filter_preset_combo.lineEdit().setText(display_name + suffix)
            except Exception as exc:
                self._log_warning(f"Preset indicator update failed: {exc}")
        self.work_save_preset_btn.setText("Save filter *" if modified else "Save filter")
        default_snapshot = self._default_work_filter_presets.get("All works", {})
        self.work_clear_filters_btn.setText("Clear filters *" if current != default_snapshot else "Clear filters")
        self._update_work_filter_summary(current, None)

    def on_work_filters_changed(self, *_args: Any) -> None:
        if self._applying_work_filter_preset:
            return
        self._work_filter_refresh_timer.start()

    def on_work_facet_filters_changed(self, *_args: Any) -> None:
        """Keep visible facet controls and the smart search string in one source of truth."""
        if self._applying_work_filter_preset:
            return
        if not hasattr(self, "work_smart_filter"):
            self._apply_work_filter_refresh()
            return
        parsed = self._parse_work_smart_filter(self.work_smart_filter.text())
        snapshot = {
            "search": str(parsed.get("search") or ""),
            "series": self.work_series_filter_combo.currentText().strip() or "All series",
            "review": self.work_review_filter_combo.currentText().strip() or "All",
            "published": self.work_pub_filter_combo.currentText().strip() or "All",
            "issue": self.work_issue_filter_combo.currentText().strip() or "All works",
        }
        with signals_blocked(self.work_smart_filter):
            self.work_smart_filter.setText(self._compose_work_smart_filter(snapshot))
        self._work_filter_refresh_timer.start()

    def _apply_works_responsive_layout(self) -> None:
        """Prevent the Works editor/detail column from being clipped on wide and laptop layouts."""
        if not hasattr(self, "works_main_splitter") or not hasattr(self, "work_editor_grid"):
            return
        try:
            total = int(self.works_main_splitter.width() or 0)
            if total <= 0 and hasattr(self, "tabs"):
                total = int(self.tabs.width() or 0)
            if total <= 0:
                return
            inspector_visible = bool(getattr(self, "context_inspector", None) is not None and self.context_inspector.isVisible())
            compact_editor = total < 1480 or (inspector_visible and total < 1660)
            direction = QBoxLayout.Direction.TopToBottom if compact_editor else QBoxLayout.Direction.LeftToRight
            if self.work_editor_grid.direction() != direction:
                self.work_editor_grid.setDirection(direction)
            if hasattr(self, "work_core_column"):
                self.work_core_column.setMinimumWidth(0 if compact_editor else 320)
            if hasattr(self, "work_detail_column"):
                self.work_detail_column.setMinimumWidth(0 if compact_editor else 360)
            if hasattr(self, "work_image_preview"):
                self.work_image_preview.setMinimumHeight(190 if compact_editor else 220)
                self.work_image_preview.setMaximumHeight(320 if compact_editor else 360)
            min_left = 360
            max_left = 600 if compact_editor else 640
            preferred_left = int(total * (0.32 if compact_editor else 0.36))
            left_width = max(min_left, min(max_left, preferred_left))
            min_right = 620 if compact_editor else 820
            right_width = max(min_right, total - left_width - 12)
            current = self.works_main_splitter.sizes()
            if not current or len(current) < 2 or abs(current[0] - left_width) > 96 or current[1] < min_right:
                self.works_main_splitter.setSizes([left_width, right_width])
        except Exception as exc:
            self._log_warning(f"Works responsive layout failed: {exc}")

    def _apply_work_filter_refresh(self, *_args: Any) -> None:
        if self._applying_work_filter_preset:
            return
        self.refresh_work_list()
        self.update_work_filter_preset_indicator()
        self._schedule_window_state_save()

    def _schedule_window_state_save(self) -> None:
        self._state_save_timer.start()

    def refresh_work_list(self, *, force: bool = False, reason: str = "") -> None:
        """Debounced Works refresh entry point.

        Phase 23 batches rapid refresh requests into one model update instead
        of rebuilding the Works list repeatedly during tab switches/saves.
        """
        self._pending_work_list_refresh_reason = str(reason or self._pending_work_list_refresh_reason or "scheduled")
        # Batch A / Phase 3: a refresh request for the hidden Works tab should
        # dirty the scope, not rebuild cards, icons and models while the user is
        # working somewhere else. Forced/manual refreshes still run immediately.
        if not force and hasattr(self, "tabs") and self._is_tab_built_key("works") and self._current_tab_key() != "works":
            self._mark_dirty({"works"})
            self._record_dirty_refresh_diagnostic("works", 0.0, "deferred hidden Works refresh")
            return
        if force or not hasattr(self, "_work_list_debounce"):
            if hasattr(self, "_work_list_debounce"):
                self._work_list_debounce.stop()
            self._refresh_work_list_now()
            return
        self._work_list_debounce.start()


    def _refresh_work_list_now(self) -> None:
        """Start an asynchronous Works query; UI rendering happens on result apply.

        Batch B / Phase 4 separates the expensive backend query from widget
        updates and protects the UI from stale filter/search results.
        """
        if not hasattr(self, "work_tree"):
            self._log_warning("Works refresh skipped because work list is not available")
            return
        if getattr(self, "_works_refresh_inflight", False):
            # The keyed task below cancels the old request. This flag is kept only
            # for status diagnostics and does not block newer filter/search input.
            self._record_dirty_refresh_diagnostic("works", 0.0, "Cancelling stale Works refresh for newer request")
        request_id = int(getattr(self, "_works_refresh_request_id", 0) or 0) + 1
        self._works_refresh_request_id = request_id
        self._works_refresh_inflight = True
        self._works_refresh_started_by_id = dict(getattr(self, "_works_refresh_started_by_id", {}) or {})
        self._works_refresh_started_by_id[request_id] = time.perf_counter()
        active_filters = self.current_work_filter_snapshot()
        current = str(getattr(self, "_current_work_id", "") or "")
        if hasattr(self, "progress_hint"):
            self.progress_hint.setText("Refreshing Works…")
        gallery_view = bool(getattr(self, "_gallery_mode", True) and hasattr(self, "work_gallery_scroll"))
        if gallery_view and not getattr(self, "_gallery_cards_by_work_id", {}):
            self._show_work_gallery_skeletons(8)

        def task(*, task_context: TaskContext | None = None) -> dict[str, Any]:
            return self._query_works_state(request_id, active_filters, current, task_context=task_context)

        self.start_keyed_background_task(
            "works-query",
            task,
            on_done=self._apply_works_state,
            on_error=lambda detail, rid=request_id: self._works_query_failed(rid, detail),
            label="Works refresh",
            cancel_previous=True,
        )

    def _query_works_state(
        self,
        request_id: int,
        active_filters: dict[str, str],
        current_work_id: str,
        *,
        task_context: TaskContext | None = None,
    ) -> dict[str, Any]:
        if task_context is not None:
            task_context.stage("Loading Works filters", progress=10)
        series_values = works_filter_series_values()
        live_series = available_series_slugs()
        editor_series = ""
        if current_work_id:
            payload = load_work_payload(current_work_id) or {}
            editor_series = str(payload.get("series") or "").strip()
        if task_context is not None:
            task_context.stage("Filtering Works", progress=45)
        query_started = time.perf_counter()
        works = load_works_filtered(
            search=active_filters.get("search", ""),
            series_slug=active_filters.get("series", "All series"),
            review_status=active_filters.get("review", "All"),
            published_state=active_filters.get("published", "All"),
            issue_filter=active_filters.get("issue", "All works"),
            fast=True,
            task_context=task_context,
        )
        if task_context is not None:
            task_context.stage("Preparing Works result", progress=90)
        return {
            "request_id": int(request_id),
            "filters": dict(active_filters or {}),
            "works": list(works),
            "series_values": list(series_values),
            "live_series": list(live_series),
            "editor_series": editor_series,
            "current_work_id": current_work_id,
            "query_elapsed": time.perf_counter() - query_started,
        }

    def _works_query_failed(self, request_id: int, detail: str) -> None:
        if int(request_id) != int(getattr(self, "_works_refresh_request_id", 0) or 0):
            return
        self._works_refresh_inflight = False
        if hasattr(self, "progress_hint"):
            self.progress_hint.setText("")
        self._log_warning(f"Works refresh failed: {detail}")
        self.push_notification("error", "Works refresh failed", str(detail), target_scope="work")

    def _apply_works_state(self, state: dict[str, Any]) -> None:
        request_id = int((state or {}).get("request_id") or 0)
        if request_id != int(getattr(self, "_works_refresh_request_id", 0) or 0):
            self._record_dirty_refresh_diagnostic("works", 0.0, f"Ignored stale Works result #{request_id}")
            return
        started_by_id = dict(getattr(self, "_works_refresh_started_by_id", {}) or {})
        started = float(started_by_id.pop(request_id, time.perf_counter()) or time.perf_counter())
        self._works_refresh_started_by_id = started_by_id
        self._works_refresh_inflight = False
        works = list((state or {}).get("works") or [])
        active_filters = dict((state or {}).get("filters") or self.current_work_filter_snapshot())
        query_elapsed = float((state or {}).get("query_elapsed") or 0.0)
        render_elapsed = 0.0
        visible_icon_payloads: list[dict[str, Any]] = []
        target_view = None
        table_view = False
        gallery_view = False
        sort_col = 2
        sort_order = Qt.SortOrder.AscendingOrder
        # Use the live selection at apply-time, not only the selection captured
        # when the async Works query was queued. Otherwise a slower background
        # refresh can finish after the user has clicked another gallery card and
        # silently push the editor/preview back to the older work.
        captured_current = str((state or {}).get("current_work_id") or "")
        live_current = str(getattr(self, "_current_work_id", "") or "")
        current = live_current or captured_current
        if captured_current and live_current and captured_current != live_current:
            self._record_dirty_refresh_diagnostic("works", 0.0, f"Kept live Works selection '{live_current}' over stale refresh selection '{captured_current}'")
        if not hasattr(self, "work_tree"):
            return
        try:
            table_view = bool(getattr(self, "_works_model_view_enabled", False) and hasattr(self, "work_table"))
            gallery_view = bool(getattr(self, "_gallery_mode", True) and hasattr(self, "work_gallery_scroll"))
            target_view = self.work_table if table_view else (self.work_gallery_scroll if gallery_view and hasattr(self, "work_gallery_scroll") else self.work_tree)
            try:
                if table_view and hasattr(self.work_table, "horizontalHeader"):
                    header = self.work_table.horizontalHeader()
                    sort_col = int(header.sortIndicatorSection())
                    sort_order = header.sortIndicatorOrder()
                elif hasattr(self.work_tree, "sortColumn"):
                    sort_col = int(self.work_tree.sortColumn())
            except Exception:
                sort_col = 2
                sort_order = Qt.SortOrder.AscendingOrder
            if target_view is not None:
                target_view.setUpdatesEnabled(False)
            if not table_view and not gallery_view:
                self.work_tree.setSortingEnabled(False)
                self.work_tree.clear()

            series_values = list((state or {}).get("series_values") or ["All series"])
            previous_series = self.work_series_filter_combo.currentText()
            with signals_blocked(self.work_series_filter_combo):
                self.work_series_filter_combo.clear()
                self.work_series_filter_combo.addItems(series_values)
                if previous_series in series_values:
                    self.work_series_filter_combo.setCurrentText(previous_series)
                else:
                    self.work_series_filter_combo.setCurrentText(active_filters.get("series", "All series"))

            live_series = list((state or {}).get("live_series") or [])
            editor_series = str((state or {}).get("editor_series") or "").strip()
            if not editor_series:
                editor_series = self.work_series_combo.currentText().strip() if hasattr(self, "work_series_combo") else ""
            with signals_blocked(self.work_series_combo):
                self.work_series_combo.clear()
                self.work_series_combo.addItems(live_series)
                if editor_series and editor_series not in live_series:
                    self.work_series_combo.addItem(editor_series)
                if editor_series:
                    self.work_series_combo.setCurrentText(editor_series)
            with signals_blocked(self.batch_move_series_combo):
                current_batch_series = self.batch_move_series_combo.currentText()
                self.batch_move_series_combo.clear()
                self.batch_move_series_combo.addItems(live_series)
                if current_batch_series in live_series:
                    self.batch_move_series_combo.setCurrentText(current_batch_series)

            with signals_blocked(self.work_series_filter_combo):
                self.work_series_filter_combo.setCurrentText(active_filters.get("series", "All series"))
            with signals_blocked(self.work_review_filter_combo):
                self.work_review_filter_combo.setCurrentText(active_filters.get("review", "All"))
            with signals_blocked(self.work_pub_filter_combo):
                self.work_pub_filter_combo.setCurrentText(active_filters.get("published", "All"))
            with signals_blocked(self.work_issue_filter_combo):
                self.work_issue_filter_combo.setCurrentText(active_filters.get("issue", "All works"))

            initial_limit = int(getattr(self, "_work_gallery_initial_limit", 50) or 50)
            gallery_works = list(works)[:initial_limit]
            self._current_gallery_works = gallery_works
            self._visible_work_payloads_by_id = {str(row.get("id") or ""): dict(row) for row in works if str(row.get("id") or "")}
            self._visible_work_id_order = [str(row.get("id") or "") for row in works if str(row.get("id") or "")]
            self._update_work_filter_summary(active_filters, len(works))
            render_started = time.perf_counter()
            if table_view:
                with signals_blocked(self.work_table):
                    self._works_model.set_rows(list(works))
                    if sort_col < 0:
                        sort_col = 2
                    self.work_table.sortByColumn(sort_col, sort_order)
                self._last_works_model_summary = works_model_summary(self._works_model.rows())
            elif gallery_view:
                self._works_model.set_rows(list(works))
                self._last_works_model_summary = works_model_summary(list(works))
            else:
                self._works_model.set_rows(list(works))
                self._last_works_model_summary = works_model_summary(list(works))
                for payload in works:
                    item = QTreeWidgetItem([
                        str(payload.get("id") or ""),
                        str(payload.get("title") or ""),
                        str(payload.get("series") or ""),
                        str(payload.get("review_status") or ""),
                        "Yes" if bool(payload.get("published")) else "No",
                        str(int(payload.get("_completeness_score") or 0)),
                        str(payload.get("_source_status") or "-"),
                        self._work_issue_text(payload),
                    ])
                    item.setData(0, Qt.ItemDataRole.UserRole, payload.get("id"))
                    item.setData(0, Qt.ItemDataRole.UserRole + 5, dict(payload))
                    item.setIcon(0, self._placeholder_work_icon())
                    self._apply_work_tree_item_payload(item, payload)
                    self.work_tree.addTopLevelItem(item)
                if not works:
                    empty = QTreeWidgetItem(["No works match the current filters", "", "", "", "", "", "", "Clear filters or add an image"])
                    empty.setFlags(Qt.ItemFlag.NoItemFlags)
                    self.work_tree.addTopLevelItem(empty)
                if works:
                    self.work_tree.setSortingEnabled(True)
                    self.work_tree.sortItems(sort_col if sort_col >= 0 else 2, sort_order)
                else:
                    self.work_tree.setSortingEnabled(False)
            render_elapsed = time.perf_counter() - render_started
            visible_icon_payloads = self._visible_work_icon_payloads(works)[:96]
            self._start_work_icon_loader(visible_icon_payloads)
            self._schedule_visible_asset_health_check()
            if gallery_view or getattr(self, "_work_gallery_view", False):
                self._populate_work_gallery(gallery_works)
            elif hasattr(self, "work_gallery_grid"):
                self._clear_layout(self.work_gallery_grid)
            if hasattr(self, "work_table"):
                self.work_table.setVisible(bool(table_view and not gallery_view))
            if hasattr(self, "work_tree"):
                self.work_tree.setVisible(False)
            if hasattr(self, "work_gallery_scroll"):
                self.work_gallery_scroll.setVisible(bool(gallery_view))
            self._update_work_batch_bar()
            if current and current in self._visible_work_payloads_by_id:
                self._select_work_row_by_id(current)
            elif current:
                self.select_work(current, silent=True)
            else:
                self._update_work_preview_pane({})
            self.update_tab_badges()
            self.refresh_context_inspector()
            getattr(self, "_dirty_tabs", {}).pop("works", None)
            if hasattr(self, "progress_hint"):
                self.progress_hint.setText("")
        except Exception as exc:
            self._log_warning(f"Works refresh apply failed: {exc}")
            self.push_notification("error", "Works refresh failed", str(exc), target_scope="work")
        finally:
            try:
                if target_view is not None:
                    target_view.setUpdatesEnabled(True)
                    if hasattr(target_view, "viewport"):
                        target_view.viewport().update()
            except Exception as exc:
                self._log_warning(f"Works refresh UI restore failed: {exc}")
            self._record_perf("works refresh", time.perf_counter() - started, f"{len(works)} work(s) · async query {query_elapsed * 1000:.0f} ms · render {render_elapsed * 1000:.0f} ms · {len(visible_icon_payloads)} visible thumbnails queued")

    def _work_issue_text(self, payload: dict[str, Any]) -> str:
        issues = payload.get("_issue_list") or []
        if not issues:
            return "0"
        if any(str(issue).lower().startswith(("error", "missing")) for issue in issues):
            return f"✕ {len(issues)}"
        return f"⚠ {len(issues)}"

    def clear_work_filters(self) -> None:
        self.set_work_filter_snapshot(self._default_work_filter_presets["All works"], refresh=True)

    def _update_work_filter_summary(self, snapshot: dict[str, str] | None = None, total: int | None = None) -> None:
        if not hasattr(self, "work_filter_summary"):
            return
        snapshot = dict(snapshot or self.current_work_filter_snapshot())
        chips: list[str] = []
        search = str(snapshot.get("search") or "").strip()
        if search:
            chips.append(f"search: {search}")
        series = str(snapshot.get("series") or "All series").strip()
        if series and series != "All series":
            chips.append(f"series: {series}")
        review = str(snapshot.get("review") or "All").strip()
        if review and review != "All":
            chips.append(f"status: {review}")
        published = str(snapshot.get("published") or "All").strip()
        if published and published != "All":
            chips.append(f"published: {published.lower()}")
        issue = str(snapshot.get("issue") or "All works").strip()
        if issue and issue != "All works":
            chips.append(f"issue: {issue}")
        prefix = f"{total} visible" if total is not None else "Works"
        if not chips:
            chips = ["all works"]
        self.work_filter_summary.setText(prefix + " · " + " · ".join(chips) + " · double-click Review/Published to quick-edit")

    def _using_work_model_view(self) -> bool:
        return bool(getattr(self, "_works_model_view_enabled", False) and hasattr(self, "work_table"))

    def _work_model_payload_for_id(self, work_id: str) -> dict[str, Any]:
        if not work_id:
            return {}
        payload = self._works_model.payload_for_id(str(work_id)) if hasattr(self, "_works_model") else {}
        if payload:
            return payload
        return dict(getattr(self, "_visible_work_payloads_by_id", {}).get(str(work_id), {}) or {})

    def _work_model_row_for_id(self, work_id: str) -> int:
        return self._works_model.row_for_id(str(work_id)) if hasattr(self, "_works_model") else -1

    def _select_work_row_by_id(self, work_id: str | None) -> None:
        if not work_id or not self._using_work_model_view():
            return
        row = self._work_model_row_for_id(str(work_id))
        if row < 0:
            return
        index = self._works_model.index(row, 0)
        with signals_blocked(self.work_table):
            self.work_table.selectRow(row)
            self.work_table.setCurrentIndex(index)
            self.work_table.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)

    def _work_id_from_model_index(self, index) -> str:
        if index is None or not index.isValid():
            return ""
        return str(self._works_model.index(index.row(), 0).data(Qt.ItemDataRole.UserRole) or "")

    def _patch_work_tree_row_after_quick_state(self, work_id: str, *, published: bool | None = None, review_status: str | None = None) -> None:
        if self._using_work_model_view():
            payload = self._work_model_payload_for_id(work_id) or load_work_payload(work_id)
            if payload:
                if review_status is not None:
                    payload["review_status"] = str(review_status)
                if published is not None:
                    payload["published"] = bool(published)
                self._works_model.update_row(work_id, payload)
                self._visible_work_payloads_by_id[str(payload.get("id") or work_id)] = dict(payload)
                self._current_gallery_works = [dict(payload) if str(row.get("id") or "") == str(work_id) else row for row in getattr(self, "_current_gallery_works", [])]
                self.work_table.viewport().update()
                if getattr(self, "_current_work_id", "") == work_id:
                    self._update_work_preview_pane(payload)
            return
        if not hasattr(self, "work_tree"):
            return
        for idx in range(self.work_tree.topLevelItemCount()):
            item = self.work_tree.topLevelItem(idx)
            if str(item.data(0, Qt.ItemDataRole.UserRole) or "") != str(work_id):
                continue
            if review_status is not None:
                item.setText(3, str(review_status))
            if published is not None:
                item.setText(4, "Yes" if bool(published) else "No")
            for col in (3, 4):
                item.setForeground(col, self._severity_color("ok" if (published or review_status == "published") else "info"))
            self.work_tree.viewport().update()
            break
        if getattr(self, "_current_work_id", "") == work_id:
            try:
                payload = load_work_payload(work_id)
                if payload:
                    self._update_work_preview_pane(payload)
            except Exception as exc:
                self._log_warning(f"Quick state preview patch failed for {work_id}: {exc}")

    def _work_tree_item_for_id(self, work_id: str) -> QTreeWidgetItem | None:
        if not hasattr(self, "work_tree") or not work_id:
            return None
        for idx in range(self.work_tree.topLevelItemCount()):
            item = self.work_tree.topLevelItem(idx)
            if str(item.data(0, Qt.ItemDataRole.UserRole) or "") == str(work_id):
                return item
        return None

    def _work_tree_payload_for_id(self, work_id: str) -> dict[str, Any]:
        if self._using_work_model_view():
            return self._work_model_payload_for_id(work_id)
        item = self._work_tree_item_for_id(work_id)
        if item is None:
            return {}
        data = item.data(0, Qt.ItemDataRole.UserRole + 5)
        return dict(data or {}) if isinstance(data, dict) else {}

    def _fast_work_row_payload(self, payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build the row payload used after a normal Work save without re-scanning assets.

        The slow path in load_works_filtered() calls work_completeness_score(), which
        can touch the file system for every visible work. A metadata save should not
        pay that cost. We keep the previous asset/status columns and patch the edited
        metadata immediately; dashboard/validation/publish are marked dirty for later.
        """
        existing = dict(existing or {})
        row = dict(existing)
        row.update(dict(payload or {}))
        issues = work_issue_list(row)
        previous_issues = list(existing.get("_issue_list") or [])
        asset_issues = [issue for issue in previous_issues if any(token in str(issue).lower() for token in ("source", "image", "thumbnail", "asset"))]
        for issue in asset_issues:
            if issue not in issues:
                issues.append(issue)
        row["_issue_list"] = issues
        if "_completeness_score" not in row:
            row["_completeness_score"] = max(0, 100 - min(80, len(issues) * 12))
        if "_completeness_status" not in row:
            score = int(row.get("_completeness_score") or 0)
            row["_completeness_status"] = "ready" if score >= 85 and not issues else "review" if score >= 60 else "blocked"
        row["_source_status"] = existing.get("_source_status", row.get("_source_status") or "deferred")
        return row

    def _apply_work_tree_item_payload(self, item: QTreeWidgetItem, payload: dict[str, Any]) -> None:
        issues = payload.get("_issue_list") or []
        issue_text = "0"
        if issues:
            issue_text = f"⚠ {len(issues)}"
            if any(str(issue).lower().startswith(("error", "missing")) for issue in issues):
                issue_text = f"✕ {len(issues)}"
        score_value = int(payload.get("_completeness_score") or 0)
        source_status = str(payload.get("_source_status") or "-")
        values = [
            str(payload.get("id") or ""),
            str(payload.get("title") or ""),
            str(payload.get("series") or ""),
            str(payload.get("review_status") or ""),
            "Yes" if bool(payload.get("published")) else "No",
            str(score_value),
            source_status,
            issue_text,
        ]
        for col, value in enumerate(values):
            item.setText(col, value)
        item.setData(0, Qt.ItemDataRole.UserRole, payload.get("id"))
        item.setData(0, Qt.ItemDataRole.UserRole + 5, dict(payload))
        severity = self._work_row_severity(payload)
        for data_col in range(8):
            item.setData(data_col, Qt.ItemDataRole.UserRole + 2, severity)
        score_color = self._severity_color("ok" if score_value >= 85 else "warning" if score_value >= 60 else "error")
        item.setForeground(5, score_color)
        if source_status not in {"-", "", "ok"}:
            item.setForeground(6, self._severity_color("warning" if source_status in {"orphan-risk", "deferred"} else "error"))
        if issues:
            item.setToolTip(7, "\n".join(str(issue) for issue in issues))
            issue_color = self._severity_color("error" if issue_text.startswith("✕") else "warning")
            item.setForeground(7, issue_color)
        else:
            item.setToolTip(7, "")

    def _patch_work_tree_row_after_save(self, old_work_id: str | None, work_id: str, payload: dict[str, Any]) -> None:
        existing = self._work_tree_payload_for_id(old_work_id or work_id) or self._work_tree_payload_for_id(work_id)
        row_payload = self._fast_work_row_payload(payload, existing)
        if self._using_work_model_view():
            self._works_model.replace_or_insert_row(old_work_id or work_id, row_payload)
            new_id = str(row_payload.get("id") or work_id)
            if old_work_id and old_work_id != new_id:
                self._visible_work_payloads_by_id.pop(str(old_work_id), None)
                self._visible_work_id_order = [new_id if item == str(old_work_id) else item for item in getattr(self, "_visible_work_id_order", [])]
            self._visible_work_payloads_by_id[new_id] = dict(row_payload)
            replaced = False
            rows = []
            for row in getattr(self, "_current_gallery_works", []):
                if str(row.get("id") or "") in {str(old_work_id or ""), str(work_id)}:
                    rows.append(dict(row_payload)); replaced = True
                else:
                    rows.append(row)
            if not replaced:
                rows.append(dict(row_payload))
            self._current_gallery_works = rows
            self._select_work_row_by_id(new_id)
            if getattr(self, "_work_gallery_view", False) or getattr(self, "_gallery_mode", False):
                self._populate_work_gallery(list(getattr(self, "_current_gallery_works", [])))
            self.work_table.viewport().update()
            self._update_work_preview_pane(row_payload)
            return
        item = self._work_tree_item_for_id(old_work_id or work_id) or self._work_tree_item_for_id(work_id)
        if item is None:
            self.refresh_work_list()
            self.select_work(work_id, silent=True)
            return
        with signals_blocked(self.work_tree):
            self._apply_work_tree_item_payload(item, row_payload)
            self.work_tree.setCurrentItem(item)
            item.setSelected(True)
        self._current_gallery_works = [row_payload if str(row.get("id") or "") in {str(old_work_id or ""), str(work_id)} else row for row in getattr(self, "_current_gallery_works", [])]
        if hasattr(self, "_works_model"):
            self._works_model.set_rows(list(getattr(self, "_current_gallery_works", [])))
            self._last_works_model_summary = works_model_summary(list(getattr(self, "_current_gallery_works", [])))
        if getattr(self, "_work_gallery_view", False):
            self._populate_work_gallery(list(getattr(self, "_current_gallery_works", [])))
        self.work_tree.viewport().update()
        self._update_work_preview_pane(row_payload)

    def _mark_work_save_dependents_dirty(self, *, structural: bool = False) -> None:
        scopes = {"dashboard", "validation", "studio", "publish"}
        if structural:
            scopes.update({"series", "relationships"})
        self._mark_dirty(scopes)
        self.update_tab_badges()
        self.sync_side_navigation()

    def _mark_work_quick_edit_dependents_dirty(self) -> None:
        self._mark_dirty({"dashboard", "validation", "studio", "publish"})
        self.sync_side_navigation()

    def _normalized_text(self, value: str) -> str:
        return (value or "").replace("\r\n", "\n").strip()

    def _normalized_payload(self, payload: dict[str, Any] | None) -> str:
        return json.dumps(payload or {}, sort_keys=True, ensure_ascii=False)

    def is_work_dirty(self) -> bool:
        if not self._current_work_id or self._loaded_work_snapshot is None:
            return False
        return self._normalized_payload(self.current_work_payload_from_form()) != self._normalized_payload(self._loaded_work_snapshot)

    def is_series_dirty(self) -> bool:
        if not self._current_series_slug or self._loaded_series_snapshot is None:
            return False
        return self._normalized_payload(self.current_series_payload_from_form()) != self._normalized_payload(self._loaded_series_snapshot)

    def is_page_dirty(self) -> bool:
        if not self._current_page_key:
            return False
        return self._normalized_text(self.page_editor.toPlainText()) != self._normalized_text(self._loaded_page_text)

    def is_authority_dirty(self) -> bool:
        if not self._current_authority_key:
            return False
        return self._normalized_text(self.authority_editor.toPlainText()) != self._normalized_text(self._loaded_authority_text)

    def prompt_unsaved_changes(self, label: str) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText(f"{label} has unsaved changes.")
        box.setInformativeText("Save before switching? Cancel keeps you on the current item.")
        save_btn = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked == save_btn:
            return "save"
        if clicked == discard_btn:
            return "discard"
        return "cancel"

    def _restore_work_selection(self) -> None:
        if self._using_work_model_view():
            if self._current_work_id:
                self._select_work_row_by_id(self._current_work_id)
            else:
                self.work_table.clearSelection()
            return
        with signals_blocked(self.work_tree):
            self.work_tree.clearSelection()
            if self._current_work_id:
                for idx in range(self.work_tree.topLevelItemCount()):
                    item = self.work_tree.topLevelItem(idx)
                    if str(item.data(0, Qt.ItemDataRole.UserRole) or "") == self._current_work_id:
                        self.work_tree.setCurrentItem(item)
                        item.setSelected(True)
                        break

    def _restore_series_selection(self) -> None:
        with signals_blocked(self.series_list):
            self.series_list.clearSelection()
            if self._current_series_slug:
                for idx in range(self.series_list.count()):
                    item = self.series_list.item(idx)
                    if str(item.data(Qt.ItemDataRole.UserRole) or "") == self._current_series_slug:
                        item.setSelected(True)
                        self.series_list.setCurrentItem(item)
                        break

    def _restore_page_selection(self) -> None:
        with signals_blocked(self.pages_list):
            self.pages_list.clearSelection()
            if self._current_page_key:
                for idx in range(self.pages_list.count()):
                    item = self.pages_list.item(idx)
                    if str(item.data(Qt.ItemDataRole.UserRole) or "") == self._current_page_key:
                        item.setSelected(True)
                        self.pages_list.setCurrentItem(item)
                        break

    def _restore_authority_selection(self) -> None:
        with signals_blocked(self.authority_list):
            self.authority_list.clearSelection()
            if self._current_authority_key:
                for idx in range(self.authority_list.count()):
                    item = self.authority_list.item(idx)
                    if str(item.data(Qt.ItemDataRole.UserRole) or "") == self._current_authority_key:
                        item.setSelected(True)
                        self.authority_list.setCurrentItem(item)
                        break

    def ensure_work_editor_safe(self) -> bool:
        if not self.is_work_dirty():
            return True
        action = self.prompt_unsaved_changes(f"Work '{self._current_work_id or ''}'")
        if action == "save":
            self.save_current_work()
            return not self.is_work_dirty()
        if action == "discard":
            return True
        return False

    def ensure_series_editor_safe(self) -> bool:
        if not self.is_series_dirty():
            return True
        action = self.prompt_unsaved_changes(f"Series '{self._current_series_slug or ''}'")
        if action == "save":
            self.save_current_series()
            return not self.is_series_dirty()
        if action == "discard":
            return True
        return False

    def ensure_page_editor_safe(self) -> bool:
        if not self.is_page_dirty():
            return True
        action = self.prompt_unsaved_changes(f"Page '{self._current_page_key or ''}'")
        if action == "save":
            self.save_current_page()
            return not self.is_page_dirty()
        if action == "discard":
            return True
        return False

    def ensure_authority_editor_safe(self) -> bool:
        if not self.is_authority_dirty():
            return True
        action = self.prompt_unsaved_changes(f"Authority document '{self._current_authority_key or ''}'")
        if action == "save":
            self.save_current_authority()
            return not self.is_authority_dirty()
        if action == "discard":
            return True
        return False

    def ensure_all_editors_safe(self) -> bool:
        work_safe = self.ensure_work_editor_safe()
        series_safe = self.ensure_series_editor_safe()
        page_safe = self.ensure_page_editor_safe()
        authority_safe = self.ensure_authority_editor_safe()
        return work_safe and series_safe and page_safe and authority_safe

    def selected_work_ids(self) -> list[str]:
        if self._using_work_model_view():
            selection = self.work_table.selectionModel()
            if selection is None:
                return []
            ids: list[str] = []
            for index in selection.selectedRows(0):
                work_id = str(self._works_model.index(index.row(), 0).data(Qt.ItemDataRole.UserRole) or "")
                if work_id:
                    ids.append(work_id)
            return ids
        return [str(item.data(0, Qt.ItemDataRole.UserRole) or "") for item in self.work_tree.selectedItems() if str(item.data(0, Qt.ItemDataRole.UserRole) or "")]

    def open_bulk_edit_dialog(self) -> None:
        ids = self.selected_work_ids()
        if not ids:
            self._info_nonblocking("No works selected", "Select one or more works first.", target_scope="work")
            return
        BulkEditDialog(self, ids).exec()

    def open_bulk_image_ingest_dialog(self) -> None:
        BulkImageIngestDialog(self).exec()

    def open_metadata_audit_dialog(self) -> None:
        ids = self.selected_work_ids()
        WorkMetadataAuditDialog(self, ids or None).exec()

    def open_duplicate_scan_dialog(self) -> None:
        DuplicateScanDialog(self).exec()

    def verify_current_work_assets(self) -> None:
        work_id = self._current_work_id
        if not work_id:
            self._info_nonblocking("No work selected", "Select a work first.", target_scope="work")
            return
        try:
            presence = reconcile_asset_presence_for_work(work_id)
            verification = verify_work_transaction(work_id, work_id)
            stale_runtime = scan_stale_references(work_id, work_id)
        except Exception as exc:
            self._log_warning(f"Verify assets failed for {work_id}: {exc}")
            QMessageBox.critical(self, "Asset verification failed", str(exc))
            return
        exact_content = [row for row in stale_runtime if row.get("source") == "content-yaml" and row.get("match") == "exact"]
        report = {
            "operation": "verify-work-assets",
            "work_id": work_id,
            "presence": presence,
            "verification": verification,
            "content_exact_references": len(exact_content),
            "runtime_reference_mentions": len([row for row in stale_runtime if row.get("source") == "control-json"]),
        }
        level = "success" if presence.get("status") == "ok" and verification.get("ok") and not exact_content else "warning"
        self.push_notification(level, f"Asset verification: {work_id}", presence.get("message") or presence.get("status") or "", target_scope="work", target_id=work_id)
        self.show_operation_report("Selected work asset verification", report, force=True)
        self.status_message(f"Verified assets for {work_id}: {presence.get('status')}")

    def open_work_lineage_dialog(self) -> None:
        if not self._current_work_id:
            self._info_nonblocking("No work selected", "Select a work first.", target_scope="work")
            return
        WorkLineageDialog(self, self._current_work_id).exec()

    def save_current_work_private_note(self) -> None:
        if not self._current_work_id:
            self._info_nonblocking("No work selected", "Select a work first.", target_scope="work")
            return
        try:
            save_private_note("work", self._current_work_id, self.work_private_note_edit.toPlainText())
        except Exception as exc:
            QMessageBox.critical(self, "Private note failed", str(exc))
            return
        self.push_notification("success", "Saved private work note", self._current_work_id, target_scope="work", target_id=self._current_work_id)
        self.status_message("Saved private work note")

    def open_derivative_compare_dialog(self) -> None:
        if not self._current_work_id:
            self._info_nonblocking("No work selected", "Select a work first.", target_scope="work")
            return
        payload = load_work_payload(self._current_work_id) or {}
        source = None
        try:
            from qt_backend import source_path_for_work, load_pipeline
            source = source_path_for_work(str(payload.get("series") or ""), self._current_work_id, load_pipeline())
        except Exception as exc:
            self._log_warning(f"Derivative compare source lookup failed: {exc}")
        derivative = best_preview_path_for_work(payload)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Derivative comparison · {self._current_work_id}")
        dialog.resize(980, 560)
        layout = QHBoxLayout(dialog)
        for label, path in (("Original/source", source), ("Best generated preview", derivative)):
            panel = QVBoxLayout()
            panel.addWidget(QLabel(label))
            image_label = QLabel(str(path or "No image available"))
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image_label.setMinimumSize(420, 420)
            if path and Path(path).exists():
                pix = QPixmap(str(path))
                if not pix.isNull():
                    image_label.setPixmap(pix.scaled(QSize(420, 420), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                    image_label.setToolTip(str(path))
            panel.addWidget(image_label, 1)
            wrap = QWidget(); wrap.setLayout(panel); layout.addWidget(wrap)
        dialog.exec()

    def select_all_visible_works(self) -> None:
        if self._using_work_model_view():
            self.work_table.selectAll()
            self._update_work_batch_bar()
            return
        with signals_blocked(self.work_tree):
            for index in range(self.work_tree.topLevelItemCount()):
                self.work_tree.topLevelItem(index).setSelected(True)

    def deselect_all_visible_works(self) -> None:
        if self._using_work_model_view():
            self.work_table.clearSelection()
            if self._current_work_id:
                self._restore_work_selection()
            self._update_work_batch_bar()
            return
        with signals_blocked(self.work_tree):
            self.work_tree.clearSelection()
            if self._current_work_id:
                self._restore_work_selection()

    def _set_preview_label(self, label: QLabel, image_path: str | None, *, fallback: str, size: QSize) -> None:
        if image_path:
            pix = QPixmap(str(image_path))
            if not pix.isNull():
                label.setPixmap(pix.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                label.setToolTip(str(image_path))
                return
        label.setPixmap(QPixmap())
        label.setText(fallback)
        label.setToolTip(fallback)

    def _placeholder_work_icon(self) -> QIcon:
        cached = self._work_icon_cache.get("__placeholder__")
        if cached is not None:
            return cached
        pix = QPixmap(52, 52)
        pix.fill(QColor("#162232"))
        icon = QIcon(pix)
        self._work_icon_cache.put("__placeholder__", icon)
        return icon

    def _work_icon_cache_key(self, payload: dict[str, Any]) -> str:
        work_id = str(payload.get("id") or "")
        # Phase 4: list-row cache keys must not call the heavier preview/source
        # resolver. Use manifest/direct-path lookup here; deeper truth runs in a
        # deferred background pass.
        image_path = fast_preview_path_for_work(payload)
        return thumbnail_signature(work_id, image_path, payload)

    def _visible_work_icon_payloads(self, works: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._using_work_model_view():
            rows = self._works_model.rows() if hasattr(self, "_works_model") else list(works or [])
            if not rows:
                return []
            try:
                first = self.work_table.rowAt(0)
                last = self.work_table.rowAt(max(0, self.work_table.viewport().height() - 1))
            except Exception:
                first, last = 0, -1
            if first < 0:
                first = 0
            if last < first:
                last = min(len(rows) - 1, first + 60)
            start = max(0, first - 20)
            stop = min(len(rows), last + 41)
            visible_ids = {str(row.get("id") or "") for row in rows[start:stop]}
            priority = [payload for payload in rows if str(payload.get("id") or "") in visible_ids]
            rest = [payload for payload in rows if str(payload.get("id") or "") not in visible_ids]
            return priority + rest
        if not hasattr(self, "work_tree"):
            return works[:20]
        row_budget = 60
        visible_ids: set[str] = set()
        for idx in range(min(self.work_tree.topLevelItemCount(), row_budget)):
            item = self.work_tree.topLevelItem(idx)
            work_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            if work_id:
                visible_ids.add(work_id)
        priority = [payload for payload in works if str(payload.get("id") or "") in visible_ids]
        rest = [payload for payload in works if str(payload.get("id") or "") not in visible_ids]
        return priority + rest

    def _schedule_visible_thumbnail_load(self) -> None:
        if getattr(self, "_closing", False):
            return
        timer = getattr(self, "_work_thumbnail_timer", None)
        if timer is not None:
            timer.start()

    def _trigger_visible_thumbnail_load(self) -> None:
        works = getattr(self, "_current_gallery_works", [])
        self._start_work_icon_loader(self._visible_work_icon_payloads(works)[:96])


    def _work_asset_health_signature(self, payload: dict[str, Any]) -> str:
        work_id = str(payload.get("id") or "")
        image = payload.get("image") if isinstance(payload.get("image"), dict) else {}
        master = str(image.get("master") or payload.get("image_master") or "")
        series = str(payload.get("series") or "")
        return hashlib.sha256(json.dumps({"id": work_id, "series": series, "master": master}, sort_keys=True).encode("utf-8")).hexdigest()[:24]


    def _visible_work_asset_payloads(self, limit: int = 24) -> list[dict[str, Any]]:
        rows = self._works_model.rows() if self._using_work_model_view() and hasattr(self, "_works_model") else list(getattr(self, "_current_gallery_works", []) or [])
        if not rows:
            return []
        start = 0
        stop = min(len(rows), max(1, int(limit or 24)))
        if self._using_work_model_view() and hasattr(self, "work_table"):
            try:
                first = self.work_table.rowAt(0)
                last = self.work_table.rowAt(max(0, self.work_table.viewport().height() - 1))
                if first >= 0:
                    start = max(0, first - 4)
                if last >= first >= 0:
                    stop = min(len(rows), last + 12)
                else:
                    stop = min(len(rows), start + max(1, int(limit or 24)))
            except Exception:
                stop = min(len(rows), max(1, int(limit or 24)))
        window = rows[start:stop]
        unresolved = [dict(row) for row in window if str(row.get("_source_status") or "deferred") in {"", "-", "deferred"}]
        resolved = [dict(row) for row in window if str(row.get("_source_status") or "deferred") not in {"", "-", "deferred"}]
        return (unresolved + resolved)[:max(1, int(limit or 24))]


    def _schedule_visible_asset_health_check(self) -> None:
        if getattr(self, "_closing", False):
            return
        self._work_asset_health_token = int(getattr(self, "_work_asset_health_token", 0) or 0) + 1
        timer = getattr(self, "_work_asset_health_timer", None)
        if timer is not None:
            timer.start()


    def _start_visible_work_asset_health_check(self) -> None:
        if getattr(self, "_work_asset_health_inflight", False):
            self._work_asset_health_timer.start()
            return
        limit = int(getattr(self, "_work_asset_health_batch_limit", 24) or 24)
        payloads = self._visible_work_asset_payloads(limit=limit)
        payloads = [dict(row) for row in payloads if str(row.get("id") or "")]
        if not payloads:
            return
        cached_rows: list[dict[str, Any]] = []
        uncached: list[dict[str, Any]] = []
        cache = getattr(self, "_work_asset_health_cache", {})
        for payload in payloads:
            work_id = str(payload.get("id") or "")
            signature = self._work_asset_health_signature(payload)
            cached = cache.get(work_id)
            if isinstance(cached, dict) and cached.get("signature") == signature:
                cached_rows.append(dict(cached.get("row") or {}))
            else:
                uncached.append(payload)
        token = int(getattr(self, "_work_asset_health_token", 0) or 0)
        if cached_rows:
            self._apply_work_asset_health_rows(cached_rows, token, time.perf_counter(), from_cache=True)
        if not uncached:
            return
        self._work_asset_health_inflight = True
        started = time.perf_counter()

        def task(rows: list[dict[str, Any]] = uncached) -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []
            batch_started = time.perf_counter()
            for payload in rows:
                if time.perf_counter() - batch_started > 1.25:
                    break
                truth = cached_asset_truth_for_work(payload)
                results.append({
                    "id": str(truth.get("id") or payload.get("id") or ""),
                    "status": str(truth.get("status") or "missing"),
                    "severity": str(truth.get("severity") or ""),
                    "message": str(truth.get("message") or ""),
                    "derivative_count": int(truth.get("derivative_count") or 0),
                    "signature": self._work_asset_health_signature(payload),
                })
            return results

        self.start_keyed_background_task(
            "works-visible-asset-health",
            task,
            on_done=lambda rows, phase_token=token, start_time=started: self._apply_work_asset_health_rows(rows, phase_token, start_time),
            on_error=lambda tb: self._work_asset_health_failed(tb),
            label="Works visible asset health",
            cancel_previous=True,
        )

    def _work_asset_health_failed(self, detail: str) -> None:
        self._work_asset_health_inflight = False
        self.append_build_log_line(f"Deferred work asset check skipped: {detail}")


    def _asset_health_payload_changed(self, before: dict[str, Any], after: dict[str, Any]) -> bool:
        """Return True only when asset-health fields visible to the user changed.

        Background health checks may run repeatedly while a user is selecting or
        editing works. Patching the model for identical status/detail values is
        unnecessary and can still trigger view repaint/focus churn.
        """
        visible_keys = ("_source_status", "_source_detail")
        for key in visible_keys:
            if str(before.get(key) or "") != str(after.get(key) or ""):
                return True
        before_issues = [str(item) for item in (before.get("_issue_list") or [])]
        after_issues = [str(item) for item in (after.get("_issue_list") or [])]
        return before_issues != after_issues

    def _apply_work_asset_health_rows(self, rows: Any, token: int, started: float, *, from_cache: bool = False) -> None:
        if not from_cache:
            self._work_asset_health_inflight = False
        if token != int(getattr(self, "_work_asset_health_token", 0) or 0):
            return
        changed = 0
        for row in list(rows or []):
            work_id = str((row or {}).get("id") or "")
            if not work_id:
                continue
            payload = self._work_model_payload_for_id(work_id)
            if not payload:
                continue
            before_payload = dict(payload)
            source_status = str((row or {}).get("status") or "")
            source_detail = str((row or {}).get("message") or "")
            issues = [str(issue) for issue in (payload.get("_issue_list") or []) if not str(issue).lower().startswith("source ")]
            if source_status and source_status not in {"ok", "deferred"}:
                issues.append(f"source {source_status}")
            payload["_source_status"] = source_status or payload.get("_source_status") or "deferred"
            payload["_source_detail"] = source_detail
            payload["_issue_list"] = issues
            payload["_asset_health_checked"] = True
            signature = str((row or {}).get("signature") or self._work_asset_health_signature(payload))
            self._work_asset_health_cache[work_id] = {"signature": signature, "row": dict(row or {}), "checked_at": time.time()}
            self._visible_work_payloads_by_id[work_id] = dict(payload)
            if self._asset_health_payload_changed(before_payload, payload):
                self._patch_work_asset_health_row(payload)
                changed += 1
        if self._current_work_id and self._current_work_id in self._visible_work_payloads_by_id:
            self._update_work_health_chips(self._visible_work_payloads_by_id.get(self._current_work_id, {}))
        if changed:
            self._last_works_model_summary = works_model_summary(self._works_model.rows()) if self._using_work_model_view() else works_model_summary(list(getattr(self, "_current_gallery_works", []) or []))
            self._update_work_filter_summary(self.current_work_filter_snapshot(), len(getattr(self, "_visible_work_payloads_by_id", {}) or {}))
            self._record_perf("works deferred asset health", time.perf_counter() - started, f"{changed} visible row(s) patched{' from cache' if from_cache else ''}")
        if not from_cache and any(str(row.get("_source_status") or "") in {"", "-", "deferred"} for row in self._visible_work_asset_payloads(limit=int(getattr(self, "_work_asset_health_batch_limit", 24) or 24))):
            self._work_asset_health_timer.start()

    def _patch_work_asset_health_row(self, payload: dict[str, Any]) -> None:
        """Patch asset-health metadata without changing the active selection.

        Deferred visible-asset checks run shortly after the Works tab paints.
        The previous implementation reused a selection-owning save-row path.
        In gallery mode the hidden tree often has no matching item, so the old
        code rebuilt the list and reloaded the editor. That made the preview
        blink and pulled the editor back to whichever row the background asset
        check had just processed.
        """
        payload = dict(payload or {})
        work_id = str(payload.get("id") or "")
        if not work_id:
            return
        if hasattr(self, "_works_model"):
            try:
                self._works_model.update_row(work_id, payload)
            except Exception as exc:
                self._log_warning(f"Asset-health model patch skipped for {work_id}: {exc}")
        self._visible_work_payloads_by_id[work_id] = dict(payload)
        rows = []
        replaced = False
        for row in list(getattr(self, "_current_gallery_works", []) or []):
            if str(row.get("id") or "") == work_id:
                rows.append(dict(payload))
                replaced = True
            else:
                rows.append(row)
        if replaced:
            self._current_gallery_works = rows
        # Patch the legacy tree only when the item exists. Never refresh the
        # Works list and never select a row from a background health update.
        if hasattr(self, "work_tree"):
            item = self._work_tree_item_for_id(work_id)
            if item is not None:
                try:
                    with signals_blocked(self.work_tree):
                        self._apply_work_tree_item_payload(item, payload)
                    self.work_tree.viewport().update()
                except Exception as exc:
                    self._log_warning(f"Asset-health tree patch skipped for {work_id}: {exc}")
        if self._using_work_model_view() and hasattr(self, "work_table"):
            try:
                self.work_table.viewport().update()
            except Exception:
                pass
        card = getattr(self, "_gallery_cards_by_work_id", {}).get(work_id)
        if _qt_object_alive(card):
            try:
                status = str(payload.get("_source_status") or "deferred")
                detail = str(payload.get("_source_detail") or "")
                card.setToolTip(f"Asset status: {status}" + (f" · {detail}" if detail else ""))
            except Exception:
                pass

    def clear_work_icon_cache(self, work_id: str | None = None) -> None:
        if work_id:
            prefix = str(work_id) + "::"
            for key in list(getattr(self._work_icon_cache, "_data", {}).keys()):
                if str(key).startswith(prefix) or str(key) == str(work_id):
                    self._work_icon_cache.pop(str(key), None)
            try:
                self._work_asset_health_cache.pop(str(work_id), None)
            except Exception:
                pass
        else:
            self._work_icon_cache.clear()
            try:
                self._work_asset_health_cache.clear()
            except Exception:
                pass
        # Source/image changes can reuse the same filename with a newer mtime.
        # Clear scaled preview pixmaps as well so replacements are visible without restart.
        cache = getattr(self, "_work_preview_pixmap_cache", None)
        if isinstance(cache, OrderedDict):
            cache.clear()
        self._work_main_preview_signature = None
        self._work_side_preview_signature = None
        token = getattr(self, "_thumbnail_batch_token", None)
        if token is not None:
            token.cancel()
        self._thumbnail_batch_token = ThumbnailBatchToken()

    def work_tree_icon(self, payload: dict[str, Any]) -> QIcon:
        work_id = str(payload.get("id") or "")
        cache_key = f"{work_id}::{self._work_icon_cache_key(payload)}"
        cached = self._work_icon_cache.get(cache_key)
        if cached is not None:
            return cached
        image_path = fast_preview_path_for_work(payload)
        if image_path:
            pix = QPixmap(str(image_path))
            if not pix.isNull():
                icon = QIcon(pix.scaled(QSize(52, 52), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
                self._work_icon_cache.put(cache_key, icon)
                return icon
        icon = QIcon()
        self._work_icon_cache.put(cache_key, icon)
        return icon

    def _load_work_icon_images(self, works: list[dict[str, Any]], token: ThumbnailBatchToken | None = None) -> list[tuple[str, str, QImage]]:
        rows: list[tuple[str, str, QImage]] = []
        for payload in works:
            if token is not None and token.cancelled:
                break
            work_id = str(payload.get("id") or "")
            if not work_id:
                continue
            cache_key = f"{work_id}::{self._work_icon_cache_key(payload)}"
            if cache_key in self._work_icon_cache:
                continue
            image_path = fast_preview_path_for_work(payload)
            if not image_path:
                continue
            size = QSize(52, 52)
            disk_cache = self._thumbnail_disk_cache_path(cache_key, image_path)
            image = QImage(str(disk_cache)) if disk_cache.exists() else QImage()
            if image.isNull():
                source = QImage(str(image_path))
                if source.isNull():
                    continue
                image = source.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                try:
                    disk_cache.parent.mkdir(parents=True, exist_ok=True)
                    image.save(str(disk_cache), "JPG", 82)
                except Exception:
                    pass
            scaled = image.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            focal = payload.get("focal_point") or payload.get("focal") or {}
            fx = int(focal.get("x", 50) if isinstance(focal, dict) else 50)
            fy = int(focal.get("y", 50) if isinstance(focal, dict) else 50)
            painter = QPainter(scaled)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(QColor("#ffcf74"), 1))
            cx = max(2, min(50, int(round((fx / 100.0) * max(1, scaled.width())))))
            cy = max(2, min(50, int(round((fy / 100.0) * max(1, scaled.height())))))
            painter.drawLine(cx - 5, cy, cx + 5, cy)
            painter.drawLine(cx, cy - 5, cx, cy + 5)
            painter.end()
            rows.append((work_id, cache_key, scaled))
        return rows

    def _start_work_icon_loader(self, works: list[dict[str, Any]]) -> None:
        old_token = getattr(self, "_thumbnail_batch_token", None)
        if old_token is not None:
            old_token.cancel()
        token = ThumbnailBatchToken()
        self._thumbnail_batch_token = token
        pending = []
        for payload in works:
            work_id = str(payload.get("id") or "")
            if not work_id:
                continue
            cache_key = f"{work_id}::{self._work_icon_cache_key(payload)}"
            if cache_key not in self._work_icon_cache:
                pending.append(dict(payload))
            if len(pending) >= 28:
                break
        if not pending:
            self._apply_work_icons([])
            return
        worker = FunctionWorker(lambda rows=pending, batch_token=token: self._load_work_icon_images(rows, batch_token))
        self._active_workers.append(worker)
        worker.signals.result.connect(lambda rows, batch_token=token: self._apply_work_icons(rows, batch_token))
        worker.signals.error.connect(lambda tb: self.append_build_log_line(f"Thumbnail loading skipped: {tb}"))
        worker.signals.finished.connect(lambda w=worker: self._forget_worker(w))
        self.io_thread_pool.start(worker)

    def _apply_work_icons(self, rows: Any, token: ThumbnailBatchToken | None = None) -> None:
        if token is not None and token.cancelled:
            return
        if not hasattr(self, "work_tree"):
            return
        for work_id, cache_key, image in list(rows or []):
            if not work_id or image.isNull():
                continue
            self._work_icon_cache.put(cache_key, QIcon(QPixmap.fromImage(image)))
        if self._using_work_model_view():
            for row in self._works_model.rows():
                work_id = str(row.get("id") or "")
                icon = self._work_icon_cache.get(f"{work_id}::{self._work_icon_cache_key(row)}")
                if icon and not icon.isNull():
                    self._works_model.set_icon(work_id, icon)
            self.work_table.viewport().update()
            return
        for idx in range(self.work_tree.topLevelItemCount()):
            item = self.work_tree.topLevelItem(idx)
            work_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            payload = item.data(0, Qt.ItemDataRole.UserRole + 5) or {}
            icon = None
            if isinstance(payload, dict):
                icon = self._work_icon_cache.get(f"{work_id}::{self._work_icon_cache_key(payload)}")
            if icon and not icon.isNull():
                item.setIcon(0, icon)

    def on_work_selection_changed(self) -> None:
        selected = self.selected_work_ids()
        self._update_work_batch_bar()
        self.refresh_context_inspector()
        if not selected:
            self._update_work_preview_pane({})
            return
        target_id = selected[0]
        if target_id == self._current_work_id:
            return
        if not self.ensure_work_editor_safe():
            self._restore_work_selection()
            return
        self.select_work(target_id)


    def _update_work_batch_bar(self) -> None:
        if not hasattr(self, "work_batch_bar"):
            return
        count = len(self.selected_work_ids()) if hasattr(self, "work_tree") else 0
        self.work_batch_bar.setVisible(count > 1)
        if hasattr(self, "work_batch_label"):
            self.work_batch_label.setText(f"Batch · {count} selected")

    def _update_work_health_chips(self, payload: dict[str, Any] | None = None, issues: list[str] | None = None) -> None:
        if not hasattr(self, "work_health_chips"):
            return
        payload = payload or (self.current_work_payload_from_form() if hasattr(self, "work_id_edit") else {})
        issue_text = "\n".join(str(item).lower() for item in (issues if issues is not None else work_issue_list(payload)))
        def chip(key: str, state: str, text: str) -> None:
            widget = self.work_health_chips.get(key)
            if widget is not None:
                widget.set_status(state, text)
        chip("series", "ok" if payload.get("series") else "warning", "Series")
        chip("alt", "ok" if len(str(payload.get("alt") or "").strip()) >= 40 else "warning", "Alt")
        chip("caption", "ok" if len(str(payload.get("caption") or "").strip()) >= 50 else "warning", "Caption")
        asset_bad = any(token in issue_text for token in ("source", "image", "thumbnail", "asset"))
        chip("asset", "warning" if asset_bad else "ok", "Asset")
        review = str(payload.get("review_status") or "").strip().lower()
        published = bool(payload.get("published"))
        if review == "published" and published:
            publish_state = "ok"
        elif review == "published" or published:
            publish_state = "warning"
        else:
            publish_state = "info"
        chip("publish", publish_state, "Publish")


    def show_work_table_menu(self, position) -> None:
        index = self.work_table.indexAt(position)
        if not index.isValid():
            return
        work_id = self._work_id_from_model_index(index)
        if not work_id:
            return
        self._show_work_context_menu_for_id(work_id, self.work_table.viewport().mapToGlobal(position))

    def show_work_tree_menu(self, position) -> None:
        item = self.work_tree.itemAt(position)
        if item is None:
            return
        work_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if not work_id:
            return
        self._show_work_context_menu_for_id(work_id, self.work_tree.viewport().mapToGlobal(position))

    def _show_work_context_menu_for_id(self, work_id: str, global_position) -> None:
        if work_id != self._current_work_id and not self.ensure_work_editor_safe():
            self._restore_work_selection()
            return
        self.select_work(work_id, silent=True)
        menu = QMenu(self)
        copy_id = menu.addAction("Copy work ID")
        open_series = menu.addAction("Open series")
        menu.addSeparator()
        duplicate = menu.addAction("Duplicate work…")
        replace_image = menu.addAction("Replace image…")
        safe_remove = menu.addAction("Archive / delete image…")
        impact = menu.addAction("Public impact preview…")
        menu.addSeparator()
        quick_publish = menu.addAction("Toggle published")
        quick_review = menu.addAction("Advance review state")
        action = menu.exec(global_position)
        if action == copy_id:
            QApplication.clipboard().setText(work_id)
            self.status_message(f"Copied work ID: {work_id}")
        elif action == open_series:
            payload = load_work_payload(work_id)
            series_slug = str(payload.get("series") or "")
            if series_slug:
                self.tabs.setCurrentWidget(self.series_tab)
                self.select_series(series_slug)
        elif action == duplicate:
            self.duplicate_selected_work()
        elif action == replace_image:
            self.open_replace_image_dialog()
        elif action == safe_remove:
            self.safe_remove_current_work()
        elif action == impact:
            self.show_current_work_impact_report()
        elif action == quick_publish:
            payload = load_work_payload(work_id)
            new_state = not bool(payload.get("published"))
            self._remember_quick_work_state(work_id, published=new_state)
            try:
                update_work_quick_state(work_id, published=new_state)
            except Exception as exc:
                QMessageBox.critical(self, "Quick publish failed", str(exc))
                return
            self._patch_work_tree_row_after_quick_state(work_id, published=new_state)
            self._mark_work_quick_edit_dependents_dirty()
            self._show_toast("Publish state updated · use Command Palette → Undo last quick work-state change if needed")
        elif action == quick_review:
            payload = load_work_payload(work_id)
            current = str(payload.get("review_status") or "draft")
            statuses = PUBLISH_STATES
            try:
                next_status = statuses[(statuses.index(current) + 1) % len(statuses)]
            except ValueError:
                next_status = "draft"
            self._remember_quick_work_state(work_id, review_status=next_status)
            try:
                update_work_quick_state(work_id, review_status=next_status)
            except Exception as exc:
                QMessageBox.critical(self, "Quick review failed", str(exc))
                return
            self._patch_work_tree_row_after_quick_state(work_id, review_status=next_status)
            self._mark_work_quick_edit_dependents_dirty()
            self._show_toast("Review state updated · use Command Palette → Undo last quick work-state change if needed")

    def apply_batch_update(self, *, published: bool | None = None, review_status: str | None = None, series_slug: str | None = None, label: str = "Batch update") -> None:
        work_ids = self.selected_work_ids()
        if not work_ids:
            self._info_nonblocking("No works selected", "Select one or more works first.", target_scope="work")
            return
        try:
            preview = batch_update_works(work_ids, published=published, review_status=review_status, series_slug=series_slug, dry_run=True)
            changed_preview = preview.get("changed_ids") or []
            if changed_preview:
                detail = "\n".join(f"• {item}" for item in changed_preview[:25])
                if len(changed_preview) > 25:
                    detail += f"\n• … and {len(changed_preview) - 25} more"
                reply = QMessageBox.question(
                    self,
                    label,
                    f"Apply {label.lower()} to {len(changed_preview)} work(s)?\n\n{detail}",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            result = batch_update_works(work_ids, published=published, review_status=review_status, series_slug=series_slug)
        except Exception as exc:
            QMessageBox.critical(self, f"{label} failed", str(exc))
            return
        changed = result.get("changed_ids") or []
        self.status_message(f"{label}: {len(changed)} work(s) updated")
        self.refresh_work_list()
        if changed:
            self.select_work(changed[0], silent=True)
        self._mark_work_save_dependents_dirty(structural=bool(series_slug))

    def batch_publish_selected_works(self) -> None:
        self.apply_batch_update(published=True, review_status="published", label="Batch publish")

    def batch_unpublish_selected_works(self) -> None:
        self.apply_batch_update(published=False, label="Batch unpublish")

    def batch_mark_review_selected_works(self) -> None:
        self.apply_batch_update(review_status="review", label="Batch mark review")

    def batch_move_selected_works(self) -> None:
        target_series = self.batch_move_series_combo.currentText().strip()
        if not target_series:
            QMessageBox.information(self, "No target series", "Choose a target series first.")
            return
        self.apply_batch_update(series_slug=target_series, label=f"Batch move to {target_series}")


    def _fade_in_work_editor(self) -> None:
        """Subtle Phase 18 editor transition; disabled when reduced motion is active."""
        panel = getattr(self, "work_editor_panel", None)
        if getattr(self, "_reduced_motion", False) or not _qt_object_alive(panel):
            return
        try:
            effect = getattr(panel, "graphicsEffect", lambda: None)()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(panel)
                panel.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", panel)
            anim.setDuration(200)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start()
            panel._fade_in_animation = anim
        except Exception as exc:
            self._log_warning(f"Work editor fade failed: {exc}")

    def _layout_value_from_payload(self, payload: dict[str, Any], context: str) -> str:
        key = "portfolio_layout" if context == "portfolio" else "series_layout"
        camel_key = "portfolioLayout" if context == "portfolio" else "seriesLayout"
        nested = payload.get("display_layouts") if isinstance(payload.get("display_layouts"), dict) else {}
        return normalise_layout_control_value(payload.get(key) or payload.get(camel_key) or nested.get(context), "auto")

    def _ratio_value_from_payload(self, payload: dict[str, Any], context: str) -> str:
        ratios = payload.get("display_ratios") if isinstance(payload.get("display_ratios"), dict) else {}
        fallback_key = "portfolio_ratio" if context == "portfolio" else "series_ratio"
        value = ratios.get(context) if isinstance(ratios, dict) else ""
        if value is None or str(value).strip() == "":
            value = payload.get(fallback_key) or ""
        return str(value or "").strip()

    def _set_layout_combo_value(self, combo: QComboBox, value: str) -> None:
        token = normalise_layout_control_value(value, "auto")
        index = combo.findText(token)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _set_work_layout_controls_from_payload(self, payload: dict[str, Any]) -> None:
        self._current_work_display_ratios_base = dict(payload.get("display_ratios") or {}) if isinstance(payload.get("display_ratios"), dict) else {}
        self._current_work_display_layouts_base = dict(payload.get("display_layouts") or {}) if isinstance(payload.get("display_layouts"), dict) else {}
        if not hasattr(self, "work_portfolio_layout_combo"):
            return
        self._set_layout_combo_value(self.work_portfolio_layout_combo, self._layout_value_from_payload(payload, "portfolio"))
        self._set_layout_combo_value(self.work_series_layout_combo, self._layout_value_from_payload(payload, "series"))
        self.work_portfolio_ratio_edit.setText(self._ratio_value_from_payload(payload, "portfolio"))
        self.work_series_ratio_edit.setText(self._ratio_value_from_payload(payload, "series"))
        self.update_work_layout_summary()

    def _display_layouts_from_form(self) -> dict[str, str]:
        base = dict(getattr(self, "_current_work_display_layouts_base", {}) or {})
        if not hasattr(self, "work_portfolio_layout_combo"):
            return base
        for context, combo in (("portfolio", self.work_portfolio_layout_combo), ("series", self.work_series_layout_combo)):
            token = normalise_layout_control_value(combo.currentText(), "auto")
            if token == "auto":
                base.pop(context, None)
            else:
                base[context] = token
        return base

    def _display_ratios_from_form(self) -> dict[str, str]:
        base = dict(getattr(self, "_current_work_display_ratios_base", {}) or {})
        if not hasattr(self, "work_portfolio_ratio_edit"):
            return base
        for context, editor in (("portfolio", self.work_portfolio_ratio_edit), ("series", self.work_series_ratio_edit)):
            value = editor.text().strip()
            if value:
                base[context] = value
            else:
                base.pop(context, None)
        return base

    def update_work_layout_summary(self) -> None:
        if not hasattr(self, "work_layout_summary"):
            return
        portfolio = normalise_layout_control_value(self.work_portfolio_layout_combo.currentText(), "auto")
        series = normalise_layout_control_value(self.work_series_layout_combo.currentText(), "auto")
        portfolio_ratio = self.work_portfolio_ratio_edit.text().strip()
        series_ratio = self.work_series_ratio_edit.text().strip()
        ratio_bits = []
        if portfolio_ratio:
            ratio_bits.append(f"portfolio {portfolio_ratio}")
        if series_ratio:
            ratio_bits.append(f"series {series_ratio}")
        ratio_text = ", ".join(ratio_bits) if ratio_bits else "intrinsic/default"
        self.work_layout_summary.setText(f"Layout: Portfolio {portfolio} · Series {series} · Ratios: {ratio_text}")

    def select_work(self, work_id: str, *, silent: bool = False, restore_draft: bool = False) -> None:
        if not work_id:
            return
        payload = load_work_payload(work_id)
        if not payload:
            return
        if hasattr(self, "_work_preview_timer"):
            self._work_preview_timer.stop()
        self._current_work_id = work_id
        if hasattr(self, "tab_controllers") and "works" in self.tab_controllers:
            self.tab_controllers["works"].mark_current(work_id, payload)
        self._current_work_image_block = dict(payload.get("image") or {}) if isinstance(payload.get("image"), dict) else {}
        self._suspend_work_form = True
        try:
            with signals_blocked(self):
                self.work_id_edit.setText(str(payload.get("id") or ""))
                self.work_id_edit.setReadOnly(True)
                if hasattr(self, "work_unlock_id_btn"):
                    self.work_unlock_id_btn.setText("Rename ID safely…")
                self.work_title_edit.setText(str(payload.get("title") or ""))
                series_value = str(payload.get("series") or "").strip()
                if series_value and self.work_series_combo.findText(series_value) < 0:
                    self.work_series_combo.addItem(series_value)
                self.work_series_combo.setCurrentText(series_value)
                self.work_year_edit.setText(str(payload.get("year") or ""))
                self.work_location_edit.setText(str(payload.get("location") or ""))
                review = str(payload.get("review_status") or ("published" if bool(payload.get("published")) else "draft"))
                if review not in PUBLISH_STATES:
                    review = "published" if bool(payload.get("published")) else "draft"
                self.work_review_combo.setCurrentText(review)
                self.work_published_check.setChecked(bool(payload.get("published")))
                self.work_tags_edit.setText(", ".join(str(item).strip() for item in (payload.get("tags") or []) if str(item).strip()))
                self.work_hero_check.setChecked(bool(payload.get("hero_safe", True)))
                self.work_grid_check.setChecked(bool(payload.get("grid_safe", True)))
                self.work_social_check.setChecked(bool(payload.get("social_safe", False)))
                focal = payload.get("focal_point") if isinstance(payload.get("focal_point"), dict) else {}
                self.work_focal_x.setValue(int(focal.get("x", 50)))
                self.work_focal_y.setValue(int(focal.get("y", 50)))
                self.work_alt_edit.setPlainText(str(payload.get("alt") or ""))
                self.work_caption_edit.setPlainText(str(payload.get("caption") or ""))
                self._set_work_layout_controls_from_payload(payload)
                if hasattr(self, "work_private_note_edit"):
                    self.work_private_note_edit.setPlainText(load_private_note("work", work_id))
        finally:
            self._suspend_work_form = False
        self.update_work_preview()
        self._update_work_preview_pane(payload)
        self._fade_in_work_editor()
        self._sync_work_gallery_selection(work_id)
        self.update_work_text_stats()
        self._loaded_work_snapshot = self.current_work_payload_from_form()
        self._reset_autosave_state("work")
        if hasattr(self, "work_breadcrumb"):
            title = str(payload.get("title") or work_id)
            series = str(payload.get("series") or "—")
            self.work_breadcrumb.setText(f"Works  ›  {title}  ·  {series}")
        self.maybe_restore_editor_draft("work", work_id, interactive=restore_draft)
        self.focus_first_problematic_work_field(self.current_work_payload_from_form())
        self._update_autosave_labels()
        if not silent:
            self.status_message(f"Loaded work: {work_id}")
        if self._using_work_model_view():
            self._select_work_row_by_id(work_id)
        else:
            for idx in range(self.work_tree.topLevelItemCount()):
                item = self.work_tree.topLevelItem(idx)
                if item.data(0, Qt.ItemDataRole.UserRole) == work_id:
                    with signals_blocked(self.work_tree):
                        self.work_tree.setCurrentItem(item)
                        item.setSelected(True)
                        self.work_tree.scrollToItem(item)
                    break

    def populate_work_form(self, payload: dict[str, Any], *, reset_snapshot: bool = True) -> None:
        """Populate the Work editor from an in-memory payload without changing selection.

        Template application previously called this method but it did not exist,
        which made saved templates a crash path. It deliberately keeps the current
        image block unless the payload explicitly provides one. Population blocks
        child-widget signals so loading a work never schedules a phantom autosave.
        """
        payload = dict(payload or {})
        if isinstance(payload.get("image"), dict):
            self._current_work_image_block = dict(payload.get("image") or {})
        self._suspend_work_form = True
        try:
            with signals_blocked(self):
                self.work_id_edit.setText(str(payload.get("id") or ""))
                self.work_title_edit.setText(str(payload.get("title") or ""))
                series_value = str(payload.get("series") or "").strip()
                if series_value and self.work_series_combo.findText(series_value) < 0:
                    self.work_series_combo.addItem(series_value)
                self.work_series_combo.setCurrentText(series_value)
                self.work_year_edit.setText(str(payload.get("year") or ""))
                self.work_location_edit.setText(str(payload.get("location") or ""))
                review = str(payload.get("review_status") or ("published" if bool(payload.get("published")) else "draft"))
                if review not in PUBLISH_STATES:
                    review = "published" if bool(payload.get("published")) else "draft"
                self.work_review_combo.setCurrentText(review)
                self.work_published_check.setChecked(bool(payload.get("published")))
                self.work_tags_edit.setText(", ".join(str(item).strip() for item in (payload.get("tags") or []) if str(item).strip()))
                self.work_hero_check.setChecked(bool(payload.get("hero_safe", True)))
                self.work_grid_check.setChecked(bool(payload.get("grid_safe", True)))
                self.work_social_check.setChecked(bool(payload.get("social_safe", False)))
                focal = payload.get("focal_point") if isinstance(payload.get("focal_point"), dict) else {}
                self.work_focal_x.setValue(int(focal.get("x", 50)))
                self.work_focal_y.setValue(int(focal.get("y", 50)))
                self.work_alt_edit.setPlainText(str(payload.get("alt") or ""))
                self.work_caption_edit.setPlainText(str(payload.get("caption") or ""))
                self._set_work_layout_controls_from_payload(payload)
        finally:
            self._suspend_work_form = False
        self.update_work_preview()
        self._update_work_preview_pane(payload)
        self.update_work_text_stats()
        if reset_snapshot:
            self._loaded_work_snapshot = self.current_work_payload_from_form()
            self._reset_autosave_state("work")
        self.focus_first_problematic_work_field(self.current_work_payload_from_form())
        self._update_autosave_labels()

    def _safe_current_work_series_slug(self) -> str:
        series_value = self.work_series_combo.currentText().strip() if hasattr(self, "work_series_combo") else ""
        if series_value:
            return series_value
        work_id = str(getattr(self, "_current_work_id", "") or "").strip()
        if work_id:
            try:
                payload = load_work_payload(work_id) or {}
                fallback = str(payload.get("series") or "").strip()
                if fallback:
                    if hasattr(self, "work_series_combo") and self.work_series_combo.findText(fallback) < 0:
                        self.work_series_combo.addItem(fallback)
                    if hasattr(self, "work_series_combo"):
                        with signals_blocked(self.work_series_combo):
                            self.work_series_combo.setCurrentText(fallback)
                    return fallback
            except Exception as exc:
                self._log_warning(f"Could not restore work series for {work_id}: {exc}")
        return ""

    def current_work_payload_from_form(self) -> dict[str, Any]:
        portfolio_layout = normalise_layout_control_value(self.work_portfolio_layout_combo.currentText(), "auto") if hasattr(self, "work_portfolio_layout_combo") else "auto"
        series_layout = normalise_layout_control_value(self.work_series_layout_combo.currentText(), "auto") if hasattr(self, "work_series_layout_combo") else "auto"
        payload = {
            "id": self.work_id_edit.text().strip(),
            "title": self.work_title_edit.text().strip(),
            "series": self._safe_current_work_series_slug(),
            "year": self.work_year_edit.text().strip(),
            "location": self.work_location_edit.text().strip(),
            "alt": self.work_alt_edit.toPlainText().strip(),
            "caption": self.work_caption_edit.toPlainText().strip(),
            "tags": [item.strip() for item in self.work_tags_edit.text().split(",") if item.strip()],
            "review_status": self.work_review_combo.currentText().strip(),
            "published": self.work_published_check.isChecked(),
            "hero_safe": self.work_hero_check.isChecked(),
            "grid_safe": self.work_grid_check.isChecked(),
            "social_safe": self.work_social_check.isChecked(),
            "portfolio_layout": portfolio_layout,
            "series_layout": series_layout,
            "display_layouts": self._display_layouts_from_form(),
            "display_ratios": self._display_ratios_from_form(),
            "focal_point": {"x": self.work_focal_x.value(), "y": self.work_focal_y.value()},
            "image": dict(getattr(self, "_current_work_image_block", {}) or {}),
        }
        return payload

    def _validation_border(self, severity: str) -> str:
        severity_text = str(severity or "").lower()
        if severity_text == "error":
            return "#ff7a7a"
        if severity_text in {"warning", "warn"}:
            return "#ffcf74"
        return "#70e0a2"

    def _set_field_validation_state(self, widget: QWidget, severity: str | None = None, message: str = "") -> None:
        if widget is None:
            return
        if severity:
            widget.setProperty("validation", str(severity or "").lower())
            widget.setToolTip(message)
        else:
            widget.setProperty("validation", "")
            widget.setToolTip("")
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _validate_work_form(self) -> bool:
        if not hasattr(self, "work_save_btn") or getattr(self, "_suspend_work_form", False):
            return True
        payload = self.current_work_payload_from_form()
        rows = validate_editor_payload("work", payload, original_key=self._current_work_id)
        field_widgets = {
            "id": self.work_id_edit,
            "title": self.work_title_edit,
            "series": self.work_series_combo,
            "review_status": self.work_review_combo,
            "alt": self.work_alt_edit,
            "caption": self.work_caption_edit,
            "portfolio_layout": getattr(self, "work_portfolio_layout_combo", None),
            "series_layout": getattr(self, "work_series_layout_combo", None),
            "display_ratios.portfolio": getattr(self, "work_portfolio_ratio_edit", None),
            "display_ratios.series": getattr(self, "work_series_ratio_edit", None),
            "focal_point.x": self.work_focal_x,
            "focal_point.y": self.work_focal_y,
        }
        for widget in field_widgets.values():
            self._set_field_validation_state(widget)
        has_errors = False
        messages: list[str] = []
        for row in rows:
            field = str(row.get("field") or "")
            severity = str(row.get("severity") or "warning")
            message = str(row.get("message") or "")
            if severity == "error":
                has_errors = True
            messages.append(f"{severity.upper()} · {field}: {message}")
            widget = field_widgets.get(field)
            if widget is not None:
                self._set_field_validation_state(widget, severity, message)
        for field, editor in (("display_ratios.portfolio", getattr(self, "work_portfolio_ratio_edit", None)), ("display_ratios.series", getattr(self, "work_series_ratio_edit", None))):
            if editor is not None and not ratio_text_is_valid(editor.text()):
                message = "Use a positive width / height ratio such as 4 / 3 or 16 / 9, or leave blank."
                messages.append(f"WARNING · {field}: {message}")
                self._set_field_validation_state(editor, "warning", message)
        backend_issues = work_issue_list(payload)
        if hasattr(self, "work_issue_hint"):
            combined = messages + [f"INFO · issue: {issue}" for issue in backend_issues]
            self.work_issue_hint.setPlainText("\n".join(f"• {line}" for line in combined) if combined else "No validation issues for this work.")
        self._update_work_health_chips(payload, backend_issues)
        self.work_save_btn.setEnabled(not has_errors)
        return not has_errors

    def _payload_diff_summary(self, before: dict[str, Any], after: dict[str, Any], *, limit: int = 6) -> str:
        before_text = yaml.safe_dump(before or {}, sort_keys=False, allow_unicode=True).splitlines()
        after_text = yaml.safe_dump(after or {}, sort_keys=False, allow_unicode=True).splitlines()
        changed = [line for line in unified_diff(before_text, after_text, lineterm="") if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
        if not changed:
            return "No payload changes detected."
        preview = " / ".join(changed[:limit])
        if len(changed) > limit:
            preview += f" / … {len(changed) - limit} more"
        return preview

    def show_payload_preview(self, title: str, payload: dict[str, Any]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(760, 620)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(yaml.safe_dump(payload or {}, sort_keys=False, allow_unicode=True))
        layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def show_current_work_payload_preview(self) -> None:
        self.show_payload_preview("Current work payload preview", self.current_work_payload_from_form())

    def _operation_report_lines(self, title: str, report: dict[str, Any] | None) -> list[str]:
        report = dict(report or {})
        lines = [title, ""]
        for key in ("operation", "old_work_id", "new_work_id", "old_series", "new_series", "old_yaml", "new_yaml", "old_source", "new_source", "old_derivatives", "new_derivatives"):
            value = report.get(key)
            if value:
                lines.append(f"{key.replace('_', ' ').title()}: {value}")
        verification = report.get("verification") if isinstance(report.get("verification"), dict) else {}
        if verification:
            lines.extend(["", "Verification:"])
            errors = verification.get("errors") or []
            warnings = verification.get("warnings") or []
            info = verification.get("info") or []
            if not errors and not warnings:
                lines.append("- Clean")
            for item in errors:
                lines.append(f"- ERROR: {item}")
            for item in warnings:
                lines.append(f"- WARNING: {item}")
            for item in info[:12]:
                lines.append(f"- INFO: {item}")
        reference_updates = report.get("reference_updates") or []
        if reference_updates:
            lines.extend(["", "Reference updates:"])
            lines.extend(f"- {item}" for item in reference_updates[:20])
            if len(reference_updates) > 20:
                lines.append(f"- … and {len(reference_updates) - 20} more")
        stale = report.get("reference_scan") or report.get("stale_references") or []
        if stale:
            lines.extend(["", "Stale reference scan:"])
            for row in stale[:20]:
                lines.append(f"- {row.get('match')}: {row.get('file')} {row.get('path')} = {row.get('value')}")
            if len(stale) > 20:
                lines.append(f"- … and {len(stale) - 20} more")
        removed = report.get("removed_stale_originals") or []
        if removed:
            lines.extend(["", "Removed stale source files:"])
            lines.extend(f"- {item}" for item in removed)
        presence = report.get("presence") if isinstance(report.get("presence"), dict) else {}
        if presence:
            lines.extend(["", "Asset presence:"])
            lines.append(f"- Status: {presence.get('status') or '-'}")
            lines.append(f"- Active source: {presence.get('active_source') or '-'}")
            lines.append(f"- Derivative count: {presence.get('derivative_count') or 0}")
            extras = presence.get("extra_sources") or []
            if extras:
                lines.append("- Extra source candidates:")
                lines.extend(f"  - {item}" for item in extras)
        return lines

    def show_operation_report(self, title: str, report: dict[str, Any] | None, *, force: bool = False) -> None:
        report = dict(report or {})
        verification = report.get("verification") if isinstance(report.get("verification"), dict) else {}
        has_warning = bool((verification.get("warnings") or []) or report.get("removed_stale_originals") or report.get("reference_updates"))
        has_error = bool(verification.get("errors") or report.get("stale_references"))
        if not force and not has_warning and not has_error:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(820, 620)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText("\n".join(self._operation_report_lines(title, report)))
        layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def confirm_work_change_preview(self, old_work_id: str | None, payload: dict[str, Any]) -> bool:
        new_work_id = str(payload.get("id") or "").strip()
        if not old_work_id or old_work_id == new_work_id:
            return True
        try:
            preview = preview_work_change_map(old_work_id, payload)
        except Exception as exc:
            QMessageBox.critical(self, "Rename preview failed", f"Could not build the Work ID rename plan:\n{exc}")
            return False
        lines = [
            f"Rename Work ID: {old_work_id} → {new_work_id}",
            "",
            f"YAML: {preview.get('old_yaml') or '-'} → {preview.get('new_yaml') or '-'}",
            f"Source: {preview.get('old_source') or '-'} → {preview.get('new_source') or '-'}",
            f"Derivatives: {preview.get('old_derivatives') or '-'} → {preview.get('new_derivatives') or '-'}",
            "",
            "This will update exact content references, relationship refs, source image name, derivative folder, caches, drafts, and the current selection.",
        ]
        stale = preview.get("reference_scan") or []
        exact = [row for row in stale if row.get("match") == "exact"]
        contains = [row for row in stale if row.get("match") == "contains"]
        if exact or contains:
            lines.extend(["", f"Pre-save reference scan: {len(exact)} exact · {len(contains)} containing old ID"])
        reply = QMessageBox.question(
            self,
            "Confirm Work ID rename transaction",
            "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        self._pending_work_change_preview = preview
        return True

    def run_startup_preflight(self) -> None:
        try:
            report = startup_preflight_checks(fast=bool(getattr(self, "_safe_mode", False)))
        except Exception as exc:
            self._log_warning(f"Startup preflight failed: {exc}")
            report = {"ok": False, "errors": 1, "warnings": 0, "rows": [{"status": "error", "check": "startup preflight", "detail": str(exc)}]}
        guard = getattr(self, "_startup_guard_report", {}) or {}
        rows = list(guard.get("rows") or []) + list((report or {}).get("rows") or [])
        errors = sum(1 for row in rows if row.get("status") == "error")
        warnings = sum(1 for row in rows if row.get("status") == "warning")
        report = {**dict(report or {}), "rows": rows, "errors": errors, "warnings": warnings, "ok": errors == 0}
        self._startup_preflight_report = dict(report or {})
        if errors or warnings:
            detail = f"{errors} error(s), {warnings} warning(s). Open Notifications or Publish Ops for context."
            self.push_notification("error" if errors else "warning", "Startup health check needs attention", detail, target_scope="publish")
            if hasattr(self, "build_log"):
                self.append_build_log_line("Startup health check:")
                for row in rows:
                    if row.get("status") != "ok":
                        self.append_build_log_line(f"⚠ {row.get('check')}: {row.get('detail')}")
        else:
            self.push_notification("success", "Startup health check passed", f"{len(rows)} checks completed.", target_scope="dashboard")
        self._update_session_health()

    def focus_first_problematic_work_field(self, payload: dict[str, Any]) -> None:
        issue_map = {
            "missing caption": self.work_caption_edit,
            "weak alt text": self.work_alt_edit,
            "placeholder alt text": self.work_alt_edit,
            "missing title": self.work_title_edit,
            "placeholder caption": self.work_caption_edit,
            "missing focal point": self.work_focal_x,
        }
        issues = work_issue_list(payload)
        self.work_issue_hint.setPlainText("\n".join(f"• {issue}" for issue in issues) if issues else "No validation issues for this work.")
        self._update_work_health_chips(payload, issues)
        self.refresh_context_inspector()
        if issues:
            widget = issue_map.get(issues[0])
            if widget is not None:
                widget.setFocus()

    def update_work_text_stats(self) -> None:
        if not hasattr(self, "work_alt_stats"):
            return
        alt = self.work_alt_edit.toPlainText().strip() if hasattr(self, "work_alt_edit") else ""
        caption = self.work_caption_edit.toPlainText().strip() if hasattr(self, "work_caption_edit") else ""
        def apply(label: QLabel, n: int, min_len: int, max_len: int) -> None:
            label.setText(f"{n} / {max_len}")
            if n > max_len:
                state = "error"
            elif n >= min_len:
                state = "ok"
            else:
                state = "warning"
            label.setProperty("state", state)
            label.style().unpolish(label)
            label.style().polish(label)
        apply(self.work_alt_stats, len(alt), 40, 125)
        apply(self.work_caption_stats, len(caption), 50, 300)
        if hasattr(self, "work_title_counter"):
            title = self.work_title_edit.text().strip() if hasattr(self, "work_title_edit") else ""
            apply(self.work_title_counter, len(title), 12, 80)
        # Do not recalculate side-nav/tab badges on every keystroke. Saves,
        # selections and explicit refreshes update those counters.

    def schedule_work_validation(self) -> None:
        if getattr(self, "_suspend_work_form", False):
            return
        if hasattr(self, "_work_validation_timer"):
            self._work_validation_timer.start()

    def schedule_work_preview_update(self) -> None:
        if getattr(self, "_suspend_work_form", False):
            return
        if hasattr(self, "_work_preview_timer"):
            self._work_preview_timer.start()

    def update_work_preview(self) -> None:
        if self._suspend_work_form:
            return
        payload = self.current_work_payload_from_form()
        issues = work_issue_list(payload)
        self.work_issue_hint.setPlainText("\n".join(f"• {issue}" for issue in issues) if issues else "No validation issues for this work.")
        self._update_work_health_chips(payload, issues)
        self.refresh_context_inspector()
        work_id = payload.get("id") or self._current_work_id or ""
        series_slug = payload.get("series") or ""
        image_path = None
        if work_id and series_slug:
            from qt_backend import source_path_for_work, load_pipeline
            try:
                image_path = source_path_for_work(series_slug, work_id, load_pipeline())
            except Exception as exc:
                self._log_warning(f"Work preview source lookup failed: {exc}")
                image_path = None
        size = QSize(520, 320)
        if image_path and Path(image_path).exists():
            signature = self._preview_file_signature(
                image_path,
                size,
                work_id,
                series_slug,
                int(self.work_focal_x.value()) if hasattr(self, "work_focal_x") else 50,
                int(self.work_focal_y.value()) if hasattr(self, "work_focal_y") else 50,
            )
            if getattr(self, "_work_main_preview_signature", None) != signature:
                scaled = self._scaled_work_preview_pixmap(image_path, size)
                if not scaled.isNull():
                    self._work_main_preview_signature = signature
                    self.work_image_preview.setText("")
                    self.work_image_preview.setPixmap(scaled)
                    self.work_image_preview.setToolTip(str(Path(image_path)))
            if hasattr(self, "work_image_status_label"):
                self.work_image_status_label.setText(f"Source linked · {Path(image_path).name}")
            self._update_work_preview_pane(payload)
            return
        details = "No image preview available"
        if work_id and series_slug:
            details += f"\nMissing source image for {work_id} in {series_slug}."
        missing_signature = self._preview_file_signature(None, size, work_id, series_slug, details)
        if getattr(self, "_work_main_preview_signature", None) != missing_signature:
            self._work_main_preview_signature = missing_signature
            self.work_image_preview.setPixmap(QPixmap())
            self.work_image_preview.setText(details)
            self.work_image_preview.setToolTip(details)
        if hasattr(self, "work_image_status_label"):
            self.work_image_status_label.setText(details.replace("\n", " · "))
        self._update_work_preview_pane(payload)

    def _set_work_save_state(self, state: str, detail: str = "") -> None:
        """Single save-controller state for button, Ctrl+S, dirty and error feedback."""
        self._work_save_state = str(state or "clean")
        if not hasattr(self, "work_save_btn"):
            return
        saving = self._work_save_state in {"validating", "saving"}
        failed = self._work_save_state == "failed"
        self.work_save_btn.setEnabled(not saving)
        if saving:
            self.work_save_btn.setText("Saving…")
        elif failed:
            self.work_save_btn.setText("Save failed · fix/retry")
        elif self.is_work_dirty() if hasattr(self, "work_id_edit") else False:
            self.work_save_btn.setText("Save work * · Ctrl+S")
        else:
            self.work_save_btn.setText("Save work · Ctrl+S")
        if hasattr(self, "progress_hint"):
            if saving:
                self.progress_hint.setText(detail or "Saving work metadata…")
            elif detail:
                self.progress_hint.setText(detail)

    def _work_save_failed(self, request_id: int, detail: str, work_id: str = "") -> None:
        if int(request_id) != int(getattr(self, "_work_save_request_id", 0) or 0):
            return
        self._set_work_save_state("failed", "Save failed")
        self._log_warning(f"Save work failed for {work_id or '-'}: {detail}")
        self._critical_modal("Save work failed", str(detail), target_scope="work", target_id=work_id or self._current_work_id)
        self._validate_work_form()

    def _apply_saved_work_result(self, result_state: dict[str, Any]) -> None:
        started = float((result_state or {}).get("started") or time.perf_counter())
        request_id = int((result_state or {}).get("request_id") or 0)
        if request_id != int(getattr(self, "_work_save_request_id", 0) or 0):
            self._record_dirty_refresh_diagnostic("work-save", 0.0, f"Ignored stale work save result #{request_id}")
            return
        old_work_id = str((result_state or {}).get("old_work_id") or "")
        work_id = str((result_state or {}).get("work_id") or "")
        payload = dict((result_state or {}).get("payload") or {})
        before_payload = dict((result_state or {}).get("before_payload") or {})
        after_payload = dict((result_state or {}).get("after_payload") or payload)
        structural_change = bool((result_state or {}).get("structural_change"))
        result = dict((result_state or {}).get("result") or {})
        verification = dict(result.get("verification") or {})
        exact_stale = list((result_state or {}).get("exact_stale") or [])
        for key in {old_work_id, work_id}:
            if key:
                clear_editor_draft("work", key)
                self._draft_restore_seen.discard(("work", key))
                self._last_draft_hash.pop(("work", key), None)
                self.clear_work_icon_cache(key)
        self._current_work_id = work_id
        self._current_work_image_block = dict(after_payload.get("image") or {}) if isinstance(after_payload.get("image"), dict) else {}
        self._loaded_work_snapshot = dict(after_payload)
        if exact_stale:
            self.push_notification("error", f"Saved work with stale refs: {work_id}", f"{len(exact_stale)} exact stale reference(s) remain.", target_scope="validation")
        self.push_notification("success", f"Saved work: {work_id}", payload.get("title") or "", target_scope="work", target_id=work_id)
        self._reset_autosave_state("work")
        self._show_toast(f"✓ Saved: {payload.get('title') or work_id}")
        self._mark_saved()
        self._store_payload_diff("work", before_payload, after_payload)
        report = dict(getattr(self, "_pending_work_change_preview", {}) or {})
        if old_work_id == work_id:
            report.update({"operation": "save-work", "old_work_id": old_work_id, "new_work_id": work_id})
        report.update({"verification": verification, "reference_updates": result.get("reference_updates") or [], "stale_references": exact_stale})
        if old_work_id and old_work_id != work_id:
            self.show_operation_report("Work ID rename transaction report", report, force=True)
        else:
            self.show_operation_report("Work save verification report", report, force=False)
        self._pending_work_change_preview = {}
        if structural_change:
            self.refresh_reference_controls("work")
            self.refresh_work_list()
            self.select_work(work_id, silent=True)
        else:
            self._patch_work_tree_row_after_save(old_work_id, work_id, after_payload)
        self._mark_work_save_dependents_dirty(structural=structural_change)
        self._schedule_visible_asset_health_check()
        self._schedule_visible_thumbnail_load()
        elapsed = time.perf_counter() - started
        self._last_work_save_ms = elapsed * 1000.0
        self._set_work_save_state("saved", "Saved")
        self._record_perf("work save async", elapsed, "structural" if structural_change else "metadata-only")
        self.status_message(f"Saved work: {work_id} · {self._payload_diff_summary(before_payload, after_payload)} · UI patched in {elapsed * 1000:.0f} ms")
        self._update_autosave_labels()
        self._validate_work_form()

    def save_current_work(self) -> None:
        # Batch C keeps the metadata-only path as a local row patch: _patch_work_tree_row_after_save.
        # Perf label compatibility: work save local patch.
        started = time.perf_counter()
        self._commit_pending_editor_edits("work")
        self._set_work_save_state("validating", "Validating work metadata…")
        if not self._validate_work_form():
            self._set_work_save_state("failed", "Fix highlighted work fields before saving.")
            QMessageBox.warning(self, "Invalid work", "Fix highlighted work fields before saving.")
            return
        old_work_id = self._current_work_id
        before_payload = load_work_payload(old_work_id or "") if old_work_id else {}
        payload = self.current_work_payload_from_form()
        new_work_id = str(payload.get("id") or "").strip()
        old_series = str((before_payload or {}).get("series") or "")
        new_series = str(payload.get("series") or "")
        structural_change = bool(old_work_id and new_work_id and old_work_id != new_work_id) or bool(old_series and new_series and old_series != new_series)
        if old_work_id and new_work_id and old_work_id != new_work_id:
            if not self.confirm_work_change_preview(old_work_id, payload):
                self._set_work_save_state("dirty", "Work ID rename cancelled")
                self.status_message("Work ID rename cancelled")
                return
        request_id = int(getattr(self, "_work_save_request_id", 0) or 0) + 1
        self._work_save_request_id = request_id
        self._set_work_save_state("saving", f"Saving work: {new_work_id or old_work_id or '-'}…")

        def task(*, task_context: TaskContext | None = None) -> dict[str, Any]:
            if task_context is not None:
                task_context.stage("Writing work YAML", progress=25)
            result = save_work_from_payload(old_work_id, dict(payload))
            work_id = str(result.get("work_id") or new_work_id or old_work_id or "")
            if task_context is not None:
                task_context.stage("Loading saved work", progress=70)
                task_context.check_cancelled()
            after_payload = load_work_payload(work_id) or dict(payload, id=work_id)
            exact_stale: list[dict[str, Any]] = []
            if old_work_id and old_work_id != work_id:
                if task_context is not None:
                    task_context.stage("Checking renamed references", progress=88)
                post_stale = scan_stale_references(str(old_work_id or ""), work_id, include_runtime=False)
                exact_stale = [row for row in post_stale if row.get("match") == "exact"]
            return {
                "request_id": request_id,
                "started": started,
                "old_work_id": old_work_id,
                "work_id": work_id,
                "payload": dict(payload),
                "before_payload": before_payload,
                "after_payload": after_payload,
                "structural_change": structural_change,
                "result": result,
                "exact_stale": exact_stale,
            }

        self.start_keyed_background_task(
            "work-save",
            task,
            on_done=self._apply_saved_work_result,
            on_error=lambda detail, rid=request_id, wid=(old_work_id or new_work_id or ""): self._work_save_failed(rid, detail, wid),
            label="Save work metadata",
            cancel_previous=False,
        )

    def reload_current_work(self) -> None:
        if self._current_work_id and self.ensure_work_editor_safe():
            self._draft_restore_seen.discard(("work", self._current_work_id))
            self._last_draft_hash.pop(("work", self._current_work_id), None)
            self.select_work(self._current_work_id)

    def open_add_image_dialog(self) -> None:
        dialog = AddImageDialog(self)
        dialog.exec()

    def open_replace_image_dialog(self) -> None:
        work_id = self._current_work_id
        if not work_id:
            self._info_nonblocking("No work selected", "Select a work first.", target_scope="work")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choose replacement image", str(ROOT), "Images (*.jpg *.jpeg *.png *.webp *.tif *.tiff)")
        if not path:
            return
        try:
            preview = preview_replace_work_image(work_id, path)
        except Exception as exc:
            QMessageBox.critical(self, "Replacement preview failed", f"Could not build a safe image replacement plan:\n{exc}")
            return
        stale_sources = list(preview.get("stale_same_id_sources_to_remove") or [])
        confirm_lines = [
            f"Replace source image for: {work_id}",
            "",
            f"Current source: {preview.get('current_source') or '-'}",
            f"Incoming file: {preview.get('incoming_file') or path}",
            f"Target source: {preview.get('target_source') or '-'}",
            f"Derivatives: {preview.get('derivative_dir_to_regenerate') or '-'}",
            "",
            "Planned transaction:",
        ]
        confirm_lines.extend([f"• {item}" for item in preview.get("updates") or []])
        if stale_sources:
            confirm_lines.extend(["", f"Stale same-ID originals to remove: {len(stale_sources)}"])
            confirm_lines.extend([f"• {item}" for item in stale_sources[:8]])
            if len(stale_sources) > 8:
                confirm_lines.append(f"• … and {len(stale_sources) - 8} more")
        if QMessageBox.question(
            self,
            "Confirm image replacement",
            "\n".join(confirm_lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            self.status_message("Image replacement cancelled")
            return
        try:
            result = replace_work_image(work_id, path)
        except Exception as exc:
            self._log_warning(f"Replace image failed for {work_id}: {exc}")
            QMessageBox.critical(self, "Replace image failed", str(exc))
            return
        self.clear_work_icon_cache(work_id)
        presence = result.get("presence") if isinstance(result, dict) else {}
        removed = result.get("removed_stale_originals") if isinstance(result, dict) else []
        level = "success" if (presence or {}).get("status") == "clean" else "warning"
        detail = f"{path}"
        if removed:
            detail += f" · removed {len(removed)} stale original(s)"
        self.push_notification(level, f"Replaced image for {work_id}", detail, target_scope="work", target_id=work_id)
        self.show_operation_report("Image replacement transaction report", result, force=bool(removed) or level == "warning")
        self.status_message(f"Replaced image for {work_id}")
        # Keep image replacement local to Works; dependent heavy views are marked
        # dirty and refreshed when opened, not during the editing flow.
        self.refresh_work_list()
        self.select_work(work_id, silent=True)
        self._mark_work_save_dependents_dirty(structural=False)

    def duplicate_selected_work(self) -> None:
        work_id = self._current_work_id
        if not work_id:
            self._info_nonblocking("No work selected", "Select a work first.", target_scope="work")
            return
        dialog = DuplicateWorkDialog(self, work_id)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_id = dialog.created_work_id
        if not new_id:
            return
        self.push_notification("success", f"Duplicated {work_id}", f"New metadata-only draft created as {new_id}", target_scope="work", target_id=new_id)
        self.status_message(f"Duplicated {work_id} as draft {new_id}")
        self.refresh_all_context(activate="works", select_work=new_id, force=True, scope={"works", "series", "dashboard", "validation", "studio"})

    def safe_remove_current_work(self) -> None:
        work_id = str(getattr(self, "_current_work_id", "") or "").strip()
        if not work_id:
            QMessageBox.information(self, "No work selected", "Select a saved work first.")
            return
        try:
            preview = safe_remove_work_preview(work_id)
        except Exception as exc:
            QMessageBox.critical(self, "Delete preview failed", str(exc))
            return

        blockers = [str(item) for item in (preview.get("blockers") or []) if str(item).strip()]
        series_hits = list(preview.get("series_hits") or [])
        page_hits = list(preview.get("page_hits") or [])
        title_text = str(preview.get("title") or "-")
        lines = [
            f"Work: {work_id}",
            f"Title: {title_text}",
            f"Series references: {len(series_hits)}",
            f"Page references: {len(page_hits)}",
            "",
        ]
        if blockers:
            lines.append("References will be pruned if you choose full delete:")
            lines.extend(f"• {item}" for item in blockers[:12])
            if len(blockers) > 12:
                lines.append(f"• … and {len(blockers) - 12} more")
            lines.append("")
        lines.extend([
            "Choose Archive only if you want to hide the image but keep files.",
            "Choose Delete image + assets to remove:",
            "• work YAML metadata",
            "• references from series/pages/home selections",
            "• original/source image file(s)",
            "• generated derivative folder/file(s)",
            "• now-empty work asset folders",
        ])

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Archive or delete selected image")
        box.setText("\n".join(lines))
        archive_btn = box.addButton("Archive only", QMessageBox.ButtonRole.AcceptRole)
        delete_btn = box.addButton("Delete image + assets", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_btn or clicked is None:
            return

        archive_only = clicked is archive_btn
        remove_assets = False
        force_delete = False

        if clicked is delete_btn:
            confirm_text = (
                f"Delete '{title_text}' completely?\n\n"
                f"Work ID: {work_id}\n\n"
                "This will remove the work metadata, original/source image, generated derivatives, "
                "and matching references from series/pages. Transaction backups are created, but this "
                "is still a destructive library cleanup action."
            )
            if QMessageBox.question(
                self,
                "Confirm full image deletion",
                confirm_text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
            archive_only = False
            remove_assets = True
            force_delete = True

        try:
            result = safe_remove_work(work_id, archive_only=archive_only, remove_assets=remove_assets, force=force_delete)
        except Exception as exc:
            QMessageBox.critical(self, "Image delete failed" if remove_assets else "Archive failed", str(exc))
            return

        self.clear_work_icon_cache(work_id)
        title = "Work archived" if archive_only else "Image deleted"
        self.push_notification("success", title, work_id, target_scope="work", target_id=work_id)
        self.show_operation_report(f"{title} transaction report", result, force=True)
        self.status_message(f"{title}: {work_id}")
        self._current_work_id = ""
        self.refresh_all_context(activate="works", force=True, scope={"works", "series", "relationships", "dashboard", "validation", "studio", "publish"})


    def quick_edit_work_model_cell(self, index) -> None:
        if index is None or not index.isValid():
            return
        work_id = self._work_id_from_model_index(index)
        payload = self._work_model_payload_for_id(work_id)
        self._quick_edit_work_cell(
            work_id,
            int(index.column()),
            published=bool(payload.get("published")),
            review_status=str(payload.get("review_status") or "draft"),
        )

    def quick_edit_work_list_cell(self, item: QTreeWidgetItem, column: int) -> None:
        work_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        self._quick_edit_work_cell(
            work_id,
            int(column),
            published=item.text(4).strip().lower() == "yes",
            review_status=item.text(3).strip() or "draft",
        )

    def _quick_edit_work_cell(self, work_id: str, column: int, *, published: bool, review_status: str) -> None:
        if not work_id:
            return
        if column == 4:
            new_state = not bool(published)
            self._remember_quick_work_state(work_id, published=new_state)
            try:
                result = update_work_quick_state(work_id, published=new_state)
            except Exception as exc:
                QMessageBox.critical(self, "Quick publish failed", str(exc))
                return
            self.push_notification("success", "Updated publish state", f"{work_id}: {', '.join(result.get('changed') or [])}", target_scope="work", target_id=work_id)
            self._patch_work_tree_row_after_quick_state(work_id, published=new_state)
            self._show_toast("Publish state updated · undo available in command palette")
            self._mark_work_quick_edit_dependents_dirty()
            self.status_message(f"Updated publish state for {work_id} without a full Works refresh")
        elif column == 3:
            statuses = PUBLISH_STATES
            current = review_status or "draft"
            try:
                idx = statuses.index(current)
            except ValueError:
                idx = 0
            next_status = statuses[(idx + 1) % len(statuses)]
            self._remember_quick_work_state(work_id, review_status=next_status)
            try:
                update_work_quick_state(work_id, review_status=next_status)
            except Exception as exc:
                QMessageBox.critical(self, "Quick review update failed", str(exc))
                return
            self._patch_work_tree_row_after_quick_state(work_id, review_status=next_status)
            self._show_toast("Review state updated · undo available in command palette")
            self._mark_work_quick_edit_dependents_dirty()
            self.status_message(f"Updated review state for {work_id} without a full Works refresh")
        elif column in {5, 6, 7}:
            self.show_current_work_impact_report()

    def show_current_work_impact_report(self) -> None:
        work_id = self._current_work_id
        if not work_id:
            self._info_nonblocking("No work selected", "Select a work first.", target_scope="work")
            return
        try:
            impact = work_public_impact_report(work_id)
            remove_preview = safe_remove_work_preview(work_id)
        except Exception as exc:
            QMessageBox.critical(self, "Impact report failed", str(exc))
            return
        lines = [
            f"Work: {impact.get('work_id')} · {impact.get('title') or '-'}",
            f"Series: {impact.get('series') or '-'}",
            f"Published: {impact.get('published')} · Review: {impact.get('review_status') or '-'}",
            f"Source: {impact.get('source_status') or '-'} · {impact.get('source_detail') or '-'}",
            "",
            "Series usage:",
        ]
        for hit in impact.get("series_hits") or []:
            lines.append(f"- {hit.get('slug')}: position {hit.get('position') or '-'} · cover={hit.get('is_cover')}")
        if not impact.get("series_hits"):
            lines.append("- None")
        lines.extend(["", "Page references:"])
        for hit in impact.get("page_hits") or []:
            lines.append(f"- {hit.get('page')}: {hit.get('count')} reference(s) · {', '.join(hit.get('references') or [])}")
        if not impact.get("page_hits"):
            lines.append("- None")
        lines.extend(["", "Remove/Archive preview:"])
        lines.append(f"Recommended action: {remove_preview.get('recommended_action')}")
        blockers = remove_preview.get("blockers") or []
        lines.extend([f"- {item}" for item in blockers] or ["- No obvious public-reference blocker found."])
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Public impact preview · {work_id}")
        dialog.resize(760, 560)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(); text.setReadOnly(True); text.setPlainText("\n".join(lines))
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject); buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def navigate_work(self, direction: int) -> None:
        if self.tabs.currentWidget() is not self.works_tab:
            return
        if self._using_work_model_view():
            ids = self._works_model.row_ids()
            if not ids:
                return
            try:
                current_index = ids.index(str(self._current_work_id or ""))
            except ValueError:
                current_index = 0
            target_index = max(0, min(len(ids) - 1, current_index + direction))
            target_id = ids[target_index]
            if target_id != self._current_work_id and not self.ensure_work_editor_safe():
                self._restore_work_selection()
                return
            self.select_work(target_id)
            return
        count = self.work_tree.topLevelItemCount()
        if count == 0:
            return
        current_item = self.work_tree.currentItem()
        current_index = self.work_tree.indexOfTopLevelItem(current_item) if current_item else 0
        target_index = max(0, min(count - 1, current_index + direction))
        item = self.work_tree.topLevelItem(target_index)
        if item is not None:
            target_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            if target_id != self._current_work_id and not self.ensure_work_editor_safe():
                self._restore_work_selection()
                return
            self.select_work(target_id)

    def navigate_series(self, direction: int) -> None:
        if self.tabs.currentWidget() is not self.series_tab:
            return
        count = self.series_list.count()
        if count == 0:
            return
        current_index = self.series_list.currentRow()
        if current_index < 0:
            current_index = 0
        target_index = max(0, min(count - 1, current_index + direction))
        item = self.series_list.item(target_index)
        if item is None:
            return
        target = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if target != self._current_series_slug and not self.ensure_series_editor_safe():
            self._restore_series_selection()
            return
        self.series_list.setCurrentRow(target_index)
        self.select_series(target)

    def navigate_page(self, direction: int) -> None:
        if self.tabs.currentWidget() is not self.pages_tab:
            return
        count = self.pages_list.count()
        if count == 0:
            return
        current_index = self.pages_list.currentRow()
        if current_index < 0:
            current_index = 0
        target_index = max(0, min(count - 1, current_index + direction))
        item = self.pages_list.item(target_index)
        if item is None:
            return
        target = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if target != self._current_page_key and not self.ensure_page_editor_safe():
            self._restore_page_selection()
            return
        self.pages_list.setCurrentRow(target_index)
        self.select_page(target)

    # ---------- series ----------
    def build_series_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setObjectName("series-main-splitter")
        self.series_main_splitter = split
        layout.addWidget(split, 1)

        # Left rail: curated series cards + primary actions only.
        left = QFrame()
        left.setObjectName("workspaceCard")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)
        left_layout.addWidget(QLabel("Series library"))
        self.series_list = QListWidget()
        self.series_list.setObjectName("seriesCardList")
        self.series_list.setSpacing(8)
        self.series_list.setIconSize(QSize(52, 52))
        self.series_list.setUniformItemSizes(False)
        self.series_list.itemSelectionChanged.connect(self.on_series_selection_changed)
        left_layout.addWidget(self.series_list, 1)
        series_actions = QHBoxLayout()
        new_series_btn = QPushButton("New…")
        new_series_btn.clicked.connect(self.open_new_series_dialog)
        delete_series_btn = QPushButton("Delete…")
        delete_series_btn.setToolTip("Delete the selected empty series YAML. Series with works are blocked until their works are moved or removed from the sequence.")
        delete_series_btn.clicked.connect(self.delete_current_series)
        curation_btn = QPushButton("Curation…")
        curation_btn.clicked.connect(self.open_series_curation_workspace)
        story_btn = QPushButton("Health…")
        story_btn.clicked.connect(self.open_series_story_health_dialog)
        self.series_inspector_toggle_btn = QPushButton("Inspector")
        self.series_inspector_toggle_btn.setToolTip("Open the contextual series inspector without leaving the Series workspace.")
        self.series_inspector_toggle_btn.clicked.connect(self.toggle_context_inspector)
        for btn in (new_series_btn, delete_series_btn, curation_btn, story_btn, self.series_inspector_toggle_btn):
            series_actions.addWidget(btn)
        left_layout.addLayout(series_actions)
        split.addWidget(left)

        # Right workspace: separate identity/story from sequencing so dense fields cannot collapse.
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 0, 0, 0)
        right_layout.setSpacing(8)
        series_header = QHBoxLayout()
        self.series_breadcrumb = QLabel("Series  ›  No series selected")
        self.series_breadcrumb.setObjectName("breadcrumb")
        self.series_autosave_status = QLabel("")
        self.series_autosave_status.setObjectName("autosaveStatus")
        series_header.addWidget(self.series_breadcrumb, 1)
        series_header.addWidget(self.series_autosave_status)
        right_layout.addLayout(series_header)
        self.series_health_strip = QLabel("Select a series to edit identity, story, cover, and sequence.")
        self.series_health_strip.setObjectName("missionStatus")
        self.series_health_strip.setWordWrap(True)
        right_layout.addWidget(self.series_health_strip)
        series_integrity_row = QHBoxLayout()
        self.series_broken_refs_badge = StatusBadge("References OK", "ok")
        self.series_broken_refs_badge.setToolTip("Series reference integrity: sequence and cover should point to existing work YAML files.")
        self.series_repair_refs_btn = QPushButton("Repair references")
        self.series_repair_refs_btn.setToolTip("Remove missing work IDs from this series sequence, or mark the series incomplete if you choose not to publish it yet.")
        self.series_repair_refs_btn.clicked.connect(self.repair_current_series_references)
        self.series_repair_refs_btn.setVisible(False)
        series_integrity_row.addWidget(self.series_broken_refs_badge)
        series_integrity_row.addWidget(self.series_repair_refs_btn)
        series_integrity_row.addStretch(1)
        right_layout.addLayout(series_integrity_row)

        # Phase 16: the Series editor is a single scrollable workspace.
        # Overview remains open; dense sequence/cover controls are collapsed.
        self.series_editor_scroll = QScrollArea()
        self.series_editor_scroll.setObjectName("seriesEditorScroll")
        self.series_editor_scroll.setWidgetResizable(True)
        self.series_editor_host = QWidget()
        self.series_editor_layout = QVBoxLayout(self.series_editor_host)
        self.series_editor_layout.setContentsMargins(0, 0, 0, 0)
        self.series_editor_layout.setSpacing(12)
        self.series_editor_scroll.setWidget(self.series_editor_host)
        right_layout.addWidget(self.series_editor_scroll, 1)

        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        overview_layout.setContentsMargins(12, 12, 12, 12)
        overview_layout.setSpacing(10)
        overview_card = QFrame()
        overview_card.setObjectName("workspaceCard")
        overview_card_layout = QVBoxLayout(overview_card)
        overview_card_layout.setContentsMargins(14, 14, 14, 14)
        overview_card_layout.setSpacing(10)
        overview_card_layout.addWidget(QLabel("Identity and public story"))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)
        self.series_slug_edit = QLineEdit(); form.addRow("Slug", self.series_slug_edit)
        self.series_title_edit = QLineEdit(); form.addRow("Title", self.series_title_edit)
        self.series_years_edit = QLineEdit(); form.addRow("Years", self.series_years_edit)
        self.series_mood_edit = QLineEdit(); form.addRow("Mood", self.series_mood_edit)
        self.series_order_spin = QSpinBox(); self.series_order_spin.setRange(0, 9999); form.addRow("Order", self.series_order_spin)
        self.series_visibility_combo = QComboBox(); self.series_visibility_combo.addItems(["public", "private"]); form.addRow("Visibility", self.series_visibility_combo)
        self.series_project_type_combo = QComboBox(); self.series_project_type_combo.addItems(["fine-art", "performance", "editorial", "commission", "archive"]); form.addRow("Project type", self.series_project_type_combo)
        cover_row = QHBoxLayout()
        self.series_cover_combo = QComboBox(); self.series_cover_combo.currentTextChanged.connect(self.update_series_preview)
        cover_row.addWidget(self.series_cover_combo, 1)
        refresh_cover_btn = QPushButton("Refresh")
        refresh_cover_btn.clicked.connect(self.refresh_series_cover_choices)
        cover_row.addWidget(refresh_cover_btn)
        cover_wrap = QWidget(); cover_wrap.setLayout(cover_row)
        form.addRow("Cover", cover_wrap)
        toggles = QHBoxLayout()
        self.series_review_check = QCheckBox("Review")
        self.series_favorites_check = QCheckBox("Favorites")
        self.series_inquiry_check = QCheckBox("Inquiry basket")
        for check in (self.series_review_check, self.series_favorites_check, self.series_inquiry_check):
            toggles.addWidget(check)
        toggles.addStretch(1)
        toggle_wrap = QWidget(); toggle_wrap.setLayout(toggles)
        form.addRow("Flags", toggle_wrap)
        overview_card_layout.addLayout(form)
        overview_layout.addWidget(overview_card)

        story_card = QFrame()
        story_card.setObjectName("workspaceCard")
        story_layout = QVBoxLayout(story_card)
        story_layout.setContentsMargins(14, 14, 14, 14)
        story_layout.setSpacing(8)
        story_layout.addWidget(QLabel("Description"))
        self.series_desc_edit = QPlainTextEdit()
        self.series_desc_edit.setMinimumHeight(120)
        self.series_desc_edit.setMaximumHeight(190)
        story_layout.addWidget(self.series_desc_edit)
        story_layout.addWidget(QLabel("Private curation note · not published"))
        self.series_private_note_edit = QPlainTextEdit()
        self.series_private_note_edit.setMinimumHeight(96)
        self.series_private_note_edit.setMaximumHeight(160)
        story_layout.addWidget(self.series_private_note_edit)
        save_series_note_btn = QPushButton("Save private note")
        save_series_note_btn.clicked.connect(self.save_current_series_private_note)
        story_layout.addWidget(save_series_note_btn)
        overview_layout.addWidget(story_card, 1)
        self.series_overview_section = CollapsibleSection("Overview", "title, slug, description and cover", expanded=True)
        self.series_overview_section.add_widget(overview_tab)
        self.series_editor_layout.addWidget(self.series_overview_section)

        sequence_tab = QWidget()
        sequence_layout = QVBoxLayout(sequence_tab)
        sequence_layout.setContentsMargins(12, 12, 12, 12)
        sequence_layout.setSpacing(10)
        sequence_split = QSplitter(Qt.Orientation.Horizontal)
        sequence_split.setObjectName("series-sequence-splitter")
        seq_left = QFrame(); seq_left.setObjectName("workspaceCard")
        seq_left_layout = QVBoxLayout(seq_left)
        seq_left_layout.setContentsMargins(14, 14, 14, 14)
        seq_left_layout.setSpacing(8)
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Sequence board"), 1)
        title_row.addWidget(QLabel("Drag to reorder · arrows remain available"))
        seq_left_layout.addLayout(title_row)
        self.series_sequence_list = ReorderListWidget()
        self.series_sequence_list.setObjectName("seriesSequenceBoard")
        self.series_sequence_list.setIconSize(QSize(72, 72))
        self.series_sequence_list.setSpacing(6)
        self.series_sequence_list.setToolTip("Drag works to reorder the series sequence. Use ↑/↓ as the accessible fallback.")
        self.series_sequence_list.orderChanged.connect(self.on_series_sequence_reordered)
        self.series_sequence_list.itemDoubleClicked.connect(lambda _item: self.open_selected_series_sequence_work())
        seq_left_layout.addWidget(self.series_sequence_list, 1)
        self.series_sequence_summary = QLabel("No sequence loaded.")
        self.series_sequence_summary.setObjectName("quietHint")
        self.series_sequence_summary.setWordWrap(True)
        seq_left_layout.addWidget(self.series_sequence_summary)
        sequence_row = QHBoxLayout()
        self.series_sequence_picker = QComboBox()
        add_sequence_btn = QPushButton("Add")
        add_sequence_btn.clicked.connect(self.add_series_sequence_item)
        remove_sequence_btn = QPushButton("Remove")
        remove_sequence_btn.clicked.connect(self.remove_series_sequence_item)
        move_sequence_up = QPushButton("↑")
        move_sequence_up.clicked.connect(lambda: self.move_series_sequence_item(-1))
        move_sequence_down = QPushButton("↓")
        move_sequence_down.clicked.connect(lambda: self.move_series_sequence_item(1))
        open_sequence_work = QPushButton("Open")
        open_sequence_work.clicked.connect(self.open_selected_series_sequence_work)
        preview_move_btn = QPushButton("Preview move")
        preview_move_btn.clicked.connect(self.preview_selected_sequence_move)
        sequence_row.addWidget(self.series_sequence_picker, 1)
        for widget in (add_sequence_btn, remove_sequence_btn, move_sequence_up, move_sequence_down, open_sequence_work, preview_move_btn):
            sequence_row.addWidget(widget)
        seq_left_layout.addLayout(sequence_row)
        sequence_split.addWidget(seq_left)

        seq_right = QFrame(); seq_right.setObjectName("workspaceCard")
        seq_right_layout = QVBoxLayout(seq_right)
        seq_right_layout.setContentsMargins(14, 14, 14, 14)
        seq_right_layout.setSpacing(8)
        seq_right_layout.addWidget(QLabel("Cover preview"))
        self.series_preview_label = QLabel("No cover preview")
        self.series_preview_label.setMinimumHeight(280)
        self.series_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.series_preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        seq_right_layout.addWidget(self.series_preview_label, 1)
        sequence_split.addWidget(seq_right)
        sequence_split.setSizes([820, 420])
        sequence_layout.addWidget(sequence_split, 1)
        self.series_sequence_section = CollapsibleSection("Sequence & cover", "drag order and cover preview", expanded=False)
        self.series_sequence_section.add_widget(sequence_tab)
        self.series_editor_layout.addWidget(self.series_sequence_section, 1)

        self.series_save_btn = QPushButton("Save series")
        save_series_btn = self.series_save_btn
        save_series_btn.clicked.connect(self.save_current_series)
        preview_series_payload_btn = QPushButton("Preview payload")
        preview_series_payload_btn.clicked.connect(self.show_current_series_payload_preview)
        save_series_template_btn = QPushButton("Save template")
        save_series_template_btn.clicked.connect(self.save_current_series_template)
        apply_series_template_btn = QPushButton("Use template…")
        apply_series_template_btn.clicked.connect(self.apply_series_template_to_current)
        series_action_row = QHBoxLayout()
        series_action_row.addWidget(save_series_btn)
        series_action_row.addWidget(preview_series_payload_btn)
        series_action_row.addWidget(save_series_template_btn)
        series_action_row.addWidget(apply_series_template_btn)
        series_action_row.addStretch(1)
        right_layout.addLayout(series_action_row)

        split.addWidget(right)
        split.setChildrenCollapsible(False)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 1180])
        for widget in [self.series_slug_edit, self.series_title_edit, self.series_years_edit, self.series_mood_edit]:
            widget.textChanged.connect(lambda _value=None: self.schedule_editor_autosave("series"))
            widget.textChanged.connect(lambda _value=None: self._validate_series_form())
        self.series_order_spin.valueChanged.connect(lambda _value=None: self.schedule_editor_autosave("series"))
        self.series_visibility_combo.currentTextChanged.connect(lambda _value=None: self.schedule_editor_autosave("series"))
        self.series_project_type_combo.currentTextChanged.connect(lambda _value=None: self.schedule_editor_autosave("series"))
        self.series_cover_combo.currentTextChanged.connect(lambda _value=None: self.schedule_editor_autosave("series"))
        self.series_desc_edit.textChanged.connect(lambda: self.schedule_editor_autosave("series"))
        for widget in [self.series_review_check, self.series_favorites_check, self.series_inquiry_check]:
            widget.toggled.connect(lambda _state=None: self.schedule_editor_autosave("series"))
        return tab

    def open_series_curation_workspace(self) -> None:
        SeriesCurationDialog(self, self._current_series_slug).exec()

    def open_series_story_health_dialog(self) -> None:
        try:
            rows = series_story_rows()
        except Exception as exc:
            QMessageBox.critical(self, "Story health failed", str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Series story health")
        dialog.resize(900, 560)
        layout = QVBoxLayout(dialog)
        tree = QTreeWidget(); tree.setHeaderLabels(["Score", "Status", "Series", "Works", "Weak", "Missing assets", "Orientation mix"]); tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for row in rows:
            item = QTreeWidgetItem([str(row.get("score") or 0), str(row.get("status") or ""), str(row.get("slug") or ""), str(row.get("works") or 0), str(row.get("weak_items") or 0), str(row.get("missing_assets") or 0), str(row.get("orientation_mix") or "")])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            color = self._severity_color("ok" if row.get("status") == "ready" else "warning" if row.get("status") == "review" else "error")
            for col in range(7):
                item.setForeground(col, color)
            tree.addTopLevelItem(item)
        layout.addWidget(tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject); buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        tree.itemDoubleClicked.connect(lambda item, _col: (self.tabs.setCurrentWidget(self.series_tab), self.select_series(str((item.data(0, Qt.ItemDataRole.UserRole) or {}).get("slug") or "")), dialog.accept()))
        dialog.exec()

    def delete_current_series(self) -> None:
        selected = self.series_list.selectedItems() if hasattr(self, "series_list") else []
        slug = str((selected[0].data(Qt.ItemDataRole.UserRole) if selected else None) or self._current_series_slug or "").strip()
        if not slug:
            self._info_nonblocking("No series selected", "Select a series in the Series library first.", target_scope="series")
            return
        if not self.ensure_series_editor_safe():
            return
        try:
            preview = series_delete_preview(slug)
        except Exception as exc:
            QMessageBox.critical(self, "Delete series preview failed", str(exc))
            return

        work_ids = [str(item).strip() for item in (preview.get("work_ids") or []) if str(item).strip()]
        if work_ids:
            shown = "\n".join(f"- {item}" for item in work_ids[:12])
            if len(work_ids) > 12:
                shown += f"\n- … and {len(work_ids) - 12} more"
            QMessageBox.warning(
                self,
                "Delete blocked",
                "This series still owns or references works, so deleting it would break content integrity.\n\n"
                f"Series: {preview.get('title') or slug}\n"
                f"Works:\n{shown}\n\n"
                "Move those works to another series, or remove them from this sequence, then try Delete again.",
            )
            return

        refs = []
        refs.extend(str(item) for item in (preview.get("homepage_refs") or []))
        refs.extend(str(item) for item in (preview.get("collection_refs") or []))
        ref_note = "\n\nReferences that will be pruned:\n" + "\n".join(f"- {item}" for item in refs) if refs else ""
        confirm = QMessageBox.warning(
            self,
            "Delete empty series?",
            f"Delete the empty series '{preview.get('title') or slug}'?\n\n"
            f"File: {preview.get('path') or f'content/series/{slug}.yaml'}\n"
            "Works and image files will not be deleted. This removes the series YAML and prunes series-list references."
            f"{ref_note}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            result = delete_series_record(slug)
        except Exception as exc:
            QMessageBox.critical(self, "Delete series failed", str(exc))
            return

        self._current_series_slug = ""
        self._loaded_series_snapshot = None
        self.populate_series_form({}, reset_snapshot=True)
        if hasattr(self, "series_breadcrumb"):
            self.series_breadcrumb.setText("Series  ›  No series selected")
        if hasattr(self, "series_health_strip"):
            self.series_health_strip.setText("Select a series to edit identity, story, cover, and sequence.")
        self.push_notification("success", "Deleted series", slug, target_scope="series")
        self.show_operation_report("Delete series transaction report", result, force=True)
        self.refresh_all_context(activate="series", force=True, scope={"series", "relationships", "dashboard", "validation", "studio", "publish"})
        self.status_message(f"Deleted series: {slug}")

    def save_current_series_private_note(self) -> None:
        if not self._current_series_slug:
            self._info_nonblocking("No series selected", "Select a series first.", target_scope="series")
            return
        try:
            save_private_note("series", self._current_series_slug, self.series_private_note_edit.toPlainText())
        except Exception as exc:
            QMessageBox.critical(self, "Private note failed", str(exc))
            return
        self.push_notification("success", "Saved private series note", self._current_series_slug, target_scope="series", target_id=self._current_series_slug)
        self.status_message("Saved private series note")

    def preview_selected_sequence_move(self) -> None:
        if not self._current_series_slug:
            self._info_nonblocking("No series selected", "Select a series first.", target_scope="series")
            return
        item = self.series_sequence_list.currentItem()
        if item is None:
            QMessageBox.information(self, "No work selected", "Select a work in the sequence first.")
            return
        work_id = item.text().strip()
        target, ok = QInputDialog.getItem(self, "Preview move", "Target series", available_series_slugs(), 0, False)
        if not ok or not target:
            return
        try:
            report = preview_work_move(work_id, target)
        except Exception as exc:
            QMessageBox.critical(self, "Move preview failed", str(exc))
            return
        self.show_operation_report("Work move preview", report, force=True)

    def refresh_series_list(self) -> None:
        current = self._current_series_slug
        self.series_list.clear()
        for payload in load_series_entries():
            slug = str(payload.get("slug") or "")
            work_ids = [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]
            visibility = str(payload.get("visibility") or "public")
            project_type = str(payload.get("project_type") or "fine-art")
            cover = str(payload.get("cover_work_id") or "")
            missing_refs = self._current_series_missing_refs(payload)
            readiness = "broken refs" if missing_refs else "ready" if work_ids and cover else "needs setup"
            broken_suffix = f" · {len(missing_refs)} broken" if missing_refs else ""
            item = QListWidgetItem(f"{payload.get('title') or slug}\n{slug} · {project_type} · {len(work_ids)} works · {visibility} · {readiness}{broken_suffix}")
            if missing_refs:
                item.setForeground(self._severity_color("error"))
                item.setToolTip("Missing work references: " + ", ".join(missing_refs[:10]))
            item.setData(Qt.ItemDataRole.UserRole, slug)
            if cover:
                cover_payload = load_work_payload(cover) or {"id": cover, "series": slug}
                icon = self.work_tree_icon(cover_payload)
                if not icon.isNull():
                    item.setIcon(icon)
            self.series_list.addItem(item)
        if current:
            self.select_series(current, silent=True)

    def on_series_selection_changed(self) -> None:
        items = self.series_list.selectedItems()
        if not items:
            return
        target = str(items[0].data(Qt.ItemDataRole.UserRole) or "")
        if target == self._current_series_slug:
            return
        if not self.ensure_series_editor_safe():
            self._restore_series_selection()
            return
        self.select_series(target)

    def select_series(self, series_slug: str, *, silent: bool = False, restore_draft: bool = False) -> None:
        if not series_slug:
            return
        payload = load_series_payload(series_slug)
        if not payload:
            return
        self._current_series_slug = series_slug
        if hasattr(self, "tab_controllers") and "series" in self.tab_controllers:
            self.tab_controllers["series"].mark_current(series_slug, payload)
        self._suspend_series_form = True
        try:
            with signals_blocked(self):
                self.series_slug_edit.setText(str(payload.get("slug") or ""))
                self.series_title_edit.setText(str(payload.get("title") or ""))
                self.series_years_edit.setText(str(payload.get("years") or ""))
                self.series_mood_edit.setText(str(payload.get("mood") or ""))
                self.series_order_spin.setValue(int(payload.get("order") or 0))
                self.series_visibility_combo.setCurrentText(str(payload.get("visibility") or "public"))
                self.series_project_type_combo.setCurrentText(str(payload.get("project_type") or "fine-art"))
                self.series_review_check.setChecked(bool(payload.get("review_mode")))
                self.series_favorites_check.setChecked(bool(payload.get("allow_favorites", True)))
                self.series_inquiry_check.setChecked(bool(payload.get("allow_inquiry_basket", True)))
                self.series_desc_edit.setPlainText(str(payload.get("description") or ""))
                if hasattr(self, "series_private_note_edit"):
                    self.series_private_note_edit.setPlainText(load_private_note("series", series_slug))
                sequence = [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]
                self.series_sequence_list.clear()
                for index, work_id in enumerate(sequence, start=1):
                    work_payload = load_work_payload(work_id) or {"id": work_id, "series": series_slug}
                    title = str(work_payload.get("title") or work_id)
                    item = QListWidgetItem(f"{index:02d} · {title}\n{work_id}")
                    item.setData(Qt.ItemDataRole.UserRole, work_id)
                    icon = self.work_tree_icon(work_payload)
                    if not icon.isNull():
                        item.setIcon(icon)
                    self.series_sequence_list.addItem(item)
        finally:
            self._suspend_series_form = False
        self.refresh_series_sequence_choices()
        self.refresh_series_cover_choices(series_slug)
        self.series_cover_combo.setCurrentText(str(payload.get("cover_work_id") or ""))
        self.update_series_preview()
        self.update_series_health_strip()
        self._loaded_series_snapshot = self.current_series_payload_from_form()
        self._reset_autosave_state("series")
        if hasattr(self, "series_breadcrumb"):
            title = str(payload.get("title") or series_slug)
            count = len([str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()])
            self.series_breadcrumb.setText(f"Series  ›  {title}  ·  {count} works")
        self.maybe_restore_editor_draft("series", series_slug, interactive=restore_draft)
        self._update_autosave_labels()
        if not silent:
            self.status_message(f"Loaded series: {series_slug}")

    def populate_series_form(self, payload: dict[str, Any], *, reset_snapshot: bool = True) -> None:
        """Populate the Series editor from an in-memory payload without changing selection."""
        payload = dict(payload or {})
        self._suspend_series_form = True
        sequence = [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]
        try:
            with signals_blocked(self):
                self.series_slug_edit.setText(str(payload.get("slug") or ""))
                self.series_title_edit.setText(str(payload.get("title") or ""))
                self.series_years_edit.setText(str(payload.get("years") or ""))
                self.series_mood_edit.setText(str(payload.get("mood") or ""))
                self.series_order_spin.setValue(int(payload.get("order") or 0))
                self.series_visibility_combo.setCurrentText(str(payload.get("visibility") or "public"))
                self.series_project_type_combo.setCurrentText(str(payload.get("project_type") or "fine-art"))
                self.series_review_check.setChecked(bool(payload.get("review_mode")))
                self.series_favorites_check.setChecked(bool(payload.get("allow_favorites", True)))
                self.series_inquiry_check.setChecked(bool(payload.get("allow_inquiry_basket", True)))
                self.series_desc_edit.setPlainText(str(payload.get("description") or ""))
                self.series_sequence_list.clear()
                for index, work_id in enumerate(sequence, start=1):
                    work_payload = load_work_payload(work_id) or {"id": work_id, "series": payload.get("slug") or self._current_series_slug or ""}
                    title = str(work_payload.get("title") or work_id)
                    item = QListWidgetItem(f"{index:02d} · {title}\n{work_id}")
                    item.setData(Qt.ItemDataRole.UserRole, work_id)
                    icon = self.work_tree_icon(work_payload)
                    if not icon.isNull():
                        item.setIcon(icon)
                    self.series_sequence_list.addItem(item)
        finally:
            self._suspend_series_form = False
        self.refresh_series_sequence_choices()
        self.refresh_series_cover_choices(str(payload.get("slug") or self._current_series_slug or ""))
        self.series_cover_combo.setCurrentText(str(payload.get("cover_work_id") or ""))
        self.update_series_preview()
        self.update_series_health_strip()
        self._validate_series_form()
        if reset_snapshot:
            self._loaded_series_snapshot = self.current_series_payload_from_form()
            self._reset_autosave_state("series")
        self._update_autosave_labels()

    def _series_sequence_health(self, sequence: list[str] | None = None, *, cover_work_id: str | None = None, visibility: str | None = None) -> tuple[list[str], str]:
        sequence = list(sequence if sequence is not None else self.list_widget_values(self.series_sequence_list))
        known = {str(item.get("id") or "") for item in load_work_entries()}
        duplicate_ids = sorted({work_id for work_id in sequence if sequence.count(work_id) > 1})
        missing_ids = [work_id for work_id in sequence if work_id and work_id not in known]
        cover = str(cover_work_id if cover_work_id is not None else self.series_cover_combo.currentText()).strip()
        problems: list[str] = []
        if duplicate_ids:
            problems.append(f"duplicate: {', '.join(duplicate_ids[:4])}")
        if missing_ids:
            problems.append(f"missing: {', '.join(missing_ids[:4])}")
        if cover and cover not in sequence:
            problems.append("cover not in sequence")
        if not cover:
            problems.append("missing cover")
        visibility_text = str(visibility if visibility is not None else self.series_visibility_combo.currentText() or "public")
        state = "Blocked" if missing_ids else "Needs review" if problems else "Healthy"
        summary = f"{state} · {len(sequence)} work(s) · {visibility_text} · " + (" · ".join(problems) if problems else "cover and sequence are coherent")
        return problems, summary

    def update_series_health_strip(self) -> None:
        if not hasattr(self, "series_health_strip"):
            return
        _problems, summary = self._series_sequence_health()
        self.series_health_strip.setText(summary + " · drag sequence to refine rhythm, or use ↑/↓ as fallback.")
        if hasattr(self, "series_sequence_summary"):
            self.series_sequence_summary.setText(summary)
        self._update_series_reference_badge()

    def _current_series_missing_refs(self, payload: dict[str, Any] | None = None) -> list[str]:
        payload = dict(payload or {})
        if not payload and self._current_series_slug:
            try:
                payload = load_series_payload(self._current_series_slug)
            except Exception:
                payload = {}
        missing = payload.get("_missing_work_ids") if isinstance(payload, dict) else []
        if isinstance(missing, list):
            return [str(item).strip() for item in missing if str(item).strip()]
        known = {str(item.get("id") or "").strip() for item in load_work_entries() if str(item.get("id") or "").strip()}
        sequence = [str(item).strip() for item in (payload.get("work_ids") or self.list_widget_values(self.series_sequence_list)) if str(item).strip()] if isinstance(payload, dict) else self.list_widget_values(self.series_sequence_list)
        cover = str((payload.get("cover_work_id") if isinstance(payload, dict) else self.series_cover_combo.currentText()) or "").strip()
        missing_refs = [work_id for work_id in sequence if work_id and work_id not in known]
        if cover and cover not in known and cover not in missing_refs:
            missing_refs.append(cover)
        return missing_refs

    def _update_series_reference_badge(self, payload: dict[str, Any] | None = None) -> None:
        if not hasattr(self, "series_broken_refs_badge"):
            return
        missing = self._current_series_missing_refs(payload)
        if missing:
            self.series_broken_refs_badge.set_status("error", f"Broken refs · {len(missing)}")
            self.series_broken_refs_badge.setToolTip("Missing work references: " + ", ".join(missing[:10]))
            if hasattr(self, "series_repair_refs_btn"):
                self.series_repair_refs_btn.setVisible(True)
        else:
            self.series_broken_refs_badge.set_status("ok", "References OK")
            self.series_broken_refs_badge.setToolTip("Every sequence and cover reference points to an existing work YAML file.")
            if hasattr(self, "series_repair_refs_btn"):
                self.series_repair_refs_btn.setVisible(False)

    def repair_current_series_references(self) -> None:
        if not self._current_series_slug:
            self._info_nonblocking("No series selected", "Select a series first.", target_scope="series")
            return
        missing = self._current_series_missing_refs()
        if not missing:
            self.push_notification("success", "Series references already clean", self._current_series_slug, target_scope="series", target_id=self._current_series_slug)
            return
        message = (
            f"{self._current_series_slug} references missing work YAML files:\n"
            + "\n".join(f"- {item}" for item in missing[:12])
            + "\n\nRemove the dead references from the series sequence, or mark the series incomplete/private for manual curation?"
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Repair series references")
        box.setText(message)
        remove_btn = box.addButton("Remove dead references", QMessageBox.ButtonRole.AcceptRole)
        incomplete_btn = box.addButton("Mark incomplete", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (remove_btn, incomplete_btn):
            return
        try:
            result = remove_missing_work_references_from_series(self._current_series_slug, mark_incomplete=(clicked is incomplete_btn))
        except Exception as exc:
            QMessageBox.critical(self, "Series repair failed", str(exc))
            return
        self.select_series(self._current_series_slug, silent=True)
        self.refresh_series_list()
        self.push_notification("success", "Series references repaired", f"Removed {len(result.get('removed') or [])} missing reference(s).", target_scope="series", target_id=self._current_series_slug)

    def refresh_series_cover_choices(self, series_slug: str | None = None) -> None:
        sequence = self.list_widget_values(self.series_sequence_list)
        if not sequence and series_slug:
            sequence = load_series_sequence(series_slug)
        with signals_blocked(self.series_cover_combo):
            current = self.series_cover_combo.currentText()
            self.series_cover_combo.clear(); self.series_cover_combo.addItems(sequence)
            if current in sequence:
                self.series_cover_combo.setCurrentText(current)

    def refresh_series_sequence_choices(self) -> None:
        current = self.series_sequence_picker.currentText()
        work_choices = [str(item.get("id") or "") for item in load_work_entries() if str(item.get("id") or "")]
        with signals_blocked(self.series_sequence_picker):
            self.series_sequence_picker.clear()
            self.series_sequence_picker.addItems(work_choices)
            if current in work_choices:
                self.series_sequence_picker.setCurrentText(current)

    def add_series_sequence_item(self) -> None:
        work_id = self.series_sequence_picker.currentText().strip()
        if not work_id:
            return
        existing = self.list_widget_values(self.series_sequence_list)
        if work_id in existing:
            self.series_sequence_list.setCurrentRow(existing.index(work_id))
            return
        work_payload = load_work_payload(work_id) or {"id": work_id, "series": self.series_slug_edit.text().strip() or self._current_series_slug or ""}
        title = str(work_payload.get("title") or work_id)
        item = QListWidgetItem(f"{self.series_sequence_list.count() + 1:02d} · {title}\n{work_id}")
        item.setData(Qt.ItemDataRole.UserRole, work_id)
        icon = self.work_tree_icon(work_payload)
        if not icon.isNull():
            item.setIcon(icon)
        self.series_sequence_list.addItem(item)
        self.series_sequence_list.setCurrentRow(self.series_sequence_list.count() - 1)
        self.refresh_series_cover_choices(self.series_slug_edit.text().strip() or self._current_series_slug)
        self.update_series_health_strip()
        self.schedule_editor_autosave("series")

    def remove_series_sequence_item(self) -> None:
        row = self.series_sequence_list.currentRow()
        if row < 0:
            return
        removed = self.series_sequence_list.takeItem(row)
        del removed
        self.refresh_series_cover_choices(self.series_slug_edit.text().strip() or self._current_series_slug)
        self.update_series_health_strip()
        self.schedule_editor_autosave("series")

    def on_series_sequence_reordered(self) -> None:
        if getattr(self, "_suspend_series_form", False):
            return
        self.refresh_series_cover_choices(self.series_slug_edit.text().strip() or self._current_series_slug)
        self._validate_series_form()
        self.update_series_health_strip()
        self.schedule_editor_autosave("series")
        count = self.series_sequence_list.count() if hasattr(self, "series_sequence_list") else 0
        self.status_message(f"Series sequence reordered · {count} work(s) · Save series to persist")

    def move_series_sequence_item(self, direction: int) -> None:
        row = self.series_sequence_list.currentRow()
        if row < 0:
            return
        target = max(0, min(self.series_sequence_list.count() - 1, row + direction))
        if target == row:
            return
        item = self.series_sequence_list.takeItem(row)
        self.series_sequence_list.insertItem(target, item)
        self.series_sequence_list.setCurrentRow(target)
        self.refresh_series_cover_choices(self.series_slug_edit.text().strip() or self._current_series_slug)
        self.update_series_health_strip()
        self.schedule_editor_autosave("series")

    def open_selected_series_sequence_work(self) -> None:
        item = self.series_sequence_list.currentItem()
        if item is None:
            return
        work_id = str(item.data(Qt.ItemDataRole.UserRole) or item.text()).strip()
        if "\n" in work_id:
            work_id = work_id.split("\n")[-1].strip()
        if not work_id:
            return
        self.tabs.setCurrentWidget(self.works_tab)
        self.select_work(work_id)

    def update_series_preview(self) -> None:
        work_id = self.series_cover_combo.currentText().strip()
        series_slug = self.series_slug_edit.text().strip() or self._current_series_slug or ""
        if not work_id or not series_slug:
            self.series_preview_label.setPixmap(QPixmap())
            self.series_preview_label.setText("No cover preview")
            return
        from qt_backend import source_path_for_work, load_pipeline
        path = source_path_for_work(series_slug, work_id, load_pipeline())
        if path and Path(path).exists():
            pix = QPixmap(str(path))
            if not pix.isNull():
                self.series_preview_label.setPixmap(pix.scaled(QSize(520, 260), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                return
        self.series_preview_label.setPixmap(QPixmap())
        self.series_preview_label.setText("No cover preview")

    def current_series_payload_from_form(self) -> dict[str, Any]:
        return {
            "slug": self.series_slug_edit.text().strip(),
            "title": self.series_title_edit.text().strip(),
            "years": self.series_years_edit.text().strip(),
            "mood": self.series_mood_edit.text().strip(),
            "description": self.series_desc_edit.toPlainText().strip(),
            "cover_work_id": self.series_cover_combo.currentText().strip(),
            "work_ids": self.list_widget_values(self.series_sequence_list),
            "order": self.series_order_spin.value(),
            "visibility": self.series_visibility_combo.currentText(),
            "project_type": self.series_project_type_combo.currentText(),
            "review_mode": self.series_review_check.isChecked(),
            "allow_favorites": self.series_favorites_check.isChecked(),
            "allow_inquiry_basket": self.series_inquiry_check.isChecked(),
        }

    def _validate_series_form(self) -> bool:
        if not hasattr(self, "series_save_btn") or getattr(self, "_suspend_series_form", False):
            return True
        payload = self.current_series_payload_from_form()
        rows = validate_editor_payload("series", payload, original_key=self._current_series_slug)
        field_widgets = {
            "slug": self.series_slug_edit,
            "title": self.series_title_edit,
            "cover_work_id": self.series_cover_combo,
            "work_ids": self.series_sequence_list,
        }
        for widget in field_widgets.values():
            self._set_field_validation_state(widget)
        has_errors = False
        messages: list[str] = []
        sequence_problems, sequence_summary = self._series_sequence_health(payload.get("work_ids") or [], cover_work_id=payload.get("cover_work_id"), visibility=payload.get("visibility"))
        if sequence_problems:
            has_errors = has_errors or any(problem.startswith("missing") for problem in sequence_problems)
            messages.append("SEQUENCE · " + sequence_summary)
        if hasattr(self, "series_health_strip"):
            self.series_health_strip.setText(sequence_summary + " · drag sequence to refine rhythm, or use ↑/↓ as fallback.")
        if hasattr(self, "series_sequence_summary"):
            self.series_sequence_summary.setText(sequence_summary)
        for row in rows:
            field = str(row.get("field") or "")
            severity = str(row.get("severity") or "warning")
            message = str(row.get("message") or "")
            if severity == "error":
                has_errors = True
            messages.append(f"{severity.upper()} · {field}: {message}")
            widget = field_widgets.get(field)
            if widget is not None:
                self._set_field_validation_state(widget, severity, message)
        if hasattr(self, "series_preview_label"):
            self.series_preview_label.setToolTip("\n".join(messages) if messages else "Series fields are valid.")
        self.series_save_btn.setEnabled(not has_errors)
        return not has_errors

    def show_current_series_payload_preview(self) -> None:
        self.show_payload_preview("Current series payload preview", self.current_series_payload_from_form())

    def refresh_reference_controls(self, changed_kind: str = "all") -> None:
        """Refresh controls that depend on live work/series/page IDs after saves or renames."""
        if hasattr(self, "work_series_combo"):
            self.refresh_work_series_combos()
        if hasattr(self, "series_cover_combo"):
            self.refresh_series_cover_choices(self.series_slug_edit.text().strip() or self._current_series_slug)
        if hasattr(self, "featured_series_picker") and hasattr(self, "selected_works_picker"):
            if self.tabs.currentWidget() is getattr(self, "relationships_tab", None):
                self.refresh_relationships()
            else:
                self._relationships_dirty = True

    def save_current_series(self) -> None:
        if not self._validate_series_form():
            QMessageBox.warning(self, "Invalid series", "Fix highlighted series fields before saving.")
            return
        old_slug = self._current_series_slug
        before_payload = load_series_payload(old_slug or "") if old_slug else {}
        payload = self.current_series_payload_from_form()
        try:
            slug = save_series_from_payload(old_slug, payload)
        except Exception as exc:
            QMessageBox.critical(self, "Save series failed", str(exc))
            return
        for key in {str(old_slug or ""), str(slug or "")}:
            if key:
                clear_editor_draft("series", key)
                self._draft_restore_seen.discard(("series", key))
                self._last_draft_hash.pop(("series", key), None)
        after_payload = load_series_payload(slug)
        self.refresh_reference_controls("series")
        self.push_notification("success", f"Saved series: {slug}", payload.get("title") or "", target_scope="series", target_id=slug)
        self._reset_autosave_state("series")
        self._show_toast(f"✓ Saved: {payload.get('title') or slug}")
        self._mark_saved()
        self._store_payload_diff("series", before_payload, after_payload)
        self.status_message(f"Saved series: {slug} · {self._payload_diff_summary(before_payload, after_payload)}")
        self.refresh_all_context(activate="series", select_series=slug, force=True, scope={"series", "dashboard", "validation", "studio"})

    def refresh_work_series_combos(self) -> None:
        if not hasattr(self, "work_series_combo"):
            return
        live_series = available_series_slugs()
        with signals_blocked(self.work_series_filter_combo):
            current = self.work_series_filter_combo.currentText()
            series_values = self._all_work_series_filter_values()
            self.work_series_filter_combo.clear(); self.work_series_filter_combo.addItems(series_values)
            if current in series_values:
                self.work_series_filter_combo.setCurrentText(current)
        with signals_blocked(self.work_series_combo):
            current = self.work_series_combo.currentText()
            self.work_series_combo.clear(); self.work_series_combo.addItems(live_series)
            if current in live_series:
                self.work_series_combo.setCurrentText(current)
        with signals_blocked(self.batch_move_series_combo):
            current = self.batch_move_series_combo.currentText()
            self.batch_move_series_combo.clear(); self.batch_move_series_combo.addItems(live_series)
            if current in live_series:
                self.batch_move_series_combo.setCurrentText(current)

    def open_new_series_dialog(self) -> None:
        dialog = NewSeriesDialog(self)
        dialog.exec()

    # ---------- relationships ----------
    def build_relationships_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.relationships_summary_label = QLabel("Homepage curation: arrange featured series and selected works without editing website code.")
        self.relationships_summary_label.setObjectName("missionStatus")
        self.relationships_summary_label.setWordWrap(True)
        layout.addWidget(self.relationships_summary_label)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setObjectName("relationships-main-splitter")

        left = QWidget(); left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Featured series on home page"))
        self.featured_series_list = ReorderListWidget()
        self.featured_series_list.setObjectName("featuredSeriesRelationshipList")
        self.featured_series_list.setIconSize(QSize(58, 58))
        self.featured_series_list.setSpacing(4)
        self.featured_series_list.setToolTip("Drag featured series to reorder their homepage presentation. Use ↑/↓ as the accessible fallback.")
        self.featured_series_list.orderChanged.connect(self.on_relationship_order_changed)
        self.featured_series_list.itemDoubleClicked.connect(lambda _item: self.open_selected_relationship_item("series"))
        left_layout.addWidget(self.featured_series_list, 1)
        left_pick_row = QHBoxLayout()
        self.featured_series_picker = QComboBox()
        add_series_btn = QPushButton("Add")
        add_series_btn.clicked.connect(lambda: self.add_relationship_item(self.featured_series_list, self.featured_series_picker))
        remove_series_btn = QPushButton("Remove")
        remove_series_btn.clicked.connect(lambda: self.remove_relationship_item(self.featured_series_list))
        move_series_up = QPushButton("↑")
        move_series_up.clicked.connect(lambda: self.move_relationship_item(self.featured_series_list, -1))
        move_series_down = QPushButton("↓")
        move_series_down.clicked.connect(lambda: self.move_relationship_item(self.featured_series_list, 1))
        open_series_btn = QPushButton("Open")
        open_series_btn.clicked.connect(lambda: self.open_selected_relationship_item("series"))
        for widget in (self.featured_series_picker, add_series_btn, remove_series_btn, move_series_up, move_series_down, open_series_btn):
            left_pick_row.addWidget(widget)
        left_layout.addLayout(left_pick_row)
        split.addWidget(left)

        right = QWidget(); right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Selected works on home page"))
        self.selected_works_list = ReorderListWidget()
        self.selected_works_list.setObjectName("selectedWorksRelationshipList")
        self.selected_works_list.setIconSize(QSize(58, 58))
        self.selected_works_list.setSpacing(4)
        self.selected_works_list.setToolTip("Drag selected works to reorder their homepage presentation. Use ↑/↓ as the accessible fallback.")
        self.selected_works_list.orderChanged.connect(self.on_relationship_order_changed)
        self.selected_works_list.itemDoubleClicked.connect(lambda _item: self.open_selected_relationship_item("work"))
        right_layout.addWidget(self.selected_works_list, 1)
        right_pick_row = QHBoxLayout()
        self.selected_works_picker = QComboBox()
        add_work_btn = QPushButton("Add")
        add_work_btn.clicked.connect(lambda: self.add_relationship_item(self.selected_works_list, self.selected_works_picker))
        remove_work_btn = QPushButton("Remove")
        remove_work_btn.clicked.connect(lambda: self.remove_relationship_item(self.selected_works_list))
        move_work_up = QPushButton("↑")
        move_work_up.clicked.connect(lambda: self.move_relationship_item(self.selected_works_list, -1))
        move_work_down = QPushButton("↓")
        move_work_down.clicked.connect(lambda: self.move_relationship_item(self.selected_works_list, 1))
        open_work_btn = QPushButton("Open")
        open_work_btn.clicked.connect(lambda: self.open_selected_relationship_item("work"))
        for widget in (self.selected_works_picker, add_work_btn, remove_work_btn, move_work_up, move_work_down, open_work_btn):
            right_pick_row.addWidget(widget)
        right_layout.addLayout(right_pick_row)
        split.addWidget(right)

        split.setSizes([520, 760])
        layout.addWidget(split, 1)
        save_btn = QPushButton("Save relationships")
        save_btn.clicked.connect(self.save_relationships_tab)
        layout.addWidget(save_btn)
        return tab

    def refresh_relationships(self) -> None:
        data = load_relationships()
        self.populate_relationship_pickers()
        self.featured_series_list.clear()
        for slug in data.get("featured_series", []):
            series_payload = load_series_payload(str(slug)) or {}
            title = str(series_payload.get("title") or slug)
            item = QListWidgetItem(f"{title}\n{slug}")
            item.setData(Qt.ItemDataRole.UserRole, str(slug))
            cover = str(series_payload.get("cover_work_id") or "")
            if cover:
                icon = self.work_tree_icon(load_work_payload(cover) or {"id": cover, "series": slug})
                if not icon.isNull():
                    item.setIcon(icon)
            self.featured_series_list.addItem(item)
        self.selected_works_list.clear()
        for work_id in data.get("featured_works", []):
            work_payload = load_work_payload(str(work_id)) or {"id": work_id}
            title = str(work_payload.get("title") or work_id)
            item = QListWidgetItem(f"{title}\n{work_id}")
            item.setData(Qt.ItemDataRole.UserRole, str(work_id))
            icon = self.work_tree_icon(work_payload)
            if not icon.isNull():
                item.setIcon(icon)
            self.selected_works_list.addItem(item)
        if hasattr(self, "relationships_summary_label"):
            duplicate_works = len(data.get("featured_works", []) or []) - len(set(data.get("featured_works", []) or []))
            warnings = f" · {duplicate_works} duplicate work pick(s)" if duplicate_works else ""
            self.relationships_summary_label.setText(f"Homepage curation: {self.featured_series_list.count()} featured series · {self.selected_works_list.count()} selected work(s){warnings}.")

    def populate_relationship_pickers(self) -> None:
        series_choices = available_series_slugs()
        work_choices = [str(item.get("id") or "") for item in load_work_entries() if str(item.get("id") or "")]
        self.featured_series_picker.clear(); self.featured_series_picker.addItems(series_choices)
        self.selected_works_picker.clear(); self.selected_works_picker.addItems(work_choices)

    def add_relationship_item(self, list_widget: QListWidget, picker: QComboBox) -> None:
        value = picker.currentText().strip()
        if not value:
            return
        existing = [list_widget.item(index).text() for index in range(list_widget.count())]
        if value in existing:
            list_widget.setCurrentRow(existing.index(value))
            return
        list_widget.addItem(value)
        list_widget.setCurrentRow(list_widget.count() - 1)
        self.on_relationship_order_changed()

    def remove_relationship_item(self, list_widget: QListWidget) -> None:
        row = list_widget.currentRow()
        if row >= 0:
            removed = list_widget.takeItem(row)
            del removed
            self.on_relationship_order_changed()

    def move_relationship_item(self, list_widget: QListWidget, direction: int) -> None:
        row = list_widget.currentRow()
        if row < 0:
            return
        target = max(0, min(list_widget.count() - 1, row + direction))
        if target == row:
            return
        item = list_widget.takeItem(row)
        list_widget.insertItem(target, item)
        list_widget.setCurrentRow(target)
        self.on_relationship_order_changed()

    def on_relationship_order_changed(self) -> None:
        if not hasattr(self, "featured_series_list") or not hasattr(self, "selected_works_list"):
            return
        self._relationships_dirty = True
        self.status_message("Relationships changed · Save relationships to persist homepage ordering")
        if hasattr(self, "side_nav"):
            self.sync_side_navigation()

    def open_selected_relationship_item(self, kind: str) -> None:
        if kind == "series":
            item = self.featured_series_list.currentItem() if hasattr(self, "featured_series_list") else None
            slug = str(item.data(Qt.ItemDataRole.UserRole) or item.text()).strip() if item is not None else ""
            if "\n" in slug:
                slug = slug.split("\n")[-1].strip()
            if not slug:
                return
            self.tabs.setCurrentWidget(self.series_tab)
            self.select_series(slug)
            return
        item = self.selected_works_list.currentItem() if hasattr(self, "selected_works_list") else None
        work_id = str(item.data(Qt.ItemDataRole.UserRole) or item.text()).strip() if item is not None else ""
        if "\n" in work_id:
            work_id = work_id.split("\n")[-1].strip()
        if not work_id:
            return
        self.tabs.setCurrentWidget(self.works_tab)
        self.select_work(work_id)

    def list_widget_values(self, list_widget: QListWidget) -> list[str]:
        values: list[str] = []
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            if item is None:
                continue
            value = str(item.data(Qt.ItemDataRole.UserRole) or item.text()).strip()
            if "\n" in value and not item.data(Qt.ItemDataRole.UserRole):
                value = value.split("\n")[-1].strip()
            if value:
                values.append(value)
        return values

    def save_relationships_tab(self) -> None:
        featured = self.list_widget_values(self.featured_series_list)
        works = self.list_widget_values(self.selected_works_list)
        try:
            save_relationships(featured, works)
        except Exception as exc:
            QMessageBox.critical(self, "Save relationships failed", str(exc))
            return
        self._relationships_dirty = False
        self.push_notification("success", "Saved homepage relationships", f"{len(featured)} series · {len(works)} work(s)", target_scope="relationships")
        self.status_message("Saved homepage relationships")
        self.refresh_dashboard()
        self.sync_side_navigation()


    # ---------- pages ----------
    def build_pages_tab(self) -> QWidget:
        tab = QWidget()
        tab.setObjectName("contentPagesTab")
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        def content_label(text: str, object_name: str = "contentSectionTitle") -> QLabel:
            label = QLabel(text)
            label.setObjectName(object_name)
            label.setWordWrap(True)
            return label

        def content_hint(text: str, object_name: str = "contentSectionHint") -> QLabel:
            label = QLabel(text)
            label.setObjectName(object_name)
            label.setWordWrap(True)
            return label

        def make_card(title: str = "", hint: str = "", object_name: str = "contentCard") -> tuple[QFrame, QVBoxLayout]:
            card = QFrame()
            card.setObjectName(object_name)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(10)
            if title or hint:
                header = QVBoxLayout()
                header.setContentsMargins(0, 0, 0, 0)
                header.setSpacing(2)
                if title:
                    header.addWidget(content_label(title))
                if hint:
                    header.addWidget(content_hint(hint))
                card_layout.addLayout(header)
            return card, card_layout

        def configure_form(form: QFormLayout) -> None:
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(14)
            form.setVerticalSpacing(10)

        nav_card, nav_layout = make_card(
            "Pages",
            "Select one public page, then edit hero, SEO, sections, and advanced YAML only when needed.",
            "contentNavCard",
        )
        nav_card.setMinimumWidth(250)
        nav_card.setMaximumWidth(340)
        self.pages_list = QListWidget()
        self.pages_list.setObjectName("contentPagesList")
        self.pages_list.setAccessibleName("Content Builder page list")
        self.pages_list.setToolTip("Select a public page to edit its structured content.")
        self.pages_list.itemSelectionChanged.connect(self.on_page_selection_changed)
        nav_layout.addWidget(self.pages_list, 1)
        self.page_context_hint = QLabel("Structured page editing with live YAML sync, validation, and change review.")
        self.page_context_hint.setObjectName("contentHelpText")
        self.page_context_hint.setWordWrap(True)
        nav_layout.addWidget(self.page_context_hint)
        layout.addWidget(nav_card, 0)

        right_host = QWidget()
        right_host.setObjectName("contentWorkspace")
        right = QVBoxLayout(right_host)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        header_card = QFrame()
        header_card.setObjectName("contentHeaderCard")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(9)
        header_top = QHBoxLayout()
        header_top.setContentsMargins(0, 0, 0, 0)
        header_top.setSpacing(10)
        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(4)
        self.page_breadcrumb = QLabel("Content Builder  ›  No page selected")
        self.page_breadcrumb.setObjectName("contentBreadcrumb")
        self.page_breadcrumb.setWordWrap(True)
        header_text.addWidget(self.page_breadcrumb)
        header_text.addWidget(content_hint("Edit the public page in structured mode first. Raw YAML stays behind Advanced YAML.", "contentHeaderHint"))
        header_top.addLayout(header_text, 1)

        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(7)
        self.page_builder_context = QLabel("No page loaded")
        self.page_builder_context.setObjectName("contentBadge")
        badge_row.addWidget(self.page_builder_context)
        self.page_builder_state = QLabel("Clean")
        self.page_builder_state.setObjectName("contentBadge")
        badge_row.addWidget(self.page_builder_state)
        self.page_autosave_status = QLabel("")
        self.page_autosave_status.setObjectName("contentAutosaveStatus")
        badge_row.addWidget(self.page_autosave_status)
        header_top.addLayout(badge_row, 0)
        header_layout.addLayout(header_top)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.page_advanced_yaml_btn = QPushButton("Advanced YAML")
        self.page_advanced_yaml_btn.setObjectName("contentSecondaryAction")
        self.page_advanced_yaml_btn.setCheckable(True)
        self.page_advanced_yaml_btn.setToolTip("Show raw YAML and detailed diff tools. Leave off for normal structured editing.")
        self.page_advanced_yaml_btn.toggled.connect(self.set_page_advanced_yaml_mode)
        page_validate = QPushButton("Validate")
        page_validate.setObjectName("contentSecondaryAction")
        page_validate.clicked.connect(self.validate_current_page_builder)
        page_save = QPushButton("Save page")
        page_save.setObjectName("contentPrimaryAction")
        page_save.clicked.connect(self.save_current_page)
        page_reload = QPushButton("Reload")
        page_reload.setObjectName("contentSecondaryAction")
        page_reload.clicked.connect(self.reload_current_page)
        action_row.addStretch(1)
        for button in (self.page_advanced_yaml_btn, page_validate, page_save, page_reload):
            action_row.addWidget(button)
        header_layout.addLayout(action_row)
        right.addWidget(header_card)

        self.page_builder_tabs = QTabWidget()
        self.page_builder_tabs.setObjectName("contentBuilderTabs")
        right.addWidget(self.page_builder_tabs, 1)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(10)
        self.page_live_review_drawer = QLabel("Live page health will appear after a page loads.")
        self.page_live_review_drawer.setObjectName("contentHealthCard")
        self.page_live_review_drawer.setWordWrap(True)
        status_row.addWidget(self.page_live_review_drawer, 2)
        self.page_structure_summary = QLabel("Page summary: choose a page to review hero, SEO, sections, and visibility.")
        self.page_structure_summary.setObjectName("contentSummaryCard")
        self.page_structure_summary.setWordWrap(True)
        status_row.addWidget(self.page_structure_summary, 1)
        right.addLayout(status_row)

        structured_tab = QWidget()
        structured_tab.setObjectName("contentStructuredTab")
        structured_layout = QVBoxLayout(structured_tab)
        structured_layout.setContentsMargins(0, 0, 0, 0)
        structured_layout.setSpacing(0)
        structured_scroll = QScrollArea()
        structured_scroll.setObjectName("contentStructuredScroll")
        structured_scroll.setWidgetResizable(True)
        structured_scroll.setFrameShape(QFrame.Shape.NoFrame)
        structured_layout.addWidget(structured_scroll, 1)
        structured_canvas = QWidget()
        structured_canvas.setObjectName("contentStructuredCanvas")
        canvas_layout = QVBoxLayout(structured_canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(12)
        structured_scroll.setWidget(structured_canvas)

        content_split = QSplitter(Qt.Orientation.Horizontal)
        content_split.setObjectName("pages-main-splitter")
        self.pages_top_splitter = content_split
        canvas_layout.addWidget(content_split, 1)

        left_column = QWidget()
        left_column.setObjectName("contentLeftColumn")
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)

        meta_card, meta_layout = make_card(
            "Meta and social",
            "Search/social text used outside the visible page. Keep it precise and source-safe.",
            "contentEditorCard",
        )
        meta_form = QFormLayout()
        configure_form(meta_form)
        self.page_meta_title_edit = QLineEdit()
        self.page_meta_title_edit.setObjectName("contentLineEdit")
        meta_form.addRow("Meta title", self.page_meta_title_edit)
        self.page_meta_description_edit = QPlainTextEdit()
        self.page_meta_description_edit.setObjectName("contentTextEdit")
        self.page_meta_description_edit.setMinimumHeight(82)
        self.page_meta_description_edit.setMaximumHeight(118)
        meta_form.addRow("Meta description", self.page_meta_description_edit)
        self.page_meta_og_description_edit = QPlainTextEdit()
        self.page_meta_og_description_edit.setObjectName("contentTextEdit")
        self.page_meta_og_description_edit.setMinimumHeight(82)
        self.page_meta_og_description_edit.setMaximumHeight(118)
        meta_form.addRow("OG description", self.page_meta_og_description_edit)
        self.page_meta_og_image_edit = QLineEdit()
        self.page_meta_og_image_edit.setObjectName("contentLineEdit")
        meta_form.addRow("OG image", self.page_meta_og_image_edit)
        self.page_meta_og_alt_edit = QPlainTextEdit()
        self.page_meta_og_alt_edit.setObjectName("contentTextEdit")
        self.page_meta_og_alt_edit.setMinimumHeight(72)
        self.page_meta_og_alt_edit.setMaximumHeight(100)
        meta_form.addRow("OG image alt", self.page_meta_og_alt_edit)
        meta_layout.addLayout(meta_form)
        left_layout.addWidget(meta_card)

        section_card, section_layout = make_card(
            "Page sections",
            "Build the public reading order. Select a row to edit its fields on the right.",
            "contentEditorCard",
        )
        section_toolbar = QHBoxLayout()
        section_toolbar.setContentsMargins(0, 0, 0, 0)
        section_toolbar.setSpacing(7)
        self.page_add_section_button = QPushButton("Add")
        self.page_add_section_button.setObjectName("contentPrimaryAction")
        self.page_duplicate_section_button = QPushButton("Duplicate")
        self.page_change_section_type_button = QPushButton("Change type")
        self.page_edit_section_json_button = QPushButton("Section JSON")
        self.page_remove_section_button = QPushButton("Remove")
        self.page_toggle_section_button = QPushButton("Hide/Show")
        self.page_section_up_button = QPushButton("↑")
        self.page_section_down_button = QPushButton("↓")
        section_menu = QMenu(self)
        self.page_section_json_action = None
        for label, button in (
            ("Duplicate section", self.page_duplicate_section_button),
            ("Change section type", self.page_change_section_type_button),
            ("Edit section JSON", self.page_edit_section_json_button),
            ("Remove section", self.page_remove_section_button),
            ("Hide / show section", self.page_toggle_section_button),
        ):
            action = QAction(label, self)
            action.triggered.connect(lambda _checked=False, b=button: b.click())
            section_menu.addAction(action)
            if label == "Edit section JSON":
                self.page_section_json_action = action
                action.setVisible(False)
        section_more_button = QPushButton("Section actions ▾")
        section_more_button.setObjectName("contentSecondaryAction")
        section_more_button.setMenu(section_menu)
        for btn in (self.page_section_up_button, self.page_section_down_button):
            btn.setObjectName("contentIconAction")
        section_toolbar.addWidget(self.page_add_section_button)
        section_toolbar.addWidget(self.page_section_up_button)
        section_toolbar.addWidget(self.page_section_down_button)
        section_toolbar.addWidget(section_more_button)
        section_toolbar.addStretch(1)
        section_layout.addLayout(section_toolbar)
        self.page_sections_list = QTreeWidget()
        self.page_sections_list.setObjectName("contentSectionsTree")
        self.page_sections_list.setAccessibleName("Page sections list")
        self.page_sections_list.setHeaderLabels(["Section", "Type", "State"])
        self.page_sections_list.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.page_sections_list.setColumnWidth(0, 210)
        self.page_sections_list.setColumnWidth(1, 140)
        self.page_sections_list.setMinimumHeight(250)
        self.page_sections_list.itemSelectionChanged.connect(self.on_page_section_selected)
        try:
            self._polish_data_tree(self.page_sections_list, "content_sections")
        except Exception as exc:
            self._log_warning(f"Content Builder section tree polish failed: {exc}")
        section_layout.addWidget(self.page_sections_list, 1)
        left_layout.addWidget(section_card, 1)

        right_column = QWidget()
        right_column.setObjectName("contentRightColumn")
        right_column_layout = QVBoxLayout(right_column)
        right_column_layout.setContentsMargins(0, 0, 0, 0)
        right_column_layout.setSpacing(12)

        hero_card, hero_layout = make_card(
            "Hero and public narrative",
            "This is the visible page opening. Keep the lead readable and the action list intentional.",
            "contentEditorCard",
        )
        hero_form = QFormLayout()
        configure_form(hero_form)
        self.page_hero_eyebrow_edit = QLineEdit()
        self.page_hero_eyebrow_edit.setObjectName("contentLineEdit")
        hero_form.addRow("Eyebrow", self.page_hero_eyebrow_edit)
        self.page_hero_title_edit = QLineEdit()
        self.page_hero_title_edit.setObjectName("contentLineEdit")
        hero_form.addRow("Title", self.page_hero_title_edit)
        self.page_hero_lead_edit = QPlainTextEdit()
        self.page_hero_lead_edit.setObjectName("contentTextEdit")
        self.page_hero_lead_edit.setMinimumHeight(100)
        self.page_hero_lead_edit.setMaximumHeight(150)
        hero_form.addRow("Lead", self.page_hero_lead_edit)
        self.page_hero_feature_combo = QComboBox()
        self.page_hero_feature_combo.setObjectName("contentComboBox")
        self.page_hero_feature_combo.setEditable(True)
        try:
            self.page_hero_feature_combo.lineEdit().setPlaceholderText("Choose or type a valid work ID")
        except Exception:
            pass
        feature_picker_wrap = QWidget()
        feature_picker_wrap.setObjectName("contentFeatureWorkPicker")
        feature_picker_layout = QHBoxLayout(feature_picker_wrap)
        feature_picker_layout.setContentsMargins(0, 0, 0, 0)
        feature_picker_layout.setSpacing(7)
        feature_picker_layout.addWidget(self.page_hero_feature_combo, 1)
        self.page_hero_feature_choose_button = QPushButton("Choose…")
        self.page_hero_feature_refresh_button = QPushButton("Refresh")
        self.page_hero_feature_auto_button = QPushButton("Auto-pick")
        self.page_hero_feature_clear_button = QPushButton("Clear")
        for btn in (self.page_hero_feature_choose_button, self.page_hero_feature_refresh_button, self.page_hero_feature_auto_button, self.page_hero_feature_clear_button):
            btn.setObjectName("contentSecondaryAction")
            feature_picker_layout.addWidget(btn)
        hero_form.addRow("Feature work", feature_picker_wrap)
        self.page_hero_notes_edit = QPlainTextEdit()
        self.page_hero_notes_edit.setObjectName("contentTextEdit")
        self.page_hero_notes_edit.setPlaceholderText("One note per line")
        self.page_hero_notes_edit.setMinimumHeight(72)
        self.page_hero_notes_edit.setMaximumHeight(110)
        hero_form.addRow("Hero notes", self.page_hero_notes_edit)

        hero_actions_wrap = QWidget()
        hero_actions_wrap.setObjectName("contentActionListWrap")
        hero_actions_layout = QVBoxLayout(hero_actions_wrap)
        hero_actions_layout.setContentsMargins(0, 0, 0, 0)
        hero_actions_layout.setSpacing(8)
        self.page_hero_actions_list = QListWidget()
        self.page_hero_actions_list.setObjectName("contentHeroActionsList")
        self.page_hero_actions_list.setMinimumHeight(78)
        self.page_hero_actions_list.setMaximumHeight(138)
        hero_actions_layout.addWidget(self.page_hero_actions_list)
        hero_btns = QHBoxLayout()
        hero_btns.setContentsMargins(0, 0, 0, 0)
        hero_btns.setSpacing(7)
        self.page_hero_action_add = QPushButton("Add action")
        self.page_hero_action_edit = QPushButton("Edit")
        self.page_hero_action_remove = QPushButton("Remove")
        self.page_hero_action_up = QPushButton("↑")
        self.page_hero_action_down = QPushButton("↓")
        self.page_hero_action_add.setObjectName("contentPrimaryAction")
        for btn in (self.page_hero_action_edit, self.page_hero_action_remove):
            btn.setObjectName("contentSecondaryAction")
        for btn in (self.page_hero_action_up, self.page_hero_action_down):
            btn.setObjectName("contentIconAction")
        for btn in (self.page_hero_action_add, self.page_hero_action_edit, self.page_hero_action_remove, self.page_hero_action_up, self.page_hero_action_down):
            hero_btns.addWidget(btn)
        hero_btns.addStretch(1)
        hero_actions_layout.addLayout(hero_btns)
        hero_form.addRow("Hero actions", hero_actions_wrap)
        hero_layout.addLayout(hero_form)
        right_column_layout.addWidget(hero_card)

        editor_card, editor_layout = make_card(
            "Selected section editor",
            "Edit only the selected section. The form updates automatically when you select a different row.",
            "contentEditorCard",
        )
        self.page_section_status = QLabel("Select a section to edit its fields.")
        self.page_section_status.setObjectName("contentSectionStatus")
        self.page_section_status.setWordWrap(True)
        editor_layout.addWidget(self.page_section_status)
        section_scroll = QScrollArea()
        section_scroll.setObjectName("contentSectionScroll")
        section_scroll.setWidgetResizable(True)
        section_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page_section_form_host = QWidget()
        self.page_section_form_host.setObjectName("contentSectionFormHost")
        self.page_section_form_layout = QFormLayout(self.page_section_form_host)
        configure_form(self.page_section_form_layout)
        self.page_section_form_layout.setContentsMargins(10, 10, 10, 10)
        section_scroll.setWidget(self.page_section_form_host)
        editor_layout.addWidget(section_scroll, 1)
        right_column_layout.addWidget(editor_card, 1)

        content_split.addWidget(left_column)
        content_split.addWidget(right_column)
        content_split.setSizes([560, 780])
        content_split.setStretchFactor(0, 4)
        content_split.setStretchFactor(1, 5)
        canvas_layout.addStretch(1)
        self.page_builder_tabs.addTab(structured_tab, "Structured editor")

        raw_tab = QWidget()
        raw_tab.setObjectName("contentRawTab")
        raw_layout = QVBoxLayout(raw_tab)
        raw_layout.setContentsMargins(0, 0, 0, 0)
        raw_layout.setSpacing(10)
        raw_toolbar_card, raw_toolbar_layout = make_card(
            "Raw YAML tools",
            "Use this only for raw-file repair, formatting, or detailed diff review.",
            "contentEditorCard",
        )
        raw_toolbar = QHBoxLayout()
        raw_toolbar.setContentsMargins(0, 0, 0, 0)
        raw_toolbar.setSpacing(8)
        self.page_apply_yaml_button = QPushButton("Apply YAML to builder")
        self.page_apply_yaml_button.clicked.connect(self.apply_page_yaml_to_builder)
        self.page_format_yaml_button = QPushButton("Format YAML")
        self.page_format_yaml_button.clicked.connect(self.format_current_page_yaml)
        self.page_validate_yaml_button = QPushButton("Validate YAML")
        self.page_validate_yaml_button.clicked.connect(self.validate_current_page_builder)
        self.page_copy_yaml_button = QPushButton("Copy YAML")
        self.page_copy_yaml_button.clicked.connect(self.copy_page_yaml)
        self.page_restore_valid_button = QPushButton("Restore last valid")
        self.page_restore_valid_button.setToolTip("Recover the last YAML version that passed validation before a raw save.")
        self.page_restore_valid_button.clicked.connect(self.restore_current_page_last_valid)
        for button in (self.page_apply_yaml_button, self.page_format_yaml_button, self.page_validate_yaml_button, self.page_copy_yaml_button, self.page_restore_valid_button):
            button.setObjectName("contentSecondaryAction")
            raw_toolbar.addWidget(button)
        raw_toolbar.addStretch(1)
        self.page_yaml_mode_label = QLabel("Builder and YAML are in sync")
        self.page_yaml_mode_label.setObjectName("contentHeaderHint")
        raw_toolbar.addWidget(self.page_yaml_mode_label)
        raw_toolbar_layout.addLayout(raw_toolbar)
        raw_layout.addWidget(raw_toolbar_card)
        self.page_editor = QPlainTextEdit()
        self.page_editor.setObjectName("contentYamlEditor")
        raw_layout.addWidget(self.page_editor, 1)
        self.page_builder_tabs.addTab(raw_tab, "Raw YAML")

        review_tab = QWidget()
        review_tab.setObjectName("contentReviewTab")
        review_layout = QVBoxLayout(review_tab)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.setSpacing(10)
        review_header_card, review_header_layout = make_card(
            "Validation and change review",
            "Errors, warnings, and YAML diff stay here so the structured editor stays calm.",
            "contentEditorCard",
        )
        self.page_review_summary = QLabel("Validation and diff review will appear here.")
        self.page_review_summary.setObjectName("contentSectionStatus")
        self.page_review_summary.setWordWrap(True)
        review_header_layout.addWidget(self.page_review_summary)
        review_layout.addWidget(review_header_card)
        review_split = QSplitter(Qt.Orientation.Vertical)
        review_split.setObjectName("pages-review-splitter")
        self.page_validation_box = QPlainTextEdit()
        self.page_validation_box.setObjectName("contentReviewBox")
        self.page_validation_box.setReadOnly(True)
        self.page_diff_box = QPlainTextEdit()
        self.page_diff_box.setObjectName("contentReviewBox")
        self.page_diff_box.setReadOnly(True)
        review_split.addWidget(self.page_validation_box)
        review_split.addWidget(self.page_diff_box)
        review_split.setSizes([220, 280])
        review_layout.addWidget(review_split, 1)
        self.page_builder_tabs.addTab(review_tab, "Validation & changes")
        try:
            self.page_builder_tabs.setTabVisible(1, False)
            self.page_builder_tabs.setTabVisible(2, False)
        except Exception as exc:
            self._log_warning(f"Page advanced-tab setup failed: {exc}")
        self._last_page_builder_tab_index = 0
        self.page_builder_tabs.currentChanged.connect(self._on_page_builder_tab_changed)

        layout.addWidget(right_host, 1)

        for widget in (self.page_meta_title_edit, self.page_meta_og_image_edit, self.page_hero_eyebrow_edit, self.page_hero_title_edit):
            widget.textChanged.connect(self.on_page_builder_header_changed)
        for widget in (self.page_meta_description_edit, self.page_meta_og_description_edit, self.page_meta_og_alt_edit, self.page_hero_lead_edit, self.page_hero_notes_edit):
            widget.textChanged.connect(self.on_page_builder_header_changed)
        self.page_hero_feature_combo.currentTextChanged.connect(self.on_page_builder_header_changed)
        self.page_hero_feature_choose_button.clicked.connect(self.choose_page_hero_feature_work)
        self.page_hero_feature_refresh_button.clicked.connect(self.refresh_page_hero_feature_options_from_ui)
        self.page_hero_feature_auto_button.clicked.connect(self.auto_pick_page_hero_feature_work)
        self.page_hero_feature_clear_button.clicked.connect(self.clear_page_hero_feature_work)
        self.page_editor.textChanged.connect(lambda: self.schedule_editor_autosave("page"))
        self.page_editor.textChanged.connect(self.on_page_raw_text_changed)

        self.page_hero_action_add.clicked.connect(lambda: self.edit_page_action_item("hero", mode="add"))
        self.page_hero_action_edit.clicked.connect(lambda: self.edit_page_action_item("hero", mode="edit"))
        self.page_hero_action_remove.clicked.connect(lambda: self.edit_page_action_item("hero", mode="remove"))
        self.page_hero_action_up.clicked.connect(lambda: self.edit_page_action_item("hero", mode="up"))
        self.page_hero_action_down.clicked.connect(lambda: self.edit_page_action_item("hero", mode="down"))

        self.page_add_section_button.clicked.connect(self.add_page_section)
        self.page_duplicate_section_button.clicked.connect(self.duplicate_page_section)
        self.page_change_section_type_button.clicked.connect(self.change_page_section_type)
        self.page_edit_section_json_button.clicked.connect(self.edit_current_page_section_json)
        self.page_remove_section_button.clicked.connect(self.remove_page_section)
        self.page_toggle_section_button.clicked.connect(self.toggle_page_section_visibility)
        self.page_section_up_button.clicked.connect(lambda: self.move_page_section(-1))
        self.page_section_down_button.clicked.connect(lambda: self.move_page_section(1))

        outer = QWidget()
        outer.setObjectName("contentBuilderOuter")
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        self.content_inner_tabs = QTabWidget()
        self.content_inner_tabs.setObjectName("contentInnerTabs")
        self.content_inner_tabs.addTab(tab, "Pages")
        try:
            self.authority_tab = self.build_authority_tab()
            self.content_inner_tabs.addTab(self.authority_tab, "Authority Files")
        except Exception as exc:
            self._log_warning(f"Authority panel could not be embedded in Content Builder: {exc}")
        outer_layout.addWidget(self.content_inner_tabs, 1)
        return outer

    def set_page_advanced_yaml_mode(self, enabled: bool) -> None:
        if not hasattr(self, "page_builder_tabs"):
            return
        try:
            self.page_builder_tabs.setTabVisible(1, bool(enabled))
            self.page_builder_tabs.setTabVisible(2, bool(enabled))
        except Exception as exc:
            self._log_warning(f"Page advanced-tab toggle failed: {exc}")
        if not enabled and self.page_builder_tabs.currentIndex() in {1, 2}:
            self.page_builder_tabs.setCurrentIndex(0)
        if hasattr(self, "page_section_json_action") and self.page_section_json_action is not None:
            self.page_section_json_action.setVisible(bool(enabled))
        self.status_message("Advanced page YAML tools shown" if enabled else "Advanced page YAML tools hidden")

    def refresh_pages_list(self) -> None:
        current = self._current_page_key
        self.pages_list.clear()
        for page_key in available_page_keys():
            item = QListWidgetItem(page_key)
            item.setData(Qt.ItemDataRole.UserRole, page_key)
            self.pages_list.addItem(item)
        if current:
            self.select_page(current, silent=True)

    def on_page_selection_changed(self) -> None:
        items = self.pages_list.selectedItems()
        if not items:
            return
        target = str(items[0].data(Qt.ItemDataRole.UserRole) or "")
        if target == self._current_page_key:
            return
        if not self.ensure_page_editor_safe():
            self._restore_page_selection()
            return
        self.select_page(target)

    def select_page(self, page_key: str, *, silent: bool = False, restore_draft: bool = False) -> None:
        if not page_key:
            return
        self._current_page_key = page_key
        bundle = load_page_builder_bundle(page_key)
        if hasattr(self, "tab_controllers") and "pages" in self.tab_controllers:
            self.tab_controllers["pages"].mark_current(page_key, dict(bundle.get("model") or {}))
        self._page_builder_model = dict(bundle.get("model") or {})
        self._page_builder_loaded_model = json.loads(json.dumps(self._page_builder_model))
        self._page_raw_override = False
        self._current_page_section_index = -1
        file_text = str(bundle.get("file_text") or load_page_yaml_text(page_key))
        self._loaded_page_text = file_text
        self._suspend_page_raw_sync = True
        try:
            with signals_blocked(self):
                self.page_editor.setPlainText(file_text)
                self.render_page_builder_from_model(select_first_section=True)
        finally:
            self._suspend_page_raw_sync = False
        self.render_page_review(bundle)
        if hasattr(self, "page_breadcrumb"):
            self.page_breadcrumb.setText(f"Content Builder  ›  {page_key}")
        self._reset_autosave_state("page")
        self.maybe_restore_editor_draft("page", page_key, interactive=restore_draft)
        self._update_autosave_labels()
        if not silent:
            self.status_message(f"Loaded page: {page_key}")

    def current_page_builder_model(self) -> dict[str, Any]:
        return dict(self._page_builder_model or {})

    def render_page_builder_from_model(self, *, select_first_section: bool = False) -> None:
        model = self._page_builder_model or {}
        meta = dict(model.get("meta") or {})
        hero = dict(model.get("hero") or {})
        self._suspend_page_builder_form = True
        try:
            with signals_blocked(self):
                self.page_builder_context.setText(self._current_page_key or "No page loaded")
                self.page_meta_title_edit.setText(str(meta.get("title") or ""))
                self.page_meta_description_edit.setPlainText(str(meta.get("description") or ""))
                self.page_meta_og_description_edit.setPlainText(str(meta.get("og_description") or ""))
                self.page_meta_og_image_edit.setText(str(meta.get("og_image") or ""))
                self.page_meta_og_alt_edit.setPlainText(str(meta.get("og_image_alt") or ""))
                self.refresh_page_hero_feature_options(selected_work_id=str(hero.get("feature_work_id") or ""), silent=True)
                self.page_hero_eyebrow_edit.setText(str(hero.get("eyebrow") or ""))
                self.page_hero_title_edit.setText(str(hero.get("title") or ""))
                self.page_hero_lead_edit.setPlainText(str(hero.get("lead") or ""))
                self.page_hero_notes_edit.setPlainText("\n".join(str(item).strip() for item in (hero.get("notes") or []) if str(item).strip()))
                self.render_page_action_list(self.page_hero_actions_list, hero.get("actions") or [])
                self.refresh_page_sections_list(select_first=select_first_section)
        finally:
            self._suspend_page_builder_form = False
        self.update_page_builder_state_label()
        self.update_page_structure_summary()

    def page_feature_work_rows(self) -> list[dict[str, Any]]:
        """Return a resilient, fresh work list for page hero pickers.

        The normal repository can be stale while the Works tab is being refreshed or
        after bulk import. The direct YAML fallback prevents the Content Builder
        feature-work dropdown from collapsing to a single empty item.
        """
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_row(payload: dict[str, Any], *, source: str) -> None:
            if not isinstance(payload, dict):
                return
            work_id = str(payload.get("id") or "").strip()
            if not work_id or work_id in seen:
                return
            seen.add(work_id)
            title = str(payload.get("title") or work_id).strip() or work_id
            series = str(payload.get("series") or "").strip()
            review = str(payload.get("review_status") or "").strip() or "draft"
            published = bool(payload.get("published"))
            rows.append({
                "id": work_id,
                "title": title,
                "series": series,
                "review_status": review,
                "published": published,
                "source": source,
                "label": f"{work_id} — {title} · {series or 'no series'} · {'published' if published else review}",
            })

        try:
            for payload in load_work_entries():
                add_row(dict(payload or {}), source="repository")
        except Exception as exc:
            self._log_warning(f"Feature-work repository load failed: {exc}")

        try:
            works_dir = ROOT / "content" / "works"
            for path in sorted(works_dir.glob("*.yaml")):
                try:
                    with path.open("r", encoding="utf-8") as handle:
                        payload = yaml.safe_load(handle) or {}
                except Exception as exc:
                    self._log_warning(f"Could not read work YAML for feature picker: {path.name}: {exc}")
                    continue
                add_row(dict(payload or {}), source="yaml")
        except Exception as exc:
            self._log_warning(f"Feature-work direct YAML scan failed: {exc}")

        rows.sort(key=lambda row: (str(row.get("series") or "").lower(), str(row.get("title") or "").lower(), str(row.get("id") or "").lower()))
        return rows

    def refresh_page_hero_feature_options(self, *, selected_work_id: str = "", silent: bool = False) -> None:
        if not hasattr(self, "page_hero_feature_combo"):
            return
        selected = str(selected_work_id or self.current_page_hero_feature_work_id() or "").strip()
        rows = self.page_feature_work_rows()
        with signals_blocked(self.page_hero_feature_combo):
            self.page_hero_feature_combo.clear()
            self.page_hero_feature_combo.addItem("", "")
            for row in rows:
                label = str(row.get("label") or row.get("id") or "")
                work_id = str(row.get("id") or "")
                self.page_hero_feature_combo.addItem(label, work_id)
            if selected:
                self.set_page_hero_feature_work(selected, emit_change=False)
            else:
                self.page_hero_feature_combo.setCurrentIndex(0)
        if not silent:
            self.status_message(f"Feature work picker refreshed · {len(rows)} work(s) available")

    def refresh_page_hero_feature_options_from_ui(self) -> None:
        self.refresh_page_hero_feature_options(selected_work_id=self.current_page_hero_feature_work_id(), silent=False)

    def current_page_hero_feature_work_id(self) -> str:
        if not hasattr(self, "page_hero_feature_combo"):
            return ""
        data = self.page_hero_feature_combo.currentData()
        if data is not None:
            value = str(data or "").strip()
            if value:
                return value
        text = str(self.page_hero_feature_combo.currentText() or "").strip()
        if not text:
            return ""
        # Labels are formatted as "work-id — title · series · status". Keep direct
        # typing of an ID supported, but never save the whole label as the ID.
        candidate = text.split(" — ", 1)[0].strip()
        known = {str(row.get("id") or "").strip() for row in self.page_feature_work_rows()}
        if candidate in known:
            return candidate
        return text if text in known else candidate

    def set_page_hero_feature_work(self, work_id: str, *, emit_change: bool = True) -> None:
        work_id = str(work_id or "").strip()
        if not hasattr(self, "page_hero_feature_combo"):
            return
        with signals_blocked(self.page_hero_feature_combo):
            target_index = -1
            for index in range(self.page_hero_feature_combo.count()):
                if str(self.page_hero_feature_combo.itemData(index) or "").strip() == work_id:
                    target_index = index
                    break
            if target_index >= 0:
                self.page_hero_feature_combo.setCurrentIndex(target_index)
            elif work_id:
                self.page_hero_feature_combo.addItem(work_id, work_id)
                self.page_hero_feature_combo.setCurrentIndex(self.page_hero_feature_combo.count() - 1)
            else:
                self.page_hero_feature_combo.setCurrentIndex(0 if self.page_hero_feature_combo.count() else -1)
        if emit_change:
            self.on_page_builder_header_changed()

    def choose_page_hero_feature_work(self) -> None:
        rows = self.page_feature_work_rows()
        if not rows:
            self._critical_modal("No works available", "No work YAML files were found in content/works. Import or create a work before assigning a page feature image.", target_scope="page", target_id=self._current_page_key)
            return
        labels = [str(row.get("label") or row.get("id") or "") for row in rows]
        current_id = self.current_page_hero_feature_work_id()
        current_index = 0
        for idx, row in enumerate(rows):
            if str(row.get("id") or "") == current_id:
                current_index = idx
                break
        selected, ok = QInputDialog.getItem(self, "Choose feature work", "Feature work", labels, current_index, False)
        if not ok or not selected:
            return
        by_label = {str(row.get("label") or row.get("id") or ""): str(row.get("id") or "") for row in rows}
        self.set_page_hero_feature_work(by_label.get(str(selected), str(selected).split(" — ", 1)[0].strip()), emit_change=True)

    def suggested_page_feature_work_id(self) -> str:
        rows = self.page_feature_work_rows()
        if not rows:
            return ""
        by_id = {str(row.get("id") or ""): row for row in rows}
        candidate_ids: list[str] = []
        if str(self._current_page_key or "") == "performance":
            performance_series: list[dict[str, Any]] = []
            try:
                collection_path = ROOT / "content" / "collections" / "performance.yaml"
                collection = yaml.safe_load(collection_path.read_text(encoding="utf-8")) if collection_path.exists() else {}
                preferred_slugs = [str(item).strip() for item in (collection or {}).get("series_slugs", []) if str(item).strip()]
            except Exception:
                preferred_slugs = []
            try:
                all_series = [dict(item or {}) for item in load_series_entries()]
            except Exception:
                all_series = []
            for slug in preferred_slugs:
                for series in all_series:
                    if str(series.get("slug") or "").strip() == slug:
                        performance_series.append(series)
                        break
            for series in all_series:
                if str(series.get("project_type") or "").strip().lower() == "performance" and series not in performance_series:
                    performance_series.append(series)
            for series in performance_series:
                cover = str(series.get("cover_work_id") or "").strip()
                if cover:
                    candidate_ids.append(cover)
                candidate_ids.extend(str(item).strip() for item in (series.get("work_ids") or []) if str(item).strip())
        candidate_ids.extend(str(row.get("id") or "") for row in rows if bool(row.get("published")))
        candidate_ids.extend(str(row.get("id") or "") for row in rows)
        seen: set[str] = set()
        for work_id in candidate_ids:
            if not work_id or work_id in seen:
                continue
            seen.add(work_id)
            if work_id in by_id and bool(by_id[work_id].get("published")):
                return work_id
        for work_id in candidate_ids:
            if work_id in by_id:
                return work_id
        return ""

    def auto_pick_page_hero_feature_work(self) -> None:
        work_id = self.suggested_page_feature_work_id()
        if not work_id:
            self._critical_modal("Auto-pick failed", "No suitable work was found for this page hero.", target_scope="page", target_id=self._current_page_key)
            return
        self.set_page_hero_feature_work(work_id, emit_change=True)
        self.status_message(f"Feature work set to {work_id}")

    def clear_page_hero_feature_work(self) -> None:
        self.set_page_hero_feature_work("", emit_change=True)
        self.status_message("Feature work cleared")

    def render_page_action_list(self, widget: QListWidget, rows: list[dict[str, Any]]) -> None:
        widget.clear()
        for row in rows or []:
            label = str(row.get("label") or "Action")
            href = str(row.get("href") or "")
            style = str(row.get("style") or "")
            item = QListWidgetItem(f"{label} → {href} {('· ' + style) if style else ''}".strip())
            item.setData(Qt.ItemDataRole.UserRole, dict(row))
            widget.addItem(item)

    def refresh_page_sections_list(self, *, select_first: bool = False) -> None:
        current_index = self._current_page_section_index
        self.page_sections_list.clear()
        sections = list((self._page_builder_model or {}).get("sections") or [])
        for index, section in enumerate(sections):
            label = str(section.get("label") or section.get("id") or f"Section {index+1}")
            items = section.get('items') if section.get('items') is not None else (section.get('data') or {}).get('items', [])
            docs = section.get('document_ids') if section.get('document_ids') is not None else (section.get('data') or {}).get('document_ids', [])
            if str(section.get("type") or "") == 'card_grid':
                label += f" ({len(list(items or []))} cards)"
            elif str(section.get("type") or "") == 'document_list':
                label += f" ({len(list(docs or []))} docs)"
            block_type = str(section.get("type") or "")
            state = []
            if section.get("locked"):
                state.append("System")
            state.append("Visible" if section.get("visible", True) else "Hidden")
            visible_icon = "●" if section.get("visible", True) else "○"
            item = QTreeWidgetItem([f"{visible_icon} {label}", friendly_block_name(block_type) if block_type else block_type, " · ".join(state)])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            self.page_sections_list.addTopLevelItem(item)
        if sections:
            target = 0 if select_first or current_index < 0 or current_index >= len(sections) else current_index
            self._current_page_section_index = target
            item = self.page_sections_list.topLevelItem(target)
            if item is not None:
                self.page_sections_list.setCurrentItem(item)
        else:
            self._current_page_section_index = -1
            self.render_page_section_editor()

    def current_page_section(self) -> dict[str, Any] | None:
        sections = list((self._page_builder_model or {}).get("sections") or [])
        if self._current_page_section_index < 0 or self._current_page_section_index >= len(sections):
            return None
        return sections[self._current_page_section_index]

    def on_page_builder_header_changed(self) -> None:
        if self._suspend_page_builder_form or not self._page_builder_model:
            return
        meta = self._page_builder_model.setdefault("meta", {})
        hero = self._page_builder_model.setdefault("hero", {})
        meta["title"] = self.page_meta_title_edit.text().strip()
        meta["description"] = self.page_meta_description_edit.toPlainText().strip()
        meta["og_description"] = self.page_meta_og_description_edit.toPlainText().strip()
        meta["og_image"] = self.page_meta_og_image_edit.text().strip()
        meta["og_image_alt"] = self.page_meta_og_alt_edit.toPlainText().strip()
        hero["eyebrow"] = self.page_hero_eyebrow_edit.text().strip()
        hero["title"] = self.page_hero_title_edit.text().strip()
        hero["lead"] = self.page_hero_lead_edit.toPlainText().strip()
        hero["feature_work_id"] = self.current_page_hero_feature_work_id()
        hero["notes"] = [line.strip() for line in self.page_hero_notes_edit.toPlainText().splitlines() if line.strip()]
        hero["actions"] = [dict(self.page_hero_actions_list.item(i).data(Qt.ItemDataRole.UserRole) or {}) for i in range(self.page_hero_actions_list.count())]
        self.commit_page_builder_change()

    def commit_page_builder_change(self) -> None:
        if not self._page_builder_model or self._suspend_page_builder_form:
            return
        self._page_raw_override = False
        try:
            review = review_page_builder_model(self._current_page_key or "", self._page_builder_model)
        except Exception as exc:
            self.page_review_summary.setText(f"Builder review failed: {exc}")
            return
        self._suspend_page_raw_sync = True
        try:
            self.page_editor.setPlainText(str(review.get("raw_text") or ""))
        finally:
            self._suspend_page_raw_sync = False
        self.render_page_review(review)
        self.update_page_builder_state_label()
        self.update_page_structure_summary()
        self.schedule_editor_autosave("page")

    def update_page_builder_state_label(self) -> None:
        if not self._current_page_key:
            self.page_builder_state.setText("No page selected")
            return
        state = "Modified" if self.is_page_dirty() else "Clean"
        if self._page_raw_override:
            state += " · YAML override"
        self.page_builder_state.setText(state)
        self.page_yaml_mode_label.setText("Raw YAML differs from structured builder" if self._page_raw_override else "Builder and YAML are in sync")

    def update_page_structure_summary(self) -> None:
        if not hasattr(self, "page_structure_summary"):
            return
        model = dict(self._page_builder_model or {})
        meta = dict(model.get("meta") or {})
        hero = dict(model.get("hero") or {})
        sections = list(model.get("sections") or [])
        visible_sections = [section for section in sections if bool(section.get("visible", True))]
        missing: list[str] = []
        if not str(meta.get("title") or "").strip():
            missing.append("meta title")
        if not str(meta.get("description") or "").strip():
            missing.append("meta description")
        if not str(hero.get("title") or "").strip():
            missing.append("hero title")
        if not str(hero.get("lead") or "").strip():
            missing.append("hero lead")
        state = "Healthy" if not missing else "Needs content"
        detail = f"{state} · {len(visible_sections)}/{len(sections)} visible section(s)"
        if missing:
            detail += " · missing " + ", ".join(missing[:4])
        feature = str(hero.get("feature_work_id") or "").strip()
        if feature:
            detail += f" · feature work {feature}"
        self.page_structure_summary.setText("Page summary: " + detail)

    def render_page_review(self, review: dict[str, Any]) -> None:
        issues = list(review.get("issues") or [])
        errors = sum(1 for item in issues if str(item.get("severity") or "") == "error")
        warnings = sum(1 for item in issues if str(item.get("severity") or "") == "warning")
        summary_text = f"{errors} error(s) · {warnings} warning(s) · {len(review.get('diff_lines') or [])} change line(s)"
        self.page_review_summary.setText(summary_text)
        if hasattr(self, "page_live_review_drawer"):
            state = "Blocked" if errors else "Needs review" if warnings else "Healthy"
            self.page_live_review_drawer.setText(f"Page health: {state} · {summary_text}. Use Advanced YAML only for raw-file edits or detailed diff review.")
        if issues:
            lines = []
            for item in issues:
                parts = [str(item.get("severity") or "info").upper(), str(item.get("field") or "<page>"), str(item.get("message") or "")]
                suggestion = str(item.get("suggestion") or "")
                if suggestion:
                    parts.append(f"Suggestion: {suggestion}")
                lines.append(" · ".join(part for part in parts if part))
            self.page_validation_box.setPlainText("\n".join(lines))
        else:
            self.page_validation_box.setPlainText("No page-level validation issues detected.")
        diff_lines = list(review.get("diff_lines") or [])
        self.page_diff_box.setPlainText("\n".join(diff_lines) if diff_lines else "No unsaved content changes relative to the loaded file.")
        self.update_page_structure_summary()

    def _on_page_builder_tab_changed(self, index: int) -> None:
        previous = getattr(self, "_last_page_builder_tab_index", index)
        raw_index = 1
        if previous == raw_index and index != raw_index and self._current_page_key and self._page_raw_override:
            try:
                review = review_page_yaml_text(self._current_page_key, self.page_editor.toPlainText())
                self._page_builder_model = dict(review.get("model") or {})
                self.render_page_builder_from_model(select_first_section=True)
                self.render_page_review(review)
            except Exception as exc:
                self.page_review_summary.setText(f"Raw YAML cannot sync: {exc}")
                with signals_blocked(self.page_builder_tabs):
                    self.page_builder_tabs.setCurrentIndex(raw_index)
                self._last_page_builder_tab_index = raw_index
                return
        self._last_page_builder_tab_index = index

    def validate_current_page_builder(self) -> None:
        if not self._current_page_key:
            return
        try:
            review = review_page_yaml_text(self._current_page_key, self.page_editor.toPlainText()) if self._page_raw_override else review_page_builder_model(self._current_page_key, self._page_builder_model or {})
        except Exception as exc:
            self._critical_modal("Page validation failed", str(exc), target_scope="page", target_id=self._current_page_key)
            return
        self.render_page_review(review)
        if hasattr(self, "page_advanced_yaml_btn") and self.page_advanced_yaml_btn.isChecked():
            self.page_builder_tabs.setCurrentIndex(2)
        self.status_message(f"Validated page: {self._current_page_key}")

    def on_page_raw_text_changed(self) -> None:
        if self._suspend_page_raw_sync or not self._current_page_key:
            return
        self._page_raw_override = True
        try:
            review = review_page_yaml_text(self._current_page_key, self.page_editor.toPlainText())
        except Exception as exc:
            self.page_review_summary.setText(f"Raw YAML not yet valid: {exc}")
            self.page_validation_box.setPlainText(str(exc))
            self.page_diff_box.setPlainText("Diff preview unavailable until the YAML parses correctly.")
            self.update_page_builder_state_label()
            return
        self.render_page_review(review)
        self.update_page_builder_state_label()

    def apply_page_yaml_to_builder(self) -> None:
        if not self._current_page_key:
            return
        try:
            review = review_page_yaml_text(self._current_page_key, self.page_editor.toPlainText())
        except Exception as exc:
            self._critical_modal("Apply YAML failed", str(exc), target_scope="page", target_id=self._current_page_key)
            return
        self._page_builder_model = dict(review.get("model") or {})
        self._page_raw_override = False
        self.render_page_builder_from_model(select_first_section=True)
        self.render_page_review(review)
        self.status_message(f"Applied raw YAML into builder for page: {self._current_page_key}")

    def format_current_page_yaml(self) -> None:
        if not self._current_page_key:
            return
        try:
            review = review_page_yaml_text(self._current_page_key, self.page_editor.toPlainText())
        except Exception as exc:
            self._critical_modal("Format YAML failed", str(exc), target_scope="page", target_id=self._current_page_key)
            return
        self._suspend_page_raw_sync = True
        try:
            self.page_editor.setPlainText(str(review.get("raw_text") or ""))
        finally:
            self._suspend_page_raw_sync = False
        self._page_raw_override = True
        self.render_page_review(review)
        self.update_page_builder_state_label()

    def copy_page_yaml(self) -> None:
        QApplication.clipboard().setText(self.page_editor.toPlainText())
        self.status_message("YAML copied to clipboard")

    def restore_current_page_last_valid(self) -> None:
        if not self._current_page_key:
            return
        if QMessageBox.question(self, "Restore last valid page YAML", f"Restore the last validated YAML version for page '{self._current_page_key}'? Unsaved editor text will be replaced.") != QMessageBox.StandardButton.Yes:
            return
        try:
            text = restore_last_valid_page_yaml(self._current_page_key)
        except Exception as exc:
            self._critical_modal("Restore last valid page failed", str(exc), target_scope="page", target_id=self._current_page_key)
            return
        self._suspend_page_raw_sync = True
        try:
            self.page_editor.setPlainText(text)
        finally:
            self._suspend_page_raw_sync = False
        self.select_page(self._current_page_key, silent=True)
        self._notify_nonblocking("success", "Restored last valid page YAML", self._current_page_key, target_scope="page", target_id=self._current_page_key)

    def _page_save_preview_allows_commit(self, review: dict[str, Any], *, raw: bool) -> bool:
        issues = list(review.get("issues") or [])
        errors = [item for item in issues if str(item.get("severity") or "").lower() == "error"]
        self.render_page_review(review)
        if errors:
            self._critical_modal("Page save blocked", "\n".join(f"- {row.get('field') or '<page>'}: {row.get('message') or ''}" for row in errors[:20]), target_scope="page", target_id=self._current_page_key)
            return False
        diff_lines = list(review.get("diff_lines") or [])
        if raw and diff_lines:
            preview = "\n".join(diff_lines[:70])
            confirm = QMessageBox.question(self, "Save raw page YAML", f"Validated raw YAML has {len(diff_lines)} diff line(s).\n\n{preview}\n\nSave this page YAML?")
            return confirm == QMessageBox.StandardButton.Yes
        return True

    def on_page_section_selected(self) -> None:
        item = self.page_sections_list.currentItem()
        self._current_page_section_index = int(item.data(0, Qt.ItemDataRole.UserRole)) if item is not None else -1
        self.render_page_section_editor()

    def clear_page_section_form(self) -> None:
        while self.page_section_form_layout.count():
            row = self.page_section_form_layout.takeAt(0)
            widget = row.widget()
            if widget is not None:
                widget.deleteLater()
            else:
                child_layout = row.layout()
                if child_layout is not None:
                    while child_layout.count():
                        item = child_layout.takeAt(0)
                        if item.widget() is not None:
                            item.widget().deleteLater()
        self.page_section_status.setText("Select a section to edit its fields.")

    def render_page_section_editor(self) -> None:
        self.clear_page_section_form()
        section = self.current_page_section()
        if not section:
            return
        spec = block_spec(str(section.get("type") or "rich_text"))
        self.page_section_status.setText(spec.description)
        self._suspend_page_builder_form = True
        try:
            id_edit = QLineEdit(str(section.get("id") or "")); self.page_section_form_layout.addRow("Section id", id_edit)
            label_edit = QLineEdit(str(section.get("label") or "")); self.page_section_form_layout.addRow("Label", label_edit)
            visible_check = QCheckBox("Visible in public page"); visible_check.setChecked(bool(section.get("visible", True))); self.page_section_form_layout.addRow("State", visible_check)
            type_label = QLabel(f"{friendly_block_name(str(section.get('type') or ''))} · {str(section.get('type') or '')}")
            self.page_section_form_layout.addRow("Block type", type_label)
            if bool(section.get("locked")):
                id_edit.setDisabled(True)
                visible_check.setDisabled(True)
            id_edit.textChanged.connect(lambda _v=None: self.on_page_section_core_changed(id_edit, label_edit, visible_check))
            label_edit.textChanged.connect(lambda _v=None: self.on_page_section_core_changed(id_edit, label_edit, visible_check))
            visible_check.toggled.connect(lambda _state=None: self.on_page_section_core_changed(id_edit, label_edit, visible_check))
            for field in spec.fields:
                self.page_section_form_layout.addRow(field.label, self.create_page_section_field_editor(field, section))
        finally:
            self._suspend_page_builder_form = False

    def on_page_section_core_changed(self, id_edit: QLineEdit, label_edit: QLineEdit, visible_check: QCheckBox) -> None:
        if self._suspend_page_builder_form:
            return
        section = self.current_page_section()
        if not section:
            return
        if not section.get("locked"):
            section["id"] = id_edit.text().strip()
            section["visible"] = bool(visible_check.isChecked())
        section["label"] = label_edit.text().strip()
        self.refresh_page_sections_list(select_first=False)
        self.commit_page_builder_change()

    def create_page_section_field_editor(self, field, section: dict[str, Any]) -> QWidget:
        current = section.get(field.key)
        if current is None and isinstance(section.get("data"), dict):
            current = section.get("data", {}).get(field.key)
        editor_kind = str(field.editor)
        if editor_kind == "entry":
            widget = QLineEdit(str(current or ""))
            widget.textChanged.connect(lambda _v=None, key=field.key, w=widget: self.update_page_section_scalar(key, w.text()))
            return widget
        if editor_kind == "textarea":
            widget = QPlainTextEdit(str(current or ""))
            widget.setFixedHeight(max(70, int(getattr(field, 'rows', 4) or 4) * 26))
            widget.textChanged.connect(lambda key=field.key, w=widget: self.update_page_section_scalar(key, w.toPlainText()))
            return widget
        if editor_kind == "combobox":
            widget = QComboBox(); widget.setEditable(True)
            widget.addItem("")
            widget.addItems([str(item.get("id") or "") for item in load_work_entries() if str(item.get("id") or "")])
            widget.setCurrentText(str(current or ""))
            widget.currentTextChanged.connect(lambda value, key=field.key: self.update_page_section_scalar(key, value))
            return widget
        if editor_kind in {"reorder_list", "token_list", "series_picker", "work_picker", "document_picker"}:
            if editor_kind == "series_picker":
                options = available_series_slugs()
            elif editor_kind == "work_picker":
                options = [str(item.get("id") or "") for item in load_work_entries() if str(item.get("id") or "")]
            elif editor_kind == "document_picker":
                return self.create_document_picker_editor(field.key, list(current or []))
            else:
                options = []
            return self.create_string_list_editor(field.key, list(current or []), options=options)
        if editor_kind == "action_list":
            return self.create_dict_list_editor(field.key, list(current or []), kind="action")
        if editor_kind == "metric_list":
            return self.create_dict_list_editor(field.key, list(current or []), kind="metric")
        if editor_kind == "card_list":
            return self.create_dict_list_editor(field.key, list(current or []), kind="card")
        if editor_kind == "checkbox":
            widget = QCheckBox(); widget.setChecked(bool(current))
            widget.toggled.connect(lambda state, key=field.key: self.update_page_section_scalar(key, bool(state)))
            return widget
        widget = QLabel(f"Unsupported editor: {editor_kind}")
        return widget

    def update_page_section_scalar(self, key: str, value: Any) -> None:
        if self._suspend_page_builder_form:
            return
        section = self.current_page_section()
        if not section:
            return
        section[key] = value
        if isinstance(section.get("data"), dict):
            section.get("data", {}).pop(key, None)
        self.commit_page_builder_change()

    def create_string_list_editor(self, key: str, values: list[str], *, options: list[str] | None = None, on_change: Callable[[list[str]], None] | None = None) -> QWidget:
        shell = QWidget(); layout = QVBoxLayout(shell); layout.setContentsMargins(0, 0, 0, 0)
        add_row = QHBoxLayout()
        combo = QComboBox(); combo.setEditable(True); combo.addItem("")
        for value in options or []:
            if value:
                combo.addItem(value)
        add_btn = QPushButton("Add")
        add_row.addWidget(combo, 1)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)
        list_widget = QListWidget()
        for value in values:
            list_widget.addItem(str(value))
        layout.addWidget(list_widget)
        btns = QHBoxLayout()
        remove_btn = QPushButton("Remove")
        edit_btn = QPushButton("Edit")
        duplicate_btn = QPushButton("Duplicate")
        up_btn = QPushButton("↑")
        down_btn = QPushButton("↓")
        manual_btn = QPushButton("New item")
        for btn in (remove_btn, edit_btn, duplicate_btn, up_btn, down_btn, manual_btn):
            btns.addWidget(btn)
        btns.addStretch(1)
        layout.addLayout(btns)

        def commit() -> None:
            payload = [list_widget.item(i).text() for i in range(list_widget.count())]
            if on_change:
                on_change(payload)
            else:
                self.update_page_section_scalar(key, payload)

        def add_value(value: str) -> None:
            value = value.strip()
            if not value:
                return
            list_widget.addItem(value)
            combo.setCurrentText("")
            commit()

        add_btn.clicked.connect(lambda: add_value(combo.currentText()))
        manual_btn.clicked.connect(lambda: add_value(QInputDialog.getText(self, "Add item", "Value")[0]))

        def edit_current() -> None:
            row = list_widget.currentRow()
            if row < 0:
                return
            current = list_widget.item(row).text()
            value, ok = QInputDialog.getText(self, "Edit item", "Value", text=current)
            if ok and value.strip():
                list_widget.item(row).setText(value.strip())
                commit()

        def duplicate_current() -> None:
            row = list_widget.currentRow()
            if row < 0:
                return
            value = list_widget.item(row).text().strip()
            if value:
                list_widget.insertItem(row + 1, value)
                list_widget.setCurrentRow(row + 1)
                commit()

        edit_btn.clicked.connect(edit_current)
        duplicate_btn.clicked.connect(duplicate_current)
        list_widget.itemDoubleClicked.connect(lambda _item: edit_current())
        remove_btn.clicked.connect(lambda: (list_widget.takeItem(list_widget.currentRow()), commit()) if list_widget.currentRow() >= 0 else None)

        def move(delta: int) -> None:
            row = list_widget.currentRow()
            target = row + delta
            if row < 0 or target < 0 or target >= list_widget.count():
                return
            item = list_widget.takeItem(row)
            list_widget.insertItem(target, item)
            list_widget.setCurrentRow(target)
            commit()

        up_btn.clicked.connect(lambda: move(-1))
        down_btn.clicked.connect(lambda: move(1))
        return shell

    def _resource_summary(self, row: dict[str, Any]) -> str:
        ident = str(row.get('id') or '').strip()
        title = str(row.get('title') or '').strip()
        kind = str(row.get('kind') or '').strip()
        file_value = str(row.get('file') or '').strip()
        tail = []
        if kind:
            tail.append(kind)
        if file_value:
            tail.append(Path(file_value).name)
        suffix = f" · {' · '.join(tail)}" if tail else ''
        base = title or ident or 'Document'
        return f"{base}{suffix}"

    def _save_document_library_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        saved = save_resource_documents(rows)
        self.push_notification('success', 'Document library updated', f"{len(saved)} document record(s) available.", target_scope='authority', target_id='resources')
        self.status_message('Document library updated')
        if getattr(self, '_current_authority_key', None) == 'resources':
            self.select_authority('resources', silent=True)
        return saved

    def create_document_picker_editor(self, key: str, values: list[str]) -> QWidget:
        shell = QWidget()
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        add_row = QHBoxLayout()
        combo = QComboBox(); combo.setEditable(True)
        add_btn = QPushButton('Add existing')
        refresh_btn = QPushButton('Refresh')
        add_row.addWidget(combo, 1)
        add_row.addWidget(add_btn)
        add_row.addWidget(refresh_btn)
        layout.addLayout(add_row)
        list_widget = QListWidget()
        detail = QPlainTextEdit(); detail.setReadOnly(True); detail.setFixedHeight(90)
        layout.addWidget(list_widget)
        layout.addWidget(detail)
        btns = QHBoxLayout()
        new_btn = QPushButton('New doc')
        edit_btn = QPushButton('Edit doc')
        duplicate_btn = QPushButton('Duplicate')
        remove_btn = QPushButton('Remove from page')
        delete_btn = QPushButton('Delete doc')
        up_btn = QPushButton('↑')
        down_btn = QPushButton('↓')
        for btn in (new_btn, edit_btn, duplicate_btn, remove_btn, delete_btn, up_btn, down_btn):
            btns.addWidget(btn)
        btns.addStretch(1)
        layout.addLayout(btns)

        selected_ids = [str(item).strip() for item in values if str(item).strip()]

        def catalog() -> list[dict[str, Any]]:
            return load_resource_documents()

        def catalog_map(rows: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
            rows = rows if rows is not None else catalog()
            return {str(item.get('id') or '').strip(): dict(item) for item in rows if str(item.get('id') or '').strip()}

        def refresh_combo(rows: list[dict[str, Any]] | None = None) -> None:
            rows = rows if rows is not None else catalog()
            current = combo.currentText().strip()
            with signals_blocked(combo):
                combo.clear(); combo.addItem('')
                for row in rows:
                    ident = str(row.get('id') or '').strip()
                    if not ident:
                        continue
                    combo.addItem(ident)
                combo.setCurrentText(current)

        def render_selection(rows: list[dict[str, Any]] | None = None) -> None:
            rows = rows if rows is not None else catalog()
            cmap = catalog_map(rows)
            current_id = ''
            if list_widget.currentItem() is not None:
                current_id = str(list_widget.currentItem().data(Qt.ItemDataRole.UserRole) or '')
            list_widget.clear()
            for ident in selected_ids:
                row = cmap.get(ident)
                label = self._resource_summary(row) if row else f"{ident} · missing from library"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, ident)
                list_widget.addItem(item)
            for i in range(list_widget.count()):
                if str(list_widget.item(i).data(Qt.ItemDataRole.UserRole) or '') == current_id:
                    list_widget.setCurrentRow(i)
                    break
            update_detail()

        def commit() -> None:
            self.update_page_section_scalar(key, list(selected_ids))

        def update_detail() -> None:
            item = list_widget.currentItem()
            if item is None:
                detail.setPlainText('Select a linked document to inspect or edit it.')
                return
            ident = str(item.data(Qt.ItemDataRole.UserRole) or '')
            row = catalog_map().get(ident)
            if not row:
                detail.setPlainText(f'{ident}\nMissing from document library. Add it back or remove it from the page selection.')
                return
            lines = [
                f"ID: {ident}",
                f"Title: {row.get('title') or ''}",
                f"Kind: {row.get('kind') or ''}",
                f"File: {row.get('file') or ''}",
                f"Audience: {row.get('audience') or ''}",
                '',
                str(row.get('description') or ''),
            ]
            detail.setPlainText('\n'.join(lines).strip())

        def add_existing() -> None:
            ident = combo.currentText().strip()
            if ident and ident not in selected_ids:
                selected_ids.append(ident)
                render_selection()
                commit()

        def move(delta: int) -> None:
            row = list_widget.currentRow()
            target = row + delta
            if row < 0 or target < 0 or target >= len(selected_ids):
                return
            selected_ids[row], selected_ids[target] = selected_ids[target], selected_ids[row]
            render_selection()
            list_widget.setCurrentRow(target)
            commit()

        def remove_selected() -> None:
            row = list_widget.currentRow()
            if row < 0:
                return
            selected_ids.pop(row)
            render_selection()
            commit()

        def upsert_document(initial: dict[str, Any] | None = None, *, duplicate: bool = False) -> str | None:
            seed = dict(initial or {})
            if duplicate:
                base_id = str(seed.get('id') or 'document').strip() or 'document'
                seed['id'] = f"{base_id}-copy"
                if seed.get('title'):
                    seed['title'] = f"{seed.get('title')} Copy"
            dialog = ResourceItemDialog(self, seed)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            payload = dialog.value()
            ident = str(payload.get('id') or '').strip()
            if not ident or not str(payload.get('title') or '').strip() or not str(payload.get('file') or '').strip():
                QMessageBox.information(self, 'Incomplete document', 'Document ID, title, and file are required.')
                return None
            rows = catalog()
            replaced = False
            for idx, row in enumerate(rows):
                if str(row.get('id') or '').strip() == ident:
                    rows[idx] = payload
                    replaced = True
                    break
            if not replaced:
                rows.append(payload)
            self._save_document_library_rows(rows)
            refresh_combo(rows)
            render_selection(rows)
            return ident

        def edit_selected_document(*, duplicate: bool = False) -> None:
            item = list_widget.currentItem()
            if item is None:
                return
            ident = str(item.data(Qt.ItemDataRole.UserRole) or '')
            row = catalog_map().get(ident)
            if not row:
                QMessageBox.warning(self, 'Document missing', f'Document {ident} is no longer in the library.')
                return
            new_id = upsert_document(row, duplicate=duplicate)
            if not new_id:
                return
            if duplicate and new_id not in selected_ids:
                selected_ids.append(new_id)
                render_selection()
                commit()
            elif new_id != ident:
                selected_ids[:] = [new_id if item_id == ident else item_id for item_id in selected_ids]
                render_selection()
                commit()

        def new_document() -> None:
            new_id = upsert_document({'audience': 'public'})
            if new_id and new_id not in selected_ids:
                selected_ids.append(new_id)
                render_selection()
                commit()

        def delete_document() -> None:
            item = list_widget.currentItem()
            if item is None:
                return
            ident = str(item.data(Qt.ItemDataRole.UserRole) or '')
            confirm = QMessageBox.question(self, 'Delete document', f'Delete document {ident} from the shared library?')
            if confirm != QMessageBox.StandardButton.Yes:
                return
            rows = [row for row in catalog() if str(row.get('id') or '').strip() != ident]
            self._save_document_library_rows(rows)
            while ident in selected_ids:
                selected_ids.remove(ident)
            refresh_combo(rows)
            render_selection(rows)
            commit()

        add_btn.clicked.connect(add_existing)
        refresh_btn.clicked.connect(lambda: (refresh_combo(), render_selection()))
        new_btn.clicked.connect(new_document)
        edit_btn.clicked.connect(lambda: edit_selected_document(duplicate=False))
        duplicate_btn.clicked.connect(lambda: edit_selected_document(duplicate=True))
        remove_btn.clicked.connect(remove_selected)
        delete_btn.clicked.connect(delete_document)
        up_btn.clicked.connect(lambda: move(-1))
        down_btn.clicked.connect(lambda: move(1))
        list_widget.itemSelectionChanged.connect(update_detail)
        list_widget.itemDoubleClicked.connect(lambda _item: edit_selected_document(duplicate=False))

        refresh_combo()
        render_selection()
        return shell

    def create_dict_list_editor(self, key: str, rows: list[dict[str, Any]], *, kind: str, on_change: Callable[[list[dict[str, Any]]], None] | None = None) -> QWidget:
        shell = QWidget(); layout = QVBoxLayout(shell); layout.setContentsMargins(0, 0, 0, 0)
        list_widget = QListWidget(); layout.addWidget(list_widget)

        def summary(row: dict[str, Any]) -> str:
            if kind == "action":
                label = str(row.get('label') or 'Action')
                href = str(row.get('href') or '')
                style = str(row.get('style') or '')
                return f"{label} → {href}{(' · ' + style) if style else ''}".strip()
            if kind == "metric":
                suffix = str(row.get('suffix') or '')
                return f"{row.get('label', 'Metric')}: {row.get('value', '')}{suffix}"
            if kind == "navigation":
                return f"{row.get('label', 'Nav')} → {row.get('href', '')}"
            if kind == "resource":
                return f"{row.get('title', 'Document')} · {row.get('kind', '')}"
            return f"{row.get('title', 'Card')}"

        def render(items: list[dict[str, Any]]) -> None:
            list_widget.clear()
            for row in items:
                item = QListWidgetItem(summary(row))
                item.setData(Qt.ItemDataRole.UserRole, dict(row))
                list_widget.addItem(item)

        render(rows)
        btns = QHBoxLayout()
        add_btn = QPushButton("Add")
        edit_btn = QPushButton("Edit")
        duplicate_btn = QPushButton("Duplicate")
        json_btn = QPushButton("JSON")
        remove_btn = QPushButton("Remove")
        up_btn = QPushButton("↑")
        down_btn = QPushButton("↓")
        for btn in (add_btn, edit_btn, duplicate_btn, json_btn, remove_btn, up_btn, down_btn):
            btns.addWidget(btn)
        btns.addStretch(1)
        layout.addLayout(btns)

        def items() -> list[dict[str, Any]]:
            return [dict(list_widget.item(i).data(Qt.ItemDataRole.UserRole) or {}) for i in range(list_widget.count())]

        def commit() -> None:
            payload = items()
            if on_change:
                on_change(payload)
            else:
                self.update_page_section_scalar(key, payload)

        def dialog_for(current: dict[str, Any]):
            if kind == 'action':
                return ActionItemDialog(self, current, title='Action')
            if kind == 'metric':
                return MetricItemDialog(self, current)
            if kind == 'navigation':
                return NavigationItemDialog(self, current)
            if kind == 'resource':
                return ResourceItemDialog(self, current)
            return CardItemDialog(self, current)

        def validate_payload(payload: dict[str, Any]) -> bool:
            if kind == 'action':
                return bool(payload.get('label')) and bool(payload.get('href'))
            if kind == 'metric':
                return bool(payload.get('label')) and bool(payload.get('value'))
            if kind == 'navigation':
                return bool(payload.get('label')) and bool(payload.get('href'))
            if kind == 'resource':
                return bool(payload.get('id')) and bool(payload.get('title')) and bool(payload.get('file'))
            return bool(payload.get('title'))

        def open_json_editor() -> None:
            row = list_widget.currentRow()
            if row < 0:
                return
            current = dict(list_widget.item(row).data(Qt.ItemDataRole.UserRole) or {})
            dialog = JsonObjectDialog(self, current, title='Edit item JSON', help_text='Use this when the structured form does not expose a field you need.')
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                payload = dialog.value()
            except Exception as exc:
                QMessageBox.critical(self, 'Invalid JSON', str(exc))
                return
            if not validate_payload(payload):
                QMessageBox.information(self, 'Incomplete item', 'Required fields are missing for this item type.')
                return
            item = QListWidgetItem(summary(payload))
            item.setData(Qt.ItemDataRole.UserRole, payload)
            list_widget.takeItem(row)
            list_widget.insertItem(row, item)
            list_widget.setCurrentRow(row)
            commit()

        def edit_item(mode: str) -> None:
            row = list_widget.currentRow()
            current = dict(list_widget.item(row).data(Qt.ItemDataRole.UserRole) or {}) if row >= 0 else {}
            if mode == 'remove':
                if row >= 0:
                    list_widget.takeItem(row)
                    commit()
                return
            if mode == 'duplicate':
                if row < 0:
                    return
                clone = json.loads(json.dumps(current))
                item = QListWidgetItem(summary(clone))
                item.setData(Qt.ItemDataRole.UserRole, clone)
                list_widget.insertItem(row + 1, item)
                list_widget.setCurrentRow(row + 1)
                commit()
                return
            if mode in {'up', 'down'}:
                target = row + (-1 if mode == 'up' else 1)
                if row < 0 or target < 0 or target >= list_widget.count():
                    return
                item = list_widget.takeItem(row)
                list_widget.insertItem(target, item)
                list_widget.setCurrentRow(target)
                commit()
                return
            if mode == 'edit' and row < 0:
                return
            dialog = dialog_for(current)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                payload = dialog.value()
            except Exception as exc:
                QMessageBox.critical(self, 'Invalid item', str(exc))
                return
            if not validate_payload(payload):
                QMessageBox.information(self, 'Incomplete item', 'Required fields are missing for this item type.')
                return
            item = QListWidgetItem(summary(payload))
            item.setData(Qt.ItemDataRole.UserRole, payload)
            if mode == 'add':
                list_widget.addItem(item)
                list_widget.setCurrentItem(item)
            else:
                list_widget.takeItem(row)
                list_widget.insertItem(row, item)
                list_widget.setCurrentRow(row)
            commit()

        add_btn.clicked.connect(lambda: edit_item('add'))
        edit_btn.clicked.connect(lambda: edit_item('edit'))
        duplicate_btn.clicked.connect(lambda: edit_item('duplicate'))
        json_btn.clicked.connect(open_json_editor)
        remove_btn.clicked.connect(lambda: edit_item('remove'))
        up_btn.clicked.connect(lambda: edit_item('up'))
        down_btn.clicked.connect(lambda: edit_item('down'))
        list_widget.itemDoubleClicked.connect(lambda _item: edit_item('edit'))
        return shell

    def edit_page_action_item(self, scope: str, *, mode: str) -> None:
        if scope != "hero" or not self._page_builder_model:
            return
        hero = self._page_builder_model.setdefault("hero", {})
        actions = list(hero.get("actions") or [])
        row = self.page_hero_actions_list.currentRow()
        current = dict(self.page_hero_actions_list.item(row).data(Qt.ItemDataRole.UserRole) or {}) if row >= 0 else {}
        if mode == "remove":
            if row >= 0:
                actions.pop(row)
        elif mode in {"up", "down"}:
            target = row + (-1 if mode == "up" else 1)
            if row < 0 or target < 0 or target >= len(actions):
                return
            actions[row], actions[target] = actions[target], actions[row]
            row = target
        else:
            dialog = ActionItemDialog(self, current, title="Hero action")
            if mode == "edit" and row < 0:
                return
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            payload = dialog.value()
            if not payload.get("label") or not payload.get("href"):
                return
            if mode == "add":
                actions.append(payload)
                row = len(actions) - 1
            else:
                actions[row] = payload
        hero["actions"] = actions
        self.render_page_action_list(self.page_hero_actions_list, actions)
        if row >= 0 and row < self.page_hero_actions_list.count():
            self.page_hero_actions_list.setCurrentRow(row)
        self.commit_page_builder_change()

    def add_page_section(self) -> None:
        if not self._current_page_key or not self._page_builder_model:
            return
        allowed = list(allowed_block_types(self._current_page_key))
        labels = [f"{friendly_block_name(block_type)} · {block_type}" for block_type in allowed]
        choice, ok = QInputDialog.getItem(self, "Add section", "Block type", labels, 0, False)
        if not ok or not choice:
            return
        block_type = allowed[labels.index(choice)]
        existing_ids = {str(section.get('id') or '') for section in (self._page_builder_model.get('sections') or [])}
        section = default_section(block_type, seed=next_section_id(existing_ids, block_type.replace('_', '-'))).to_dict()
        self._page_builder_model.setdefault("sections", []).append(section)
        self._current_page_section_index = len(self._page_builder_model["sections"]) - 1
        self.refresh_page_sections_list(select_first=False)
        self.commit_page_builder_change()

    def duplicate_page_section(self) -> None:
        section = self.current_page_section()
        if not section or not self._page_builder_model:
            return
        clone = json.loads(json.dumps(section))
        existing_ids = {str(item.get('id') or '') for item in self._page_builder_model.get('sections') or []}
        clone['id'] = next_section_id(existing_ids, str(section.get('id') or 'section'))
        clone['locked'] = False
        self._page_builder_model.setdefault('sections', []).insert(self._current_page_section_index + 1, clone)
        self._current_page_section_index += 1
        self.refresh_page_sections_list(select_first=False)
        self.commit_page_builder_change()

    def remove_page_section(self) -> None:
        section = self.current_page_section()
        if not section or not self._page_builder_model:
            return
        if section.get('locked'):
            QMessageBox.information(self, 'Locked section', 'This system section cannot be removed.')
            return
        self._page_builder_model.setdefault('sections', []).pop(self._current_page_section_index)
        self._current_page_section_index = max(0, self._current_page_section_index - 1)
        self.refresh_page_sections_list(select_first=False)
        self.commit_page_builder_change()

    def toggle_page_section_visibility(self) -> None:
        section = self.current_page_section()
        if not section or section.get('locked'):
            return
        section['visible'] = not bool(section.get('visible', True))
        self.refresh_page_sections_list(select_first=False)
        self.commit_page_builder_change()

    def move_page_section(self, direction: int) -> None:
        if not self._page_builder_model:
            return
        sections = self._page_builder_model.setdefault('sections', [])
        row = self._current_page_section_index
        target = row + direction
        if row < 0 or target < 0 or target >= len(sections):
            return
        sections[row], sections[target] = sections[target], sections[row]
        self._current_page_section_index = target
        self.refresh_page_sections_list(select_first=False)
        self.commit_page_builder_change()

    def change_page_section_type(self) -> None:
        section = self.current_page_section()
        if not section or not self._current_page_key or not self._page_builder_model:
            return
        if section.get('locked'):
            QMessageBox.information(self, 'Locked section', 'This system section cannot change type.')
            return
        allowed = list(allowed_block_types(self._current_page_key))
        labels = [f"{friendly_block_name(block_type)} · {block_type}" for block_type in allowed]
        current_type = str(section.get('type') or '')
        current_index = allowed.index(current_type) if current_type in allowed else 0
        choice, ok = QInputDialog.getItem(self, 'Change block type', 'Block type', labels, current_index, False)
        if not ok or not choice:
            return
        new_type = allowed[labels.index(choice)]
        if new_type == current_type:
            return
        template = default_section(new_type, seed=str(section.get('id') or new_type.replace('_', '-'))).to_dict()
        preserved = {'id': str(section.get('id') or template.get('id') or ''), 'label': str(section.get('label') or template.get('label') or ''), 'visible': bool(section.get('visible', True)), 'locked': False, 'type': new_type}
        old_data = dict(section.get('data') or {})
        new_data = dict(template.get('data') or {})
        for key in list(new_data.keys()):
            if key in old_data:
                new_data[key] = json.loads(json.dumps(old_data[key]))
        section.clear()
        section.update(preserved)
        section['data'] = new_data
        self.refresh_page_sections_list(select_first=False)
        self.commit_page_builder_change()

    def edit_current_page_section_json(self) -> None:
        section = self.current_page_section()
        if not section:
            return
        dialog = JsonObjectDialog(self, dict(section), title='Edit section JSON', help_text='Use this for full-control editing of any section fields, cards, actions, or nested data.')
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            payload = dialog.value()
        except Exception as exc:
            QMessageBox.critical(self, 'Invalid JSON', str(exc))
            return
        if not isinstance(payload, dict):
            QMessageBox.critical(self, 'Invalid JSON', 'Section JSON must be an object.')
            return
        if section.get('locked'):
            payload['type'] = section.get('type')
            payload['locked'] = True
            payload['id'] = section.get('id')
        else:
            payload.setdefault('type', section.get('type'))
            payload.setdefault('id', section.get('id'))
        payload.setdefault('label', section.get('label'))
        payload.setdefault('visible', section.get('visible', True))
        data = dict(payload)
        ident = str(data.pop('id', '')).strip()
        block_type = str(data.pop('type', section.get('type') or 'rich_text')).strip() or 'rich_text'
        label = str(data.pop('label', ident or block_type)).strip()
        visible = bool(data.pop('visible', True))
        locked = bool(data.pop('locked', section.get('locked', False)))
        section.clear()
        section.update({'id': ident, 'type': block_type, 'label': label, 'visible': visible, 'locked': locked, 'data': data})
        self.refresh_page_sections_list(select_first=False)
        self.commit_page_builder_change()

    def sync_performance_collection_feature_work(self, work_id: str) -> None:
        work_id = str(work_id or "").strip()
        collection_path = ROOT / "content" / "collections" / "performance.yaml"
        if not collection_path.exists():
            return
        try:
            payload = yaml.safe_load(collection_path.read_text(encoding="utf-8")) or {}
            if not isinstance(payload, dict):
                payload = {}
            payload["feature_work_id"] = work_id
            payload["cover_work_id"] = work_id
            collection_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        except Exception as exc:
            self._log_warning(f"Could not sync Performance collection feature work: {exc}")

    def save_current_page(self) -> None:
        if not self._current_page_key:
            return
        before_text = self._loaded_page_text
        try:
            review = review_page_yaml_text(self._current_page_key, self.page_editor.toPlainText()) if self._page_raw_override else review_page_builder_model(self._current_page_key, self._page_builder_model or {})
        except Exception as exc:
            self._critical_modal("Save page failed", str(exc), target_scope="page", target_id=self._current_page_key)
            return
        if not self._page_save_preview_allows_commit(review, raw=bool(self._page_raw_override)):
            return
        try:
            if self._page_raw_override:
                save_page_yaml_text(self._current_page_key, self.page_editor.toPlainText())
            else:
                save_page_builder_model(self._current_page_key, self._page_builder_model or {})
        except Exception as exc:
            self._critical_modal("Save page failed", str(exc), target_scope="page", target_id=self._current_page_key)
            return
        current_key = self._current_page_key
        if current_key == "performance":
            try:
                review_model = dict(review.get("model") or {})
                review_hero = dict(review_model.get("hero") or {})
                self.sync_performance_collection_feature_work(str(review_hero.get("feature_work_id") or ""))
            except Exception as exc:
                self._log_warning(f"Performance collection sync after page save failed: {exc}")
        self.select_page(current_key, silent=True)
        clear_editor_draft("page", current_key)
        self._draft_restore_seen.discard(("page", current_key))
        self._last_draft_hash.pop(("page", current_key), None)
        self.push_notification("success", f"Saved page: {current_key}", "Content Builder page updated.", target_scope="page", target_id=current_key)
        self._reset_autosave_state("page")
        self._show_toast(f"✓ Saved: {current_key}")
        self._store_text_diff("page", before_text, self.page_editor.toPlainText())
        self._mark_saved()
        self.status_message(f"Saved page: {current_key} · diff ready")
        self.refresh_all_context(force=True, scope={"pages", "dashboard", "validation"})

    def reload_current_page(self) -> None:
        if self._current_page_key and self.ensure_page_editor_safe():
            self._draft_restore_seen.discard(("page", self._current_page_key))
            self._last_draft_hash.pop(("page", self._current_page_key), None)
            self.select_page(self._current_page_key)

    # ---------- authority ----------
    def build_authority_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        self.authority_list = QListWidget(); self.authority_list.itemSelectionChanged.connect(self.on_authority_selection_changed)
        layout.addWidget(self.authority_list, 1)

        right = QVBoxLayout()
        header = QHBoxLayout()
        self.authority_breadcrumb = QLabel('Content Authority  ›  No authority file selected')
        self.authority_breadcrumb.setObjectName('breadcrumb')
        header.addWidget(self.authority_breadcrumb, 1)
        self.authority_context = QLabel('No authority file loaded')
        self.authority_context.setObjectName('taskBadge')
        header.addWidget(self.authority_context)
        self.authority_state = QLabel('Clean')
        self.authority_state.setObjectName('taskBadge')
        header.addWidget(self.authority_state)
        self.authority_autosave_status = QLabel('')
        self.authority_autosave_status.setObjectName('autosaveStatus')
        header.addWidget(self.authority_autosave_status)
        header.addStretch(1)
        self.authority_advanced_yaml_btn = QPushButton('Advanced YAML')
        self.authority_advanced_yaml_btn.setCheckable(True)
        self.authority_advanced_yaml_btn.setToolTip('Show raw YAML and detailed diff review for advanced authority edits.')
        self.authority_advanced_yaml_btn.toggled.connect(self.set_authority_advanced_yaml_mode)
        header.addWidget(self.authority_advanced_yaml_btn)
        auth_validate = QPushButton('Validate')
        auth_validate.clicked.connect(self.validate_current_authority_builder)
        auth_save = QPushButton('Save authority document')
        auth_save.clicked.connect(self.save_current_authority)
        auth_reload = QPushButton('Reload')
        auth_reload.clicked.connect(self.reload_current_authority)
        header.addWidget(auth_validate); header.addWidget(auth_save); header.addWidget(auth_reload)
        right.addLayout(header)

        self.authority_tabs = QTabWidget()
        right.addWidget(self.authority_tabs, 1)
        self.authority_live_review_drawer = QLabel('Live authority health will appear after a document loads.')
        self.authority_live_review_drawer.setObjectName('missionStatus')
        self.authority_live_review_drawer.setWordWrap(True)
        right.addWidget(self.authority_live_review_drawer)

        structured_tab = QWidget()
        structured_layout = QVBoxLayout(structured_tab)
        self.authority_builder_hint = QLabel('Structured authority editing for global content, navigation, resources, and release settings.')
        self.authority_builder_hint.setWordWrap(True)
        structured_layout.addWidget(self.authority_builder_hint)
        authority_scroll = QScrollArea(); authority_scroll.setWidgetResizable(True)
        self.authority_form_host = QWidget()
        self.authority_form_layout = QFormLayout(self.authority_form_host)
        self.authority_form_layout.setContentsMargins(12, 12, 12, 12)
        authority_scroll.setWidget(self.authority_form_host)
        structured_layout.addWidget(authority_scroll, 1)
        self.authority_tabs.addTab(structured_tab, 'Structured editor')

        raw_tab = QWidget()
        raw_layout = QVBoxLayout(raw_tab)
        raw_toolbar = QHBoxLayout()
        self.authority_apply_yaml_button = QPushButton('Apply YAML to builder')
        self.authority_apply_yaml_button.clicked.connect(self.apply_authority_yaml_to_builder)
        self.authority_format_yaml_button = QPushButton('Format YAML')
        self.authority_format_yaml_button.clicked.connect(self.format_current_authority_yaml)
        self.authority_copy_yaml_button = QPushButton('Copy YAML')
        self.authority_copy_yaml_button.clicked.connect(self.copy_authority_yaml)
        self.authority_restore_valid_button = QPushButton('Restore last valid')
        self.authority_restore_valid_button.setToolTip('Recover the last authority YAML version that passed validation before a raw save.')
        self.authority_restore_valid_button.clicked.connect(self.restore_current_authority_last_valid)
        raw_toolbar.addWidget(self.authority_apply_yaml_button)
        raw_toolbar.addWidget(self.authority_format_yaml_button)
        raw_toolbar.addWidget(self.authority_copy_yaml_button)
        raw_toolbar.addWidget(self.authority_restore_valid_button)
        raw_toolbar.addStretch(1)
        self.authority_mode_label = QLabel('Builder and YAML are in sync')
        raw_toolbar.addWidget(self.authority_mode_label)
        raw_layout.addLayout(raw_toolbar)
        self.authority_editor = QPlainTextEdit(); raw_layout.addWidget(self.authority_editor, 1)
        self.authority_tabs.addTab(raw_tab, 'Raw YAML')

        review_tab = QWidget()
        review_layout = QVBoxLayout(review_tab)
        self.authority_review_summary = QLabel('Validation and diff review will appear here.')
        self.authority_review_summary.setWordWrap(True)
        review_layout.addWidget(self.authority_review_summary)
        review_split = QSplitter(Qt.Orientation.Vertical)
        review_split.setObjectName("authority-review-splitter")
        self.authority_validation_box = QPlainTextEdit(); self.authority_validation_box.setReadOnly(True)
        self.authority_diff_box = QPlainTextEdit(); self.authority_diff_box.setReadOnly(True)
        review_split.addWidget(self.authority_validation_box)
        review_split.addWidget(self.authority_diff_box)
        review_split.setSizes([220, 280])
        review_layout.addWidget(review_split, 1)
        self.authority_tabs.addTab(review_tab, 'Validation & changes')
        try:
            self.authority_tabs.setTabVisible(1, False)
            self.authority_tabs.setTabVisible(2, False)
        except Exception as exc:
            self._log_warning(f"Authority advanced-tab setup failed: {exc}")

        wrap = QWidget(); wrap.setLayout(right)
        layout.addWidget(wrap, 3)
        self.authority_editor.textChanged.connect(lambda: self.schedule_editor_autosave('authority'))
        self.authority_editor.textChanged.connect(self.on_authority_raw_text_changed)
        return tab

    def set_authority_advanced_yaml_mode(self, enabled: bool) -> None:
        if not hasattr(self, 'authority_tabs'):
            return
        try:
            self.authority_tabs.setTabVisible(1, bool(enabled))
            self.authority_tabs.setTabVisible(2, bool(enabled))
        except Exception as exc:
            self._log_warning(f"Authority advanced-tab toggle failed: {exc}")
        if not enabled and self.authority_tabs.currentIndex() in {1, 2}:
            self.authority_tabs.setCurrentIndex(0)
        self.status_message('Advanced authority YAML tools shown' if enabled else 'Advanced authority YAML tools hidden')

    def refresh_authority_list(self) -> None:
        current = self._current_authority_key
        self.authority_list.clear()
        for key in AUTHORITY_FILES:
            item = QListWidgetItem(key)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.authority_list.addItem(item)
        if current:
            self.select_authority(current, silent=True)

    def on_authority_selection_changed(self) -> None:
        items = self.authority_list.selectedItems()
        if not items:
            return
        target = str(items[0].data(Qt.ItemDataRole.UserRole) or '')
        if target == self._current_authority_key:
            return
        if not self.ensure_authority_editor_safe():
            self._restore_authority_selection()
            return
        self.select_authority(target)

    def clear_authority_form(self) -> None:
        while self.authority_form_layout.count():
            row = self.authority_form_layout.takeAt(0)
            if row is None:
                continue
            widget = row.widget()
            if widget is not None:
                widget.deleteLater()
                continue
            child_layout = row.layout()
            if child_layout is not None:
                while child_layout.count():
                    child = child_layout.takeAt(0)
                    child_widget = child.widget()
                    if child_widget is not None:
                        child_widget.deleteLater()

    def render_authority_builder(self) -> None:
        self.clear_authority_form()
        key = self._current_authority_key
        payload = dict(self._authority_model or {})
        self.authority_context.setText(key or 'No authority file loaded')
        self._suspend_authority_form = True
        try:
            if not key:
                return
            if key == 'site':
                self.authority_form_layout.addRow('Site name', self._authority_line('name', payload.get('name')))
                self.authority_form_layout.addRow('Short description', self._authority_text('short_description', payload.get('short_description'), rows=3))
                self.authority_form_layout.addRow('Description', self._authority_text('description', payload.get('description'), rows=5))
                self.authority_form_layout.addRow('OG image', self._authority_line('og_image', payload.get('og_image')))
                self.authority_form_layout.addRow('Site URL', self._authority_line('site_url', payload.get('site_url')))
                self.authority_form_layout.addRow('Display URL', self._authority_line('display_url', payload.get('display_url')))
                self.authority_form_layout.addRow('Environment', self._authority_line('environment', payload.get('environment')))
                allow_indexing = QCheckBox('Allow indexing'); allow_indexing.setChecked(bool(payload.get('allow_indexing', True))); allow_indexing.toggled.connect(lambda state: self.set_authority_value('allow_indexing', bool(state))); self.authority_form_layout.addRow('Indexing', allow_indexing)
                self.authority_form_layout.addRow('Public email', self._authority_line('public_email', payload.get('public_email')))
                self.authority_form_layout.addRow('Analytics ID', self._authority_line('analytics_id', payload.get('analytics_id')))
                self.authority_form_layout.addRow('Search names', self.create_string_list_editor('search_names', list(payload.get('search_names') or []), on_change=lambda rows: self.set_authority_value('search_names', rows)))
                self.authority_form_layout.addRow('Footer text', self._authority_text('footer_text', payload.get('footer_text'), rows=2))
                self.authority_form_layout.addRow('Footer microcopy', self._authority_text('footer_microcopy', payload.get('footer_microcopy'), rows=2))
                self.authority_form_layout.addRow('Footer contact text', self._authority_text('footer_contact_text', payload.get('footer_contact_text'), rows=2))
                self.authority_form_layout.addRow('Copyright', self._authority_text('copyright_text', payload.get('copyright_text'), rows=2))
                self.authority_form_layout.addRow('Footer links', self.create_dict_list_editor('footer_links', list(payload.get('footer_links') or []), kind='action', on_change=lambda rows: self.set_authority_value('footer_links', rows)))
            elif key == 'artist':
                self.authority_form_layout.addRow('Name', self._authority_line('name', payload.get('name')))
                self.authority_form_layout.addRow('Discipline', self._authority_line('discipline', payload.get('discipline')))
                self.authority_form_layout.addRow('Tagline', self._authority_text('tagline', payload.get('tagline'), rows=3))
                self.authority_form_layout.addRow('Intro', self._authority_text('intro', payload.get('intro'), rows=4))
                self.authority_form_layout.addRow('About', self._authority_text('about', payload.get('about'), rows=6))
                self.authority_form_layout.addRow('Statement', self._authority_text('statement', payload.get('statement'), rows=6))
                self.authority_form_layout.addRow('Status', self._authority_text('status', payload.get('status'), rows=3))
                self.authority_form_layout.addRow('Email', self._authority_line('email', payload.get('email')))
                self.authority_form_layout.addRow('Instagram', self._authority_line('instagram', payload.get('instagram')))
                self.authority_form_layout.addRow('Location', self._authority_line('location', payload.get('location')))
                self.authority_form_layout.addRow('Header label', self._authority_line('header_label', payload.get('header_label')))
                self.authority_form_layout.addRow('Alternate names', self.create_string_list_editor('alternate_names', list(payload.get('alternate_names') or []), on_change=lambda rows: self.set_authority_value('alternate_names', rows)))
                self.authority_form_layout.addRow('Social links', self.create_dict_list_editor('social_links', list(payload.get('social_links') or []), kind='action', on_change=lambda rows: self.set_authority_value('social_links', rows)))
            elif key == 'navigation':
                self.authority_form_layout.addRow('Navigation items', self.create_dict_list_editor('items', list(payload.get('items') or []), kind='navigation', on_change=lambda rows: self.set_authority_value('items', rows)))
            elif key == 'resources':
                self.authority_form_layout.addRow('Downloads', self.create_dict_list_editor('downloads', list(payload.get('downloads') or []), kind='resource', on_change=lambda rows: self.set_authority_value('downloads', rows)))
            elif key == 'release':
                self.authority_form_layout.addRow('Staging URL', self._authority_line('staging_url', payload.get('staging_url')))
                self.authority_form_layout.addRow('Production URL', self._authority_line('production_url', payload.get('production_url')))
                self.authority_form_layout.addRow('Preview branch', self._authority_line('preview_branch', payload.get('preview_branch')))
                self.authority_form_layout.addRow('Production branch', self._authority_line('production_branch', payload.get('production_branch')))
                self.authority_form_layout.addRow('Production backend', self._authority_line('production_backend', payload.get('production_backend')))
                self.authority_form_layout.addRow('Repo', self._authority_line('repo', payload.get('repo')))
                self.authority_form_layout.addRow('Commit message template', self._authority_line('commit_message_template', payload.get('commit_message_template')))
                self.authority_form_layout.addRow('Change note template', self._authority_text('change_note_template', payload.get('change_note_template'), rows=3))
                self.authority_form_layout.addRow('Required checks', self.create_string_list_editor('required_checks', list(payload.get('required_checks') or []), on_change=lambda rows: self.set_authority_value('required_checks', rows)))
            else:
                self.authority_form_layout.addRow(QLabel('Unsupported authority document. Use the raw YAML editor.'))
        finally:
            self._suspend_authority_form = False
        self.update_authority_builder_state_label()

    def _authority_line(self, key: str, value: Any) -> QWidget:
        widget = QLineEdit(str(value or ''))
        widget.textChanged.connect(lambda text, k=key: self.set_authority_value(k, text))
        return widget

    def _authority_text(self, key: str, value: Any, *, rows: int = 4) -> QWidget:
        widget = QPlainTextEdit(str(value or ''))
        widget.setFixedHeight(max(70, rows * 26))
        widget.textChanged.connect(lambda k=key, w=widget: self.set_authority_value(k, w.toPlainText()))
        return widget

    def set_authority_value(self, key: str, value: Any) -> None:
        if self._suspend_authority_form or self._authority_model is None:
            return
        self._authority_model[key] = value
        self.commit_authority_builder_change()

    def authority_yaml_from_model(self) -> str:
        payload = self._authority_model or {}
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).rstrip() + '\n'

    def commit_authority_builder_change(self) -> None:
        if self._authority_model is None:
            return
        self._suspend_authority_raw_sync = True
        try:
            self.authority_editor.setPlainText(self.authority_yaml_from_model())
        finally:
            self._suspend_authority_raw_sync = False
        self.render_authority_review()
        self.update_authority_builder_state_label()

    def select_authority(self, key: str, *, silent: bool = False, restore_draft: bool = False) -> None:
        if not key:
            return
        self._current_authority_key = key
        text_value = load_authority_yaml_text(key)
        self._suspend_authority_raw_sync = True
        try:
            self.authority_editor.setPlainText(text_value)
        finally:
            self._suspend_authority_raw_sync = False
        self._loaded_authority_text = text_value
        try:
            payload = yaml.safe_load(text_value) or {}
        except Exception as exc:
            self._log_warning(f"Authority YAML parse failed: {exc}")
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        self._authority_model = json.loads(json.dumps(payload))
        self._authority_loaded_model = json.loads(json.dumps(payload))
        self.render_authority_builder()
        self.render_authority_review()
        if hasattr(self, "authority_breadcrumb"):
            self.authority_breadcrumb.setText(f"Content Authority  ›  {key}")
        self._last_authority_autosave_at = None
        self.maybe_restore_editor_draft('authority', key, interactive=restore_draft)
        self._update_autosave_labels()
        if not silent:
            self.status_message(f'Loaded authority file: {key}')

    def on_authority_raw_text_changed(self) -> None:
        self.update_authority_builder_state_label()
        if self._suspend_authority_raw_sync:
            return
        self.authority_mode_label.setText('Raw YAML differs from structured editor')
        self.render_authority_review()

    def apply_authority_yaml_to_builder(self) -> None:
        if not self._current_authority_key:
            return
        review = review_authority_yaml_text(self._current_authority_key, self.authority_editor.toPlainText() or '')
        errors = [row for row in list(review.get('issues') or []) if str(row.get('severity') or '').lower() == 'error']
        self.render_authority_review(force_refresh_validation=True)
        if errors:
            self._critical_modal('Invalid YAML', '\n'.join(f"- {row.get('field')}: {row.get('message')}" for row in errors[:20]), target_scope='authority', target_id=self._current_authority_key)
            return
        payload = dict(review.get('payload') or {})
        self._authority_model = json.loads(json.dumps(payload))
        self.authority_mode_label.setText('Builder and YAML are in sync')
        self.render_authority_builder()
        self.render_authority_review(force_refresh_validation=True)
        self.update_authority_builder_state_label()
        self.status_message(f'Applied YAML to structured authority editor: {self._current_authority_key}')

    def format_current_authority_yaml(self) -> None:
        if not self._current_authority_key:
            return
        review = review_authority_yaml_text(self._current_authority_key, self.authority_editor.toPlainText() or '')
        errors = [row for row in list(review.get('issues') or []) if str(row.get('severity') or '').lower() == 'error']
        if errors:
            self._critical_modal('Invalid YAML', '\n'.join(f"- {row.get('field')}: {row.get('message')}" for row in errors[:20]), target_scope='authority', target_id=self._current_authority_key)
            return
        self._suspend_authority_raw_sync = True
        try:
            self.authority_editor.setPlainText(str(review.get('raw_text') or '').rstrip() + '\n')
        finally:
            self._suspend_authority_raw_sync = False
        self.render_authority_review(force_refresh_validation=True)
        self.update_authority_builder_state_label()

    def copy_authority_yaml(self) -> None:
        QApplication.clipboard().setText(self.authority_editor.toPlainText())
        self.status_message("YAML copied to clipboard")

    def restore_current_authority_last_valid(self) -> None:
        if not self._current_authority_key:
            return
        if QMessageBox.question(self, 'Restore last valid authority YAML', f"Restore the last validated YAML version for authority file '{self._current_authority_key}'? Unsaved editor text will be replaced.") != QMessageBox.StandardButton.Yes:
            return
        try:
            text = restore_last_valid_authority_yaml(self._current_authority_key)
        except Exception as exc:
            self._critical_modal('Restore last valid authority failed', str(exc), target_scope='authority', target_id=self._current_authority_key)
            return
        self._suspend_authority_raw_sync = True
        try:
            self.authority_editor.setPlainText(text)
        finally:
            self._suspend_authority_raw_sync = False
        self.select_authority(self._current_authority_key, silent=True)
        self._notify_nonblocking('success', 'Restored last valid authority YAML', self._current_authority_key, target_scope='authority', target_id=self._current_authority_key)

    def _authority_save_preview_allows_commit(self, review: dict[str, Any]) -> bool:
        issues = list(review.get('issues') or [])
        errors = [item for item in issues if str(item.get('severity') or '').lower() == 'error']
        if errors:
            self._critical_modal('Authority save blocked', '\n'.join(f"- {row.get('field') or '<root>'}: {row.get('message') or ''}" for row in errors[:20]), target_scope='authority', target_id=self._current_authority_key)
            return False
        diff_lines = list(review.get('diff_lines') or [])
        if diff_lines:
            preview = '\n'.join(diff_lines[:70])
            confirm = QMessageBox.question(self, 'Save authority YAML', f"Validated YAML has {len(diff_lines)} diff line(s).\n\n{preview}\n\nSave this authority file?")
            return confirm == QMessageBox.StandardButton.Yes
        return True

    def validate_current_authority_builder(self) -> None:
        self.render_authority_review(force_refresh_validation=True)
        self.authority_tabs.setCurrentIndex(2)

    def render_authority_review(self, *, force_refresh_validation: bool = False) -> None:
        if not self._current_authority_key:
            self.authority_review_summary.setText('No authority file loaded.')
            self.authority_validation_box.setPlainText('')
            self.authority_diff_box.setPlainText('')
            return
        if force_refresh_validation or not hasattr(self, '_authority_validation_cache'):
            rows = [row for row in validate_all() if row.get('scope') in {'site', 'artist', 'navigation', 'resource'}]
            self._authority_validation_cache = rows
        else:
            rows = getattr(self, '_authority_validation_cache', [])
        raw_review = review_authority_yaml_text(self._current_authority_key, self.authority_editor.toPlainText())
        raw_issues = list(raw_review.get('issues') or [])
        if self._current_authority_key == 'site':
            relevant = [row for row in rows if row.get('scope') == 'site']
        elif self._current_authority_key == 'artist':
            relevant = [row for row in rows if row.get('scope') == 'artist']
        elif self._current_authority_key == 'navigation':
            relevant = [row for row in rows if row.get('scope') == 'navigation']
        elif self._current_authority_key == 'resources':
            relevant = [row for row in rows if row.get('scope') == 'resource']
        else:
            relevant = []
        authority_summary_text = f"{len(relevant) + len(raw_issues)} validation item(s) for {self._current_authority_key}. Structured edits sync directly into the YAML editor."
        self.authority_review_summary.setText(authority_summary_text)
        if hasattr(self, 'authority_live_review_drawer'):
            state = 'Needs review' if relevant else 'Healthy'
            self.authority_live_review_drawer.setText(f"Authority health: {state} · {authority_summary_text}. Use Advanced YAML only for raw-file edits or detailed diff review.")
        authority_lines = [f"[{row.get('severity','info').upper()}] {row.get('message','')}\nTarget: {row.get('id','')}" for row in relevant]
        authority_lines += [f"[{row.get('severity','info').upper()}] {row.get('field','<root>')}: {row.get('message','')}" for row in raw_issues]
        if authority_lines:
            self.authority_validation_box.setPlainText("\n\n".join(authority_lines))
        else:
            self.authority_validation_box.setPlainText('No validation issues for this authority document.')
        before = self._loaded_authority_text.splitlines(keepends=True)
        after = self.authority_editor.toPlainText().splitlines(keepends=True)
        diff = ''.join(unified_diff(before, after, fromfile='saved', tofile='current'))
        self.authority_diff_box.setPlainText(diff or 'No unsaved text changes.')

    def update_authority_builder_state_label(self) -> None:
        self.authority_state.setText('Modified' if self.is_authority_dirty() else 'Clean')
        if self._authority_model is None:
            self.authority_mode_label.setText('No authority builder loaded')
            return
        try:
            builder_text = self.authority_yaml_from_model()
        except Exception as exc:
            self._log_warning(f"Authority builder serialization failed: {exc}")
            builder_text = ''
        if self._normalized_text(builder_text) == self._normalized_text(self.authority_editor.toPlainText()):
            self.authority_mode_label.setText('Builder and YAML are in sync')
        else:
            self.authority_mode_label.setText('Raw YAML differs from structured editor')

    def save_current_authority(self) -> None:
        if not self._current_authority_key:
            return
        before_text = self._loaded_authority_text
        review = review_authority_yaml_text(self._current_authority_key, self.authority_editor.toPlainText())
        self.render_authority_review(force_refresh_validation=True)
        if not self._authority_save_preview_allows_commit(review):
            return
        try:
            save_authority_yaml_text(self._current_authority_key, self.authority_editor.toPlainText())
        except Exception as exc:
            self._critical_modal('Save failed', str(exc), target_scope='authority', target_id=self._current_authority_key)
            return
        self._loaded_authority_text = self.authority_editor.toPlainText()
        try:
            payload = yaml.safe_load(self._loaded_authority_text) or {}
        except Exception as exc:
            self._log_warning(f"Saved authority YAML parse failed: {exc}")
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        self._authority_model = json.loads(json.dumps(payload))
        self._authority_loaded_model = json.loads(json.dumps(payload))
        clear_editor_draft('authority', self._current_authority_key)
        self._draft_restore_seen.discard(('authority', self._current_authority_key))
        self._last_draft_hash.pop(('authority', self._current_authority_key), None)
        self.render_authority_builder()
        self.render_authority_review(force_refresh_validation=True)
        self.push_notification('success', f"Saved authority file: {self._current_authority_key}", 'Authority content updated.', target_scope='authority', target_id=self._current_authority_key)
        self._reset_autosave_state("authority")
        self._show_toast(f"✓ Saved: {self._current_authority_key}")
        self._store_text_diff("authority", before_text, self.authority_editor.toPlainText())
        self.status_message(f'Saved authority file: {self._current_authority_key} · diff ready')
        self.refresh_all_context(force=True, scope={"authority", "dashboard", "validation"})

    def reload_current_authority(self) -> None:
        if self._current_authority_key and self.ensure_authority_editor_safe():
            self._draft_restore_seen.discard(('authority', self._current_authority_key))
            self._last_draft_hash.pop(('authority', self._current_authority_key), None)
            self.select_authority(self._current_authority_key)

    # ---------- validation ----------
    def build_validation_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        top_card = QFrame()
        top_card.setObjectName("workspaceCard")
        top_layout = QHBoxLayout(top_card)
        top_layout.setContentsMargins(14, 12, 14, 12)
        top_layout.setSpacing(10)
        self.validation_summary_label = QLabel("Validation has not run yet.")
        self.validation_summary_label.setObjectName("missionStatus")
        self.validation_summary_label.setWordWrap(True)
        top_layout.addWidget(self.validation_summary_label, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_validation)
        open_item = QPushButton("Open item")
        open_item.clicked.connect(self.open_selected_validation_item)
        autofix = QPushButton("Auto-fix")
        autofix.clicked.connect(self.auto_fix_selected_validation_item)
        explain = QPushButton("Explain")
        explain.clicked.connect(self.explain_selected_validation_item)
        accessibility = QPushButton("Accessibility audit")
        accessibility.clicked.connect(self.open_accessibility_audit)
        for btn in (refresh, open_item, autofix, explain, accessibility):
            top_layout.addWidget(btn)
        layout.addWidget(top_card)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("Severity"))
        self._validation_filter_buttons = {}
        for mode, label in [("all", "All"), ("errors", "Errors"), ("warnings", "Warnings"), ("advisory", "Advisory")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, m=mode: self._set_validation_filter(m))
            self._validation_filter_buttons[mode] = btn
            filter_row.addWidget(btn)
        self._validation_filter_mode = "all"
        self._validation_filter_buttons["all"].setChecked(True)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setObjectName("validation-main-splitter")
        self.validation_tree = QTreeWidget()
        self.validation_tree.setHeaderLabels(["Scope", "ID", "Severity", "Action", "Message", "Fix"])
        self.validation_tree.itemSelectionChanged.connect(self.update_validation_detail)
        self.validation_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.validation_tree.customContextMenuRequested.connect(self.show_validation_menu)
        self._polish_data_tree(self.validation_tree, "validation")
        split.addWidget(self.validation_tree)
        self.validation_detail = QPlainTextEdit()
        self.validation_detail.setReadOnly(True)
        self.validation_detail.setMinimumHeight(180)
        split.addWidget(self.validation_detail)
        split.setHandleWidth(8)
        split.setSizes([900, 520])
        layout.addWidget(split, 1)
        return tab

    def _load_validation_data(self) -> dict[str, Any]:
        rows = list(validation_action_rows())
        return {"rows": rows}

    def refresh_validation(self) -> None:
        if not hasattr(self, "validation_tree"):
            self._mark_dirty({"validation"})
            return
        if getattr(self, "_validation_refresh_inflight", False):
            self._mark_dirty({"validation"})
            return
        self._validation_refresh_inflight = True
        self._set_tab_loading(getattr(self, "validation_tab", None) or getattr(self, "studio_tab", None), True)
        self.start_task("Refreshing validation", self._load_validation_data, on_done=self._apply_validation_data)

    def _apply_validation_data(self, result: Any) -> None:
        started = time.perf_counter()
        rows = list((result or {}).get("rows") or []) if isinstance(result, dict) else list(result or [])
        self._validation_rows = list(rows)
        self._cached_validation_count = len(rows)
        self.validation_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        if not (self.state.get("column_widths") or {}).get("validation"):
            self.validation_tree.setColumnWidth(0, 110)
            self.validation_tree.setColumnWidth(1, 180)
            self.validation_tree.setColumnWidth(2, 100)
            self.validation_tree.setColumnWidth(3, 150)
            self.validation_tree.setColumnWidth(4, 520)
            self.validation_tree.setColumnWidth(5, 90)
        self._apply_validation_filter()
        fixable = sum(1 for row in rows if row.get('fixable'))
        if hasattr(self, "validation_summary_label"):
            if rows:
                errors = sum(1 for row in rows if str(row.get("severity") or "").lower() == "error")
                warnings = sum(1 for row in rows if str(row.get("severity") or "").lower() in {"warning", "warn"})
                self.validation_summary_label.setText(f"{len(rows)} validation issue(s): {errors} error(s), {warnings} warning(s), {fixable} auto-fixable.")
            else:
                self.validation_summary_label.setText("Validation is clean. No blocking content issues were found.")
        self.validation_detail.setPlainText(f"{len(rows)} issue(s) found. Fixable: {fixable}.")
        self._validation_refresh_inflight = False
        self._dirty_tabs.pop("validation", None)
        self._set_tab_loading(getattr(self, "validation_tab", None) or getattr(self, "studio_tab", None), False)
        self.update_tab_badges()
        self._record_perf("validation refresh", time.perf_counter() - started, f"{len(rows)} issue(s)")

    def _rebuild_validation_tree(self, rows: list[dict[str, Any]]) -> None:
        self.validation_tree.clear()
        for row in rows:
            item = QTreeWidgetItem([str(row.get("scope") or ""), str(row.get("id") or ""), str(row.get("severity") or ""), str(row.get("action") or "Open"), str(row.get("message") or ""), ""])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            color = self._severity_color(str(row.get("severity") or "info"))
            for col in range(6):
                item.setForeground(col, color)
            self.validation_tree.addTopLevelItem(item)
            if row.get("fixable"):
                fix_btn = QPushButton("Auto-fix")
                fix_btn.setFixedWidth(76)
                fix_btn.clicked.connect(lambda _checked=False, r=dict(row): self._run_auto_fix(r))
                self.validation_tree.setItemWidget(item, 5, fix_btn)
        total = len(getattr(self, '_validation_rows', []))
        if hasattr(self, "validation_summary_label"):
            self.validation_summary_label.setText(f"Showing {len(rows)} of {total} validation issue(s).")
        self.validation_detail.setPlainText(f"Showing {len(rows)} of {total} validation issue(s).")

    def update_validation_detail(self) -> None:
        item = self.validation_tree.currentItem()
        if item is None:
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        self.validation_detail.setPlainText(
            f"Scope: {row.get('scope')}\nID: {row.get('id')}\nSeverity: {row.get('severity')}\nAction: {row.get('action') or 'Open'}\nFixable: {bool(row.get('fixable'))}\n\n{row.get('message')}\n\nExplanation:\n{row.get('explain') or ''}"
        )

    def show_validation_menu(self, position) -> None:
        item = self.validation_tree.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        open_item = menu.addAction("Open selected item")
        autofix_item = menu.addAction("Auto-fix selected")
        explain_item = menu.addAction("Explain issue")
        copy_issue = menu.addAction("Copy issue detail")
        action = menu.exec(self.validation_tree.viewport().mapToGlobal(position))
        if action == open_item:
            self.validation_tree.setCurrentItem(item)
            self.open_selected_validation_item()
        elif action == autofix_item:
            self.validation_tree.setCurrentItem(item)
            self.auto_fix_selected_validation_item()
        elif action == explain_item:
            self.validation_tree.setCurrentItem(item)
            self.explain_selected_validation_item()
        elif action == copy_issue:
            self.validation_tree.setCurrentItem(item)
            self.update_validation_detail()
            QApplication.clipboard().setText(self.validation_detail.toPlainText())
            self.status_message("Copied validation detail")

    def _selected_validation_row(self) -> dict[str, Any] | None:
        item = self.validation_tree.currentItem()
        return dict(item.data(0, Qt.ItemDataRole.UserRole) or {}) if item is not None else None

    def auto_fix_selected_validation_item(self) -> None:
        row = self._selected_validation_row()
        if not row:
            self._info_nonblocking("No validation item", "Select a validation row first.", target_scope="validation")
            return
        if not row.get("fixable"):
            QMessageBox.information(self, "Manual fix required", row.get("explain") or "Open the item and edit it manually.")
            return
        if QMessageBox.question(self, "Auto-fix validation issue", f"Apply safe fix for {row.get('scope')}:{row.get('id')}?\n\n{row.get('message')}") != QMessageBox.StandardButton.Yes:
            return
        try:
            result = auto_fix_validation_issue(row)
        except Exception as exc:
            QMessageBox.critical(self, "Auto-fix failed", str(exc))
            return
        self.push_notification("success", "Validation issue auto-fixed", ", ".join(result.get("changed") or []), target_scope="validation")
        self.refresh_all_context(force=True, scope={"series", "pages", "dashboard", "validation", "studio", "publish"})

    def explain_selected_validation_item(self) -> None:
        row = self._selected_validation_row()
        if not row:
            self._info_nonblocking("No validation item", "Select a validation row first.", target_scope="validation")
            return
        QMessageBox.information(self, "Validation explanation", row.get("explain") or row.get("message") or "No explanation available.")

    def open_selected_validation_item(self) -> None:
        item = self.validation_tree.currentItem()
        if item is None:
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        scope = row.get("scope")
        if scope == "work":
            self.tabs.setCurrentWidget(self.works_tab)
            self.select_work(str(row.get("id") or ""))
        elif scope == "series":
            self.tabs.setCurrentWidget(self.series_tab)
            self.select_series(str(row.get("id") or ""))
        elif scope == "page":
            self.tabs.setCurrentWidget(self.pages_tab)
            self.select_page(str(row.get("id") or ""))

    # ---------- studio ----------
    def build_studio_tab(self) -> QWidget:
        """Studio: cached, async review workspace with three focused inner views."""
        tab = QWidget()
        tab.setObjectName("studioTab")
        root = QVBoxLayout(tab)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        studio_scroll = QScrollArea()
        studio_scroll.setObjectName("studioScrollArea")
        studio_scroll.setWidgetResizable(True)
        studio_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        studio_scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(studio_scroll, 1)

        studio_canvas = QWidget()
        studio_canvas.setObjectName("studioCanvas")
        studio_scroll.setWidget(studio_canvas)
        canvas = QVBoxLayout(studio_canvas)
        canvas.setContentsMargins(10, 10, 10, 10)
        canvas.setSpacing(10)

        def make_card(title: str = "", detail: str = "", object_name: str = "studioCard") -> tuple[QFrame, QVBoxLayout]:
            card = QFrame()
            card.setObjectName(object_name)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(10)
            if title or detail:
                heading = QHBoxLayout()
                heading.setContentsMargins(0, 0, 0, 0)
                heading.setSpacing(8)
                text_col = QVBoxLayout()
                text_col.setContentsMargins(0, 0, 0, 0)
                text_col.setSpacing(2)
                if title:
                    title_label = QLabel(title)
                    title_label.setObjectName("studioSectionTitle")
                    text_col.addWidget(title_label)
                if detail:
                    detail_label = QLabel(detail)
                    detail_label.setObjectName("studioSectionHint")
                    detail_label.setWordWrap(True)
                    text_col.addWidget(detail_label)
                heading.addLayout(text_col, 1)
                card_layout.addLayout(heading)
            return card, card_layout

        # Studio command centre: metrics and actions are grouped instead of scattered.
        hero_card, hero_layout = make_card("Studio command centre", "Sequence pages, check image health, then clear release blockers before publishing.", "studioHeroCard")
        hero_top = QHBoxLayout()
        hero_top.setContentsMargins(0, 0, 0, 0)
        hero_top.setSpacing(8)
        self.studio_metric_published = StatusBadge("Published: —", "info")
        self.studio_metric_validation = StatusBadge("Validation: —", "info")
        self.studio_metric_assets = StatusBadge("Assets: —", "info")
        self.studio_metric_health = StatusBadge("Health: —", "info")
        for badge in (self.studio_metric_published, self.studio_metric_validation, self.studio_metric_assets, self.studio_metric_health):
            badge.setMinimumWidth(104)
            hero_top.addWidget(badge)
        self.studio_last_refreshed_label = QLabel("Last refreshed: never")
        self.studio_last_refreshed_label.setObjectName("quietHint")
        hero_top.addWidget(self.studio_last_refreshed_label, 1)
        refresh_btn = QPushButton("Refresh Studio")
        refresh_btn.setObjectName("studioPrimaryAction")
        refresh_btn.setToolTip("Reload Studio data once, then reuse the cached result across the inner Studio views.")
        refresh_btn.clicked.connect(lambda: (setattr(self, "_studio_dirty", True), self._mark_dirty({"studio"}), self.refresh_studio()))
        review_tools_btn = self._make_menu_button("Review tools ▾", [
            ("Export metadata CSV", self.export_metadata_csv),
            ("Import metadata CSV…", self.import_metadata_csv),
            ("Inquiries", self.open_inquiry_tracker),
            ("Print editions", self.open_print_edition_manager),
            ("Media library…", self.open_media_library_dialog),
            ("Panel diagnostics", self.open_panel_diagnostics),
        ])
        hero_top.addWidget(refresh_btn)
        hero_top.addWidget(review_tools_btn)
        hero_layout.addLayout(hero_top)

        health_row = QHBoxLayout()
        health_row.setContentsMargins(0, 0, 0, 0)
        health_row.setSpacing(10)
        health_label = QLabel("Asset health")
        health_label.setObjectName("studioInlineLabel")
        health_row.addWidget(health_label)
        self.asset_health_bar = AssetHealthBar()
        self.asset_health_bar.setObjectName("studioAssetHealthBar")
        self.asset_health_bar.setToolTip("Asset health: green=ok, amber=recoverable/risk, red=missing/broken, grey=derivative-only/unknown")
        self.asset_health_bar.setMaximumHeight(14)
        health_row.addWidget(self.asset_health_bar, 1)
        hero_layout.addLayout(health_row)
        canvas.addWidget(hero_card)

        workflow_card, workflow_layout = make_card("Review path", "Work from left to right. The tab stays cached until you refresh Studio or change content.", "studioWorkflowCard")
        self.studio_review_stepper = WorkflowStepper(["Sequence", "Images", "Release"])
        self.studio_review_stepper.setToolTip("Studio workflow: check sequence and pages, repair image health, clear release blockers.")
        workflow_layout.addWidget(self.studio_review_stepper)
        canvas.addWidget(workflow_card)

        self.studio_inner_tabs = QTabWidget()
        self.studio_inner_tabs.setObjectName("studioWorkspaceTabs")
        self.studio_inner_tabs.currentChanged.connect(lambda _index: self._populate_studio_visible_subview())
        canvas.addWidget(self.studio_inner_tabs, 1)

        # 1) Sequence & Pages
        sequence_page = QWidget()
        sequence_page.setObjectName("studioSequencePage")
        seq_root = QVBoxLayout(sequence_page)
        seq_root.setContentsMargins(10, 10, 10, 10)
        seq_root.setSpacing(10)

        control_card, control_layout = make_card("Sequence and page controls", "Use the page tools for public-page preview and the series tools for ordering works.", "studioToolbarCard")
        control_grid = QGridLayout()
        control_grid.setContentsMargins(0, 0, 0, 0)
        control_grid.setHorizontalSpacing(8)
        control_grid.setVerticalSpacing(8)

        page_label = QLabel("Page")
        page_label.setObjectName("studioInlineLabel")
        self.studio_page_combo = QComboBox()
        self.studio_page_combo.addItems(available_page_keys())
        self.studio_page_combo.currentTextChanged.connect(self.refresh_studio_page_preview)
        page_refresh_btn = QPushButton("Refresh page")
        page_refresh_btn.clicked.connect(self.refresh_studio_page_preview)
        open_page_btn = QPushButton("Open preview")
        open_page_btn.clicked.connect(self.open_studio_page_preview)
        control_grid.addWidget(page_label, 0, 0)
        control_grid.addWidget(self.studio_page_combo, 0, 1)
        control_grid.addWidget(page_refresh_btn, 0, 2)
        control_grid.addWidget(open_page_btn, 0, 3)

        series_label = QLabel("Series")
        series_label.setObjectName("studioInlineLabel")
        self.studio_series_combo = QComboBox()
        self.studio_series_combo.addItems(available_series_slugs())
        self.studio_series_combo.currentTextChanged.connect(self.refresh_studio_sequence_board)
        control_grid.addWidget(series_label, 1, 0)
        control_grid.addWidget(self.studio_series_combo, 1, 1)
        series_actions = [
            ("Move up", lambda: self.move_studio_sequence_item(-1)),
            ("Move down", lambda: self.move_studio_sequence_item(1)),
            ("Use as cover", self.set_studio_sequence_cover),
            ("Suggest order", self.suggest_studio_series_order),
            ("Save sequence", self.save_studio_sequence),
            ("Refresh sequence", self.refresh_studio_sequence_board),
            ("Open Series", self.open_studio_series_in_series_tab),
        ]
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        for label, slot in series_actions:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            action_row.addWidget(btn)
        action_row.addStretch(1)
        control_grid.addLayout(action_row, 1, 2, 1, 4)
        control_grid.setColumnStretch(4, 1)
        control_layout.addLayout(control_grid)
        seq_root.addWidget(control_card)

        seq_split = QSplitter(Qt.Orientation.Horizontal)
        seq_split.setObjectName("studio-sequence-pages-splitter")
        seq_split.setChildrenCollapsible(False)
        seq_split.setHandleWidth(8)

        seq_left_card, seq_left_layout = make_card("Series index", "Select a work to inspect the image, review state, and metadata used by the public series page.", "studioPanelCard")
        self.studio_sequence = QTreeWidget()
        self.studio_sequence.setObjectName("studioSequenceTree")
        self.studio_sequence.setHeaderLabels(["#", "Work ID", "Title", "Review"])
        self._polish_data_tree(self.studio_sequence, "studio_sequence")
        self.studio_sequence.itemSelectionChanged.connect(self.update_studio_sequence_preview)
        seq_left_layout.addWidget(self.studio_sequence, 1)
        seq_split.addWidget(seq_left_card)

        seq_right_card, seq_right_layout = make_card("Preview and page context", "The top panel follows the selected series work. The bottom panel follows the selected public page.", "studioPanelCard")
        preview_split = QSplitter(Qt.Orientation.Vertical)
        preview_split.setObjectName("studio-sequence-preview-splitter")
        preview_split.setChildrenCollapsible(False)
        preview_split.setHandleWidth(8)

        work_preview_card, work_preview_layout = make_card("Selected work", "", "studioNestedCard")
        self.studio_sequence_preview = QLabel("Select a work in the sequence to preview it.")
        self.studio_sequence_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.studio_sequence_preview.setMinimumHeight(170)
        self.studio_sequence_preview.setObjectName("imagePreview")
        self.studio_sequence_detail = QPlainTextEdit()
        self.studio_sequence_detail.setObjectName("studioDetailBox")
        self.studio_sequence_detail.setReadOnly(True)
        self.studio_sequence_detail.setMaximumHeight(78)
        work_preview_layout.addWidget(self.studio_sequence_preview, 1)
        work_preview_layout.addWidget(self.studio_sequence_detail)
        preview_split.addWidget(work_preview_card)

        page_preview_card, page_preview_layout = make_card("Page preview", "", "studioNestedCard")
        self.studio_page_preview = QLabel("Select a page to preview its lead image and narrative summary.")
        self.studio_page_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.studio_page_preview.setMinimumHeight(150)
        self.studio_page_preview.setObjectName("imagePreview")
        self.studio_page_text = QPlainTextEdit()
        self.studio_page_text.setObjectName("studioDetailBox")
        self.studio_page_text.setReadOnly(True)
        self.studio_page_text.setMaximumHeight(88)
        page_preview_layout.addWidget(self.studio_page_preview, 1)
        page_preview_layout.addWidget(self.studio_page_text)
        preview_split.addWidget(page_preview_card)
        preview_split.setSizes([310, 260])
        seq_right_layout.addWidget(preview_split, 1)
        seq_split.addWidget(seq_right_card)
        seq_split.setStretchFactor(0, 3)
        seq_split.setStretchFactor(1, 2)
        seq_split.setSizes([820, 540])
        seq_root.addWidget(seq_split, 1)
        self.studio_inner_tabs.addTab(sequence_page, "Sequence & Pages")

        # 2) Image Health
        health_page = QWidget()
        health_page.setObjectName("studioHealthPage")
        health_layout = QVBoxLayout(health_page)
        health_layout.setContentsMargins(10, 10, 10, 10)
        health_layout.setSpacing(10)

        source_card, source_layout = make_card("Image health and source-asset audit", "Audit and repair actions are separated from the data tables so the work area stays readable.", "studioToolbarCard")
        source_actions = QHBoxLayout()
        source_actions.setContentsMargins(0, 0, 0, 0)
        source_actions.setSpacing(8)
        for label, slot in [
            ("Audit now", self.refresh_studio),
            ("Repair plan", self.show_selected_studio_asset_repair_plan),
            ("Repair selected", self.repair_selected_studio_asset),
            ("Relink selected…", self.relink_selected_studio_asset),
            ("Bulk relink…", self.bulk_relink_sources_from_folder),
            ("Refresh registry", self.run_refresh_image_registry),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            source_actions.addWidget(btn)
        source_actions.addStretch(1)
        source_layout.addLayout(source_actions)
        self.studio_registry_hint = QPlainTextEdit()
        self.studio_registry_hint.setObjectName("studioRegistryHint")
        self.studio_registry_hint.setReadOnly(True)
        self.studio_registry_hint.setMaximumHeight(76)
        source_layout.addWidget(self.studio_registry_hint)
        health_layout.addWidget(source_card)

        asset_split = QSplitter(Qt.Orientation.Horizontal)
        asset_split.setObjectName("studio-assets-splitter")
        asset_split.setChildrenCollapsible(False)
        asset_split.setHandleWidth(8)

        asset_left_card, asset_left_layout = make_card("Asset tables", "Image health shows the complete register. Source blockers shows only items that need recovery.", "studioPanelCard")
        asset_tables_split = QSplitter(Qt.Orientation.Vertical)
        asset_tables_split.setObjectName("studio-asset-tables-splitter")
        asset_tables_split.setChildrenCollapsible(False)
        asset_tables_split.setHandleWidth(8)

        health_table_card, health_table_layout = make_card("Image health dashboard", "", "studioNestedCard")
        self.studio_image_health = QTreeWidget()
        self.studio_image_health.setObjectName("studioImageHealthTree")
        self.studio_image_health.setHeaderLabels(["Work ID", "Series", "Health", "Source", "Preview", "Derivatives", "Focal"])
        self._polish_data_tree(self.studio_image_health, "studio_image_health")
        self.studio_image_health.itemSelectionChanged.connect(self.update_studio_image_health_detail)
        health_table_layout.addWidget(self.studio_image_health, 1)
        asset_tables_split.addWidget(health_table_card)

        blockers_card, blockers_layout = make_card("Source asset blockers", "", "studioNestedCard")
        self.studio_assets = QTreeWidget()
        self.studio_assets.setObjectName("studioAssetsTree")
        self.studio_assets.setHeaderLabels(["Work ID", "Series", "Status", "Recovery", "Actions"])
        self._polish_data_tree(self.studio_assets, "studio_assets")
        self.studio_assets.itemSelectionChanged.connect(self.update_studio_asset_detail)
        blockers_layout.addWidget(self.studio_assets, 1)
        asset_tables_split.addWidget(blockers_card)
        asset_tables_split.setSizes([420, 260])
        asset_left_layout.addWidget(asset_tables_split, 1)
        asset_split.addWidget(asset_left_card)

        asset_right_card, asset_right_layout = make_card("Selected asset", "Preview and repair detail follow the selected row.", "studioPanelCard")
        self.studio_asset_preview = QLabel("Select a source-asset row to preview the best available image.")
        self.studio_asset_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.studio_asset_preview.setMinimumHeight(280)
        self.studio_asset_preview.setObjectName("imagePreview")
        asset_right_layout.addWidget(self.studio_asset_preview, 1)
        self.studio_asset_detail = QPlainTextEdit()
        self.studio_asset_detail.setObjectName("studioDetailBox")
        self.studio_asset_detail.setReadOnly(True)
        self.studio_asset_detail.setMaximumHeight(126)
        asset_right_layout.addWidget(self.studio_asset_detail)
        asset_split.addWidget(asset_right_card)
        asset_split.setStretchFactor(0, 3)
        asset_split.setStretchFactor(1, 2)
        asset_split.setSizes([880, 520])
        health_layout.addWidget(asset_split, 1)
        self.studio_inner_tabs.addTab(health_page, "Image Health")

        # 3) Release Checks, including validation
        release_page = QWidget()
        release_page.setObjectName("studioReleasePage")
        release_layout = QVBoxLayout(release_page)
        release_layout.setContentsMargins(10, 10, 10, 10)
        release_layout.setSpacing(10)

        release_toolbar_card, release_toolbar_layout = make_card("Validation and release gates", "Open the exact blocker, then return to Publish only when the release list is clean.", "studioToolbarCard")
        release_actions = QHBoxLayout()
        release_actions.setContentsMargins(0, 0, 0, 0)
        release_actions.setSpacing(8)
        open_issue_btn = QPushButton("Open selected issue")
        open_issue_btn.clicked.connect(self.open_selected_studio_issue)
        open_publish_btn = QPushButton("Open Publish")
        open_publish_btn.clicked.connect(lambda: self.tabs.setCurrentWidget(self.publish_tab))
        release_actions.addWidget(open_issue_btn)
        release_actions.addWidget(open_publish_btn)
        release_actions.addStretch(1)
        release_toolbar_layout.addLayout(release_actions)
        release_layout.addWidget(release_toolbar_card)

        release_split = QSplitter(Qt.Orientation.Horizontal)
        release_split.setObjectName("studio-release-validation-splitter")
        release_split.setChildrenCollapsible(False)
        release_split.setHandleWidth(8)

        validation_panel, validation_panel_layout = make_card("Blocking validation issues", "Rows here should be opened and repaired before packaging.", "studioPanelCard")
        self.studio_validation = QTreeWidget()
        self.studio_validation.setObjectName("studioValidationTree")
        self.studio_validation.setHeaderLabels(["Scope", "ID", "Severity", "Message"])
        self._polish_data_tree(self.studio_validation, "studio_validation")
        self.studio_validation.itemSelectionChanged.connect(self.update_studio_validation_detail)
        validation_panel_layout.addWidget(self.studio_validation, 1)
        self.studio_validation_detail = QPlainTextEdit()
        self.studio_validation_detail.setObjectName("studioDetailBox")
        self.studio_validation_detail.setReadOnly(True)
        self.studio_validation_detail.setMaximumHeight(118)
        validation_panel_layout.addWidget(self.studio_validation_detail)
        release_split.addWidget(validation_panel)

        release_panel, release_panel_layout = make_card("Release checks", "Checklist state mirrors the release gate used by the Publish tab.", "studioPanelCard")
        self.studio_release_checks = QTreeWidget()
        self.studio_release_checks.setObjectName("studioReleaseTree")
        self.studio_release_checks.setHeaderLabels(["Area", "Status", "Detail"])
        self._polish_data_tree(self.studio_release_checks, "studio_release")
        self.studio_release_checks.itemSelectionChanged.connect(self.update_studio_release_detail)
        release_panel_layout.addWidget(self.studio_release_checks, 1)
        self.studio_release_detail = QPlainTextEdit()
        self.studio_release_detail.setObjectName("studioDetailBox")
        self.studio_release_detail.setReadOnly(True)
        self.studio_release_detail.setMaximumHeight(118)
        release_panel_layout.addWidget(self.studio_release_detail)
        release_split.addWidget(release_panel)
        release_split.setStretchFactor(0, 1)
        release_split.setStretchFactor(1, 1)
        release_split.setSizes([700, 700])
        release_layout.addWidget(release_split, 1)
        self.studio_inner_tabs.addTab(release_page, "Release Checks")

        self._studio_sequence_order = []
        self._studio_sequence_cover_id = ""
        self._studio_selected_work_id = ""
        QTimer.singleShot(0, self._apply_layout_rescue_defaults)
        return tab

    def open_media_library_dialog(self) -> None:
        MediaLibraryDialog(self).exec()

    def export_metadata_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export works metadata CSV", str(ROOT / "works-metadata.csv"), "CSV files (*.csv)")
        if not path:
            return
        def task() -> str:
            return export_works_csv(path)
        def done(result: Any) -> None:
            self.push_notification("success", "Metadata CSV exported", str(result), target_scope="studio")
            self.status_message(f"Exported metadata CSV: {Path(str(result)).name}")
        self.start_task("Export metadata CSV", task, on_done=done)

    def show_orphaned_assets(self) -> None:
        try:
            rows = find_orphaned_assets()
        except Exception as exc:
            QMessageBox.critical(self, "Orphan scan failed", str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Orphaned assets · quarantine review")
        dialog.resize(980, 580)
        layout = QVBoxLayout(dialog)
        label = QLabel(
            f"{len(rows)} potential orphaned asset(s). This workflow quarantines files instead of deleting them, so cleanup is reversible."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        tree = QTreeWidget()
        tree.setHeaderLabels(["Path", "Root", "Size"])
        tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        for row in rows:
            item = QTreeWidgetItem([str(row.get("path") or ""), str(row.get("root") or ""), str(row.get("size") or "")])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            tree.addTopLevelItem(item)
        layout.addWidget(tree, 1)
        buttons = QHBoxLayout()
        quarantine_btn = QPushButton("Quarantine selected")
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        buttons.addWidget(quarantine_btn)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        def quarantine_selected() -> None:
            selected = tree.selectedItems()
            if not selected:
                QMessageBox.information(dialog, "Nothing selected", "Select orphaned asset rows to quarantine.")
                return
            paths = [str((item.data(0, Qt.ItemDataRole.UserRole) or {}).get("path") or "") for item in selected]
            if QMessageBox.question(dialog, "Quarantine assets", f"Move {len(paths)} file(s) into .stillmrk-build/quarantine/assets?") != QMessageBox.StandardButton.Yes:
                return
            try:
                moved = quarantine_orphaned_assets(paths)
            except Exception as exc:
                QMessageBox.critical(dialog, "Quarantine failed", str(exc))
                return
            self.push_notification("success", "Assets quarantined", f"Moved {len(moved)} orphaned asset(s) to quarantine.", target_scope="studio")
            self.refresh_studio()
            dialog.accept()

        quarantine_btn.clicked.connect(quarantine_selected)
        dialog.exec()

    def import_metadata_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import works metadata CSV", str(ROOT), "CSV files (*.csv)")
        if not path:
            return
        try:
            preview = preview_works_csv_import(path)
        except Exception as exc:
            QMessageBox.critical(self, "CSV import preview failed", str(exc))
            return
        errors = list(preview.get("errors") or [])
        changes = list(preview.get("changes") or [])
        lines = [f"CSV: {Path(path).name}", f"Rows changing: {len(changes)}", f"Errors: {len(errors)}", ""]
        if errors:
            lines.append("Errors:")
            lines.extend(f"- {err}" for err in errors[:20])
        else:
            lines.append("Changes:")
            for row in changes[:80]:
                lines.append(f"- {row.get('work_id')}: {', '.join(row.get('fields') or [])}")
            if len(changes) > 80:
                lines.append(f"- … and {len(changes) - 80} more")
        detail = "\n".join(lines)
        if errors:
            QMessageBox.warning(self, "CSV has errors", detail)
            return
        if not changes:
            QMessageBox.information(self, "No CSV changes", detail)
            return
        if QMessageBox.question(self, "Import metadata CSV", detail + "\n\nApply these changes in one transaction?") != QMessageBox.StandardButton.Yes:
            return

        def task() -> dict[str, Any]:
            return import_works_csv(path)

        def done(result: Any) -> None:
            count = int((result or {}).get("count") or 0)
            self.push_notification("success", "Metadata CSV imported", f"Updated {count} work(s).", target_scope="studio")
            self.status_message(f"Imported metadata CSV · {count} work(s)")
            self.clear_work_icon_cache()
            self.refresh_all_context(force=True, scope={"works", "dashboard", "validation", "studio"})

        self.start_task("Import metadata CSV", task, on_done=done)

    def regenerate_selected_studio_derivatives(self) -> None:
        items = self.studio_image_health.selectedItems() if hasattr(self, "studio_image_health") else []
        if not items and hasattr(self, "studio_assets"):
            items = self.studio_assets.selectedItems()
        work_ids = []
        for item in items:
            row = item.data(0, Qt.ItemDataRole.UserRole) or {}
            work_id = str(row.get("id") or item.text(0) or "").strip()
            if work_id and work_id not in work_ids:
                work_ids.append(work_id)
        if not work_ids:
            QMessageBox.information(self, "No works selected", "Select one or more image health/source rows first.")
            return
        if QMessageBox.question(self, "Regenerate derivatives", f"Regenerate responsive derivatives for {len(work_ids)} selected work(s)?") != QMessageBox.StandardButton.Yes:
            return

        def task() -> dict[str, Any]:
            return regenerate_derivatives_for_work_ids(work_ids, line_callback=self._emit_line)

        def done(result: Any) -> None:
            regenerated = len((result or {}).get("regenerated") or [])
            failed = len((result or {}).get("failed") or [])
            self.clear_work_icon_cache()
            self.append_build_log_line(f"✓ Regenerated derivatives for {regenerated} work(s); failures: {failed}")
            self.push_notification("success" if failed == 0 else "warning", "Derivative regeneration finished", f"{regenerated} regenerated · {failed} failed.", target_scope="studio")
            self.refresh_all_context(force=True, scope={"works", "dashboard", "validation", "studio"})

        self.start_task("Regenerate derivatives", task, on_done=done)

    def studio_page_preview_target(self, page_key: str) -> Path:
        key = (page_key or "home").strip() or "home"
        filename = "index.html" if key == "home" else f"{key}.html"
        public_target = ROOT / "public_upload" / filename
        if public_target.exists():
            return public_target
        return ROOT / filename

    def _set_tab_loading(self, tab_widget: QWidget | None, loading: bool, message: str = "Refreshing…") -> None:
        if tab_widget is None:
            return
        try:
            overlay = self._loading_overlays.get(tab_widget)
            if loading:
                if overlay is None:
                    overlay = QFrame(tab_widget)
                    overlay.setObjectName("tabLoadingOverlay")
                    layout = QVBoxLayout(overlay)
                    layout.setContentsMargins(18, 18, 18, 18)
                    layout.addStretch(1)
                    label = QLabel(message)
                    label.setObjectName("tabLoadingLabel")
                    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    overlay._loading_label = label
                    layout.addWidget(label)
                    layout.addStretch(1)
                    self._loading_overlays[tab_widget] = overlay
                if hasattr(overlay, "_loading_label"):
                    overlay._loading_label.setText(message)
                overlay.setGeometry(tab_widget.rect())
                overlay.raise_()
                overlay.show()
            elif overlay is not None:
                overlay.hide()
        except Exception as exc:
            self._log_warning(f"Studio loading overlay update failed: {exc}")

    def _load_studio_data(self) -> dict[str, Any]:
        issues = validate_all()
        source_rows = source_asset_report_rows()
        registry = image_registry_summary()
        image_health = load_image_health_summary()
        checks = release_checks()
        txns = recent_operation_rows(20)
        published = [item for item in load_work_entries() if bool(item.get("published"))]
        touched_pages: set[str] = set()
        touched_series: set[str] = set()
        touched_works: set[str] = set()
        for txn in txns:
            for target in list(txn.get("targets") or []):
                target_text = str(target).replace("REL::", "")
                if target_text.startswith("content/pages/") and target_text.endswith((".yaml", ".yml")):
                    touched_pages.add(Path(target_text).stem)
                elif target_text.startswith("content/series/") and target_text.endswith((".yaml", ".yml")):
                    touched_series.add(Path(target_text).stem)
                elif target_text.startswith("content/works/") and target_text.endswith((".yaml", ".yml")):
                    touched_works.add(Path(target_text).stem)
        payload_ids: set[str] = set()
        for row in list(source_rows) + list(image_health.get("work_rows") or []):
            work_id = str(row.get("id") or "").strip()
            if work_id:
                payload_ids.add(work_id)
        work_payloads = {work_id: load_work_payload(work_id) for work_id in sorted(payload_ids)}
        return {
            "issues": issues,
            "source_rows": source_rows,
            "registry": registry,
            "image_health": image_health,
            "checks": checks,
            "txns": txns,
            "published_count": len(published),
            "touched_pages": sorted(touched_pages),
            "touched_series": sorted(touched_series),
            "touched_works": sorted(touched_works),
            "available_page_count": len(available_page_keys()),
            "available_series_count": len(available_series_slugs()),
            "work_payloads": work_payloads,
        }

    def refresh_studio(self) -> None:
        if not hasattr(self, "studio_inner_tabs"):
            self._mark_dirty({"studio"})
            return
        if self._studio_data_cache is not None and not self._studio_dirty and "studio" not in getattr(self, "_dirty_tabs", {}):
            self._populate_studio_visible_subview()
            self._update_studio_last_refreshed_label()
            return
        if getattr(self, "_studio_refresh_inflight", False):
            self._studio_dirty = True
            return
        self._studio_refresh_inflight = True
        self._set_tab_loading(self.studio_tab, True)
        self.start_task("Refreshing studio", self._load_studio_data, on_done=self._apply_studio_data)

    def _update_studio_last_refreshed_label(self) -> None:
        if not hasattr(self, "studio_last_refreshed_label"):
            return
        stamp = self._studio_last_refreshed_at
        if not stamp:
            self.studio_last_refreshed_label.setText("Last refreshed: never")
            return
        seconds = max(0, int((datetime.now() - stamp).total_seconds()))
        if seconds < 60:
            text = "just now"
        elif seconds < 3600:
            text = f"{seconds // 60} min ago"
        else:
            text = f"{seconds // 3600} hr ago"
        self.studio_last_refreshed_label.setText(f"Last refreshed: {text}")

    def _apply_studio_data(self, result: Any) -> None:
        started = time.perf_counter()
        data = dict(result or {})
        self._studio_data_cache = data
        self._studio_last_refreshed_at = datetime.now()
        self._studio_refresh_inflight = False
        self._studio_dirty = False
        self._dirty_tabs.pop("studio", None)
        self._populate_studio_metrics(data)
        self._populate_studio_visible_subview(force=True)
        self._update_studio_last_refreshed_label()
        self._set_tab_loading(self.studio_tab, False)
        self._record_perf("studio refresh", time.perf_counter() - started, f"{len(list(data.get('source_rows') or []))} source row(s)")

    def _populate_studio_metrics(self, data: dict[str, Any] | None = None) -> None:
        data = dict(data or self._studio_data_cache or {})
        issues = list(data.get("issues") or [])
        source_rows = list(data.get("source_rows") or [])
        image_health = dict(data.get("image_health") or {})
        published_count = int(data.get("published_count") or 0)
        validation_errors = sum(1 for item in issues if str(item.get("severity") or "").lower() == "error")
        asset_issues = sum(1 for row in source_rows if row.get("status") != "ok")
        coverage = image_health.get("coverage_percent")
        health_text = f"Health: {coverage}%" if coverage not in {None, ""} else "Health: —"
        if hasattr(self, "studio_metric_published"):
            self.studio_metric_published.setText(f"Published: {published_count}")
            self.studio_metric_published.set_status("ok" if published_count else "info", f"Published: {published_count}")
        if hasattr(self, "studio_metric_validation"):
            self.studio_metric_validation.setText(f"Validation: {validation_errors}")
            self.studio_metric_validation.set_status("error" if validation_errors else "ok", f"Validation: {validation_errors}")
        if hasattr(self, "studio_metric_assets"):
            self.studio_metric_assets.setText(f"Assets: {asset_issues}")
            self.studio_metric_assets.set_status("error" if asset_issues else "ok", f"Assets: {asset_issues}")
        if hasattr(self, "studio_metric_health"):
            self.studio_metric_health.setText(health_text)
            self.studio_metric_health.set_status("ok" if not asset_issues else "warning", health_text)
        if hasattr(self, "asset_health_bar"):
            work_rows = list(image_health.get("work_rows") or [])
            ok = warn = error = grey = 0
            for row in work_rows:
                status = str(row.get("status") or row.get("source_status") or "").lower()
                if status in {"broken", "missing", "error"}:
                    error += 1
                elif status in {"warning", "orphan-risk", "recoverable"}:
                    warn += 1
                elif status in {"derivative-only", "unknown"}:
                    grey += 1
                else:
                    ok += 1
            if not work_rows:
                for row in source_rows:
                    status = str(row.get("status") or "").lower()
                    if status == "ok": ok += 1
                    elif "recover" in str(row.get("recovery") or "").lower(): warn += 1
                    elif status: error += 1
            self.asset_health_bar.set_segments(ok, warn, error, grey)
        if hasattr(self, "studio_review_stepper"):
            statuses = ["ok", "error" if asset_issues else "ok", "error" if validation_errors else "ok"]
            self.studio_review_stepper.set_statuses(statuses)

    def _populate_studio_visible_subview(self, force: bool = False) -> None:
        data = dict(self._studio_data_cache or {})
        if not data or not hasattr(self, "studio_inner_tabs"):
            return
        index = self.studio_inner_tabs.currentIndex()
        if index == 0:
            self.refresh_studio_page_preview()
            self.refresh_studio_sequence_board()
        elif index == 1:
            self._populate_studio_image_health_view(data)
        else:
            self._populate_studio_release_view_from_cache(data)
        self._update_studio_last_refreshed_label()

    def _populate_studio_image_health_view(self, data: dict[str, Any]) -> None:
        source_rows = list(data.get("source_rows") or [])
        registry = dict(data.get("registry") or {})
        image_health = dict(data.get("image_health") or {})
        work_payloads = dict(data.get("work_payloads") or {})
        if hasattr(self, "studio_registry_hint"):
            self.studio_registry_hint.setPlainText(
                f"Source root: {registry.get('source_root')}\nGenerated root: {registry.get('generated_root')}\nManifest dir: {registry.get('manifest_dir')} · image rows {registry.get('image_index_rows')} · derivative rows {registry.get('derivative_index_rows')}"
            )
        if hasattr(self, "studio_image_health"):
            self.studio_image_health.clear()
            for row in sorted(list(image_health.get("work_rows") or []), key=lambda r: (str(r.get("status") or ""), str(r.get("series") or ""), str(r.get("id") or ""))):
                item = QTreeWidgetItem([str(row.get("id") or ""), str(row.get("series") or ""), str(row.get("status") or ""), str(row.get("source_dimensions") or row.get("source_status") or ""), str(row.get("preview_dimensions") or "missing"), str(row.get("derivative_count") or 0), str(row.get("focal") or "")])
                item.setData(0, Qt.ItemDataRole.UserRole, row)
                color = self._severity_color("error" if row.get("status") == "broken" else "warning" if row.get("status") == "warning" else "ok")
                for col in range(7): item.setForeground(col, color)
                self.studio_image_health.addTopLevelItem(item)
            self.update_studio_image_health_detail()
        if hasattr(self, "studio_assets"):
            self.studio_assets.clear()
            for row in sorted(source_rows, key=lambda row: (row.get("status") == "ok", str(row.get("series") or ""), str(row.get("id") or ""))):
                item = QTreeWidgetItem([str(row.get("id") or ""), str(row.get("series") or ""), str(row.get("status") or ""), str(row.get("recovery") or ""), ""])
                item.setData(0, Qt.ItemDataRole.UserRole, row)
                self.studio_assets.addTopLevelItem(item)
                status = str(row.get("status") or "").lower(); recovery = str(row.get("recovery") or "").lower()
                if status in {"missing", "recoverable"} or "recover" in recovery:
                    action_wrap = QWidget(); action_layout = QHBoxLayout(action_wrap); action_layout.setContentsMargins(0,0,0,0)
                    relink = QPushButton("Relink"); relink.setFixedWidth(62); relink.clicked.connect(lambda _checked=False, it=item: (self.studio_assets.setCurrentItem(it), self.relink_selected_studio_asset()))
                    verify = QPushButton("Verify"); verify.setFixedWidth(58); verify.clicked.connect(lambda _checked=False, wid=str(row.get("id") or ""): (self.tabs.setCurrentWidget(self.works_tab), self.select_work(wid), self.verify_current_work_assets()))
                    action_layout.addWidget(relink); action_layout.addWidget(verify); action_layout.addStretch(1)
                    self.studio_assets.setItemWidget(item, 4, action_wrap)
            self.update_studio_asset_detail()

    def _populate_studio_release_view_from_cache(self, data: dict[str, Any]) -> None:
        issues = list(data.get("issues") or [])
        checks = list(data.get("checks") or [])
        touched_pages = set(data.get("touched_pages") or [])
        touched_series = set(data.get("touched_series") or [])
        touched_works = set(data.get("touched_works") or [])
        if hasattr(self, "studio_validation"):
            self.studio_validation.clear()
            blocking_rows = [row for row in issues if str(row.get("severity") or "").lower() == "error"]
            for row in blocking_rows:
                item = QTreeWidgetItem([str(row.get("scope") or ""), str(row.get("id") or ""), str(row.get("severity") or ""), str(row.get("message") or "")])
                item.setData(0, Qt.ItemDataRole.UserRole, row)
                color = self._severity_color(str(row.get("severity") or "error"))
                for col in range(4): item.setForeground(col, color)
                self.studio_validation.addTopLevelItem(item)
            self.update_studio_validation_detail()
        if hasattr(self, "studio_release_checks"):
            self.studio_release_checks.clear()
            for row in checks:
                item = QTreeWidgetItem([str(row.get("area") or ""), str(row.get("status") or ""), str(row.get("detail") or "")])
                item.setData(0, Qt.ItemDataRole.UserRole, row)
                color = self._severity_color(str(row.get("status") or "info"))
                for col in range(3): item.setForeground(col, color)
                self.studio_release_checks.addTopLevelItem(item)
            extra = QTreeWidgetItem(["Recent changes", "info", f"Pages {', '.join(sorted(touched_pages)) or 'none'} · Series {', '.join(sorted(touched_series)) or 'none'} · Works {len(touched_works)}"])
            extra.setData(0, Qt.ItemDataRole.UserRole, {"area": "Recent changes", "status": "info", "detail": extra.text(2), "pages": sorted(touched_pages), "series": sorted(touched_series), "works": sorted(touched_works)[:40]})
            self.studio_release_checks.addTopLevelItem(extra)
            self.update_studio_release_detail()

    def refresh_studio_page_preview(self) -> None:
        page_key = getattr(self, "studio_page_combo", None).currentText().strip() if hasattr(self, "studio_page_combo") else "home"
        if not page_key:
            page_key = "home"
        try:
            payload = yaml.safe_load(load_page_yaml_text(page_key)) or {}
        except Exception as exc:
            self.studio_page_text.setPlainText(f"Page YAML could not be loaded for {page_key}: {exc}")
            self._set_preview_label(self.studio_page_preview, None, fallback="Page preview unavailable.", size=QSize(520, 300))
            return
        hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
        work_id = str(hero.get("feature_work_id") or payload.get("feature_work_id") or self._studio_selected_work_id or self._studio_sequence_cover_id or "").strip()
        image_path = None
        if work_id:
            work_payload = load_work_payload(work_id)
            if work_payload:
                image_path = best_preview_path_for_work(work_payload)
        lines = [
            f"Page: {page_key}",
            f"Title: {hero.get('title') or payload.get('hero_title') or '-'}",
            f"Eyebrow: {hero.get('eyebrow') or payload.get('hero_eyebrow') or '-'}",
            f"Lead: {hero.get('lead') or payload.get('hero_lead') or '-'}",
            f"Feature work: {work_id or '-'}",
        ]
        notes = hero.get("notes") if isinstance(hero.get("notes"), list) else []
        if notes:
            lines.append("Notes: " + ", ".join(str(item) for item in notes))
        self.studio_page_text.setPlainText("\n".join(lines))
        self._set_preview_label(self.studio_page_preview, image_path, fallback="No preview available for the selected page hero.", size=QSize(520, 300))

    def open_studio_page_preview(self) -> None:
        page_key = getattr(self, "studio_page_combo", None).currentText().strip() if hasattr(self, "studio_page_combo") else "home"
        target = self.studio_page_preview_target(page_key)
        webbrowser.open(target.as_uri())
        self.status_message(f"Opened preview: {target.name}")

    def refresh_studio_sequence_board(self) -> None:
        slug = getattr(self, "studio_series_combo", None).currentText().strip() if hasattr(self, "studio_series_combo") else ""
        self.studio_sequence.clear()
        if not slug:
            self._studio_sequence_order = []
            self._studio_sequence_cover_id = ""
            self._studio_selected_work_id = ""
            self.update_studio_sequence_preview()
            return
        payload = load_series_payload(slug) or {}
        self._studio_sequence_order = [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]
        self._studio_sequence_cover_id = str(payload.get("cover_work_id") or "").strip()
        if self._studio_selected_work_id not in self._studio_sequence_order:
            self._studio_selected_work_id = self._studio_sequence_order[0] if self._studio_sequence_order else ""
        for index, work_id in enumerate(self._studio_sequence_order, start=1):
            work_payload = load_work_payload(work_id) or {}
            item = QTreeWidgetItem([
                str(index),
                work_id,
                str(work_payload.get("title") or ""),
                str(work_payload.get("review_status") or ""),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, work_payload)
            if work_id == self._studio_sequence_cover_id:
                item.setText(2, f"★ {item.text(2)}" if item.text(2) else "★")
            icon = self.work_tree_icon(work_payload)
            if not icon.isNull():
                item.setIcon(1, icon)
            self.studio_sequence.addTopLevelItem(item)
            if work_id == self._studio_selected_work_id:
                self.studio_sequence.setCurrentItem(item)
        self.update_studio_sequence_preview()

    def update_studio_sequence_preview(self) -> None:
        item = self.studio_sequence.currentItem() if hasattr(self, "studio_sequence") else None
        if item is None:
            self._studio_selected_work_id = ""
            self.studio_sequence_detail.setPlainText("Select a work in the current series sequence to inspect it.")
            self._set_preview_label(self.studio_sequence_preview, None, fallback="Select a work in the studio sequence to preview it.", size=QSize(520, 300))
            self.refresh_studio_page_preview()
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole) or {}
        work_id = str(payload.get("id") or item.text(1) or "").strip()
        self._studio_selected_work_id = work_id
        image_path = best_preview_path_for_work(payload)
        series_slug = getattr(self, "studio_series_combo", None).currentText().strip() if hasattr(self, "studio_series_combo") else ""
        try:
            index = self._studio_sequence_order.index(work_id) + 1
        except ValueError:
            index = 0
        lines = [
            f"Work ID: {work_id or '-'}",
            f"Series: {series_slug or payload.get('series') or '-'}",
            f"Position: {index or '—'} / {len(self._studio_sequence_order)}",
            f"Review: {payload.get('review_status') or '-'}",
            f"Published: {'yes' if bool(payload.get('published')) else 'no'}",
            f"Title: {payload.get('title') or '-'}",
            f"Caption: {payload.get('caption') or '-'}",
        ]
        if work_id == self._studio_sequence_cover_id:
            lines.append("Cover: yes")
        self.studio_sequence_detail.setPlainText("\n".join(lines))
        self._set_preview_label(self.studio_sequence_preview, image_path, fallback="No preview available for selected sequence work.", size=QSize(520, 300))
        self.refresh_studio_page_preview()

    def move_studio_sequence_item(self, direction: int) -> None:
        work_id = self._studio_selected_work_id
        if not work_id or work_id not in self._studio_sequence_order:
            return
        idx = self._studio_sequence_order.index(work_id)
        new_idx = max(0, min(len(self._studio_sequence_order) - 1, idx + direction))
        if new_idx == idx:
            return
        self._studio_sequence_order.insert(new_idx, self._studio_sequence_order.pop(idx))
        self.refresh_studio_sequence_board()

    def set_studio_sequence_cover(self) -> None:
        if not self._studio_selected_work_id:
            return
        self._studio_sequence_cover_id = self._studio_selected_work_id
        self.refresh_studio_sequence_board()
        self.status_message(f"Studio cover set: {self._studio_selected_work_id}")

    def set_studio_series_page_hero(self) -> None:
        work_id = self._studio_selected_work_id
        if not work_id:
            return
        try:
            payload = yaml.safe_load(load_page_yaml_text("series")) or {}
            hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
            hero["feature_work_id"] = work_id
            payload["hero"] = hero
            save_page_yaml_text("series", yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
            self.select_page("series")
            self.refresh_studio_page_preview()
            self.push_notification("success", "Series page hero updated", f"Studio set the series page hero to {work_id}.", target_scope="pages", target_id="series")
            self.status_message(f"Set series page hero: {work_id}")
        except Exception as exc:
            QMessageBox.critical(self, "Set series page hero failed", str(exc))

    def suggest_studio_series_order(self) -> None:
        series_slug = self.studio_series_combo.currentText().strip() if hasattr(self, "studio_series_combo") else ""
        if not series_slug:
            return
        try:
            proposed = suggest_series_order(series_slug)
        except Exception as exc:
            QMessageBox.critical(self, "Suggest order failed", str(exc))
            return
        if not proposed:
            QMessageBox.information(self, "No suggestion", "No works were available for this series.")
            return
        preview = "\n".join(f"{i+1}. {work_id}" for i, work_id in enumerate(proposed[:40]))
        if QMessageBox.question(self, "Apply suggested order?", "Suggested visual-rhythm order:\n\n" + preview + "\n\nApply this order to the Review sequence board?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self._studio_sequence_order = proposed
        self.refresh_studio_sequence_board()
        self.status_message("Suggested order applied to board; click Save sequence to persist.")

    def save_studio_sequence(self) -> None:
        slug = getattr(self, "studio_series_combo", None).currentText().strip() if hasattr(self, "studio_series_combo") else ""
        if not slug:
            return
        try:
            payload = load_series_payload(slug) or {}
            payload["work_ids"] = list(self._studio_sequence_order)
            payload["cover_work_id"] = self._studio_sequence_cover_id
            save_series_from_payload(slug, payload)
            self.refresh_series_list()
            self.refresh_studio_sequence_board()
            self.push_notification("success", "Studio sequence saved", f"Saved sequence and cover for {slug}.", target_scope="series", target_id=slug)
            self.status_message(f"Saved studio sequence: {slug}")
        except Exception as exc:
            QMessageBox.critical(self, "Save studio sequence failed", str(exc))

    def open_studio_series_in_series_tab(self) -> None:
        slug = getattr(self, "studio_series_combo", None).currentText().strip() if hasattr(self, "studio_series_combo") else ""
        if not slug:
            return
        self.tabs.setCurrentWidget(self.series_tab)
        self.select_series(slug)

    def refresh_studio_release_view(self) -> None:
        checks = release_checks()
        txns = recent_operation_rows(20)
        touched_pages: set[str] = set()
        touched_series: set[str] = set()
        touched_works: set[str] = set()
        for txn in txns:
            for target in list(txn.get("targets") or []):
                target_text = str(target).replace("REL::", "")
                if target_text.startswith("content/pages/") and target_text.endswith((".yaml", ".yml")):
                    touched_pages.add(Path(target_text).stem)
                elif target_text.startswith("content/series/") and target_text.endswith((".yaml", ".yml")):
                    touched_series.add(Path(target_text).stem)
                elif target_text.startswith("content/works/") and target_text.endswith((".yaml", ".yml")):
                    touched_works.add(Path(target_text).stem)
        if hasattr(self, "studio_release_checks"):
            self.studio_release_checks.clear()
            for row in checks:
                item = QTreeWidgetItem([str(row.get("area") or ""), str(row.get("status") or ""), str(row.get("detail") or "")])
                item.setData(0, Qt.ItemDataRole.UserRole, row)
                color = self._severity_color(str(row.get("status") or "info"))
                for col in range(3):
                    item.setForeground(col, color)
                self.studio_release_checks.addTopLevelItem(item)
            changes = {
                "area": "Recent changes",
                "status": "info",
                "detail": f"Pages {', '.join(sorted(touched_pages)) or 'none'} · Series {', '.join(sorted(touched_series)) or 'none'} · Works {len(touched_works)}",
                "pages": sorted(touched_pages),
                "series": sorted(touched_series),
                "works": sorted(touched_works)[:60],
            }
            extra = QTreeWidgetItem([changes["area"], changes["status"], changes["detail"]])
            extra.setData(0, Qt.ItemDataRole.UserRole, changes)
            self.studio_release_checks.addTopLevelItem(extra)
        self.update_studio_release_detail()

    def update_studio_release_detail(self) -> None:
        item = getattr(self, "studio_release_checks", None).currentItem() if hasattr(self, "studio_release_checks") else None
        if item is None:
            if hasattr(self, "studio_release_detail"):
                self.studio_release_detail.setPlainText("Select a release-check row to inspect current publish readiness.")
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        lines = [
            f"Area: {row.get('area') or '-'}",
            f"Status: {row.get('status') or '-'}",
            "",
            str(row.get('detail') or '-'),
        ]
        pages = row.get("pages") or []
        series = row.get("series") or []
        works = row.get("works") or []
        if pages:
            lines.append("")
            lines.append("Pages touched: " + ", ".join(str(item) for item in pages))
        if series:
            lines.append("Series touched: " + ", ".join(str(item) for item in series))
        if works:
            lines.append("Works touched: " + ", ".join(str(item) for item in works[:20]))
        self.studio_release_detail.setPlainText("\n".join(lines))

    def update_studio_image_health_detail(self) -> None:
        item = getattr(self, "studio_image_health", None).currentItem() if hasattr(self, "studio_image_health") else None
        if item is None:
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        lines = [
            f"Work ID: {row.get('id') or '-'}",
            f"Title: {row.get('title') or '-'}",
            f"Series: {row.get('series') or '-'}",
            f"Health: {row.get('status') or '-'}",
            f"Source status: {row.get('source_status') or '-'}",
            f"Source: {row.get('source_path') or '-'}",
            f"Source dimensions: {row.get('source_dimensions') or '-'} · {row.get('source_size') or ''}",
            f"Preview: {row.get('preview_path') or '-'}",
            f"Preview dimensions: {row.get('preview_dimensions') or '-'} · {row.get('preview_size') or ''}",
            f"Derivatives: {row.get('derivative_count') or 0}",
            f"Focal point: {row.get('focal') or '-'}",
            "",
            f"Detail: {row.get('detail') or '-'}",
            f"Recovery: {row.get('recovery') or '-'}",
        ]
        if hasattr(self, "studio_asset_detail"):
            self.studio_asset_detail.setPlainText("\n".join(lines))
        self._set_preview_label(self.studio_asset_preview, row.get("preview_path") or row.get("source_path"), fallback="No preview file available for this image health row.", size=QSize(520, 320))

    def update_studio_asset_detail(self) -> None:
        item = self.studio_assets.currentItem()
        if item is None:
            self.studio_asset_detail.setPlainText("Select a source-asset row to inspect missing-source status and recovery path.")
            self._set_preview_label(self.studio_asset_preview, None, fallback="Select a source-asset row to preview the best available image.", size=QSize(520, 320))
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        expected = ", ".join(row.get("expected_stems") or []) or "-"
        lines = [
            f"Work ID: {row.get('id') or '-'}",
            f"Series: {row.get('series') or '-'}",
            f"Status: {row.get('status') or '-'}",
            f"Expected names: {expected}",
            f"Detail: {row.get('detail') or '-'}",
            f"Recovery: {row.get('recovery') or '-'}",
        ]
        self.studio_asset_detail.setPlainText("\n".join(lines))
        self._set_preview_label(self.studio_asset_preview, row.get("preview_path"), fallback="No preview file available for this source-asset row.", size=QSize(520, 320))

    def update_studio_validation_detail(self) -> None:
        item = getattr(self, "studio_validation", None).currentItem() if hasattr(self, "studio_validation") else None
        if item is None:
            if hasattr(self, "studio_validation_detail"):
                self.studio_validation_detail.setPlainText("No blocking validation issue selected.")
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        lines = [
            f"Scope: {row.get('scope') or '-'}",
            f"ID: {row.get('id') or '-'}",
            f"Severity: {row.get('severity') or '-'}",
            "",
            str(row.get('message') or '-'),
        ]
        self.studio_validation_detail.setPlainText("\n".join(lines))

    def open_selected_studio_issue(self) -> None:
        item = getattr(self, "studio_validation", None).currentItem() if hasattr(self, "studio_validation") else None
        if item is None:
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        scope = row.get("scope")
        target = str(row.get("id") or "")
        if scope == "work":
            self.tabs.setCurrentWidget(self.works_tab)
            self.select_work(target)
        elif scope == "series":
            self.tabs.setCurrentWidget(self.series_tab)
            self.select_series(target)
        elif scope == "page":
            self.tabs.setCurrentWidget(self.pages_tab)
            self.select_page(target)

    def _selected_studio_asset_row(self) -> dict[str, Any]:
        item = None
        if hasattr(self, "studio_assets"):
            item = self.studio_assets.currentItem()
        if item is None and hasattr(self, "studio_image_health"):
            item = self.studio_image_health.currentItem()
        return dict(item.data(0, Qt.ItemDataRole.UserRole) or {}) if item is not None else {}

    def show_selected_studio_asset_repair_plan(self) -> None:
        row = self._selected_studio_asset_row()
        if not row:
            self._info_nonblocking("No image row selected", "Select an Image Health or Source Asset row first.", target_scope="studio")
            return
        work_id = str(row.get("id") or "").strip()
        status = str(row.get("status") or row.get("source_status") or "-")
        recovery = str(row.get("recovery") or "-")
        expected = ", ".join(str(item) for item in (row.get("expected_stems") or [])) or "-"
        source_path = str(row.get("source_path") or row.get("source") or "-")
        preview_path = str(row.get("preview_path") or row.get("preview") or "-")
        lines = [
            f"Work ID: {work_id or '-'}",
            f"Current status: {status}",
            f"Expected source names: {expected}",
            f"Current source: {source_path}",
            f"Current preview: {preview_path}",
            "",
            "Safe repair plan:",
        ]
        if status.lower() in {"ok", "healthy"}:
            lines.append("• No repair recommended. Use Verify if you want to re-check the selected work.")
        elif "recover" in recovery.lower() or status.lower() in {"missing", "recoverable"}:
            lines.extend([
                "• Search known generated/manifest locations for a recoverable original.",
                "• Copy/relink the source into the expected source folder.",
                "• Reconcile image presence and mark Studio/Works/Publish dirty.",
                "• Regenerate derivatives only after the source path is clean.",
            ])
        else:
            lines.extend([
                "• Prefer Relink selected… if you have the original image file.",
                "• Use Repair selected only when the recovery column says the source is recoverable.",
                "• Avoid deleting anything manually until the transaction report confirms stale paths.",
            ])
        QMessageBox.information(self, "Image repair plan", "\n".join(lines))

    def repair_selected_studio_asset(self) -> None:
        item = self.studio_assets.currentItem()
        if item is None:
            QMessageBox.information(self, "No source-asset row selected", "Select a source-asset row first.")
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        work_id = str(row.get("id") or "")
        if not work_id:
            return
        recovery_text = str(row.get("recovery") or row.get("status") or "").lower()
        if "recover" not in recovery_text and row.get("status") not in {"missing", "recoverable"}:
            if QMessageBox.question(self, "Repair may not be applicable", "This row does not advertise a recoverable source. Show the repair plan instead of running repair?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes) == QMessageBox.StandardButton.Yes:
                self.show_selected_studio_asset_repair_plan()
                return
        self.append_build_log_line(f"Checking source asset for {work_id}…")

        def task() -> list[dict[str, str]]:
            return recover_missing_source_images([work_id], line_callback=self._emit_line)

        self.start_task(f"Repair source {work_id}", task, on_done=self._repair_sources_done)

    def relink_selected_studio_asset(self) -> None:
        item = self.studio_assets.currentItem()
        if item is None:
            QMessageBox.information(self, "No source-asset row selected", "Select a source-asset row first.")
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        work_id = str(row.get("id") or "")
        if not work_id:
            return
        path, _ = QFileDialog.getOpenFileName(self, f"Relink source for {work_id}", str(ROOT), "Images (*.jpg *.jpeg *.png *.webp *.tif *.tiff)")
        if not path:
            return
        self.append_build_log_line(f"Relinking source image for {work_id}…")

        def task() -> dict[str, str]:
            return relink_source_image(work_id, path, line_callback=self._emit_line)

        self.start_task(f"Relink source {work_id}", task, on_done=self._relink_source_done)

    def bulk_relink_sources_from_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose folder containing original images", str(ROOT))
        if not folder:
            return
        self.append_build_log_line(f"Scanning folder for missing source images: {folder}")

        def task() -> list[dict[str, str]]:
            return bulk_relink_missing_sources(folder, line_callback=self._emit_line)

        self.start_task("Bulk relink sources", task, on_done=self._bulk_relink_done)

    def refresh_source_reports(self) -> None:
        self.refresh_publish_source_panel()



    # ---------- Review/Publish disclosure helpers ----------
    def _configure_drawer_group(self, group: QGroupBox, *, checked: bool = False) -> None:
        """Use QGroupBox as a progressive-disclosure drawer without losing functionality."""
        group.setCheckable(True)
        group.setChecked(bool(checked))

        def update(visible: bool) -> None:
            for child in group.findChildren(QWidget):
                if child is group:
                    continue
                child.setVisible(bool(visible))
        group.toggled.connect(update)
        QTimer.singleShot(0, lambda: update(bool(checked)))

    def _make_menu_button(self, label: str, actions: list[tuple[str, Callable[[], None]]]) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("menuActionButton")
        menu = QMenu(self)
        for action_label, slot in actions:
            action = QAction(action_label, self)
            action.triggered.connect(slot)
            menu.addAction(action)
        button.setMenu(menu)
        return button


    def _set_publish_workflow_state(self) -> None:
        """Live release gate state without doing heavy validation/source scans.

        Expensive source truth and release artifact discovery run through explicit
        Check/Refresh actions. This method reflects cached state so normal tab
        painting stays responsive.
        """
        if not hasattr(self, "publish_stepper"):
            return
        try:
            last_status = str(getattr(self, "_last_build_status", "") or "")
            build_failed = "failed" in last_status.lower()
            source_cache = getattr(self, "_publish_source_cache", None)
            source_rows = list((source_cache or {}).get("rows") or []) if isinstance(source_cache, dict) else []
            source_blockers = [row for row in source_rows if row.get("status") != "ok"]
            archives = list(getattr(self, "_release_artifact_cache", []) or [])
            has_archive = bool(archives or getattr(self, "_last_publish_archive", ""))
            check_passed = bool(getattr(self, "_publish_check_passed", False)) and not source_blockers and not build_failed
            check_state = "error" if source_blockers or build_failed else "ok" if check_passed else "warning"
            package_state = "ok" if has_archive else "warning" if check_passed else "locked"
            upload_state = "ok" if has_archive else "locked"
            self.publish_stepper.set_statuses([check_state, package_state, upload_state])
            archive_hint = ""
            if has_archive:
                first_archive = archives[0] if archives else {}
                archive_hint = Path(str(getattr(self, "_last_publish_archive", "") or first_archive.get("path") or first_archive.get("name") or "")).name
            self.publish_stepper.set_tooltips([
                f"Cached check state · source blockers: {len(source_blockers)}",
                "Package is enabled after Check passes." if not has_archive else f"Archive ready: {archive_hint}",
                "Open or copy public_upload after packaging." if has_archive else "Locked until Package succeeds.",
            ])
            if hasattr(self, "publish_package_btn"):
                self.publish_package_btn.setEnabled(check_passed)
            if hasattr(self, "publish_upload_btn"):
                self.publish_upload_btn.setEnabled(has_archive)
            if hasattr(self, "copy_upload_path_btn"):
                self.copy_upload_path_btn.setEnabled(has_archive)
            if hasattr(self, "publish_gate_label"):
                if source_blockers or build_failed:
                    self.publish_gate_label.set_status("error", f"Blocked · {len(source_blockers)} cached source blocker(s)")
                elif check_passed:
                    self.publish_gate_label.set_status("ok", "Checked · ready to package")
                else:
                    self.publish_gate_label.set_status("warning", "Run Check before packaging")
        except Exception as exc:
            self._log_warning(f"Publish workflow state update failed: {exc}")

    def _sync_publish_review_panels(
        self,
        errors: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        source_blockers: list[dict[str, Any]],
        archives: list[dict[str, Any]],
        has_build: bool,
        build_failed: bool,
        last_status: str,
    ) -> None:
        """Render blockers, advisories, and the final release checklist without changing public output."""
        if hasattr(self, "publish_blockers_tree"):
            self.publish_blockers_tree.clear()
            blocker_rows: list[tuple[str, str, str]] = []
            for row in errors:
                blocker_rows.append((str(row.get("area") or row.get("file") or "Validation"), str(row.get("message") or row.get("detail") or row), str(row.get("target") or row.get("path") or "")))
            for row in source_blockers:
                blocker_rows.append(("Source asset", str(row.get("detail") or row.get("status") or "Missing source image"), str(row.get("id") or row.get("work_id") or "")))
            if build_failed:
                blocker_rows.append(("Package", last_status or "Package failed", "Publish"))
            if not blocker_rows:
                blocker_rows.append(("Clear", "No blocking release issues detected in the current panel state.", ""))
            for area, detail, target in blocker_rows[:80]:
                item = QTreeWidgetItem([area, detail, target])
                color = self._severity_color("ok" if area == "Clear" else "error")
                for col in range(3):
                    item.setForeground(col, color)
                self.publish_blockers_tree.addTopLevelItem(item)
        if hasattr(self, "publish_warnings_tree"):
            self.publish_warnings_tree.clear()
            warning_rows: list[tuple[str, str, str]] = []
            for row in warnings:
                warning_rows.append((str(row.get("area") or row.get("file") or "Validation"), str(row.get("message") or row.get("detail") or row), str(row.get("target") or row.get("path") or "")))
            if not has_build:
                warning_rows.append(("Package", "No successful package has run in this session.", "Run Package"))
            if not warning_rows:
                warning_rows.append(("Clear", "No advisory warnings for the current release state.", ""))
            for area, detail, target in warning_rows[:80]:
                item = QTreeWidgetItem([area, detail, target])
                color = self._severity_color("ok" if area == "Clear" else "warning")
                for col in range(3):
                    item.setForeground(col, color)
                self.publish_warnings_tree.addTopLevelItem(item)
        if hasattr(self, "publish_checklist_tree"):
            self.publish_checklist_tree.clear()
            checklist = [
                ("Check", "ok" if not errors and not source_blockers else "error", f"{len(errors)} validation blocker(s), {len(source_blockers)} source blocker(s), {len(warnings)} warning(s)"),
                ("Package", "error" if build_failed else "ok" if has_build else "warning", f"{len(archives)} archive(s) available" if has_build else "Run Package after Check passes"),
                ("Upload", "ok" if has_build else "locked", "Open or copy public_upload after packaging" if has_build else "Locked until Package succeeds"),
            ]
            for label, state, detail in checklist:
                item = QTreeWidgetItem([label, state, detail])
                color = self._severity_color(state)
                for col in range(3):
                    item.setForeground(col, color)
                self.publish_checklist_tree.addTopLevelItem(item)
        if hasattr(self, "publish_summary"):
            lines = [
                "Release flow is intentionally reduced to three decisions: Check, Package, Upload.",
                f"Blockers: {len(errors) + len(source_blockers) + (1 if build_failed else 0)}",
                f"Warnings: {len(warnings) + (0 if has_build else 1)}",
                f"Package: {'ready' if has_build else 'not prepared'}",
                f"Archives: {len(archives)}",
            ]
            self.publish_summary.setPlainText("\n".join(lines))

    # ---------- publish ops ----------
    def _configure_publish_tree(self, tree: QTreeWidget, key: str, *, stretch_column: int = 1, min_height: int = 170) -> None:
        """Publish-tab-only tree polish: stable row height, readable columns, and visible card styling."""
        tree.setObjectName(key)
        tree.setRootIsDecorated(False)
        tree.setAllColumnsShowFocus(True)
        tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        tree.setMinimumHeight(int(min_height))
        tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._polish_data_tree(tree, key)
        try:
            header = tree.header()
            header.setStretchLastSection(False)
            header.setHighlightSections(False)
            header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            for column in range(tree.columnCount()):
                mode = QHeaderView.ResizeMode.Stretch if column == stretch_column else QHeaderView.ResizeMode.ResizeToContents
                header.setSectionResizeMode(column, mode)
        except Exception as exc:
            self._log_warning(f"Could not configure publish tree '{key}': {exc}")

    def _publish_button(self, text: str, slot: Callable[[], None], *, role: str = "secondary", enabled: bool = True) -> QPushButton:
        """Create a consistently styled Publish-tab action button without touching other tabs."""
        button = QPushButton(text)
        button.setObjectName("publishPrimaryAction" if role == "primary" else "publishSecondaryAction")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        button.setEnabled(enabled)
        return button

    def build_publish_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.publish_inner_tabs = QTabWidget()
        self.publish_inner_tabs.setObjectName("publishInnerTabs")
        layout.addWidget(self.publish_inner_tabs, 1)

        publish_page = QWidget()
        publish_outer_layout = QVBoxLayout(publish_page)
        publish_outer_layout.setContentsMargins(0, 0, 0, 0)
        publish_outer_layout.setSpacing(0)
        publish_scroll = QScrollArea()
        publish_scroll.setObjectName("publishScrollArea")
        publish_scroll.setWidgetResizable(True)
        publish_scroll.setFrameShape(QFrame.Shape.NoFrame)
        publish_canvas = QWidget()
        publish_canvas.setObjectName("publishCanvas")
        publish_layout = QVBoxLayout(publish_canvas)
        publish_layout.setContentsMargins(12, 12, 12, 18)
        publish_layout.setSpacing(14)
        publish_scroll.setWidget(publish_canvas)
        publish_outer_layout.addWidget(publish_scroll, 1)

        history_page = QWidget(); history_layout = QVBoxLayout(history_page)
        workbook_page = QWidget(); workbook_layout = QVBoxLayout(workbook_page)
        self.publish_inner_tabs.addTab(publish_page, "Publish")
        self.publish_inner_tabs.addTab(history_page, "History")
        self.publish_inner_tabs.addTab(workbook_page, "Workbook")
        try:
            self.publish_inner_tabs.setTabVisible(2, False)
        except Exception as exc:
            self._log_warning(f"Could not hide advanced workbook tab: {exc}")

        # Hero: the daily release path is intentionally one clear flow, not a wall of widgets.
        primary = QFrame()
        primary.setObjectName("publishHeroCard")
        primary_layout = QVBoxLayout(primary)
        primary_layout.setContentsMargins(18, 16, 18, 16)
        primary_layout.setSpacing(12)

        hero_header = QHBoxLayout()
        hero_header.setContentsMargins(0, 0, 0, 0)
        hero_header.setSpacing(12)
        hero_copy = QVBoxLayout()
        hero_copy.setContentsMargins(0, 0, 0, 0)
        hero_copy.setSpacing(3)
        eyebrow = QLabel("RELEASE WORKFLOW")
        eyebrow.setObjectName("publishEyebrow")
        title = QLabel("Publish gate")
        title.setObjectName("publishHeroTitle")
        subtitle = QLabel("Validate blockers first, package only when clean, then open the upload folder. The website output remains untouched until you run the release actions.")
        subtitle.setObjectName("publishHeroSubtitle")
        subtitle.setWordWrap(True)
        hero_copy.addWidget(eyebrow)
        hero_copy.addWidget(title)
        hero_copy.addWidget(subtitle)
        hero_header.addLayout(hero_copy, 1)
        self.publish_gate_label = StatusBadge("Release gate not evaluated", "info")
        self.publish_gate_label.setObjectName("releaseGateBadge")
        self.publish_gate_label.setMinimumWidth(220)
        hero_header.addWidget(self.publish_gate_label, 0, Qt.AlignmentFlag.AlignTop)
        primary_layout.addLayout(hero_header)

        flow = QHBoxLayout()
        flow.setContentsMargins(0, 0, 0, 0)
        flow.setSpacing(8)
        self.publish_check_btn = self._publish_button("1 · Check", self.run_publish_check_step, role="primary")
        self.publish_package_btn = self._publish_button("2 · Package", self.run_prepare_publish, role="primary", enabled=False)
        self.publish_upload_btn = self._publish_button("3 · Upload folder", self.open_public_upload_folder, role="primary", enabled=False)
        self.copy_upload_path_btn = self._publish_button("Copy upload path", self.copy_public_upload_path, enabled=False)
        self.build_btn = QPushButton("Build site")
        self.build_btn.clicked.connect(self.run_build_site)
        self.build_btn.hide()
        self._build_trigger_widgets.append(self.build_btn)
        workbook_tools_btn = self._publish_button("Advanced workbook", self.show_publish_workbook_tools)
        workbook_tools_btn.setToolTip("Shows workbook import/export tools. Hidden by default to keep publish workflow linear.")
        self.open_changed_output_btn = self._publish_button("Open changed output", self.show_public_output_diff)
        self.open_changed_output_btn.hide()
        for btn in (self.publish_check_btn, self.publish_package_btn, self.publish_upload_btn, self.copy_upload_path_btn, self.open_changed_output_btn, workbook_tools_btn):
            flow.addWidget(btn)
        flow.addStretch(1)
        primary_layout.addLayout(flow)

        advanced_flow = QHBoxLayout()
        advanced_flow.setContentsMargins(0, 0, 0, 0)
        advanced_flow.setSpacing(8)
        advanced_flow.addWidget(self.build_btn)
        advanced_release_btn = self._publish_button("Advanced release workspace…", self.open_release_workspace)
        advanced_flow.addWidget(advanced_release_btn)
        advanced_flow.addStretch(1)
        primary_layout.addLayout(advanced_flow)

        self.publish_stepper = WorkflowStepper(["Check", "Package", "Upload"])
        self.publish_stepper.setObjectName("publishWorkflowStepper")
        self.publish_stepper.setToolTip("Guided release workflow. Package unlocks only after Check passes.")
        primary_layout.addWidget(self.publish_stepper)
        self.publish_summary = QPlainTextEdit()
        self.publish_summary.setObjectName("publishSummaryBox")
        self.publish_summary.setReadOnly(True)
        self.publish_summary.setFixedHeight(88)
        self.publish_summary.setAccessibleName("Publish release summary")
        primary_layout.addWidget(self.publish_summary)
        publish_layout.addWidget(primary)

        review_wrap = QFrame()
        review_wrap.setObjectName("publishSectionCard")
        review_layout = QVBoxLayout(review_wrap)
        review_layout.setContentsMargins(18, 16, 18, 16)
        review_layout.setSpacing(12)
        review_header_row = QHBoxLayout()
        review_header_row.setContentsMargins(0, 0, 0, 0)
        review_title_block = QVBoxLayout()
        review_title_block.setContentsMargins(0, 0, 0, 0)
        review_title_block.setSpacing(2)
        review_header = QLabel("Release review")
        review_header.setObjectName("publishSectionTitle")
        review_detail = QLabel("Blockers and advisories are split so the next decision is visible instead of buried in one dense table.")
        review_detail.setObjectName("publishSectionSubtitle")
        review_detail.setWordWrap(True)
        review_title_block.addWidget(review_header)
        review_title_block.addWidget(review_detail)
        review_header_row.addLayout(review_title_block, 1)
        review_layout.addLayout(review_header_row)

        review_split = QSplitter(Qt.Orientation.Horizontal)
        review_split.setObjectName("publishReviewSplitter")
        review_split.setChildrenCollapsible(False)
        blockers_box = QFrame(); blockers_box.setObjectName("publishIssueBox")
        blockers_layout = QVBoxLayout(blockers_box); blockers_layout.setContentsMargins(12, 10, 12, 12); blockers_layout.setSpacing(8)
        blockers_title = QLabel("Blocking issues")
        blockers_title.setObjectName("publishSubsectionTitle")
        blockers_layout.addWidget(blockers_title)
        self.publish_blockers_tree = QTreeWidget()
        self.publish_blockers_tree.setHeaderLabels(["Area", "Detail", "Target"])
        self._configure_publish_tree(self.publish_blockers_tree, "publish_blockers", stretch_column=1, min_height=190)
        blockers_layout.addWidget(self.publish_blockers_tree, 1)
        warnings_box = QFrame(); warnings_box.setObjectName("publishIssueBox")
        warnings_layout = QVBoxLayout(warnings_box); warnings_layout.setContentsMargins(12, 10, 12, 12); warnings_layout.setSpacing(8)
        warnings_title = QLabel("Advisory warnings")
        warnings_title.setObjectName("publishSubsectionTitle")
        warnings_layout.addWidget(warnings_title)
        self.publish_warnings_tree = QTreeWidget()
        self.publish_warnings_tree.setHeaderLabels(["Area", "Detail", "Target"])
        self._configure_publish_tree(self.publish_warnings_tree, "publish_warnings", stretch_column=1, min_height=190)
        warnings_layout.addWidget(self.publish_warnings_tree, 1)
        review_split.addWidget(blockers_box)
        review_split.addWidget(warnings_box)
        review_split.setSizes([620, 620])
        review_layout.addWidget(review_split, 1)

        checklist_panel = QFrame()
        checklist_panel.setObjectName("publishChecklistPanel")
        checklist_layout = QVBoxLayout(checklist_panel)
        checklist_layout.setContentsMargins(12, 10, 12, 12)
        checklist_layout.setSpacing(8)
        checklist_label = QLabel("Final package checklist")
        checklist_label.setObjectName("publishSubsectionTitle")
        checklist_layout.addWidget(checklist_label)
        self.publish_checklist_tree = QTreeWidget()
        self.publish_checklist_tree.setHeaderLabels(["Check", "State", "Detail"])
        self._configure_publish_tree(self.publish_checklist_tree, "publish_checklist", stretch_column=2, min_height=132)
        self.publish_checklist_tree.setMaximumHeight(180)
        checklist_layout.addWidget(self.publish_checklist_tree)
        review_layout.addWidget(checklist_panel)
        publish_layout.addWidget(review_wrap)

        source_wrap = QFrame()
        source_wrap.setObjectName("publishSectionCard")
        source_layout = QVBoxLayout(source_wrap)
        source_layout.setContentsMargins(18, 16, 18, 16)
        source_layout.setSpacing(12)
        source_header = QHBoxLayout()
        source_header.setContentsMargins(0, 0, 0, 0)
        source_title_block = QVBoxLayout()
        source_title_block.setContentsMargins(0, 0, 0, 0)
        source_title_block.setSpacing(2)
        source_title = QLabel("Source asset truth")
        source_title.setObjectName("publishSectionTitle")
        source_detail = QLabel("Only works with recoverable or missing source-image problems appear here. Use Studio or relink directly from the selected row.")
        source_detail.setObjectName("publishSectionSubtitle")
        source_detail.setWordWrap(True)
        source_title_block.addWidget(source_title)
        source_title_block.addWidget(source_detail)
        source_header.addLayout(source_title_block, 1)
        open_studio_btn = self._publish_button("Open Studio", lambda: (self._ensure_tab_built_by_key("studio"), self.tabs.setCurrentWidget(self.studio_tab)))
        repair_selected_btn = self._publish_button("Repair selected", self.repair_selected_publish_source)
        relink_selected_btn = self._publish_button("Relink selected…", self.relink_selected_publish_source)
        for btn in (open_studio_btn, repair_selected_btn, relink_selected_btn):
            source_header.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
        source_layout.addLayout(source_header)
        self.publish_registry_hint = QPlainTextEdit()
        self.publish_registry_hint.setObjectName("publishRegistryHint")
        self.publish_registry_hint.setReadOnly(True)
        self.publish_registry_hint.setFixedHeight(58)
        source_layout.addWidget(self.publish_registry_hint)
        source_split = QSplitter(Qt.Orientation.Vertical)
        source_split.setObjectName("publishSourceSplitter")
        source_split.setChildrenCollapsible(False)
        self.publish_source_tree = QTreeWidget()
        self.publish_source_tree.setHeaderLabels(["Work ID", "Series", "Status", "Recovery"])
        self._configure_publish_tree(self.publish_source_tree, "publish_source", stretch_column=3, min_height=190)
        self.publish_source_tree.itemSelectionChanged.connect(self.update_publish_source_detail)
        source_split.addWidget(self.publish_source_tree)
        self.publish_source_detail = QPlainTextEdit()
        self.publish_source_detail.setObjectName("publishSourceDetail")
        self.publish_source_detail.setReadOnly(True)
        self.publish_source_detail.setMinimumHeight(92)
        self.publish_source_detail.setMaximumHeight(132)
        source_split.addWidget(self.publish_source_detail)
        source_split.setSizes([260, 104])
        source_layout.addWidget(source_split, 1)
        publish_layout.addWidget(source_wrap)
        publish_layout.addStretch(1)

        history_header = QHBoxLayout()
        history_header.addWidget(QLabel("Operation history"))
        refresh_ops_btn = QPushButton("Refresh")
        refresh_ops_btn.clicked.connect(self.refresh_operation_history)
        restore_btn = QPushButton("Restore last completed")
        restore_btn.clicked.connect(self.restore_last_completed_operation)
        export_log_btn = QPushButton("Export log")
        export_log_btn.clicked.connect(self.export_build_log)
        history_header.addWidget(refresh_ops_btn)
        history_header.addWidget(restore_btn)
        history_header.addWidget(export_log_btn)
        history_header.addStretch(1)
        history_layout.addLayout(history_header)
        self.operation_history_tree = QTreeWidget()
        self.operation_history_tree.setHeaderLabels(["Started", "Status", "Targets", "Operations"])
        self._polish_data_tree(self.operation_history_tree, "operation_history")
        self.operation_history_tree.itemSelectionChanged.connect(self.update_operation_history_detail)
        history_layout.addWidget(self.operation_history_tree, 1)
        self.operation_history_detail = QPlainTextEdit(); self.operation_history_detail.setReadOnly(True); self.operation_history_detail.setFixedHeight(110)
        history_layout.addWidget(self.operation_history_detail)
        op_actions = QHBoxLayout()
        copy_targets_btn = QPushButton("Copy targets")
        copy_targets_btn.clicked.connect(self.copy_selected_operation_targets)
        open_backup_btn = QPushButton("Open first backup")
        open_backup_btn.clicked.connect(self.open_selected_operation_backup)
        release_meta_btn = QPushButton("Release workspace…")
        release_meta_btn.clicked.connect(self.open_release_workspace)
        for btn in (copy_targets_btn, open_backup_btn, release_meta_btn):
            op_actions.addWidget(btn)
        op_actions.addStretch(1)
        history_layout.addLayout(op_actions)
        self.build_log_drawer = QGroupBox("Build log and raw output")
        self.build_log_drawer.setObjectName("buildLogDrawer")
        self.build_log_drawer.setCheckable(True)
        self.build_log_drawer.setChecked(False)
        build_log_layout = QVBoxLayout(self.build_log_drawer)
        self.build_log = QTextEdit(); self.build_log.setReadOnly(True)
        self.build_log.setVisible(False)
        build_log_layout.addWidget(self.build_log, 1)
        self.build_log_drawer.toggled.connect(self.build_log.setVisible)
        history_layout.addWidget(self.build_log_drawer, 0)

        workbook_layout.addWidget(QLabel("Workbook review & import"))
        path_row = QHBoxLayout()
        self.workbook_path_edit = QLineEdit(self._workbook_path)
        self.workbook_path_edit.textChanged.connect(self._on_workbook_path_changed)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self.choose_workbook)
        path_row.addWidget(self.workbook_path_edit, 1)
        path_row.addWidget(browse_btn)
        workbook_layout.addLayout(path_row)
        wb_btn_row = QHBoxLayout()
        export_btn = QPushButton("Export workbook")
        export_btn.clicked.connect(self.export_workbook)
        analyze_btn = QPushButton("Analyze workbook")
        analyze_btn.clicked.connect(self.analyze_selected_workbook)
        import_btn = QPushButton("Import workbook")
        import_btn.clicked.connect(self.import_selected_workbook)
        for btn in (export_btn, analyze_btn, import_btn):
            wb_btn_row.addWidget(btn)
        wb_btn_row.addStretch(1)
        workbook_layout.addLayout(wb_btn_row)
        self.workbook_review_box = QPlainTextEdit(); self.workbook_review_box.setReadOnly(True)
        workbook_layout.addWidget(self.workbook_review_box)
        self.workbook_preview_tree = QTreeWidget()
        self.workbook_preview_tree.setHeaderLabels(["Area", "ID", "Field", "Risk", "Incoming", "Affected file"])
        self.workbook_preview_tree.setAccessibleName("Workbook dry-run import preview")
        self.workbook_preview_tree.setToolTip("Dry-run import preview grouped by content area. High risk rows indicate empty-field overwrite or broad scope.")
        workbook_layout.addWidget(self.workbook_preview_tree, 1)
        self.workbook_rollback_btn = QPushButton("Rollback last import")
        self.workbook_rollback_btn.setEnabled(False)
        self.workbook_rollback_btn.setToolTip("Restore the last completed transaction after a workbook import.")
        self.workbook_rollback_btn.clicked.connect(self.restore_last_completed_operation)
        workbook_layout.addWidget(self.workbook_rollback_btn)
        artifact_header = QHBoxLayout()
        artifact_header.addWidget(QLabel("Release artifacts"))
        refresh_artifacts_btn = QPushButton("Refresh")
        refresh_artifacts_btn.clicked.connect(self.refresh_release_artifacts)
        open_archive_btn = QPushButton("Open selected")
        open_archive_btn.clicked.connect(self.open_selected_release_artifact)
        open_deploy_btn = QPushButton("Open deploy folder")
        open_deploy_btn.clicked.connect(self.open_deploy_folder)
        artifact_header.addWidget(refresh_artifacts_btn)
        artifact_header.addWidget(open_archive_btn)
        artifact_header.addWidget(open_deploy_btn)
        artifact_header.addStretch(1)
        workbook_layout.addLayout(artifact_header)
        self.release_artifact_tree = QTreeWidget()
        self.release_artifact_tree.setHeaderLabels(["Archive", "Updated", "Size"])
        self._polish_data_tree(self.release_artifact_tree, "release_artifacts")
        self.release_artifact_tree.itemDoubleClicked.connect(lambda _item, _col: self.open_selected_release_artifact())
        workbook_layout.addWidget(self.release_artifact_tree, 1)

        self.open_preview_after_build_btn = QPushButton("Open preview after build")
        self.open_preview_after_build_btn.clicked.connect(self.open_preview)
        self.open_preview_after_build_btn.hide()
        layout.addWidget(self.open_preview_after_build_btn)
        self._set_publish_workflow_state()
        self._load_persisted_build_log()
        self.apply_button_tooltips(tab)
        return tab

    def show_publish_workbook_tools(self) -> None:
        """Reveal the advanced workbook workspace without putting it in the daily publish path."""
        if not hasattr(self, "publish_inner_tabs"):
            return
        try:
            self.publish_inner_tabs.setTabVisible(2, True)
            self.publish_inner_tabs.setCurrentIndex(2)
        except Exception as exc:
            self._log_warning(f"Could not open workbook tools: {exc}")

    def _build_log_path(self) -> Path:
        path = ROOT / ".stillmrk-build" / "meta" / "build-log.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load_persisted_build_log(self) -> None:
        if not hasattr(self, "build_log"):
            return
        path = self._build_log_path()
        if not path.exists():
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-500:]
        except Exception as exc:
            self._log_warning(f"Could not load build log: {exc}")
            return
        if lines:
            self.build_log.setPlainText("\n".join(lines))
            self.build_log.moveCursor(QTextCursor.MoveOperation.End)

    def _persist_build_log_line(self, line: str) -> None:
        self._build_log_buffer.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {line}")
        if not self._build_log_flush_timer.isActive():
            self._build_log_flush_timer.start()

    def _flush_build_log_buffer(self) -> None:
        if not getattr(self, "_build_log_buffer", None):
            return
        try:
            path = self._build_log_path()
            existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            existing.extend(self._build_log_buffer)
            self._build_log_buffer.clear()
            path.write_text("\n".join(existing[-500:]) + "\n", encoding="utf-8")
        except Exception as exc:
            self._build_log_buffer.clear()
            self._log_warning(f"Could not persist build log: {exc}")

    def export_build_log(self) -> None:
        if not hasattr(self, "build_log"):
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export build log", str(ROOT / "build-log.txt"), "Text files (*.txt)")
        if not path:
            return
        Path(path).write_text(self.build_log.toPlainText(), encoding="utf-8")
        self.status_message(f"Exported build log: {Path(path).name}")

    def append_build_log_line(self, line: str) -> None:
        if not hasattr(self, "build_log"):
            return
        text_line = str(line)
        self._append_log_line(text_line)
        self._persist_build_log_line(text_line)

    def _tick_task_activity(self) -> None:
        if not self._running_tasks:
            self._task_animation_timer.stop()
            self._update_task_badge()
            return
        self._task_animation_step = (self._task_animation_step + 1) % len(SPINNER_FRAMES)
        self._update_task_badge()

    def _update_task_badge(self) -> None:
        if self._running_tasks:
            frame = SPINNER_FRAMES[self._task_animation_step % len(SPINNER_FRAMES)]
            label = self._active_task_label or "Working"
            extra = f" · +{len(self._task_queue)} queued" if self._task_queue else ""
            elapsed = int(max(0, time.monotonic() - float(getattr(self, "_active_task_started_at", 0.0) or 0.0)))
            text = f"{frame} {label} · {elapsed}s{extra}"
            if hasattr(self.task_label, "set_status"):
                self.task_label.set_status("info", text)
            else:
                self.task_label.setText(text)
            self.progress_hint.setText(label)
            if not self._task_animation_timer.isActive():
                self._task_animation_timer.start()
        elif self._task_queue:
            text = f"⚠ Blocked · {len(self._task_queue)} queued"
            if hasattr(self.task_label, "set_status"):
                self.task_label.set_status("warning", text)
            else:
                self.task_label.setText(text)
        else:
            if hasattr(self.task_label, "set_status"):
                self.task_label.set_status("ok", "✓ Idle")
            else:
                self.task_label.setText("✓ Idle")
            self.progress_hint.setText("")
            if self._task_animation_timer.isActive():
                self._task_animation_timer.stop()

    def _task_label_exists(self, label: str) -> bool:
        if self._running_tasks and self._active_task_label == label:
            return True
        return any(queued_label == label for queued_label, _fn, _done in self._task_queue)

    def _is_window_alive(self) -> bool:
        return not bool(getattr(self, "_closing", False)) and QApplication.instance() is not None

    def _safe_worker_finished(self, worker: FunctionWorker) -> None:
        try:
            self._forget_worker(worker)
        except RuntimeError:
            return
        except Exception as exc:
            try:
                self._log_warning(f"Worker cleanup warning: {exc}")
            except Exception:
                print(f"Worker cleanup warning: {exc}", file=sys.stderr)


    def _forget_worker(self, worker: FunctionWorker) -> None:
        try:
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            keyed = getattr(self, "_keyed_background_tasks", None)
            if isinstance(keyed, dict):
                for key, pair in list(keyed.items()):
                    if len(pair) >= 2 and pair[1] is worker:
                        keyed.pop(key, None)
        except RuntimeError:
            return

    def start_keyed_background_task(
        self,
        key: str,
        fn: Callable[..., Any],
        *,
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        label: str = "",
        cancel_previous: bool = False,
    ) -> None:
        """Start a coalesced background task without blocking the main task queue."""
        task_key = str(key or label or "background")
        keyed = getattr(self, "_keyed_background_tasks", {})
        existing = keyed.get(task_key)
        if existing is not None:
            context, _worker = existing
            if cancel_previous:
                context.cancel()
                keyed.pop(task_key, None)
            else:
                self._record_dirty_refresh_diagnostic(task_key, 0.0, f"Skipped duplicate background task: {task_key}")
                return
        context = TaskContext(label=label or task_key)
        worker = FunctionWorker(fn, task_context=context)
        keyed[task_key] = (context, worker)
        self._keyed_background_tasks = keyed
        self._active_workers.append(worker)
        started = time.perf_counter()
        if on_done is not None:
            worker.signals.result.connect(lambda result: on_done(result) if self._is_window_alive() else None)
        if on_error is not None:
            worker.signals.error.connect(lambda detail: on_error(detail) if self._is_window_alive() else None)
        else:
            worker.signals.error.connect(lambda detail, k=task_key: self._log_warning(f"{k} failed: {detail}") if self._is_window_alive() else None)
        worker.signals.cancelled.connect(lambda detail, k=task_key: self._log_warning(f"{k} cancelled: {detail}") if self._is_window_alive() else None)
        def _finish_keyed_background(w: FunctionWorker = worker, k: str = task_key, ctx: TaskContext = context, t0: float = started) -> None:
            try: self._record_perf(f"background {k}", time.perf_counter() - t0, ctx.current_stage or "finished")
            finally: self._safe_worker_finished(w)
        worker.signals.finished.connect(_finish_keyed_background)
        self.io_thread_pool.start(worker)

    def _set_task_cancellation_controls(self, enabled: bool) -> None:
        for name in ("cancel_task_button", "cancel_task_action"):
            control = getattr(self, name, None)
            if control is None:
                continue
            try:
                control.setEnabled(bool(enabled))
                if name == "cancel_task_button":
                    control.setVisible(bool(enabled))
            except RuntimeError:
                continue

    def cancel_current_task(self) -> None:
        if not self._running_tasks and not self._task_queue:
            self.status_message("No active task to cancel")
            return
        self._task_cancel_requested = True
        context = getattr(self, "_active_task_context", None)
        if context is not None:
            context.cancel()
        dropped = len(getattr(self, "_task_queue", []))
        self._task_queue.clear()
        self.append_build_log_line(f"Cancellation requested for: {self._active_task_label or 'active task'}")
        if dropped:
            self.append_build_log_line(f"Cleared {dropped} queued follow-up task(s).")
        self.push_notification("warning", "Task cancellation requested", "The active task will stop at its next safe checkpoint.", target_scope="publish")
        self.status_message("Cancellation requested")
        self._update_task_badge()

    def _launch_task(self, label: str, fn: Callable[..., Any], on_done: Callable[[Any], None] | None = None) -> None:
        self._running_tasks = 1
        self._active_task_label = label
        self._active_task_started_at = time.monotonic()
        self._task_animation_step = 0
        self._task_cancel_requested = False
        self._active_task_context = TaskContext(label=label)
        self._task_history.insert(0, {"label": label, "status": "started", "detail": datetime.now().isoformat(timespec="seconds")})
        self._task_history = self._task_history[:30]
        self._task_animation_timer.start()
        self.setCursor(Qt.CursorShape.BusyCursor)
        self._set_task_cancellation_controls(True)
        self._update_task_badge()
        worker = FunctionWorker(fn, task_context=self._active_task_context)
        self._active_workers.append(worker)
        worker.signals.cancelled.connect(lambda detail: self._task_cancelled(detail) if self._is_window_alive() else None)
        worker.signals.error.connect(lambda tb: self._task_error(tb) if self._is_window_alive() else None)
        worker.signals.result.connect(lambda result: self._task_result(label, result, on_done) if self._is_window_alive() else None)
        worker.signals.finished.connect(lambda: self._task_finished() if self._is_window_alive() else None)
        worker.signals.finished.connect(lambda w=worker: self._safe_worker_finished(w))
        self.thread_pool.start(worker)

    def start_task(self, label: str, fn: Callable[..., Any], *, on_done: Callable[[Any], None] | None = None) -> None:
        if self._task_label_exists(label):
            self.append_build_log_line(f"→ Already queued: {label}")
            self.status_message(f"Already queued: {label}")
            return
        if self._running_tasks:
            self._task_queue.append((label, fn, on_done))
            self._update_task_badge()
            self.append_build_log_line(f"→ Queued: {label}")
            self.push_notification("info", f"Queued task: {label}", "The task will start automatically after the active task finishes.", target_scope="publish")
            self.status_message(f"Queued: {label}")
            return
        self._launch_task(label, fn, on_done=on_done)

    def _task_result(self, label: str, result: Any, on_done: Callable[[Any], None] | None) -> None:
        elapsed_note = datetime.now().isoformat(timespec="seconds")
        self._task_history.insert(0, {"label": label, "status": "finished", "detail": elapsed_note})
        self._task_history = self._task_history[:30]
        if isinstance(result, dict) and result.get("stages"):
            for stage in result.get("stages") or []:
                self.append_build_log_line(f"✓ {stage.get('label')}: {stage.get('status')} ({stage.get('elapsed_ms', 0)} ms)")
        if on_done is not None:
            on_done(result)

    def _task_cancelled(self, detail: str) -> None:
        label = self._active_task_label or "Task"
        self._task_history.insert(0, {"label": label, "status": "cancelled", "detail": detail or datetime.now().isoformat(timespec="seconds")})
        self._task_history = self._task_history[:30]
        self.append_build_log_line(detail or f"Cancelled: {label}")
        self.push_notification("warning", "Task cancelled", detail or label, target_scope="publish")
        self.status_message("Task cancelled")

    def _parse_worker_error(self, tb_text: str) -> dict[str, Any]:
        try:
            payload = json.loads(str(tb_text or ""))
            if isinstance(payload, dict) and payload.get("kind"):
                return payload
        except Exception:
            pass
        return {
            "kind": "text",
            "summary": str(tb_text or "Task failed"),
            "detail": str(tb_text or ""),
            "path": "",
        }

    def _show_task_error_detail(self, title: str, detail: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(860, 560)
        layout = QVBoxLayout(dialog)
        viewer = QPlainTextEdit()
        viewer.setReadOnly(True)
        viewer.setPlainText(str(detail or "No traceback detail was provided."))
        layout.addWidget(viewer, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _task_error(self, tb_text: str) -> None:
        assert_gui_thread("task error UI apply")
        if getattr(self, "_closing", False):
            return
        error_payload = self._parse_worker_error(tb_text)
        summary = str(error_payload.get("summary") or "Task failed")
        detail = str(error_payload.get("detail") or tb_text or summary)
        path = str(error_payload.get("path") or "").strip()
        if path and path not in summary:
            summary = f"{summary} · {path}"
        _append_control_panel_diagnostic_event({
            "event": "task-error-ui",
            "task": self._active_task_label or "task",
            "summary": summary,
            "path": path,
            "kind": str(error_payload.get("kind") or "text"),
            "detail": detail,
        })
        self._studio_refresh_inflight = False
        self._validation_refresh_inflight = False
        self._publish_source_refresh_inflight = False
        for overlay in list(getattr(self, "_loading_overlays", {}).values()):
            try:
                overlay.hide()
            except Exception as exc:
                self._log_warning(f"Could not hide loading overlay after task error: {exc}")
        self.append_build_log_line(summary)
        if detail and detail != summary:
            self.append_build_log_line(detail)
        if hasattr(self, "build_log_drawer"):
            self.build_log_drawer.setChecked(True)
        self._task_history.insert(0, {"label": self._active_task_label or "task", "status": "failed", "detail": summary})
        self._task_history = self._task_history[:30]
        if self._active_task_label == "Build site":
            self.set_build_triggers_enabled(True)
            self._flush_build_log_buffer()
            self._last_build_time = datetime.now()
            self._last_build_status = "Failed"
            self._update_session_health()
        title = "Task failed"
        message = summary
        if "missing source images" in (summary + " " + detail).lower():
            self.refresh_studio()
            self.tabs.setCurrentWidget(self.publish_tab)
            title = "Missing source images"
            message = summary + "\n\nOpen the source blockers panel below, or switch to Studio for preview-led relinking."
        self.push_notification("error", title, message, target_scope="publish")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(message)
        box.setInformativeText("The full traceback was written to .stillmrk-build/meta/control-panel-diagnostics.jsonl.")
        detail_button = box.addButton("View detail", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is detail_button:
            self._show_task_error_detail(f"{title} detail", detail)
        self.status_message(summary[:140] or "Task failed")

    def _task_finished(self) -> None:
        self._running_tasks = 0
        self._active_task_label = ""
        self._active_task_started_at = None
        self._active_task_context = None
        self._task_animation_timer.stop()
        self._set_task_cancellation_controls(False)
        self.unsetCursor()
        if self._is_window_alive():
            self.refresh_dashboard()
        if self._task_queue:
            label, fn, on_done = self._task_queue.pop(0)
            QTimer.singleShot(0, lambda l=label, f=fn, d=on_done: self._launch_task(l, f, on_done=d))
        self._update_task_badge()

    def _release_checks_ok(self, rows: list[dict[str, Any]]) -> bool:
        """Return True when the explicit Check step has no blocking release rows."""
        for row in rows:
            status = str(row.get("status") or row.get("severity") or "").lower()
            if status in {"error", "critical", "blocked", "blocker", "fail", "failed"}:
                return False
        return True

    def run_publish_check_step(self) -> None:
        """Phase 14 primary release gate: Check → Package → Upload."""
        try:
            rows = list(release_checks())
            source_blockers = [row for row in source_asset_report_rows() if row.get("status") != "ok"]
            validation_errors = [row for row in validate_all() if str(row.get("severity") or "").lower() == "error"]
        except Exception as exc:
            self._publish_check_passed = False
            self._set_publish_workflow_state()
            QMessageBox.critical(self, "Publish check failed", str(exc))
            return
        ok = self._release_checks_ok(rows) and not source_blockers and not validation_errors
        self._publish_check_passed = bool(ok)
        self._last_dashboard_release_rows = rows
        self._set_publish_workflow_state()
        if hasattr(self, "publish_summary"):
            lines = [
                f"Check result: {'passed' if ok else 'blocked'}",
                f"Release checks: {len(rows)}",
                f"Validation blockers: {len(validation_errors)}",
                f"Source blockers: {len(source_blockers)}",
                "",
            ]
            lines.extend(f"- {row.get('area') or row.get('file') or 'Check'}: {row.get('status') or row.get('severity') or '-'} — {row.get('detail') or row.get('message') or ''}" for row in rows[:60])
            self.publish_summary.setPlainText("\n".join(lines))
        if ok:
            self.push_notification("success", "Publish check passed", "Package is now enabled.", target_scope="publish")
            self.status_message("Publish check passed")
        else:
            self.push_notification("error", "Publish check blocked", "Fix blockers before packaging.", target_scope="publish")
            self.status_message("Publish check blocked")

    def copy_public_upload_path(self) -> None:
        path = ROOT / "public_upload"
        path.mkdir(exist_ok=True)
        QApplication.clipboard().setText(str(path.resolve()))
        self.status_message("Copied public_upload path")
        self.push_notification("success", "Upload path copied", str(path.resolve()), target_scope="publish")

    def run_build_site(self) -> None:
        self.validate_external_paths(notify=True)
        if self._task_label_exists("Build site"):
            self.append_build_log_line("→ Already queued: Build site")
            self.status_message("Build already running or queued")
            return
        self.build_log.clear()
        if hasattr(self, "build_log_drawer"):
            self.build_log_drawer.setChecked(True)
        self._public_upload_snapshot = self._snapshot_public_upload()
        self.set_build_triggers_enabled(False)
        self.append_build_log_line("Starting build…")

        def task(task_context: TaskContext | None = None) -> dict[str, Any]:
            return run_staged_build(run_build_with_preflight, line_callback=self._emit_line, task_context=task_context)

        self.start_task("Build site", task, on_done=self._build_done)

    def run_generate_documents(self) -> None:
        self.append_build_log_line("Generating documents…")

        def task() -> int:
            return run_documents(line_callback=self._emit_line)

        self.start_task("Generate documents", task, on_done=self._documents_done)


    def run_prepare_publish(self) -> None:
        if not getattr(self, "_publish_check_passed", False):
            self.status_message("Run Check before Package")
            self.push_notification("warning", "Package locked", "Run Check first; packaging is disabled until blockers are clear.", target_scope="publish")
            self._set_publish_workflow_state()
            return
        self.validate_external_paths(notify=True)
        self.append_build_log_line("Preparing publish package…")

        def task(task_context: TaskContext | None = None) -> dict[str, Any]:
            return run_staged_publish_package(prepare_publish_package, line_callback=self._emit_line, task_context=task_context)

        self.start_task("Prepare publish", task, on_done=self._prepare_publish_done)

    def _prepare_publish_done(self, result: Any) -> None:
        archive = str((result or {}).get("archive") or "")
        recovered = int((result or {}).get("recovered_sources") or 0)
        missing_sources = int((result or {}).get("missing_sources") or 0)
        if recovered:
            self.append_build_log_line(f"✓ Recovered {recovered} source image(s) before build")
        if missing_sources:
            self.append_build_log_line(f"⚠ Publish package was prepared with placeholders for {missing_sources} work(s) that still have missing source images")
        if archive:
            self._last_publish_archive = archive
            self.append_build_log_line(f"✓ Publish package ready: {Path(archive).name}")
            if missing_sources:
                self.push_notification("warning", "Publish package ready with missing images", f"{Path(archive).name}\n{missing_sources} work(s) used placeholders because their source images are still missing.", target_scope="publish")
            else:
                self.push_notification("success", "Publish package ready", archive, target_scope="publish")
            self.status_message("Publish package ready")
        else:
            self.append_build_log_line("✕ Publish package did not return an archive path")
            self.status_message("Prepare publish failed")
        self.refresh_dashboard()
        self._set_publish_workflow_state()

    def _emit_line(self, line: str) -> None:
        # Safe UI marshal via posted events. During teardown, QApplication.instance() may be None.
        app = QApplication.instance()
        if app is not None:
            app.postEvent(self, _LogEvent(line))

    def customEvent(self, event) -> None:  # pragma: no cover - UI event plumbing
        if not self.isVisible():
            return
        if isinstance(event, _LogEvent):
            self.append_build_log_line(event.line)
            return
        if isinstance(event, _StatusEvent):
            self.statusBar().showMessage(event.text, 5000)
            return
        super().customEvent(event)

    def _snapshot_public_upload(self) -> dict[str, tuple[int, int]]:
        root_path = ROOT / "public_upload"
        snapshot: dict[str, tuple[int, int]] = {}
        if not root_path.exists():
            return snapshot
        for path in root_path.rglob("*"):
            if path.is_file():
                try:
                    rel = str(path.relative_to(root_path)).replace("\\", "/")
                    stat = path.stat()
                    snapshot[rel] = (int(stat.st_mtime_ns), int(stat.st_size))
                except Exception as exc:
                    self._log_warning(f"Could not snapshot public_upload file: {exc}")
        return snapshot

    def _summarize_public_upload_diff(self) -> str:
        before = self._public_upload_snapshot or {}
        after = self._snapshot_public_upload()
        changed = [path for path, meta in after.items() if before.get(path) != meta]
        removed = [path for path in before if path not in after]
        self._last_public_upload_diff = {"changed": changed, "removed": removed}
        total = len(changed) + len(removed)
        if not total:
            return "No public_upload file changes detected."
        sample = changed[:8] + [f"removed: {p}" for p in removed[:4]]
        suffix = "" if total <= len(sample) else f" … +{total - len(sample)} more"
        return f"{total} public_upload file(s) changed: " + ", ".join(sample) + suffix

    def set_build_triggers_enabled(self, enabled: bool) -> None:
        for action in list(getattr(self, "_build_trigger_actions", [])):
            try:
                action.setEnabled(enabled)
            except RuntimeError:
                continue
        for widget in list(getattr(self, "_build_trigger_widgets", [])):
            try:
                widget.setEnabled(enabled)
            except RuntimeError:
                continue

    def _build_done(self, result: Any) -> None:
        if isinstance(result, dict):
            return_code = int(result.get("return_code") or 0)
            recovered = int(result.get("recovered_sources") or 0)
            missing_sources = int(result.get("missing_sources") or 0)
        else:
            return_code = int(result or 0)
            recovered = 0
            missing_sources = 0
        if recovered:
            self.append_build_log_line(f"✓ Recovered {recovered} source image(s) before build")
        if missing_sources:
            self.append_build_log_line(f"⚠ Build continued with placeholders for {missing_sources} work(s) that still have missing source images")
        if return_code == 0:
            self.append_build_log_line("✓ Build completed successfully")
            self.append_build_log_line(self._summarize_public_upload_diff())
            try:
                preview_check = verify_preview_output()
                self.append_build_log_line(f"Preview integrity: {preview_check.get('errors', 0)} error(s), {preview_check.get('warnings', 0)} warning(s)")
                for row in list(preview_check.get("rows") or [])[:12]:
                    prefix = "✓" if row.get("status") == "ok" else "⚠" if row.get("status") == "warn" else "✕"
                    self.append_build_log_line(f"{prefix} {row.get('path')}: {row.get('detail')}")
            except Exception as exc:
                self.append_build_log_line(f"⚠ Preview integrity check failed: {exc}")
            if hasattr(self, "open_preview_after_build_btn"):
                self.open_preview_after_build_btn.show()
                QTimer.singleShot(30000, self.open_preview_after_build_btn.hide)
            if hasattr(self, "open_changed_output_btn"):
                self.open_changed_output_btn.show()
            if hasattr(self, "build_log_drawer"):
                self.build_log_drawer.setChecked(False)
            self._last_build_time = datetime.now()
            self._last_build_status = "Clean" if not missing_sources else f"{missing_sources} missing images"
            self._update_session_health()
            if missing_sources:
                self.push_notification("warning", "Build completed with missing images", f"The site was rebuilt, but {missing_sources} work(s) used placeholders because their source images are still missing.", target_scope="publish")
            else:
                self.push_notification("success", "Build completed", "The public site build finished successfully.", target_scope="publish")
            self.status_message("Build complete")
        else:
            self.append_build_log_line(f"✕ Build exited with code {return_code}")
            self._last_build_time = datetime.now()
            self._last_build_status = f"Failed ({return_code})"
            self._update_session_health()
            self.status_message("Build failed")
        self.set_build_triggers_enabled(True)
        self._set_publish_workflow_state()
        self._flush_build_log_buffer()

    def _documents_done(self, return_code: Any) -> None:
        if int(return_code or 0) == 0:
            self.append_build_log_line("✓ Document generation completed successfully")
            self.push_notification("success", "Documents generated", "Portfolio documents were regenerated.", target_scope="publish")
            self.status_message("Documents generated")
        else:
            self.append_build_log_line(f"✕ Document generation exited with code {return_code}")
            self.status_message("Document generation failed")

    def _on_workbook_path_changed(self, value: str) -> None:
        self._workbook_path = value.strip()
        self.save_window_state()

    def _current_workbook_path(self) -> str:
        if hasattr(self, "workbook_path_edit"):
            self._workbook_path = self.workbook_path_edit.text().strip()
        return self._workbook_path

    def choose_workbook(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose workbook", str(ROOT / "exports"), "Excel workbook (*.xlsx)")
        if path and hasattr(self, "workbook_path_edit"):
            self.workbook_path_edit.setText(path)

    def _format_workbook_summary(self, workbook: str, summary: dict[str, Any]) -> str:
        lines = [
            f"Workbook: {workbook}",
            f"Site setting changes: {summary.get('site_setting_changes', 0)}",
            f"Pages changed: {', '.join(summary.get('pages_changed', [])) or 'none'}",
            f"Series changed: {summary.get('series_changed', 0)}",
            f"Works changed: {summary.get('works_changed', 0)}",
            f"Home ordering changes: {summary.get('home_order_changed', 0)}",
            f"Documents changed: {summary.get('documents_changed', 0)}",
            f"Navigation changed: {summary.get('navigation_changed', 0)}",
        ]
        warnings = summary.get('warnings') or []
        if warnings:
            lines.append("\nWarnings:")
            lines.extend([f"- {warning}" for warning in warnings])
        else:
            lines.append("\nWarnings: none")
        return "\n".join(lines)

    def export_workbook(self) -> None:
        self.append_build_log_line("Exporting workbook…")

        def task() -> str:
            return export_workbook_bundle(line_callback=self._emit_line)

        def done(path: Any) -> None:
            path_text = str(path or "")
            if path_text and hasattr(self, "workbook_path_edit"):
                self.workbook_path_edit.setText(path_text)
            self.append_build_log_line(f"✓ Workbook exported: {Path(path_text).name if path_text else path_text}")
            self.push_notification("success", "Workbook exported", path_text, target_scope="publish")
            self.status_message("Workbook exported")

        self.start_task("Export workbook", task, on_done=done)

    def analyze_selected_workbook(self) -> None:
        path = self._current_workbook_path()
        if not path:
            self.choose_workbook()
            path = self._current_workbook_path()
        if not path:
            return
        self.append_build_log_line(f"Analyzing workbook… {Path(path).name}")

        def task() -> dict[str, Any]:
            return analyze_workbook_bundle(path, line_callback=self._emit_line)

        def done(summary: Any) -> None:
            if not isinstance(summary, dict):
                return
            self.last_workbook_analysis = dict(summary)
            workbook = str(summary.get('workbook') or path)
            self.workbook_review_box.setPlainText(self._format_workbook_summary(workbook, summary))
            self._render_workbook_preview_tree(summary)
            self.append_build_log_line("✓ Workbook analyzed")
            self.push_notification("info", "Workbook analyzed", self._format_workbook_summary(workbook, summary), target_scope="publish")
            self.status_message("Workbook analyzed")

        self.start_task("Analyze workbook", task, on_done=done)

    def import_selected_workbook(self) -> None:
        path = self._current_workbook_path()
        if not path:
            self.choose_workbook()
            path = self._current_workbook_path()
        if not path:
            return
        workbook = Path(path)
        summary = self.last_workbook_analysis
        if summary is None or str(summary.get('workbook') or '') != str(workbook):
            try:
                summary = analyze_workbook_bundle(workbook)
            except BackendError as exc:
                self._critical_modal("Import analysis failed", str(exc), target_scope="publish")
                return
            self.last_workbook_analysis = dict(summary)
            if hasattr(self, 'workbook_review_box'):
                self.workbook_review_box.setPlainText(self._format_workbook_summary(str(workbook), summary))
            self._render_workbook_preview_tree(summary)
        msg = self._format_workbook_summary(str(workbook), summary)
        high_risk = int((summary.get('risk_counts') or {}).get('high') or 0)
        if high_risk:
            self.push_notification('warning', 'Workbook import has high-risk overwrites', f'{high_risk} empty-field overwrite(s) flagged.', target_scope='publish')
        confirm = QMessageBox.question(self, "Apply workbook changes", msg + "\n\nThis is a transaction. Use Rollback last import immediately if the dry run was wrong.")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.append_build_log_line(f"Importing workbook… {workbook.name}")

        def task() -> dict[str, Any]:
            return import_workbook_bundle(workbook, line_callback=self._emit_line)

        def done(result: Any) -> None:
            applied = result.get('applied') if isinstance(result, dict) else result
            self.append_build_log_line(f"✓ Workbook import complete: {applied}")
            self.push_notification("success", "Workbook import complete", f"Applied changes: {applied}", target_scope="publish")
            self.status_message("Workbook imported")
            self.refresh_all_context(force=True)
            if hasattr(self, "workbook_rollback_btn"):
                self.workbook_rollback_btn.setEnabled(True)
            ask_build = QMessageBox.question(self, "Build now", "Workbook changes were applied.\nRun build now?")
            if ask_build == QMessageBox.StandardButton.Yes:
                self.run_build_site()

        self.start_task("Import workbook", task, on_done=done)

    def refresh_operation_history(self) -> None:
        if not hasattr(self, 'operation_history_tree'):
            return
        self.operation_history_tree.clear()
        for row in recent_operation_rows(limit=30):
            started = str(row.get('started_at') or row.get('timestamp') or '')
            targets = list(row.get('targets') or [])
            ops = list(row.get('ops') or [])
            item = QTreeWidgetItem([
                started.replace('T', ' ')[:19],
                str(row.get('status') or ''),
                str(len(targets)),
                str(len(ops)),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            self.operation_history_tree.addTopLevelItem(item)
        if self.operation_history_tree.topLevelItemCount() and self.operation_history_tree.currentItem() is None:
            self.operation_history_tree.setCurrentItem(self.operation_history_tree.topLevelItem(0))
        self.update_operation_history_detail()

    def update_operation_history_detail(self) -> None:
        if not hasattr(self, 'operation_history_detail'):
            return
        item = self.operation_history_tree.currentItem() if hasattr(self, 'operation_history_tree') else None
        if item is None:
            self.operation_history_detail.setPlainText('Select an operation to inspect its targets and backup steps.')
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        lines = [
            f"Started: {row.get('started_at') or row.get('timestamp') or ''}",
            f"Status: {row.get('status') or ''}",
            f"Ended: {row.get('ended_at') or ''}",
            '',
            'Targets:',
        ]
        for target in row.get('targets') or []:
            lines.append(f"- {target}")
        lines.append('')
        lines.append('Operations:')
        backup_count = 0
        for op in row.get('ops') or []:
            target = op.get('target') or ''
            backup = op.get('backup') or ''
            if backup:
                backup_count += 1
                lines.append(f"- {op.get('type') or ''}: {target} -> {backup}")
            else:
                lines.append(f"- {op.get('type') or ''}: {target}")
        if backup_count:
            lines.extend(['', f'Backups: {backup_count} file backup(s) available'])
        self.operation_history_detail.setPlainText('\n'.join(lines).strip())

    def restore_last_completed_operation(self) -> None:
        latest = recent_operation_rows(1)
        if latest:
            row = latest[0]
            targets = list(row.get("targets") or [])
            preview = f"Transaction: {row.get('label') or row.get('id') or '-'}\nStatus: {row.get('status') or '-'}\nTargets: {len(targets)}"
            if targets:
                preview += "\n\n" + "\n".join(f"- {target}" for target in targets[:8])
                if len(targets) > 8:
                    preview += f"\n- … and {len(targets) - 8} more"
        else:
            preview = "No recent completed transaction preview is available."
        confirm = QMessageBox.question(self, 'Restore last completed transaction', preview + '\n\nRoll back this transaction?')
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.append_build_log_line('Restoring last completed transaction…')

        def task() -> dict[str, Any]:
            return restore_last_completed_transaction()

        def done(result: Any) -> None:
            txn = dict(result or {})
            self.append_build_log_line('✓ Last completed transaction restored')
            self.push_notification('success', 'Transaction restored', f"Restored transaction from {txn.get('started_at') or txn.get('timestamp') or ''}", target_scope='publish')
            self.refresh_all_context(force=True)
            self.refresh_operation_history()

        self.start_task('Restore last transaction', task, on_done=done)

    def copy_selected_operation_targets(self) -> None:
        item = self.operation_history_tree.currentItem() if hasattr(self, 'operation_history_tree') else None
        if item is None:
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        targets = [str(target) for target in (row.get('targets') or [])]
        if not targets:
            self.status_message('No targets to copy for the selected operation.')
            return
        QApplication.clipboard().setText("\n".join(targets))
        self.status_message(f"Copied {len(targets)} operation target(s)")

    def open_selected_operation_backup(self) -> None:
        item = self.operation_history_tree.currentItem() if hasattr(self, 'operation_history_tree') else None
        if item is None:
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        backup_path = ''
        for op in row.get('ops') or []:
            backup = str(op.get('backup') or '')
            if backup:
                backup_path = backup.replace('REL::', '')
                break
        if not backup_path:
            QMessageBox.information(self, 'No backup available', 'The selected operation does not contain a file backup path.')
            return
        path = ROOT / backup_path
        if not path.exists():
            QMessageBox.warning(self, 'Backup missing', f'Backup file not found: {path}')
            return
        webbrowser.open(path.resolve().as_uri())

    def open_public_upload_folder(self) -> None:
        path = ROOT / 'public_upload'
        path.mkdir(exist_ok=True)
        webbrowser.open(path.resolve().as_uri())
        self.status_message('Opened public_upload folder')

    def show_release_gate_summary(self) -> None:
        try:
            # Reuse the current health report rows so release gate does not
            # immediately rescan source assets after a dashboard health run.
            health = portfolio_health_report(force=False, save=True, timeout_seconds=10.0)
            source_issues_rows = health.get("source_issues_rows")
            if source_issues_rows is None and health.get("source_rows") is not None:
                source_issues_rows = source_asset_issues(rows=list(health.get("source_rows") or []))
            summary = release_gate_summary(
                validation_rows=list(health.get("validation_rows") or []),
                source_issues=list(source_issues_rows or []),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Release gate failed", str(exc))
            return
        self.show_operation_report("Release gate summary", summary, force=True)

    def show_public_output_diff(self) -> None:
        try:
            diff = diff_public_output_snapshot()
        except Exception as exc:
            QMessageBox.critical(self, "Public diff failed", str(exc))
            return
        lines = [
            f"Previous snapshot: {diff.get('previous_at') or '-'}",
            f"New snapshot: {diff.get('captured_at') or '-'}",
            f"Added: {len(diff.get('added') or [])}",
            f"Changed: {len(diff.get('changed') or [])}",
            f"Removed: {len(diff.get('removed') or [])}",
            "",
            "Added:",
            *[f"+ {item}" for item in (diff.get('added') or [])[:80]],
            "",
            "Changed:",
            *[f"~ {item}" for item in (diff.get('changed') or [])[:80]],
            "",
            "Removed:",
            *[f"- {item}" for item in (diff.get('removed') or [])[:80]],
        ]
        dialog = QDialog(self)
        dialog.setWindowTitle("Public output diff")
        dialog.resize(900, 620)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit(); editor.setReadOnly(True); editor.setPlainText("\n".join(lines))
        layout.addWidget(editor, 1)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def create_named_release_snapshot(self) -> None:
        name, ok = QInputDialog.getText(self, "Release snapshot", "Snapshot name")
        if not ok:
            return
        note, ok_note = QInputDialog.getMultiLineText(self, "Release snapshot note", "Optional note", "")
        if not ok_note:
            note = ""
        try:
            result = create_release_snapshot(name, note)
            snapshots = list_release_snapshots()
        except Exception as exc:
            QMessageBox.critical(self, "Snapshot failed", str(exc))
            return
        self.push_notification("success", "Release snapshot created", str(result.get("path") or ""), target_scope="publish")
        self.show_operation_report("Release snapshot created", {"created": result, "recent_snapshots": snapshots[:10]}, force=True)

    def _prepublish_checks_passed(self) -> bool:
        rows = release_checks()
        dialog = PrePublishChecklistDialog(self, rows)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def create_upload_zip(self) -> None:
        if not self._prepublish_checks_passed():
            return
        self.append_build_log_line('Preparing upload zip…')

        def task() -> dict[str, Any]:
            return create_public_upload_archive(line_callback=self._emit_line)

        def done(result: Any) -> None:
            row = dict(result or {})
            archive = str(row.get('archive') or '')
            count = int(row.get('count') or 0)
            if archive:
                self._last_publish_archive = archive
                self.append_build_log_line(f"✓ Upload archive ready: {Path(archive).name}")
            self.push_notification('success', 'Upload archive prepared', f"{Path(archive).name if archive else 'Archive ready'} · {count} public_upload file(s)", target_scope='publish')
            self.refresh_release_artifacts()
            self._set_publish_workflow_state()
            self.status_message('Upload archive prepared')

        self.start_task('Create upload zip', task, on_done=done)

    def open_release_workspace(self) -> None:
        ReleaseAdminDialog(self).exec()


    def _load_release_artifacts_data(self, task_context: TaskContext | None = None) -> dict[str, Any]:
        if task_context is not None:
            task_context.stage("Loading release artifacts", progress=15)
        rows = list(deploy_archives())
        if task_context is not None:
            task_context.check_cancelled()
        return {"status": load_build_status(), "rows": rows, "loaded_at": datetime.now().isoformat(timespec="seconds")}

    def _apply_release_artifacts_data(self, result: Any, *, from_cache: bool = False) -> None:
        if not hasattr(self, "release_artifact_tree"):
            self._release_artifact_refresh_inflight = False
            return
        data = dict(result or {})
        rows = list(data.get("rows") or [])
        status = dict(data.get("status") or {})
        current_name = ""
        current_item = self.release_artifact_tree.currentItem()
        if current_item is not None:
            current_name = str((current_item.data(0, Qt.ItemDataRole.UserRole) or {}).get("name") or "")
        self.release_artifact_tree.setUpdatesEnabled(False)
        try:
            self.release_artifact_tree.clear()
            for row in rows:
                updated = str(row.get("updated_at") or "")
                size_bytes = int(row.get("size") or 0)
                size_label = f"{size_bytes / (1024 * 1024):.2f} MB" if size_bytes else "0 MB"
                name = str(row.get("name") or "")
                item = QTreeWidgetItem([name, updated.replace("T", " ")[:19], size_label])
                item.setData(0, Qt.ItemDataRole.UserRole, row)
                self.release_artifact_tree.addTopLevelItem(item)
                if current_name and name == current_name:
                    self.release_artifact_tree.setCurrentItem(item)
            if self.release_artifact_tree.topLevelItemCount() and self.release_artifact_tree.currentItem() is None:
                self.release_artifact_tree.setCurrentItem(self.release_artifact_tree.topLevelItem(0))
        finally:
            self.release_artifact_tree.setUpdatesEnabled(True)
            self.release_artifact_tree.viewport().update()
        self._release_artifact_cache = rows
        self._release_artifact_refresh_inflight = False
        self._dirty_tabs.pop("publish", None)
        self._publish_dirty = False
        if hasattr(self, "publish_summary") and status and int(status.get("missingImageCount") or 0):
            self.status_message(f"Latest build used placeholders for {int(status.get('missingImageCount') or 0)} missing image(s)")
        elif from_cache:
            self.status_message("Release artifacts shown from cache; refresh running.")
        self._set_publish_workflow_state()

    def refresh_release_artifacts(self) -> None:
        if not hasattr(self, "release_artifact_tree"):
            return
        cached = list(getattr(self, "_release_artifact_cache", []) or [])
        if cached and self.release_artifact_tree.topLevelItemCount() == 0:
            self._apply_release_artifacts_data({"rows": cached, "status": load_build_status()}, from_cache=True)
        if getattr(self, "_release_artifact_refresh_inflight", False):
            self._mark_dirty({"publish"})
            return
        self._release_artifact_refresh_inflight = True
        self.start_keyed_background_task(
            "release-artifacts",
            self._load_release_artifacts_data,
            on_done=self._apply_release_artifacts_data,
            on_error=lambda tb: (setattr(self, "_release_artifact_refresh_inflight", False), self._log_warning(f"Release artifact refresh failed: {tb}")),
            label="Release artifact refresh",
            cancel_previous=False,
        )

    def open_selected_release_artifact(self) -> None:
        item = self.release_artifact_tree.currentItem() if hasattr(self, 'release_artifact_tree') else None
        if item is None:
            QMessageBox.information(self, 'No artifact selected', 'Select a release archive first.')
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        path = Path(str(row.get('path') or ''))
        if not path.exists():
            QMessageBox.warning(self, 'Archive missing', f'Archive not found: {path}')
            return
        webbrowser.open(path.resolve().as_uri())

    def open_deploy_folder(self) -> None:
        deploy_dir = ROOT / 'deploy'
        deploy_dir.mkdir(exist_ok=True)
        webbrowser.open(deploy_dir.resolve().as_uri())

    def _load_publish_source_data(self) -> dict[str, Any]:
        registry = image_registry_summary()
        rows = [row for row in source_asset_report_rows() if row.get('status') != 'ok']
        payloads = {}
        for row in rows:
            work_id = str(row.get('id') or '').strip()
            if work_id:
                payloads[work_id] = load_work_payload(work_id)
        return {"registry": registry, "rows": rows, "payloads": payloads}


    def refresh_publish_source_panel(self) -> None:
        if not hasattr(self, "publish_source_tree"):
            self._mark_dirty({"publish"})
            return
        cached = getattr(self, "_publish_source_cache", None)
        if isinstance(cached, dict) and self.publish_source_tree.topLevelItemCount() == 0:
            self._apply_publish_source_data(cached, from_cache=True)
        if getattr(self, "_publish_source_refresh_inflight", False):
            self._mark_dirty({"publish"})
            return
        self._publish_source_refresh_inflight = True
        self._set_tab_loading(self.publish_tab, True)
        self.start_keyed_background_task(
            "publish-source-panel",
            self._load_publish_source_data,
            on_done=self._apply_publish_source_data,
            on_error=lambda tb: (setattr(self, "_publish_source_refresh_inflight", False), self._set_tab_loading(self.publish_tab, False), self._log_warning(f"Publish source refresh failed: {tb}")),
            label="Publish source refresh",
            cancel_previous=False,
        )

    def _apply_publish_source_data(self, result: Any, *, from_cache: bool = False) -> None:
        if not hasattr(self, "publish_source_tree"):
            self._publish_source_refresh_inflight = False
            return
        data = dict(result or {})
        self._publish_source_cache = data
        current_id = ""
        current_item = self.publish_source_tree.currentItem()
        if current_item is not None:
            current_id = str((current_item.data(0, Qt.ItemDataRole.UserRole) or {}).get('id') or '')
        self.publish_source_tree.clear()
        registry = dict(data.get("registry") or {})
        if hasattr(self, 'publish_registry_hint'):
            self.publish_registry_hint.setPlainText(
                f"Source root: {registry.get('source_root')}\nGenerated root: {registry.get('generated_root')}\nManifest dir: {registry.get('manifest_dir')} · image rows {registry.get('image_index_rows')} · derivative rows {registry.get('derivative_index_rows')}"
            )
        rows = list(data.get("rows") or [])
        payloads = dict(data.get("payloads") or {})
        for row in rows:
            item = QTreeWidgetItem([
                str(row.get('id') or ''),
                str(row.get('series') or ''),
                str(row.get('status') or ''),
                str(row.get('recovery') or ''),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            payload = payloads.get(str(row.get('id') or ''))
            icon = self.work_tree_icon(payload) if payload else QIcon()
            if not icon.isNull():
                item.setIcon(0, icon)
            self.publish_source_tree.addTopLevelItem(item)
            if current_id and str(row.get('id') or '') == current_id:
                self.publish_source_tree.setCurrentItem(item)
        if self.publish_source_tree.topLevelItemCount() and self.publish_source_tree.currentItem() is None:
            self.publish_source_tree.setCurrentItem(self.publish_source_tree.topLevelItem(0))
        self._publish_source_refresh_inflight = False
        self._set_tab_loading(self.publish_tab, False)
        self._dirty_tabs.pop("publish", None)
        self._publish_dirty = False
        self.update_publish_source_detail()
        self._set_publish_workflow_state()
        if from_cache:
            self.status_message("Publish source report shown from cache; refresh running.")

    def update_publish_source_detail(self) -> None:
        if not hasattr(self, 'publish_source_detail'):
            return
        item = self.publish_source_tree.currentItem() if hasattr(self, 'publish_source_tree') else None
        if item is None:
            self.publish_source_detail.setPlainText("No source blockers right now. Strict source asset truth passed for the current report.")
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        expected = ", ".join(row.get('expected_stems') or []) or '-'
        lines = [
            f"Work ID: {row.get('id') or '-'}",
            f"Series: {row.get('series') or '-'}",
            f"Status: {row.get('status') or '-'}",
            f"Expected names: {expected}",
            f"Detail: {row.get('detail') or '-'}",
            f"Recovery: {row.get('recovery') or '-'}",
        ]
        self.publish_source_detail.setPlainText("\n".join(lines))

    def repair_selected_publish_source(self) -> None:
        item = self.publish_source_tree.currentItem() if hasattr(self, 'publish_source_tree') else None
        if item is None:
            self._info_nonblocking("No source blocker selected", "Select a missing-source row first.", target_scope="studio")
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        work_id = str(row.get('id') or '')
        if not work_id:
            return
        self.append_build_log_line(f"Checking source asset for {work_id}…")

        def task() -> list[dict[str, str]]:
            return recover_missing_source_images([work_id], line_callback=self._emit_line)

        self.start_task(f"Repair source {work_id}", task, on_done=self._repair_sources_done)

    def relink_selected_publish_source(self) -> None:
        item = self.publish_source_tree.currentItem() if hasattr(self, 'publish_source_tree') else None
        if item is None:
            self._info_nonblocking("No source blocker selected", "Select a missing-source row first.", target_scope="studio")
            return
        row = item.data(0, Qt.ItemDataRole.UserRole) or {}
        work_id = str(row.get('id') or '')
        if not work_id:
            return
        path, _ = QFileDialog.getOpenFileName(self, f"Relink source for {work_id}", str(ROOT), "Images (*.jpg *.jpeg *.png *.webp *.tif *.tiff)")
        if not path:
            return
        self.append_build_log_line(f"Relinking source image for {work_id}…")

        def task() -> dict[str, str]:
            return relink_source_image(work_id, path, line_callback=self._emit_line)

        self.start_task(f"Relink source {work_id}", task, on_done=self._relink_source_done)


    def open_preview(self) -> None:
        target = preview_target()
        webbrowser.open(target.as_uri())
        self.status_message("Opened preview")

    # ---------- global refresh / commands ----------
    def _expanded_refresh_scope(self, scope: set[str] | None) -> set[str]:
        try:
            return self._refresh_coordinator.expand(scope)
        except Exception as exc:
            self._log_warning(f"Refresh coordinator fallback used: {exc}")
            return set(scope or {"works", "series", "pages", "studio", "publish", "dashboard"})

    def _mark_dirty(self, scopes: set[str] | list[str] | tuple[str, ...]) -> None:
        try:
            scopes = self._refresh_coordinator.remember_dirty(scopes)
        except Exception:
            scopes = set(scopes or [])
        now = time.time()
        dirty = getattr(self, "_dirty_tabs", None)
        if not isinstance(dirty, dict):
            dirty = {str(key): now for key in list(dirty or [])}
            self._dirty_tabs = dirty
        for scope in scopes:
            key = str(scope or "").strip()
            if key:
                self._dirty_tabs[key] = now
                if key == "studio":
                    self._studio_dirty = True
                elif key == "publish":
                    self._publish_dirty = True
                elif key == "relationships":
                    self._relationships_dirty = True

    def _dirty_age_seconds(self, key: str) -> float:
        dirty = getattr(self, "_dirty_tabs", {})
        if isinstance(dirty, dict):
            marked = float(dirty.get(str(key), 0.0) or 0.0)
        else:
            marked = time.time() if str(key) in dirty else 0.0
        return max(0.0, time.time() - marked) if marked else 0.0

    def _record_dirty_refresh_diagnostic(self, key: str, age: float, detail: str = "") -> None:
        try:
            message = detail or f"Refreshing {key} from a dirty flag aged {int(age)}s"
            _append_control_panel_diagnostic_event({
                "event": "dirty-refresh",
                "scope": str(key),
                "age_seconds": int(age),
                "summary": message,
            })
            self._log_warning(message)
        except Exception:
            return

    def _is_tab_built_key(self, key: str) -> bool:
        index = self._tab_index_for_key(key)
        return index in getattr(self, "_tab_built", set())

    def _refresh_scope_now(self, key: str) -> None:
        key = str(key or "")
        if not key:
            return
        if key != "dashboard" and not self._is_tab_built_key(key):
            self._mark_dirty({key})
            return
        tab_index = self._tab_index_for_key(key)
        tab_widget = self.tabs.widget(tab_index) if hasattr(self, "tabs") and tab_index >= 0 else None
        if key in {"works", "series", "pages", "dashboard", "studio", "publish"}:
            self._set_tab_loading(tab_widget, True, f"Refreshing {key}…")
        try:
            if key == "works":
                self._safe_refresh_step("Works", self.refresh_work_list)
            elif key == "series":
                self._safe_refresh_step("Series", self.refresh_series_list)
            elif key == "relationships":
                self._safe_refresh_step("Relationships", self.refresh_relationships)
                self._relationships_dirty = False
            elif key == "pages":
                self._safe_refresh_step("Pages", self.refresh_pages_list)
            elif key == "authority":
                self._safe_refresh_step("Authority", self.refresh_authority_list)
            elif key == "validation":
                self._safe_refresh_step("Validation", self.refresh_validation)
            elif key == "dashboard":
                self._safe_refresh_step("Dashboard", self.refresh_dashboard)
            elif key == "studio":
                self._safe_refresh_step("Studio", self.refresh_studio)
                self._studio_dirty = False
            elif key == "publish":
                self._safe_refresh_step("Source reports", self.refresh_source_reports)
                self._safe_refresh_step("Release artifacts", self.refresh_release_artifacts)
                self._safe_refresh_step("Operation history", self.refresh_operation_history)
                self._publish_dirty = False
        finally:
            if key in {"works", "series", "pages", "dashboard", "studio", "publish"}:
                self._set_tab_loading(tab_widget, False)
        if key == "publish" and (getattr(self, "_publish_source_refresh_inflight", False) or getattr(self, "_release_artifact_refresh_inflight", False)):
            self._last_scope_refresh_at[key] = time.time()
            self._record_dirty_refresh_diagnostic(key, 0.0, "Publish refresh started asynchronously; dirty flag remains until data applies")
            return
        self._last_scope_refresh_at[key] = time.time()
        label = getattr(self, f"{key}_last_refreshed_label", None)
        if _qt_object_alive(label):
            label.setText("Last refreshed: " + datetime.now().strftime("%H:%M:%S"))
        self._dirty_tabs.pop(key, None)

    def _refresh_current_dirty_tab(self) -> None:
        key = self._current_tab_key()
        dirty = getattr(self, "_dirty_tabs", {})
        if not key or key not in dirty:
            return
        now = time.time()
        marked = float(dirty.get(key, now) if isinstance(dirty, dict) else now)
        age = max(0.0, now - marked)
        last_refresh = float(getattr(self, "_last_scope_refresh_at", {}).get(key, 0.0) or 0.0)
        # Dirty state is never expired without a real refresh. A stale flag means
        # a dependent tab still needs to reconcile data, even after idle time.
        if last_refresh >= marked:
            if isinstance(dirty, dict):
                dirty.pop(key, None)
            return
        if age > 60:
            self._record_dirty_refresh_diagnostic(key, age)
        self._refresh_scope_now(key)

    @contextmanager
    def _batched_widget_updates(self, *widgets: QWidget):
        targets = [w for w in widgets if w is not None]
        previous: list[tuple[QWidget, bool]] = []
        for widget in targets:
            try:
                previous.append((widget, widget.updatesEnabled()))
                widget.setUpdatesEnabled(False)
            except Exception as exc:
                self._log_warning(f"Could not suspend widget updates: {exc}")
        try:
            yield
        finally:
            for widget, was_enabled in previous:
                try:
                    widget.setUpdatesEnabled(was_enabled)
                    if was_enabled:
                        widget.update()
                        viewport = getattr(widget, "viewport", lambda: None)()
                        if viewport is not None:
                            viewport.update()
                except Exception as exc:
                    self._log_warning(f"Batched widget update failed: {exc}")

    @contextmanager
    def _soft_busy(self, label: str):
        old_progress = self.progress_hint.text() if hasattr(self, "progress_hint") else ""
        try:
            if hasattr(self, "progress_hint"):
                self.progress_hint.setText(label)
            if hasattr(self, "task_label"):
                self.task_label.set_status("running", label)
            yield
        finally:
            if hasattr(self, "progress_hint"):
                self.progress_hint.setText(old_progress)
            self._update_task_badge()
            self.refresh_context_inspector()

    def _safe_refresh_step(self, label: str, fn: Callable[[], None]) -> None:
        started = time.perf_counter()
        try:
            with self._batched_widget_updates(getattr(self, "tabs", None), getattr(self, "side_nav", None)):
                fn()
        except Exception as exc:
            self._log_warning(f"{label} refresh failed: {exc}")
            self.push_notification("error", f"{label} refresh failed", str(exc), target_scope="dashboard")
        finally:
            elapsed = (time.perf_counter() - started) * 1000.0
            try:
                self._refresh_coordinator.record_elapsed(label, elapsed)
            except Exception:
                pass
            self._record_perf(f"refresh:{label}", elapsed / 1000.0)

    def run_gui_smoke_test(self, *, interactive: bool = True) -> bool:
        if hasattr(self, "tabs"):
            for index in range(self.tabs.count()):
                self._ensure_tab_built(index)
        required = {
            "shell": ["main_toolbar", "side_nav", "tabs", "context_inspector"],
            "dashboard": ["dashboard_actions"],
            "works": ["work_tree", "work_search", "work_filter_preset_combo", "work_image_preview", "work_editor_panel", "work_save_btn"],
            "series": ["series_list", "series_sequence_list"],
            "pages": ["pages_list", "page_editor", "authority_list", "authority_editor"],
            "studio": ["studio_inner_tabs", "studio_validation", "studio_release_checks"],
            "publish": ["build_log"],
        }
        failures: list[str] = []
        original_index = self.tabs.currentIndex() if hasattr(self, "tabs") else 0
        for area, names in required.items():
            for name in names:
                if not hasattr(self, name):
                    failures.append(f"{area}: missing {name}")
        if hasattr(self, "tabs"):
            for index in range(self.tabs.count()):
                try:
                    with signals_blocked(self.tabs):
                        self.tabs.setCurrentIndex(index)
                    widget = self.tabs.widget(index)
                    if widget is None:
                        failures.append(f"tab {index}: no widget")
                    elif not widget.layout():
                        failures.append(f"tab {index}: no root layout")
                except Exception as exc:
                    failures.append(f"tab {index}: {exc}")
            with signals_blocked(self.tabs):
                self.tabs.setCurrentIndex(original_index)
        ok = not failures
        detail = "GUI smoke test passed." if ok else "\n".join(failures[:30])
        if len(failures) > 30:
            detail += f"\n… and {len(failures) - 30} more"
        self.push_notification("success" if ok else "error", "GUI smoke test", detail, target_scope="dashboard")
        self.status_message(detail.split("\n", 1)[0])
        if interactive:
            if ok:
                self._notify_nonblocking("success", "GUI smoke test passed", "All required control-panel widgets are wired.", target_scope="dashboard", toast="GUI smoke test passed")
            else:
                QMessageBox.warning(self, "GUI smoke test found issues", detail)
        return ok

    def request_refresh_event(self, event: str, *, force: bool = True, activate: str | None = None, select_work: str | None = None, select_series: str | None = None) -> None:
        refresh_event = RefreshEvent(str(event or "dashboard"))
        scopes = self._refresh_coordinator.expand(event=refresh_event.name)
        self._mark_dirty(scopes)
        self.refresh_all_context(force=force, scope=scopes, activate=activate, select_work=select_work, select_series=select_series)

    def refresh_all_context(
        self,
        checked: bool | None = None,
        *,
        activate: str | None = None,
        select_work: str | None = None,
        select_series: str | None = None,
        force: bool = False,
        scope: set[str] | None = None,
    ) -> None:
        if not force and not self.ensure_all_editors_safe():
            return
        if getattr(self, "_context_refresh_inflight", False):
            self._context_refresh_pending = True
            self._mark_dirty(set(scope) if scope else {"works", "series", "pages", "dashboard", "studio", "publish"})
            return
        self._context_refresh_inflight = True
        try:
            with self._soft_busy("Refreshing…"):
                self._dismissed_action_labels.clear()
                requested = self._expanded_refresh_scope(scope)
                current_key = self._current_tab_key()
                manual_full_refresh = scope is None and checked is not None
                for key in ["works", "series", "pages", "dashboard", "studio", "publish"]:
                    if key not in requested:
                        continue
                    should_refresh_now = key == "dashboard" or key == current_key or (manual_full_refresh and self._is_tab_built_key(key))
                    if should_refresh_now:
                        self._refresh_scope_now(key)
                    else:
                        self._mark_dirty({key})
                if activate == "works":
                    self.tabs.setCurrentWidget(self.works_tab)
                elif activate == "series":
                    self.tabs.setCurrentWidget(self.series_tab)
                if select_work:
                    self.select_work(select_work)
                if select_series:
                    self.select_series(select_series)
                self._refresh_current_dirty_tab()
                self.refresh_context_inspector()
        finally:
            self._context_refresh_inflight = False
            if getattr(self, "_context_refresh_pending", False):
                self._context_refresh_pending = False
                pending_scopes = set(getattr(self, "_dirty_tabs", {}).keys()) or {"dashboard"}
                if "dashboard" in pending_scopes and getattr(self, "_dashboard_refresh_inflight", False):
                    pending_scopes.discard("dashboard")
                if pending_scopes:
                    QTimer.singleShot(0, lambda scopes=set(pending_scopes): self.refresh_all_context(force=True, scope=scopes))


    # ---------- Phase 7-10 navigation, fixed layout density, readiness, and panel quality ----------
    def _clean_tab_label(self, label: str) -> str:
        value = str(label or "").replace("✓", "").replace("●", "").strip()
        if value.endswith(")") and "(" in value:
            value = value[:value.rfind("(")].strip()
        return value

    def _add_side_nav_header(self, label: str) -> None:
        header_item = QListWidgetItem(f"  {label.upper()}")
        header_item.setFlags(Qt.ItemFlag.NoItemFlags)
        header_item.setData(Qt.ItemDataRole.UserRole + 2, True)
        header_item.setData(Qt.ItemDataRole.UserRole + 4, str(label).upper())
        header_item.setForeground(QColor("#4a6a8a"))
        font = header_item.font()
        font.setPointSize(9)
        font.setWeight(QFont.Weight.Bold)
        header_item.setFont(font)
        self.side_nav.addItem(header_item)

    def _side_nav_count_for_index(self, index: int) -> int:
        widget = self.tabs.widget(index) if 0 <= index < self.tabs.count() else None
        if widget is self.dashboard_tab:
            return int(getattr(self, "_cached_dashboard_action_count", 0) or 0)
        if widget is self.works_tab:
            return int(getattr(self, "_cached_work_issue_count", 0) or 0)
        if widget is getattr(self, "validation_tab", None):
            return int(getattr(self, "_cached_validation_count", 0) or 0)
        return 0

    def _add_side_nav_item(self, index: int, *, prefix: str = "") -> None:
        label = self.tabs.tabText(index)
        base = self._clean_tab_label(label)
        item = QListWidgetItem(f"  {prefix}{base}")
        item.setToolTip(self.tabs.tabToolTip(index) or tab_purpose(base))
        item.setData(Qt.ItemDataRole.UserRole, index)
        count = self._side_nav_count_for_index(index)
        if count:
            item.setData(Qt.ItemDataRole.UserRole + 1, count)
            item.setData(Qt.ItemDataRole.UserRole + 3, "error" if count > 5 else "warning")
        self.side_nav.addItem(item)

    def _side_nav_row_for_tab(self, tab_index: int) -> int:
        for row in range(self.side_nav.count()):
            item = self.side_nav.item(row)
            if item and item.data(Qt.ItemDataRole.UserRole) == tab_index and (item.flags() & Qt.ItemFlag.ItemIsSelectable):
                return row
        return -1

    def configure_side_navigation(self) -> None:
        if not hasattr(self, "side_nav"):
            return
        with signals_blocked(self.side_nav):
            self.side_nav.clear()
            # Phase 15: remove duplicate Quick Access rows; the visible search bar and main nav now cover this path.
            current_group = None
            for index in range(self.tabs.count()):
                if self._tab_key_for_index(index) not in self._primary_nav_keys:
                    continue
                label = self._clean_tab_label(self.tabs.tabText(index))
                group = tab_group(label)
                if group != current_group:
                    current_group = group
                    self._add_side_nav_header(group)
                self._add_side_nav_item(index)
            advanced_indices = [index for index in range(self.tabs.count()) if self._tab_key_for_index(index) not in self._primary_nav_keys]
            if advanced_indices:
                self._add_side_nav_header("Advanced Tools")
                for idx in advanced_indices:
                    # Keep Studio available, but intentionally below daily workflows.
                    self._add_side_nav_item(idx, prefix="⋯ ")
            row = self._side_nav_row_for_tab(self.tabs.currentIndex())
            if row >= 0:
                self.side_nav.setCurrentRow(row)

    def _side_nav_changed(self, row: int) -> None:
        if getattr(self, "_nav_switch_guard", False):
            return
        if row < 0 or row >= self.side_nav.count():
            return
        item = self.side_nav.item(row)
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsSelectable):
            return
        target_data = item.data(Qt.ItemDataRole.UserRole)
        if target_data is None:
            return
        target = int(target_data)
        if target == self.tabs.currentIndex():
            return
        self._nav_switch_guard = True
        try:
            self.tabs.setCurrentIndex(target)
        finally:
            self._nav_switch_guard = False

    def sync_side_navigation(self) -> None:
        self.configure_side_navigation()
        dirty_map: dict[int, bool] = {}
        checks = [
            (self.works_tab if hasattr(self, "works_tab") else None, lambda: self.is_work_dirty()),
            (self.series_tab if hasattr(self, "series_tab") else None, lambda: self.is_series_dirty()),
            (self.pages_tab if hasattr(self, "pages_tab") else None, lambda: self.is_page_dirty()),
            (self.authority_tab if hasattr(self, "authority_tab") else None, lambda: self.is_authority_dirty()),
        ]
        for widget, fn in checks:
            if widget is None:
                continue
            index = self.tabs.indexOf(widget)
            if index >= 0:
                try:
                    dirty_map[index] = bool(fn())
                except Exception:
                    dirty_map[index] = False
        for row in range(self.side_nav.count()):
            item = self.side_nav.item(row)
            if item is None or not (item.flags() & Qt.ItemFlag.ItemIsSelectable):
                continue
            tab_index = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(tab_index, int) and dirty_map.get(tab_index):
                item.setForeground(QColor("#ffcf74"))
                item.setBackground(QColor("#1a1400"))
            else:
                item.setForeground(QColor("#9fb1c8"))
                item.setBackground(QColor("transparent"))

    def _apply_layout_rescue_defaults(self) -> None:
        """Last-mile GUI layout rescue: reduce scrollbars, prevent splitter collapse, and normalize dense widgets.

        This does not change website content or persisted portfolio data. It is intentionally
        visual/layout-only and safe to call after tabs are built.
        """
        try:
            if hasattr(self, "main_toolbar"):
                self.main_toolbar.setFixedHeight(46)
            if hasattr(self, "side_nav"):
                self.side_nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                self.side_nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                self.side_nav.setTextElideMode(Qt.TextElideMode.ElideRight)
                self.side_nav.setSpacing(2)
            if hasattr(self, "context_inspector"):
                self.context_inspector.setMinimumWidth(0)
                self.context_inspector.setMaximumWidth(260)
            for splitter in self.findChildren(QSplitter):
                splitter.setChildrenCollapsible(False)
                splitter.setHandleWidth(8)
            for tree in self.findChildren(QTreeWidget):
                try:
                    tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                    tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                    tree.setRootIsDecorated(False)
                    tree.setUniformRowHeights(True)
                    tree.setAlternatingRowColors(True)
                    tree.setTextElideMode(Qt.TextElideMode.ElideRight)
                    tree.setMinimumHeight(max(96, tree.minimumHeight()))
                    header = tree.header()
                    if header is not None:
                        header.setStretchLastSection(True)
                        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                except Exception as exc:
                    self._log_warning(f"Responsive tree polish failed: {exc}")
            for lst in self.findChildren(QListWidget):
                try:
                    lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                    lst.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                    lst.setTextElideMode(Qt.TextElideMode.ElideRight)
                    lst.setSpacing(max(2, lst.spacing()))
                except Exception as exc:
                    self._log_warning(f"Responsive list polish failed: {exc}")
            for edit in self.findChildren(QPlainTextEdit):
                try:
                    edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
                    edit.setTabChangesFocus(True)
                    edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                    edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                    if edit.isReadOnly() and edit.maximumHeight() > 16777200:
                        edit.setMaximumHeight(160)
                except Exception as exc:
                    self._log_warning(f"Responsive text edit polish failed: {exc}")
            if hasattr(self, "dashboard_main_splitter"):
                self.dashboard_main_splitter.setSizes([460, 540, 620])
            if hasattr(self, "dashboard_right_splitter"):
                self.dashboard_right_splitter.setSizes([240, 360])
            if hasattr(self, "series_main_splitter"):
                self.series_main_splitter.setSizes([300, 1180])
            if hasattr(self, "works_main_splitter"):
                self.works_main_splitter.setSizes([500, 1040])
                self._apply_works_responsive_layout()
            if hasattr(self, "pages_top_splitter"):
                self.pages_top_splitter.setSizes([650, 420])
            if hasattr(self, "publish_main_splitter"):
                self.publish_main_splitter.setSizes([760, 760])
            if hasattr(self, "main_splitter") and hasattr(self, "context_inspector") and not self.context_inspector.isVisible():
                self.main_splitter.setSizes([max(204, self.side_nav.width() if hasattr(self, "side_nav") else 220), 1400, 0])
        except Exception as exc:
            self._log_warning(f"Layout rescue defaults failed: {exc}")

    def apply_density_layout(self) -> None:
        """Apply fixed panel density decisions without changing public website output."""
        profile = density_profile(FIXED_CONTROL_PANEL_DENSITY)
        if hasattr(self, "side_nav"):
            self.side_nav.setMinimumWidth(180)
            self.side_nav.setMaximumWidth(240)
        if hasattr(self, "work_tree"):
            size = int(profile.get("thumb", 52))
            self.work_tree.setIconSize(QSize(size, size))
        for splitter in self.findChildren(QSplitter):
            try:
                splitter.setHandleWidth(8)
            except Exception as exc:
                self._log_warning(f"Splitter handle update failed: {exc}")
        row_h = int(profile.get("row", 30))
        for tree in self.findChildren(QTreeWidget):
            try:
                tree.setUniformRowHeights(True)
                tree.setAlternatingRowColors(True)
                tree.setProperty("densityRowHeight", row_h)
                tree.style().unpolish(tree); tree.style().polish(tree)
            except Exception as exc:
                self._log_warning(f"Fixed layout tree update failed: {exc}")
        if hasattr(self, "main_splitter"):
            try:
                width = int(profile.get("side_nav", 238))
                total = max(980, self.width())
                inspector = 240 if getattr(self, "context_inspector", None) is not None and self.context_inspector.isVisible() else 0
                editor = max(760, total - width - inspector - 48)
                self.main_splitter.setHandleWidth(8)
                self.main_splitter.setSizes([width, editor, inspector])
            except Exception as exc:
                self._log_warning(f"Could not apply fixed layout density: {exc}")

    def refresh_dashboard_live_status(self) -> None:
        """Lightweight dashboard pulse: task badge + recent activity only."""
        started = time.perf_counter()
        try:
            self._update_task_badge()
            self._update_session_health()
            if hasattr(self, "dashboard_activity") and self.tabs.currentWidget() is self.dashboard_tab:
                self._sync_activity_timeline(list(recent_operation_rows(10)), reset=False)
        except Exception as exc:
            self._log_warning(f"Live dashboard pulse failed: {exc}")
        finally:
            self._record_perf("live dashboard pulse", time.perf_counter() - started)

    def install_accessibility_shortcuts(self) -> None:
        """Add predictable keyboard affordances to the main control widgets."""
        def add_shortcut(widget: QWidget, sequence: str, slot: Callable[[], None]) -> None:
            shortcut = QShortcut(QKeySequence(sequence), widget)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

        if hasattr(self, "work_tree"):
            add_shortcut(self.work_tree, "Return", lambda: self.select_work(self._current_work_id) if self._current_work_id else None)
            add_shortcut(self.work_tree, "Enter", lambda: self.select_work(self._current_work_id) if self._current_work_id else None)
            add_shortcut(self.work_tree, "Delete", self.show_current_work_impact_report)
            self.work_tree.setToolTip("Works table. Enter opens the selected work; Delete opens safe remove/public-impact preview; double-click Review/Published to quick-edit.")
        if hasattr(self, "series_list"):
            add_shortcut(self.series_list, "Return", lambda: self.select_series(self._current_series_slug) if self._current_series_slug else None)
            add_shortcut(self.series_list, "Enter", lambda: self.select_series(self._current_series_slug) if self._current_series_slug else None)
            self.series_list.setToolTip("Series list. Enter reloads the selected series; Alt+Left/Right navigates series.")
        if hasattr(self, "series_sequence_list"):
            add_shortcut(self.series_sequence_list, "Alt+Up", lambda: self.move_series_sequence_item(-1))
            add_shortcut(self.series_sequence_list, "Alt+Down", lambda: self.move_series_sequence_item(1))
            self.series_sequence_list.setToolTip("Series sequence board. Drag items or use Alt+Up / Alt+Down for keyboard reordering.")
            self.series_sequence_list.setAccessibleName("Series sequence board with keyboard reordering")
        if hasattr(self, "page_sections_list"):
            add_shortcut(self.page_sections_list, "Alt+Up", lambda: self.move_page_section(-1))
            add_shortcut(self.page_sections_list, "Alt+Down", lambda: self.move_page_section(1))
            self.page_sections_list.setToolTip("Page section list. Use Alt+Up / Alt+Down to reorder sections without dragging.")
            self.page_sections_list.setAccessibleName("Page section list with keyboard reordering")
        if hasattr(self, "validation_tree"):
            add_shortcut(self.validation_tree, "Return", self.open_selected_validation_item)
            add_shortcut(self.validation_tree, "Enter", self.open_selected_validation_item)
            self.validation_tree.setToolTip("Validation list. Enter opens the selected issue target.")
        f6 = QShortcut(QKeySequence("F6"), self)
        f6.activated.connect(self._focus_next_zone)
        shift_f6 = QShortcut(QKeySequence("Shift+F6"), self)
        shift_f6.activated.connect(lambda: self._focus_next_zone(reverse=True))
        self.command_shortcuts["focus_next_zone"] = "F6"
        self.command_shortcuts["focus_previous_zone"] = "Shift+F6"

    def _focusable_widget_in_zone(self, zone: QWidget) -> QWidget:
        if zone.focusPolicy() != Qt.FocusPolicy.NoFocus:
            return zone
        for child in zone.findChildren(QWidget):
            if child.isVisible() and child.isEnabled() and child.focusPolicy() != Qt.FocusPolicy.NoFocus:
                return child
        return zone

    def _focus_next_zone(self, reverse: bool = False) -> None:
        toolbar = self.findChild(QToolBar)
        zones: list[tuple[str, QWidget]] = []
        if toolbar is not None:
            zones.append(("toolbar", toolbar))
        if hasattr(self, "side_nav"):
            zones.append(("side nav", self.side_nav))
        if hasattr(self, "tabs") and self.tabs.currentWidget() is not None:
            zones.append(("editor", self.tabs.currentWidget()))
        if self.statusBar() is not None:
            zones.append(("status bar", self.statusBar()))
        if not zones:
            return
        focused = QApplication.focusWidget()
        current_index = -1
        for idx, (_name, zone) in enumerate(zones):
            if focused is zone or (focused is not None and zone.isAncestorOf(focused)):
                current_index = idx
                break
        step = -1 if reverse else 1
        next_index = (current_index + step) % len(zones)
        name, zone = zones[next_index]
        self._focusable_widget_in_zone(zone).setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.status_message(f"Focus: {name}")


    def _apply_readiness_widget(self, readiness: dict[str, Any]) -> None:
        if not hasattr(self, "readiness_gauge"):
            return
        score = int(readiness.get("score") or 0)
        status = str(readiness.get("status") or "unknown")
        metrics = readiness.get("metrics") if isinstance(readiness.get("metrics"), dict) else {}
        self.readiness_gauge.set_score(score)
        if hasattr(self, "readiness_score_label"):
            self.readiness_score_label.setText(f"{score}/100")
        detail = [
            f"Status: {status}",
            f"Validation errors: {metrics.get('validation_errors', 0)}",
            f"Source issues: {metrics.get('source_issues', 0)}",
            f"Metadata issues: {metrics.get('metadata_issues', 0)}",
            f"Series below 75: {metrics.get('series_below_75', 0)}",
        ]
        self.readiness_status_label.setText(" · ".join(detail))
        self.readiness_action_tree.clear()
        for row in list(readiness.get("actions") or []):
            item = QTreeWidgetItem([str(row.get("label") or ""), str(row.get("count") or ""), str(row.get("target") or "")])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            self.readiness_action_tree.addTopLevelItem(item)

    def open_readiness_action(self, item: QTreeWidgetItem | None = None, column: int = 0) -> None:
        row = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else {}
        target = str((row or {}).get("target") or "")
        if target == "validation":
            self.open_validation_panel()
            return
        if target == "source_recovery":
            self.open_source_recovery_dialog()
            return
        mapping = {
            "works": self.works_tab,
            "series": self.series_tab,
            "studio": self.studio_tab,
            "publish": self.publish_tab,
        }
        widget = mapping.get(target)
        if widget is not None:
            self.tabs.setCurrentWidget(widget)
        else:
            self.open_readiness_report()

    def open_guided_add_work(self) -> None:
        dialog = AddImageDialog(self)
        dialog.setWindowTitle("Guided add work · image, metadata, series, preview, validation")
        dialog.exec()

    def open_readiness_report(self) -> None:
        try:
            health = portfolio_health_report(force=True, save=True, timeout_seconds=10.0)
            readiness = dict(health.get("readiness") or {})
        except Exception as exc:
            QMessageBox.critical(self, "Readiness failed", str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Portfolio readiness report")
        dialog.resize(760, 560)
        layout = QVBoxLayout(dialog)
        header = QLabel(f"Readiness: {int(readiness.get('score') or 0)}/100 · {readiness.get('status') or 'unknown'}")
        header.setObjectName("missionStatus")
        header.setWordWrap(True)
        layout.addWidget(header)
        tree = QTreeWidget()
        tree.setHeaderLabels(["Action", "Count", "Target"])
        for row in list(readiness.get("actions") or []):
            tree.addTopLevelItem(QTreeWidgetItem([str(row.get("label") or ""), str(row.get("count") or ""), str(row.get("target") or "")]))
        layout.addWidget(tree, 1)
        metrics = QPlainTextEdit()
        metrics.setReadOnly(True)
        metrics.setPlainText(json.dumps(readiness.get("metrics") or {}, ensure_ascii=False, indent=2))
        layout.addWidget(metrics, 1)
        row = QHBoxLayout()
        open_validation = QPushButton("Open validation")
        open_validation.clicked.connect(lambda: (dialog.accept(), self.open_validation_panel()))
        row.addWidget(open_validation)
        open_studio = QPushButton("Open studio")
        open_studio.clicked.connect(lambda: (dialog.accept(), self._ensure_tab_built_by_key("studio"), self.tabs.setCurrentWidget(self.studio_tab)))
        row.addWidget(open_studio)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)
        dialog.exec()

    def open_source_recovery_dialog(self) -> None:
        try:
            summary = source_recovery_summary(use_cache=True)
        except Exception as exc:
            QMessageBox.critical(self, "Source recovery failed", str(exc))
            return
        rows = list(summary.get("rows") or [])
        dialog = QDialog(self)
        dialog.setWindowTitle("Source recovery")
        dialog.resize(920, 600)
        layout = QVBoxLayout(dialog)
        header = QLabel(str(summary.get("label") or "Source recovery"))
        header.setObjectName("missionStatus")
        header.setWordWrap(True)
        layout.addWidget(header)
        helper = QLabel("Focused workflow for missing original/source images. This does not change the public website UI; it only repairs control-panel source truth and image links.")
        helper.setWordWrap(True)
        layout.addWidget(helper)
        tree = QTreeWidget()
        tree.setHeaderLabels(["Work ID", "Title", "Series", "Status", "Recovery", "Detail"])
        tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        tree.setColumnWidth(0, 150)
        tree.setColumnWidth(1, 190)
        tree.setColumnWidth(2, 140)
        tree.setColumnWidth(3, 90)
        for row in rows:
            item = QTreeWidgetItem([
                str(row.get("id") or ""),
                str(row.get("title") or ""),
                str(row.get("series") or ""),
                str(row.get("status") or ""),
                str(row.get("recovery") or row.get("priority") or ""),
                str(row.get("detail") or ""),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            tree.addTopLevelItem(item)
        if tree.topLevelItemCount():
            tree.setCurrentItem(tree.topLevelItem(0))
        layout.addWidget(tree, 1)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setMaximumHeight(120)
        layout.addWidget(details)

        def update_detail() -> None:
            item = tree.currentItem()
            row = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else {}
            if not isinstance(row, dict):
                row = {}
            expected = ", ".join(row.get("expected_stems") or []) or "—"
            details.setPlainText("\n".join([
                f"Work ID: {row.get('id') or '—'}",
                f"Expected source names: {expected}",
                f"Source folder: {row.get('source_dir') or row.get('expected_dir') or '—'}",
                f"Recovery: {row.get('recovery') or 'Manual relink recommended'}",
            ]))

        tree.itemSelectionChanged.connect(update_detail)
        update_detail()

        buttons = QHBoxLayout()
        repair_btn = QPushButton("Repair recoverable")
        repair_btn.clicked.connect(lambda: (dialog.accept(), self.run_repair_missing_sources()))
        buttons.addWidget(repair_btn)
        relink_btn = QPushButton("Relink selected…")
        def relink_selected() -> None:
            item = tree.currentItem()
            row = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else {}
            work_id = str((row or {}).get("id") or "")
            if not work_id:
                return
            path, _ = QFileDialog.getOpenFileName(self, f"Relink source for {work_id}", str(ROOT), "Images (*.jpg *.jpeg *.png *.webp *.tif *.tiff)")
            if not path:
                return
            dialog.accept()
            self.append_build_log_line(f"Relinking source image for {work_id}…")
            self.start_task(f"Relink source {work_id}", lambda: relink_source_image(work_id, path, line_callback=self._emit_line), on_done=self._relink_source_done)
        relink_btn.clicked.connect(relink_selected)
        buttons.addWidget(relink_btn)
        bulk_btn = QPushButton("Bulk relink folder…")
        bulk_btn.clicked.connect(lambda: (dialog.accept(), self.bulk_relink_sources_from_folder()))
        buttons.addWidget(bulk_btn)
        open_studio = QPushButton("Open Studio source panel")
        open_studio.clicked.connect(lambda: (dialog.accept(), self._ensure_tab_built_by_key("studio"), self.tabs.setCurrentWidget(self.studio_tab)))
        buttons.addWidget(open_studio)
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        dialog.exec()

    def open_task_monitor(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Task monitor")
        dialog.resize(720, 500)
        layout = QVBoxLayout(dialog)
        status = QLabel(f"Active: {self._active_task_label or 'none'} · queued: {len(self._task_queue)}")
        status.setObjectName("missionStatus")
        layout.addWidget(status)
        progress = QProgressBar()
        progress.setRange(0, 0 if self._running_tasks else 1)
        progress.setValue(0 if self._running_tasks else 1)
        progress.setFormat("Running…" if self._running_tasks else "Idle")
        layout.addWidget(progress)
        tree = QTreeWidget()
        tree.setHeaderLabels(["State", "Task", "Detail"])
        if self._active_task_label:
            tree.addTopLevelItem(QTreeWidgetItem(["running", self._active_task_label, "Active worker cannot be force-cancelled safely; queued tasks can be cleared."]))
        for label, _fn, _done in list(self._task_queue):
            tree.addTopLevelItem(QTreeWidgetItem(["queued", label, "Waiting for active task"]))
        for row in list(getattr(self, "_task_history", []))[:20]:
            tree.addTopLevelItem(QTreeWidgetItem([str(row.get("status") or ""), str(row.get("label") or ""), str(row.get("detail") or "")]))
        layout.addWidget(tree, 1)
        buttons = QHBoxLayout()
        cancel_queue = QPushButton("Clear queued tasks")
        cancel_queue.clicked.connect(lambda: (self.cancel_queued_tasks(), dialog.accept()))
        buttons.addWidget(cancel_queue)
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        dialog.exec()

    def cancel_queued_tasks(self) -> None:
        count = len(self._task_queue)
        if not count:
            self.status_message("No queued tasks to clear")
            return
        self._task_queue.clear()
        self._task_history.insert(0, {"label": "queued tasks", "status": "cancelled", "detail": f"{count} queued task(s) cleared"})
        self._task_history = self._task_history[:30]
        self._update_task_badge()
        self.push_notification("info", "Cleared queued tasks", f"{count} queued task(s) removed.", target_scope="publish")
        self.status_message(f"Cleared {count} queued task(s)")

    def _runtime_accessibility_rows(self) -> list[dict[str, str]]:
        """Phase 19: inspect the live widget tree, not only source-code markers."""
        rows: list[dict[str, str]] = []
        focusable = 0
        missing_tooltips = 0
        missing_accessible_names = 0
        tiny_targets = 0
        context_widgets = 0
        drag_widgets_without_keyboard_hint = 0
        tab_stop_order_breaks = 0
        last_tab_index = -1
        inspected_types = (QPushButton, QLineEdit, QComboBox, QTreeWidget, QListWidget)
        for widget in QApplication.allWidgets():
            try:
                if not widget.isVisible() or widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
                    continue
                focusable += 1
                if isinstance(widget, inspected_types) and not widget.toolTip():
                    missing_tooltips += 1
                if isinstance(widget, inspected_types) and not widget.accessibleName():
                    missing_accessible_names += 1
                size = widget.size()
                if isinstance(widget, QPushButton) and (size.width() < 32 or size.height() < 28):
                    tiny_targets += 1
                if widget.contextMenuPolicy() != Qt.ContextMenuPolicy.NoContextMenu:
                    context_widgets += 1
                if isinstance(widget, (QListWidget, QTreeWidget)) and widget.dragDropMode() != QAbstractItemView.DragDropMode.NoDragDrop:
                    hint = f"{widget.toolTip()} {widget.accessibleDescription()}".lower()
                    if "keyboard" not in hint and "move up" not in hint and "move down" not in hint:
                        drag_widgets_without_keyboard_hint += 1
                tab_index = int(widget.property("tabIndex") or -1)
                if tab_index >= 0:
                    if last_tab_index > tab_index:
                        tab_stop_order_breaks += 1
                    last_tab_index = tab_index
            except RuntimeError:
                continue
            except Exception as exc:
                self._log_warning(f"Accessibility widget inspection failed: {exc}")
        rows.append({"status": "watch" if missing_tooltips else "ok", "check": "Runtime tooltips", "detail": f"{missing_tooltips} of {focusable} focusable controls have no tooltip."})
        rows.append({"status": "watch" if missing_accessible_names else "ok", "check": "Accessible names", "detail": f"{missing_accessible_names} focusable controls are missing an accessible name."})
        rows.append({"status": "watch" if tiny_targets else "ok", "check": "Target size", "detail": f"{tiny_targets} visible buttons are below the control-panel target-size floor."})
        rows.append({"status": "ok" if not drag_widgets_without_keyboard_hint else "watch", "check": "Drag alternatives", "detail": f"{drag_widgets_without_keyboard_hint} drag/drop list(s) need an explicit keyboard-move hint."})
        rows.append({"status": "ok" if not tab_stop_order_breaks else "watch", "check": "Tab order", "detail": f"{tab_stop_order_breaks} possible tab-order break(s) found in visible controls."})
        rows.append({"status": "ok", "check": "Context menus", "detail": f"{context_widgets} widget(s) expose contextual actions; command palette remains available from Ctrl+K."})
        rows.append({"status": "ok", "check": "Keyboard focus", "detail": f"{focusable} focusable controls detected; visible focus styling is enabled in the theme."})
        rows.append({"status": "ok", "check": "Focus not obscured", "detail": "F6 zone navigation and visible focus rings keep focus recoverable when drawers/overlays are open."})
        rows.append({"status": "ok" if getattr(self, "_reduced_motion", False) else "info", "check": "Reduced motion", "detail": "Enabled" if getattr(self, "_reduced_motion", False) else "Available from the command palette."})
        return rows

    def open_accessibility_audit(self) -> None:
        try:
            rows = list(panel_accessibility_static_audit())
        except Exception as exc:
            rows = [{"status": "error", "check": "Static audit", "detail": str(exc)}]
        rows.extend(self._runtime_accessibility_rows())
        self._show_rows_dialog("Control-panel accessibility audit", ["Status", "Check", "Detail"], rows, ["status", "check", "detail"], width=900, height=600)

    def open_panel_diagnostics(self) -> None:
        try:
            diagnostics = control_panel_diagnostics()
        except Exception as exc:
            self._critical_modal("Panel diagnostics failed", str(exc), target_scope="diagnostics")
            return
        rows = list(diagnostics.get("rows") or [])
        save_panel_diagnostics_snapshot(diagnostics)
        dialog = QDialog(self)
        dialog.setWindowTitle("Control-panel diagnostics")
        dialog.resize(900, 580)
        layout = QVBoxLayout(dialog)
        tree = QTreeWidget()
        tree.setHeaderLabels(["Area", "Status", "Detail"])
        tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for row in rows:
            item = QTreeWidgetItem([str(row.get("area") or ""), str(row.get("status") or ""), str(row.get("detail") or "")])
            color = self._severity_color(str(row.get("status") or "info"))
            for col in range(3):
                item.setForeground(col, color)
            tree.addTopLevelItem(item)
        layout.addWidget(tree, 1)
        buttons = QHBoxLayout()
        bundle_btn = QPushButton("Export diagnostic bundle")
        bundle_btn.clicked.connect(lambda: (self.export_panel_diagnostic_bundle(), dialog.accept()))
        stale_btn = QPushButton("Stale asset report")
        stale_btn.clicked.connect(self.show_stale_asset_cleanup_report)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(bundle_btn)
        buttons.addWidget(stale_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        dialog.exec()

    def export_panel_diagnostic_bundle(self) -> None:
        try:
            path = export_control_panel_diagnostic_bundle()
        except Exception as exc:
            self._critical_modal("Diagnostic export failed", str(exc), target_scope="diagnostics")
            return
        self._notify_nonblocking(
            "success",
            "Diagnostic bundle exported",
            str(path),
            target_scope="diagnostics",
            toast="Diagnostic bundle exported",
        )

    def show_stale_asset_cleanup_report(self) -> None:
        try:
            rows = stale_asset_cleanup_report()
        except Exception as exc:
            self._critical_modal("Stale asset report failed", str(exc), target_scope="diagnostics")
            return
        if not rows:
            self._notify_nonblocking(
                "success",
                "Stale asset report clean",
                "No stale derivative folders were detected in the generated image tree.",
                target_scope="diagnostics",
                toast="No stale asset folders detected",
            )
            return
        self._show_rows_dialog(
            "Stale asset cleanup report",
            ["Kind", "Series", "Render name", "Files", "Path", "Safe action"],
            rows,
            ["kind", "series", "render_name", "file_count", "path", "safe_action"],
            width=1040,
            height=560,
        )

    def _show_rows_dialog(self, title: str, headers: list[str], rows: list[dict[str, Any]], keys: list[str], *, width: int = 760, height: int = 520) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(width, height)
        layout = QVBoxLayout(dialog)
        tree = QTreeWidget()
        tree.setHeaderLabels(headers)
        tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for row in rows:
            item = QTreeWidgetItem([str(row.get(key) or "") for key in keys])
            color = self._severity_color(str(row.get(keys[0]) or row.get("status") or "info"))
            for col in range(len(headers)):
                item.setForeground(col, color)
            tree.addTopLevelItem(item)
        layout.addWidget(tree, 1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()

    def open_inquiry_tracker(self) -> None:
        self._open_record_manager(
            title="Private inquiry tracker",
            load_fn=load_inquiries,
            save_fn=save_inquiry_record,
            delete_fn=delete_inquiry_record,
            headers=["ID", "Contact", "Subject", "Status", "Priority", "Note"],
            fields=["id", "contact", "subject", "status", "priority", "note"],
            defaults={"status": "new", "priority": "normal"},
        )

    def open_print_edition_manager(self) -> None:
        self._open_record_manager(
            title="Private print / edition manager",
            load_fn=load_print_editions,
            save_fn=save_print_edition_record,
            delete_fn=delete_print_edition_record,
            headers=["ID", "Work ID", "Title", "Status", "Size", "Paper", "Edition", "Price", "Note"],
            fields=["id", "work_id", "title", "status", "size", "paper", "edition", "price", "note"],
            defaults={"status": "draft"},
        )

    def _open_record_manager(
        self,
        *,
        title: str,
        load_fn: Callable[[], list[dict[str, Any]]],
        save_fn: Callable[[dict[str, Any]], dict[str, Any]],
        delete_fn: Callable[[str], int],
        headers: list[str],
        fields: list[str],
        defaults: dict[str, Any] | None = None,
    ) -> None:
        defaults = defaults or {}
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(980, 620)
        layout = QVBoxLayout(dialog)
        help_label = QLabel("Private control-panel metadata only. These records do not change the public website.")
        help_label.setObjectName("missionStatus")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        split = QSplitter(Qt.Orientation.Horizontal)
        tree = QTreeWidget()
        tree.setHeaderLabels(headers)
        tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        split.addWidget(tree)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        edits: dict[str, QWidget] = {}
        for field in fields:
            if field == "note":
                edit = QPlainTextEdit()
                edit.setFixedHeight(150)
            else:
                edit = QLineEdit()
            edits[field] = edit
            form.addRow(field.replace("_", " ").title(), edit)
        split.addWidget(form_widget)
        split.setSizes([520, 420])
        layout.addWidget(split, 1)

        def load_rows() -> None:
            tree.clear()
            for row in load_fn():
                item = QTreeWidgetItem([str(row.get(field) or "") for field in fields])
                item.setData(0, Qt.ItemDataRole.UserRole, row)
                tree.addTopLevelItem(item)

        def fill_form(item: QTreeWidgetItem | None = None) -> None:
            row = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else {}
            for field, edit in edits.items():
                value = str((row or {}).get(field) or defaults.get(field) or "")
                if isinstance(edit, QPlainTextEdit):
                    edit.setPlainText(value)
                elif isinstance(edit, QLineEdit):
                    edit.setText(value)

        def collect_form() -> dict[str, Any]:
            row: dict[str, Any] = {}
            for field, edit in edits.items():
                if isinstance(edit, QPlainTextEdit):
                    row[field] = edit.toPlainText()
                elif isinstance(edit, QLineEdit):
                    row[field] = edit.text()
            return row

        def save_record() -> None:
            try:
                saved = save_fn(collect_form())
            except Exception as exc:
                QMessageBox.critical(dialog, "Save failed", str(exc))
                return
            self.push_notification("success", f"Saved {title}", str(saved.get("id") or ""), target_scope="studio")
            load_rows()
            fill_form(None)

        def delete_record() -> None:
            item = tree.currentItem()
            if item is None:
                return
            row = item.data(0, Qt.ItemDataRole.UserRole) or {}
            record_id = str(row.get("id") or "")
            if not record_id:
                return
            if QMessageBox.question(dialog, "Delete record", f"Delete private record {record_id}?") != QMessageBox.StandardButton.Yes:
                return
            try:
                delete_fn(record_id)
            except Exception as exc:
                QMessageBox.critical(dialog, "Delete failed", str(exc))
                return
            load_rows()
            fill_form(None)

        tree.itemSelectionChanged.connect(lambda: fill_form(tree.currentItem()))
        button_row = QHBoxLayout()
        new_btn = QPushButton("New")
        new_btn.clicked.connect(lambda: fill_form(None))
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(save_record)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(delete_record)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        for button in (new_btn, save_btn, delete_btn):
            button_row.addWidget(button)
        button_row.addStretch(1)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)
        load_rows()
        fill_form(None)
        dialog.exec()

    def update_tab_badges(self) -> None:
        if not hasattr(self, "tabs"):
            return
        work_issues = int(getattr(self, "_cached_work_issue_count", 0) or 0)
        validation_count = int(getattr(self, "_cached_validation_count", 0) or 0)
        action_count = int(getattr(self, '_cached_dashboard_action_count', 0) or 0)
        series_count = int(getattr(self, '_cached_series_count', 0) or 0)
        page_count = int(getattr(self, '_cached_pages_count', 0) or 0)
        labels_by_key = {
            "dashboard": f"Dashboard ({action_count})" if action_count else "Dashboard",
            "works": f"Works ({work_issues})" if work_issues else "Works",
            "series": f"Series ({series_count})",
            "relationships": "Relationships",
            "pages": f"Content Builder ({page_count})",
            "authority": f"Content Authority ({len(AUTHORITY_FILES)})",
            "validation": f"Validation ({validation_count})" if validation_count else "Validation",
            "studio": "Studio",
            "publish": "Publish",
        }
        dirty_by_key = {
            "works": self.is_work_dirty() if self._is_tab_built_key("works") else False,
            "series": self.is_series_dirty() if self._is_tab_built_key("series") else False,
            "pages": self.is_page_dirty() if self._is_tab_built_key("pages") else False,
            "authority": self.is_authority_dirty() if self._is_tab_built_key("authority") else False,
        }
        tooltips_by_key = {
            "dashboard": "Action center items requiring attention right now.",
            "works": f"{work_issues} work(s) need metadata attention such as missing caption, weak alt text, or missing focal point.",
            "series": "Series count in the current library.",
            "pages": "Structured page editor with live YAML sync, validation, and change review for every editable page.",
            "authority": "Global site, artist, navigation, resources, and release documents.",
            "validation": f"{validation_count} validation issue(s) across works, series, and pages.",
        }
        for index in range(self.tabs.count()):
            key = self._tab_key_for_index(index)
            label = labels_by_key.get(key, self.tabs.tabText(index).lstrip('● '))
            if dirty_by_key.get(key):
                label = f"● {label}"
            self.tabs.setTabText(index, label)
            self.tabs.setTabToolTip(index, tooltips_by_key.get(key, ""))
        self.sync_side_navigation()

    def _flush_editor_draft_for_widget(self, widget: QWidget | None) -> None:
        try:
            if widget is getattr(self, "works_tab", None) and self._is_tab_built_key("works"):
                self._autosave_work_draft()
            elif widget is getattr(self, "series_tab", None) and self._is_tab_built_key("series"):
                self._autosave_series_draft()
            elif widget is getattr(self, "pages_tab", None) and self._is_tab_built_key("pages"):
                self._autosave_page_draft()
            elif widget is getattr(self, "authority_tab", None) and self._is_tab_built_key("authority"):
                self._autosave_authority_draft()
        except Exception as exc:
            self._log_warning(f"Could not flush editor draft before tab switch: {exc}")

    def on_tab_changed(self, index: int) -> None:
        if getattr(self, "_context_refresh_inflight", False):
            previous = getattr(self, "_last_tab_index", index)
            if previous != index and hasattr(self, "tabs"):
                with signals_blocked(self.tabs):
                    self.tabs.setCurrentIndex(previous)
                previous_key = self._tab_key_for_index(previous) or "dashboard"
                self._context_refresh_pending = True
                # Leaving a tab while a context refresh is active should only mark
                # the old scope dirty. Reloading it immediately competes with the
                # tab being entered and was the main source of navigation jank.
                self._mark_dirty({previous_key})
            return
        if getattr(self, "_tab_switch_guard", False):
            return
        self._tab_switch_guard = True
        previous = getattr(self, "_last_tab_index", index)
        try:
            dirty_checks = {}
            if self._is_tab_built_key("works"):
                dirty_checks[getattr(self, "works_tab", None)] = (self.is_work_dirty, self.ensure_work_editor_safe)
            if self._is_tab_built_key("series"):
                dirty_checks[getattr(self, "series_tab", None)] = (self.is_series_dirty, self.ensure_series_editor_safe)
            if self._is_tab_built_key("pages"):
                dirty_checks[getattr(self, "pages_tab", None)] = (self.is_page_dirty, self.ensure_page_editor_safe)
            if self._is_tab_built_key("authority"):
                dirty_checks[getattr(self, "authority_tab", None)] = (self.is_authority_dirty, self.ensure_authority_editor_safe)
            previous_widget = self.tabs.widget(previous) if 0 <= previous < self.tabs.count() else None
            self._flush_editor_draft_for_widget(previous_widget)
            checker = dirty_checks.get(previous_widget)
            if checker and checker[0]():
                if not checker[1]():
                    with signals_blocked(self.tabs):
                        self.tabs.setCurrentIndex(previous)
                    self._last_tab_index = previous
                    return
            self._last_tab_index = index
            if not getattr(self, "_nav_switch_guard", False) and 0 <= index < self.tabs.count():
                self._recent_tab_indices = ([index] + [i for i in getattr(self, "_recent_tab_indices", []) if i != index])[:3]
            current_widget = self._ensure_tab_built(index)
            current_key = self._tab_key_for_index(index)
            if current_key in getattr(self, "_dirty_tabs", {}):
                self._refresh_current_dirty_tab()
            elif current_key == "studio" and self._studio_dirty:
                self.refresh_studio()
                self._studio_dirty = False
            elif current_key == "relationships" and self._relationships_dirty:
                self.refresh_relationships()
                self._relationships_dirty = False
            elif current_key == "publish" and getattr(self, "_publish_dirty", False):
                self.refresh_source_reports()
                self.refresh_release_artifacts()
                self.refresh_operation_history()
                self._publish_dirty = False
            self.sync_side_navigation()
            self.refresh_context_inspector()
            self._state_save_timer.start()
        finally:
            self._tab_switch_guard = False

    def open_authority_panel(self, key: str | None = None) -> None:
        self._ensure_tab_built_by_key("pages")
        if hasattr(self, "tabs") and getattr(self, "pages_tab", None) is not None:
            self.tabs.setCurrentWidget(self.pages_tab)
        if hasattr(self, "content_inner_tabs"):
            try:
                self.content_inner_tabs.setCurrentIndex(1)
            except Exception as exc:
                self._log_warning(f"Could not switch to authority inner tab: {exc}")
        if key:
            self.select_authority(str(key))

    def open_validation_panel(self) -> None:
        self._ensure_tab_built_by_key("studio")
        if hasattr(self, "tabs") and getattr(self, "studio_tab", None) is not None:
            self.tabs.setCurrentWidget(self.studio_tab)
        if hasattr(self, "studio_inner_tabs"):
            try:
                self.studio_inner_tabs.setCurrentIndex(2)
            except Exception as exc:
                self._log_warning(f"Could not switch to Studio validation view: {exc}")
        if self._studio_data_cache is None or self._studio_dirty:
            self.refresh_studio()
        else:
            self._populate_studio_visible_subview()

    def open_relationships_panel(self) -> None:
        if self._relationships_dialog is not None and self._relationships_dialog.isVisible():
            self._relationships_dialog.raise_()
            self._relationships_dialog.activateWindow()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Relationships")
        dialog.resize(1180, 760)
        layout = QVBoxLayout(dialog)
        self.relationships_tab = self.build_relationships_tab()
        layout.addWidget(self.relationships_tab, 1)
        buttons = QHBoxLayout(); buttons.addStretch(1)
        save_btn = QPushButton("Save relationships"); save_btn.clicked.connect(self.save_relationships_tab)
        close_btn = QPushButton("Close"); close_btn.clicked.connect(dialog.close)
        buttons.addWidget(save_btn); buttons.addWidget(close_btn); layout.addLayout(buttons)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.finished.connect(lambda _result=0: setattr(self, "_relationships_dialog", None))
        self._relationships_dialog = dialog
        self.refresh_relationships()
        dialog.show()

    def register_commands(self) -> None:
        self.command_map = {
            "refresh": ("Refresh all", self.refresh_all_context, "Reload dashboard, validation, and editors."),
            "add_image": ("Add image", self.open_add_image_dialog, "Create a new work and ingest its image into a series."),
            "bulk_image_ingest": ("Bulk image ingest", self.open_bulk_image_ingest_dialog, "Add multiple originals into a series with generated IDs and review preview."),
            "metadata_audit": ("Work metadata audit", self.open_metadata_audit_dialog, "Audit selected or all works for missing metadata, weak alt text, and image readiness."),
            "duplicate_scan": ("Duplicate image scan", self.open_duplicate_scan_dialog, "Find likely duplicate or near-duplicate images by perceptual hash."),
            "work_lineage": ("Open work lineage", self.open_work_lineage_dialog, "Inspect source image, generated derivatives, social refs, and asset presence for the selected work."),
            "verify_work_assets": ("Verify selected work assets", self.verify_current_work_assets, "Check source truth, derivatives, stale refs, and same-ID orphan risk for the selected work."),
            "build": ("Build site", self.run_build_site, "Run build_site.py and stream the log."),
            "prepare_publish": ("Prepare publish", self.run_prepare_publish, "Generate OG images, build the site, and create a deploy zip."),
            "preview": ("Open preview", self.open_preview, "Open the generated public preview in a browser."),
            "release_workspace": ("Open release workspace", self.open_release_workspace, "Inspect release report, content graph, upload manifest, and public_upload files."),
            "create_upload_zip": ("Create upload zip", self.create_upload_zip, "Package the public_upload folder into a host-ready upload archive."),
            "release_gate": ("Release gate summary", self.show_release_gate_summary, "Show blocking errors, warnings, and publish readiness before packaging."),
            "public_diff": ("Public output diff", self.show_public_output_diff, "Compare public_upload against the last saved output snapshot."),
            "release_snapshot": ("Create release snapshot", self.create_named_release_snapshot, "Create a named content/control metadata snapshot before risky release work."),
            "focus_next_zone": ("Focus next zone", self._focus_next_zone, "Cycle keyboard focus through toolbar, side nav, current editor, and status bar."),
            "focus_previous_zone": ("Focus previous zone", lambda: self._focus_next_zone(reverse=True), "Cycle keyboard focus backward through toolbar, side nav, current editor, and status bar."),
            "open_public_upload": ("Open public_upload folder", self.open_public_upload_folder, "Open the generated upload folder that should be pushed to your host."),
            "notifications": ("Open notification center", self.open_notification_center, "Review task results, errors, saves, and queued actions."),
            "validation": ("Refresh validation", self.refresh_validation, "Re-scan works, series, and pages for issues."),
            "open_validation_item": ("Open selected validation item", self.open_selected_validation_item, "Open the currently selected validation issue in its editor."),
            "new_series": ("New series", self.open_new_series_dialog, "Create a new series shell."),
            "series_curation": ("Series curation workspace", self.open_series_curation_workspace, "Review series completeness and image rhythm before publishing."),
            "duplicate_work": ("Duplicate selected work", self.duplicate_selected_work, "Clone the current work as a draft."),
            "replace_image": ("Replace selected work image", self.open_replace_image_dialog, "Swap the source image for the selected work."),
            "safe_remove_work": ("Archive / delete selected image", self.safe_remove_current_work, "Preview references, then archive or delete the selected image and its assets."),
            "batch_publish": ("Publish selected works", self.batch_publish_selected_works, "Publish the currently selected works."),
            "batch_unpublish": ("Unpublish selected works", self.batch_unpublish_selected_works, "Remove the published flag from the selected works."),
            "mark_review": ("Mark selected works review", self.batch_mark_review_selected_works, "Set selected works to review."),
            "save_current": ("Save current tab", self.save_current_tab, "Save the current editor tab."),
            "undo_batch": ("Undo last batch operation", self.restore_last_completed_operation, "Roll back the most recently completed batch change."),
            "next_work": ("Next work", lambda: self.navigate_work(1), "Load the next visible work in the filtered list."),
            "previous_work": ("Previous work", lambda: self.navigate_work(-1), "Load the previous visible work in the filtered list."),
            "next_series": ("Next series", lambda: self.navigate_series(1), "Load the next series in the list."),
            "previous_series": ("Previous series", lambda: self.navigate_series(-1), "Load the previous series in the list."),
            "next_page": ("Next page", lambda: self.navigate_page(1), "Load the next page in the Content Builder list."),
            "previous_page": ("Previous page", lambda: self.navigate_page(-1), "Load the previous page in the Content Builder list."),
            "clear_filters": ("Clear work filters", self.clear_work_filters, "Reset work filters back to the All works view."),
            "search": ("Search content", self.open_global_search, "Search works, series, pages, and authority documents."),
            "command_palette": ("Command palette", self.open_command_palette, "Open the command palette."),
            "repair_sources": ("Repair missing source images", self.run_repair_missing_sources, "Attempt to restore missing originals from generated derivatives or backup originals."),
            "bulk_relink_sources": ("Bulk relink source images from folder", self.bulk_relink_sources_from_folder, "Scan a folder of originals and relink missing source images by work id or render name."),
            "relink_selected_source": ("Relink selected source image", self.relink_selected_studio_asset, "Choose a file manually for the selected missing-source work in Studio."),
            "audit_sources": ("Audit source assets", lambda: self.tabs.setCurrentWidget(self.studio_tab), "Open Studio and inspect source coverage, preview paths, and recovery candidates."),
            "documents": ("Generate documents", self.run_generate_documents, "Regenerate CV, press kit, and related documents."),
            "export_workbook": ("Export workbook", self.export_workbook, "Create an editable Excel workbook snapshot of the current site content."),
            "analyze_workbook": ("Analyze selected workbook", self.analyze_selected_workbook, "Preview workbook changes before applying them."),
            "import_workbook": ("Import selected workbook", self.import_selected_workbook, "Apply workbook changes only after dry-run preview, risk flags, and transaction confirmation."),
            "validate_page": ("Validate current page", self.validate_current_page_builder, "Run page-level validation and show the change review."),
            "apply_yaml_page": ("Apply page YAML to builder", self.apply_page_yaml_to_builder, "Parse the raw YAML and sync the structured Content Builder editor."),
            "format_page_yaml": ("Format page YAML", self.format_current_page_yaml, "Normalize the current page YAML formatting."),
            "apply_yaml_authority": ("Apply authority YAML to builder", self.apply_authority_yaml_to_builder, "Parse the raw authority YAML and sync the structured authority editor."),
            "format_authority_yaml": ("Format authority YAML", self.format_current_authority_yaml, "Normalize the current authority YAML formatting."),
            "validate_authority": ("Validate current authority", self.validate_current_authority_builder, "Refresh validation and authority change review for the current authority file."),
            "open_studio_preview": ("Open selected studio page preview", self.open_studio_page_preview, "Open the currently selected Studio page preview in the browser."),
            "save_studio_sequence": ("Save studio sequence", self.save_studio_sequence, "Persist the current Studio sequence order and cover back into the selected series."),
            "studio_use_cover": ("Use selected studio work as cover", self.set_studio_sequence_cover, "Mark the selected Studio work as the cover for the active series."),
            "studio_set_series_hero": ("Use selected studio work as series page hero", self.set_studio_series_page_hero, "Set the selected Studio work as the hero image for the public series page."),
            "export_metadata_csv": ("Export metadata CSV", self.export_metadata_csv, "Export all work metadata to a portable CSV file."),
            "import_metadata_csv": ("Import metadata CSV", self.import_metadata_csv, "Preview and apply a validated CSV metadata roundtrip."),
            "regenerate_derivatives": ("Regenerate selected derivatives", self.regenerate_selected_studio_derivatives, "Regenerate responsive image derivatives for selected Studio rows."),
            "find_orphaned_assets": ("Find orphaned assets", self.show_orphaned_assets, "Scan for asset files that do not map to active works and quarantine them safely."),
            "shortcuts": ("Show keyboard shortcuts", self.show_shortcuts, "Open the keyboard shortcuts cheatsheet."),
            "show_last_save_diff": ("View last save diff", self.show_last_save_diff, "Inspect the most recent saved YAML/payload change."),
            "visual_review": ("Toggle Works visual review", self.toggle_work_gallery_view, "Switch the Works list between table and thumbnail gallery mode."),
            "guided_add_work": ("Guided add work", self.open_guided_add_work, "Open the guided image, metadata, series, and validation add-work flow."),
            "readiness_report": ("Portfolio readiness report", self.open_readiness_report, "Show the readiness score and the next practical blockers."),
            "source_recovery": ("Source recovery", self.open_source_recovery_dialog, "Focused workflow for missing original/source images."),
            "task_monitor": ("Task monitor", self.open_task_monitor, "Show active, queued, and recent control-panel tasks."),
            "clear_queued_tasks": ("Clear queued tasks", self.cancel_queued_tasks, "Remove waiting tasks without interrupting the active worker."),
            "inquiry_tracker": ("Private inquiry tracker", self.open_inquiry_tracker, "Track collector, curator, print, or licensing inquiries privately."),
            "print_editions": ("Private print/edition manager", self.open_print_edition_manager, "Manage private print edition metadata without changing the public site."),
            "accessibility_audit": ("Control-panel accessibility audit", self.open_accessibility_audit, "Check focus, keyboard, tooltips, and panel accessibility indicators."),
            "panel_diagnostics": ("Control-panel diagnostics", self.open_panel_diagnostics, "Review maintainability, performance budgets, and UI-state diagnostics."),
            "export_diagnostic_bundle": ("Export diagnostic bundle", self.export_panel_diagnostic_bundle, "Create a compact support zip with logs, diagnostics, state, transactions, and reports."),
            "stale_asset_report": ("Stale asset cleanup report", self.show_stale_asset_cleanup_report, "Review derivative folders that may be leftovers from rename, replace, or remove operations."),
            "gui_smoke_test": ("Run GUI smoke test", lambda: self.run_gui_smoke_test(interactive=True), "Run a fast GUI wiring check for developer validation."),
            "export_build_log": ("Export build log", self.export_build_log, "Save the current build log to a text file."),
            "toggle_context": ("Toggle context inspector", self.toggle_context_inspector, "Show or hide the optional right-side context inspector."),
            "performance_diagnostics": ("Performance diagnostics", self.refresh_performance_diagnostics, "Refresh the local performance diagnostic text panel when available."),
            "undo_quick_state": ("Undo last quick work-state change", self.undo_last_quick_work_state, "Revert the last quick publish/review toggle made in the Works list."),
            "toggle_reduced_motion": ("Toggle reduced motion", self.toggle_reduced_motion, "Disable or re-enable non-essential control-panel motion."),
            "reset_adaptive_layout": ("Reset adaptive layout", self.reset_adaptive_layout, "Restore clean splitter sizes and the adaptive shell profile."),
            "run_regression_checks": ("Run regression checks", self.run_control_panel_regression_checks, "Run control-panel-only regression contracts without launching the public website."),
        }
        advanced_keys = {
            "repair_sources", "bulk_relink_sources", "relink_selected_source", "audit_sources",
            "accessibility_audit", "panel_diagnostics", "gui_smoke_test", "export_build_log", "performance_diagnostics", "export_workbook", "analyze_workbook",
            "import_workbook", "regenerate_derivatives", "find_orphaned_assets", "show_last_save_diff",
            "task_monitor", "clear_queued_tasks", "toggle_context", "reset_adaptive_layout", "run_regression_checks", "release_snapshot", "public_diff",
            "release_workspace", "open_validation_item", "validate_authority", "format_authority_yaml",
            "apply_yaml_authority", "format_page_yaml", "apply_yaml_page", "validate_page",
            "toggle_reduced_motion", "safe_remove_work", "export_diagnostic_bundle", "stale_asset_report",
        }
        self.command_tiers = {key: ("advanced" if key in advanced_keys else "daily") for key in self.command_map}
        for i in range(min(9, self.tabs.count())):
            label = self.tabs.tabText(i).replace("● ", "")
            self.command_map[f"tab_{i + 1}"] = (f"Go to {label}", lambda index=i: self.tabs.setCurrentIndex(index), f"Switch to tab {i + 1}.")

    def command_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        current = self.tabs.currentWidget() if hasattr(self, "tabs") else None
        current_context = ""
        if current is getattr(self, "works_tab", None):
            current_context = "work"
        elif current is getattr(self, "series_tab", None):
            current_context = "series"
        elif current is getattr(self, "studio_tab", None):
            current_context = "studio"
        elif current is getattr(self, "pages_tab", None):
            current_context = "page"
        elif current is getattr(self, "publish_tab", None):
            current_context = "publish"
        elif current is getattr(self, "validation_tab", None):
            current_context = "validation"
        for key, (label, _fn, detail) in self.command_map.items():
            haystack = f"{key} {label} {detail}".lower()
            score = 1 if current_context and current_context in haystack else 0
            usage = command_usage(label)
            rows.append({"key": key, "label": label, "detail": detail, "shortcut": self.command_shortcuts.get(key, ""), "context_score": str(score), "tier": self.command_tiers.get(key, "daily"), "usage": str(usage)})
        rows.extend(self._dynamic_command_target_rows(current_context))
        rows.sort(key=lambda row: (-int(row.get("context_score") or 0), -int(row.get("usage") or 0), row["label"].lower()))
        return rows

    def _dynamic_command_target_rows(self, current_context: str = "") -> list[dict[str, str]]:
        """Phase 17: let the command palette navigate directly to records.

        This keeps rare navigation/search power out of the visible layout while
        preserving full control over works, series, and pages.
        """
        rows: list[dict[str, str]] = []
        try:
            for work in list(load_work_entries()):
                work_id = str(work.get("id") or "").strip()
                if not work_id:
                    continue
                title = str(work.get("title") or work_id).strip()
                series = str(work.get("series") or "No series").strip()
                status = str(work.get("review_status") or ("published" if work.get("published") else "draft")).strip()
                rows.append({
                    "key": f"work:{work_id}",
                    "label": f"Open work · {title}",
                    "detail": f"{work_id} · {series} · {status}",
                    "shortcut": "",
                    "context_score": "2" if current_context in {"work", "studio"} else "0",
                    "tier": "daily",
                    "usage": str(command_usage(f"work:{work_id}")),
                })
        except Exception as exc:
            self._log_warning(f"Dynamic work command rows failed: {exc}")
        try:
            for series in list(load_series_entries()):
                slug = str(series.get("slug") or "").strip()
                if not slug:
                    continue
                title = str(series.get("title") or slug).strip()
                count = len([item for item in (series.get("work_ids") or []) if str(item).strip()])
                rows.append({
                    "key": f"series:{slug}",
                    "label": f"Open series · {title}",
                    "detail": f"{slug} · {count} work(s)",
                    "shortcut": "",
                    "context_score": "2" if current_context == "series" else "0",
                    "tier": "daily",
                    "usage": str(command_usage(f"series:{slug}")),
                })
        except Exception as exc:
            self._log_warning(f"Dynamic series command rows failed: {exc}")
        try:
            for page_key in list(available_page_keys()):
                key = str(page_key or "").strip()
                if not key:
                    continue
                rows.append({
                    "key": f"page:{key}",
                    "label": f"Open page · {key}",
                    "detail": "Content Builder page",
                    "shortcut": "",
                    "context_score": "2" if current_context == "page" else "0",
                    "tier": "daily",
                    "usage": str(command_usage(f"page:{key}")),
                })
        except Exception as exc:
            self._log_warning(f"Dynamic page command rows failed: {exc}")
        return rows

    def _run_dynamic_command_target(self, key: str) -> bool:
        if key.startswith("work:"):
            work_id = key.split(":", 1)[1]
            increment_command_usage(key)
            self._ensure_tab_built_by_key("works")
            if hasattr(self, "tabs") and getattr(self, "works_tab", None) is not None:
                self.tabs.setCurrentWidget(self.works_tab)
            self.select_work(work_id)
            return True
        if key.startswith("series:"):
            slug = key.split(":", 1)[1]
            increment_command_usage(key)
            self._ensure_tab_built_by_key("series")
            if hasattr(self, "tabs") and getattr(self, "series_tab", None) is not None:
                self.tabs.setCurrentWidget(self.series_tab)
            self.select_series(slug)
            return True
        if key.startswith("page:"):
            page_key = key.split(":", 1)[1]
            increment_command_usage(key)
            self._ensure_tab_built_by_key("pages")
            if hasattr(self, "tabs") and getattr(self, "pages_tab", None) is not None:
                self.tabs.setCurrentWidget(self.pages_tab)
            self.select_page(page_key)
            return True
        return False

    def run_command(self, key: str) -> None:
        key = str(key or "")
        if self._run_dynamic_command_target(key):
            self._recent_command_keys = ([key] + [k for k in getattr(self, "_recent_command_keys", []) if k != key])[:5]
            self.state["recent_commands"] = self._recent_command_keys
            self._state_save_timer.start()
            return
        row = self.command_map.get(key)
        if not row:
            return
        label, fn, _detail = row
        increment_command_usage(label)
        self._recent_command_keys = ([str(key)] + [k for k in getattr(self, "_recent_command_keys", []) if k != str(key)])[:5]
        self.state["recent_commands"] = self._recent_command_keys
        self._state_save_timer.start()
        try:
            if key in {"save_current", "replace_image", "duplicate_work", "safe_remove_work", "verify_work_assets", "work_lineage"}: self._ensure_tab_built_by_key("works")
            elif key in {"new_series", "series_curation"}: self._ensure_tab_built_by_key("series")
            elif key in {"validation", "open_validation_item"}: self._ensure_tab_built_by_key("validation")
            elif key in {"prepare_publish", "release_gate", "create_upload_zip", "public_diff", "release_snapshot", "release_workspace"}: self._ensure_tab_built_by_key("publish")
            fn()
        except Exception as exc:
            self._show_command_error(label, exc, "Open Notifications for details.")

    def run_control_panel_regression_checks(self) -> None:
        """Phase 20: run sandbox-safe control-panel regression contracts."""
        commands = [
            [sys.executable, "scripts/control_panel_regression_tests.py"],
            [sys.executable, "scripts/control_panel_backend_regression_tests.py"],
            [sys.executable, "scripts/control_panel_phase_11_15_regression_tests.py"],
            [sys.executable, "scripts/control_panel_batch_d_regression_tests.py"],
        ]
        output: list[str] = []
        ok = True
        for command in commands:
            try:
                result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=45)
            except Exception as exc:
                ok = False
                output.append(f"{' '.join(command)}\n{exc}")
                continue
            if result.returncode != 0:
                ok = False
            output.append("$ " + " ".join(command))
            if result.stdout.strip():
                output.append(result.stdout.strip())
            if result.stderr.strip():
                output.append(result.stderr.strip())
            output.append(f"exit={result.returncode}")
        detail = "\n\n".join(output).strip() or "No regression output."
        self.push_notification("success" if ok else "error", "Regression checks", "Passed" if ok else "Failed", target_scope="diagnostics")
        if ok:
            self._notify_nonblocking("success", "Regression checks passed", "Control-panel contracts are intact.", target_scope="diagnostics", toast="Regression checks passed")
        else:
            dialog = QDialog(self)
            dialog.setWindowTitle("Regression checks failed")
            dialog.resize(900, 640)
            layout = QVBoxLayout(dialog)
            text = QPlainTextEdit()
            text.setReadOnly(True)
            text.setPlainText(detail)
            layout.addWidget(text, 1)
            close = QPushButton("Close")
            close.clicked.connect(dialog.accept)
            layout.addWidget(close)
            dialog.exec()

    def open_command_palette(self) -> None:
        CommandPaletteDialog(self).exec()

    def show_shortcuts(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Help & Shortcuts")
        dialog.resize(720, 560)
        layout = QVBoxLayout(dialog)
        intro = QLabel("Help & Shortcuts · tab purposes and keyboard shortcuts · press Esc to close")
        intro.setObjectName("appSubTitle")
        layout.addWidget(intro)
        purpose_box = QPlainTextEdit()
        purpose_box.setReadOnly(True)
        purpose_box.setMaximumHeight(130)
        purpose_lines = []
        for index in range(self.tabs.count()):
            label = self._clean_tab_label(self.tabs.tabText(index))
            purpose_lines.append(f"{label}: {tab_purpose(label)}")
        purpose_box.setPlainText("\n".join(purpose_lines))
        layout.addWidget(purpose_box)
        tree = QTreeWidget()
        tree.setHeaderLabels(["Shortcut", "Action", "Detail"])
        tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for key, shortcut in sorted(self.command_shortcuts.items(), key=lambda item: item[1]):
            command = self.command_map.get(key)
            if not command:
                continue
            item = QTreeWidgetItem([shortcut, command[0], command[2]])
            tree.addTopLevelItem(item)
        tree.setColumnWidth(0, 140)
        tree.setColumnWidth(1, 240)
        layout.addWidget(tree, 1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()

    def save_current_tab(self) -> None:
        current_key = self._current_tab_key() if hasattr(self, "tabs") else ""
        if current_key:
            self._ensure_tab_built_by_key(current_key)
        current = self.tabs.currentWidget() if hasattr(self, "tabs") else None
        if current_key == "works" or current is getattr(self, "works_tab", None):
            self.save_current_work()
        elif current_key == "series" or current is getattr(self, "series_tab", None):
            self.save_current_series()
        elif current_key == "relationships" or current is getattr(self, "relationships_tab", None):
            self.save_relationships_tab()
        elif current_key == "pages" or current is getattr(self, "pages_tab", None):
            if hasattr(self, "content_inner_tabs") and self.content_inner_tabs.currentIndex() == 1:
                self.save_current_authority()
            else:
                self.save_current_page()
        elif current is getattr(self, "authority_tab", None):
            self.save_current_authority()
        else:
            self.status_message("Nothing editable is selected for Save")

    def notifications(self) -> list[dict[str, Any]]:
        return list(self._notifications)

    def update_notification_badge(self) -> None:
        unread = sum(1 for row in self._notifications if not row.get("read"))
        errors = sum(1 for row in self._notifications if str(row.get("level") or "").lower() == "error")
        prefix = "🔴 " if errors else ""
        label = f"{prefix}🔔 Notifications ({unread})" if unread else f"{prefix}🔔 Notifications"
        if hasattr(self, "notification_button"):
            self.notification_button.setText(label)
            self.notification_button.setProperty("hasErrors", bool(errors))
            self.notification_button.setToolTip(f"{errors} error notification(s). Open the notification center and use Errors only." if errors else "Open notification center.")
            self.notification_button.style().unpolish(self.notification_button)
            self.notification_button.style().polish(self.notification_button)

    def push_notification(self, level: str, title: str, detail: str = "", *, target_scope: str | None = None, target_id: str | None = None) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        notif = {
            "id": f"notif-{int(datetime.now().timestamp() * 1000)}-{len(self._notifications)}",
            "timestamp": stamp,
            "level": str(level or "info"),
            "title": str(title or "Notification"),
            "detail": str(detail or ""),
            "target_scope": target_scope,
            "target_id": target_id,
            "read": False,
        }
        self._notifications = ([notif] + self._notifications)[:MAX_SAVED_NOTIFICATIONS]
        self.state["notifications"] = self._notifications
        self.update_notification_badge()

    def mark_notification_read(self, notif_id: Any) -> None:
        changed = False
        for row in self._notifications:
            if row.get("id") == notif_id and not row.get("read"):
                row["read"] = True
                changed = True
                break
        if changed:
            self.state["notifications"] = self._notifications
            self.update_notification_badge()

    def mark_all_notifications_read(self) -> None:
        for row in self._notifications:
            row["read"] = True
        self.state["notifications"] = self._notifications
        self.update_notification_badge()

    def clear_notifications(self) -> None:
        self._notifications = []
        self.state["notifications"] = self._notifications
        self.update_notification_badge()

    def open_notification_target(self, row: dict[str, Any]) -> None:
        scope = row.get("target_scope")
        target = str(row.get("target_id") or "")
        if scope == "work" and target:
            self.tabs.setCurrentWidget(self.works_tab)
            self.select_work(target)
        elif scope == "series" and target:
            self.tabs.setCurrentWidget(self.series_tab)
            self.select_series(target)
        elif scope == "page" and target:
            self.tabs.setCurrentWidget(self.pages_tab)
            self.select_page(target)
        elif scope == "authority" and target:
            self.open_authority_panel(target)
        elif scope == "validation":
            self.open_validation_panel()
        elif scope == "publish":
            self.tabs.setCurrentWidget(self.publish_tab)
        elif scope == "studio":
            self.tabs.setCurrentWidget(self.studio_tab)

    def open_notification_center(self) -> None:
        dialog = NotificationCenterDialog(self)
        dialog.exec()
        self.update_notification_badge()

    def status_message(self, text: str) -> None:
        self.statusBar().showMessage(text, 5000)
        try:
            self.refresh_context_inspector()
        except Exception as exc:
            self._log_warning(f"Context inspector refresh failed: {exc}")

    def _log_warning(self, message: str) -> None:
        detail = str(message)
        try:
            self.push_notification("warning", "Control panel warning", detail)
        except Exception as exc:
            print(f"Control panel warning logging failed: {exc}: {detail}", file=sys.stderr)
        try:
            if hasattr(self, "build_log"):
                self.append_build_log_line(f"⚠ {detail}")
        except Exception as exc:
            print(f"Control panel build-log warning failed: {exc}: {detail}", file=sys.stderr)

    def _relative_time(self, when: datetime | None) -> str:
        if when is None:
            return "never"
        seconds = max(0, int((datetime.now() - when).total_seconds()))
        if seconds < 60:
            return "just now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} min ago"
        return when.strftime("%H:%M")

    def _update_session_health(self) -> None:
        if hasattr(self, "session_health_label"):
            preflight = getattr(self, "_startup_preflight_report", None) or {}
            preflight_text = "Health: not checked"
            if preflight:
                errors = int(preflight.get("errors") or 0)
                warnings = int(preflight.get("warnings") or 0)
                preflight_text = "Health: clean" if not errors and not warnings else f"Health: {errors}E/{warnings}W"
            self.session_health_label.setText(f"Last build: {self._relative_time(self._last_build_time)} · {self._last_build_status} · {preflight_text}")

    def _mark_saved(self) -> None:
        self._last_save_time = datetime.now()
        if hasattr(self, "work_last_saved_inline"):
            self.work_last_saved_inline.setText(self._last_save_time.strftime("%H:%M:%S"))
        self._update_session_health()

    def _tooltip_for_label(self, label: str) -> str:
        tips = {
            "Refresh": "Reload control-panel data from disk. Unsaved editor changes are checked first.",
            "Add image": "Ingest a new source image and create a work record.",
            "Build site": "Regenerate the static website into public_upload.",
            "Prepare publish": "Run the publish preparation workflow and create release artifacts.",
            "Open preview": "Open the local generated preview in your browser.",
            "Search": "Search works, series, pages, and authority documents.",
            "Readiness": "Show the portfolio readiness score and practical blockers.",
            "Task monitor": "Show active, queued, and recent control-panel tasks.",
            "Command palette": "Run any registered control-panel command from the keyboard.",
            "Shortcuts": "Show keyboard shortcuts.",
        }
        return tips.get(label, label)

    def apply_button_tooltips(self, root: QWidget | None = None) -> None:
        host = root or self
        for button in host.findChildren(QPushButton):
            clean = button.text().replace("…", "").replace("· Ctrl+S", "").strip()
            if not button.toolTip():
                button.setToolTip(self._tooltip_for_label(clean))
            if not button.accessibleName():
                button.setAccessibleName(clean or button.toolTip() or "Control-panel action")
            if not button.accessibleDescription() and button.toolTip():
                button.setAccessibleDescription(button.toolTip())
        for klass in (QLineEdit, QComboBox, QTreeWidget, QListWidget):
            for widget in host.findChildren(klass):
                if not widget.accessibleName():
                    name = widget.objectName() or widget.toolTip() or widget.__class__.__name__
                    widget.setAccessibleName(str(name).replace("_", " "))

    def _reset_autosave_state(self, kind: str) -> None:
        kind = str(kind or "")
        if not kind:
            return
        if hasattr(self, "_autosave_dirty_kinds"):
            self._autosave_dirty_kinds.discard(kind)
        if hasattr(self, "_autosave_due_at"):
            self._autosave_due_at.pop(kind, None)
        if kind == "work":
            self._last_work_autosave_at = None
        elif kind == "series":
            self._last_series_autosave_at = None
        elif kind == "page":
            self._last_page_autosave_at = None
        elif kind == "authority":
            self._last_authority_autosave_at = None

    def schedule_editor_autosave(self, kind: str) -> None:
        kind = str(kind or "")
        autosavers = {"work", "series", "page", "authority"}
        if kind in autosavers:
            self._autosave_dirty_kinds.add(kind)
            self._autosave_due_at[kind] = time.monotonic() + 2.5
        self._update_autosave_labels()

    def _autosave_coordinator(self) -> None:
        if not getattr(self, "_autosave_dirty_kinds", None):
            return
        now = time.monotonic()
        autosavers: dict[str, Callable[[], None]] = {
            "work": self._autosave_work_draft,
            "series": self._autosave_series_draft,
            "page": self._autosave_page_draft,
            "authority": self._autosave_authority_draft,
        }
        ready = [kind for kind in list(self._autosave_dirty_kinds) if now >= float(self._autosave_due_at.get(kind, 0.0))]
        for kind in ready:
            fn = autosavers.get(kind)
            self._autosave_dirty_kinds.discard(kind)
            self._autosave_due_at.pop(kind, None)
            if fn is None:
                continue
            try:
                fn()
            except Exception as exc:
                self._log_warning(f"Autosave for {kind} failed: {exc}")
        if ready:
            self._update_autosave_labels()

    def _update_autosave_label(self, attr: str, label: QLabel | None, dirty: bool) -> None:
        if label is None:
            return
        timestamp = getattr(self, attr, None)
        if timestamp:
            ago = max(0, int(time.time() - float(timestamp)))
            label.setText(f"Draft saved {ago}s ago")
            label.setProperty("state", "ok")
        elif dirty:
            label.setText("Unsaved changes")
            label.setProperty("state", "warning")
        else:
            label.setText("Clean")
            label.setProperty("state", "idle")
        label.style().unpolish(label)
        label.style().polish(label)

    def _update_autosave_labels(self) -> None:
        work_dirty = self.is_work_dirty() if hasattr(self, "work_id_edit") else False
        self._update_autosave_label("_last_work_autosave_at", getattr(self, "work_autosave_status", None), work_dirty)
        if hasattr(self, "work_last_saved_inline"):
            self.work_last_saved_inline.setText("unsaved" if work_dirty else self._relative_time(getattr(self, "_last_save_time", None)))
        self._update_autosave_label("_last_series_autosave_at", getattr(self, "series_autosave_status", None), self.is_series_dirty() if hasattr(self, "series_slug_edit") else False)
        self._update_autosave_label("_last_page_autosave_at", getattr(self, "page_autosave_status", None), self.is_page_dirty() if hasattr(self, "page_editor") else False)
        self._update_autosave_label("_last_authority_autosave_at", getattr(self, "authority_autosave_status", None), self.is_authority_dirty() if hasattr(self, "authority_editor") else False)

    def _draft_payload_hash(self, payload: dict[str, Any]) -> str:
        return hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _write_editor_draft_if_changed(self, kind: str, key: str, payload: dict[str, Any]) -> bool:
        marker = (kind, key)
        payload = dict(payload or {})
        try:
            payload["source_fingerprint"] = editor_source_fingerprint(kind, key)
        except Exception as exc:
            payload["source_fingerprint"] = {"error": str(exc)}
        digest = self._draft_payload_hash(payload)
        if self._last_draft_hash.get(marker) == digest:
            return False
        self._last_draft_hash[marker] = digest
        draft_payload = dict(payload)

        def task(*, task_context: TaskContext | None = None) -> tuple[str, str]:
            save_editor_draft(kind, key, draft_payload)
            return (kind, key)

        self.start_keyed_background_task(
            f"autosave-draft:{kind}:{key}",
            task,
            on_error=lambda detail, k=kind: self._log_warning(f"Autosave draft write failed for {k}: {detail}"),
            label=f"Autosave {kind} draft",
            cancel_previous=True,
        )
        return True

    def _autosave_work_draft(self) -> None:
        if not self._current_work_id:
            return
        current_payload = self.current_work_payload_from_form()
        loaded_snapshot = getattr(self, "_loaded_work_snapshot", None)
        if loaded_snapshot is not None and self._draft_payload_hash(current_payload) == self._draft_payload_hash(loaded_snapshot):
            self._autosave_dirty_kinds.discard("work")
            self._autosave_due_at.pop("work", None)
            self._update_autosave_labels()
            return
        if not self.is_work_dirty():
            return
        payload = {
            "kind": "work",
            "key": self._current_work_id,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "payload": current_payload,
        }
        if self._write_editor_draft_if_changed("work", self._current_work_id, payload):
            self._last_work_autosave_at = time.time()
            self.progress_hint.setText(f"Draft saved · work {self._current_work_id}")
            self._update_autosave_labels()
            self.update_tab_badges()

    def _autosave_series_draft(self) -> None:
        key = self.series_slug_edit.text().strip() or self._current_series_slug or "series"
        if not self.is_series_dirty() or not key:
            return
        payload = {
            "kind": "series",
            "key": key,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "payload": self.current_series_payload_from_form(),
        }
        if self._write_editor_draft_if_changed("series", key, payload):
            self._last_series_autosave_at = time.time()
            self.progress_hint.setText(f"Draft saved · series {key}")
            self._update_autosave_labels()
            self.update_tab_badges()

    def _autosave_page_draft(self) -> None:
        if not self.is_page_dirty() or not self._current_page_key:
            return
        payload = {
            "kind": "page",
            "key": self._current_page_key,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "text": self.page_editor.toPlainText(),
        }
        if self._write_editor_draft_if_changed("page", self._current_page_key, payload):
            self._last_page_autosave_at = time.time()
            self.progress_hint.setText(f"Draft saved · page {self._current_page_key}")
            self._update_autosave_labels()
            self.update_tab_badges()

    def _autosave_authority_draft(self) -> None:
        if not self.is_authority_dirty() or not self._current_authority_key:
            return
        payload = {
            "kind": "authority",
            "key": self._current_authority_key,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "text": self.authority_editor.toPlainText(),
        }
        if self._write_editor_draft_if_changed("authority", self._current_authority_key, payload):
            self._last_authority_autosave_at = time.time()
            self.progress_hint.setText(f"Draft saved · authority {self._current_authority_key}")
            self._update_autosave_labels()
            self.update_tab_badges()

    def _draft_source_diff_lines(self, kind: str, key: str, draft: dict[str, Any]) -> list[str]:
        payload = draft.get("payload") if isinstance(draft.get("payload"), dict) else None
        text_value = str(draft.get("text") or "")
        if kind == "work":
            current = load_work_payload(key)
            before = yaml.safe_dump(current or {}, sort_keys=True, allow_unicode=True).splitlines()
            after = yaml.safe_dump(payload or {}, sort_keys=True, allow_unicode=True).splitlines()
        elif kind == "series":
            current = load_series_payload(key)
            before = yaml.safe_dump(current or {}, sort_keys=True, allow_unicode=True).splitlines()
            after = yaml.safe_dump(payload or {}, sort_keys=True, allow_unicode=True).splitlines()
        elif kind == "page":
            before = load_page_yaml_text(key).splitlines()
            after = text_value.splitlines()
        elif kind == "authority":
            before = load_authority_yaml_text(key).splitlines()
            after = text_value.splitlines()
        else:
            before = []
            after = []
        return list(unified_diff(before, after, fromfile=f"current-{kind}-{key}", tofile=f"draft-{kind}-{key}", lineterm=""))[:500]

    def _confirm_restore_editor_draft(self, kind: str, key: str, draft: dict[str, Any], conflict: dict[str, Any]) -> bool:
        reason = str(conflict.get("reason") or "source changed") if conflict.get("conflict") else "newer unsaved draft"
        diff_lines = self._draft_source_diff_lines(kind, key, draft)
        box = QMessageBox(self)
        box.setWindowTitle("Restore editor draft")
        if conflict.get("conflict"):
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(f"A draft exists for {kind} '{key}', but the source file changed ({reason}).")
            box.setInformativeText("Review the diff before restoring. Restoring can overwrite newer file changes.")
        else:
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(f"A newer unsaved draft exists for {kind} '{key}'.")
            box.setInformativeText("Review the diff or restore the draft.")
        view_btn = box.addButton("View diff", QMessageBox.ButtonRole.ActionRole)
        restore_btn = box.addButton("Restore draft", QMessageBox.ButtonRole.AcceptRole)
        skip_btn = box.addButton("Skip", QMessageBox.ButtonRole.RejectRole)
        while True:
            box.exec()
            clicked = box.clickedButton()
            if clicked is restore_btn:
                return True
            if clicked is view_btn:
                dialog = QDialog(self)
                dialog.setWindowTitle(f"Draft diff · {kind} · {key}")
                dialog.resize(940, 640)
                layout = QVBoxLayout(dialog)
                text = QPlainTextEdit()
                text.setReadOnly(True)
                text.setPlainText("\n".join(diff_lines or ["No textual diff was detected, but draft metadata differs."]))
                layout.addWidget(text, 1)
                row = QHBoxLayout()
                restore_after_view = QPushButton("Restore draft")
                restore_after_view.clicked.connect(dialog.accept)
                close = QPushButton("Close")
                close.clicked.connect(dialog.reject)
                row.addStretch(1)
                row.addWidget(restore_after_view)
                row.addWidget(close)
                layout.addLayout(row)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    return True
                continue
            return False

    def maybe_restore_editor_draft(self, kind: str, key: str, *, interactive: bool = False) -> None:
        if not key:
            return
        marker = (kind, key)
        if marker in self._draft_restore_seen:
            return
        draft = load_editor_draft(kind, key)
        if not draft:
            return
        self._draft_restore_seen.add(marker)
        payload = draft.get("payload") if isinstance(draft.get("payload"), dict) else None
        text_value = str(draft.get("text") or "")
        changed = False
        if kind == "work" and payload and self._normalized_payload(payload) != self._normalized_payload(self._loaded_work_snapshot):
            changed = True
        elif kind == "series" and payload and self._normalized_payload(payload) != self._normalized_payload(self._loaded_series_snapshot):
            changed = True
        elif kind == "page" and text_value and self._normalized_text(text_value) != self._normalized_text(self._loaded_page_text):
            changed = True
        elif kind == "authority" and text_value and self._normalized_text(text_value) != self._normalized_text(self._loaded_authority_text):
            changed = True
        if not changed:
            self._draft_restore_seen.discard(marker)
            return
        if not interactive:
            self.push_notification(
                "warning",
                "Recoverable draft available",
                f"A saved editor draft exists for {kind} '{key}'. Open Dashboard → Recoverable drafts to restore or discard it.",
                target_scope=kind,
                target_id=key,
            )
            self.status_message(f"Recoverable draft available for {kind}: {key}")
            return
        if getattr(self, "_draft_prompt_active", False):
            self.push_notification(
                "warning",
                "Draft restore deferred",
                f"Another draft prompt is already open. Try again from Dashboard → Recoverable drafts for {kind} '{key}'.",
                target_scope=kind,
                target_id=key,
            )
            return
        conflict = draft_conflict_status(kind, key, draft)
        self._draft_prompt_active = True
        try:
            should_restore = self._confirm_restore_editor_draft(kind, key, draft, conflict)
        finally:
            self._draft_prompt_active = False
        if not should_restore:
            self.push_notification("warning", "Draft restore skipped", f"{kind} '{key}' was left unchanged.", target_scope=kind, target_id=key)
            return
        if kind == "work" and payload:
            self._suspend_work_form = True
            try:
                self.work_id_edit.setText(str(payload.get("id") or key))
                self.work_title_edit.setText(str(payload.get("title") or ""))
                self.work_series_combo.setCurrentText(str(payload.get("series") or ""))
                self.work_year_edit.setText(str(payload.get("year") or ""))
                self.work_location_edit.setText(str(payload.get("location") or ""))
                self.work_alt_edit.setPlainText(str(payload.get("alt") or ""))
                self.work_caption_edit.setPlainText(str(payload.get("caption") or ""))
                self.work_tags_edit.setText(", ".join(str(item).strip() for item in (payload.get("tags") or []) if str(item).strip()))
                self.work_review_combo.setCurrentText(str(payload.get("review_status") or "draft"))
                self.work_published_check.setChecked(bool(payload.get("published")))
                self.work_hero_check.setChecked(bool(payload.get("hero_safe", True)))
                self.work_grid_check.setChecked(bool(payload.get("grid_safe", True)))
                self.work_social_check.setChecked(bool(payload.get("social_safe", False)))
                focal = payload.get("focal_point") if isinstance(payload.get("focal_point"), dict) else {}
                self.work_focal_x.setValue(int(focal.get("x", 50)))
                self.work_focal_y.setValue(int(focal.get("y", 50)))
            finally:
                self._suspend_work_form = False
            self.update_work_preview()
            self.update_work_text_stats()
        elif kind == "series" and payload:
            self._suspend_series_form = True
            try:
                self.series_slug_edit.setText(str(payload.get("slug") or key))
                self.series_title_edit.setText(str(payload.get("title") or ""))
                self.series_years_edit.setText(str(payload.get("years") or ""))
                self.series_mood_edit.setText(str(payload.get("mood") or ""))
                self.series_order_spin.setValue(int(payload.get("order") or 0))
                self.series_visibility_combo.setCurrentText(str(payload.get("visibility") or "public"))
                self.series_cover_combo.setCurrentText(str(payload.get("cover_work_id") or ""))
                self.series_review_check.setChecked(bool(payload.get("review_mode")))
                self.series_favorites_check.setChecked(bool(payload.get("allow_favorites", True)))
                self.series_inquiry_check.setChecked(bool(payload.get("allow_inquiry_basket", True)))
                self.series_desc_edit.setPlainText(str(payload.get("description") or ""))
                self.series_sequence_list.clear()
                for work_id in payload.get("work_ids") or []:
                    self.series_sequence_list.addItem(str(work_id))
            finally:
                self._suspend_series_form = False
            self.refresh_series_cover_choices(self.series_slug_edit.text().strip() or self._current_series_slug)
            self.update_series_preview()
        elif kind == "page" and text_value:
            self._suspend_page_raw_sync = True
            try:
                self.page_editor.setPlainText(text_value)
            finally:
                self._suspend_page_raw_sync = False
            self._page_raw_override = True
            try:
                review = review_page_yaml_text(key, text_value)
                self.render_page_review(review)
                self._page_builder_model = dict(review.get("model") or {})
                self.render_page_builder_from_model(select_first_section=True)
            except Exception as exc:
                self._log_warning(f"Draft restore parse failed: {exc}")
            self.update_page_builder_state_label()
        elif kind == "authority" and text_value:
            self.authority_editor.setPlainText(text_value)
        self._last_draft_hash[marker] = self._draft_payload_hash(draft)
        self.update_tab_badges()
        self.status_message(f"Restored draft for {kind}: {key}")

    def global_search_rows(self, query: str = "") -> list[dict[str, str]]:
        q = (query or "").strip().lower()
        rows: list[dict[str, str]] = []
        # Search now covers both content and control-panel commands so users do not
        # have to remember where rare tools live.
        try:
            for command in self.command_rows():
                haystack = f"{command.get('key','')} {command.get('label','')} {command.get('detail','')}".lower()
                if q and q not in haystack:
                    continue
                rows.append({
                    "kind": "Command",
                    "target": str(command.get("label") or command.get("key") or ""),
                    "detail": str(command.get("detail") or "")[:140],
                    "scope": "command",
                    "id": str(command.get("key") or ""),
                })
        except Exception as exc:
            self._log_warning(f"Global command search failed: {exc}")
        try:
            diagnostics = control_panel_diagnostics()
            for row in list(diagnostics.get("rows") or []):
                target = str(row.get("area") or "diagnostic")
                detail = f"{row.get('status') or ''} · {row.get('detail') or ''}"
                haystack = f"{target} {detail}".lower()
                if q and q not in haystack:
                    continue
                rows.append({"kind": "Diagnostic", "target": target, "detail": detail[:140], "scope": "diagnostics", "id": target})
        except Exception:
            pass
        for payload in load_work_entries():
            work_id = str(payload.get("id") or "")
            detail = " · ".join(filter(None, [str(payload.get("title") or ""), str(payload.get("series") or ""), str(payload.get("location") or "")]))
            haystack = f"{work_id} {detail} {payload.get('caption') or ''} {payload.get('alt') or ''}".lower()
            if q and q not in haystack:
                continue
            rows.append({"kind": "Work", "target": work_id, "detail": detail[:140], "scope": "work", "id": work_id})
        for payload in load_series_entries():
            slug = str(payload.get("slug") or "")
            detail = " · ".join(filter(None, [str(payload.get("title") or ""), str(payload.get("years") or ""), str(payload.get("mood") or "")]))
            haystack = f"{slug} {detail} {payload.get('description') or ''}".lower()
            if q and q not in haystack:
                continue
            rows.append({"kind": "Series", "target": slug, "detail": detail[:140], "scope": "series", "id": slug})
        for page_key in available_page_keys():
            text_value = load_page_yaml_text(page_key)
            if q and q not in f"{page_key} {text_value}".lower():
                continue
            rows.append({"kind": "Page", "target": page_key, "detail": "Raw YAML page content", "scope": "page", "id": page_key})
        for key in AUTHORITY_FILES:
            text_value = load_authority_yaml_text(key)
            if q and q not in f"{key} {text_value}".lower():
                continue
            rows.append({"kind": "Authority", "target": key, "detail": "Global YAML authority document", "scope": "authority", "id": key})
        rows.sort(key=lambda row: (row["kind"], row["target"]))
        self._last_global_search_total = len(rows)
        return rows[:200]

    def open_search_result(self, row: dict[str, str]) -> None:
        scope = row.get("scope")
        target = str(row.get("id") or row.get("target") or "")
        if scope == "work":
            self.tabs.setCurrentWidget(self.works_tab)
            self.select_work(target)
        elif scope == "series":
            self.tabs.setCurrentWidget(self.series_tab)
            self.select_series(target)
        elif scope == "page":
            self.tabs.setCurrentWidget(self.pages_tab)
            self.select_page(target)
        elif scope == "authority":
            self.open_authority_panel(target)
        elif scope == "command":
            self.run_command(target if target in self.command_map else str(row.get("id") or ""))
        elif scope == "diagnostics":
            self.open_panel_diagnostics()

    def open_global_search(self) -> None:
        GlobalSearchDialog(self).exec()

    def run_refresh_image_registry(self) -> None:
        self.append_build_log_line("Refreshing image registry…")

        def task() -> dict[str, int]:
            return refresh_image_manifests(line_callback=self._emit_line)

        self.start_task("Refresh image registry", task, on_done=self._refresh_image_registry_done)

    def _refresh_image_registry_done(self, result: Any) -> None:
        rows = result if isinstance(result, dict) else {}
        image_rows = int(rows.get("image_rows") or 0)
        derivative_rows = int(rows.get("derivative_rows") or 0)
        self.append_build_log_line(f"✓ Image registry refreshed ({image_rows} image row(s), {derivative_rows} derivative row(s))")
        self.push_notification(
            "success",
            "Image registry refreshed",
            f"{image_rows} image row(s) and {derivative_rows} derivative row(s) were scanned from disk.",
            target_scope="studio",
        )
        self.status_message("Image registry refreshed")
        self.clear_work_icon_cache()
        self.refresh_all_context(force=True)

    def run_repair_missing_sources(self) -> None:
        self.append_build_log_line("Checking source assets…")

        def task() -> list[dict[str, str]]:
            return recover_missing_source_images(line_callback=self._emit_line)

        self.start_task("Repair sources", task, on_done=self._repair_sources_done)

    def _repair_sources_done(self, result: Any) -> None:
        restored = len(result or [])
        remaining = len(source_asset_issues())
        if restored:
            self.append_build_log_line(f"✓ Restored {restored} missing source image(s)")
        if remaining:
            self.append_build_log_line(f"⚠ {remaining} missing source image(s) still require manual repair")
        else:
            self.append_build_log_line("✓ Source asset coverage is complete")
        self.push_notification("success" if remaining == 0 else "warning", "Source asset repair finished", f"Recovered {restored} item(s); {remaining} missing source image(s) remain.", target_scope="studio")
        if restored:
            self.clear_work_icon_cache()
        self.refresh_all_context(force=True)

    def _relink_source_done(self, result: Any) -> None:
        row = result if isinstance(result, dict) else {}
        work_id = str(row.get('work_id') or '')
        source = str(row.get('source') or '')
        label = f"✓ Relinked source image{f' for {work_id}' if work_id else ''}"
        if source:
            label += f": {source}"
        self.append_build_log_line(label)
        notif_title = f"Relinked source image for {work_id}" if work_id else "Relinked source image"
        self.push_notification("success", notif_title, source or "Manual relink completed.", target_scope="studio")
        self.clear_work_icon_cache(work_id or None)
        self.refresh_all_context(force=True)

    def _bulk_relink_done(self, result: Any) -> None:
        rows = list(result or []) if isinstance(result, list) else []
        if rows:
            self.append_build_log_line(f"✓ Bulk relink matched {len(rows)} missing source image(s)")
        else:
            self.append_build_log_line("⚠ Bulk relink did not match any missing source images")
        self.push_notification("success" if rows else "warning", "Bulk relink finished", f"Matched {len(rows)} missing source image(s).", target_scope="studio")
        if rows:
            self.clear_work_icon_cache()
        self.refresh_all_context(force=True)

    def _consume_backend_warnings(self) -> None:
        try:
            warnings = pop_backend_warnings()
        except Exception as exc:
            self._log_warning(f"Could not load backend warnings: {exc}")
            return
        for row in warnings:
            context = str(row.get("context") or "Backend warning")
            path = str(row.get("path") or "")
            error = str(row.get("error") or "")
            detail = " · ".join(part for part in [path, error] if part)
            self.push_notification("warning", context, detail or "A backend fallback was used.")
            if hasattr(self, "build_log"):
                self.append_build_log_line(f"⚠ {context}: {detail}" if detail else f"⚠ {context}")

    def validate_external_paths(self, *, notify: bool = False) -> bool:
        ok = True
        workbook = self._current_workbook_path() if hasattr(self, "workbook_path_edit") else self._workbook_path
        if workbook and not Path(workbook).exists():
            ok = False
            if notify:
                self.push_notification("warning", "Workbook path missing", f"Saved workbook path no longer exists: {workbook}", target_scope="publish")
                self.status_message("Workbook path is missing")
        if self._current_work_id:
            try:
                payload = load_work_payload(self._current_work_id)
                preview = best_preview_path_for_work(payload) if payload else None
                if payload and not preview:
                    ok = False
                    if notify:
                        self.push_notification("warning", "Work preview image missing", self._current_work_id, target_scope="work", target_id=self._current_work_id)
            except Exception as exc:
                ok = False
                if notify:
                    self._log_warning(f"Could not validate current work paths: {exc}")
        return ok


    # ---------- Phase 8-10 interaction, performance, templates ----------
    def _record_perf(self, label: str, elapsed: float, detail: str = "") -> None:
        try:
            budget_state = performance_budget_status(label, float(elapsed))
            budget_suffix = "" if budget_state == "unbudgeted" else f" · budget {budget_state}"
            clean_detail = (str(detail or "") + budget_suffix).strip()
            self._perf_events.insert(0, (label, float(elapsed), clean_detail))
            self._perf_events = self._perf_events[:30]
            try:
                record_budget_event(str(label or ""), float(elapsed) * 1000.0, source="ui", detail=clean_detail)
            except Exception as exc:
                self._log_warning(f"Could not persist performance timing: {exc}")
            self.refresh_performance_diagnostics()
        except Exception as exc:
            self._log_warning(f"Performance recording failed: {exc}")

    def refresh_performance_diagnostics(self) -> None:
        if not hasattr(self, "performance_diagnostics"):
            return
        rows = ["Performance diagnostics · most recent first"]
        for label, elapsed, detail in list(getattr(self, "_perf_events", []))[:8]:
            rows.append(f"{label}: {elapsed * 1000:.0f} ms" + (f" · {detail}" if detail else ""))
        if len(rows) == 1:
            rows.append("No timings captured yet. Refresh Dashboard, Studio, or run a build to populate this panel.")
        self.performance_diagnostics.setPlainText("\n".join(rows))


    def _show_work_gallery_skeletons(self, count: int = 8) -> None:
        """Phase 18: immediate skeleton cards so Works never opens to a blank surface."""
        if not hasattr(self, "work_gallery_grid") or not getattr(self, "_gallery_mode", True):
            return
        self._clear_layout(self.work_gallery_grid)
        columns = 3
        try:
            available_width = int(self.work_gallery_scroll.viewport().width())
            columns = max(2, min(4, available_width // 220))
        except Exception:
            columns = 3
        for index in range(max(1, int(count or 8))):
            card = QFrame()
            card.setObjectName("workGallerySkeletonCard")
            card.setMinimumSize(220, 190)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(12, 12, 12, 12)
            image = QLabel("Loading…")
            image.setObjectName("workGallerySkeletonImage")
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setMinimumHeight(130)
            title = QLabel("")
            title.setObjectName("workGallerySkeletonLine")
            title.setMinimumHeight(14)
            meta = QLabel("")
            meta.setObjectName("workGallerySkeletonLine")
            meta.setMinimumHeight(10)
            layout.addWidget(image)
            layout.addWidget(title)
            layout.addWidget(meta)
            if not getattr(self, "_reduced_motion", False):
                effect = QGraphicsOpacityEffect(card)
                card.setGraphicsEffect(effect)
                anim = QPropertyAnimation(effect, b"opacity", card)
                anim.setDuration(900)
                anim.setStartValue(0.45)
                anim.setEndValue(0.95)
                anim.setLoopCount(-1)
                anim.setEasingCurve(QEasingCurve.Type.InOutSine)
                anim.start()
                card._skeleton_animation = anim
            row, col = divmod(index, columns)
            self.work_gallery_grid.addWidget(card, row, col)
        self.work_gallery_grid.setRowStretch((count // max(1, columns)) + 1, 1)

    def toggle_work_gallery_view(self, enabled: bool | None = None) -> None:
        if not hasattr(self, "work_gallery_toggle_btn"):
            return
        if enabled is None:
            self._gallery_mode = bool(self.work_gallery_toggle_btn.isChecked()) if self.sender() is self.work_gallery_toggle_btn else not getattr(self, "_gallery_mode", False)
        else:
            self._gallery_mode = bool(enabled)
        # Phase 17: gallery is the primary view; the table is a secondary list mode.
        self._works_model_view_enabled = not self._gallery_mode
        self.work_gallery_toggle_btn.setChecked(self._gallery_mode)
        if hasattr(self, "work_table"):
            self.work_table.setVisible(not self._gallery_mode)
        if hasattr(self, "work_tree"):
            self.work_tree.setVisible(False)
        if hasattr(self, "work_gallery_scroll"):
            self.work_gallery_scroll.setVisible(self._gallery_mode)
            if self._gallery_mode and getattr(self, "_current_gallery_works", None):
                self._populate_work_gallery(list(getattr(self, "_current_gallery_works", [])))
        if hasattr(self, "work_gallery_grid_btn"):
            self.work_gallery_grid_btn.setText("Gallery ✓" if self._gallery_mode else "Gallery")
        if hasattr(self, "work_gallery_list_btn"):
            self.work_gallery_list_btn.setText("List view" if self._gallery_mode else "List view ✓")
        self.status_message("Works gallery view" if self._gallery_mode else "Works list view")

    def _clear_layout(self, layout: QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                try:
                    animation = getattr(widget, "_skeleton_animation", None)
                    if animation is not None:
                        animation.stop()
                except Exception:
                    pass
                widget.deleteLater()

    def _work_gallery_column_count(self) -> int:
        available_width = 720
        try:
            if hasattr(self, "work_gallery_scroll"):
                available_width = int(self.work_gallery_scroll.viewport().width())
        except Exception as exc:
            self._log_warning(f"Gallery viewport measurement failed: {exc}")
        # Use a conservative column width so cards do not oscillate between
        # layouts when a scrollbar appears/disappears by a few pixels.
        return max(1, min(5, available_width // 248))

    def _work_gallery_signature(self, works: list[dict[str, Any]], columns: int) -> tuple[Any, ...]:
        rows: list[tuple[Any, ...]] = []
        for payload in works or []:
            work_id = str(payload.get("id") or "")
            image_path = fast_preview_path_for_work(payload)
            image_sig = thumbnail_signature(work_id, image_path, payload)
            issues = payload.get("_issue_list") or payload.get("issues") or []
            rows.append((
                work_id,
                str(payload.get("title") or ""),
                str(payload.get("series") or ""),
                str(payload.get("review_status") or ""),
                bool(payload.get("published")),
                len(issues),
                image_sig,
            ))
        return (int(columns), tuple(rows))

    def _schedule_work_gallery_reflow(self) -> None:
        if getattr(self, "_closing", False) or not getattr(self, "_gallery_mode", True):
            return
        timer = getattr(self, "_gallery_reflow_timer", None)
        if timer is not None:
            timer.start()
        else:
            QTimer.singleShot(140, self._reflow_work_gallery_after_resize)

    def _reflow_work_gallery_after_resize(self) -> None:
        if getattr(self, "_closing", False) or not getattr(self, "_gallery_mode", True):
            return
        works = list(getattr(self, "_current_gallery_works", []) or [])
        columns = self._work_gallery_column_count()
        if columns == int(getattr(self, "_gallery_last_columns", 0) or 0) and getattr(self, "_gallery_cards_by_work_id", {}):
            return
        self._populate_work_gallery(works, force=True)

    def _gallery_thumbnail_cache_key(self, work_id: str, image_path: Path | str | None, payload: dict[str, Any], size: QSize) -> str:
        return f"gallery::{thumbnail_signature(work_id, image_path, payload)}::{size.width()}x{size.height()}"

    def _gallery_cache_get(self, cache_key: str) -> QPixmap | None:
        cache = getattr(self, "_work_preview_pixmap_cache", None)
        if isinstance(cache, OrderedDict) and cache_key in cache:
            pix = cache.pop(cache_key)
            cache[cache_key] = pix
            return pix
        return None

    def _gallery_cache_put(self, cache_key: str, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        cache = getattr(self, "_work_preview_pixmap_cache", None)
        if isinstance(cache, OrderedDict):
            cache[cache_key] = pixmap
            limit = int(getattr(self, "_work_preview_pixmap_cache_limit", 200) or 200)
            while len(cache) > limit:
                cache.popitem(last=False)

    def _thumbnail_disk_cache_path(self, cache_key: str, source_path: str | Path | None = None) -> Path:
        digest_source = f"{cache_key}|{Path(source_path).stat().st_mtime_ns if source_path and Path(source_path).exists() else 0}"
        digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:32]
        return ROOT / ".stillmrk-build" / "meta" / "thumbnails" / f"{digest}.jpg"

    def _gallery_disk_cache_get(self, cache_key: str, source_path: str | Path | None, size: QSize) -> QPixmap | None:
        path = self._thumbnail_disk_cache_path(cache_key, source_path)
        if not path.exists():
            return None
        image = QImage(str(path))
        if image.isNull():
            return None
        pixmap = QPixmap.fromImage(image.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
        return pixmap if not pixmap.isNull() else None

    def _reprioritise_gallery_thumbnail_queue(self) -> None:
        """Keep visible/top queued thumbnails first without launching new disk work."""
        queue = getattr(self, "_gallery_thumbnail_queue", deque())
        if not queue:
            return
        try:
            visible_order = list(getattr(self, "_gallery_cards_by_work_id", {}).keys())
            priority = {work_id: index for index, work_id in enumerate(visible_order)}
            self._gallery_thumbnail_queue = deque(sorted(queue, key=lambda item: priority.get(item[0], 9999)))
        except Exception as exc:
            self._log_warning(f"Thumbnail queue prioritisation skipped: {exc}")

    def _populate_work_gallery(self, works: list[dict[str, Any]], *, force: bool = False) -> None:
        if not hasattr(self, "work_gallery_grid"):
            return
        works = list(works or [])
        columns = self._work_gallery_column_count()
        signature = self._work_gallery_signature(works, columns)
        if (not force) and signature == getattr(self, "_gallery_last_layout_signature", None) and getattr(self, "_gallery_cards_by_work_id", {}):
            self._sync_work_gallery_selection()
            # Do not let an identical refresh short-circuit the thumbnail
            # pipeline. If the previous async batch was cancelled, starved, or
            # lost a runnable reference, cards would otherwise stay on
            # "Loading preview…" indefinitely.
            self._ensure_gallery_thumbnail_pipeline_running()
            return
        self._gallery_last_layout_signature = signature
        self._gallery_last_columns = columns
        self._gallery_thumbnail_generation = int(getattr(self, "_gallery_thumbnail_generation", 0) or 0) + 1
        generation = self._gallery_thumbnail_generation
        self._gallery_thumbnail_queue = deque()
        self._gallery_thumbnail_loading = set()
        self._gallery_thumbnail_workers = {}
        self._gallery_thumbnail_started_at = {}
        self._gallery_thumbnail_last_progress = time.monotonic()
        self._gallery_cards_by_work_id = {}
        self._current_gallery_works = works
        self._clear_layout(self.work_gallery_grid)
        target_size = QSize(300, 190)
        if not works:
            empty = QLabel("No works match this view. Clear filters or add an image.")
            empty.setObjectName("emptyDetail")
            empty.setWordWrap(True)
            self.work_gallery_grid.addWidget(empty, 0, 0)
            self.work_gallery_grid.setRowStretch(1, 1)
            return
        for index, payload in enumerate(works or []):
            work_id = str(payload.get("id") or "")
            image_path = fast_preview_path_for_work(payload)
            image_path = Path(image_path) if image_path and Path(image_path).exists() else None
            card = WorkGalleryCard(payload, str(image_path) if image_path else None, selected=(work_id == self._current_work_id))
            card.clicked.connect(lambda wid, _card=card: self.select_work(wid))
            if work_id:
                self._gallery_cards_by_work_id[work_id] = card
            row, col = divmod(index, columns)
            self.work_gallery_grid.addWidget(card, row, col)
            if work_id and image_path:
                cache_key = self._gallery_thumbnail_cache_key(work_id, image_path, payload, target_size)
                cached = self._gallery_cache_get(cache_key)
                if cached is None or cached.isNull():
                    cached = self._gallery_disk_cache_get(cache_key, image_path, target_size)
                    if cached is not None and not cached.isNull():
                        self._gallery_cache_put(cache_key, cached)
                if cached is not None and not cached.isNull():
                    card.set_pixmap(cached)
                else:
                    self._gallery_thumbnail_queue.append((work_id, str(image_path), cache_key, target_size, generation))
        self.work_gallery_grid.setRowStretch(((len(works or []) // columns) + 1), 1)
        self._reprioritise_gallery_thumbnail_queue()
        QTimer.singleShot(50, self._load_next_gallery_thumbnail_batch)

    def _ensure_gallery_thumbnail_pipeline_running(self) -> None:
        """Restart the gallery preview queue when cards are still waiting.

        This is deliberately conservative: it does not rebuild cards, it only
        nudges the existing queue/worker pipeline. The user-visible symptom it
        prevents is stable cards that remain stuck on "Loading preview…" after
        resize, filtering, or a stale async batch.
        """
        if getattr(self, "_closing", False):
            return
        queue = getattr(self, "_gallery_thumbnail_queue", deque())
        loading = getattr(self, "_gallery_thumbnail_loading", set())
        cards = getattr(self, "_gallery_cards_by_work_id", {})
        has_loading_cards = False
        for card in list(cards.values()):
            if not _qt_object_alive(card):
                continue
            try:
                if not getattr(card, "_pixmap", QPixmap()).isNull():
                    continue
                text = str(card._image_label.text() or "")
                if "Loading preview" in text:
                    has_loading_cards = True
                    break
            except Exception:
                continue
        if queue or (has_loading_cards and len(loading) < int(getattr(self, "_gallery_thumbnail_max_concurrent", 2) or 2)):
            QTimer.singleShot(0, self._load_next_gallery_thumbnail_batch)

    def _gallery_thumbnail_watchdog_tick(self) -> None:
        if getattr(self, "_closing", False) or not getattr(self, "_gallery_mode", True):
            return
        generation = int(getattr(self, "_gallery_thumbnail_generation", 0) or 0)
        loading = set(getattr(self, "_gallery_thumbnail_loading", set()) or set())
        if not loading and not getattr(self, "_gallery_thumbnail_queue", deque()):
            return
        now = time.monotonic()
        stale: list[str] = []
        started_at = getattr(self, "_gallery_thumbnail_started_at", {})
        for cache_key in loading:
            age = now - float(started_at.get(cache_key, now))
            if age > 12.0:
                stale.append(cache_key)
        if stale:
            for cache_key in stale:
                self._gallery_thumbnail_loading.discard(cache_key)
                self._gallery_thumbnail_workers.pop(cache_key, None)
                self._gallery_thumbnail_started_at.pop(cache_key, None)
            self._log_warning(f"Recovered {len(stale)} stalled gallery preview loader(s).")
        # If no signal has made progress for a while, nudge the queue again.
        if stale or (now - float(getattr(self, "_gallery_thumbnail_last_progress", now)) > 3.0):
            self._ensure_gallery_thumbnail_pipeline_running()

    def _load_next_gallery_thumbnail_batch(self) -> None:
        if getattr(self, "_closing", False):
            return
        generation = int(getattr(self, "_gallery_thumbnail_generation", 0) or 0)
        launched = 0
        max_concurrent = int(getattr(self, "_gallery_thumbnail_max_concurrent", 2) or 2)
        while self._gallery_thumbnail_queue and len(getattr(self, "_gallery_thumbnail_loading", set())) < max_concurrent:
            work_id, path, cache_key, size, queued_generation = self._gallery_thumbnail_queue.popleft()
            if queued_generation != generation:
                continue
            if cache_key in self._gallery_thumbnail_loading:
                continue
            cached = self._gallery_cache_get(cache_key)
            if cached is None or cached.isNull():
                cached = self._gallery_disk_cache_get(cache_key, path, size)
                if cached is not None and not cached.isNull():
                    self._gallery_cache_put(cache_key, cached)
            if cached is not None and not cached.isNull():
                card = getattr(self, "_gallery_cards_by_work_id", {}).get(work_id)
                if _qt_object_alive(card):
                    card.set_pixmap(cached)
                self._gallery_thumbnail_last_progress = time.monotonic()
                continue
            self._gallery_thumbnail_loading.add(cache_key)
            self._gallery_thumbnail_started_at[cache_key] = time.monotonic()
            disk_cache_path = self._thumbnail_disk_cache_path(cache_key, path)
            loader = ThumbnailLoader(work_id, path, cache_key, size, str(disk_cache_path))
            # Retain the runnable wrapper until loaded/error fires. This is the
            # critical fix for queues where most cards stayed in loading state.
            self._gallery_thumbnail_workers[cache_key] = loader
            loader.signals.loaded.connect(lambda wid, key, image, gen=queued_generation: self._apply_gallery_thumbnail(wid, key, image, gen))
            loader.signals.error.connect(lambda wid, detail, key=cache_key, gen=queued_generation: self._gallery_thumbnail_failed(wid, key, detail, gen))
            self.io_thread_pool.start(loader)
            launched += 1
        if self._gallery_thumbnail_queue and launched == 0 and len(getattr(self, "_gallery_thumbnail_loading", set())) < max_concurrent:
            QTimer.singleShot(50, self._load_next_gallery_thumbnail_batch)


    def _gallery_thumbnail_failed(self, work_id: str, cache_key: str, detail: str, generation: int | None = None) -> None:
        self._gallery_thumbnail_loading.discard(cache_key)
        self._gallery_thumbnail_workers.pop(cache_key, None)
        self._gallery_thumbnail_started_at.pop(cache_key, None)
        self._gallery_thumbnail_last_progress = time.monotonic()
        if generation is not None and int(generation) != int(getattr(self, "_gallery_thumbnail_generation", 0) or 0):
            return
        card = getattr(self, "_gallery_cards_by_work_id", {}).get(str(work_id))
        if _qt_object_alive(card):
            try:
                card._image_label.setText("Preview unavailable")
                card._image_label.setToolTip(str(detail or "Thumbnail failed"))
                card._image_label.setPixmap(QPixmap())
            except Exception:
                pass
        self._log_warning(f"Gallery thumbnail skipped for {work_id}: {detail}")
        QTimer.singleShot(0, self._load_next_gallery_thumbnail_batch)

    def _apply_gallery_thumbnail(self, work_id: str, cache_key: str, image: QImage, generation: int) -> None:
        self._gallery_thumbnail_loading.discard(cache_key)
        self._gallery_thumbnail_workers.pop(cache_key, None)
        self._gallery_thumbnail_started_at.pop(cache_key, None)
        self._gallery_thumbnail_last_progress = time.monotonic()
        if generation != int(getattr(self, "_gallery_thumbnail_generation", 0) or 0):
            return
        if image is None or image.isNull():
            # Treat a null image as a handled failure so the queue keeps moving.
            self._gallery_thumbnail_failed(work_id, cache_key, "Thumbnail loader returned an empty image", generation)
            return
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            self._gallery_thumbnail_failed(work_id, cache_key, "Could not convert loaded image to pixmap", generation)
            return
        self._gallery_cache_put(cache_key, pixmap)
        card = getattr(self, "_gallery_cards_by_work_id", {}).get(str(work_id))
        if _qt_object_alive(card):
            card.set_pixmap(pixmap)
        QTimer.singleShot(0, self._load_next_gallery_thumbnail_batch)

    def _template_dir(self, kind: str) -> Path:
        path = ROOT / ".stillmrk-build" / "qt-templates" / kind
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _save_template_payload(self, kind: str, name: str, payload: dict[str, Any]) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.strip()).strip("-") or "template"
        path = self._template_dir(kind) / f"{safe}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def _template_choices(self, kind: str) -> list[Path]:
        return sorted(self._template_dir(kind).glob("*.json"))

    def save_current_work_template(self) -> None:
        payload = dict(self.current_work_payload_from_form())
        for key in ("id", "title", "image"):
            payload.pop(key, None)
        name, ok = QInputDialog.getText(self, "Save work template", "Template name", text=str(payload.get("series") or "work-template"))
        if not ok or not name.strip():
            return
        path = self._save_template_payload("works", name, payload)
        self.push_notification("success", "Work template saved", str(path), target_scope="works")
        self.status_message(f"Saved work template: {path.stem}")

    def apply_work_template_to_current(self) -> None:
        choices = self._template_choices("works")
        if not choices:
            self._info_nonblocking("No work templates", "Save a work template first.", target_scope="works")
            return
        label, ok = QInputDialog.getItem(self, "Use work template", "Template", [p.stem for p in choices], 0, False)
        if not ok or not label:
            return
        path = next((p for p in choices if p.stem == label), None)
        if path is None:
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        current_id = self.work_id_edit.text().strip()
        current_title = self.work_title_edit.text().strip()
        merged = self.current_work_payload_from_form()
        merged.update(payload)
        merged["id"] = current_id
        merged["title"] = current_title
        self.populate_work_form(merged, reset_snapshot=False)
        self.schedule_editor_autosave("work")
        self.status_message(f"Applied work template: {label}")

    def save_current_series_template(self) -> None:
        payload = dict(self.current_series_payload_from_form())
        for key in ("slug", "title", "work_ids", "cover_work_id"):
            payload.pop(key, None)
        name, ok = QInputDialog.getText(self, "Save series template", "Template name", text=str(payload.get("visibility") or "series-template"))
        if not ok or not name.strip():
            return
        path = self._save_template_payload("series", name, payload)
        self.push_notification("success", "Series template saved", str(path), target_scope="series")
        self.status_message(f"Saved series template: {path.stem}")

    def apply_series_template_to_current(self) -> None:
        choices = self._template_choices("series")
        if not choices:
            self._info_nonblocking("No series templates", "Save a series template first.", target_scope="series")
            return
        label, ok = QInputDialog.getItem(self, "Use series template", "Template", [p.stem for p in choices], 0, False)
        if not ok or not label:
            return
        path = next((p for p in choices if p.stem == label), None)
        if path is None:
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        current_slug = self.series_slug_edit.text().strip()
        current_title = self.series_title_edit.text().strip()
        merged = self.current_series_payload_from_form()
        merged.update(payload)
        merged["slug"] = current_slug
        merged["title"] = current_title
        self.populate_series_form(merged, reset_snapshot=False)
        self.schedule_editor_autosave("series")
        self.status_message(f"Applied series template: {label}")

    def _store_payload_diff(self, label: str, before: dict[str, Any], after: dict[str, Any]) -> None:
        before_text = yaml.safe_dump(before or {}, sort_keys=True, allow_unicode=True).splitlines()
        after_text = yaml.safe_dump(after or {}, sort_keys=True, allow_unicode=True).splitlines()
        self._last_save_diff_lines = list(unified_diff(before_text, after_text, fromfile=f"before-{label}", tofile=f"after-{label}", lineterm=""))[:300]

    def _store_text_diff(self, label: str, before: str, after: str) -> None:
        self._last_save_diff_lines = list(unified_diff((before or "").splitlines(), (after or "").splitlines(), fromfile=f"before-{label}", tofile=f"after-{label}", lineterm=""))[:300]

    def show_last_save_diff(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Last save diff")
        dialog.resize(900, 620)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText("\n".join(getattr(self, "_last_save_diff_lines", []) or ["No save diff captured yet."]))
        layout.addWidget(text, 1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec()


    # ---------- premium shell adaptation ----------
    def resizeEvent(self, event) -> None:  # pragma: no cover - UI geometry
        super().resizeEvent(event)
        self._apply_adaptive_shell_layout()

    def _apply_adaptive_shell_layout(self) -> None:
        """Keep the dense panel usable across wide desktop, laptop, and narrow widths."""
        try:
            width = int(self.width())
            if width >= 1640:
                profile = "Wide"
                nav_target = 232
            elif width >= 1280:
                profile = "Desktop"
                nav_target = 216
            elif width >= 1060:
                profile = "Laptop"
                nav_target = 196
            else:
                profile = "Recovery"
                nav_target = 176
            self._layout_profile = profile
            if hasattr(self, "layout_profile_label"):
                state = "ok" if profile in {"Wide", "Desktop"} else "warning" if profile == "Laptop" else "error"
                self.layout_profile_label.set_status(state, profile)
            if hasattr(self, "side_nav"):
                self.side_nav.setProperty("layoutProfile", profile.lower())
                self.side_nav.setProperty("reducedMotion", bool(getattr(self, "_reduced_motion", False)))
                self.side_nav.setMinimumWidth(max(160, nav_target - 16))
                self.side_nav.setMaximumWidth(min(248, nav_target + 18))
            if width < 1280 and hasattr(self, "context_inspector") and self.context_inspector.isVisible():
                self.context_inspector.setVisible(False)
                if hasattr(self, "main_splitter"):
                    self.main_splitter.setSizes([nav_target, max(760, width - nav_target - 24), 0])
            if hasattr(self, "main_splitter") and hasattr(self, "side_nav"):
                inspector = self.context_inspector.width() if hasattr(self, "context_inspector") and self.context_inspector.isVisible() else 0
                self.main_splitter.setSizes([nav_target, max(720, width - nav_target - inspector - 48), inspector])
            self._apply_works_responsive_layout()
        except Exception as exc:
            self._log_warning(f"Adaptive shell layout failed: {exc}")

    def reset_adaptive_layout(self) -> None:
        """Restore a named profile splitter layout without touching website output."""
        self.state.pop("splitters", None)
        if hasattr(self, "context_inspector"):
            self.context_inspector.setVisible(False)
        self._apply_layout_rescue_defaults()
        self._apply_adaptive_shell_layout()
        self.save_window_state()
        self._notify_nonblocking("success", "Layout reset", f"Adaptive control-panel layout restored · {getattr(self, '_layout_profile', 'Recovery')} profile.", target_scope="dashboard", toast="Layout reset")

    def minimum_window_smoke_test(self) -> dict[str, Any]:
        """Regression smoke: make sure core panes survive the minimum supported size."""
        original = self.size()
        try:
            self.resize(1060, 700)
            self._apply_adaptive_shell_layout()
            widgets = [getattr(self, name, None) for name in ("side_nav", "tabs", "main_splitter")]
            ok = all(widget is not None and widget.width() > 0 and widget.height() > 0 for widget in widgets)
            return {"ok": ok, "profile": getattr(self, "_layout_profile", ""), "size": [self.width(), self.height()]}
        finally:
            self.resize(original)
            self._apply_adaptive_shell_layout()

    # ---------- state ----------
    def restore_state(self) -> None:
        geometry = self.state.get("geometry")
        if isinstance(geometry, list) and len(geometry) == 4:
            self.setGeometry(*[int(value) for value in geometry])
        active_tab = self.state.get("last_active_tab_index", self.state.get("active_tab"))
        if isinstance(active_tab, int) and 0 <= active_tab < self.tabs.count():
            self.tabs.setCurrentIndex(active_tab)
        saved_filters = self.state.get("work_filters")
        if isinstance(saved_filters, dict):
            self._pending_work_filter_snapshot = saved_filters
        active_preset = str(self.state.get("active_work_filter_preset") or self._active_work_filter_preset_name or "All works")
        if active_preset in self.all_work_filter_presets():
            self._active_work_filter_preset_name = active_preset
        if self._work_filter_widgets_ready():
            self.refresh_work_filter_preset_options()
            if isinstance(getattr(self, "_pending_work_filter_snapshot", None), dict):
                self.set_work_filter_snapshot(self._pending_work_filter_snapshot or {}, refresh=False)
        self.apply_theme()
        self.apply_density_layout()
        self.update_work_filter_preset_indicator()
        if hasattr(self, "workbook_path_edit") and self._workbook_path:
            if Path(self._workbook_path).exists():
                self.workbook_path_edit.setText(self._workbook_path)
            else:
                missing = self._workbook_path
                self._workbook_path = ""
                self.workbook_path_edit.setText("")
                self.push_notification("warning", "Workbook path missing", f"The saved workbook path no longer exists: {missing}", target_scope="publish")
        self.restore_splitter_state()

    def save_window_state(self) -> None:
        geometry = [int(self.x()), int(self.y()), int(self.width()), int(self.height())]
        self.state.update({
            "state_schema_version": CONTROL_PANEL_STATE_SCHEMA_VERSION,
            "geometry": geometry,
            "active_tab": self.tabs.currentIndex(),
            "last_active_tab_index": self.tabs.currentIndex(),
            "recent_tab_indices": getattr(self, "_recent_tab_indices", [])[:3],
            "recent_commands": getattr(self, "_recent_command_keys", [])[:5],
            "custom_work_filter_presets": self._custom_work_filter_presets,
            "active_work_filter_preset": self._active_work_filter_preset_name,
            "work_filters": self.current_work_filter_snapshot(),
            "workbook_path": self._current_workbook_path(),
            "reduced_motion": bool(getattr(self, "_reduced_motion", False)),
            "layout_profile": str(getattr(self, "_layout_profile", "")),
            "notifications": self._notifications[:MAX_SAVED_NOTIFICATIONS],
            "splitters": self.collect_splitter_state(),
            "layout_polish_version": LAYOUT_POLISH_VERSION,
        })
        self.state["notifications"] = self._notifications[:MAX_SAVED_NOTIFICATIONS]
        save_ui_state(self.state)

    def collect_splitter_state(self) -> dict[str, list[int]]:
        rows: dict[str, list[int]] = {}
        for splitter in QApplication.allWidgets():
            if isinstance(splitter, QSplitter):
                name = splitter.objectName()
                if not name:
                    continue
                sizes = normalise_splitter_sizes(name, [int(value) for value in splitter.sizes()])
                if sizes:
                    rows[name] = sizes
        return rows

    def restore_splitter_state(self) -> None:
        # Old persisted splitter sizes caused collapsed/messy layouts.
        # Only restore sizes created by this layout-polish version; otherwise reset to clean defaults.
        if not isinstance(self.state, dict) or self.state.get("layout_polish_version") != LAYOUT_POLISH_VERSION:
            QTimer.singleShot(0, self._apply_layout_rescue_defaults)
            return
        rows = self.state.get("splitters") if isinstance(self.state, dict) else None
        if not isinstance(rows, dict):
            return
        for splitter in QApplication.allWidgets():
            if isinstance(splitter, QSplitter):
                name = splitter.objectName()
                sizes = rows.get(name) if name else None
                safe_sizes = normalise_splitter_sizes(name, sizes)
                if safe_sizes:
                    try:
                        splitter.setSizes(safe_sizes)
                    except Exception as exc:
                        self._log_warning(f"Could not restore splitter state: {exc}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._running_tasks > 0 or self._task_queue:
            reply = QMessageBox.question(self, "Tasks running", f"{self._running_tasks + len(self._task_queue)} task(s) are still running or queued. Quit anyway?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if not self.ensure_all_editors_safe():
            event.ignore()
            return
        self._closing = True
        for context, _worker in list(getattr(self, "_keyed_background_tasks", {}).values()):
            try:
                context.cancel()
            except Exception:
                pass
        if getattr(self, "_active_task_context", None) is not None:
            try:
                self._active_task_context.cancel()
            except Exception:
                pass
        self._flush_build_log_buffer()
        self.save_window_state()
        flush_command_usage()
        super().closeEvent(event)


from PySide6.QtCore import QEvent


class _LogEvent(QEvent):
    TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, line: str) -> None:
        super().__init__(self.TYPE)
        self.line = line


class _StatusEvent(QEvent):
    TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, text: str) -> None:
        super().__init__(self.TYPE)
        self.text = text


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("STILLMRK Control Panel")
    window = ControlPanelWindow()
    window.show()
    if "--smoke-test" in sys.argv or "--smoke" in sys.argv:
        def _run_and_close() -> None:
            ok = window.run_gui_smoke_test(interactive=False)
            print("GUI smoke test passed" if ok else "GUI smoke test failed")
            window.close()
        QTimer.singleShot(300, _run_and_close)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
