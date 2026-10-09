from __future__ import annotations

import json
from pathlib import Path

from helpers_content import load_work_entries, work_to_series_map
from helpers_image import SOURCE_EXTENSIONS, derivative_dir_for_work, load_pipeline, read_dimensions, source_path_for_work

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    pipeline = load_pipeline()
    series_lookup = work_to_series_map()
    works = load_work_entries()

    work_ids = {str(entry.get("id") or "").strip() for entry in works if str(entry.get("id") or "").strip()}
    missing_originals: list[str] = []
    missing_derivatives: list[str] = []
    orphan_originals: list[str] = []
    orphan_generated: list[str] = []
    incoming_files: list[str] = []

    widths = sorted(set(int(width) for width in (pipeline.get("widths") or [480, 768, 1200, 1600, 2048])))

    for entry in works:
        work_id = str(entry.get("id") or "").strip()
        if not work_id:
            continue
        series_slug = str(entry.get("series") or series_lookup.get(work_id) or "").strip()
        source_path = source_path_for_work(series_slug, work_id, pipeline=pipeline) if series_slug else None
        if not source_path:
            missing_originals.append(work_id)
            continue
        width, _height = read_dimensions(source_path)
        expected_widths = [item for item in widths if item < width] + [width]
        render_name = str((entry.get("image") or {}).get("render_name") if isinstance(entry.get("image"), dict) else "") or str(entry.get("render_name") or work_id)
        derivative_dir = derivative_dir_for_work(series_slug or "unassigned", render_name, pipeline=pipeline)
        base_name = render_name.replace("/", "-")
        for item in sorted(set(expected_widths)):
            for extension in ("jpg", "webp"):
                candidate = derivative_dir / f"{base_name}-{item}.{extension}"
                if not candidate.exists():
                    missing_derivatives.append(candidate.relative_to(ROOT).as_posix())

    originals_root = ROOT / "assets/images/originals"
    if originals_root.exists():
        for path in originals_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS and path.stem not in work_ids:
                orphan_originals.append(path.relative_to(ROOT).as_posix())

    generated_root = ROOT / str(pipeline.get("generated_dir") or "assets/images/generated/series")
    if generated_root.exists():
        for series_dir in generated_root.iterdir():
            if not series_dir.is_dir():
                continue
            for work_dir in series_dir.iterdir():
                if work_dir.is_dir() and work_dir.name not in work_ids:
                    orphan_generated.append(work_dir.relative_to(ROOT).as_posix())

    incoming_root = ROOT / str(pipeline.get("incoming_dir") or "assets/images/incoming")
    if incoming_root.exists():
        incoming_files = [path.relative_to(ROOT).as_posix() for path in incoming_root.iterdir() if path.is_file()]

    report = {
        "missing_originals": missing_originals,
        "missing_derivatives": missing_derivatives,
        "orphan_originals": orphan_originals,
        "orphan_generated": orphan_generated,
        "incoming_files": incoming_files,
    }
    manifest_root = ROOT / str(pipeline.get("manifest_dir") or "assets/images/manifests")
    manifest_root.mkdir(parents=True, exist_ok=True)
    (manifest_root / "audit-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("Audit summary")
    print(f"- Missing originals: {len(missing_originals)}")
    print(f"- Missing derivatives: {len(missing_derivatives)}")
    print(f"- Orphan originals: {len(orphan_originals)}")
    print(f"- Orphan generated folders: {len(orphan_generated)}")
    print(f"- Incoming files waiting: {len(incoming_files)}")
    print(f"- Full report: {(manifest_root / 'audit-report.json').relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
