from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from helpers_content import load_series_entries, load_work_payload, save_work_payload  # noqa: E402
from helpers_image import load_pipeline, move_original_between_series, move_generated_between_series  # noqa: E402
from qt_backend import refresh_image_manifests  # noqa: E402


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _render_name(payload: dict[str, Any], work_id: str) -> str:
    image = payload.get("image") if isinstance(payload.get("image"), dict) else {}
    return _clean(image.get("render_name")) or _clean(payload.get("render_name")) or work_id


def repair_series_asset_folders(*, dry_run: bool = False) -> dict[str, Any]:
    """Align work YAML series fields and source/generated asset folders with series membership.

    This fixes historical cases where a series YAML slug was renamed but the listed
    works, original-image folders, or generated-derivative folders still use the old
    slug. The repair is driven by the authoritative series work_ids sequence.
    """
    pipeline = load_pipeline()
    rows: list[dict[str, str]] = []
    changed_yaml = 0
    moved_originals = 0
    moved_generated = 0

    for series in load_series_entries():
        new_slug = _clean(series.get("slug"))
        if not new_slug:
            continue
        for work_id in [_clean(item) for item in (series.get("work_ids") or []) if _clean(item)]:
            payload = load_work_payload(work_id) or {}
            if not payload:
                rows.append({"work_id": work_id, "series": new_slug, "status": "missing-work-yaml"})
                continue
            old_slug = _clean(payload.get("series"))
            render_name = _render_name(payload, work_id)
            if old_slug != new_slug:
                rows.append({"work_id": work_id, "from": old_slug, "to": new_slug, "status": "updated" if not dry_run else "would-update"})
                if not dry_run:
                    updated = dict(payload)
                    updated["series"] = new_slug
                    save_work_payload(work_id, updated)
                    changed_yaml += 1
                    if old_slug:
                        if move_original_between_series(work_id, old_slug, new_slug, pipeline=pipeline):
                            moved_originals += 1
                        if move_generated_between_series(work_id, old_slug, new_slug, pipeline=pipeline, render_name=render_name):
                            moved_generated += 1
            else:
                rows.append({"work_id": work_id, "series": new_slug, "status": "already-aligned"})

    if not dry_run:
        try:
            refresh_image_manifests(line_callback=None)
        except Exception:
            pass

    return {
        "dry_run": dry_run,
        "changed_work_yaml": changed_yaml,
        "moved_originals": moved_originals,
        "moved_generated": moved_generated,
        "rows": rows,
    }


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    result = repair_series_asset_folders(dry_run=dry_run)
    print("Series asset-folder repair")
    print(f"Dry run: {result['dry_run']}")
    print(f"Work YAML updated: {result['changed_work_yaml']}")
    print(f"Original images moved: {result['moved_originals']}")
    print(f"Generated derivative folders moved: {result['moved_generated']}")
    changed_rows = [row for row in result["rows"] if row.get("status") in {"updated", "would-update", "missing-work-yaml"}]
    if changed_rows:
        print("\nRows needing attention:")
        for row in changed_rows[:100]:
            print("- " + ", ".join(f"{k}={v}" for k, v in row.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
