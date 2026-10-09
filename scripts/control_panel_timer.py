from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer


_LOGGER = logging.getLogger("stillmark.timer")


def _record_timer_warning(message: str, **payload: object) -> None:
    """Best-effort bridge into backend diagnostics without hard coupling."""
    try:
        try:
            from qt_backend import _record_backend_warning  # type: ignore
        except Exception:
            from scripts.qt_backend import _record_backend_warning  # type: ignore
        _record_backend_warning(message, **payload)
    except Exception:
        return


@dataclass
class _TimerSubscriber:
    callback: Callable[[], None]
    interval_ms: int
    last_called_ms: float
    enabled: bool = True


class TimerBus(QObject):
    """One lightweight periodic timer that fans out to named subscribers.

    This keeps low-frequency panel maintenance tasks from creating many
    independent QTimer wake-ups. Debounce/single-shot timers should stay
    independent; steady background tasks belong here.
    """

    def __init__(self, parent: QObject | None = None, *, tick_ms: int = 1000) -> None:
        super().__init__(parent)
        self._subscribers: dict[str, _TimerSubscriber] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(max(250, int(tick_ms or 1000)))
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def register(self, key: str, callback: Callable[[], None], interval_ms: int, *, run_immediately: bool = False) -> None:
        now_ms = time.monotonic() * 1000.0
        last_called = 0.0 if run_immediately else now_ms
        self._subscribers[str(key)] = _TimerSubscriber(
            callback=callback,
            interval_ms=max(250, int(interval_ms or 1000)),
            last_called_ms=last_called,
        )

    def unregister(self, key: str) -> None:
        self._subscribers.pop(str(key), None)

    def set_enabled(self, key: str, enabled: bool) -> None:
        subscriber = self._subscribers.get(str(key))
        if subscriber is not None:
            subscriber.enabled = bool(enabled)

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def _tick(self) -> None:
        now_ms = time.monotonic() * 1000.0
        for key, subscriber in list(self._subscribers.items()):
            if not subscriber.enabled:
                continue
            if now_ms - subscriber.last_called_ms < subscriber.interval_ms:
                continue
            subscriber.last_called_ms = now_ms
            try:
                subscriber.callback()
            except RuntimeError as exc:
                message = str(exc).lower()
                if "deleted" in message or "wrapped" in message:
                    _LOGGER.warning(
                        "TimerBus: subscriber '%s' raised RuntimeError and was unregistered: %s",
                        key,
                        exc,
                    )
                    _record_timer_warning("TimerBus subscriber was unregistered after Qt object deletion", key=key, error=exc)
                    self.unregister(key)
                    continue
                _LOGGER.exception("TimerBus: subscriber '%s' raised RuntimeError", key)
                _record_timer_warning("TimerBus subscriber raised RuntimeError", key=key, error=exc)
                raise
            except Exception as exc:
                # TimerBus should never kill the UI event loop. The owning
                # control panel can log richer errors inside each callback.
                _LOGGER.debug("TimerBus: subscriber '%s' raised %s: %s", key, type(exc).__name__, exc)
                _record_timer_warning("TimerBus subscriber callback failed", key=key, error=exc, error_type=type(exc).__name__)
                continue
