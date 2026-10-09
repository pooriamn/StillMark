from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import stat
import re
import shutil
import time
from datetime import datetime, timezone
from collections import Counter
from urllib.parse import quote, urlparse
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from PIL import Image, ImageOps, features as pil_features

try:
    from scripts.og_images import ensure_og_images_from_content
except Exception:  # pragma: no cover
    ensure_og_images_from_content = None

ROOT = Path(__file__).resolve().parent
CONTENT_DIR = ROOT / 'content'
SCHEMA_PATH = CONTENT_DIR / 'schema' / 'content.schema.json'
DEFAULT_IMAGE_PIPELINE = {
    "source_dir": "assets/images/originals/series",
    "responsive_dir": "assets/images/responsive",
    "generated_dir": "assets/images/generated/series",
    "incoming_dir": "assets/images/incoming",
    "manifest_dir": "assets/images/manifests",
    "widths": [480, 768, 1200, 1600, 2048],
    "formats": ["jpg", "webp"],
    "jpg_quality": 86,
    "webp_quality": 82,
    "lightbox_width": 1600,
    "default_focal_point": {"x": 50, "y": 50},
}
SOURCE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff')
BUILD_STATE_DIR = ROOT / '.stillmrk-build'
ASSET_MANIFEST_PATH = BUILD_STATE_DIR / 'responsive-assets.json'
ASSET_QUARANTINE_ROOT = BUILD_STATE_DIR / 'quarantine' / 'generated-images'
IMAGE_DERIVATIVE_EXTENSIONS = {'.jpg', '.jpeg', '.webp', '.avif'}
BUILD_META_DIR = BUILD_STATE_DIR / 'meta'
BUILD_STATUS_PATH = BUILD_META_DIR / 'build-status.json'
CONTENT_GRAPH_PATH = BUILD_META_DIR / 'content-graph.json'
RELEASE_REPORT_PATH = BUILD_META_DIR / 'release-report.json'
# All build output goes to dist/. Nothing generated is written into the source
# tree any more (pages, data.js and the upload bundle used to be written to the
# repository root and to public_upload/).
DIST_DIR = ROOT / 'dist'
PUBLIC_UPLOAD_DIR = DIST_DIR  # legacy name, kept for older tooling
IMAGE_STAMP_NAME = '.derivatives.json'

# 'build' renders missing/outdated derivatives; 'validate' only reads image
# headers so `--validate-only` never decodes, resizes or writes anything.
IMAGE_MODE = 'build'

PUBLISH_STATE_PATH = BUILD_META_DIR / 'publish-state.json'

BUILD_MISSING_ASSET_ROWS: list[dict[str, Any]] = []
PLACEHOLDER_INTRINSIC_SIZE = (1600, 1200)


def build_public_identity(raw: dict[str, Any]) -> dict[str, str]:
    site = raw.get('site') if isinstance(raw.get('site'), dict) else {}
    artist = raw.get('artist') if isinstance(raw.get('artist'), dict) else {}
    public_email = str(site.get('public_email') or artist.get('email') or '').strip()
    public_location = str(artist.get('location') or site.get('location') or '').strip()
    return {
        'email': public_email,
        'location': public_location,
        'instagram': str(artist.get('instagram') or '').strip(),
        'name': str(artist.get('name') or site.get('name') or '').strip(),
        'status': str(artist.get('status') or '').strip(),
        'discipline': str(artist.get('discipline') or '').strip(),
    }


def write_publish_state_after_build() -> None:
    import hashlib
    BUILD_META_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    for candidate in sorted((CONTENT_DIR).rglob('*.yaml')):
        digest.update(candidate.relative_to(ROOT).as_posix().encode('utf-8'))
        digest.update(candidate.read_bytes())
    payload = {
        'last_build_at': iso_timestamp(),
        'last_publish_at': iso_timestamp(),
        'content_hash': digest.hexdigest(),
        'has_unpublished_changes': False,
    }
    PUBLISH_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')


def yaml_glob(folder: Path) -> list[Path]:
    return sorted([*folder.glob('*.yaml'), *folder.glob('*.yml')])


def load_yaml_file(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f'Missing content file: {path.relative_to(ROOT).as_posix()}')
    with path.open('r', encoding='utf-8') as handle:
        data = yaml.safe_load(handle)
    return data


def load_yaml_folder(folder: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in yaml_glob(folder):
        loaded = load_yaml_file(path)
        if loaded is None:
            raise ValueError(f'Content file is empty: {path.relative_to(ROOT).as_posix()}')
        if not isinstance(loaded, dict):
            raise TypeError(f'Expected a YAML object in {path.relative_to(ROOT).as_posix()}')
        entries.append(loaded)
    return entries


def load_site_content() -> dict[str, Any]:
    navigation_loaded = load_yaml_file(CONTENT_DIR / 'navigation.yaml')
    if isinstance(navigation_loaded, dict) and isinstance(navigation_loaded.get('items'), list):
        navigation_loaded = navigation_loaded['items']

    content = {
        'site': load_yaml_file(CONTENT_DIR / 'site.yaml'),
        'artist': load_yaml_file(CONTENT_DIR / 'artist.yaml'),
        'navigation': navigation_loaded,
        'image_pipeline': load_yaml_file(CONTENT_DIR / 'image-pipeline.yaml'),
        'resources': load_yaml_file(CONTENT_DIR / 'resources.yaml') if (CONTENT_DIR / 'resources.yaml').exists() else {'downloads': []},
        'release': load_yaml_file(CONTENT_DIR / 'release.yaml') if (CONTENT_DIR / 'release.yaml').exists() else {},
        'pages': {},
        'collections': [],
        'series': [],
        'works': [],
    }

    pages_dir = CONTENT_DIR / 'pages'
    for page_path in yaml_glob(pages_dir):
        content['pages'][page_path.stem] = load_yaml_file(page_path)

    collections_dir = CONTENT_DIR / 'collections'
    if collections_dir.exists():
        collection_entries = load_yaml_folder(collections_dir)
        content['collections'] = sorted(collection_entries, key=lambda entry: (int(entry.get('order', 9999)), str(entry.get('slug', ''))))

    series_entries = load_yaml_folder(CONTENT_DIR / 'series')
    content['series'] = sorted(series_entries, key=lambda entry: (int(entry.get('order', 9999)), str(entry.get('slug', ''))))

    work_entries = load_yaml_folder(CONTENT_DIR / 'works')
    content['works'] = sorted(work_entries, key=lambda entry: str(entry.get('id', '')))

    validate_site_content(content)
    return content

def load_schema() -> dict[str, Any]:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f'Missing schema file: {SCHEMA_PATH.relative_to(ROOT).as_posix()}')
    return json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))


def format_error_path(parts: list[Any]) -> str:
    if not parts:
        return '<root>'
    formatted: list[str] = []
    for part in parts:
        if isinstance(part, int):
            formatted.append(f'[{part}]')
        else:
            formatted.append(str(part) if not formatted else f'.{part}')
    return ''.join(formatted)


