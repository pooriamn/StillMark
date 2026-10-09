from __future__ import annotations

"""Safe bulk-operation planning utilities for the Stillmark control panel."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
META_DIR = ROOT / ".stillmrk-build" / "meta"
BULK_REPORT_PATH = META_DIR / "control-panel-bulk-operations.jsonl"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def operation_id(kind: str, targets: list[str], payload: dict[str, Any] | None = None) -> str:
    seed = json.dumps({"kind": kind, "targets": sorted(str(t) for t in targets), "payload": payload or {}, "at": utc_stamp()}, sort_keys=True, default=str)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def confirmation_phrase(kind: str, count: int) -> str:
    return f"APPLY {str(kind).upper()} {int(count)}"


def plan_bulk_operation(kind: str, targets: list[str], *, changes: list[dict[str, Any]] | None = None, skipped: list[str] | None = None, destructive: bool = False) -> dict[str, Any]:
    clean_targets = [str(item).strip() for item in targets if str(item).strip()]
    clean_changes = [dict(row) for row in (changes or []) if isinstance(row, dict)]
    clean_skipped = [str(item).strip() for item in (skipped or []) if str(item).strip()]
    op_id = operation_id(kind, clean_targets, {"changes": clean_changes, "skipped": clean_skipped, "destructive": destructive})
    phrase = confirmation_phrase(kind, len(clean_changes) or len(clean_targets))
    return {
        "operation_id": op_id,
        "kind": kind,
        "target_count": len(clean_targets),
        "change_count": len(clean_changes),
        "skipped_count": len(clean_skipped),
        "destructive": bool(destructive),
        "confirmation_required": bool(destructive or len(clean_changes) >= 10),
        "confirmation_phrase": phrase,
        "per_item_results": [
            {"target": str(row.get("work_id") or row.get("id") or row.get("target") or ""), "status": "would-change", "fields": list(row.get("fields") or [])}
            for row in clean_changes
        ] + [{"target": item, "status": "skipped", "fields": []} for item in clean_skipped],
        "rollback": {"available": True, "scope": "latest transaction", "hint": "Use Restore last completed transaction immediately if the result is wrong."},
        "created_at": utc_stamp(),
    }


def append_bulk_report(row: dict[str, Any]) -> None:
    try:
        META_DIR.mkdir(parents=True, exist_ok=True)
        with BULK_REPORT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(row or {}, logged_at=utc_stamp()), ensure_ascii=False, sort_keys=True, default=str) + "\n")
    except OSError:
        return
