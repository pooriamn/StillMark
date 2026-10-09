from __future__ import annotations

"""Signature-based thumbnail cache helpers for the control panel."""

import json
from pathlib import Path
from typing import Any


def focal_signature(payload: dict[str, Any]) -> str:
    focal = payload.get("focal_point") or payload.get("focal") or {}
    if not isinstance(focal, dict):
        return "50:50"
    return f"{int(focal.get('x', 50) or 50)}:{int(focal.get('y', 50) or 50)}"


def thumbnail_signature(work_id: str, image_path: str | Path | None, payload: dict[str, Any]) -> str:
    base = {"id": str(work_id or payload.get("id") or ""), "focal": focal_signature(payload)}
    if image_path:
        path = Path(image_path)
        try:
            stat = path.stat()
            base.update({"path": str(path), "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)})
        except OSError:
            base.update({"path": str(path), "missing": True})
    else:
        base.update({"missing": True})
    return json.dumps(base, sort_keys=True, separators=(",", ":"))


class ThumbnailBatchToken:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
