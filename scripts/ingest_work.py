from __future__ import annotations

import sys
from pathlib import Path

from helpers_content import (
    available_series_slugs,
    create_series_file,
    create_work_payload,
    ensure_unique_work_id,
    insert_work_into_series,
    load_yaml,
    slugify_work_id,
    transaction,
    validate_work_input,
    work_file_for_id,
    write_yaml,
)
from helpers_image import (
    SOURCE_EXTENSIONS,
    generate_derivatives,
    incoming_root,
    load_pipeline,
    safe_move_to_originals,
    write_ingestion_log,
)
try:
    from og_images import ensure_og_images_from_content, load_content_for_og
except ImportError:  # pragma: no cover
    from scripts.og_images import ensure_og_images_from_content, load_content_for_og


def prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    return value or default


def prompt_bool(text: str, default: bool) -> bool:
    label = "Y/n" if default else "y/N"
    value = input(f"{text} ({label}): ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "true", "1"}


def prompt_int(text: str, default: int) -> int:
    raw = prompt(text, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"Expected an integer for '{text}'") from exc
    return max(0, min(100, value))


def choose_series(series_options: list[str]) -> str:
    print("Available series:")
    for index, slug in enumerate(series_options, start=1):
        print(f"  {index}. {slug}")
    print("  N. Create a new series now")
    selection = input(f"Series slug or number [{series_options[0]}]: ").strip()
    if not selection:
        return series_options[0]
    if selection.lower() in {"n", "new"}:
        title = prompt("New series title")
        slug_default = slugify_work_id(title)
        series_slug = prompt("New series slug", slug_default)
        series_slug = slugify_work_id(series_slug)
        years = prompt("Series years", "2026")
        mood = prompt("Series mood", "Monochrome sequence")
        description = prompt("Series description", f"A monochrome sequence titled {title}.")
        visibility = prompt("Visibility (public/private)", "public").strip().lower() or "public"
        create_series_file(series_slug=series_slug, title=title, years=years, mood=mood, description=description, visibility=visibility)
        print(f"Created series '{series_slug}'.")
        return series_slug
    if selection.isdigit():
        numeric = int(selection)
        if 1 <= numeric <= len(series_options):
            return series_options[numeric - 1]
    if selection in series_options:
        return selection
    print("Unknown series selection.")
    return choose_series(series_options)


def main() -> None:
    pipeline = load_pipeline()
    incoming = incoming_root(pipeline)
    incoming.mkdir(parents=True, exist_ok=True)
    candidates = sorted([path for path in incoming.iterdir() if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS])
    if not candidates:
        print("No incoming image files found.")
        return

    series_options = available_series_slugs()
    if not series_options:
        raise RuntimeError("No series slugs found in content/series/")

    for source_path in candidates:
        print(f"\nProcessing: {source_path.name}")
        existing_defaults = {}
        default_id = slugify_work_id(source_path.stem)
        series_slug = choose_series(available_series_slugs())

        work_id = prompt("Work id", default_id)
        work_id = slugify_work_id(work_id)
        work_path = work_file_for_id(work_id)
        allow_existing = work_path.exists() and prompt_bool(f"Work '{work_id}' already exists. Update it", True)
        ensure_unique_work_id(work_id, allow_existing=allow_existing)
        if work_path.exists():
            existing_defaults = load_yaml(work_path) or {}

        title = prompt("Title", str(existing_defaults.get("title") or source_path.stem.replace("-", " ").title()))
        year = prompt("Year", str(existing_defaults.get("year") or "2026"))
        location = prompt("Location", str(existing_defaults.get("location") or "Untitled location"))
        alt = prompt("Alt text", str(existing_defaults.get("alt") or ""))
        while len(alt.split()) < 5:
            print("Alt text is too weak. Use at least 5 words.")
            alt = prompt("Alt text", alt)
        caption = prompt("Caption", str(existing_defaults.get("caption") or ""))
        tags_default = ", ".join(existing_defaults.get("tags") or [])
        tags_input = prompt("Tags (comma separated)", tags_default)
        tags = [item.strip() for item in tags_input.split(",") if item.strip()]
        published = prompt_bool("Published", bool(existing_defaults.get("published", True)))
        hero_safe = prompt_bool("Hero safe", bool(existing_defaults.get("hero_safe", True)))
        grid_safe = prompt_bool("Grid safe", bool(existing_defaults.get("grid_safe", True)))
        social_safe = prompt_bool("Social safe", bool(existing_defaults.get("social_safe", False)))
        focal_existing = existing_defaults.get("focal_point") if isinstance(existing_defaults.get("focal_point"), dict) else {}
        focal_x = prompt_int("Focal point X", int(focal_existing.get("x", pipeline.get("default_focal_point", {}).get("x", 50))))
        focal_y = prompt_int("Focal point Y", int(focal_existing.get("y", pipeline.get("default_focal_point", {}).get("y", 50))))
        position_raw = prompt("Series insertion position (blank = append)", "")
        position = int(position_raw) if position_raw.strip() else None

        warnings = validate_work_input(
            work_id=work_id,
            title=title,
            alt=alt,
            caption=caption,
            tags=tags,
            hero_safe=hero_safe,
            social_safe=social_safe,
        )
        if warnings:
            print("Warnings:")
            for item in warnings:
                print(f"- {item}")
            if not prompt_bool("Continue anyway", False):
                print("Skipped this file.")
                continue

        with transaction(f"ingest:{work_id}"):
            destination_name = f"{work_id}{source_path.suffix.lower()}"
            stored_original = safe_move_to_originals(source_path, series_slug, destination_name, pipeline=pipeline)
            payload = create_work_payload(
                work_id=work_id,
                title=title,
                series_slug=series_slug,
                year=year,
                location=location,
                alt=alt,
                caption=caption,
                tags=tags,
                published=published,
                hero_safe=hero_safe,
                grid_safe=grid_safe,
                social_safe=social_safe,
                focal_x=focal_x,
                focal_y=focal_y,
                master_filename=stored_original.name,
            )
            write_yaml(work_path, payload)
            insert_work_into_series(series_slug, work_id, position=position)
            derivative_meta = generate_derivatives(stored_original, series_slug, work_id, pipeline=pipeline, force=True)
            write_ingestion_log(
                {
                    "event": "ingest",
                    "workId": work_id,
                    "series": series_slug,
                    "sourceOriginal": stored_original.relative_to(Path(__file__).resolve().parents[1]).as_posix(),
                    "responsiveBase": derivative_meta["responsiveBase"],
                    "generatedFiles": derivative_meta["generatedFiles"],
                },
                pipeline=pipeline,
            )
            ensure_og_images_from_content(load_content_for_og(), force=True)
        print(f"Added {work_id} to {series_slug} and generated {len(derivative_meta['generatedFiles'])} files.")

    print("\nDone. Run: python build_site.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelled.")
