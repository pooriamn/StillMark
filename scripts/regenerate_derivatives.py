from __future__ import annotations

import argparse
from pathlib import Path

from helpers_content import load_work_entries, work_to_series_map
from helpers_image import generate_derivatives, load_pipeline, source_path_for_work


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild generated image derivatives.")
    parser.add_argument("--all", action="store_true", help="Regenerate all works")
    parser.add_argument("--series", help="Regenerate one series slug")
    parser.add_argument("--work", help="Regenerate one work id")
    args = parser.parse_args()

    if not any([args.all, args.series, args.work]):
        parser.error("Choose --all, --series, or --work")

    pipeline = load_pipeline()
    series_lookup = work_to_series_map()
    works = load_work_entries()
    selected: list[dict] = []
    for work in works:
        work_id = str(work.get("id") or "").strip()
        series_slug = str(work.get("series") or series_lookup.get(work_id) or "").strip()
        if args.work and work_id != args.work:
            continue
        if args.series and series_slug != args.series:
            continue
        if not work_id or not series_slug:
            continue
        selected.append(work)

    rebuilt = 0
    for work in selected:
        work_id = str(work.get("id") or "").strip()
        render_name = str((work.get("image") or {}).get("render_name") if isinstance(work.get("image"), dict) else "") or str(work.get("render_name") or work_id)
        series_slug = str(work.get("series") or series_lookup.get(work_id) or "").strip()
        source_path = source_path_for_work(series_slug, work_id, pipeline=pipeline)
        if not source_path:
            print(f"Missing original for {work_id}")
            continue
        generate_derivatives(source_path, series_slug, render_name, pipeline=pipeline, force=True)
        rebuilt += 1
        print(f"Rebuilt {work_id}")

    print(f"Done. Rebuilt {rebuilt} work(s).")


if __name__ == "__main__":
    main()
