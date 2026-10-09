from __future__ import annotations

import copy
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from typing import Any

from audit_library import main as audit_main
from helpers_content import (
    available_page_keys,
    available_series_slugs,
    available_work_ids,
    create_series_file,
    edit_work_payload,
    get_page_feature_work,
    insert_work_into_series,
    load_page_payload,
    load_work_entries,
    load_yaml,
    move_work_to_series,
    page_file_for_key,
    recent_transactions,
    reorder_homepage_featured,
    restore_last_transaction,
    save_page_payload,
    search_library,
    snapshot_path,
    series_file_for_slug,
    set_page_feature_work,
    set_series_cover_work,
    slugify_work_id,
    transaction,
    validate_page_payload,
    validate_work_input,
    work_file_for_id,
    work_to_series_map,
    write_yaml,
)
from helpers_image import (
    SOURCE_EXTENSIONS,
    compute_image_hash,
    derivative_dir_for_work,
    generate_derivatives,
    incoming_root,
    load_pipeline,
    move_generated_between_series,
    move_original_between_series,
    read_dimensions,
    safe_move_to_originals,
    source_path_for_work,
    unassigned_root,
)
from ingest_work import main as ingest_main
from og_images import ensure_og_images_from_content, load_content_for_og
from workbook_sync import analyze_workbook_import, export_site_workbook, import_site_workbook

ROOT = Path(__file__).resolve().parents[1]


def _run_audit_silently() -> None:
    sink = io.StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        _run_audit_silently()



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
    except ValueError:
        print("Please enter a whole number.")
        return prompt_int(text, default)
    return max(0, min(100, value))