def validate_schema(content: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(load_schema())
    errors: list[str] = []
    for error in sorted(validator.iter_errors(content), key=lambda item: list(item.absolute_path)):
        errors.append(f'{format_error_path(list(error.absolute_path))}: {error.message}')
    return errors


def validate_relationships(content: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    works = content.get('works', [])
    series_list = content.get('series', [])
    collections_list = content.get('collections', []) if isinstance(content.get('collections', []), list) else []
    resources = content.get('resources', {}) if isinstance(content.get('resources'), dict) else {}
    release = content.get('release', {}) if isinstance(content.get('release'), dict) else {}
    work_ids = [entry.get('id') for entry in works]
    series_slugs = [entry.get('slug') for entry in series_list]
    collection_slugs = [entry.get('slug') for entry in collections_list if isinstance(entry, dict)]

    for work_id, count in Counter(work_ids).items():
        if work_id and count > 1:
            errors.append(f"Duplicate work id '{work_id}' found in content/works/")

    for slug, count in Counter(series_slugs).items():
        if slug and count > 1:
            errors.append(f"Duplicate series slug '{slug}' found in content/series/")

    for slug, count in Counter(collection_slugs).items():
        if slug and count > 1:
            errors.append(f"Duplicate collection slug '{slug}' found in content/collections/")

    work_id_set = {work_id for work_id in work_ids if isinstance(work_id, str)}
    published_work_id_set = {
        entry.get('id')
        for entry in works
        if isinstance(entry.get('id'), str) and entry.get('published', True) is not False
    }
    series_slug_set = {slug for slug in series_slugs if isinstance(slug, str)}
    resource_entries = resources.get('downloads', []) if isinstance(resources.get('downloads', []), list) else []
    resource_ids = [str(item.get('id') or '').strip() for item in resource_entries if isinstance(item, dict)]
    resource_id_set = {item for item in resource_ids if item}

    for collection in collections_list:
        if not isinstance(collection, dict):
            continue
        collection_slug = str(collection.get('slug') or '<missing-slug>').strip()
        for slug in collection.get('series_slugs', []) or []:
            if slug not in series_slug_set:
                errors.append(f"Collection '{collection_slug}' references missing series slug '{slug}'")
        feature_work_id = str(collection.get('feature_work_id') or collection.get('cover_work_id') or '').strip()
        if feature_work_id and feature_work_id not in work_id_set:
            errors.append(f"Collection '{collection_slug}' references missing feature_work_id '{feature_work_id}'")

    for resource_id, count in Counter(resource_ids).items():
        if resource_id and count > 1:
            errors.append(f"Duplicate resource id '{resource_id}' found in content/resources.yaml")

    render_name_map: dict[str, str] = {}
    for entry in works:
        work_id = entry.get('id')
        if not isinstance(work_id, str) or not work_id.strip():
            continue
        image_value = entry.get('image')
        if isinstance(image_value, dict):
            render_name = str(image_value.get('render_name') or work_id).strip().replace(chr(92), '/')
        else:
            render_name = str(entry.get('render_name') or work_id).strip().replace(chr(92), '/')
        if not render_name:
            errors.append(f"Work '{work_id}' resolves to an empty render_name")
            continue
        previous = render_name_map.get(render_name)
        if previous and previous != work_id:
            errors.append(
                f"Works '{previous}' and '{work_id}' resolve to the same responsive render_name '{render_name}'"
            )
        render_name_map[render_name] = work_id

    private_series_slugs: set[str] = set()
    for series in series_list:
        if series.get('published', True) is False:
            continue

        slug = str(series.get('slug', '<missing-slug>'))
        visibility = str(series.get('visibility') or 'public').strip().lower()
        if visibility == 'private':
            private_series_slugs.add(slug)

        seen_in_series: set[str] = set()
        resolved_work_ids: list[str] = []
        for work_id in series.get('work_ids', []):
            if work_id not in work_id_set:
                errors.append(f"Series '{slug}' references missing work id '{work_id}'")
                continue
            if work_id not in published_work_id_set:
                # Keep unpublished works in editorial series structure without blocking the public build.
                continue
            if work_id in seen_in_series:
                errors.append(f"Series '{slug}' repeats work id '{work_id}'")
                continue
            seen_in_series.add(work_id)
            resolved_work_ids.append(work_id)

        cover_work_id = series.get('cover_work_id')
        if cover_work_id:
            if cover_work_id not in work_id_set:
                errors.append(f"Series '{slug}' has missing cover_work_id '{cover_work_id}'")
            elif cover_work_id in published_work_id_set and cover_work_id not in resolved_work_ids:
                errors.append(f"Series '{slug}' cover_work_id '{cover_work_id}' is not included in work_ids")

        # Allow editorial draft/unpublished works to remain attached to a series without blocking public build.

        for resource_id in series.get('download_ids', []) or []:
            if resource_id and resource_id not in resource_id_set:
                errors.append(f"Series '{slug}' references missing download id '{resource_id}'")

    pages = content.get('pages', {})
    home = pages.get('home', {})
    hero = home.get('hero', {})
    hero_work_id = hero.get('feature_work_id')
    if hero_work_id and hero_work_id not in work_id_set:
        errors.append(f"Home hero feature_work_id '{hero_work_id}' does not exist in content/works/")
    elif hero_work_id and hero_work_id not in published_work_id_set:
        errors.append(f"Home hero feature_work_id '{hero_work_id}' must reference a published work")

    featured_series = home.get('featured_series', {}).get('series_slugs', [])
    for slug in featured_series:
        if slug not in series_slug_set:
            errors.append(f"Home featured series references missing slug '{slug}'")
        elif slug in private_series_slugs:
            errors.append(f"Home featured series references private slug '{slug}'. Keep private series out of public homepage modules.")

    selected_works = home.get('selected_works', {}).get('work_ids', [])
    private_work_ids = {
        work_id
        for series in series_list
        if str(series.get('visibility') or 'public').strip().lower() == 'private'
        for work_id in (series.get('work_ids', []) or [])
    }
    for work_id in selected_works:
        if work_id not in work_id_set:
            errors.append(f"Home selected works references missing id '{work_id}'")
        elif work_id not in published_work_id_set:
            errors.append(f"Home selected works references unpublished id '{work_id}'")
        elif work_id in private_work_ids:
            errors.append(f"Home selected works references private work '{work_id}'. Keep private review material out of public homepage modules.")

    for entry in works:
        work_id = entry.get('id')
        if work_id not in published_work_id_set:
            continue
        alt_text = str(entry.get('alt') or '').strip()
        title_text = str(entry.get('title') or '').strip()
        work_path = f"content/works/{work_id}.yaml" if work_id else "content/works/<unknown>.yaml"
        if len(alt_text.split()) < 5 or len(alt_text) < 24:
            errors.append(
                f"Work '{work_id}' ({work_path}) needs a more descriptive alt text with at least 5 words. "
                "Fix it in Works tab → Alt text, or set the work to Draft/Review until final metadata is ready."
            )
        elif title_text and alt_text.casefold() == title_text.casefold():
            errors.append(
                f"Work '{work_id}' ({work_path}) alt text should describe the photograph, not repeat the title."
            )

    referenced_in_series: set[str] = set()
    for series in series_list:
        if series.get('published', True) is False:
            continue
        published_ids_in_series = [work_id for work_id in (series.get('work_ids', []) or []) if work_id in published_work_id_set]
        cover_work_id = series.get('cover_work_id')
        if published_ids_in_series and not cover_work_id:
            errors.append(f"Series '{series.get('slug', '<missing-slug>')}' needs a cover_work_id")
        for work_id in published_ids_in_series:
            referenced_in_series.add(work_id)

    for work_id in sorted(published_work_id_set - referenced_in_series):
        errors.append(f"Published work '{work_id}' is not attached to any published series")

    site = content.get('site', {}) if isinstance(content.get('site'), dict) else {}
    site_url = str(site.get('site_url') or '').strip()
    allow_indexing = bool(site.get('allow_indexing', False))
    if site_url and not re.match(r'^https?://[^\s]+$', site_url):
        errors.append('site.site_url must be a full URL starting with http:// or https://')
    if allow_indexing and not site_url:
        errors.append('site.allow_indexing cannot be true until site.site_url is configured')
    if allow_indexing and site_url:
        host = (urlparse(site_url).hostname or '').casefold()
        if host in {'localhost', '127.0.0.1', '0.0.0.0'} or host.endswith('.local'):
            errors.append('site.allow_indexing cannot be true while site.site_url points to a local preview host')

    for module in home.get('modules', []):
        if module.get('type') == 'work_spotlight':
            work_id = module.get('work_id')
            if work_id and work_id not in work_id_set:
                errors.append(f"Home work_spotlight module references missing id '{work_id}'")
            elif work_id and work_id not in published_work_id_set:
                errors.append(f"Home work_spotlight module references unpublished id '{work_id}'")
            elif work_id and work_id in private_work_ids:
                errors.append(f"Home work_spotlight module references private id '{work_id}'")

    page_keys = set(pages.keys())
    for item in content.get('navigation', []):
        page = item.get('page')
        if isinstance(page, str) and page and page not in page_keys:
            errors.append(f"Navigation item '{item.get('label', page)}' points to missing page '{page}'")

    for resource in resource_entries:
        if not isinstance(resource, dict):
            continue
        resource_id = str(resource.get('id') or '<missing-id>').strip()
        file_path = str(resource.get('file') or '').strip()
        if not file_path:
            errors.append(f"Resource '{resource_id}' needs a file path")
        elif file_path.startswith('/') and not (ROOT / file_path.lstrip('/')).exists():
            errors.append(f"Resource '{resource_id}' points to a missing file '{file_path}'")

    production_backend = str(release.get('production_backend') or '').strip()
    if production_backend and production_backend not in {'github', 'git-gateway'}:
        errors.append("release.production_backend must be 'github' or 'git-gateway'")
    if production_backend == 'github' and not str(release.get('repo') or '').strip():
        errors.append('release.repo is required when release.production_backend is github')

    return errors

def validate_site_content(content: dict[str, Any]) -> None:
    errors = [*validate_schema(content), *validate_relationships(content)]
    if errors:
        bullet_list = '\n'.join(f'- {message}' for message in errors)
        raise ValueError(f'Content validation failed:\n{bullet_list}')

def normalize_responsive_widths(raw_widths: Any) -> list[int]:
    widths: list[int] = []
    for value in raw_widths or []:
        try:
            width = int(value)
        except (TypeError, ValueError):
            continue
        if width > 0:
            widths.append(width)
    widths = sorted(set(widths))
    return widths or list(DEFAULT_IMAGE_PIPELINE['widths'])


SITE_CONTENT = load_site_content()
IMAGE_PIPELINE = {**DEFAULT_IMAGE_PIPELINE, **SITE_CONTENT.get('image_pipeline', {})}
RESPONSIVE_WIDTHS = normalize_responsive_widths(IMAGE_PIPELINE.get('widths'))
IMAGE_PIPELINE['widths'] = RESPONSIVE_WIDTHS


def build_work_to_series_lookup(content: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for series_entry in content.get('series', []):
        slug = str(series_entry.get('slug') or '').strip()
        if not slug:
            continue
        for work_id in series_entry.get('work_ids', []) or []:
            work_text = str(work_id or '').strip()
            if work_text:
                lookup[work_text] = slug
    return lookup


WORK_TO_SERIES_SLUG = build_work_to_series_lookup(SITE_CONTENT)


def resolve_series_slug_for_work(work_entry: dict[str, Any]) -> str:
    work_id = str(work_entry.get('id') or '').strip()
    return str(work_entry.get('series') or WORK_TO_SERIES_SLUG.get(work_id) or '').strip()


def configured_source_root() -> Path:
    return ROOT / str(IMAGE_PIPELINE.get('source_dir') or DEFAULT_IMAGE_PIPELINE['source_dir'])


def legacy_originals_root() -> Path:
    return ROOT / 'assets/images/originals'


def legacy_series_originals_root() -> Path:
    return legacy_originals_root() / 'series'


def unassigned_originals_root() -> Path:
    return legacy_originals_root() / 'unassigned'


def current_generated_root() -> Path:
    generated_dir = str(IMAGE_PIPELINE.get('generated_dir') or IMAGE_PIPELINE.get('responsive_dir') or DEFAULT_IMAGE_PIPELINE['generated_dir'])
    return ROOT / generated_dir


def legacy_generated_root() -> Path:
    return ROOT / str(IMAGE_PIPELINE.get('responsive_dir') or DEFAULT_IMAGE_PIPELINE['responsive_dir'])


def current_manifest_root() -> Path:
    return ROOT / str(IMAGE_PIPELINE.get('manifest_dir') or DEFAULT_IMAGE_PIPELINE['manifest_dir'])


def path_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def configured_source_roots(series_slug: str | None = None) -> list[Path]:
    candidates: list[Path] = []
    source_root = configured_source_root()
    if series_slug:
        candidates.extend([
            source_root / series_slug,
            legacy_series_originals_root() / series_slug,
        ])
    candidates.extend([
        source_root,
        legacy_originals_root(),
        unassigned_originals_root(),
        ROOT / 'assets/images',
    ])

    resolved: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(candidate)
    return resolved


def default_focal_point_config() -> dict[str, int]:
    pipeline_default = IMAGE_PIPELINE.get('default_focal_point') if isinstance(IMAGE_PIPELINE.get('default_focal_point'), dict) else {}
    fallback_default = DEFAULT_IMAGE_PIPELINE.get('default_focal_point') if isinstance(DEFAULT_IMAGE_PIPELINE.get('default_focal_point'), dict) else {}
    return {
        'x': clamp_percentage(pipeline_default.get('x'), int(fallback_default.get('x', 50))),
        'y': clamp_percentage(pipeline_default.get('y'), int(fallback_default.get('y', 50))),
    }


def normalize_base_url(value: Any) -> str:
    text_value = str(value or '').strip()
    if not text_value:
        return ''
    return text_value.rstrip('/') + '/'


def is_local_preview_url(value: Any) -> bool:
    base_url = str(value or '').strip()
    if not base_url:
        return True
    parsed = urlparse(base_url)
    host = (parsed.hostname or '').casefold()
    return host in {'localhost', '127.0.0.1', '0.0.0.0'} or host.endswith('.local')


PLACEHOLDER_TOKENS = (
    'example.com',
    'your-email@',
    'your-handle',
    'your-user/',
    'replace this',
    'placeholder',
    'your-domain',
)


def looks_like_placeholder(value: Any) -> bool:
    text_value = str(value or '').strip().casefold()
    if not text_value:
        return True
    return any(token in text_value for token in PLACEHOLDER_TOKENS)


def is_real_public_url(value: Any) -> bool:
    text_value = str(value or '').strip()
    if not text_value or looks_like_placeholder(text_value):
        return False
    parsed = urlparse(text_value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        return False
    if is_local_preview_url(text_value):
        return False
    return True


def is_real_contact_email(value: Any) -> bool:
    text_value = str(value or '').strip()
    if not text_value or looks_like_placeholder(text_value):
        return False
    return bool(re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', text_value))


def has_public_contact_email(value: Any) -> bool:
    return is_real_contact_email(value)


def has_public_profile_url(value: Any) -> bool:
    return is_real_public_url(value)


def is_stage_contact_optional(environment: str) -> bool:
    return environment in {'local', 'staging'}


def is_real_repo(value: Any) -> bool:
    text_value = str(value or '').strip()
    if not text_value or looks_like_placeholder(text_value):
        return False
    return '/' in text_value and len(text_value.split('/', 1)[0]) > 1 and len(text_value.split('/', 1)[1]) > 1


def build_site_settings(raw_site: dict[str, Any]) -> dict[str, Any]:
    explicit_site_url = normalize_base_url(raw_site.get('site_url'))
    display_url = normalize_base_url(raw_site.get('display_url') or explicit_site_url or 'http://127.0.0.1:8000/')
    environment = str(raw_site.get('environment') or ('local' if is_local_preview_url(display_url) else 'production')).strip().lower()
    allow_indexing = bool(raw_site.get('allow_indexing', False)) and not is_local_preview_url(explicit_site_url or display_url)
    metadata_base_url = explicit_site_url or display_url
    robots = 'index,follow,max-image-preview:large' if allow_indexing else 'noindex,nofollow,max-image-preview:large'
    return {
        'siteUrl': explicit_site_url,
        'displayUrl': display_url,
        'metadataBaseUrl': metadata_base_url,
        'environment': environment,
        'allowIndexing': allow_indexing,
        'robots': robots,
        'isLocalPreview': is_local_preview_url(metadata_base_url),
    }


def absolute_url(path: str, base_url: str) -> str:
    if path.startswith('http://') or path.startswith('https://'):
        return path
    return normalize_base_url(base_url) + path.lstrip('/')


def page_output_path(page_key: str) -> str:
    return 'index.html' if page_key == 'home' else f'{page_key}.html'


def build_page_url(page_key: str, raw_site: dict[str, Any]) -> str:
    settings = build_site_settings(raw_site)
    if page_key == 'home':
        return normalize_base_url(settings['metadataBaseUrl'])
    return absolute_url(page_output_path(page_key), settings['metadataBaseUrl'])


def validate_runtime_store(store: dict[str, Any]) -> None:
    errors: list[str] = []
    warnings: list[str] = []
    site = store['raw'].get('site', {})
    resources = store['raw'].get('resources', {}) if isinstance(store['raw'].get('resources'), dict) else {}
    release = store.get('release_settings', {})
    og_image = str(site.get('og_image') or '').strip()
    if og_image:
        og_path = ROOT / og_image.lstrip('/')
        if not og_path.exists():
            warnings.append(f"Site og_image '{og_image}' does not exist")

    pages = store['raw'].get('pages', {}) if isinstance(store['raw'].get('pages'), dict) else {}
    for page_key, page in pages.items():
        if not isinstance(page, dict):
            continue
        meta = page.get('meta', {}) if isinstance(page.get('meta'), dict) else {}
        page_og_image = str(meta.get('og_image') or '').strip()
        if page_og_image:
            page_og_path = ROOT / page_og_image.lstrip('/')
            if not page_og_path.exists():
                warnings.append(f"Page og_image '{page_og_image}' does not exist for '{page_key}'")

    minimum_lead_dimension = 1200
    minimum_series_cover_dimension = 800
    hero_work_id = store['raw'].get('pages', {}).get('home', {}).get('hero', {}).get('feature_work_id')
    if hero_work_id:
        hero_work = store['works_by_id'].get(hero_work_id)
        if hero_work and (hero_work['width'] < minimum_lead_dimension or hero_work['height'] < minimum_lead_dimension):
            errors.append(f"Home hero work '{hero_work_id}' is too small for a lead image. Use at least {minimum_lead_dimension}px on both dimensions")

    for series in store['series_list']:
        cover_work_id = str(series.get('coverWorkId') or '').strip()
        cover_work = store['works_by_id'].get(cover_work_id)
        if not cover_work:
            continue
        is_private_series = str(series.get('visibility') or 'public').strip().lower() == 'private'
        cover_is_too_small = cover_work['width'] < minimum_series_cover_dimension or cover_work['height'] < minimum_series_cover_dimension
        if cover_is_too_small and is_private_series:
            warnings.append(
                f"Private series cover '{cover_work_id}' for '{series['slug']}' is below the public cover recommendation. "
                f"Allowed while private; replace it before publishing the series."
            )
        elif cover_is_too_small:
            warnings.append(
                f"Series cover '{cover_work_id}' for '{series['slug']}' is below the recommended public cover size. "
                f"Recommended minimum is {minimum_series_cover_dimension}px on both dimensions; build continues so the control panel does not become fragile."
            )

    for resource in resources.get('downloads', []) if isinstance(resources.get('downloads', []), list) else []:
        if not isinstance(resource, dict):
            continue
        file_path = str(resource.get('file') or '').strip()
        resource_id = str(resource.get('id') or '<missing-id>').strip()
        candidate = ROOT / file_path.lstrip('/') if file_path.startswith('/') else ROOT / file_path
        if not file_path or not candidate.exists():
            errors.append(f"Download resource '{resource_id}' points to a missing file '{file_path}'")
            continue
        if candidate.suffix.lower() != '.pdf':
            errors.append(f"Download resource '{resource_id}' must point to a PDF file")
        if candidate.stat().st_size < 2048:
            errors.append(f"Download resource '{resource_id}' is too small to be a credible public document")

    env = store['site_data']['site']['environment']
    if env in {'staging', 'production'}:
        if env == 'production' and not store['site_data']['site']['siteUrl']:
            errors.append('Production environment requires site.site_url to be configured')
        if env == 'production':
            production_url = normalize_base_url(release.get('productionUrl') or '')
            if production_url and normalize_base_url(store['site_data']['site']['siteUrl']) != production_url:
                errors.append('Site URL must match release.production_url before a production build is published')
        if release.get('productionBackend') == 'github' and not release.get('repo'):
            errors.append('Release profile needs release.repo before a production release can be generated')

    for message in warnings:
        print(f"[STILLMRK build] Warning: {message}", flush=True)

    if errors:
        bullet_list = '\n'.join(f'- {message}' for message in errors)
        raise ValueError(f'Content validation failed:\n{bullet_list}')

_MD_STRONG = re.compile(r'\*\*(?=\S)(.+?)(?<=\S)\*\*')
_MD_EM = re.compile(r'(?<![\w*])[*_](?=\S)(.+?)(?<=\S)[*_](?![\w*])')


def md_inline(value: Any) -> str:
    """Escape text, then render **strong** and *emphasis* (used for play titles)."""
    text = esc(value)
    text = _MD_STRONG.sub(r'<strong>\1</strong>', text)
    return _MD_EM.sub(r'<em>\1</em>', text)


RAW_CAPTIONS: dict[str, str] = {}
RAW_SERIES_TEXT: dict[str, dict[str, str]] = {}


def md_plain(value: Any) -> str:
    """Strip markdown emphasis markers for meta tags and plain-text contexts."""
    text = _MD_STRONG.sub(r'\1', str(value or ''))
    return _MD_EM.sub(r'\1', text).strip()


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def relative_asset_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def resolve_image_definition(work_entry: dict[str, Any]) -> dict[str, Any]:
    image_value = work_entry.get("image")
    if image_value is None:
        resolved = {"source": None}
    elif isinstance(image_value, str):
        resolved = {"source": image_value}
    elif isinstance(image_value, dict):
        resolved = dict(image_value)
    else:
        raise TypeError(f"Unsupported image definition for work '{work_entry['id']}'")

    if resolved.get('master') and not resolved.get('source'):
        resolved['source'] = resolved['master']

    root_render_name = str(work_entry.get('render_name') or '').strip()
    if root_render_name and not resolved.get('render_name'):
        resolved['render_name'] = root_render_name

    if 'series' not in resolved:
        series_slug = resolve_series_slug_for_work(work_entry)
        if series_slug:
            resolved['series'] = series_slug

    if 'force_rebuild' not in resolved and work_entry.get('force_rebuild') is not None:
        resolved['force_rebuild'] = bool(work_entry.get('force_rebuild'))

    return resolved


def infer_source_path(work_id: str, series_slug: str | None = None) -> Path | None:
    for root_path in configured_source_roots(series_slug):
        for ext in SOURCE_EXTENSIONS:
            candidate = root_path / f"{work_id}{ext}"
            if candidate.exists():
                return candidate
    return None


def _source_stems_for_work_entry(work_entry: dict[str, Any], image_config: dict[str, Any]) -> list[str]:
    ordered: list[str] = []

    def add(value: Any) -> None:
        stem = Path(str(value or '').strip().replace('\\', '/')).stem.strip()
        if stem and stem not in ordered:
            ordered.append(stem)

    add(work_entry.get('id'))
    add(work_entry.get('render_name'))
    add(image_config.get('render_name'))
    add(image_config.get('master'))
    add(image_config.get('source'))
    add(image_config.get('original'))
    return ordered


def infer_source_path_from_work_entry(work_entry: dict[str, Any], image_config: dict[str, Any], series_slug: str | None = None) -> Path | None:
    for stem in _source_stems_for_work_entry(work_entry, image_config):
        inferred = infer_source_path(stem, series_slug)
        if inferred:
            return inferred
    return None


def infer_source_path_anywhere(work_id: str) -> Path | None:
    search_roots = [configured_source_root(), legacy_originals_root()]
    seen: set[str] = set()
    for root_path in search_roots:
        if not root_path.exists():
            continue
        root_key = str(root_path.resolve())
        if root_key in seen:
            continue
        seen.add(root_key)
        for ext in SOURCE_EXTENSIONS:
            matches = sorted(root_path.rglob(f"{work_id}{ext}"))
            if matches:
                return matches[0]
    return None


def infer_requested_name_anywhere(source_value: str) -> Path | None:
    requested = Path(str(source_value).strip().replace('\\', '/'))
    stem = requested.stem
    if not stem:
        return None
    direct_ext = requested.suffix.lower()
    ordered_exts = [direct_ext] if direct_ext in SOURCE_EXTENSIONS else []
    ordered_exts.extend(ext for ext in SOURCE_EXTENSIONS if ext not in ordered_exts)
    search_roots = [configured_source_root(), legacy_originals_root()]
    seen: set[str] = set()
    for root_path in search_roots:
        if not root_path.exists():
            continue
        root_key = str(root_path.resolve())
        if root_key in seen:
            continue
        seen.add(root_key)
        for ext in ordered_exts:
            matches = sorted(root_path.rglob(f"{stem}{ext}"))
            if matches:
                return matches[0]
    return None


def resolve_source_path(work_entry: dict[str, Any], image_config: dict[str, Any]) -> Path:
    source_value = image_config.get("source") or image_config.get("original") or image_config.get("master")
    series_slug = str(image_config.get('series') or resolve_series_slug_for_work(work_entry) or '').strip() or None
    candidates: list[Path] = []
    canonical_originals = configured_source_root()
    source_roots = configured_source_roots(series_slug)

    if source_value:
        requested_text = str(source_value).strip().replace('\\', '/')
        requested = Path(requested_text)
        if requested_text.startswith("/"):
            candidates.append(ROOT / requested_text.lstrip("/"))
        if requested.is_absolute():
            candidates.append(requested)
        else:
            candidates.append(ROOT / requested)
            for root_path in source_roots:
                candidates.append(root_path / requested)
                candidates.append(root_path / requested.name)
            candidates.append(Path.cwd() / requested)
    else:
        inferred = infer_source_path_from_work_entry(work_entry, image_config, series_slug)
        if inferred:
            return inferred

    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    for candidate in deduped:
        if candidate.exists():
            return candidate

    inferred = infer_source_path_from_work_entry(work_entry, image_config, series_slug)
    if inferred:
        return inferred

    requested_anywhere = infer_requested_name_anywhere(str(source_value or '')) if source_value else None
    if requested_anywhere:
        return requested_anywhere

    for stem in _source_stems_for_work_entry(work_entry, image_config):
        inferred_anywhere = infer_source_path_anywhere(stem)
        if inferred_anywhere:
            return inferred_anywhere

    searched_paths = deduped[:]
    if not searched_paths:
        for root_path in configured_source_roots(series_slug):
            for ext in SOURCE_EXTENSIONS:
                searched_paths.append(root_path / f"{work_entry['id']}{ext}")
    searched = ", ".join(relative_asset_path(path) if path_within(path, ROOT) else str(path) for path in searched_paths) or str(canonical_originals / f"{work_entry['id']}.jpg")
    hint = " Try restoring the source image from the Qt control panel via Publish Ops → Repair missing source images, or relink it manually from Studio / Publish Ops if the original now lives outside the project folder."
    raise FileNotFoundError(f"No source image found for work '{work_entry['id']}'. Searched: {searched}.{hint}")


def prepare_source_image(source_path: Path) -> Image.Image:
    with Image.open(source_path) as raw_image:
        image = ImageOps.exif_transpose(raw_image)

        if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background

        if image.mode != "RGB":
            return image.convert("RGB")

        return image.copy()


def _record_missing_asset(work_entry: dict[str, Any], series_slug: str, render_name: str, detail: str) -> None:
    work_id = str(work_entry.get('id') or '').strip()
    if not work_id:
        return
    row = {
        'id': work_id,
        'series': series_slug,
        'renderName': render_name,
        'detail': detail,
    }
    if not any(existing.get('id') == work_id for existing in BUILD_MISSING_ASSET_ROWS):
        BUILD_MISSING_ASSET_ROWS.append(row)


def clamp_percentage(value: Any, fallback: int = 50) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    return max(0, min(100, number))


def derive_orientation(width: int, height: int) -> str:
    ratio = (width or 1) / (height or 1)
    if ratio > 1.12:
        return 'landscape'
    if ratio < 0.88:
        return 'portrait'
    return 'square'


def derivative_inventory_for_work(work: dict[str, Any]) -> list[dict[str, Any]]:
    responsive_base = str(work.get('responsiveBase') or '').strip()
    if not responsive_base:
        return []

    inventory: list[dict[str, Any]] = []
    for width in available_widths(work):
        for extension in ('jpg', 'webp'):
            relative_path = f"{responsive_base}-{width}.{extension}"
            candidate = ROOT / relative_path
            inventory.append({
                'format': extension,
                'width': width,
                'path': relative_path,
                'exists': candidate.exists(),
                'sizeBytes': candidate.stat().st_size if candidate.exists() else 0,
            })
    return inventory


def slugify_label(value: Any, fallback: str = 'item') -> str:
    text_value = re.sub(r'[^a-z0-9]+', '-', str(value or '').strip().lower()).strip('-')
    return text_value or fallback


def normalize_download_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': str(entry.get('id') or slugify_label(entry.get('title') or 'download')).strip(),
        'title': str(entry.get('title') or 'Download').strip(),
        'description': str(entry.get('description') or '').strip(),
        'file': str(entry.get('file') or '').strip(),
        'kind': str(entry.get('kind') or 'press').strip(),
        'audience': str(entry.get('audience') or 'public').strip(),
        'featured': bool(entry.get('featured', False)),
    }


def build_release_settings(raw_release: dict[str, Any]) -> dict[str, Any]:
    release = raw_release if isinstance(raw_release, dict) else {}
    return {
        'stagingUrl': normalize_base_url(release.get('staging_url') or ''),
        'productionUrl': normalize_base_url(release.get('production_url') or ''),
        'previewBranch': str(release.get('preview_branch') or 'preview').strip(),
        'productionBranch': str(release.get('production_branch') or 'main').strip(),
        'productionBackend': str(release.get('production_backend') or 'github').strip(),
        'repo': str(release.get('repo') or '').strip(),
        'commitMessageTemplate': str(release.get('commit_message_template') or 'content: {collection} - {entry}').strip(),
        'changeNoteTemplate': str(release.get('change_note_template') or 'Edited {collection}/{entry}: summarize what changed and why.').strip(),
        'requiredChecks': [str(item).strip() for item in (release.get('required_checks') or []) if str(item).strip()],
    }


def build_empty_image_meta(work_entry: dict[str, Any], image_config: dict[str, Any], detail: str = 'No image assigned') -> dict[str, Any]:
    """Return metadata for a work that intentionally has no image attached yet.

    This reset mode keeps the work card, title, caption, alt text, ordering, and
    series relationships intact without generating placeholder image files.
    """
    series_slug = str(image_config.get('series') or resolve_series_slug_for_work(work_entry) or 'unassigned').strip() or 'unassigned'
    render_slug = str(image_config.get("render_name") or work_entry.get('render_name') or work_entry.get("id") or 'work').strip().replace("\\", "/").strip("/")
    render_name = render_slug.replace('/', '-') or str(work_entry.get("id") or 'work')
    width = int(work_entry.get('width') or PLACEHOLDER_INTRINSIC_SIZE[0])
    height = int(work_entry.get('height') or PLACEHOLDER_INTRINSIC_SIZE[1])
    return {
        "width": width,
        "height": height,
        "src": "",
        "responsiveBase": "",
        "sourceOriginal": "",
        "renderName": render_name,
        "seriesSlug": series_slug,
        "missingSource": True,
        "missingSourceDetail": detail,
        "imagePending": True,
    }


IMAGE_STATS = {'rendered': 0, 'cached': 0}
_EXIF_ORIENTATION_TAG = 274
_ROTATED_ORIENTATIONS = {5, 6, 7, 8}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def source_dimensions(source_path: Path) -> tuple[int, int]:
    """Return the displayed size of a source image from its header only.

    Opening a file with Pillow reads the header lazily, so this costs
    milliseconds instead of a full decode. EXIF rotation is applied to the
    reported size so it matches what prepare_source_image() produces.
    """
    with Image.open(source_path) as image:
        width, height = image.size
        try:
            orientation = image.getexif().get(_EXIF_ORIENTATION_TAG)
        except Exception:
            orientation = None
    if orientation in _ROTATED_ORIENTATIONS:
        return height, width
    return width, height


# Public derivatives never exceed this width. Larger files add weight but no
# visible detail on any screen, and they hand out near-original resolution.
MAX_DERIVATIVE_WIDTH = 2560
# AVIF is ~30% smaller than WebP at the same quality but slow to encode, so it
# is produced for the widths browsers actually request in grids and heroes.
AVIF_MAX_WIDTH = 1600
AVIF_ENABLED = bool(pil_features.check('avif'))


def derivative_widths(intrinsic_width: int) -> list[int]:
    top = min(int(intrinsic_width), MAX_DERIVATIVE_WIDTH)
    widths = [width for width in RESPONSIVE_WIDTHS if width < top]
    widths.append(top)
    return sorted(set(int(width) for width in widths))


def avif_widths_for(widths: list[int]) -> list[int]:
    return [width for width in widths if width <= AVIF_MAX_WIDTH] if AVIF_ENABLED else []


def ensure_responsive_assets(work_entry: dict[str, Any], generated_assets: set[str]) -> dict[str, Any]:
    image_config = resolve_image_definition(work_entry)
    explicit_source = str(image_config.get("source") or image_config.get("original") or image_config.get("master") or "").strip()
    series_slug = str(image_config.get('series') or resolve_series_slug_for_work(work_entry) or '').strip() or None

    # If a work has no explicit image and no matching source file exists, keep the
    # card as metadata-only. Do not generate artificial placeholder image files.
    if not explicit_source and infer_source_path_from_work_entry(work_entry, image_config, series_slug) is None:
        return build_empty_image_meta(work_entry, image_config)

    try:
        source_path = resolve_source_path(work_entry, image_config)
    except FileNotFoundError as exc:
        # A missing image should be visible as a pending state, not silently replaced
        # by generated placeholder media. This keeps image folders genuinely empty
        # until the real source image is attached.
        _record_missing_asset(
            work_entry,
            str(image_config.get('series') or resolve_series_slug_for_work(work_entry) or 'unassigned'),
            str(image_config.get('render_name') or work_entry.get('render_name') or work_entry.get('id') or ''),
            str(exc),
        )
        return build_empty_image_meta(work_entry, image_config, str(exc))

    series_slug = str(image_config.get('series') or resolve_series_slug_for_work(work_entry) or 'unassigned').strip() or 'unassigned'
    render_slug = str(image_config.get("render_name") or work_entry.get('render_name') or work_entry["id"]).strip().replace("\\", "/").strip("/")
    render_name = render_slug.replace('/', '-') or work_entry['id']
    work_output_dir = current_generated_root() / series_slug / render_name
    responsive_base_path = work_output_dir / render_name
    stamp_path = work_output_dir / IMAGE_STAMP_NAME
    previous = _read_json(stamp_path) or {}
    source_stat = source_path.stat()
    same_file = (
        previous.get('source') == relative_asset_path(source_path)
        and previous.get('source_size') == source_stat.st_size
        and previous.get('source_mtime_ns') == source_stat.st_mtime_ns
    )
    # Reading dimensions (and EXIF orientation) can force a full decode for
    # PNGs, so unchanged files reuse the size recorded at the last render.
    if same_file and isinstance(previous.get('width'), int) and isinstance(previous.get('height'), int):
        intrinsic_width, intrinsic_height = previous['width'], previous['height']
    else:
        intrinsic_width, intrinsic_height = source_dimensions(source_path)
    target_widths = derivative_widths(intrinsic_width)

    jpg_quality = int(IMAGE_PIPELINE.get("jpg_quality", DEFAULT_IMAGE_PIPELINE["jpg_quality"]))
    webp_quality = int(IMAGE_PIPELINE.get("webp_quality", DEFAULT_IMAGE_PIPELINE["webp_quality"]))
    avif_quality = int(IMAGE_PIPELINE.get("avif_quality", 55))
    force_rebuild = bool(image_config.get("force_rebuild", False))
    avif_target_widths = avif_widths_for(target_widths)
    planned = [(width, 'jpg') for width in target_widths] + [(width, 'webp') for width in target_widths] + [(width, 'avif') for width in avif_target_widths]

    stamp = {
        'source': relative_asset_path(source_path),
        'source_size': source_stat.st_size,
        'source_mtime_ns': source_stat.st_mtime_ns,
        'jpg_quality': jpg_quality,
        'webp_quality': webp_quality,
        'avif_quality': avif_quality,
    }
    same_source = not force_rebuild and all(previous.get(key) == value for key, value in stamp.items())
    # Same source and settings: only render files that are missing (for
    # example when a new format or width is introduced). Otherwise re-render all.
    todo = [(w, ext) for w, ext in planned if not same_source or not (work_output_dir / f"{render_name}-{w}.{ext}").exists()]

    if IMAGE_MODE == 'build' and todo:
        prepared = prepare_source_image(source_path)
        work_output_dir.mkdir(parents=True, exist_ok=True)
        variants: dict[int, Image.Image] = {}
        for width, ext in todo:
            variant = variants.get(width)
            if variant is None:
                if width == intrinsic_width:
                    variant = prepared
                else:
                    height = max(1, round(intrinsic_height * width / intrinsic_width))
                    variant = prepared.resize((width, height), Image.Resampling.LANCZOS)
                variants[width] = variant
            target = work_output_dir / f"{render_name}-{width}.{ext}"
            if ext == 'jpg':
                variant.save(target, format="JPEG", quality=jpg_quality, optimize=True, progressive=True)
            elif ext == 'webp':
                variant.save(target, format="WEBP", quality=webp_quality, method=6)
            else:
                variant.save(target, format="AVIF", quality=avif_quality, speed=6)
        IMAGE_STATS['rendered'] += 1
    else:
        IMAGE_STATS['cached'] += 1
    if IMAGE_MODE == 'build' and (todo or previous.get('width') != intrinsic_width or previous.get('height') != intrinsic_height):
        work_output_dir.mkdir(parents=True, exist_ok=True)
        stamp_path.write_text(json.dumps({**stamp, 'width': intrinsic_width, 'height': intrinsic_height}, indent=2) + "\n", encoding='utf-8')

    for width, ext in planned:
        generated_assets.add(relative_asset_path(work_output_dir / f"{render_name}-{width}.{ext}"))

    largest_width = target_widths[-1]
    largest_jpg = work_output_dir / f"{render_name}-{largest_width}.jpg"

    return {
        "width": intrinsic_width,
        "height": intrinsic_height,
        "src": relative_asset_path(largest_jpg),
        "responsiveBase": relative_asset_path(responsive_base_path),
        "sourceOriginal": relative_asset_path(source_path),
        "renderName": render_name,
        "seriesSlug": series_slug,
        "imagePending": False,
        "avifWidths": avif_target_widths,
    }

def normalize_ratio_value(value: Any, fallback: str) -> str:
    text_value = str(value or '').strip()
    return text_value if re.fullmatch(r'\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?', text_value) else fallback


def derive_display_ratios(entry: dict[str, Any], width: int, height: int) -> dict[str, str]:
    intrinsic = f"{width} / {height}"
    nested = entry.get('display_ratios') if isinstance(entry.get('display_ratios'), dict) else {}
    base_source = nested.get('default') or entry.get('display_ratio')
    base_ratio = normalize_ratio_value(base_source, intrinsic)
    base_has_override = bool(str(base_source or '').strip())
    return {
        'default': base_ratio,
        'hero': normalize_ratio_value(nested.get('hero') or entry.get('hero_ratio'), base_ratio if base_has_override else intrinsic),
        'cover': normalize_ratio_value(nested.get('cover') or entry.get('cover_ratio'), base_ratio if base_has_override else intrinsic),
        'about': normalize_ratio_value(nested.get('about') or entry.get('about_ratio'), base_ratio if base_has_override else intrinsic),
        'portfolio': normalize_ratio_value(nested.get('portfolio') or entry.get('portfolio_ratio'), base_ratio if base_has_override else intrinsic),
        'series': normalize_ratio_value(nested.get('series') or entry.get('series_ratio'), base_ratio if base_has_override else intrinsic),
    }


def derive_display_layouts(entry: dict[str, Any]) -> dict[str, str]:
    nested = entry.get('display_layouts') if isinstance(entry.get('display_layouts'), dict) else {}
    return {
        'portfolio': normalize_layout_token(nested.get('portfolio') or entry.get('portfolio_layout') or entry.get('portfolioLayout'), 'auto'),
        'series': normalize_layout_token(nested.get('series') or entry.get('series_layout') or entry.get('seriesLayout'), 'auto'),
    }


def normalize_content(raw: dict[str, Any]) -> dict[str, Any]:
    BUILD_MISSING_ASSET_ROWS.clear()
    works_raw = raw["works"]
    series_raw = raw["series"]
    collections_raw = raw.get("collections", []) if isinstance(raw.get("collections", []), list) else []
    generated_assets: set[str] = set()
    downloads_raw = raw.get('resources', {}).get('downloads', []) if isinstance(raw.get('resources', {}), dict) else []
    downloads = [normalize_download_entry(entry) for entry in downloads_raw if isinstance(entry, dict)]
    downloads_by_id = {entry['id']: entry for entry in downloads}
    public_downloads = [entry for entry in downloads if str(entry.get('audience') or 'public').strip().lower() in {'public', 'press'}]

    raw_works_by_id = {str(entry.get("id") or "").strip(): entry for entry in works_raw if str(entry.get("id") or "").strip()}
    published_works = [entry for entry in works_raw if entry.get("published", True) is not False]
    published_total = len(published_works)

    works_by_id: dict[str, dict[str, Any]] = {}
    for published_index, entry in enumerate(published_works, start=1):
        print(f"[STILLMRK build] Processing work {published_index} / {published_total}: {entry.get('id', 'unknown')}", flush=True)

        image_meta = ensure_responsive_assets(entry, generated_assets)
        RAW_CAPTIONS[str(entry["id"])] = str(entry.get('caption') or '').strip()

        focal_point = entry.get('focal_point') if isinstance(entry.get('focal_point'), dict) else {}
        default_focal_point = default_focal_point_config()
        width_value = int(image_meta["width"])
        height_value = int(image_meta["height"])
        works_by_id[entry["id"]] = {
            "id": entry["id"],
            "title": entry["title"],
            "year": entry["year"],
            "location": entry["location"],
            "alt": entry["alt"],
            # Plain text everywhere text is set as text (lightbox, summaries,
            # meta tags); caption_html() renders *emphasis* where HTML is built.
            "caption": md_plain(entry.get('caption')),
            "medium": str(entry.get('medium') or '').strip(),
            "edition": str(entry.get('edition') or '').strip(),
            "paletteTone": str(entry.get('palette_tone') or '').strip(),
            "projectType": str(entry.get('project_type') or '').strip(),
            "licensingAvailable": bool(entry.get('licensing_available', False)),
            "priceNote": str(entry.get('price_note') or '').strip(),
            "printAvailable": bool(entry.get('print_available', False)),
            "heroSafe": bool(entry.get('hero_safe', False)),
            "gridSafe": bool(entry.get('grid_safe', True)),
            "socialSafe": bool(entry.get('social_safe', False)),
            "renderName": str(image_meta.get("renderName") or entry.get('render_name') or entry["id"]).strip(),
            "missingSource": bool(image_meta.get('missingSource', False)),
            "missingSourceDetail": str(image_meta.get('missingSourceDetail') or '').strip(),
            "tags": entry.get("tags", []),
            "width": width_value,
            "height": height_value,
            "orientation": derive_orientation(width_value, height_value),
            "displayRatios": derive_display_ratios(entry, width_value, height_value),
            "displayLayouts": derive_display_layouts(entry),
            "portfolioLayout": normalize_layout_token(entry.get('portfolio_layout') or entry.get('portfolioLayout'), 'auto'),
            "seriesLayout": normalize_layout_token(entry.get('series_layout') or entry.get('seriesLayout'), 'auto'),
            "focalPoint": {
                "x": clamp_percentage(focal_point.get('x'), default_focal_point['x']),
                "y": clamp_percentage(focal_point.get('y'), default_focal_point['y']),
            },
            "src": image_meta["src"],
            "responsiveBase": image_meta.get("responsiveBase"),
            "sourceOriginal": image_meta.get("sourceOriginal"),
            "imagePending": bool(image_meta.get("imagePending", False)),
            "avifWidths": list(image_meta.get("avifWidths") or []),
            "published": True,
            "declaredSeries": str(entry.get("series") or "").strip(),
        }

    series_list: list[dict[str, Any]] = []
    portfolio_works: list[dict[str, Any]] = []
    portfolio_order = 1

    for series_index, series in enumerate(series_raw, start=1):
        if series.get("published", True) is False:
            continue

        resolved_work_ids = []
        for work_index, work_id in enumerate(series.get("work_ids", []), start=1):
            work = works_by_id.get(work_id)
            if not work:
                raw_work = raw_works_by_id.get(str(work_id))
                if raw_work is not None:
                    status = str(raw_work.get('review_status') or raw_work.get('reviewStatus') or 'draft').strip() or 'draft'
                    print(f"[STILLMRK build] Warning: series '{series['slug']}' references non-public work '{work_id}' (published=false, review_status={status})")
                else:
                    print(f"[STILLMRK build] Warning: series '{series['slug']}' references missing work '{work_id}'")
                continue
            if work_id in resolved_work_ids:
                continue
            work["series"] = series["slug"]
            work["seriesOrder"] = work_index
            work["portfolioOrder"] = portfolio_order
            portfolio_order += 1
            resolved_work_ids.append(work_id)
            portfolio_works.append(work)

        # Defensive fallback: a batch import or manual edit can write a valid
        # work YAML with ``series: <slug>`` but fail to append that ID to the
        # matching series sequence. Public pages count from series.work_ids, so
        # append these relationship orphans at build time instead of hiding
        # published works. Curated order from series.work_ids still wins.
        next_series_order = len(resolved_work_ids) + 1
        for work_id, work in works_by_id.items():
            if work_id in resolved_work_ids:
                continue
            if str(work.get("declaredSeries") or "").strip() != str(series.get("slug") or "").strip():
                continue
            work["series"] = series["slug"]
            work["seriesOrder"] = next_series_order
            work["portfolioOrder"] = portfolio_order
            next_series_order += 1
            portfolio_order += 1
            resolved_work_ids.append(work_id)
            portfolio_works.append(work)

        visibility = str(series.get('visibility') or 'public').strip().lower()
        RAW_SERIES_TEXT[str(series["slug"])] = {'description': str(series.get("description") or '')}
        series_list.append(
            {
                "slug": series["slug"],
                "title": series["title"],
                "years": series["years"],
                "mood": series["mood"],
                "description": md_plain(series["description"]),
                "descriptionHtml": md_inline(series["description"]),
                "coverWorkId": (series.get("cover_work_id") if series.get("cover_work_id") in resolved_work_ids else None) or (resolved_work_ids[0] if resolved_work_ids else None),
                "cardCoverWorkId": (series.get("card_cover_work_id") if series.get("card_cover_work_id") in resolved_work_ids else None) or ((series.get("cover_work_id") if series.get("cover_work_id") in resolved_work_ids else None) or (resolved_work_ids[0] if resolved_work_ids else None)),
                "heroWorkId": (series.get("hero_work_id") if series.get("hero_work_id") in resolved_work_ids else None) or ((series.get("cover_work_id") if series.get("cover_work_id") in resolved_work_ids else None) or (resolved_work_ids[0] if resolved_work_ids else None)),
                "cardSummary": str(series.get("card_summary") or '').strip(),
                "storyOpeningText": str(series.get("story_opening_text") or '').strip(),
                "storySequenceText": str(series.get("story_sequence_text") or '').strip(),
                "storyClosingText": str(series.get("story_closing_text") or '').strip(),
                "order": series_index,
                "visibility": visibility,
                "clientName": str(series.get('client_name') or '').strip(),
                "accessNote": str(series.get('access_note') or series.get('accessNote') or '').strip(),
                # Never publish an access hash. A hash checked in the browser can
                # be brute-forced offline, so private series simply stay locked
                # on the public site. Share private work through the host instead.
                "accessHash": "",
                "reviewMode": bool(series.get('review_mode', False)),
                "allowFavorites": bool(series.get('allow_favorites', True)),
                "allowInquiryBasket": bool(series.get('allow_inquiry_basket', True)),
                "projectType": str(series.get('project_type') or '').strip(),
                "downloadIds": [str(item).strip() for item in (series.get('download_ids') or []) if str(item).strip() in downloads_by_id],
                "relatedSeriesSlugs": [str(item).strip() for item in (series.get('related_series_slugs') or []) if str(item).strip()],
                "_work_ids": resolved_work_ids,
            }
        )

    home = raw["pages"]["home"]
    featured_series_slugs = home["featured_series"]["series_slugs"]
    featured_work_ids = home["selected_works"]["work_ids"]

    series_lookup = {item["slug"]: item for item in series_list}
    private_series_slugs = {item['slug'] for item in series_list if item.get('visibility') == 'private'}
    public_series_list = [item for item in series_list if item.get('visibility') != 'private']
    public_series_lookup = {item['slug']: item for item in public_series_list}

    collection_list: list[dict[str, Any]] = []
    for collection_index, collection in enumerate(collections_raw, start=1):
        if not isinstance(collection, dict) or collection.get('published', True) is False:
            continue
        visibility = str(collection.get('visibility') or 'public').strip().lower()
        if visibility == 'private':
            continue
        collection_slug = str(collection.get('slug') or '').strip()
        if not collection_slug:
            continue
        project_type = str(collection.get('project_type') or '').strip()
        selected_slugs: list[str] = []
        seen_slugs: set[str] = set()

        def add_collection_series(slug_value: Any) -> None:
            slug_text = str(slug_value or '').strip()
            if not slug_text or slug_text in seen_slugs or slug_text not in public_series_lookup:
                return
            seen_slugs.add(slug_text)
            selected_slugs.append(slug_text)

        for slug_value in collection.get('series_slugs', []) or []:
            add_collection_series(slug_value)

        if project_type and collection.get('auto_include_project_type', True) is not False:
            for series_item in public_series_list:
                if str(series_item.get('projectType') or '').strip() == project_type:
                    add_collection_series(series_item['slug'])

        cover_work_id = str(collection.get('cover_work_id') or collection.get('feature_work_id') or '').strip()
        if cover_work_id not in works_by_id:
            cover_work_id = ''
        if not cover_work_id:
            for slug_value in selected_slugs:
                candidate = public_series_lookup.get(slug_value, {}).get('coverWorkId')
                if candidate in works_by_id:
                    cover_work_id = candidate
                    break

        work_count = sum(len(public_series_lookup[slug_value].get('_work_ids', [])) for slug_value in selected_slugs if slug_value in public_series_lookup)
        collection_list.append({
            'slug': collection_slug,
            'title': str(collection.get('title') or collection_slug).strip(),
            'eyebrow': str(collection.get('eyebrow') or 'Collection').strip(),
            'lead': str(collection.get('lead') or '').strip(),
            'description': str(collection.get('description') or '').strip(),
            'projectType': project_type,
            'coverWorkId': cover_work_id,
            'order': int(collection.get('order') or collection_index),
            'visibility': visibility,
            'seriesSlugs': selected_slugs,
            'seriesCount': len(selected_slugs),
            'workCount': work_count,
        })

    collection_lookup = {item['slug']: item for item in collection_list}

    for feature_index, slug in enumerate(featured_series_slugs, start=1):
        if slug in series_lookup:
            series_lookup[slug]["homeFeatureOrder"] = feature_index
        else:
            print(f"[STILLMRK build] Warning: homepage featured series '{slug}' not found")

    for feature_index, work_id in enumerate(featured_work_ids, start=1):
        if work_id in works_by_id:
            works_by_id[work_id]["homeFeatureOrder"] = feature_index
        else:
            print(f"[STILLMRK build] Warning: homepage selected work '{work_id}' not found")

    for work in works_by_id.values():
        work.setdefault("series", "")
        work.setdefault("seriesOrder", 9999)
        work.setdefault("portfolioOrder", 9999)
        work.setdefault("homeFeatureOrder", None)

    site_settings = build_site_settings(raw["site"])
    release_settings = build_release_settings(raw.get('release', {}))

    public_work_ids = [work_id for work_id, work in works_by_id.items() if str(work.get('series') or '').strip() not in private_series_slugs]
    public_works = [works_by_id[work_id] for work_id in public_work_ids]
    private_series_list = [
        {
            key: value
            for key, value in item.items()
            if key != "_work_ids"
        }
        for item in series_list
        if item.get('visibility') == 'private'
    ]
    private_work_ids = [work_id for work_id, work in works_by_id.items() if str(work.get('series') or '').strip() in private_series_slugs]
    private_works = [works_by_id[work_id] for work_id in private_work_ids]
    public_portfolio_works = [work for work in sorted(portfolio_works, key=lambda item: item['portfolioOrder']) if str(work.get('series') or '').strip() not in private_series_slugs]

    identity = build_public_identity(raw)
    site_data = {
        "site": {
            "name": raw["site"]["name"],
            "shortDescription": raw["site"]["short_description"],
            "description": raw["site"]["description"],
            "ogImage": raw["site"]["og_image"],
            "heroWorkId": home["hero"]["feature_work_id"],
            **site_settings,
        },
        "artist": {
            "name": raw["artist"]["name"],
            "discipline": raw["artist"]["discipline"],
            "tagline": raw["artist"]["tagline"],
            "intro": raw["artist"]["intro"],
            "about": raw["artist"]["about"],
            "statement": raw["artist"]["statement"],
            "status": raw["artist"]["status"],
            "email": identity["email"],
            "instagram": raw["artist"]["instagram"],
            "location": identity["location"],
            "alternateNames": list(raw["artist"].get("alternate_names") or []),
        },
        "imagePipeline": {
            "widths": RESPONSIVE_WIDTHS,
            "lightboxWidth": int(IMAGE_PIPELINE.get("lightbox_width", DEFAULT_IMAGE_PIPELINE["lightbox_width"])),
        },
        'downloads': downloads,
        "collections": collection_list,
        "series": [
            {
                key: value
                for key, value in item.items()
                if key != "_work_ids"
            }
            for item in public_series_list
        ],
        "reviewSeries": private_series_list,
        "works": public_works,
        "reviewWorks": private_works,
        "pages": {
            key: {
                "heroWorkId": str((value.get("hero") or {}).get("feature_work_id") or ""),
                "heroTitle": str(value.get("hero_title") or ((value.get("hero") or {}).get("title") or "")),
                "heroEyebrow": str(value.get("hero_eyebrow") or ((value.get("hero") or {}).get("eyebrow") or "")),
                "heroLead": str(value.get("hero_lead") or ((value.get("hero") or {}).get("lead") or "")),
            }
            for key, value in raw["pages"].items()
            if isinstance(value, dict)
        },
    }

    store = {
        "raw": raw,
        "site_data": site_data,
        "works_by_id": works_by_id,
        "series_list": series_list,
        "series_lookup": series_lookup,
        "public_series_list": public_series_list,
        "public_series_lookup": public_series_lookup,
        "collections": collection_list,
        "collection_lookup": collection_lookup,
        "portfolio_works": sorted(portfolio_works, key=lambda item: item["portfolioOrder"]),
        "public_portfolio_works": public_portfolio_works,
        "public_work_ids": public_work_ids,
        "private_series_list": private_series_list,
        "private_works": private_works,
        'downloads': downloads,
        'public_downloads': public_downloads,
        'downloads_by_id': downloads_by_id,
        'release_settings': release_settings,
        "generated_assets": generated_assets,
    }

    validate_runtime_store(store)
    return store

def iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def build_date_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text_value = str(value or '').strip()
        if not text_value or text_value in seen:
            continue
        seen.add(text_value)
        result.append(text_value)
    return result


def build_content_graph(raw: dict[str, Any], store: dict[str, Any]) -> dict[str, Any]:
    home = raw.get('pages', {}).get('home', {})
    featured_series = _unique_strings(home.get('featured_series', {}).get('series_slugs', []) if isinstance(home.get('featured_series', {}).get('series_slugs', []), list) else [])
    works = {}
    orphan_works = []
    for entry in raw.get('works', []):
        work_id = str(entry.get('id') or '').strip()
        if not work_id:
            continue
        published = entry.get('published', True) is not False
        series_memberships = []
        for series in raw.get('series', []):
            slug = str(series.get('slug') or '').strip()
            ordered_work_ids = _unique_strings(series.get('work_ids', []) if isinstance(series.get('work_ids', []), list) else [])
            if work_id in ordered_work_ids:
                series_memberships.append(slug)
        if published and not series_memberships:
            orphan_works.append({'title': str(entry.get('title') or work_id), 'filePath': f'content/works/{work_id}.yaml'})
        works[work_id] = {
            'id': work_id,
            'title': str(entry.get('title') or work_id),
            'published': published,
            'filePath': f'content/works/{work_id}.yaml',
            'imagePath': str(entry.get('image') or '').strip(),
            'seriesSlugs': series_memberships,
        }

    series_graph = {}
    unfeatured_series = []
    for entry in raw.get('series', []):
        slug = str(entry.get('slug') or '').strip()
        if not slug:
            continue
        published = entry.get('published', True) is not False
        visibility = str(entry.get('visibility') or 'public').strip().lower()
        if published and visibility != 'private' and slug not in featured_series:
            unfeatured_series.append({'title': str(entry.get('title') or slug), 'filePath': f'content/series/{slug}.yaml'})
        series_graph[slug] = {
            'slug': slug,
            'title': str(entry.get('title') or slug),
            'published': published,
            'visibility': visibility,
            'filePath': f'content/series/{slug}.yaml',
            'coverWorkId': str(entry.get('cover_work_id') or '').strip(),
            'cardCoverWorkId': str(entry.get('card_cover_work_id') or '').strip(),
            'heroWorkId': str(entry.get('hero_work_id') or '').strip(),
            'workIds': _unique_strings(entry.get('work_ids', []) if isinstance(entry.get('work_ids', []), list) else []),
        }

    page_graph = {
        'home': {'filePath': 'content/pages/home.yaml'},
        'portfolio': {'filePath': 'content/pages/portfolio.yaml'},
        'series': {'filePath': 'content/pages/series.yaml'},
        'performance': {'filePath': 'content/pages/performance.yaml'},
        'about': {'filePath': 'content/pages/about.yaml'},
        'contact': {'filePath': 'content/pages/contact.yaml'},
    }

    return {
        'generatedAt': iso_timestamp(),
        'environment': store['site_data']['site']['environment'],
        'displayUrl': store['site_data']['site']['displayUrl'],
        'works': works,
        'series': series_graph,
        'pages': page_graph,
        'issues': {'orphanPublishedWorks': orphan_works, 'unfeaturedPublishedSeries': unfeatured_series},
    }

def write_build_metadata(store: dict[str, Any]) -> dict[str, Any]:
    BUILD_META_DIR.mkdir(parents=True, exist_ok=True)
    graph = build_content_graph(store['raw'], store)
    CONTENT_GRAPH_PATH.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')

    report = generate_release_report(store)
    RELEASE_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')

    missing_assets = list(store.get('missing_assets') or [])
    build_status = {
        'updatedAt': iso_timestamp(),
        'status': 'warning' if missing_assets else 'success',
        'message': 'Site rebuilt with missing-image placeholders.' if missing_assets else 'Site rebuilt successfully.',
        'environment': store['site_data']['site']['environment'],
        'displayUrl': store['site_data']['site']['displayUrl'],
        'allowIndexing': store['site_data']['site']['allowIndexing'],
        'pages': ['index.html', 'portfolio.html', 'series.html', 'performance.html', 'about.html', 'contact.html', '404.html'],
        'smokeChecks': report['smokeChecks'],
        'releaseReady': report['ready'],
        'missingImages': missing_assets,
        'missingImageCount': len(missing_assets),
    }
    BUILD_STATUS_PATH.write_text(json.dumps(build_status, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')
    write_publish_state_after_build()
    return report

def generate_release_report(store: dict[str, Any]) -> dict[str, Any]:
    site = store['site_data']['site']
    artist = store['site_data']['artist']
    release = store.get('release_settings', {})
    env = site['environment']
    pages = ['index.html', 'portfolio.html', 'series.html', 'performance.html', 'about.html', 'contact.html', '404.html']
    missing_assets = list(store.get('missing_assets') or [])
    smoke_checks: list[dict[str, Any]] = []

    def add_check(label: str, passed: bool, details: str) -> None:
        smoke_checks.append({'label': label, 'passed': bool(passed), 'details': details})

    add_check('Pages generated', all((ROOT / page).exists() for page in pages), 'Core public pages were written to disk.')
    add_check('Source image coverage', len(missing_assets) == 0, 'All published works have original sources.' if not missing_assets else f"{len(missing_assets)} published work(s) built with placeholder media.")
    public_email = str(site.get('public_email') or artist.get('email') or '').strip()
    instagram_value = str(artist.get('instagram') or '').strip()
    email_required = not is_stage_contact_optional(env)
    instagram_required = not is_stage_contact_optional(env)
    add_check(
        'Public contact email is configured or intentionally hidden',
        has_public_contact_email(public_email) or (not public_email and not email_required),
        f"Contact email: {public_email or 'hidden for staging'}",
    )
    add_check(
        'Public social/profile URL is configured or intentionally hidden',
        has_public_profile_url(instagram_value) or (not instagram_value and not instagram_required),
        f"Instagram/profile URL: {instagram_value or 'hidden for staging'}",
    )

    if env == 'local':
        add_check('Indexing disabled in local mode', not site['allowIndexing'], 'Local previews should stay noindex.')
    else:
        add_check('Site URL configured', is_real_public_url(site['siteUrl']), f"Site URL: {site['siteUrl'] or 'unset'}")
        add_check('Canonical/OG base is absolute', bool(site['metadataBaseUrl'].startswith('http')) and not looks_like_placeholder(site['metadataBaseUrl']), f"Metadata base: {site['metadataBaseUrl']}")

    if site['allowIndexing'] and site['siteUrl']:
        sitemap_text = (DIST_DIR / 'sitemap.xml').read_text(encoding='utf-8') if (DIST_DIR / 'sitemap.xml').exists() else ''
        add_check('Sitemap present for indexable build', '<urlset' in sitemap_text, 'Indexable builds should emit a sitemap.')
    else:
        add_check('Sitemap intentionally suppressed', '<!-- STILLMRK sitemap is intentionally disabled' in (DIST_DIR / 'sitemap.xml').read_text(encoding='utf-8'), 'Non-indexable builds suppress the sitemap on purpose.')

    private_series = [series['slug'] for series in store['series_list'] if series.get('visibility') == 'private']
    private_work_ids = {work_id for work_id, work in store['works_by_id'].items() if str(work.get('series') or '').strip() in private_series}
    public_series_slugs = {series['slug'] for series in store['site_data']['series']}
    public_work_ids = {work['id'] for work in store['site_data']['works']}
    add_check('Private series are excluded from generated public data', all(slug not in public_series_slugs for slug in private_series), 'Static builds should keep private series out of siteData and public preview routes.')
    add_check('Private works are excluded from generated public data', all(work_id not in public_work_ids for work_id in private_work_ids), 'Works attached only to private series should not ship in public JS data.')
    add_check('Private series kept out of public homepage modules', all(series.get('homeFeatureOrder') is None for series in store['series_list'] if series.get('visibility') == 'private'), 'Private series should not surface on home modules.')
    repo_required = env == 'production'
    production_url_required = env == 'production'
    add_check('Production backend profile prepared', bool(release.get('productionBackend')) and not looks_like_placeholder(release.get('productionBackend')), f"Backend: {release.get('productionBackend') or 'unset'}")
    add_check('Repository configured for backend or deferred for staging', is_real_repo(release.get('repo')) or (not repo_required), f"Repo: {release.get('repo') or 'deferred for staging'}")
    add_check('Staging URL is real', is_real_public_url(release.get('stagingUrl')), f"Staging URL: {release.get('stagingUrl') or 'unset'}")
    add_check('Production URL is real or deferred for staging', is_real_public_url(release.get('productionUrl')) or (not production_url_required), f"Production URL: {release.get('productionUrl') or 'deferred for staging'}")

    warnings = []
    if env == 'production' and not site['allowIndexing']:
        warnings.append('Environment is production but indexing is still disabled.')
    if env != 'local' and not is_real_public_url(site['siteUrl']):
        warnings.append('A non-local environment is selected without a final public site URL.')
    if (str(artist.get('email') or '').strip() and looks_like_placeholder(artist.get('email'))) or (str(artist.get('instagram') or '').strip() and looks_like_placeholder(artist.get('instagram'))):
        warnings.append('Public-facing artist contact fields still contain placeholder values. Replace them or leave them blank for staging.')
    if env == 'production' and (looks_like_placeholder(release.get('repo')) or looks_like_placeholder(release.get('stagingUrl')) or looks_like_placeholder(release.get('productionUrl'))):
        warnings.append('Release profile still contains placeholder repository or URL values.')

    ready = all(item['passed'] for item in smoke_checks)
    return {
        'generatedAt': iso_timestamp(),
        'environment': env,
        'ready': ready,
        'stagingUrl': release.get('stagingUrl') or '',
        'productionUrl': release.get('productionUrl') or site['siteUrl'],
        'productionBackend': release.get('productionBackend') or 'github',
        'repo': release.get('repo') or '',
        'previewBranch': release.get('previewBranch') or 'preview',
        'productionBranch': release.get('productionBranch') or 'main',
        'commitMessageTemplate': release.get('commitMessageTemplate') or '',
        'changeNoteTemplate': release.get('changeNoteTemplate') or '',
        'requiredChecks': release.get('requiredChecks') or [],
        'smokeChecks': smoke_checks,
        'missingImages': missing_assets,
        'missingImageCount': len(missing_assets),
        'warnings': warnings,
        'configFiles': [],
    }


def _handle_remove_readonly(func, target, exc_info) -> None:
    try:
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
        func(target)
    except Exception:
        pass


def _clear_directory_contents(path: Path) -> None:
    for child in list(path.iterdir()):
        try:
            if child.is_dir():
                shutil.rmtree(child, onerror=_handle_remove_readonly)
            else:
                os.chmod(child, stat.S_IWRITE | stat.S_IREAD)
                child.unlink(missing_ok=True)
        except PermissionError:
            print(f"[STILLMRK build] Warning: could not remove locked path: {child}", flush=True)


def reset_directory(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return

    try:
        shutil.rmtree(path, onerror=_handle_remove_readonly)
        path.mkdir(parents=True, exist_ok=True)
        return
    except PermissionError:
        print(f"[STILLMRK build] Warning: full reset failed for {path}. Trying a softer cleanup.", flush=True)

    path.mkdir(parents=True, exist_ok=True)
    _clear_directory_contents(path)
    path.mkdir(parents=True, exist_ok=True)


PAGE_FILES = ['index.html', 'portfolio.html', 'series.html', 'performance.html', 'about.html', 'contact.html', '404.html']
ASSET_COPY_BLOCKLIST = {'incoming', 'originals', 'manifests'}


def prepare_dist() -> None:
    """Reset dist/ and copy the static assets the public site needs."""
    reset_directory(DIST_DIR)

    def ignore_assets(_current_dir: str, names: list[str]) -> set[str]:
        return {name for name in names if name in ASSET_COPY_BLOCKLIST or name.startswith('.')}

    shutil.copytree(ROOT / 'assets', DIST_DIR / 'assets', dirs_exist_ok=True, ignore=ignore_assets)


def write_dist_file(relative: str, text: str) -> None:
    target = DIST_DIR / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding='utf-8')


def write_upload_manifest(store: dict[str, Any], report: dict[str, Any]) -> None:
    for required in ('index.html', 'assets/css/site.css', 'assets/js/site.js'):
        target = DIST_DIR / required
        if not target.exists() or target.stat().st_size <= 0:
            raise RuntimeError(f'Build integrity failed: dist/{required} is missing or empty.')
    manifest = {
        'generatedAt': iso_timestamp(),
        'environment': report.get('environment') or store['site_data']['site']['environment'],
        'siteUrl': store['site_data']['site']['siteUrl'],
        'displayUrl': store['site_data']['site']['displayUrl'],
        'allowIndexing': store['site_data']['site']['allowIndexing'],
        'uploadFolder': 'dist',
        'uploadOnly': PAGE_FILES + ['robots.txt', 'sitemap.xml', 'site.webmanifest', 'assets/'],
    }
    write_dist_file('upload-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def load_asset_manifest() -> set[str]:
    if not ASSET_MANIFEST_PATH.exists():
        return set()

    try:
        payload = json.loads(ASSET_MANIFEST_PATH.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return set()

    assets = payload.get('responsive_assets', []) if isinstance(payload, dict) else []
    return {str(path) for path in assets if isinstance(path, str) and path.strip()}


def save_asset_manifest(current_assets: set[str]) -> None:
    BUILD_STATE_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_MANIFEST_PATH.write_text(
        json.dumps({'responsive_assets': sorted(current_assets)}, ensure_ascii=False, indent=2) + "\n",
        encoding='utf-8',
    )


def write_image_manifests(store: dict[str, Any], cleanup_report: dict[str, Any] | None = None) -> None:
    manifest_dir = current_manifest_root()
    manifest_dir.mkdir(parents=True, exist_ok=True)

    image_index: list[dict[str, Any]] = []
    for entry in SITE_CONTENT.get('works', []):
        if not isinstance(entry, dict):
            continue
        work_id = str(entry.get('id') or '').strip()
        if not work_id:
            continue
        image_config = resolve_image_definition(entry)
        try:
            source_original = relative_asset_path(resolve_source_path(entry, image_config))
        except FileNotFoundError:
            source_original = ''
        focal_point = entry.get('focal_point') if isinstance(entry.get('focal_point'), dict) else {}
        default_focal_point = default_focal_point_config()
        image_index.append({
            'id': work_id,
            'title': str(entry.get('title') or '').strip(),
            'series': str(image_config.get('series') or resolve_series_slug_for_work(entry) or '').strip(),
            'published': bool(entry.get('published', True)),
            'renderName': str(image_config.get('render_name') or entry.get('render_name') or work_id).strip() or work_id,
            'sourceOriginal': source_original,
            'focalPoint': {
                'x': clamp_percentage(focal_point.get('x'), default_focal_point['x']),
                'y': clamp_percentage(focal_point.get('y'), default_focal_point['y']),
            },
        })

    derivative_index: list[dict[str, Any]] = []
    indexed_works = [
        *list(store['site_data'].get('works') or []),
        *list(store['site_data'].get('reviewWorks') or []),
    ]
    for work in indexed_works:
        inventory = derivative_inventory_for_work(work)
        derivative_index.append({
            'id': work['id'],
            'series': str(work.get('series') or '').strip(),
            'responsiveBase': str(work.get('responsiveBase') or '').strip(),
            'sourceOriginal': str(work.get('sourceOriginal') or '').strip(),
            'width': int(work.get('width') or 0),
            'height': int(work.get('height') or 0),
            'missingSource': bool(work.get('missingSource', False)),
            'missingSourceDetail': str(work.get('missingSourceDetail') or '').strip(),
            'variants': inventory,
        })

    ingestion_log = {
        'lastBuildAt': iso_timestamp(),
        'publishedWorkCount': len(store['site_data']['works']),
        'reviewWorkCount': len(store['site_data'].get('reviewWorks') or []),
        'generatedVariantCount': sum(len(item['variants']) for item in derivative_index),
        'manifestVersion': 2,
        'pipelineWidths': RESPONSIVE_WIDTHS,
    }

    cleanup = cleanup_report or {}
    referenced_derivatives = {
        'generatedAt': iso_timestamp(),
        'manifestVersion': 1,
        'generatedRoot': relative_asset_path(current_generated_root()),
        'legacyResponsiveRoot': relative_asset_path(legacy_generated_root()),
        'pipelineWidths': RESPONSIVE_WIDTHS,
        'formats': [str(item).strip().lower() for item in (IMAGE_PIPELINE.get('formats') or DEFAULT_IMAGE_PIPELINE['formats']) if str(item).strip()],
        'referencedAssets': sorted(store.get('generated_assets') or []),
        'referencedAssetCount': len(store.get('generated_assets') or []),
        'workCount': len(indexed_works),
        'works': derivative_index,
        'cleanup': cleanup,
    }

    (manifest_dir / 'image-index.json').write_text(json.dumps(image_index, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')
    (manifest_dir / 'derivative-index.json').write_text(json.dumps(derivative_index, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')
    (manifest_dir / 'ingestion-log.json').write_text(json.dumps(ingestion_log, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')
    (manifest_dir / 'referenced-derivatives.json').write_text(json.dumps(referenced_derivatives, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')
    BUILD_META_DIR.mkdir(parents=True, exist_ok=True)
    (BUILD_META_DIR / 'asset-truth-report.json').write_text(json.dumps(referenced_derivatives, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')


def scan_generated_derivative_files() -> set[str]:
    generated_root = current_generated_root()
    if not generated_root.exists():
        return set()
    assets: set[str] = set()
    for path in generated_root.rglob('*'):
        if path.is_file() and path.suffix.lower() in IMAGE_DERIVATIVE_EXTENSIONS:
            assets.add(relative_asset_path(path))
    return assets


def cleanup_empty_generated_dirs() -> None:
    generated_root = current_generated_root()
    if not generated_root.exists():
        return
    for path in sorted((item for item in generated_root.rglob('*') if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        if path == generated_root:
            continue
        try:
            path.rmdir()
        except OSError:
            pass


def quarantine_generated_asset(relative_path: str, batch_id: str) -> str | None:
    source = ROOT / relative_path
    generated_root = current_generated_root()
    if not source.exists() or not source.is_file() or not path_within(source, generated_root):
        return None
    target = ASSET_QUARANTINE_ROOT / batch_id / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        suffix = source.suffix
        target = target.with_name(f"{target.stem}-{hashlib.sha1(str(source).encode('utf-8')).hexdigest()[:8]}{suffix}")
    shutil.move(str(source), str(target))
    return relative_asset_path(target)


def prune_generated_responsive_assets(current_assets: set[str]) -> dict[str, Any]:
    current_assets = {str(item).strip() for item in current_assets if str(item).strip()}
    previous_assets = load_asset_manifest()
    scanned_assets = scan_generated_derivative_files()
    stale_assets = sorted((previous_assets | scanned_assets) - current_assets)

    batch_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    quarantined: list[dict[str, str]] = []
    skipped: list[str] = []
    for relative_path in stale_assets:
        moved_to = quarantine_generated_asset(relative_path, batch_id)
        if moved_to:
            quarantined.append({'from': relative_path, 'to': moved_to})
        else:
            skipped.append(relative_path)

    cleanup_empty_generated_dirs()
    save_asset_manifest(current_assets)

    report = {
        'checkedAt': iso_timestamp(),
        'mode': 'quarantine-not-delete',
        'pipelineWidths': RESPONSIVE_WIDTHS,
        'referencedAssetCount': len(current_assets),
        'scannedAssetCount': len(scanned_assets),
        'previousManifestAssetCount': len(previous_assets),
        'staleAssetCount': len(stale_assets),
        'quarantinedAssetCount': len(quarantined),
        'quarantineRoot': relative_asset_path(ASSET_QUARANTINE_ROOT / batch_id) if quarantined else '',
        'quarantinedAssets': quarantined,
        'skippedAssets': skipped,
    }

    if quarantined:
        print(f"[STILLMRK build] Quarantined {len(quarantined)} stale generated image asset(s); no files were deleted.")
    return report


def series_path(slug: str) -> str:
    return f"/series/{quote(slug)}/"


def work_path(work_id: str) -> str:
    return f"/works/{quote(work_id)}/"


def available_widths(work: dict[str, Any]) -> list[int]:
    intrinsic = int(work.get("width") or RESPONSIVE_WIDTHS[-1])
    widths = [width for width in RESPONSIVE_WIDTHS if width <= intrinsic]
    fallback = min(intrinsic, RESPONSIVE_WIDTHS[-1])
    if fallback not in widths:
        widths.append(fallback)
    return sorted(set(widths))


def preferred_width(work: dict[str, Any], preferred: int = 1200) -> int:
    widths = available_widths(work)
    for width in reversed(widths):
        if width <= preferred:
            return width
    return widths[-1]


def largest_available_width(work: dict[str, Any]) -> int:
    return available_widths(work)[-1]


def image_path(work: dict[str, Any], width: int | None = None, extension: str = "jpg") -> str:
    base = work.get("responsiveBase")
    if base:
        resolved = width or preferred_width(work)
        return f"{base}-{resolved}.{extension}"
    return str(work.get("src") or "")


def source_set(work: dict[str, Any], extension: str) -> str:
    base = work.get("responsiveBase")
    if not base:
        return ""
    return ", ".join(f"{base}-{width}.{extension} {width}w" for width in available_widths(work))


def avif_source_set(work: dict[str, Any]) -> str:
    base = work.get("responsiveBase")
    widths = set(work.get("avifWidths") or [])
    if not base or not widths:
        return ""
    return ", ".join(f"{base}-{width}.avif {width}w" for width in available_widths(work) if width in widths)


def orientation(work: dict[str, Any]) -> str:
    ratio = work["width"] / work["height"]
    if ratio > 1.12:
        return "landscape"
    if ratio < 0.88:
        return "portrait"
    return "square"


LAYOUT_TOKENS = {"auto", "quiet", "standard", "medium", "large", "wide", "full"}
LAYOUT_ALIASES = {
    "small": "quiet",
    "compact": "quiet",
    "normal": "standard",
    "default": "standard",
    "regular": "standard",
    "feature": "large",
    "featured": "large",
    "hero": "wide",
    "cinematic": "wide",
    "span": "wide",
}


def normalize_layout_token(value: Any, fallback: str = "auto") -> str:
    token = str(value or "").strip().lower().replace("_", "-")
    if not token:
        token = fallback
    token = LAYOUT_ALIASES.get(token, token)
    return token if token in LAYOUT_TOKENS else fallback


def _visible_nav_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in raw.get('navigation') or []:
        if not isinstance(entry, dict):
            continue
        if entry.get('visible', True) is False:
            continue
        items.append(entry)
    return items


def _artist_social_links(artist: dict[str, Any]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    custom = artist.get('social_links') if isinstance(artist.get('social_links'), list) else []
    for entry in custom:
        if not isinstance(entry, dict):
            continue
        if entry.get('visible', True) is False:
            continue
        href = str(entry.get('href') or '').strip()
        label = str(entry.get('label') or '').strip()
        if href and label:
            links.append({'label': label, 'href': href})
    instagram = str(artist.get('instagram') or '').strip()
    if instagram and has_public_profile_url(instagram) and not any(item['href'] == instagram for item in links):
        links.append({'label': 'Instagram', 'href': instagram})
    return links


def analytics_id() -> str:
    value = str((SITE_CONTENT.get('site') or {}).get('analytics_id') or '').strip()
    return value if re.fullmatch(r'G-[A-Z0-9]+', value, re.IGNORECASE) else ''


def split_home_hero_lead(lead: Any) -> tuple[str, str | None]:
    text = str(lead or '').strip()
    if not text:
        return '', None

    if '\n\n' in text:
        primary, secondary = text.split('\n\n', 1)
        return primary.strip(), secondary.strip() or None

    breakpoint = 'Trees return as witnesses.'
    if breakpoint in text:
        primary, secondary = text.split(breakpoint, 1)
        primary = f"{primary.strip()} {breakpoint}".strip()
        secondary = secondary.strip() or None
        return primary, secondary

    return text, None


def summarize_story_text(text: str, *, fallback: str = '', limit: int = 190) -> str:
    cleaned = ' '.join(str(text or '').split())
    if not cleaned:
        cleaned = ' '.join(str(fallback or '').split())
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit].rsplit(' ', 1)[0].rstrip(' ,;:.')
    return f"{clipped}…" if clipped else cleaned[:limit]


def render_sitemap_xml(extra_paths: list[str] | None = None) -> str:
    site_settings = build_site_settings(SITE_CONTENT['site'])
    if not site_settings['allowIndexing'] or not site_settings['siteUrl']:
        return '<!-- STILLMRK sitemap is intentionally disabled for local or non-indexable builds. -->\n'

    page_specs = [
        ('home', 1.0),
        ('portfolio', 0.9),
        ('series', 0.9),
        ('performance', 0.85),
        ('about', 0.7),
        ('contact', 0.7),
    ]
    lastmod = build_date_iso()
    body = '\n'.join(
        f'  <url><loc>{esc(build_page_url(page_key, SITE_CONTENT["site"]))}</loc><lastmod>{lastmod}</lastmod><changefreq>monthly</changefreq><priority>{priority:.1f}</priority></url>'
        for page_key, priority in page_specs
    )
    for path in extra_paths or []:
        body += f'\n  <url><loc>{esc(absolute_url(path.lstrip("/"), site_settings["siteUrl"]))}</loc><lastmod>{lastmod}</lastmod><changefreq>monthly</changefreq><priority>0.6</priority></url>'
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'{body}\n'
        '</urlset>\n'
    )


def render_site_manifest() -> str:
    site_settings = build_site_settings(SITE_CONTENT['site'])
    payload = {
        'name': str(SITE_CONTENT['site'].get('name') or 'STILLMRK').strip(),
        'short_name': str(SITE_CONTENT['site'].get('name') or 'STILLMRK').strip(),
        'description': str(SITE_CONTENT['site'].get('short_description') or SITE_CONTENT['site'].get('description') or '').strip(),
        'start_url': '/',
        'display': 'standalone',
        'background_color': '#0b0b0b',
        'theme_color': '#0b0b0b',
        'icons': [
            {'src': 'assets/icons/android-chrome-192x192.png', 'sizes': '192x192', 'type': 'image/png'},
            {'src': 'assets/icons/android-chrome-512x512.png', 'sizes': '512x512', 'type': 'image/png'},
            {'src': 'assets/icons/apple-touch-icon.png', 'sizes': '180x180', 'type': 'image/png', 'purpose': 'any'},
        ],
    }
    if site_settings['siteUrl']:
        payload['id'] = '/'
        payload['scope'] = '/'
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_robots_txt() -> str:
    site_settings = build_site_settings(SITE_CONTENT['site'])
    lines = ['User-agent: *', 'Allow: /']
    if site_settings['allowIndexing'] and site_settings['siteUrl']:
        lines.extend(['', f"Sitemap: {absolute_url('sitemap.xml', site_settings['siteUrl'])}"])
    else:
        lines.extend(['', '# Local or non-indexable build: pages emit a noindex robots meta tag in HTML.'])
    return '\n'.join(lines) + '\n'


# ─────────────────────────────────────────────────────────────
# Phase 2: real URLs, build-time structured data, work pages
# ─────────────────────────────────────────────────────────────
PUBLIC_SERIES_SLUGS: list[str] = []
_URL_ATTR = re.compile(r'(?P<name>\b[\w:-]*(?:href|src|srcset))="(?P<value>[^"]*)"', re.IGNORECASE)
_NON_RELATIVE = ('/', '#', 'http:', 'https:', 'mailto:', 'tel:', 'data:', 'javascript:', 'blob:', '?', '{', '$')


def _rootify_url(url: str) -> str:
    url = url.strip()
    if not url or url.startswith(_NON_RELATIVE) or '${' in url:
        return url
    return '/' + url


def rootify_html(html_text: str) -> str:
    """Make every local URL root-relative so pages work at any depth.

    Pages now live at /series/<slug>/ and /works/<id>/ as well as the root, and
    404.html is served for any missing path, so 'assets/...' must become
    '/assets/...'. Absolute URLs, anchors and template placeholders are kept.
    """
    def fix(match: re.Match[str]) -> str:
        name, value = match.group('name'), match.group('value')
        if name.lower().endswith('srcset'):
            parts = []
            for candidate in value.split(','):
                bits = candidate.strip().split(' ', 1)
                if bits[0]:
                    parts.append(' '.join([_rootify_url(bits[0])] + bits[1:]))
            value = ', '.join(parts)
        else:
            value = _rootify_url(value)
        return f'{name}="{value}"'
    return _URL_ATTR.sub(fix, html_text)


def json_ld(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')


def _site_url() -> str:
    return build_site_settings(SITE_CONTENT['site'])['metadataBaseUrl']


def base_schema() -> dict[str, Any]:
    site_url = _site_url()
    site = SITE_CONTENT['site']
    artist = SITE_CONTENT['artist']
    identity = build_public_identity(SITE_CONTENT)
    person: dict[str, Any] = {
        '@type': 'Person',
        '@id': f'{site_url}#person',
        'name': artist.get('name'),
        'alternateName': list(artist.get('alternate_names') or site.get('search_names') or []),
        'jobTitle': artist.get('discipline'),
        'description': md_plain(artist.get('about')),
        'url': site_url,
    }
    if identity.get('location'):
        person['homeLocation'] = identity['location']
    if has_public_contact_email(identity.get('email')):
        person['email'] = identity['email']
    if has_public_profile_url(artist.get('instagram')):
        person['sameAs'] = [artist['instagram']]
    return {
        '@context': 'https://schema.org',
        '@graph': [
            {
                '@type': 'WebSite',
                '@id': f'{site_url}#website',
                'name': site.get('name'),
                'description': md_plain(site.get('description')),
                'url': site_url,
                'publisher': {'@id': f'{site_url}#person'},
            },
            person,
        ],
    }


def page_schema(page_key: str, meta: dict[str, Any], canonical_url: str, image_url: str) -> dict[str, Any]:
    site_url = _site_url()
    page_types = {'home': 'CollectionPage', 'portfolio': 'CollectionPage', 'series': 'CollectionPage',
                  'performance': 'CollectionPage', 'about': 'ProfilePage', 'contact': 'ContactPage'}
    schema: dict[str, Any] = {
        '@context': 'https://schema.org',
        '@type': page_types.get(page_key, 'WebPage'),
        'name': meta.get('title'),
        'description': md_plain(meta.get('description')),
        'url': canonical_url,
        'inLanguage': 'en-GB',
        'image': image_url,
        'isPartOf': {'@id': f'{site_url}#website'},
        'author': {'@id': f'{site_url}#person'},
    }
    if page_key == 'about':
        schema['mainEntity'] = {'@id': f'{site_url}#person'}
    return schema


def _image_url(work: dict[str, Any], width: int | None = None) -> str:
    return absolute_url(image_path(work, width or preferred_width(work, 1600), 'jpg'), _site_url())


def series_schema(store: dict[str, Any], series: dict[str, Any] | None, works: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not series:
        return None
    site_url = _site_url()
    url = absolute_url(series_path(series['slug']).lstrip('/'), site_url)
    return {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        'name': series['title'],
        'description': series['description'],
        'url': url,
        'isPartOf': {'@id': f'{site_url}#website'},
        'author': {'@id': f'{site_url}#person'},
        'about': {'@type': 'CreativeWorkSeries', 'name': series['title'], 'description': series['description'], 'creator': {'@id': f'{site_url}#person'}},
        'hasPart': [
            {'@type': 'VisualArtwork', 'name': work['title'], 'url': absolute_url(work_path(work['id']).lstrip('/'), site_url),
             'image': _image_url(work), 'description': work.get('alt') or ''}
            for work in works if work.get('responsiveBase')
        ],
    }


def series_page_meta(store: dict[str, Any], base_meta: dict[str, Any], series: dict[str, Any] | None, works: list[dict[str, Any]]) -> dict[str, Any]:
    if not series:
        return base_meta
    site_name = str(SITE_CONTENT['site'].get('name') or 'STILLMRK')
    description = summarize_story_text(series['description'], fallback=series.get('mood') or '', limit=158)
    meta = dict(base_meta)
    meta.update({
        'title': f"{series['title']} - {site_name}",
        'description': description,
        'og_description': description,
        'canonical_path': series_path(series['slug']).lstrip('/'),
    })
    return meta


def work_inquiry_href(work: dict[str, Any]) -> str:
    query = f"works={quote(work['id'])}"
    if work.get('series'):
        query += f"&series={quote(work['series'])}"
    return f"/contact.html?{query}"


# ─────────────────────────────────────────────────────────────
# Phase 3: templates (templates/*.html, Jinja2) and the new design system
# (assets/css/site.css). Pages move here one at a time; the remaining
# f-string renderers above are deleted once every page has moved.
# ─────────────────────────────────────────────────────────────
TEMPLATES_DIR = ROOT / 'templates'
_TEMPLATE_ENV = None


def template_env():
    global _TEMPLATE_ENV
    if _TEMPLATE_ENV is None:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
        from markupsafe import Markup
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(['html']),
            undefined=StrictUndefined,
            trim_blocks=False,
            lstrip_blocks=False,
        )
        env.globals.update(
            image_path=image_path,
            source_set=source_set,
            avif_source_set=avif_source_set,
            preferred_width=preferred_width,
            largest_available_width=largest_available_width,
            series_path=series_path,
            work_path=work_path,
        )
        env.filters['md'] = lambda value: Markup(md_inline(value))
        _TEMPLATE_ENV = env
    return _TEMPLATE_ENV


def head_context(page_key: str, meta: dict[str, Any], *, preload_work: dict[str, Any] | None = None,
                 preload_sizes: str = '100vw', schema: dict[str, Any] | None = None, og_type: str = 'website') -> dict[str, Any]:
    from markupsafe import Markup
    site = SITE_CONTENT['site']
    settings = build_site_settings(site)
    canonical_override = str(meta.get('canonical_path') or '').strip()
    if canonical_override.startswith(('http://', 'https://')):
        canonical = canonical_override
    elif canonical_override or page_key in {'work', 'series'}:
        canonical = absolute_url(canonical_override, settings['metadataBaseUrl'])
    else:
        canonical = build_page_url(page_key, site)
    image = absolute_url(str(meta.get('og_image') or site['og_image']).strip(), settings['metadataBaseUrl'])
    preload = None
    if preload_work and preload_work.get('responsiveBase'):
        avif = avif_source_set(preload_work)
        preload = {'type': 'image/avif' if avif else 'image/webp', 'srcset': avif or source_set(preload_work, 'webp'), 'sizes': preload_sizes}
    names = [str(SITE_CONTENT['artist'].get('name') or '')] + list(SITE_CONTENT['artist'].get('alternate_names') or [])
    return {
        'title': meta['title'],
        'description': md_plain(meta.get('description')),
        'og_description': md_plain(meta.get('og_description') or meta.get('description')),
        'author': ', '.join(name for name in names if name),
        'robots': settings['robots'],
        'canonical': canonical,
        'site_name': str(site.get('name') or 'STILLMRK'),
        'og_type': og_type,
        'image': image,
        'image_alt': str(meta.get('og_image_alt') or meta['title']),
        'preload': preload,
        'analytics_id': analytics_id(),
        'base_schema': Markup(json_ld(base_schema())),
        'page_schema': Markup(json_ld(schema or page_schema(page_key, meta, canonical, image))),
    }


def chrome_context(store: dict[str, Any], nav_section: str) -> dict[str, Any]:
    raw = store['raw']
    identity = build_public_identity(raw)
    nav = []
    for item in _visible_nav_items(raw):
        page = str(item.get('page') or '')
        if page == 'home':
            continue  # the wordmark is the way home
        href = str(item.get('href') or '')
        nav.append({'label': item.get('label'), 'href': href if href.startswith(('/', 'http')) else '/' + href, 'page': page})
    return {
        'site_name': str(raw['site'].get('name') or 'STILLMRK'),
        'nav': nav,
        'nav_section': nav_section,
        'artist_name': identity.get('name') or '',
        'email': identity['email'] if has_public_contact_email(identity.get('email')) else '',
        'social_links': _artist_social_links(raw['artist']),
        'analytics_id': analytics_id(),
        'year': datetime.now(timezone.utc).year,
    }


def render_template(name: str, **context: Any) -> str:
    return template_env().get_template(name).render(**context)


def _paragraphs(text: Any) -> list[Any]:
    from markupsafe import Markup
    return [Markup(md_inline(part.strip())) for part in re.split(r'\n\s*\n', str(text or '')) if part.strip()]


def render_home_v2(store: dict[str, Any]) -> str:
    raw = store['raw']
    home = raw['pages']['home']
    hero_raw = home.get('hero') or {}
    works_by_id = store['works_by_id']
    hero_work = works_by_id.get(str(hero_raw.get('feature_work_id') or ''))
    lead = str(hero_raw.get('lead') or '')
    lead_paragraphs = _paragraphs(lead) if '\n\n' in lead else [part for part in split_home_hero_lead(lead) if part]
    actions = [action for action in (hero_raw.get('primary_action'), hero_raw.get('secondary_action')) if isinstance(action, dict) and action.get('href')]
    groups = series_groups(store)
    programme_groups = [
        {'id': 'series', 'title': 'Series', 'href': '/series.html',
         'intro': md_plain((home.get('featured_series') or {}).get('intro')),
         'rows': [series_row(store, series, works) for series, works in groups['series']]},
        {'id': 'stage', 'title': 'Stage works', 'href': '/performance.html',
         'intro': md_plain((store['raw']['pages'].get('performance') or {}).get('projects', {}).get('intro')),
         'rows': [series_row(store, series, works) for series, works in groups['performance']]},
    ]
    selected = []
    for work_id in (home.get('selected_works') or {}).get('work_ids') or []:
        work = works_by_id.get(work_id)
        if work:
            selected.append({'work': work, 'series_title': (store['series_lookup'].get(work.get('series') or '') or {}).get('title', '')})
    statement = next((module for module in home.get('modules') or [] if isinstance(module, dict) and module.get('type') == 'text'), None)
    meta = dict(home['meta'])
    meta['canonical_path'] = ''
    return render_template(
        'pages/home.html',
        page_key='home',
        head=head_context('home', meta, preload_work=hero_work, preload_sizes='(min-width: 60rem) 70vw, 100vw'),
        **chrome_context(store, 'home'),
        hero={
            'work': hero_work,
            'title': hero_raw.get('title') or raw['site'].get('name'),
            'lead': lead_paragraphs,
            'actions': actions,
            'series_title': (store['series_lookup'].get((hero_work or {}).get('series') or '') or {}).get('title', ''),
        },
        programme_groups=programme_groups,
        selected=selected,
        selected_intro=md_plain((home.get('selected_works') or {}).get('intro')),
        statement=statement,
    )


def render_work_v2(store: dict[str, Any], work: dict[str, Any], neighbours: tuple[dict[str, Any] | None, dict[str, Any] | None], position: tuple[int, int]) -> str:
    series = store['series_lookup'].get(work.get('series') or '')
    site_name = str(SITE_CONTENT['site'].get('name') or 'STILLMRK')
    caption = RAW_CAPTIONS.get(work['id'], work.get('caption') or '')
    description = summarize_story_text(md_plain(caption) or work.get('alt') or '', fallback=work.get('alt') or '', limit=158)
    meta = {
        'title': f"{work['title']} - {site_name}",
        'description': description,
        'og_description': description,
        'og_image': image_path(work, preferred_width(work, 1200), 'jpg') if work.get('responsiveBase') else SITE_CONTENT['site']['og_image'],
        'og_image_alt': work.get('alt') or work['title'],
        'canonical_path': work_path(work['id']).lstrip('/'),
    }
    facts = [(label, value) for label, value in (('Year', work.get('year')), ('Place', work.get('location')), ('Medium', work.get('medium')), ('Edition', work.get('edition'))) if real_value(value)]
    previous, following = neighbours
    return render_template(
        'pages/work.html',
        page_key='work',
        head=head_context('work', meta, preload_work=work, preload_sizes='(min-width: 60rem) 72vw, 100vw', schema=work_schema(work, series), og_type='article'),
        **chrome_context(store, 'portfolio'),
        work=work,
        series=series,
        position=position[0],
        total=position[1],
        caption_paragraphs=_paragraphs(caption),
        facts=facts,
        inquiry_href=work_inquiry_href(work),
        previous=previous,
        following=following,
    )


def series_groups(store: dict[str, Any]) -> dict[str, list[tuple[dict[str, Any], list[dict[str, Any]]]]]:
    """Split public series into photographic series and stage works."""
    stage_slugs: list[str] = []
    for collection in store['site_data'].get('collections') or []:
        if collection.get('slug') == 'performance':
            stage_slugs = list(collection.get('seriesSlugs') or [])
    rows = public_series_works(store)
    by_slug = {series['slug']: (series, works) for series, works in rows}
    stage = [by_slug[slug] for slug in stage_slugs if slug in by_slug]
    photographic = [(series, works) for series, works in rows if series['slug'] not in stage_slugs]
    return {'series': photographic, 'performance': stage}


def series_row(store: dict[str, Any], series: dict[str, Any], works: list[dict[str, Any]]) -> dict[str, Any]:
    cover = store['works_by_id'].get(series.get('cardCoverWorkId') or series.get('coverWorkId') or '')
    summary = series.get('cardSummary') or summarize_story_text(series.get('description') or '', fallback=series.get('mood') or '', limit=170)
    return {'slug': series['slug'], 'title': series['title'], 'href': series_path(series['slug']), 'count': len(works),
            'years': series.get('years') or '', 'cover': cover, 'summary': md_plain(summary)}


def lead_paragraphs(text: Any) -> list[Any]:
    text = str(text or '')
    return _paragraphs(text) if '\n\n' in text else [part for part in split_home_hero_lead(text) if part]


def download_rows(store: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in store.get('public_downloads') or []:
        path = ROOT / str(item.get('file') or '').lstrip('/')
        size = ''
        if path.exists():
            kb = path.stat().st_size / 1024
            size = f'{kb / 1024:.1f} MB' if kb >= 1024 else f'{kb:.0f} KB'
        rows.append({'title': item.get('title'), 'file': item.get('file'), 'description': item.get('description') or '', 'size': size})
    return rows


SEQUENCE_SIZES = {
    'wide': '(min-width: 48rem) 80vw, 100vw',
    'left': '(min-width: 48rem) 48vw, 100vw',
    'right': '(min-width: 48rem) 48vw, 100vw',
    'solo-left': '(min-width: 48rem) 56vw, 100vw',
    'solo-right': '(min-width: 48rem) 56vw, 100vw',
}


def sequence_layouts(count: int) -> list[str]:
    """Hang a series as: one wide photograph, then a pair, repeating."""
    layouts: list[str] = []
    solo_turn = 0
    while len(layouts) < count:
        layouts.append('wide')
        remaining = count - len(layouts)
        if remaining >= 2:
            layouts += ['left', 'right']
        elif remaining == 1:
            layouts.append('solo-right' if solo_turn % 2 else 'solo-left')
            solo_turn += 1
    return layouts[:count]


def render_collection_v2(store: dict[str, Any], kind: str) -> str:
    raw = store['raw']
    page = raw['pages'][kind]
    hero = page.get('hero') or {}
    groups = series_groups(store)
    rows = [series_row(store, series, works) for series, works in groups[kind]]
    notes = None
    if kind == 'performance':
        structure = page.get('structure') or {}
        if structure.get('visible', True) and structure.get('cards'):
            notes = {'title': structure.get('title'), 'intro': md_plain(structure.get('intro')),
                     'cards': [{'title': card.get('title'), 'text': md_plain(card.get('text'))} for card in structure['cards']]}
        other = {'text': 'Looking for the landscape and street photographs?', 'label': 'See the series', 'href': '/series.html'}
    else:
        other = {'text': 'Theatre and performance projects are collected separately.', 'label': 'See the stage works', 'href': '/performance.html'}
    title = hero.get('title') or page.get('hero_title') or kind.title()
    return render_template(
        'pages/collection.html',
        page_key=kind,
        head=head_context(kind, page['meta']),
        **chrome_context(store, kind),
        title=title,
        lead=lead_paragraphs(hero.get('lead') or page.get('hero_lead')),
        rows=rows,
        notes=notes,
        other=other,
    )


def render_series_v2(store: dict[str, Any], series: dict[str, Any], works: list[dict[str, Any]],
                     neighbours: tuple[dict[str, Any] | None, dict[str, Any] | None], kind: str) -> str:
    section = {'label': 'Stage works', 'href': '/performance.html'} if kind == 'performance' else {'label': 'Series', 'href': '/series.html'}
    description = _paragraphs(RAW_SERIES_TEXT.get(series['slug'], {}).get('description') or series.get('description'))
    layouts = sequence_layouts(len(works))
    previous, following = neighbours
    return render_template(
        'pages/series.html',
        page_key='series',
        head=head_context('series', series_page_meta(store, store['raw']['pages']['series']['meta'], series, works),
                          preload_work=works[0] if works else None, preload_sizes=SEQUENCE_SIZES['wide'],
                          schema=series_schema(store, series, works)),
        **chrome_context(store, kind),
        section=section,
        series=series,
        works=works,
        description=description,
        opening=_paragraphs(series.get('storyOpeningText')),
        closing=_paragraphs(' '.join(part for part in (series.get('storySequenceText'), series.get('storyClosingText')) if part)),
        layouts=layouts,
        sizes=SEQUENCE_SIZES,
        inquiry_href=f"/contact.html?series={quote(series['slug'])}",
        previous=previous,
        following=following,
    )


def render_portfolio_v2(store: dict[str, Any]) -> str:
    raw = store['raw']
    page = raw['pages']['portfolio']
    hero = page.get('hero') or {}
    groups = series_groups(store)
    works = [work for _kind in ('series', 'performance') for _series, items in groups[_kind] for work in items]
    filter_groups = [
        {'label': 'Series', 'entries': [{'slug': s['slug'], 'title': s['title'], 'count': len(w)} for s, w in groups['series']]},
        {'label': 'Stage works', 'entries': [{'slug': s['slug'], 'title': s['title'], 'count': len(w)} for s, w in groups['performance']]},
    ]
    return render_template(
        'pages/portfolio.html',
        page_key='portfolio',
        head=head_context('portfolio', page['meta']),
        **chrome_context(store, 'portfolio'),
        title=hero.get('title') or 'Portfolio',
        lead=lead_paragraphs(hero.get('lead')),
        works=works,
        filter_groups=filter_groups,
        series_titles={series['slug']: series['title'] for series in store['public_series_list']},
    )


def render_about_v2(store: dict[str, Any]) -> str:
    raw = store['raw']
    page = raw['pages']['about']
    hero = page.get('hero') or {}
    statement = page.get('statement') or {}
    cta = page.get('cta') or {}
    return render_template(
        'pages/about.html',
        page_key='about',
        head=head_context('about', page['meta'], preload_work=store['works_by_id'].get(hero.get('feature_work_id') or ''), preload_sizes='(min-width: 60rem) 40vw, 100vw'),
        **chrome_context(store, 'about'),
        title=hero.get('title') or 'About',
        lead=lead_paragraphs(hero.get('lead')),
        work=store['works_by_id'].get(hero.get('feature_work_id') or ''),
        statement={'title': statement.get('title'), 'text': _paragraphs(statement.get('text'))} if statement.get('title') else None,
        practice=[{'title': card.get('title'), 'text': md_plain(card.get('text'))} for card in page.get('practice_cards') or []],
        downloads=download_rows(store),
        cta={'title': cta.get('title'), 'text': md_plain(cta.get('text'))} if cta.get('title') else None,
    )


def render_contact_v2(store: dict[str, Any]) -> str:
    from markupsafe import Markup
    raw = store['raw']
    page = raw['pages']['contact']
    hero = page.get('hero') or {}
    return render_template(
        'pages/contact.html',
        page_key='contact',
        head=head_context('contact', page['meta']),
        **chrome_context(store, 'contact'),
        title=hero.get('title') or 'Contact',
        lead=lead_paragraphs(hero.get('lead')),
        topics=list(page.get('inquiry_types') or ['General']),
        downloads=download_rows(store),
        work_titles=Markup(json_ld({work['id']: work['title'] for work in store['site_data']['works']})),
        series_titles_json=Markup(json_ld({series['slug']: series['title'] for series in store['public_series_list']})),
    )


def render_404_v2(store: dict[str, Any]) -> str:
    site_name = str(SITE_CONTENT['site'].get('name') or 'STILLMRK')
    meta = {'title': f'Page not found - {site_name}', 'description': 'This address does not exist on the site.', 'canonical_path': '404.html'}
    head = head_context('404', meta)
    head['robots'] = 'noindex'
    return render_template('pages/404.html', page_key='404', head=head, **chrome_context(store, ''))


PLACEHOLDER_VALUES = {'', 'unspecified', 'unknown', 'n/a', 'na', 'none', '-', 'tbd'}


def real_value(value: Any) -> str:
    """Return the value as text, or '' when it is a placeholder like 'Unspecified'."""
    text = str(value or '').strip()
    return '' if text.lower() in PLACEHOLDER_VALUES else text


def work_schema(work: dict[str, Any], series: dict[str, Any] | None) -> dict[str, Any]:
    site_url = _site_url()
    schema = {
        '@context': 'https://schema.org',
        '@type': 'VisualArtwork',
        'name': work['title'],
        'description': md_plain(RAW_CAPTIONS.get(work['id'], work.get('caption') or '')) or work.get('alt') or '',
        'url': absolute_url(work_path(work['id']).lstrip('/'), site_url),
        'image': _image_url(work) if work.get('responsiveBase') else None,
        'artform': 'Photography',
        'artMedium': work.get('medium') or 'Monochrome photograph',
        'creator': {'@id': f'{site_url}#person'},
        'dateCreated': real_value(work.get('year')) or None,
        'contentLocation': real_value(work.get('location')) or None,
        'isPartOf': {'@type': 'CreativeWorkSeries', 'name': series['title'], 'url': absolute_url(series_path(series['slug']).lstrip('/'), site_url)} if series else None,
    }
    return {key: value for key, value in schema.items() if value}


def public_series_works(store: dict[str, Any]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    rows = []
    for series in store['public_series_list']:
        works = [store['works_by_id'][work_id] for work_id in series['_work_ids'] if work_id in store['works_by_id']]
        rows.append((series, works))
    return rows


def write_all() -> None:
    started = time.perf_counter()
    store = normalize_content(SITE_CONTENT)
    cleanup_report = prune_generated_responsive_assets(store['generated_assets'])
    write_image_manifests(store, cleanup_report)

    if ensure_og_images_from_content:
        try:
            ensure_og_images_from_content(SITE_CONTENT, force=False)
        except Exception as exc:  # social cards are optional; the site is not
            print(f"[STILLMRK build] Warning: social card generation failed: {exc}", flush=True)

    PUBLIC_SERIES_SLUGS[:] = [series['slug'] for series in store['public_series_list']]
    prepare_dist()
    groups = series_groups(store)
    pages = {
        'index.html': render_home_v2(store),
        'portfolio.html': render_portfolio_v2(store),
        'series.html': render_collection_v2(store, 'series'),
        'performance.html': render_collection_v2(store, 'performance'),
        'about.html': render_about_v2(store),
        'contact.html': render_contact_v2(store),
        '404.html': render_404_v2(store),
    }
    extra_paths: list[str] = []
    for kind, rows in groups.items():
        for position, (series, works) in enumerate(rows):
            neighbours = (rows[position - 1][0] if position > 0 else None, rows[position + 1][0] if position + 1 < len(rows) else None)
            pages[f"series/{series['slug']}/index.html"] = render_series_v2(store, series, works, neighbours, kind)
            extra_paths.append(series_path(series['slug']))
            for index, work in enumerate(works):
                previous = works[index - 1] if index > 0 else None
                following = works[index + 1] if index + 1 < len(works) else None
                pages[f"works/{work['id']}/index.html"] = render_work_v2(store, work, (previous, following), (index + 1, len(works)))
                extra_paths.append(work_path(work['id']))
    for relative, html_text in pages.items():
        write_dist_file(relative, rootify_html(html_text))
    write_dist_file('robots.txt', render_robots_txt())
    write_dist_file('sitemap.xml', render_sitemap_xml(extra_paths))
    print(f"[STILLMRK build] Pages: {len(pages)} written ({len(store['public_series_list'])} series, {sum(1 for p in pages if p.startswith('works/'))} works).", flush=True)
    write_dist_file('site.webmanifest', render_site_manifest())

    report = write_build_metadata(store)
    write_upload_manifest(store, report)

    missing_assets = list(store.get('missing_assets') or [])
    if missing_assets:
        print(f"[STILLMRK build] Warning: {len(missing_assets)} work(s) are metadata-only because no source image is assigned yet.", flush=True)
    elapsed = time.perf_counter() - started
    print(f"[STILLMRK build] Images: {IMAGE_STATS['rendered']} rendered, {IMAGE_STATS['cached']} reused from cache.", flush=True)
    print(f"[STILLMRK build] Site rebuilt successfully in {elapsed:.1f}s -> dist/", flush=True)


def validate_only() -> None:
    global IMAGE_MODE
    IMAGE_MODE = 'validate'
    started = time.perf_counter()
    normalize_content(SITE_CONTENT)  # also runs validate_runtime_store()
    print(f"[STILLMRK build] Content validation passed in {time.perf_counter() - started:.1f}s.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description='Build STILLMRK from YAML content files into dist/.')
    parser.add_argument('--validate-only', action='store_true', help='Check content and references without rendering images or writing output.')
    args = parser.parse_args()
    if args.validate_only:
        validate_only()
        return
    write_all()


if __name__ == '__main__':
    main()
