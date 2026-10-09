from __future__ import annotations

"""Reusable Qt components for the Stillmark control panel.

These widgets are intentionally small and dependency-free. They support the
Qt control panel only and do not affect public website output.
"""

from typing import Any, Callable

from PySide6.QtCore import QEasingCurve, QRect, QSize, Qt, QPropertyAnimation, QTimer, Signal, QStringListModel
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QImage
from PySide6.QtWidgets import (
    QCompleter,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


def _safe_font_point_size(font: QFont, fallback: int = 13) -> int:
    """Return a valid positive Qt point size.

    Some platform/default fonts report pointSize() == -1 when they are
    configured in pixels. Calling setPointSize(-1) triggers the Qt warning:
    ``QFont::setPointSize: Point size <= 0 (-1)``. Keep all custom delegates
    defensive so the control panel starts cleanly on Windows, macOS, and Linux.
    """
    try:
        point = int(font.pointSize())
    except Exception:
        point = -1
    if point > 0:
        return point
    try:
        point_f = float(font.pointSizeF())
    except Exception:
        point_f = -1.0
    if point_f > 0:
        return max(1, int(round(point_f)))
    try:
        pixel = int(font.pixelSize())
    except Exception:
        pixel = -1
    if pixel > 0:
        # Approximate px->pt at the usual desktop scale, then clamp.
        return max(1, int(round(pixel * 0.75)))
    return int(fallback) if int(fallback) > 0 else 13


class EmptyState(QFrame):
    """Consistent empty/loading/error state card."""

    def __init__(self, title: str, detail: str = "", action_label: str = "", action: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.setObjectName("emptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        title_label = QLabel(title)
        title_label.setObjectName("emptyTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)
        if detail:
            detail_label = QLabel(detail)
            detail_label.setObjectName("emptyDetail")
            detail_label.setWordWrap(True)
            layout.addWidget(detail_label)
        if action_label and action is not None:
            button = QPushButton(action_label)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(action)
            layout.addWidget(button)
        layout.addStretch(1)


class StatusBadge(QLabel):
    """Small status label with semantic object names for stylesheet targeting."""

    def __init__(self, text: str = "Info", status: str = "info") -> None:
        super().__init__(text)
        self.setObjectName("statusBadge")
        self.set_status(status, text)

    def set_status(self, status: str, text: str | None = None) -> None:
        state = str(status or "info").strip().lower() or "info"
        self.setProperty("state", state)
        self.setText(str(text if text is not None else status))
        self.style().unpolish(self)
        self.style().polish(self)


class FormRow(QWidget):
    """Consistent label/input/hint row used by Works, Series, and Pages editors."""

    def __init__(self, label: str, widget: QWidget, hint: str = "", required: bool = False, annotation: QWidget | None = None) -> None:
        super().__init__()
        self.setObjectName("formRow")
        self.input_widget = widget
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        label_text = str(label or "") + ("  •" if required else "")
        self.label = QLabel(label_text)
        self.label.setObjectName("formRowLabel")
        self.label.setFixedWidth(130)
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if required:
            self.label.setProperty("required", True)
        top.addWidget(self.label)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, widget.sizePolicy().verticalPolicy())
        top.addWidget(widget, 1)
        root.addLayout(top)
        self.annotation_wrap = QWidget()
        annotation_layout = QHBoxLayout(self.annotation_wrap)
        annotation_layout.setContentsMargins(140, 0, 0, 0)
        annotation_layout.setSpacing(6)
        self.hint_label = QLabel(str(hint or ""))
        self.hint_label.setObjectName("formRowHint")
        self.hint_label.setWordWrap(True)
        annotation_layout.addWidget(self.hint_label, 1)
        if annotation is not None:
            annotation_layout.addWidget(annotation)
        self.annotation_wrap.setVisible(bool(hint) or annotation is not None)
        root.addWidget(self.annotation_wrap)

    def set_annotation_widget(self, widget: QWidget | None) -> None:
        layout = self.annotation_wrap.layout()
        if layout is None or widget is None:
            return
        layout.addWidget(widget)
        self.annotation_wrap.setVisible(True)


class ToastLabel(QLabel):
    """Floating confirmation toast that fades out then removes itself."""

    def __init__(self, parent: QWidget, text: str, duration_ms: int = 2200) -> None:
        super().__init__(text, parent)
        self.setObjectName("toastLabel")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.adjustSize()
        self._position()
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(1.0)
        self.setGraphicsEffect(effect)
        self.show()
        self.raise_()
        self._fade = QPropertyAnimation(effect, b"opacity", self)
        self._fade.setDuration(420)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self.deleteLater)
        QTimer.singleShot(max(300, int(duration_ms) - 420), self._fade.start)

    def _position(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        x = max(16, parent.width() - self.width() - 28)
        y = 64
        self.move(x, y)


class SideNavDelegate(QStyledItemDelegate):
    """Premium sidebar renderer: section bands, icons, selected accent rail, and issue pills."""

    GROUP_ICONS = {
        "OVERVIEW": "◈",
        "CONTENT": "▧",
        "QUALITY": "◫",
        "RELEASE": "◆",
        "QUICK ACCESS": "★",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nav_selected_y: float | None = None
        self._target_selected_y: float | None = None
        self._selected_height: int = 34
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_animation)

    def _tick_animation(self) -> None:
        if self._target_selected_y is None:
            self._anim_timer.stop()
            return
        if self._nav_selected_y is None:
            self._nav_selected_y = self._target_selected_y
        delta = self._target_selected_y - self._nav_selected_y
        if abs(delta) < 0.6:
            self._nav_selected_y = self._target_selected_y
            self._anim_timer.stop()
        else:
            self._nav_selected_y += delta * 0.42
        parent = self.parent()
        viewport = getattr(parent, "viewport", lambda: None)()
        if viewport is not None:
            viewport.update()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # type: ignore[override]
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        count = index.data(Qt.ItemDataRole.UserRole + 1)
        is_header = bool(index.data(Qt.ItemDataRole.UserRole + 2))
        severity = str(index.data(Qt.ItemDataRole.UserRole + 3) or "info")
        group_label = str(index.data(Qt.ItemDataRole.UserRole + 4) or opt.text).strip().upper()
        rect = opt.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if is_header:
            painter.fillRect(rect.adjusted(0, 2, 0, -2), QColor("#07111a"))
            painter.setPen(QPen(QColor("#182a3d"), 1))
            painter.drawLine(rect.left() + 8, rect.top(), rect.right() - 8, rect.top())
            icon = self.GROUP_ICONS.get(group_label, "•")
            font = QFont(opt.font)
            font.setPointSize(10)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor("#6f86a0"))
            painter.drawText(QRect(rect.left() + 10, rect.top(), 20, rect.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, icon)
            font.setPointSize(9)
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(QRect(rect.left() + 30, rect.top(), rect.width() - 38, rect.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, group_label)
            painter.restore()
            return
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        if selected:
            self._target_selected_y = float(rect.y())
            self._selected_height = rect.height()
            parent_widget = self.parent()
            reduced_motion = bool(getattr(parent_widget, "property", lambda _name: False)("reducedMotion"))
            if self._nav_selected_y is None or reduced_motion:
                self._nav_selected_y = self._target_selected_y
            if (not reduced_motion) and abs((self._nav_selected_y or 0.0) - self._target_selected_y) > 0.6 and not self._anim_timer.isActive():
                self._anim_timer.start()
            y = int(round(self._nav_selected_y if self._nav_selected_y is not None else rect.y()))
            painter.setBrush(QColor("#0f1e2e"))
            painter.setPen(QPen(QColor("#21384f"), 1))
            painter.drawRoundedRect(QRect(rect.left() + 5, y + 2, rect.width() - 10, self._selected_height - 4), 9, 9)
            painter.fillRect(QRect(rect.left(), y + 7, 2, max(8, self._selected_height - 14)), QColor("#3d8cff"))
        elif opt.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect.adjusted(5, 2, -5, -2), QColor("#0a1420"))
        font = QFont(opt.font)
        font.setPointSize(max(10, _safe_font_point_size(font, 13)))
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor("#f7fbff") if selected else QColor("#c7d4e3"))
        text_rect = QRect(rect.left() + 18, rect.top(), rect.width() - 58, rect.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, str(opt.text).strip())
        try:
            number = int(count or 0)
        except (TypeError, ValueError):
            number = 0
        if number > 0:
            text = str(number if number < 100 else "99+")
            badge_font = QFont(font)
            badge_font.setPointSize(max(8, _safe_font_point_size(font, 13) - 2))
            badge_font.setWeight(QFont.Weight.Bold)
            painter.setFont(badge_font)
            metrics = painter.fontMetrics()
            w = max(22, metrics.horizontalAdvance(text) + 12)
            h = 20
            x = rect.right() - w - 12
            y = rect.center().y() - h // 2
            fill = QColor("#ff6f7d") if severity in {"error", "danger"} or number > 5 else QColor("#ffd166") if severity == "warning" else QColor("#3d8cff")
            painter.setBrush(fill)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRect(x, y, w, h), 10, 10)
            painter.setPen(QColor("#050a0f"))
            painter.drawText(QRect(x, y, w, h), Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # type: ignore[override]
        hint = super().sizeHint(option, index)
        if bool(index.data(Qt.ItemDataRole.UserRole + 2)):
            hint.setHeight(max(hint.height(), 28))
        else:
            hint.setHeight(max(hint.height(), 38))
        return hint


class PanelDialog(QDialog):
    """Reusable list-detail-actions dialog for audits and diagnostics.

    columns is a list of (header, row_key) pairs. load_fn returns a list of row
    dictionaries. detail_fn(row) returns a detail string. actions is a list of
    (label, callback) pairs; callback receives the dialog instance and selected row.
    """

    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        columns: list[tuple[str, str]],
        load_fn: Callable[[], list[dict[str, Any]]],
        detail_fn: Callable[[dict[str, Any]], str] | None = None,
        actions: list[tuple[str, Callable[["PanelDialog", dict[str, Any]], None]]] | None = None,
        size: tuple[int, int] = (760, 520),
        row_color_fn: Callable[[dict[str, Any]], QColor | None] | None = None,
        top_widget: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(*size)
        self.columns = list(columns)
        self.load_fn = load_fn
        self.detail_fn = detail_fn or (lambda row: "\n".join(f"{k}: {v}" for k, v in row.items()))
        self.actions = list(actions or [])
        self.row_color_fn = row_color_fn
        self.rows: list[dict[str, Any]] = []
        root = QVBoxLayout(self)
        if top_widget is not None:
            root.addWidget(top_widget)
        tools = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        tools.addWidget(refresh_btn)
        for label, callback in self.actions:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, cb=callback: cb(self, self.current_row()))
            tools.addWidget(btn)
        tools.addStretch(1)
        root.addLayout(tools)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([header for header, _key in self.columns])
        self.tree.itemSelectionChanged.connect(self.update_detail)
        self.tree.itemDoubleClicked.connect(lambda _item, _col: self._run_default_action())
        split.addWidget(self.tree)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        split.addWidget(self.detail)
        split.setSizes([int(size[0] * 0.64), int(size[0] * 0.36)])
        root.addWidget(split, 1)
        self.refresh()

    def current_row(self) -> dict[str, Any]:
        item = self.tree.currentItem()
        return dict(item.data(0, Qt.ItemDataRole.UserRole) or {}) if item is not None else {}

    def refresh(self) -> None:
        try:
            self.rows = list(self.load_fn() or [])
        except Exception as exc:  # pragma: no cover - UI path
            QMessageBox.critical(self, "Load failed", str(exc))
            return
        self.tree.clear()
        for row in self.rows:
            item = QTreeWidgetItem([str(row.get(key) if row.get(key) is not None else "") for _header, key in self.columns])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            if self.row_color_fn is not None:
                color = self.row_color_fn(row)
                if color is not None:
                    for col in range(len(self.columns)):
                        item.setForeground(col, color)
            self.tree.addTopLevelItem(item)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.update_detail()

    def update_detail(self) -> None:
        row = self.current_row()
        self.detail.setPlainText(self.detail_fn(row) if row else "No rows.")

    def _run_default_action(self) -> None:
        if self.actions:
            self.actions[0][1](self, self.current_row())


class ReadinessGauge(QWidget):
    """Simple anti-aliased donut gauge for portfolio readiness."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(124, 124)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Portfolio readiness gauge")
        self._score = 0

    def set_score(self, score: int) -> None:
        self._score = max(0, min(100, int(score or 0)))
        self.update()

    def paintEvent(self, event) -> None:  # pragma: no cover - visual painting
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        size = min(self.width(), self.height())
        margin = 14
        x = (self.width() - size) // 2 + margin
        y = (self.height() - size) // 2 + margin
        rect = QRect(x, y, size - (margin * 2), size - (margin * 2))
        base_pen = QPen(QColor("#1a2f43"), 12)
        base_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(base_pen)
        painter.drawArc(rect, 0, 360 * 16)
        color = "#70e0a2" if self._score >= 90 else "#ffcf74" if self._score >= 70 else "#ff7a7a"
        score_pen = QPen(QColor(color), 12)
        score_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(score_pen)
        span = int((self._score / 100.0) * 360 * 16)
        painter.drawArc(rect, 90 * 16, -span)
        painter.setPen(QColor("#f1f5fa"))
        font = QFont(self.font())
        font.setPointSize(max(18, _safe_font_point_size(font, 13) + 8))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(self._score))
        painter.end()


class WorkListDelegate(QStyledItemDelegate):
    """Adds a small semantic severity stripe to each work-table row."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # type: ignore[override]
        severity = str(index.data(Qt.ItemDataRole.UserRole + 2) or "").lower()
        if severity and index.column() == 0:
            painter.save()
            color_map = {"error": "#ff7a7a", "warning": "#ffcf74", "ok": "#70e0a2"}
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color_map.get(severity, "#1f3347")))
            stripe = QRect(option.rect.left(), option.rect.top() + 3, 4, max(4, option.rect.height() - 6))
            painter.drawRoundedRect(stripe, 2, 2)
            painter.restore()
        super().paint(painter, option, index)


