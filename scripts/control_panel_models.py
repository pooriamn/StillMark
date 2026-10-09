from __future__ import annotations

"""Model/view support for the Works panel.

Phase 3 makes this the primary Works list data source. The legacy QTreeWidget
remains available as a fallback, but normal rendering/selection now runs through
QTableView + WorksTableModel so row updates do not require rebuilding thousands
of widget items.
"""

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


WORKS_COLUMNS = ["ID", "Title", "Series", "Status", "Published", "Score", "Source", "Issues"]


def _issue_text(row: dict[str, Any]) -> str:
    issues = row.get("_issue_list") or []
    if not issues:
        return "0"
    if any(str(issue).lower().startswith(("error", "missing")) for issue in issues):
        return f"✕ {len(issues)}"
    return f"⚠ {len(issues)}"


def _severity(row: dict[str, Any]) -> str:
    issues = [str(issue).lower() for issue in (row.get("_issue_list") or row.get("issues") or [])]
    source_status = str(row.get("_source_status") or "").lower()
    if source_status not in {"", "-", "ok"} and ("missing" in source_status or "broken" in source_status):
        return "error"
    if any(issue.startswith(("error", "missing")) or "missing source" in issue for issue in issues):
        return "error"
    if issues or source_status in {"orphan-risk", "recoverable", "warning", "deferred"}:
        return "warning"
    return "ok"


class WorksTableModel(QAbstractTableModel):
    def __init__(self, rows: list[dict[str, Any]] | None = None, parent: Any = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._row_ids: list[str] = []
        self._icons: dict[str, Any] = {}
        self.set_rows(list(rows or []))

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = [dict(row or {}) for row in (rows or [])]
        self._row_ids = [str(row.get("id") or "") for row in self._rows]
        live_ids = set(self._row_ids)
        self._icons = {key: icon for key, icon in self._icons.items() if key in live_ids}
        self.endResetModel()

    def row_ids(self) -> list[str]:
        return list(self._row_ids)

    def rows(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows]

    def row_for_id(self, work_id: str) -> int:
        key = str(work_id or "")
        try:
            return self._row_ids.index(key)
        except ValueError:
            return -1

    def payload_for_id(self, work_id: str) -> dict[str, Any]:
        row = self.row_for_id(work_id)
        if row < 0:
            return {}
        return dict(self._rows[row])

    def payload_at_row(self, row_index: int) -> dict[str, Any]:
        if not (0 <= row_index < len(self._rows)):
            return {}
        return dict(self._rows[row_index])

    def update_row(self, work_id: str, payload: dict[str, Any]) -> bool:
        row = self.row_for_id(work_id)
        if row < 0:
            return False
        self._rows[row] = dict(payload or {})
        self._row_ids[row] = str((payload or {}).get("id") or work_id)
        top_left = self.index(row, 0)
        bottom_right = self.index(row, max(0, len(WORKS_COLUMNS) - 1))
        self.dataChanged.emit(top_left, bottom_right, [])
        return True

    def replace_or_insert_row(self, old_work_id: str | None, payload: dict[str, Any]) -> None:
        new_id = str((payload or {}).get("id") or old_work_id or "")
        row = self.row_for_id(str(old_work_id or new_id))
        if row < 0 and new_id:
            row = self.row_for_id(new_id)
        if row >= 0:
            self._rows[row] = dict(payload or {})
            self._row_ids[row] = new_id
            top_left = self.index(row, 0)
            bottom_right = self.index(row, max(0, len(WORKS_COLUMNS) - 1))
            self.dataChanged.emit(top_left, bottom_right, [])
            return
        self.beginInsertRows(QModelIndex(), len(self._rows), len(self._rows))
        self._rows.append(dict(payload or {}))
        self._row_ids.append(new_id)
        self.endInsertRows()

    def set_icon(self, work_id: str, icon: Any) -> None:
        key = str(work_id or "")
        if not key:
            return
        self._icons[key] = icon
        row = self.row_for_id(key)
        if row >= 0:
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0), [Qt.ItemDataRole.DecorationRole])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(WORKS_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(WORKS_COLUMNS):
            return WORKS_COLUMNS[section]
        return section + 1

    def _display_values(self, row: dict[str, Any]) -> list[str]:
        return [
            str(row.get("id") or ""),
            str(row.get("title") or ""),
            str(row.get("series") or ""),
            str(row.get("review_status") or ""),
            "Yes" if bool(row.get("published")) else "No",
            str(int(row.get("_completeness_score") or 0)),
            str(row.get("_source_status") or "-"),
            _issue_text(row),
        ]

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        col = index.column()
        work_id = str(row.get("id") or "")
        if role == Qt.ItemDataRole.UserRole:
            return work_id
        if role == Qt.ItemDataRole.UserRole + 2:
            return _severity(row)
        if role == Qt.ItemDataRole.UserRole + 5:
            return dict(row)
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            return self._icons.get(work_id)
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 7 and row.get("_issue_list"):
                return "\n".join(str(item) for item in (row.get("_issue_list") or []))
            return self._display_values(row)[col] if 0 <= col < len(WORKS_COLUMNS) else None
        if role == Qt.ItemDataRole.TextAlignmentRole and col in {4, 5, 7}:
            return Qt.AlignmentFlag.AlignCenter
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        values = self._display_values(row)
        return values[col] if 0 <= col < len(values) else None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:  # noqa: N802
        if not self._rows or not (0 <= column < len(WORKS_COLUMNS)):
            return
        def key(row: dict[str, Any]) -> Any:
            if column == 4:
                return bool(row.get("published"))
            if column == 5:
                return int(row.get("_completeness_score") or 0)
            if column == 7:
                return len(row.get("_issue_list") or [])
            return str(self._display_values(row)[column]).lower()
        reverse = order == Qt.SortOrder.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=key, reverse=reverse)
        self._row_ids = [str(row.get("id") or "") for row in self._rows]
        self.layoutChanged.emit()


def work_filter_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    total = len(rows or [])
    published = sum(1 for row in rows or [] if row.get("published"))
    issues = sum(1 for row in rows or [] if row.get("_issue_list"))
    missing_source = sum(1 for row in rows or [] if str(row.get("_source_status") or "") not in {"", "-", "ok"})
    return {"total": total, "published": published, "issues": issues, "missing_source": missing_source}
