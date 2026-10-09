from __future__ import annotations

"""Small QObject controller layer for the Qt control-panel tabs.

This is the safe Phase 11 migration seam: the monolithic window remains the
compatibility host, while tab-specific state, refresh requests, and navigation
requests now have typed controller objects and Qt signals. Handlers can move
from ControlPanelWindow into these controllers one workflow at a time without
changing the public website or breaking the current UI wiring.
"""

from typing import Any, Callable
import weakref

try:
    from PySide6.QtCore import QObject, Signal
except Exception:  # pragma: no cover - import-time safety for static tests
    class QObject:  # type: ignore[no-redef]
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass
    class Signal:  # type: ignore[no-redef]
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass
        def emit(self, *_args: Any, **_kwargs: Any) -> None:
            pass


class TabControllerBase(QObject):
    """Base controller used by Works, Series, and Pages tab boundaries."""

    refreshRequested = Signal(str, bool)
    selectRequested = Signal(str, str)
    saveRequested = Signal(str)
    changed = Signal(str)

    tab_key = ""
    tab_label = ""

    def __init__(self, window: Any | None = None) -> None:
        super().__init__()
        self._window_ref: Callable[[], Any | None] = weakref.ref(window) if window is not None else (lambda: None)
        self.current_id: str | None = None
        self.current_payload: dict[str, Any] | None = None
        self.owned_widget_names: set[str] = set()

    @property
    def window(self) -> Any | None:
        return self._window_ref()

    def bind_window(self, window: Any) -> None:
        self._window_ref = weakref.ref(window)

    def install_owned_widgets(self, *names: str) -> None:
        self.owned_widget_names.update(str(name) for name in names if str(name))

    def mark_current(self, key: str | None, payload: dict[str, Any] | None = None) -> None:
        self.current_id = str(key) if key else None
        self.current_payload = dict(payload or {}) if isinstance(payload, dict) else None
        self.changed.emit(self.current_id or "")

    def request_refresh(self, *, force: bool = False) -> None:
        self.refreshRequested.emit(self.tab_key, bool(force))

    def request_select(self, key: str) -> None:
        self.selectRequested.emit(self.tab_key, str(key or ""))

    def request_save(self) -> None:
        self.saveRequested.emit(self.tab_key)


class WindowDelegatingTabController(TabControllerBase):
    """Controller that delegates legacy build handlers through a weak window ref."""

    legacy_builder_name = ""

    def build(self) -> Any:
        window = self.window
        if window is None:
            raise RuntimeError(f"{self.__class__.__name__} is not bound to a control-panel window")
        builder = getattr(window, self.legacy_builder_name)
        return builder()