def prompt_list(text: str, current: list[str], allow_empty: bool = True) -> list[str]:
    current_text = ", ".join(current)
    raw = input(f"{text} [{current_text}]: ").strip()
    if not raw:
        return current
    if allow_empty and raw == "-":
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def prompt_actions(label: str, current_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    print(label)
    print("Press Enter to keep current values. Type 0 to remove all actions.")
    count_default = len(current_actions)
    count_raw = input(f"How many actions? [{count_default}]: ").strip()
    if not count_raw:
        count = count_default
    elif count_raw == "0":
        return []
    else:
        try:
            count = max(0, int(count_raw))
        except ValueError:
            print("Invalid number. Keeping current actions.")
            count = count_default
    actions: list[dict[str, Any]] = []
    for index in range(count):
        current = current_actions[index] if index < len(current_actions) else {}
        print(f"Action {index + 1}")
        label_value = prompt("  Label", str(current.get("label") or ""))
        href_value = prompt("  Href", str(current.get("href") or ""))
        style_value = prompt("  Style", str(current.get("style") or ""))
        action: dict[str, Any] = {"label": label_value, "href": href_value}
        if style_value:
            action["style"] = style_value
        actions.append(action)
    return actions


def choose_from_list(label: str, options: list[str], allow_blank: bool = False, default: str | None = None) -> str | None:
    if not options:
        return None
    print(label)
    for index, item in enumerate(options, start=1):
        print(f"  {index}. {item}")
    default_label = default or options[0]
    entry = input(f"Choose value or number [{default_label}]: ").strip()
    if not entry and allow_blank:
        return None
    if not entry:
        return default_label
    if entry.isdigit():
        numeric = int(entry)
        if 1 <= numeric <= len(options):
            return options[numeric - 1]
    if entry in options:
        return entry
    print("Unknown selection.")
    return choose_from_list(label, options, allow_blank=allow_blank, default=default)


def regenerate_og(force: bool = True) -> None:
    created = ensure_og_images_from_content(load_content_for_og(), force=force)
    if created:
        print("Updated OG images:")
        for item in created:
            print(f"- {item}")


def show_warnings(warnings: list[str]) -> bool:
    if not warnings:
        return True
    print("Warnings:")
    for item in warnings:
        print(f"- {item}")
    return prompt_bool("Continue anyway", False)


def _stringify(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _collect_changes(old: dict[str, Any], new: dict[str, Any], fields: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    changes: list[tuple[str, str, str]] = []
    for label, key in fields:
        old_value = _stringify(old.get(key))
        new_value = _stringify(new.get(key))
        if old_value != new_value:
            changes.append((label, old_value or "—", new_value or "—"))
    return changes


def confirm_changes(title: str, changes: list[tuple[str, str, str]], *, allow_empty: bool = False) -> bool:
    if not changes and not allow_empty:
        print("No changes to save.")
        return False
    print(f"\n{title}")
    if not changes:
        print("- No field changes detected.")
    else:
        for label, old_value, new_value in changes:
            print(f"- {label}: {old_value} -> {new_value}")
    return prompt_bool("Apply these changes", True)


def image_usage_warnings(*, work_id: str, series_slug: str, payload: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    pipeline = load_pipeline()
    source_path = source_path_for_work(series_slug, work_id, pipeline=pipeline)
    if not source_path or not source_path.exists():
        warnings.append("Original source image is missing")
        return warnings
    width, height = read_dimensions(source_path)
    if width < 1200:
        warnings.append(f"Source image is small ({width}px wide)")
    if bool(payload.get("hero_safe", False)) and width < 1600:
        warnings.append("Hero safe is on, but the image is narrower than 1600px")
    if bool(payload.get("social_safe", False)) and width < 1200:
        warnings.append("Social safe is on, but the image is narrower than 1200px")
    if bool(payload.get("hero_safe", False)) and width < height:
        warnings.append("Hero safe is on, but the image is portrait-oriented")
    return warnings


def summarize_order(title: str, before: list[str], after: list[str]) -> bool:
    changes: list[tuple[str, str, str]] = []
    max_len = max(len(before), len(after))
    for idx in range(max_len):
        old = before[idx] if idx < len(before) else "—"
        new = after[idx] if idx < len(after) else "—"
        if old != new:
            changes.append((f"Position {idx + 1}", old, new))
    return confirm_changes(title, changes, allow_empty=False)


def _latest_build_status() -> dict[str, Any] | None:
    candidates = [
        ROOT / ".stillmrk-build/meta/build-status.json",
        ROOT / ".quietlens-build/meta/build-status.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
    return None


def create_series_wizard() -> None:
    with transaction("create-series"):
        title = prompt("Series title")
        slug_default = title.lower().strip().replace(" ", "-")
        slug = prompt("Series slug", slug_default).lower().replace(" ", "-")
        years = prompt("Series years", "2026")
        mood = prompt("Series mood", "Monochrome sequence")
        description = prompt("Series description", f"A monochrome sequence titled {title}.")
        visibility = prompt("Visibility (public/private)", "public").strip().lower() or "public"
        path = create_series_file(slug, title, years, mood, description, visibility=visibility)
        pipeline = load_pipeline()
        for base in [ROOT / "assets/images/originals/series", ROOT / str(pipeline.get("generated_dir") or "assets/images/generated/series")]:
            (base / slug).mkdir(parents=True, exist_ok=True)
        print(f"Created series file: {path.relative_to(ROOT).as_posix()}")


def _edit_work_common(work_id: str, *, allow_move: bool = True) -> None:
    path = work_file_for_id(work_id)
    payload = load_yaml(path) or {}
    original_payload = copy.deepcopy(payload)
    current_series = work_to_series_map().get(work_id) or str(payload.get("series") or "")
    print(f"Editing {work_id} (current series: {current_series or 'unknown'})")
    updates: dict[str, Any] = {}
    updates["title"] = prompt("Title", str(payload.get("title") or ""))
    updates["year"] = prompt("Year", str(payload.get("year") or ""))
    updates["location"] = prompt("Location", str(payload.get("location") or ""))
    alt = prompt("Alt text", str(payload.get("alt") or ""))
    while len(alt.split()) < 5:
        print("Alt text should have at least 5 words.")
        alt = prompt("Alt text", alt)
    updates["alt"] = alt
    updates["caption"] = prompt("Caption", str(payload.get("caption") or ""))
    tags = prompt("Tags (comma separated)", ", ".join(payload.get("tags") or []))
    updates["tags"] = [item.strip() for item in tags.split(",") if item.strip()]
    updates["published"] = prompt_bool("Published", bool(payload.get("published", True)))
    updates["hero_safe"] = prompt_bool("Hero safe", bool(payload.get("hero_safe", True)))
    updates["grid_safe"] = prompt_bool("Grid safe", bool(payload.get("grid_safe", True)))
    updates["social_safe"] = prompt_bool("Social safe", bool(payload.get("social_safe", False)))
    focal = payload.get("focal_point") if isinstance(payload.get("focal_point"), dict) else {}
    updates["focal_point"] = {
        "x": prompt_int("Focal point X", int(focal.get("x", 50))),
        "y": prompt_int("Focal point Y", int(focal.get("y", 50))),
    }
    preview_payload = copy.deepcopy(payload)
    preview_payload.update(updates)
    warnings = validate_work_input(
        work_id=work_id,
        title=updates["title"],
        alt=updates["alt"],
        caption=updates["caption"],
        tags=updates["tags"],
        hero_safe=updates["hero_safe"],
        social_safe=updates["social_safe"],
    )
    warnings.extend(image_usage_warnings(work_id=work_id, series_slug=current_series, payload=preview_payload))
    target_series = current_series
    position = None
    if allow_move:
        target_series = choose_from_list("Move to another series or keep the current one:", available_series_slugs(), default=current_series or None) or current_series
        position_raw = prompt("Series insertion position (blank = keep/append)", "")
        position = int(position_raw) if position_raw.strip() else None
        if target_series != current_series:
            warnings.append(f"Work will move from {current_series} to {target_series}")
    changes = _collect_changes(original_payload, preview_payload, [
        ("Title", "title"),
        ("Year", "year"),
        ("Location", "location"),
        ("Alt text", "alt"),
        ("Caption", "caption"),
        ("Tags", "tags"),
        ("Published", "published"),
        ("Hero safe", "hero_safe"),
        ("Grid safe", "grid_safe"),
        ("Social safe", "social_safe"),
        ("Focal point", "focal_point"),
    ])
    if target_series != current_series:
        changes.append(("Series", current_series or "—", target_series or "—"))
    if position is not None:
        changes.append(("Series position", "keep/append", str(position)))
    if not confirm_changes(f"Planned updates for {work_id}", changes):
        print("Edit cancelled.")
        return
    if not show_warnings(warnings):
        print("Edit cancelled.")
        return
    with transaction(f"edit-work:{work_id}"):
        if allow_move:
            previous_series, new_series = move_work_to_series(work_id, target_series, position=position)
            updates["series"] = new_series
            pipeline = load_pipeline()
            moved_original = move_original_between_series(work_id, previous_series, new_series, pipeline=pipeline)
            move_generated_between_series(work_id, previous_series, new_series, pipeline=pipeline)
            source_path = moved_original or source_path_for_work(new_series, work_id, pipeline=pipeline)
            if source_path:
                generate_derivatives(source_path, new_series, work_id, pipeline=pipeline, force=True)
        edit_work_payload(work_id, updates)
        regenerate_og(force=True)
    print(f"Updated work: {work_id}")


def edit_work_wizard() -> None:
    work_id = choose_from_list("Available works:", available_work_ids())
    if not work_id:
        print("No works found.")
        return
    _edit_work_common(work_id, allow_move=True)


def page_top_image_wizard() -> None:
    pages = [page for page in ["home", "about", "contact", "portfolio"] if page in available_page_keys()]
    page_key = choose_from_list("Choose a page:", pages)
    if not page_key:
        return
    current = get_page_feature_work(page_key)
    new_work = choose_from_list(f"Choose the new top image work id for {page_key}:", available_work_ids(), default=current)
    if not new_work:
        return
    work_payload = load_yaml(work_file_for_id(new_work)) or {}
    warnings = []
    if not bool(work_payload.get("hero_safe", False)):
        warnings.append(f"{new_work} is not marked hero_safe")
    if not bool(work_payload.get("social_safe", False)):
        warnings.append(f"{new_work} is not marked social_safe, so OG crops may be weak")
    warnings.extend(image_usage_warnings(work_id=new_work, series_slug=str(work_payload.get("series") or work_to_series_map().get(new_work) or ""), payload=work_payload))
    if not confirm_changes(f"Top image update for {page_key}", [("Hero image", current or "—", new_work)]):
        print("Page top image change cancelled.")
        return
    if not show_warnings(warnings):
        return
    with transaction(f"page-top-image:{page_key}"):
        set_page_feature_work(page_key, new_work)
        regenerate_og(force=True)
    print(f"Updated {page_key} top image to {new_work}")


def series_cover_wizard() -> None:
    series_slug = choose_from_list("Choose a series:", available_series_slugs())
    if not series_slug:
        return
    series_payload = load_yaml(series_file_for_slug(series_slug)) or {}
    work_ids = [str(item).strip() for item in (series_payload.get("work_ids") or []) if str(item).strip()]
    if not work_ids:
        print("That series does not contain any works yet.")
        return
    current = str(series_payload.get("cover_work_id") or work_ids[0]).strip()
    new_cover = choose_from_list(f"Choose cover work for {series_slug}:", work_ids, default=current)
    if not new_cover:
        return
    if not confirm_changes(f"Series cover update for {series_slug}", [("Cover work", current or "—", new_cover)]):
        print("Series cover change cancelled.")
        return
    with transaction(f"series-cover:{series_slug}"):
        set_series_cover_work(series_slug, new_cover)
        regenerate_og(force=True)
    print(f"Updated {series_slug} cover image to {new_cover}")


def reorder_series_wizard() -> None:
    series_slug = choose_from_list("Choose a series to reorder:", available_series_slugs())
    if not series_slug:
        return
    path = series_file_for_slug(series_slug)
    payload = load_yaml(path) or {}
    work_ids = [str(item).strip() for item in (payload.get("work_ids") or []) if str(item).strip()]
    if not work_ids:
        print("That series has no works to reorder.")
        return
    print("Current order:")
    for index, item in enumerate(work_ids, start=1):
        marker = " (cover)" if item == str(payload.get("cover_work_id") or "") else ""
        print(f"  {index}. {item}{marker}")
    work_id = choose_from_list("Which work do you want to move?", work_ids)
    if not work_id:
        return
    try:
        new_position = int(prompt("New position", "1"))
    except ValueError:
        print("Invalid position.")
        return
    proposed = work_ids[:]
    proposed.remove(work_id)
    new_position = max(1, min(len(proposed) + 1, new_position))
    proposed.insert(new_position - 1, work_id)
    if not summarize_order(f"Series order preview for {series_slug}", work_ids, proposed):
        print("Reorder cancelled.")
        return
    with transaction(f"reorder-series:{series_slug}"):
        payload["work_ids"] = proposed
        if str(payload.get("cover_work_id") or "").strip() not in proposed and proposed:
            payload["cover_work_id"] = proposed[0]
        write_yaml(path, payload)
        regenerate_og(force=True)
    print(f"Updated order for {series_slug}")


def reorder_homepage_wizard() -> None:
    payload = load_page_payload("home")
    featured = payload.get("featured_series") if isinstance(payload.get("featured_series"), dict) else {}
    selected = payload.get("selected_works") if isinstance(payload.get("selected_works"), dict) else {}
    print("Current featured series order:")
    current_series = [str(item) for item in featured.get("series_slugs") or []]
    for idx, item in enumerate(current_series, 1):
        print(f"  {idx}. {item}")
    new_series = prompt_list("New featured series order (comma separated)", current_series)
    print("Current selected works order:")
    current_works = [str(item) for item in selected.get("work_ids") or []]
    for idx, item in enumerate(current_works, 1):
        print(f"  {idx}. {item}")
    new_works = prompt_list("New selected works order (comma separated)", current_works)
    if not summarize_order("Homepage featured series preview", current_series, new_series):
        print("Homepage featured series reorder cancelled.")
        return
    if not summarize_order("Homepage selected works preview", current_works, new_works):
        print("Homepage selected works reorder cancelled.")
        return
    with transaction("reorder-homepage-featured"):
        reorder_homepage_featured(featured_series=new_series, selected_works=new_works)
        regenerate_og(force=True)
    print("Updated homepage featured content order.")


def generate_og_wizard() -> None:
    regenerate_og(force=True)
    print("OG image generation completed.")


def print_page_summary(page_key: str, payload: dict[str, Any]) -> None:
    print(f"\nEditing page: {page_key}")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
    if meta:
        print(f"- Meta title: {meta.get('title', '')}")
        print(f"- Meta description: {meta.get('description', '')}")
    if hero:
        print(f"- Hero eyebrow: {hero.get('eyebrow', '')}")
        print(f"- Hero title: {hero.get('title', '')}")
        print(f"- Hero lead: {hero.get('lead', '')}")
        print(f"- Hero feature work: {hero.get('feature_work_id', '')}")
    if page_key == 'series':
        print(f"- Hero title: {payload.get('hero_title', '')}")


def edit_meta_common(payload: dict[str, Any]) -> None:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    meta["title"] = prompt("Meta title", str(meta.get("title") or ""))
    meta["description"] = prompt("Meta description", str(meta.get("description") or ""))
    meta["og_description"] = prompt("OG description", str(meta.get("og_description") or ""))
    meta["og_image_alt"] = prompt("OG image alt", str(meta.get("og_image_alt") or ""))
    payload["meta"] = meta


def edit_hero_common(page_key: str, payload: dict[str, Any]) -> None:
    hero = payload.get("hero") if isinstance(payload.get("hero"), dict) else {}
    if not hero:
        print("This page does not use a standard hero block.")
        return
    hero["eyebrow"] = prompt("Hero eyebrow", str(hero.get("eyebrow") or ""))
    hero["title"] = prompt("Hero title", str(hero.get("title") or ""))
    hero["lead"] = prompt("Hero lead", str(hero.get("lead") or ""))
    current_feature = str(hero.get("feature_work_id") or "").strip()
    if current_feature or prompt_bool("Choose/change hero image now", False):
        chosen = choose_from_list("Choose hero image work id:", available_work_ids(), default=current_feature or None)
        if chosen:
            hero["feature_work_id"] = chosen
    if page_key == "home":
        primary_action = hero.get("primary_action") if isinstance(hero.get("primary_action"), dict) else {}
        primary_action["label"] = prompt("Primary action label", str(primary_action.get("label") or ""))
        primary_action["href"] = prompt("Primary action href", str(primary_action.get("href") or ""))
        primary_action["style"] = prompt("Primary action style", str(primary_action.get("style") or "primary"))
        hero["primary_action"] = primary_action
        secondary_action = hero.get("secondary_action") if isinstance(hero.get("secondary_action"), dict) else {}
        secondary_action["label"] = prompt("Secondary action label", str(secondary_action.get("label") or ""))
        secondary_action["href"] = prompt("Secondary action href", str(secondary_action.get("href") or ""))
        secondary_action["style"] = prompt("Secondary action style", str(secondary_action.get("style") or "secondary"))
        hero["secondary_action"] = secondary_action
    else:
        hero["actions"] = prompt_actions("Hero actions", hero.get("actions") if isinstance(hero.get("actions"), list) else [])
    if isinstance(hero.get("notes"), list):
        hero["notes"] = prompt_list("Hero notes (comma separated, use - to clear)", [str(item) for item in hero.get("notes") or []])
    payload["hero"] = hero


def edit_home_sections(payload: dict[str, Any]) -> None:
    featured = payload.get("featured_series") if isinstance(payload.get("featured_series"), dict) else {}
    print("\nHome featured series")
    featured["eyebrow"] = prompt("Featured series eyebrow", str(featured.get("eyebrow") or ""))
    featured["title"] = prompt("Featured series title", str(featured.get("title") or ""))
    featured["intro"] = prompt("Featured series intro", str(featured.get("intro") or ""))
    featured["series_slugs"] = prompt_list("Featured series slugs (comma separated)", [str(item) for item in featured.get("series_slugs") or []])
    payload["featured_series"] = featured

    selected = payload.get("selected_works") if isinstance(payload.get("selected_works"), dict) else {}
    print("\nHome selected works")
    selected["eyebrow"] = prompt("Selected works eyebrow", str(selected.get("eyebrow") or ""))
    selected["title"] = prompt("Selected works title", str(selected.get("title") or ""))
    selected["intro"] = prompt("Selected works intro", str(selected.get("intro") or ""))
    selected["work_ids"] = prompt_list("Selected work ids (comma separated)", [str(item) for item in selected.get("work_ids") or []])
    payload["selected_works"] = selected

    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), list) else []
    if metrics and prompt_bool("Edit home metrics", False):
        print("Use Enter to keep values.")
        for index, item in enumerate(metrics, start=1):
            print(f"Metric {index}")
            item["value"] = prompt("  Value", str(item.get("value") or ""))
            item["label"] = prompt("  Label", str(item.get("label") or ""))
        payload["metrics"] = metrics


def edit_about_sections(payload: dict[str, Any]) -> None:
    statement = payload.get("statement") if isinstance(payload.get("statement"), dict) else {}
    print("\nAbout statement")
    statement["eyebrow"] = prompt("Statement eyebrow", str(statement.get("eyebrow") or ""))
    statement["title"] = prompt("Statement title", str(statement.get("title") or ""))
    statement["text"] = prompt("Statement text", str(statement.get("text") or ""))
    payload["statement"] = statement


def edit_contact_sections(payload: dict[str, Any]) -> None:
    payload["details_title"] = prompt("Details title", str(payload.get("details_title") or ""))
    payload["inquiry_types"] = prompt_list("Inquiry types (comma separated)", [str(item) for item in payload.get("inquiry_types") or []])
    payload["form_button_label"] = prompt("Form button label", str(payload.get("form_button_label") or ""))
    payload["form_note"] = prompt("Form note", str(payload.get("form_note") or ""))
    payload["form_intro"] = prompt("Form intro", str(payload.get("form_intro") or ""))


def edit_portfolio_sections(payload: dict[str, Any]) -> None:
    print("Portfolio page currently uses only meta + hero content in this manager.")


def edit_series_page_sections(payload: dict[str, Any]) -> None:
    payload["hero_title"] = prompt("Series page hero title", str(payload.get("hero_title") or ""))


def page_content_wizard() -> None:
    page_key = choose_from_list("Choose a page to edit:", available_page_keys())
    if not page_key:
        print("No page files found.")
        return
    payload = load_page_payload(page_key)
    original_payload = copy.deepcopy(payload)
    print_page_summary(page_key, payload)
    print("\nPage Manager")
    print("1. Edit SEO/meta text")
    print("2. Edit hero text")
    print("3. Edit page-specific sections")
    choice = input("Choose an option: ").strip()
    if choice == "1":
        edit_meta_common(payload)
    elif choice == "2":
        if page_key == "series":
            print("Series page does not use the standard hero block. Use page-specific sections instead.")
            return
        edit_hero_common(page_key, payload)
    elif choice == "3":
        if page_key == "home":
            edit_home_sections(payload)
        elif page_key == "about":
            edit_about_sections(payload)
        elif page_key == "contact":
            edit_contact_sections(payload)
        elif page_key == "portfolio":
            edit_portfolio_sections(payload)
        elif page_key == "series":
            edit_series_page_sections(payload)
        else:
            print("This page type is not supported yet.")
            return
    else:
        print("Unknown option.")
        return
    warnings = validate_page_payload(page_key, payload)
    changes = []
    if original_payload != payload:
        for section_key in sorted(set(original_payload) | set(payload)):
            old_value = _stringify(original_payload.get(section_key))
            new_value = _stringify(payload.get(section_key))
            if old_value != new_value:
                changes.append((section_key, (old_value[:120] + '…') if len(old_value) > 120 else old_value or "—", (new_value[:120] + '…') if len(new_value) > 120 else new_value or "—"))
    if not confirm_changes(f"Page changes for {page_key}", changes):
        print("Page changes cancelled.")
        return
    if not show_warnings(warnings):
        print("Page changes cancelled.")
        return
    with transaction(f"edit-page:{page_key}"):
        save_page_payload(page_key, payload)
        regenerate_og(force=True)
    print(f"Saved changes to {page_file_for_key(page_key).relative_to(ROOT).as_posix()}")


def run_build() -> None:
    subprocess.run([sys.executable, str(ROOT / "build_site.py")], check=False)


def run_preview() -> None:
    print("Preview server will block this menu until you stop it with Ctrl + C.")
    subprocess.run([sys.executable, str(ROOT / "preview_server.py")], check=False)


def undo_last_change_wizard() -> None:
    txns = recent_transactions(5)
    if not txns:
        print("No recorded studio transactions found.")
        return
    print("Recent changes:")
    for idx, txn in enumerate(txns, 1):
        print(f"  {idx}. {txn.get('label')} ({txn.get('status')})")
    restored = restore_last_transaction()
    if not restored:
        print("No completed transaction available to undo.")
        return
    print(f"Restored: {restored.get('label')}")


def _choose_incoming_file() -> Path | None:
    incoming = incoming_root(load_pipeline())
    files = sorted([path for path in incoming.iterdir() if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS])
    if not files:
        print("No files found in assets/images/incoming")
        return None
    rels = [path.name for path in files]
    chosen = choose_from_list("Choose an incoming image:", rels)
    if not chosen:
        return None
    return incoming / chosen


def replace_image_wizard() -> None:
    work_id = choose_from_list("Choose an existing work to replace:", available_work_ids())
    if not work_id:
        return
    incoming_file = _choose_incoming_file()
    if not incoming_file:
        return
    payload = load_yaml(work_file_for_id(work_id)) or {}
    series_slug = str(payload.get("series") or work_to_series_map().get(work_id) or "").strip()
    if not series_slug:
        print("Could not resolve the work series.")
        return
    pipeline = load_pipeline()
    current_source = source_path_for_work(series_slug, work_id, pipeline=pipeline)
    current_dims = read_dimensions(current_source) if current_source and current_source.exists() else (0, 0)
    incoming_dims = read_dimensions(incoming_file)
    changes = [
        ("Work", work_id, work_id),
        ("Current source", current_source.name if current_source else "—", incoming_file.name),
        ("Current dimensions", f"{current_dims[0]}x{current_dims[1]}", f"{incoming_dims[0]}x{incoming_dims[1]}"),
    ]
    warnings = []
    if incoming_dims[0] < 1200:
        warnings.append("Replacement image is narrower than 1200px")
    if bool(payload.get("hero_safe", False)) and incoming_dims[0] < 1600:
        warnings.append("Replacement image is small for a hero-safe work")
    if bool(payload.get("social_safe", False)) and incoming_dims[0] < 1200:
        warnings.append("Replacement image is small for social use")
    if not confirm_changes(f"Replace image for {work_id}", changes):
        print("Replace image cancelled.")
        return
    if not show_warnings(warnings):
        return
    with transaction(f"replace-image:{work_id}"):
        destination_name = f"{work_id}{incoming_file.suffix.lower()}"
        stored_original = safe_move_to_originals(incoming_file, series_slug, destination_name, pipeline=pipeline)
        image_block = payload.get("image") if isinstance(payload.get("image"), dict) else {}
        image_block["master"] = stored_original.name
        image_block["render_name"] = work_id
        payload["image"] = image_block
        write_yaml(work_file_for_id(work_id), payload)
        generate_derivatives(stored_original, series_slug, work_id, pipeline=pipeline, force=True)
        regenerate_og(force=True)
    print(f"Replaced image for {work_id}")


def publish_toggle_wizard() -> None:
    work_id = choose_from_list("Choose a work:", available_work_ids())
    if not work_id:
        return
    payload = load_yaml(work_file_for_id(work_id)) or {}
    current = bool(payload.get("published", True))
    print(f"Current published status: {current}")
    print("1. Publish")
    print("2. Unpublish / Archive")
    choice = input("Choose an option: ").strip()
    new_value = True if choice == "1" else False if choice == "2" else None
    if new_value is None:
        print("Cancelled.")
        return
    with transaction(f"publish-toggle:{work_id}"):
        payload["published"] = new_value
        write_yaml(work_file_for_id(work_id), payload)
        regenerate_og(force=True)
    print(f"Updated published status for {work_id} to {new_value}")


def move_work_wizard() -> None:
    work_id = choose_from_list("Choose a work to move:", available_work_ids())
    if not work_id:
        return
    payload = load_yaml(work_file_for_id(work_id)) or {}
    current_series = str(payload.get("series") or work_to_series_map().get(work_id) or "")
    target_series = choose_from_list("Choose the new series:", available_series_slugs(), default=current_series)
    if not target_series:
        return
    position_raw = prompt("Series insertion position (blank = append)", "")
    position = int(position_raw) if position_raw.strip() else None
    target_payload = load_yaml(series_file_for_slug(target_series)) or {}
    target_work_ids = [str(item).strip() for item in (target_payload.get("work_ids") or []) if str(item).strip() and str(item).strip() != work_id]
    preview_order = target_work_ids[:]
    if position is None or position <= 0 or position > len(preview_order) + 1:
        preview_order.append(work_id)
    else:
        preview_order.insert(position - 1, work_id)
    changes = [("Series", current_series or "—", target_series)]
    if not confirm_changes(f"Move {work_id} to another series", changes):
        print("Move cancelled.")
        return
    print("Target series preview:")
    for idx, item in enumerate(preview_order, 1):
        print(f"  {idx}. {item}")
    if not prompt_bool("Proceed with this move", True):
        print("Move cancelled.")
        return
    with transaction(f"move-work:{work_id}"):
        pipeline = load_pipeline()
        previous_series, new_series = move_work_to_series(work_id, target_series, position=position)
        move_original_between_series(work_id, previous_series, new_series, pipeline=pipeline)
        move_generated_between_series(work_id, previous_series, new_series, pipeline=pipeline)
        source_path = source_path_for_work(new_series, work_id, pipeline=pipeline)
        if source_path:
            generate_derivatives(source_path, new_series, work_id, pipeline=pipeline, force=True)
        regenerate_og(force=True)
    print(f"Moved {work_id} to {target_series}")


def search_wizard() -> None:
    query = prompt("Search query")
    results = search_library(query)
    if not results:
        print("No matches found.")
        return
    print(f"Matches: {len(results)}")
    work_total = 0
    series_total = 0
    for item in results:
        if item["type"] == "work":
            work_total += 1
            print(f"- work | {item['id']} | {item['title']} | {item['series']}")
        else:
            series_total += 1
            print(f"- series | {item['id']} | {item['title']}")
    print(f"Summary: {work_total} works, {series_total} series")


def cleanup_wizard() -> None:
    _run_audit_silently()
    report_path = ROOT / "assets/images/manifests/audit-report.json"
    if not report_path.exists():
        print("Audit report not found.")
        return
    report = json.loads(report_path.read_text(encoding="utf-8"))
    orphan_generated = report.get("orphan_generated", [])
    orphan_originals = report.get("orphan_originals", [])
    print("Cleanup Assistant")
    print(f"- Orphan originals: {len(orphan_originals)}")
    print(f"- Orphan generated folders: {len(orphan_generated)}")
    print("1. Show first 20 orphan originals")
    print("2. Delete orphan generated folders")
    print("3. Move one orphan original to incoming")
    print("0. Return")
    choice = input("Choose an option: ").strip()
    if choice == "1":
        for item in orphan_originals[:20]:
            print(f"- {item}")
        return
    if choice == "2":
        if not orphan_generated:
            print("No orphan generated folders found.")
            return
        with transaction("cleanup-orphan-generated"):
            for item in orphan_generated:
                path = ROOT / item
                if path.exists() and path.is_dir():
                    snapshot_path(path)
                    shutil.rmtree(path)
        print(f"Deleted {len(orphan_generated)} orphan generated folders.")
        return
    if choice == "3":
        if not orphan_originals:
            print("No orphan originals found.")
            return
        selection = choose_from_list("Choose an orphan original to move into incoming:", orphan_originals)
        if not selection:
            return
        src = ROOT / selection
        dst = incoming_root(load_pipeline()) / src.name
        with transaction("cleanup-move-orphan-to-incoming"):
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                raise ValueError(f"Incoming file already exists: {dst.name}")
            snapshot_path(src)
            shutil.move(str(src), str(dst))
        print(f"Moved {selection} to assets/images/incoming/{src.name}")
        return


def health_check_wizard() -> None:
    _run_audit_silently()
    report_path = ROOT / "assets/images/manifests/audit-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    build_status = _latest_build_status() or {}
    content = load_content_for_og()
    page_targets = []
    try:
        from og_images import _page_targets as og_page_targets  # type: ignore
        page_targets = og_page_targets(content)
    except Exception:
        page_targets = []
    missing_og = []
    for target in page_targets:
        og_path = ROOT / str(target.get("og_path") or "")
        if not og_path.exists():
            missing_og.append(str(target.get("og_path") or ""))
    txns = recent_transactions(1)
    latest_txn = txns[0] if txns else None
    print("Health check")
    print(f"- Missing originals: {len(report.get('missing_originals', []))}")
    print(f"- Missing derivatives: {len(report.get('missing_derivatives', []))}")
    print(f"- Incoming files waiting: {len(report.get('incoming_files', []))}")
    print(f"- Orphan originals: {len(report.get('orphan_originals', []))}")
    print(f"- Missing OG images: {len(missing_og)}")
    if latest_txn:
        print(f"- Latest studio change: {latest_txn.get('label')} ({latest_txn.get('status')})")
    if build_status:
        print(f"- Last build recorded: {build_status.get('built_at') or build_status.get('generated_at') or 'unknown'}")
    ready = not report.get('missing_originals') and not report.get('missing_derivatives') and not missing_og
    print(f"- Overall status: {'READY' if ready else 'NEEDS ATTENTION'}")




def export_workbook_wizard() -> None:
    path = export_site_workbook()
    print(f"Workbook exported: {path.relative_to(ROOT).as_posix() if path.is_absolute() and ROOT in path.parents else path}")


def import_workbook_wizard() -> None:
    export_dir = ROOT / 'exports'
    files = sorted(export_dir.glob('*.xlsx'), key=lambda item: item.stat().st_mtime, reverse=True)
    chosen_path = None
    if files:
        labels = [path.name for path in files[:20]]
        print('Available workbook exports:')
        for index, item in enumerate(labels, start=1):
            print(f'  {index}. {item}')
        entry = input(f"Choose workbook number or path [{labels[0]}]: ").strip()
        if not entry:
            chosen_path = files[0]
        elif entry.isdigit() and 1 <= int(entry) <= len(labels):
            chosen_path = files[int(entry) - 1]
        else:
            candidate = Path(entry)
            chosen_path = candidate if candidate.is_absolute() else (ROOT / candidate)
    else:
        raw = input('Workbook path: ').strip()
        if raw:
            candidate = Path(raw)
            chosen_path = candidate if candidate.is_absolute() else (ROOT / candidate)
    if not chosen_path or not chosen_path.exists():
        print('Workbook file not found.')
        return
    summary = analyze_workbook_import(chosen_path)
    print('Import preview')
    print(f"- Site setting changes: {summary.get('site_setting_changes', 0)}")
    print(f"- Pages changed: {', '.join(summary.get('pages_changed', [])) or 'none'}")
    print(f"- Series changed: {summary.get('series_changed', 0)}")
    print(f"- Works changed: {summary.get('works_changed', 0)}")
    print(f"- Home ordering changes: {summary.get('home_order_changed', 0)}")
    print(f"- Documents changed: {summary.get('documents_changed', 0)}")
    print(f"- Navigation changed: {summary.get('navigation_changed', 0)}")
    for warning in summary.get('warnings', []):
        print(f"- Warning: {warning}")
    if not prompt_bool('Apply workbook changes', False):
        print('Import cancelled.')
        return
    with transaction('import-workbook'):
        applied = import_site_workbook(chosen_path)
        regenerate_og(force=True)
    print('Workbook import complete.')
    for key, value in applied.items():
        print(f"- {key}: {value}")
    if prompt_bool('Run build now', True):
        run_build()

def main() -> None:
    menu = {
        "1": ("Add new image(s)", ingest_main),
        "2": ("Edit existing image/work metadata", edit_work_wizard),
        "3": ("Create a new series", create_series_wizard),
        "4": ("Change page top image", page_top_image_wizard),
        "5": ("Change series cover image", series_cover_wizard),
        "6": ("Reorder works inside a series", reorder_series_wizard),
        "7": ("Generate custom OG social images", generate_og_wizard),
        "8": ("Audit image library", audit_main),
        "9": ("Build site", run_build),
        "10": ("Preview site", run_preview),
        "11": ("Edit page content", page_content_wizard),
        "12": ("Undo / rollback last studio change", undo_last_change_wizard),
        "13": ("Replace image for existing work", replace_image_wizard),
        "14": ("Archive / unpublish / publish work", publish_toggle_wizard),
        "15": ("Move work to another series", move_work_wizard),
        "16": ("Search and find", search_wizard),
        "17": ("Cleanup assistant for orphan files", cleanup_wizard),
        "18": ("Reorder homepage featured content", reorder_homepage_wizard),
        "19": ("Health check", health_check_wizard),
        "20": ("Export site workbook (.xlsx)", export_workbook_wizard),
        "21": ("Import site workbook (.xlsx)", import_workbook_wizard),
        "0": ("Exit", None),
    }
    order = [str(i) for i in range(1, 22)] + ["0"]
    while True:
        print("\nSTILLMRK Studio")
        for key in order:
            print(f"{key}. {menu[key][0]}")
        choice = input("Choose an option: ").strip()
        if choice == "0":
            print("Goodbye.")
            return
        action = menu.get(choice)
        if not action:
            print("Unknown option.")
            continue
        try:
            action[1]()
        except KeyboardInterrupt:
            print("\nCancelled.")
        except Exception as exc:
            print(f"Error: {exc}")


if __name__ == "__main__":
    main()