class WorkGalleryCard(QFrame):
    """Image-first work card with a hover metadata overlay.

    The card no longer performs disk image reads in its constructor. The
    control-panel gallery feeds it scaled pixmaps progressively from the shared
    IO thread pool, so opening the Works gallery never blocks the UI thread.
    """

    clicked = Signal(str)

    def __init__(self, payload: dict, image_path: str | None = None, selected: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.work_id = str(payload.get("id") or "")
        self.image_path = str(image_path or "")
        self.setObjectName("workGalleryCard")
        self.setProperty("selected", bool(selected))
        # Stable card geometry: the gallery grid can resize horizontally, but
        # each card keeps a fixed vertical rhythm so thumbnail arrival and long
        # titles do not make neighbouring cards jump.
        self.setMinimumSize(228, 252)
        self.setMaximumHeight(252)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._image_label = QLabel("Loading preview…" if self.image_path else "No preview", self)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setObjectName("workGalleryImage")
        self._image_label.setMinimumSize(160, 150)
        self._image_label.setFixedHeight(150)
        self._image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        title = str(payload.get("title") or self.work_id or "Untitled")
        series = str(payload.get("series") or "—")
        status = str(payload.get("review_status") or ("published" if payload.get("published") else "draft"))
        issues = payload.get("_issue_list") or payload.get("issues") or []
        issue_text = f" · {len(issues)} issue(s)" if issues else " · clean"
        self._overlay = QLabel(f"<b>{title}</b><br>{series}<br>{status}{issue_text}", self)
        self._overlay.setObjectName("workGalleryOverlay")
        self._overlay.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self._overlay.setWordWrap(True)
        self._overlay.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self._image_label)
        meta_row = QHBoxLayout()
        self._status_dot = QLabel("●")
        self._status_dot.setObjectName("workGalleryStatusDot")
        self._status_dot.setToolTip(status)
        dot_color = "#70e0a2" if status in {"published", "ready"} else "#ffcf74" if status in {"review", "draft"} else "#ff7a7a"
        self._status_dot.setStyleSheet(f"color: {dot_color}; font-size: 16px;")
        text_col = QVBoxLayout()
        self._title_label = QLabel(title)
        self._title_label.setObjectName("workGalleryTitle")
        self._title_label.setWordWrap(False)
        self._title_label.setFixedHeight(20)
        self._title_label.setToolTip(title)
        self._series_label = QLabel(series)
        self._series_label.setObjectName("workGallerySeries")
        self._series_label.setWordWrap(False)
        self._series_label.setFixedHeight(18)
        self._series_label.setToolTip(series)
        text_col.addWidget(self._title_label)
        text_col.addWidget(self._series_label)
        meta_row.addWidget(self._status_dot, 0, Qt.AlignmentFlag.AlignTop)
        meta_row.addLayout(text_col, 1)
        layout.addLayout(meta_row)
        self._pixmap = QPixmap()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = QPixmap(pixmap) if pixmap is not None else QPixmap()
        if self._pixmap.isNull():
            self._image_label.setText("No preview")
            self._image_label.setPixmap(QPixmap())
            return
        self._image_label.setText("")
        self._update_pixmap()

    def set_image(self, image: QImage) -> None:
        self.set_pixmap(QPixmap.fromImage(image) if image is not None and not image.isNull() else QPixmap())

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)

    def resizeEvent(self, event) -> None:  # pragma: no cover - visual resize
        super().resizeEvent(event)
        self._overlay.setGeometry(self.rect())
        self._update_pixmap()

    def _update_pixmap(self) -> None:
        if self._pixmap.isNull():
            return
        target = QSize(max(160, self._image_label.width()), max(130, self._image_label.height()))
        scaled = self._pixmap.scaled(target, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        self._image_label.setPixmap(scaled)

    def enterEvent(self, event) -> None:  # pragma: no cover - visual hover
        self._overlay.show()
        self._overlay.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # pragma: no cover - visual hover
        self._overlay.hide()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # pragma: no cover - UI interaction
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.work_id)
            event.accept()
            return
        super().mousePressEvent(event)


