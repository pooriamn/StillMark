from __future__ import annotations

"""Crash-safe local I/O helpers for the Stillmark Qt control panel."""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_JSONL_LOCKS: dict[str, threading.Lock] = {}
_JSONL_LOCKS_GUARD = threading.Lock()
_JSONL_LOCKS_MAX = 64

JSONL_MAX_BYTES = 5 * 1024 * 1024
JSONL_ROTATE_KEEP = 3


def _rotate_jsonl_if_needed(path: Path, *, max_bytes: int = JSONL_MAX_BYTES) -> None:
    try:
        if max_bytes <= 0 or not path.exists() or path.stat().st_size <= max_bytes:
            return
        for index in range(JSONL_ROTATE_KEEP - 1, 0, -1):
            older = path.with_name(f"{path.name}.{index}")
            newer = path.with_name(f"{path.name}.{index + 1}")
            if older.exists():
                older.replace(newer)
        first = path.with_name(f"{path.name}.1")
        path.replace(first)
    except OSError:
        # Diagnostics should never block the user's editing session.
        return


def rotate_jsonl_log(path: Path | str, *, max_bytes: int = JSONL_MAX_BYTES) -> None:
    """Canonical JSONL rotation helper used by the backend and IO layer."""
    _rotate_jsonl_if_needed(Path(path), max_bytes=max_bytes)


def _jsonl_lock_key(path: Path) -> str:
    return str(path.resolve())


def _prune_jsonl_locks(*, exclude_key: str | None = None) -> None:
    """Remove stale lock entries without weakening active per-file locking.

    Existing log-file locks are intentionally retained even above the soft cap:
    evicting a live file's lock can allow two writers to use different locks for
    the same file. Stale/nonexistent file paths are safe to prune.
    """
    with _JSONL_LOCKS_GUARD:
        for key in list(_JSONL_LOCKS.keys()):
            if key == exclude_key:
                continue
            if len(_JSONL_LOCKS) <= _JSONL_LOCKS_MAX:
                break
            try:
                exists = Path(key).exists()
            except OSError:
                exists = False
            if not exists:
                _JSONL_LOCKS.pop(key, None)


def _lock_for(path: Path) -> tuple[str, threading.Lock]:
    key = _jsonl_lock_key(path)
    with _JSONL_LOCKS_GUARD:
        lock = _JSONL_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _JSONL_LOCKS[key] = lock
    _prune_jsonl_locks(exclude_key=key)
    return key, lock


def atomic_write_text(path: Path | str, text: str, *, encoding: str = "utf-8") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        try:
            dir_fd = os.open(str(target.parent), os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path | str, payload: Any, *, indent: int = 2) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=True) + "\n")


def append_jsonl(path: Path | str, row: dict[str, Any]) -> None:
    """Append one valid JSONL row with per-file locking.

    Multiple background workers can write diagnostics at the same time. The lock
    prevents interleaved JSON fragments while still keeping the helper simple and
    dependency-free.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(row or {}), ensure_ascii=False, sort_keys=True, default=str) + "\n"
    lock_key, lock = _lock_for(target)
    with lock:
        _rotate_jsonl_if_needed(target)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
    if not target.exists():
        with _JSONL_LOCKS_GUARD:
            _JSONL_LOCKS.pop(lock_key, None)
    else:
        _prune_jsonl_locks(exclude_key=lock_key)