class TagInputWidget(QFrame):
    """Small tag-pill editor with comma/Enter insertion and autocomplete."""

    textChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tagInput")
        self._tags: list[str] = []
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 5, 8, 5)
        self._layout.setSpacing(6)
        self._entry = QLineEdit()
        self._entry.setObjectName("tagInputEntry")
        self._entry.setPlaceholderText("Add tag…")
        self._entry.returnPressed.connect(self._commit_entry)
        self._entry.textEdited.connect(self._on_text_edited)
        self._layout.addWidget(self._entry, 1)
        self._tag_model = QStringListModel(self)
        self._completer = QCompleter(self._tag_model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._entry.setCompleter(self._completer)
        self._completer.activated.connect(self._add_tag)

    def set_vocabulary(self, tags: list[str]) -> None:
        values = sorted({str(tag).strip() for tag in tags if str(tag).strip()}, key=str.lower)
        self._tag_model.setStringList(values)

    def text(self) -> str:
        return ", ".join(self._tags)

    def pending_text(self) -> str:
        return self._entry.text().strip().strip(",")

    def commit_pending_text(self) -> bool:
        before = self.text()
        self._commit_entry()
        return self.text() != before

    def setText(self, value: str) -> None:
        raw = [part.strip() for part in str(value or "").split(",")]
        self._entry.clear()
        self.set_tags([part for part in raw if part])

    def set_tags(self, tags: list[str]) -> None:
        unique: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            clean = str(tag).strip()
            key = clean.casefold()
            if clean and key not in seen:
                seen.add(key)
                unique.append(clean)
        if unique == self._tags:
            return
        self._tags = unique
        self._rebuild()
        self.textChanged.emit(self.text())

    def _on_text_edited(self, text: str) -> None:
        if "," in text:
            pieces = [p.strip() for p in text.split(",")]
            for piece in pieces[:-1]:
                if piece:
                    self._add_tag(piece)
            self._entry.setText(pieces[-1])

    def _commit_entry(self) -> None:
        self._add_tag(self._entry.text())

    def _add_tag(self, tag: str) -> None:
        clean = str(tag or "").strip().strip(",")
        self._entry.clear()
        if not clean:
            return
        if clean.casefold() in {t.casefold() for t in self._tags}:
            return
        self._tags.append(clean)
        self._rebuild()
        self.textChanged.emit(self.text())

    def _remove_tag(self, tag: str) -> None:
        self._tags = [item for item in self._tags if item != tag]
        self._rebuild()
        self.textChanged.emit(self.text())

    def _rebuild(self) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for tag in self._tags:
            pill = QPushButton(f"{tag} ×")
            pill.setObjectName("tagPill")
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.clicked.connect(lambda _checked=False, t=tag: self._remove_tag(t))
            self._layout.insertWidget(self._layout.count() - 1, pill)


class AssetHealthBar(QWidget):
    """Horizontal segmented asset-health bar for Studio."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(22)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Asset health bar")
        self._segments: list[tuple[int, str]] = []
        self._total = 1

    def set_segments(self, ok: int, warn: int, error: int, grey: int) -> None:
        ok = max(0, int(ok or 0)); warn = max(0, int(warn or 0)); error = max(0, int(error or 0)); grey = max(0, int(grey or 0))
        self._total = ok + warn + error + grey or 1
        self._segments = [(ok, "#70e0a2"), (warn, "#ffcf74"), (error, "#ff7a7a"), (grey, "#2a3f55")]
        self.update()

    def paintEvent(self, event) -> None:  # pragma: no cover - visual painting
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(0, 2, 0, -2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0b1722"))
        painter.drawRoundedRect(rect, 8, 8)
        x = rect.x()
        for count, color in self._segments:
            if count <= 0:
                continue
            w = max(1, int((count / self._total) * rect.width()))
            seg = QRect(x, rect.y(), min(w, rect.right() - x + 1), rect.height())
            painter.fillRect(seg, QColor(color))
            x += w
        painter.end()


class WorkflowStepper(QFrame):
    """Compact semantic release/review workflow rail.

    Status values: ok, warning, error, running, locked, info.
    This is intentionally visual-only; it does not change backend release logic.
    """

    def __init__(self, steps: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowStepper")
        self._steps = [str(step) for step in steps]
        self._badges: list[StatusBadge] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        for index, step in enumerate(self._steps, 1):
            badge = StatusBadge(f"{index}. {step}", "info")
            badge.setObjectName("workflowStep")
            badge.setMinimumWidth(96)
            self._badges.append(badge)
            layout.addWidget(badge)
        layout.addStretch(1)

    def set_statuses(self, statuses: list[str] | tuple[str, ...]) -> None:
        values = [str(value or "info").lower() for value in statuses]
        for index, badge in enumerate(self._badges):
            state = values[index] if index < len(values) else "info"
            badge.set_status(state, f"{index + 1}. {self._steps[index]}")
            badge.setProperty("state", state)
            badge.style().unpolish(badge)
            badge.style().polish(badge)

    def set_tooltips(self, tips: list[str] | tuple[str, ...]) -> None:
        for index, tip in enumerate(tips):
            if index < len(self._badges):
                self._badges[index].setToolTip(str(tip or ""))


class PremiumCard(QFrame):
    """Reusable calm card shell for future Qt-panel sections."""

    def __init__(self, title: str = "", detail: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("premiumCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        if title:
            title_label = QLabel(title)
            title_label.setObjectName("premiumCardTitle")
            layout.addWidget(title_label)
        if detail:
            detail_label = QLabel(detail)
            detail_label.setObjectName("emptyDetail")
            detail_label.setWordWrap(True)
            layout.addWidget(detail_label)
