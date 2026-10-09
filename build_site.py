from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
import stat
import re
import shutil
from datetime import datetime, timezone
from collections import Counter
from urllib.parse import quote, urlparse
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from PIL import Image, ImageOps, ImageDraw, ImageFont

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
IMAGE_DERIVATIVE_EXTENSIONS = {'.jpg', '.jpeg', '.webp'}
BUILD_META_DIR = BUILD_STATE_DIR / 'meta'
BUILD_STATUS_PATH = BUILD_META_DIR / 'build-status.json'
CONTENT_GRAPH_PATH = BUILD_META_DIR / 'content-graph.json'
RELEASE_REPORT_PATH = BUILD_META_DIR / 'release-report.json'
PUBLIC_UPLOAD_DIR = ROOT / 'public_upload'
PUBLIC_UPLOAD_INSTRUCTIONS_PATH = ROOT / 'HOST_UPLOAD_INSTRUCTIONS.txt'

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

    if ensure_og_images_from_content:
        try:
            ensure_og_images_from_content(content, force=False)
        except Exception:
            pass

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


def root_public_path(path: str) -> str:
    cleaned = str(path or '').strip().lstrip('/')
    return f'/{cleaned}' if cleaned else '/'


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

def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def classes(*values: str | None) -> str:
    return " ".join(value for value in values if value)


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


def _placeholder_canvas(width: int, height: int, label: str, detail: str = '') -> Image.Image:
    image = Image.new('RGB', (width, height), '#11161b')
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.load_default()
        meta_font = ImageFont.load_default()
    except Exception:  # pragma: no cover
        title_font = None
        meta_font = None
    draw.rectangle((0, 0, width - 1, height - 1), outline='#2f3945', width=3)
    accent_y = max(24, height // 2 - 40)
    draw.line((width * 0.18, accent_y, width * 0.82, accent_y), fill='#697786', width=2)
    draw.line((width * 0.18, accent_y + 14, width * 0.72, accent_y + 14), fill='#3d4753', width=2)
    title = 'Image unavailable'
    bbox = draw.textbbox((0, 0), title, font=title_font) if title_font else (0, 0, 180, 20)
    title_x = max(32, (width - (bbox[2] - bbox[0])) // 2)
    title_y = min(height - 120, accent_y + 48)
    draw.text((title_x, title_y), title, fill='#d7e1ec', font=title_font)
    subtitle = label[:72]
    bbox2 = draw.textbbox((0, 0), subtitle, font=meta_font) if meta_font else (0, 0, 160, 20)
    sub_x = max(32, (width - (bbox2[2] - bbox2[0])) // 2)
    draw.text((sub_x, title_y + 24), subtitle, fill='#9fb0c0', font=meta_font)
    if detail:
        detail_text = detail[:96]
        bbox3 = draw.textbbox((0, 0), detail_text, font=meta_font) if meta_font else (0, 0, 160, 20)
        det_x = max(32, (width - (bbox3[2] - bbox3[0])) // 2)
        draw.text((det_x, title_y + 48), detail_text, fill='#718396', font=meta_font)
    return image


def build_placeholder_image_meta(work_entry: dict[str, Any], image_config: dict[str, Any], generated_assets: set[str], detail: str = '') -> dict[str, Any]:
    series_slug = str(image_config.get('series') or resolve_series_slug_for_work(work_entry) or 'unassigned').strip() or 'unassigned'
    render_slug = str(image_config.get('render_name') or work_entry.get('render_name') or work_entry['id']).strip().replace('\\', '/').strip('/')
    render_name = render_slug.replace('/', '-') or work_entry['id']
    work_output_dir = current_generated_root() / series_slug / render_name
    responsive_base_path = work_output_dir / render_name
    work_output_dir.mkdir(parents=True, exist_ok=True)

    intrinsic_width, intrinsic_height = PLACEHOLDER_INTRINSIC_SIZE
    canvas = _placeholder_canvas(intrinsic_width, intrinsic_height, str(work_entry.get('title') or work_entry.get('id') or 'Work'), str(work_entry.get('id') or ''))
    target_widths = [width for width in RESPONSIVE_WIDTHS if width < intrinsic_width]
    target_widths.append(intrinsic_width)
    target_widths = sorted(set(int(width) for width in target_widths))
    jpg_quality = int(IMAGE_PIPELINE.get('jpg_quality', DEFAULT_IMAGE_PIPELINE['jpg_quality']))
    webp_quality = int(IMAGE_PIPELINE.get('webp_quality', DEFAULT_IMAGE_PIPELINE['webp_quality']))

    for width in target_widths:
        if width == intrinsic_width:
            variant = canvas.copy()
        else:
            height = max(1, round(intrinsic_height * width / intrinsic_width))
            variant = canvas.resize((width, height), Image.Resampling.LANCZOS)
        jpg_path = work_output_dir / f'{render_name}-{width}.jpg'
        webp_path = work_output_dir / f'{render_name}-{width}.webp'
        variant.save(jpg_path, format='JPEG', quality=jpg_quality, optimize=True, progressive=True)
        variant.save(webp_path, format='WEBP', quality=webp_quality, method=6)
        generated_assets.add(relative_asset_path(jpg_path))
        generated_assets.add(relative_asset_path(webp_path))

    _record_missing_asset(work_entry, series_slug, render_name, detail or 'placeholder generated')
    print(f"[STILLMRK build] Warning: missing source for {work_entry.get('id', 'unknown')} — using generated placeholder.", flush=True)

    return {
        'width': intrinsic_width,
        'height': intrinsic_height,
        'src': relative_asset_path(work_output_dir / f'{render_name}-{intrinsic_width}.jpg'),
        'responsiveBase': relative_asset_path(responsive_base_path),
        'sourceOriginal': '',
        'renderName': render_name,
        'seriesSlug': series_slug,
        'missingSource': True,
        'missingSourceDetail': detail or 'placeholder generated',
    }



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



def hash_access_code(value: Any) -> str:
    text_value = str(value or '').strip()
    return hashlib.sha256(text_value.encode('utf-8')).hexdigest() if text_value else ''


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


def existing_generated_image_meta(work_entry: dict[str, Any], image_config: dict[str, Any], generated_assets: set[str]) -> dict[str, Any] | None:
    series_slug = str(image_config.get('series') or resolve_series_slug_for_work(work_entry) or 'unassigned').strip() or 'unassigned'
    render_slug = str(image_config.get("render_name") or work_entry.get('render_name') or work_entry["id"]).strip().replace("\\", "/").strip("/")
    render_name = render_slug.replace('/', '-') or work_entry['id']
    work_output_dir = current_generated_root() / series_slug / render_name
    responsive_base_path = work_output_dir / render_name
    if not work_output_dir.exists():
        return None

    jpg_variants = sorted(work_output_dir.glob(f"{render_name}-*.jpg"), key=lambda path: int(path.stem.rsplit('-', 1)[-1]) if path.stem.rsplit('-', 1)[-1].isdigit() else -1)
    webp_variants = sorted(work_output_dir.glob(f"{render_name}-*.webp"), key=lambda path: int(path.stem.rsplit('-', 1)[-1]) if path.stem.rsplit('-', 1)[-1].isdigit() else -1)
    if not jpg_variants and not webp_variants:
        return None

    for path in jpg_variants + webp_variants:
        generated_assets.add(relative_asset_path(path))

    probe_path = jpg_variants[-1] if jpg_variants else webp_variants[-1]
    with Image.open(probe_path) as probe:
        intrinsic_width, intrinsic_height = probe.size

    largest_jpg = jpg_variants[-1] if jpg_variants else probe_path
    return {
        "width": intrinsic_width,
        "height": intrinsic_height,
        "src": relative_asset_path(largest_jpg),
        "responsiveBase": relative_asset_path(responsive_base_path),
        "sourceOriginal": str(image_config.get('source') or image_config.get('original') or image_config.get('master') or ''),
        "renderName": render_name,
        "seriesSlug": series_slug,
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

    prepared = prepare_source_image(source_path)
    intrinsic_width, intrinsic_height = prepared.size

    target_widths = [width for width in RESPONSIVE_WIDTHS if width < intrinsic_width]
    target_widths.append(intrinsic_width)
    target_widths = sorted(set(int(width) for width in target_widths))

    series_slug = str(image_config.get('series') or resolve_series_slug_for_work(work_entry) or 'unassigned').strip() or 'unassigned'
    render_slug = str(image_config.get("render_name") or work_entry.get('render_name') or work_entry["id"]).strip().replace("\\", "/").strip("/")
    render_name = render_slug.replace('/', '-') or work_entry['id']
    work_output_dir = current_generated_root() / series_slug / render_name
    responsive_base_path = work_output_dir / render_name
    work_output_dir.mkdir(parents=True, exist_ok=True)

    source_mtime = source_path.stat().st_mtime_ns
    jpg_quality = int(IMAGE_PIPELINE.get("jpg_quality", DEFAULT_IMAGE_PIPELINE["jpg_quality"]))
    webp_quality = int(IMAGE_PIPELINE.get("webp_quality", DEFAULT_IMAGE_PIPELINE["webp_quality"]))
    force_rebuild = bool(image_config.get("force_rebuild", False))

    for width in target_widths:
        if width == intrinsic_width:
            variant = prepared.copy()
        else:
            height = max(1, round(intrinsic_height * width / intrinsic_width))
            variant = prepared.resize((width, height), Image.Resampling.LANCZOS)

        jpg_path = work_output_dir / f"{render_name}-{width}.jpg"
        webp_path = work_output_dir / f"{render_name}-{width}.webp"

        jpg_is_current = jpg_path.exists() and jpg_path.stat().st_mtime_ns >= source_mtime
        webp_is_current = webp_path.exists() and webp_path.stat().st_mtime_ns >= source_mtime

        if force_rebuild or not jpg_is_current:
            variant.save(jpg_path, format="JPEG", quality=jpg_quality, optimize=True, progressive=True)

        if force_rebuild or not webp_is_current:
            variant.save(webp_path, format="WEBP", quality=webp_quality, method=6)

        generated_assets.add(relative_asset_path(jpg_path))
        generated_assets.add(relative_asset_path(webp_path))

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
            "caption": str(entry.get('caption') or '').strip(),
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
        series_list.append(
            {
                "slug": series["slug"],
                "title": series["title"],
                "years": series["years"],
                "mood": series["mood"],
                "description": series["description"],
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
                "accessHash": hash_access_code(series.get('access_code')),
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


def admin_route(collection: str, entry_key: str | None = None) -> str:
    base = f"#/collections/{collection}"
    return f"{base}/entries/{entry_key}" if entry_key else base


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
        sitemap_text = (ROOT / 'sitemap.xml').read_text(encoding='utf-8') if (ROOT / 'sitemap.xml').exists() else ''
        add_check('Sitemap present for indexable build', '<urlset' in sitemap_text, 'Indexable builds should emit a sitemap.')
    else:
        add_check('Sitemap intentionally suppressed', '<!-- STILLMRK sitemap is intentionally disabled' in (ROOT / 'sitemap.xml').read_text(encoding='utf-8'), 'Non-indexable builds suppress the sitemap on purpose.')

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


def write_public_upload_bundle(store: dict[str, Any], report: dict[str, Any]) -> None:
    reset_directory(PUBLIC_UPLOAD_DIR)

    top_level_files = [
        'index.html',
        'portfolio.html',
        'series.html',
        'performance.html',
        'about.html',
        'contact.html',
        '404.html',
        'robots.txt',
        'sitemap.xml',
        'site.webmanifest',
    ]
    for relative in top_level_files:
        source = ROOT / relative
        if source.exists():
            shutil.copy2(source, PUBLIC_UPLOAD_DIR / relative)

    assets_source = ROOT / 'assets'
    if assets_source.exists():
        def ignore_assets(_current_dir: str, names: list[str]) -> set[str]:
            blocked = {'incoming', 'originals', 'manifests'}
            return {name for name in names if name in blocked}

        shutil.copytree(assets_source, PUBLIC_UPLOAD_DIR / 'assets', dirs_exist_ok=True, ignore=ignore_assets)

    # Public data is the hard dependency for every gallery module. Keep this
    # copy explicit instead of relying on broad copytree behaviour so a future
    # asset ignore rule cannot silently ship an empty portfolio.
    data_source = ROOT / 'assets/js/data.js'
    data_target = PUBLIC_UPLOAD_DIR / 'assets/js/data.js'
    if not data_source.exists():
        raise FileNotFoundError(f"Generated site data is missing: {data_source.relative_to(ROOT).as_posix()}")
    data_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(data_source, data_target)

    required_public_assets = [data_target]
    missing_public_assets = [path.relative_to(ROOT).as_posix() for path in required_public_assets if not path.exists() or path.stat().st_size <= 0]
    if missing_public_assets:
        raise RuntimeError('Public upload integrity failed: ' + ', '.join(missing_public_assets))

    manifest = {
        'generatedAt': iso_timestamp(),
        'environment': report.get('environment') or store['site_data']['site']['environment'],
        'siteUrl': store['site_data']['site']['siteUrl'],
        'displayUrl': store['site_data']['site']['displayUrl'],
        'allowIndexing': store['site_data']['site']['allowIndexing'],
        'uploadFolder': 'public_upload',
        'uploadOnly': [
            'index.html',
            'portfolio.html',
            'series.html',
            'performance.html',
            'about.html',
            'contact.html',
            '404.html',
            'robots.txt',
            'sitemap.xml',
            'site.webmanifest',
            'assets/',
        ],
    }
    (PUBLIC_UPLOAD_DIR / 'upload-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding='utf-8')


def write_public_upload_instructions(store: dict[str, Any], report: dict[str, Any]) -> None:
    site = store['site_data']['site']
    lines = [
        'STILLMRK public site workflow',
        '',
        'This package builds a static public portfolio. Upload only the contents of the public_upload folder to your host.',
        '',
        f"Target public URL: {site['siteUrl'] or site['displayUrl'] or 'unset'}",
        f"Environment: {site['environment']}",
        f"Indexing enabled: {'yes' if site['allowIndexing'] else 'no'}",
        f"Last build (UTC): {report.get('generatedAt') or iso_timestamp()}",
        '',
        'Local preview:',
        '1. Run: python preview_server.py',
        '2. Open: http://127.0.0.1:8000/',
        '3. Edit content files locally and run python build_site.py when needed.',
        '',
        'Upload step:',
        '1. Open the public_upload folder in this project.',
        '2. Upload its contents to the host root with FileZilla.',
        '3. Do not upload content/ or the Python source files to the host.',
        '',
        'The public_upload folder is regenerated every time python build_site.py succeeds.',
        f"Missing-image placeholders used: {len(report.get('missingImages') or [])}",
    ]
    PUBLIC_UPLOAD_INSTRUCTIONS_PATH.write_text("\n".join(lines) + "\n", encoding='utf-8')

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


def compareable_title(value: str) -> str:
    return value.casefold()


def series_path(slug: str) -> str:
    return f"series.html?series={slug}"


def portfolio_path(slug: str | None = None) -> str:
    return f"portfolio.html?series={slug}" if slug else "portfolio.html"


def collection_path(slug: str) -> str:
    return f"{slug}.html"


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


def aspect_ratio(work: dict[str, Any], context: str = "default") -> str:
    ratios = work.get('displayRatios') if isinstance(work.get('displayRatios'), dict) else {}
    fallback = f"{work['width']} / {work['height']}"
    return normalize_ratio_value(ratios.get(context) or ratios.get('default'), fallback)


def orientation(work: dict[str, Any]) -> str:
    ratio = work["width"] / work["height"]
    if ratio > 1.12:
        return "landscape"
    if ratio < 0.88:
        return "portrait"
    return "square"


def object_position(work: dict[str, Any]) -> str:
    focal_point = work.get('focalPoint') or {'x': 50, 'y': 50}
    x_value = clamp_percentage(focal_point.get('x'), 50)
    y_value = clamp_percentage(focal_point.get('y'), 50)
    return f"{x_value}% {y_value}%"


def media_attrs(work: dict[str, Any], class_name: str, context: str = 'default') -> str:
    return f'class="{class_name}" style="--media-ratio: {aspect_ratio(work, context)}; --media-position: {object_position(work)};" data-orientation="{orientation(work)}" data-protect-media="true"'


def responsive_image_html(work: dict[str, Any], sizes: str, loading: str = "lazy", fetchpriority: str = "auto") -> str:
    jpg_srcset = source_set(work, "jpg")
    webp_srcset = source_set(work, "webp")
    priority_attr = f' fetchpriority="{fetchpriority}"' if fetchpriority != "auto" else ""
    has_image = bool(jpg_srcset and webp_srcset) or bool(str(work.get('src') or '').strip())

    if not has_image:
        return f"""
            <div class=\"media-placeholder\" role=\"img\" aria-label=\"{esc(work.get('alt') or work.get('title') or 'Image pending')}\">
              <span>Image pending</span>
              <strong>{esc(work.get('title') or 'Untitled work')}</strong>
              <small>{esc(work.get('alt') or 'No image assigned yet.')}</small>
            </div>
        """.strip()

    if jpg_srcset and webp_srcset:
        return f"""
            <picture>
              <source type=\"image/webp\" srcset=\"{esc(webp_srcset)}\" sizes=\"{esc(sizes)}\">
              <img
                src=\"{esc(image_path(work, preferred_width(work), 'jpg'))}\"
                srcset=\"{esc(jpg_srcset)}\"
                sizes=\"{esc(sizes)}\"
                width=\"{work['width']}\"
                height=\"{work['height']}\"
                alt=\"{esc(work['alt'])}\"
                loading=\"{loading}\"
                decoding=\"async\" draggable=\"false\"{priority_attr}>
            </picture>
        """.strip()

    return f"""
        <img
          src=\"{esc(work.get('src') or '')}\"
          width=\"{work['width']}\"
          height=\"{work['height']}\"
          alt=\"{esc(work['alt'])}\"
          loading=\"{loading}\"
          decoding=\"async\" draggable=\"false\"{priority_attr}>
    """.strip()

def render_media_caption(label: str = '', title: str = '', meta: str = '') -> str:
    parts: list[str] = []
    if str(label).strip():
        parts.append(f'<span>{esc(label)}</span>')
    if str(title).strip():
        parts.append(f'<strong>{esc(title)}</strong>')
    if str(meta).strip():
        parts.append(f'<small>{esc(meta)}</small>')
    return f'<figcaption class="media-caption">{"".join(parts)}</figcaption>' if parts else ''



def work_caption_or_fallback(work: dict[str, Any], fallback: str = '') -> str:
    caption = str(work.get('caption') or '').strip()
    return caption or fallback


def work_media_meta(work: dict[str, Any], series_lookup: dict[str, dict[str, Any]], include_series: bool = True) -> str:
    fallback_parts: list[str] = []
    if include_series:
        series = series_lookup.get(work['series'])
        fallback_parts.append(f"{series['title'] if series else 'Series'} series")
    if str(work.get('location') or '').strip():
        fallback_parts.append(str(work['location']))
    if str(work.get('year') or '').strip():
        fallback_parts.append(str(work['year']))
    fallback = " / ".join([part for part in fallback_parts if str(part).strip()])
    return work_caption_or_fallback(work, fallback)

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


def work_layout_token(work: dict[str, Any], context: str, fallback: str = "auto") -> str:
    direct_key = "portfolioLayout" if context == "portfolio" else "seriesLayout"
    token = normalize_layout_token(work.get(direct_key), "auto")
    if token != "auto":
        return token
    layouts = work.get("displayLayouts") if isinstance(work.get("displayLayouts"), dict) else {}
    token = normalize_layout_token(layouts.get(context), "auto")
    return token if token != "auto" else fallback


def portfolio_card_variant(index: int, total: int, work: dict[str, Any] | None = None) -> str:
    if work:
        override = work_layout_token(work, "portfolio", "auto")
        if override != "auto":
            return override

    if index == 0:
        return "lead"
    if index == 1:
        return "accent"
    if total <= 2:
        return "standard"

    remaining = max(total - 2, 0)
    relative_index = max(index - 2, 0)
    full_rows, remainder = divmod(remaining, 3)
    cutoff = full_rows * 3

    if relative_index < cutoff:
        return "standard"

    if remainder == 1:
        return "standard"
    if remainder == 2:
        return "twin"
    return "standard"


def portfolio_card_sizes(variant: str) -> str:
    return {
        "quiet": "(min-width: 1180px) 24vw, (min-width: 760px) 46vw, 100vw",
        "standard": "(min-width: 1180px) 30vw, (min-width: 760px) 46vw, 100vw",
        "medium": "(min-width: 1180px) 38vw, (min-width: 760px) 92vw, 100vw",
        "large": "(min-width: 1180px) 46vw, (min-width: 760px) 92vw, 100vw",
        "wide": "(min-width: 1180px) 62vw, (min-width: 760px) 92vw, 100vw",
        "full": "(min-width: 1180px) 92vw, (min-width: 760px) 100vw, 100vw",
        "lead": "(min-width: 1180px) 46vw, (min-width: 760px) 92vw, 100vw",
        "accent": "(min-width: 1180px) 46vw, (min-width: 760px) 92vw, 100vw",
        "twin": "(min-width: 1180px) 30vw, (min-width: 760px) 46vw, 100vw",
    }.get(variant, "(min-width: 1180px) 30vw, (min-width: 760px) 46vw, 100vw")


def portfolio_layout_class(variant: str) -> str:
    canonical = {
        "lead": "large",
        "accent": "large",
        "twin": "standard",
    }.get(variant, variant)
    canonical = normalize_layout_token(canonical, "standard")
    return f" work-card--layout-{canonical}"


def portfolio_card_summary(series: dict[str, Any] | None, work: dict[str, Any], variant: str) -> str:
    caption = str(work.get('caption') or '').strip()
    if caption:
        return caption
    series_title = series['title'] if series else 'Series'
    if variant == 'lead':
        return f"Featured work · {series_title} · {work['location']}"
    if variant == 'accent':
        return f"{series_title} · {work['location']} · {work['year']}"
    return f"{series_title} · {work['location']}"

def lightbox_meta(work: dict[str, Any], series_lookup: dict[str, dict[str, Any]]) -> str:
    return work_media_meta(work, series_lookup, include_series=True)


def lightbox_attrs(work: dict[str, Any], series_lookup: dict[str, dict[str, Any]], group: str, sizes: str) -> str:
    return " ".join(
        [
            f'data-lightbox-group="{esc(group)}"',
            f'data-lightbox-src="{esc(image_path(work, largest_available_width(work), "jpg"))}"',
            f'data-lightbox-jpg-srcset="{esc(source_set(work, "jpg"))}"',
            f'data-lightbox-webp-srcset="{esc(source_set(work, "webp"))}"',
            f'data-lightbox-sizes="{esc(sizes)}"',
            f'data-lightbox-alt="{esc(work["alt"])}"',
            f'data-lightbox-title="{esc(work["title"])}"',
            f'data-lightbox-meta="{esc(lightbox_meta(work, series_lookup))}"',
            f'data-lightbox-caption="{esc(work.get("caption") or "")}"',
            f'data-lightbox-width="{work["width"]}"',
            f'data-lightbox-height="{work["height"]}"',
        ]
    )


def render_actions(actions: list[dict[str, str]]) -> str:
    parts = []
    for item in actions:
        style = item.get("style", "primary")
        class_name = "button"
        if style == "secondary":
            class_name = "button button--secondary"
        elif style == "ghost":
            class_name = "button button--ghost"
        parts.append(f'<a class="{class_name}" href="{esc(item["href"])}">{esc(item["label"])}</a>')
    return "\n".join(parts)




def resolve_page_downloads(store: dict[str, Any], document_block: dict[str, Any] | None, *, limit: int | None = None) -> list[dict[str, Any]]:
    block = dict(document_block or {})
    public_downloads = list(store.get("public_downloads") or [])
    downloads_by_id = dict(store.get("downloads_by_id") or {})
    selected_ids = [str(item).strip() for item in (block.get("document_ids") or []) if str(item).strip()]
    if selected_ids:
        rows: list[dict[str, Any]] = []
        for ident in selected_ids:
            row = downloads_by_id.get(ident)
            if isinstance(row, dict):
                rows.append(dict(row))
        downloads = rows or public_downloads
    else:
        downloads = public_downloads
    if limit is not None:
        return downloads[:limit]
    return downloads


def render_download_cards(downloads: list[dict[str, Any]], compact: bool = False) -> str:
    cards: list[str] = []
    for item in downloads:
        if compact:
            cards.append(
                f'<a class="contact-downloads__item" href="{esc(item["file"])}" target="_blank" rel="noreferrer"><strong>{esc(item["title"])}</strong><span>{esc(item.get("description") or "")}</span></a>'
            )
        else:
            cards.append(
                f'''<article class="download-card panel reveal"><p class="eyebrow">{esc(item.get("kind") or "Document")}</p><h3>{esc(item["title"])}</h3><p>{esc(item.get("description") or "")}</p><a class="button button--secondary" href="{esc(item["file"])}" target="_blank" rel="noreferrer">Open document</a></article>'''
            )
    return ''.join(cards)

def _visible_nav_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in raw.get('navigation') or []:
        if not isinstance(entry, dict):
            continue
        if entry.get('visible', True) is False:
            continue
        items.append(entry)
    return items


def render_nav(raw: dict[str, Any]) -> str:
    nav_links = []
    site_name = str(raw['site'].get('name') or 'STILLMRK').strip()
    for item in _visible_nav_items(raw):
        nav_links.append(f'<a href="{esc(item["href"])}" data-page="{esc(item["page"])}">{esc(item["label"])}</a>')

    return f"""
    <header class="site-header" data-site-header>
      <div class="nav-shell">
        <a class="brand" href="index.html" aria-label="Go to {esc(site_name)} homepage">
          <span class="brand__eyebrow">{esc(site_name)}</span>
          <span class="brand__name">{esc(str(raw['artist'].get('header_label') or raw['artist']['name']))}</span>
        </a>

        <button class="nav-toggle" type="button" aria-label="Open menu" aria-expanded="false" aria-controls="primary-nav" aria-haspopup="true">
          <span></span>
        </button>

        <nav class="site-nav" id="primary-nav" aria-label="Primary navigation">
          {'\n          '.join(nav_links)}
        </nav>
      </div>
    </header>
    """.strip()


def render_footer_wordmark(site_name: str) -> str:
    normalized = site_name.strip()
    if normalized.upper() == 'STILLMRK':
        return (
            '<span class="footer-wordmark footer-wordmark--colophon" aria-label="Stillmark">'
            '<span class="footer-wordmark__overline" aria-hidden="true">STILLMRK</span>'
            '<span class="footer-wordmark__name" aria-hidden="true">'
            '<span class="footer-wordmark__still">Still</span>'
            '<span class="footer-wordmark__mark">mark</span>'
            '</span>'
            '<span class="footer-wordmark__trace" aria-hidden="true"><span></span></span>'
            '</span>'
        )
    return esc(normalized)


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


def _footer_links(raw: dict[str, Any]) -> list[dict[str, str]]:
    site = raw.get('site') if isinstance(raw.get('site'), dict) else {}
    configured = site.get('footer_links') if isinstance(site.get('footer_links'), list) else []
    links: list[dict[str, str]] = []
    for entry in configured:
        if not isinstance(entry, dict):
            continue
        if entry.get('visible', True) is False:
            continue
        href = str(entry.get('href') or '').strip()
        label = str(entry.get('label') or '').strip()
        if href and label:
            links.append({'label': label, 'href': href})
    if links:
        return links
    return [
        {'label': 'Portfolio', 'href': 'portfolio.html'},
        {'label': 'Series', 'href': 'series.html'},
        {'label': 'About', 'href': 'about.html'},
        {'label': 'Contact', 'href': 'contact.html'},
    ]


def render_footer(raw: dict[str, Any]) -> str:
    artist = raw["artist"]
    site = raw.get('site') if isinstance(raw.get('site'), dict) else {}
    site_name = str(site.get('name') or 'STILLMRK').strip()
    identity = build_public_identity(raw)
    email = str(identity.get('email') or '').strip()
    footer_text = str(site.get('footer_text') or artist.get('tagline') or '').strip()
    footer_microcopy = str(site.get('footer_microcopy') or '').strip()
    footer_contact_text = str(site.get('footer_contact_text') or '').strip()
    copyright_text = str(site.get('copyright_text') or '© <span data-year></span>').strip()
    footer_contact = (
        f'<a href="mailto:{esc(email)}" data-artist-email>{esc(email)}</a>'
        if has_public_contact_email(email)
        else '<a data-artist-email>Available on request</a>'
    )
    footer_wordmark = render_footer_wordmark(site_name)
    footer_links_html = ''.join(f'<a href="{esc(item["href"])}">{esc(item["label"])}</a>' for item in _footer_links(raw))
    social_links_html = ''.join(f'<a href="{esc(item["href"])}" target="_blank" rel="noreferrer">{esc(item["label"])}</a>' for item in _artist_social_links(artist))
    contact_label_html = f'<p>{esc(footer_contact_text)}</p>' if footer_contact_text else ''
    microcopy_html = f'<p>{esc(footer_microcopy)}</p>' if footer_microcopy else ''
    return f"""
    <footer class="site-footer">
      <div class="footer-shell">
        <div class="footer-copy">
          <strong>{footer_wordmark}</strong>
          {f'<p>{esc(footer_text)}</p>' if footer_text else ''}
          {microcopy_html}
          {contact_label_html}
          {footer_contact}
        </div>
        <div class="footer-links">
          {footer_links_html}
          {social_links_html}
          <span>{copyright_text}</span>
        </div>
      </div>
    </footer>
    """.strip()


def render_protocol_notice() -> str:
    return """
      <div class="container">
        <div class="protocol-warning" data-protocol-warning role="status" hidden>
          <strong>Local preview note</strong>
          Open this folder through the local preview server such as <code>python preview_server.py</code>. JavaScript modules will not fully render through <code>file:///</code>.
        </div>
      </div>
    """.strip()


def render_lightbox() -> str:
    return """
    <dialog class="lightbox" data-lightbox role="dialog" aria-hidden="true" aria-modal="true" aria-labelledby="lightbox-title" aria-describedby="lightbox-meta lightbox-hint">
      <div class="lightbox__topbar">
        <div class="lightbox__support">
          <p class="lightbox__counter" id="lightbox-counter" data-lightbox-counter aria-live="polite">01 / 01</p>
          <p class="lightbox__hint" id="lightbox-hint">Use the arrow keys or swipe to move through the sequence. Press Escape to close.</p>
        </div>
        <button class="lightbox__close" type="button" data-lightbox-close aria-label="Close image viewer">Close</button>
      </div>
      <div class="lightbox__stage">
        <button class="lightbox__nav" type="button" data-lightbox-prev aria-label="Previous photograph">‹</button>
        <figure class="lightbox__figure" data-lightbox-figure tabindex="-1">
          <div class="lightbox__media" style="--media-ratio: 1 / 1;">
            <picture>
              <source data-lightbox-source type="image/webp">
              <img data-lightbox-image src="" alt="" width="1600" height="1600" loading="eager" decoding="async">
            </picture>
          </div>
          <figcaption class="lightbox__caption" id="lightbox-caption" data-lightbox-caption>
            <strong id="lightbox-title" data-lightbox-title></strong>
            <span id="lightbox-meta" data-lightbox-meta></span>
          </figcaption>
        </figure>
        <button class="lightbox__nav" type="button" data-lightbox-next aria-label="Next photograph">›</button>
      </div>
    </dialog>
    """.strip()

def render_404(store: dict[str, Any]) -> str:
    raw = store["raw"]
    meta = {
        'title': 'Page not found | STILLMRK',
        'description': 'The requested STILLMRK page could not be found. Return to the portfolio, series index, or contact page.',
        'og_description': 'The requested STILLMRK page could not be found. Return to the portfolio, series index, or contact page.',
        'og_image': str(raw.get('site', {}).get('og_image') or 'assets/images/social/quiet-lens-og-home.jpg'),
        'og_image_alt': 'STILLMRK social preview card.',
        'canonical_path': '404.html',
    }
    return f"""<!DOCTYPE html>
<html lang="en">
{page_head('404', meta)}
  <body data-page="404">
    {google_analytics_body()}
    <a class="skip-link" href="#main-content">Skip to content</a>
    {render_nav(raw)}
    <main id="main-content">
      {render_protocol_notice()}
      <section class="page-hero page-hero--centered not-found-hero">
        <div class="container-narrow reveal">
          <p class="eyebrow">404 / Not found</p>
          <h1 class="display-title">This frame is no longer here.</h1>
          <p class="page-hero__lead">The address may have changed, or the work may have moved into another sequence.</p>
          <div class="hero__actions">
            <a class="button" href="portfolio.html">Return to portfolio</a>
            <a class="button button--secondary" href="series.html">Explore series</a>
          </div>
        </div>
      </section>
    </main>
    {render_footer(raw)}
    <script type="module" src="assets/js/app.js"></script>
  </body>
</html>
"""


def google_analytics_head() -> str:
    analytics_id = str((SITE_CONTENT.get('site') or {}).get('analytics_id') or '').strip()
    if not analytics_id or not re.fullmatch(r'G-[A-Z0-9]+', analytics_id, re.IGNORECASE):
        return ""
    return f"""
    <!-- Google Analytics -->
    <script async src=\"https://www.googletagmanager.com/gtag/js?id={esc(analytics_id)}\"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){{dataLayer.push(arguments);}}
      gtag('js', new Date());
      gtag('config', '{esc(analytics_id)}');
    </script>
    """.strip()


def google_analytics_body() -> str:
    return ""


def critical_head_css() -> str:
    # Tiny, stable above-the-fold guardrail. Keep this intentionally small; the
    # full visual system remains in assets/css/styles.css.
    return """
    <style data-critical-css>
      :root{color-scheme:dark;--bg:#0b0b0b;--text:#f2efe8;--accent:#d8c5a2;--font-sans:Inter,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif;--font-display:"Cormorant Garamond",Georgia,serif;--container:min(1360px,calc(100% - max(2rem,min(5vw,4rem))));--header-height:5.6rem}
      *,*::before,*::after{box-sizing:border-box}html{background:var(--bg)}body{margin:0;min-height:100vh;background:#0b0b0b;color:var(--text);font-family:var(--font-sans);line-height:1.6;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}img,picture{display:block;max-width:100%}img{height:auto}.container{width:var(--container);margin-inline:auto}.site-header{position:sticky;top:0;z-index:1000}.hero,.page-hero{padding-top:clamp(2.2rem,6vw,5rem)}.display-title,.section-title{font-family:var(--font-display);font-weight:500;line-height:1}.js.motion-ready .reveal:not(.is-visible){opacity:0}.js.motion-ready .hero .reveal,.js.motion-ready .page-hero .reveal,.js.motion-ready .about-hero.reveal,.js.motion-ready .series-masthead.reveal{opacity:1!important;transform:none!important}.js.motion-ready.reveal-fallback .reveal,.js.reveal-fallback .reveal{opacity:1!important;transform:none!important;transition:none!important}@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto!important}.js .reveal{opacity:1!important;transform:none!important}}
    </style>
    """.strip()


def page_head(page_key: str, meta: dict[str, str], *, preload_work: dict[str, Any] | None = None, preload_sizes: str | None = None) -> str:
    preload = ""
    if preload_work:
        webp_srcset = source_set(preload_work, "webp")
        jpg_srcset = source_set(preload_work, "jpg")
        resolved_preload_sizes = preload_sizes or "(min-width: 1100px) 42vw, (min-width: 760px) 52vw, calc(100vw - 2rem)"
        # Do not emit empty preload tags for metadata-only placeholders. Empty
        # image preloads waste a request slot and can hurt the LCP path the
        # preload is supposed to protect.
        if webp_srcset:
            webp_1200 = image_path(preload_work, preferred_width(preload_work), "webp")
            preload = f'''\n    <link rel="preload" as="image" type="image/webp" href="{esc(webp_1200)}" imagesrcset="{esc(webp_srcset)}" imagesizes="{esc(resolved_preload_sizes)}" fetchpriority="high">'''
        elif jpg_srcset:
            jpg_1200 = image_path(preload_work, preferred_width(preload_work), "jpg")
            preload = f'''\n    <link rel="preload" as="image" type="image/jpeg" href="{esc(jpg_1200)}" imagesrcset="{esc(jpg_srcset)}" imagesizes="{esc(resolved_preload_sizes)}" fetchpriority="high">'''
        elif str(preload_work.get('src') or '').strip():
            preload = f'''\n    <link rel="preload" as="image" href="{esc(str(preload_work.get('src') or '').strip())}" fetchpriority="high">'''


    site_settings = build_site_settings(SITE_CONTENT['site'])
    site_name = str(SITE_CONTENT['site'].get('name') or 'STILLMRK').strip()
    canonical_override = str(meta.get('canonical_path') or '').strip()
    if canonical_override.startswith('http://') or canonical_override.startswith('https://'):
        canonical_url = canonical_override
    elif canonical_override:
        canonical_url = absolute_url(canonical_override, site_settings['metadataBaseUrl'])
    else:
        canonical_url = build_page_url(page_key, SITE_CONTENT['site'])
    social_image_path = str(meta.get('og_image') or SITE_CONTENT['site']['og_image']).strip()
    social_image = absolute_url(social_image_path, site_settings['metadataBaseUrl'])
    social_alt = str(meta.get('og_image_alt') or 'STILLMRK monochrome photography portfolio preview image').strip()
    twitter_alt = str(meta.get('twitter_image_alt') or social_alt).strip()
    return f"""
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <script>document.documentElement.classList.add('js'); if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {{ document.documentElement.classList.add('motion-ready'); window.STILLMRK_REVEAL_FALLBACK = window.setTimeout(function () {{ document.documentElement.classList.add('reveal-fallback'); }}, 2400); }} if ('{page_key}' === 'series' && new URLSearchParams(window.location.search).get('series')) {{ document.documentElement.classList.add('series-query-loading'); }}</script>
    <title>{esc(meta['title'])}</title>
    <meta name="description" content="{esc(meta['description'])}">
    <meta name="author" content="Pooria Moozarm Nia, Pooria Mn, پوریا موزرم نیا">
    <meta name="creator" content="Pooria Moozarm Nia">
    <meta name="publisher" content="{esc(site_name)}">
    <meta name="robots" content="{esc(site_settings['robots'])}">
    <meta name="theme-color" content="#0b0b0b">
    <meta name="color-scheme" content="dark">
    <meta property="og:site_name" content="{esc(site_name)}">
    <meta property="og:title" content="{esc(meta['title'])}">
    <meta property="og:description" content="{esc(meta['og_description'])}">
    <meta property="og:type" content="website">
    <meta property="og:image" content="{esc(social_image)}">
    <meta property="og:image:type" content="image/jpeg">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">
    <meta property="og:image:alt" content="{esc(social_alt)}">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{esc(meta['title'])}">
    <meta name="twitter:description" content="{esc(meta['og_description'])}">
    <meta name="twitter:image" content="{esc(social_image)}">
    <meta name="twitter:image:alt" content="{esc(twitter_alt)}">
    <meta property="og:url" content="{esc(canonical_url)}">
    <link rel="canonical" href="{esc(canonical_url)}">{preload}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&display=swap" rel="stylesheet">
    <link rel="icon" href="assets/icons/favicon.svg" type="image/svg+xml">
    <link rel="icon" href="assets/icons/favicon-32x32.png" sizes="32x32" type="image/png">
    <link rel="icon" href="assets/icons/favicon.ico" sizes="any">
    <link rel="apple-touch-icon" href="assets/icons/apple-touch-icon.png" sizes="180x180">
    <link rel="manifest" href="site.webmanifest">
    {critical_head_css()}
    <link rel="stylesheet" href="assets/css/styles.css">
    {google_analytics_head()}
    <script type="application/ld+json" data-base-schema></script>
    <script type="application/ld+json" data-page-schema></script>
  </head>
    """.rstrip()


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


def render_home(store: dict[str, Any]) -> str:
    raw = store["raw"]
    page = raw["pages"]["home"]
    hero = page["hero"]
    home_feature = store["works_by_id"][hero["feature_work_id"]]
    section_order = [str(item).strip() for item in (page.get('section_order') or ['featured_series', 'selected_works', 'modules']) if str(item).strip()]

    metrics_html = []
    auto_values = {
        "auto:works": str(len(store["site_data"]["works"])).zfill(2),
        "auto:series": str(len(store["site_data"]["series"])).zfill(2),
    }
    for item in page["metrics"]:
        value = auto_values.get(item["value"], item["value"])
        metrics_html.append(
            f'''<article class="metric-card reveal"><strong>{esc(value)}</strong><span>{esc(item['label'])}</span></article>'''
        )

    featured_series_cards = []
    for index, slug in enumerate(page["featured_series"]["series_slugs"]):
        series = store["series_lookup"].get(slug)
        if not series:
            continue
        cover = store["works_by_id"].get(series.get("coverWorkId"))
        if not cover:
            continue
        count = len(series["_work_ids"])
        featured_series_cards.append(
            f"""
            <article class="series-card panel reveal">
              <a {media_attrs(cover, 'series-card__media', context='cover')} href="{series_path(series['slug'])}" aria-label="Open the {esc(series['title'])} series">
                {responsive_image_html(cover, '(min-width: 1100px) 28vw, (min-width: 760px) 48vw, 100vw', loading='lazy' if index else 'eager', fetchpriority='high' if index == 0 else 'auto')}
              </a>
              <div class="series-card__body">
                <div class="series-card__meta">
                  <span>{esc(series['years'])}</span>
                  <span>{str(count).zfill(2)} works</span>
                </div>
                <h3>{esc(series['title'])}</h3>
                <p>{esc(series['description'])}</p>
                <div class="series-card__footer">
                  <span>{esc(series['mood'])}</span>
                  <a href="{series_path(series['slug'])}">View series</a>
                </div>
              </div>
            </article>
            """.strip()
        )

    selected_cards = []
    for index, work_id in enumerate(page["selected_works"]["work_ids"]):
        work = store["works_by_id"].get(work_id)
        if not work:
            continue
        series = store["series_lookup"].get(work["series"])
        card_class = "editorial-card"
        image_sizes = '(min-width: 1100px) 28vw, (min-width: 760px) 48vw, 100vw'
        selected_cards.append(
            f"""
            <article class="{card_class} panel reveal">
              <a
                {media_attrs(work, 'editorial-card__media', context='cover')} href="{series_path(work['series'])}" aria-label="Open the {esc(work['title'])} image in the {esc(series['title'] if series else 'series')} sequence">
                {responsive_image_html(work, image_sizes, loading='eager' if index < 2 else 'lazy', fetchpriority='high' if index < 2 else 'auto')}
              </a>
              <div class="editorial-card__body">
                <div class="editorial-card__meta">
                  <span>{esc(series['title'] if series else 'Series')}</span>
                  <span>{esc(work['year'])}</span>
                </div>
                <h3>{esc(work['title'])}</h3>
                <p>{esc(work_caption_or_fallback(work, work['location']))}</p>
                <a href="{series_path(work['series'])}">Open series</a>
              </div>
            </article>
            """.strip()
        )

    module_cards = []
    for module in page["modules"]:
        if module.get('visible', True) is False:
            continue
        module_type = module["type"]
        if module_type == "text":
            actions = render_actions(module.get("actions", []))
            module_cards.append(
                f"""
                <article class="feature-module panel reveal">
                  <p class="eyebrow">{esc(module['eyebrow'])}</p>
                  <h2 class="section-title">{esc(module['title'])}</h2>
                  <p class="section-intro">{esc(module['text'])}</p>
                  <div class="hero__actions">{actions}</div>
                </article>
                """.strip()
            )
        elif module_type == "series_index":
            items = []
            for series in store["public_series_list"]:
                items.append(
                    f'<li><a href="{series_path(series["slug"])}"><span>{esc(series["title"])}</span><small>{str(len(series["_work_ids"])).zfill(2)}</small></a></li>'
                )
            module_cards.append(
                f"""
                <aside class="feature-module panel panel--soft reveal">
                  <p class="eyebrow">{esc(module['eyebrow'])}</p>
                  <h2 class="feature-module__title">{esc(module['title'])}</h2>
                  <p class="section-intro">{esc(module['text'])}</p>
                  <ul class="series-index">{' '.join(items)}</ul>
                </aside>
                """.strip()
            )
        elif module_type == "work_spotlight":
            work = store["works_by_id"].get(module["work_id"])
            if not work:
                continue
            action = render_actions([module["action"]]) if module.get("action") else ""
            module_cards.append(
                f"""
                <article class="feature-module feature-module--spotlight panel reveal">
                  <div
                    {media_attrs(work, 'feature-module__visual')}>
                    {responsive_image_html(work, '(min-width: 1100px) 26vw, (min-width: 760px) 40vw, 100vw', loading='lazy')}
                  </div>
                  <div class="feature-module__body">
                    <p class="eyebrow">{esc(module['eyebrow'])}</p>
                    <h2 class="feature-module__title">{esc(module['title'])}</h2>
                    <p class="section-intro">{esc(module['text'])}</p>
                    <div class="hero__actions">{action}</div>
                  </div>
                </article>
                """.strip()
            )

    featured_series_visible = page.get('featured_series', {}).get('visible', True) is not False
    selected_works_visible = page.get('selected_works', {}).get('visible', True) is not False
    modules_visible = bool(module_cards)
    section_markup: dict[str, str] = {}
    if featured_series_visible:
        section_markup['featured_series'] = f"""
      <section class="section" data-deferred>
        <div class="container">
          <div class="section-head reveal">
            <div>
              <p class="eyebrow">{esc(page['featured_series']['eyebrow'])}</p>
              <h2 class="section-title">{esc(page['featured_series']['title'])}</h2>
            </div>
            <p class="section-intro">{esc(page['featured_series']['intro'])}</p>
          </div>
          <div class="series-card-grid">{' '.join(featured_series_cards)}</div>
        </div>
      </section>
        """.rstrip()
    if selected_works_visible:
        section_markup['selected_works'] = f"""
      <section class="section section--compact" data-deferred="home-selected-works">
        <div class="container editorial-shell">
          <div class="section-head reveal">
            <div>
              <p class="eyebrow">{esc(page['selected_works']['eyebrow'])}</p>
              <h2 class="section-title">{esc(page['selected_works']['title'])}</h2>
            </div>
            <p class="section-intro">{esc(page['selected_works']['intro'])}</p>
          </div>
          <div class="editorial-grid">{' '.join(selected_cards)}</div>
        </div>
      </section>
        """.rstrip()
    if modules_visible:
        section_markup['modules'] = f"""
      <section class="section" data-deferred="home-modules">
        <div class="container feature-module-grid">{' '.join(module_cards)}</div>
      </section>
        """.rstrip()
    ordered_sections: list[str] = []
    for section_key in section_order + [key for key in section_markup.keys() if key not in section_order]:
        markup = section_markup.get(section_key)
        if markup and markup not in ordered_sections:
            ordered_sections.append(markup)

    hero_lead_primary, hero_lead_secondary = split_home_hero_lead(hero.get('lead'))
    hero_lead_markup = f'<div class="hero__lead-group"><p class="hero__lead hero__lead--primary">{esc(hero_lead_primary)}</p>'
    if hero_lead_secondary:
        hero_lead_markup += f'<p class="hero__lead">{esc(hero_lead_secondary)}</p>'
    hero_lead_markup += '</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
{page_head('home', page['meta'], preload_work=home_feature)}
  <body data-page="home">
    {google_analytics_body()}
    <a class="skip-link" href="#main-content">Skip to content</a>
    {render_nav(raw)}
    <main id="main-content">
      {render_protocol_notice()}
      <section class="hero hero--home">
        <div class="container hero__layout">
          <div class="hero__copy reveal">
            <p class="eyebrow">{esc(hero['eyebrow'])}</p>
            <h1 class="display-title">{esc(hero['title'])}</h1>
            {hero_lead_markup}
            <div class="hero__actions">
              {render_actions([hero['primary_action'], hero['secondary_action']])}
            </div>
            <ul class="hero__notes" aria-label="Portfolio characteristics">
              {''.join(f'<li>{esc(note)}</li>' for note in hero['notes'])}
            </ul>
          </div>
          <figure class="hero-figure reveal">
            <div class="hero__visual" style="--media-ratio: {aspect_ratio(home_feature, 'hero')};" data-protect-media="true">
              {responsive_image_html(home_feature, '(min-width: 1100px) 42vw, (min-width: 760px) 52vw, calc(100vw - 2rem)', loading='eager', fetchpriority='high')}
            </div>
            {render_media_caption(hero['feature_label'], home_feature['title'], work_media_meta(home_feature, store['series_lookup']))}
          </figure>
        </div>
      </section>
      {'\n      '.join(ordered_sections)}
    </main>
    {render_footer(raw)}
    {render_lightbox()}
    <script type="module" src="assets/js/app.js"></script>
  </body>
</html>
"""


def render_portfolio_filter_row(store: dict[str, Any], active_series: str = 'all') -> str:
    filters = [
        {'value': 'all', 'label': 'All works', 'count': len(store['public_portfolio_works'])},
        *[
            {
                'value': series['slug'],
                'label': series['title'],
                'count': len(series['_work_ids']),
            }
            for series in store['public_series_list']
        ],
    ]

    parts = []
    for item in filters:
        href = portfolio_path(item['value'] if item['value'] != 'all' else None)
        state_class = ' is-active' if active_series == item['value'] else ''
        parts.append(
            f'<a class="filter-chip{state_class}" href="{esc(href)}" data-filter="{esc(item['value'])}"><span>{esc(item['label'])}</span><small>{str(item['count']).zfill(2)}</small></a>'
        )
    return ''.join(parts)


def render_portfolio_grid(store: dict[str, Any], works: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    total = len(works)
    for index, work in enumerate(works):
        series = store['series_lookup'].get(work['series'])
        variant = portfolio_card_variant(index, total, work)
        layout_class = portfolio_layout_class(variant)
        image_sizes = portfolio_card_sizes(variant)
        priority_attr = '' if index < 2 or variant == 'lead' else ' data-priority-candidate="portfolio"'
        cards.append(
            f'''<article class="work-card panel reveal work-card--{orientation(work)} work-card--{variant}{layout_class}" data-layout="{esc(variant)}">
              <figure
                {media_attrs(work, 'work-card__media', context='portfolio')}{priority_attr}>
                {responsive_image_html(work, image_sizes, loading='eager' if index < 2 or variant == 'lead' else 'lazy', fetchpriority='high' if index < 2 or variant == 'lead' else 'auto')}
              </figure>
              <div class="work-card__body">
                <div class="work-card__meta">
                  <span>{esc(series['title'] if series else 'Series')}</span>
                  <span>{esc(work['location'])}</span>
                </div>
                <h2 class="work-card__title">{esc(work['title'])}</h2>
                {f'<p>{esc(work.get("caption") or "")}</p>' if (work.get('caption') or '').strip() else ''}
                <div class="work-card__footer">
                  <span>{esc(work['year'])}</span>
                  <a href="{series_path(work['series'])}">Open series</a>
                </div>
              </div>
            </article>'''
        )
    return ' '.join(cards)

def render_series_index_markup(store: dict[str, Any], active_slug: str) -> str:
    items = []
    for item in store['public_series_list']:
        active_class = ' class="is-active"' if item['slug'] == active_slug else ''
        type_badge = '<em class="series-index__badge">Stage Work</em>' if story_type_label(item) == 'Stage Work' else ''
        items.append(
            f'<li><a{active_class} href="{series_path(item["slug"])}"><span class="series-index__label"><span>{esc(item["title"])} </span>{type_badge}</span><small>{str(len(item["_work_ids"])).zfill(2)}</small></a></li>'
        )
    return ''.join(items)


def story_type_label(series: dict[str, Any] | None) -> str:
    kind = str((series or {}).get('projectType') or (series or {}).get('project_type') or '').strip().lower()
    return 'Stage Work' if kind == 'performance' else 'Series'


def summarize_story_text(text: str, *, fallback: str = '', limit: int = 190) -> str:
    cleaned = ' '.join(str(text or '').split())
    if not cleaned:
        cleaned = ' '.join(str(fallback or '').split())
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit].rsplit(' ', 1)[0].rstrip(' ,;:.')
    return f"{clipped}…" if clipped else cleaned[:limit]


def series_sequence_role(series: dict[str, Any], index: int, total: int) -> str:
    if total <= 1:
        return 'Single-image story'
    kind = str(series.get('projectType') or series.get('project_type') or '').strip().lower()
    if index == 0:
        return 'Opening image'
    if index == total - 1:
        return 'Closing image'
    if kind == 'performance':
        if index == total // 2:
            return 'Turning point'
        return 'Building pressure' if index < total // 2 else 'Aftermath'
    if index == total // 2:
        return 'Pivot image'
    return 'Middle movement' if index < total // 2 else 'Later movement'


def render_series_story_map_markup(series: dict[str, Any], works: list[dict[str, Any]]) -> str:
    if not series or not works:
        return ''
    first_work = works[0]
    last_work = works[-1]
    kind_label = story_type_label(series)
    summary = summarize_story_text(series.get('cardSummary') or series.get('description') or series.get('mood') or '', fallback='This story is meant to be read through sequence rather than as a loose grid of images.', limit=220)
    sequence_note = str(series.get('storySequenceText') or '').strip() or (
        'This stage work keeps the pressure of the play intact: an opening threshold, a middle of accumulating tension, and a final image that decides what remains.'
        if kind_label == 'Stage Work'
        else 'This series is paced as a visual essay: the first image opens the threshold, the middle images deepen the pressure, and the ending image leaves the final residue.'
    )
    opening_text = str(series.get('storyOpeningText') or '').strip() or summarize_story_text(first_work.get('caption') or first_work.get('alt') or first_work.get('location') or '', fallback=first_work.get('year') or '', limit=140)
    closing_text = str(series.get('storyClosingText') or '').strip() or summarize_story_text(last_work.get('caption') or last_work.get('alt') or last_work.get('location') or '', fallback=last_work.get('year') or '', limit=140)
    return f'''<section class="series-story-map panel panel--soft reveal" data-series-story-map>
      <div class="series-story-map__head">
        <div>
          <p class="eyebrow">How to read this story</p>
          <h2 class="section-title">{esc(kind_label)} in sequence</h2>
        </div>
        <p class="section-intro">{esc(summary)}</p>
      </div>
      <div class="series-story-map__grid">
        <article class="story-note">
          <p class="eyebrow">Opening</p>
          <h3>{esc(first_work.get('title') or 'Opening image')}</h3>
          <p>{esc(opening_text or 'The first image opens the threshold of the story.')}</p>
        </article>
        <article class="story-note story-note--center">
          <p class="eyebrow">Sequence logic</p>
          <h3>{str(len(works)).zfill(2)} images · {esc(kind_label)}</h3>
          <p>{esc(sequence_note)}</p>
        </article>
        <article class="story-note">
          <p class="eyebrow">Ending</p>
          <h3>{esc(last_work.get('title') or 'Closing image')}</h3>
          <p>{esc(closing_text or 'The final image keeps the last emotional residue of the story.')}</p>
        </article>
      </div>
    </section>'''


def series_frame_layout_token(series: dict[str, Any], work: dict[str, Any], index: int, total: int) -> str:
    override = work_layout_token(work, "series", "auto")
    if override != "auto":
        return override
    if index == 0 or index == total - 1 or index % 5 == 0:
        return "large"
    if index == total // 2 or orientation(work) == "landscape":
        return "medium"
    return "standard"


def series_card_sizes(layout: str) -> str:
    return {
        "quiet": "(min-width: 1100px) 24vw, (min-width: 760px) 42vw, 100vw",
        "standard": "(min-width: 1100px) 29vw, (min-width: 760px) 48vw, 100vw",
        "medium": "(min-width: 1100px) 38vw, (min-width: 760px) 58vw, 100vw",
        "large": "(min-width: 1100px) 52vw, (min-width: 760px) 62vw, 100vw",
        "wide": "(min-width: 1100px) 64vw, (min-width: 760px) 82vw, 100vw",
        "full": "(min-width: 1100px) 78vw, (min-width: 760px) 92vw, 100vw",
    }.get(layout, "(min-width: 1100px) 29vw, (min-width: 760px) 48vw, 100vw")


def render_series_gallery_markup(store: dict[str, Any], series: dict[str, Any], works: list[dict[str, Any]]) -> str:
    frames: list[str] = []
    total = len(works)
    for index, work in enumerate(works):
        role_label = series_sequence_role(series, index, total)
        layout_token = series_frame_layout_token(series, work, index, total)
        large = layout_token in {'large', 'wide', 'full'}
        role_class = (
            ' series-frame--opening' if index == 0 else ' series-frame--closing' if index == total - 1 else ' series-frame--turning' if index == total // 2 else ''
        )
        large_class = ' series-frame--featured' if large else ''
        layout_class = f' series-frame--layout-{layout_token}'
        image_sizes = series_card_sizes(layout_token)
        frame_text = str(work.get('caption') or work.get('alt') or work.get('year') or '').strip()
        frames.append(
            f'''<article class="series-frame panel reveal series-frame--{orientation(work)}{large_class}{role_class}{layout_class}" data-layout="{esc(layout_token)}" data-sequence-role="{esc(role_label.lower())}">
              <figure
                {media_attrs(work, 'series-frame__media', context='series')}{'' if index < 2 else ' data-priority-candidate="series"'}>
                {responsive_image_html(work, image_sizes, loading='eager' if index < 2 else 'lazy', fetchpriority='high' if index < 2 else 'auto')}
              </figure>
              <div class="series-frame__body">
                <p class="series-frame__eyebrow">{esc(role_label)}</p>
                <div class="series-frame__meta">
                  <span>{str(index + 1).zfill(2)}</span>
                  <span>{esc(work['location'])}</span>
                  <span>{esc(story_type_label(series))}</span>
                </div>
                <h2>{esc(work['title'])}</h2>
                {f'<p>{esc(frame_text)}</p>' if frame_text else ''}
              </div>
            </article>'''
        )
    return ' '.join(frames)

def render_related_series_markup(store: dict[str, Any], active_slug: str) -> str:
    cards: list[str] = []
    active_series = store['series_lookup'].get(active_slug) or {}
    preferred_slugs = [str(item).strip() for item in (active_series.get('relatedSeriesSlugs') or []) if str(item).strip()]
    if preferred_slugs:
        candidates = [store['public_series_lookup'][slug] for slug in preferred_slugs if slug in store['public_series_lookup'] and slug != active_slug]
    else:
        candidates = [series for series in store['public_series_list'] if series['slug'] != active_slug][:3]
    for item in candidates[:3]:
        work = store['works_by_id'].get(item.get('cardCoverWorkId') or item['coverWorkId'])
        if not work:
            continue
        cards.append(
            f'''<article class="series-card panel reveal">
              <a {media_attrs(work, 'series-card__media', context='cover')} href="{series_path(item['slug'])}">
                {responsive_image_html(work, '(min-width: 1100px) 28vw, (min-width: 760px) 48vw, 100vw', loading='lazy')}
              </a>
              <div class="series-card__body">
                <div class="series-card__meta">
                  <span>{esc(story_type_label(item))}</span>
                  <span>{str(len(item['_work_ids'])).zfill(2)} works</span>
                </div>
                <h3>{esc(item['title'])}</h3>
                <p>{esc(summarize_story_text(item.get('cardSummary') or item.get('description') or item.get('mood') or '', fallback=item.get('mood') or '', limit=150))}</p>
                <div class="series-card__footer">
                  <span>{esc(item['years'])}</span>
                  <a href="{series_path(item['slug'])}">Open story</a>
                </div>
              </div>
            </article>'''
        )
    return ' '.join(cards)


def render_series_pagination_markup(store: dict[str, Any], active_slug: str) -> str:
    ordered = store['public_series_list']
    if not ordered or len(ordered) < 2:
        return ''
    index = next((idx for idx, item in enumerate(ordered) if item['slug'] == active_slug), 0)
    previous_series = ordered[index - 1] if index > 0 else None
    next_series = ordered[index + 1] if index < len(ordered) - 1 else None
    links: list[str] = []
    if previous_series:
        links.append(
            f'''<a class="pagination-link panel panel--soft" href="{series_path(previous_series['slug'])}">
        <span>Previous series</span>
        <strong>{esc(previous_series['title'])}</strong>
      </a>'''
        )
    if next_series:
        links.append(
            f'''<a class="pagination-link pagination-link--next panel panel--soft" href="{series_path(next_series['slug'])}">
        <span>Next series</span>
        <strong>{esc(next_series['title'])}</strong>
      </a>'''
        )
    return ''.join(links)



def render_portfolio(store: dict[str, Any]) -> str:
    raw = store["raw"]
    page = raw["pages"]["portfolio"]
    portfolio_works = store['public_portfolio_works']
    hero_config = page.get('hero', {}) if isinstance(page.get('hero'), dict) else {}
    hero_work = store['works_by_id'].get(hero_config.get('feature_work_id')) if hero_config.get('feature_work_id') else None
    preload_target = hero_work if hero_work else (portfolio_works[0] if portfolio_works else None)
    initial_summary = f"{len(portfolio_works)} works · All series · Curated order"
    portfolio_actions = render_actions(page.get('hero', {}).get('actions') or [
        {'label': 'Browse the grid', 'href': '#portfolio-grid', 'style': 'primary'},
        {'label': 'Explore series', 'href': 'series.html', 'style': 'secondary'},
    ])
    portfolio_notes = page.get('hero', {}).get('notes') or [
        f"{str(len(portfolio_works)).zfill(2)} works on view",
        f"{str(len(store['public_series_list'])).zfill(2)} series on view",
        'Search, filter, and compare the sequence',
    ]
    grid_section = page.get('grid_section') if isinstance(page.get('grid_section'), dict) else {}
    portfolio_tools = f'''<div class="portfolio-tools portfolio-tools--footer panel reveal"><div class="portfolio-tools__row"><label class="field field--search"><span>Search</span><input data-portfolio-search type="search" placeholder="Search title, location, or series"><button class="field__clear" data-portfolio-clear type="button" hidden aria-label="Clear search">×</button></label><label class="field"><span>Sort</span><select data-portfolio-sort><option value="curated">Curated order</option><option value="title">Title</option><option value="series">Series</option><option value="location">Location</option></select></label></div><div class="filter-row" data-filter-row>{render_portfolio_filter_row(store)}</div><div class="portfolio-tools__meta"><p class="toolbar-note" data-work-count>{esc(initial_summary)}</p><button class="button button--secondary" type="button" data-portfolio-reset hidden>Reset</button></div></div>'''
    return f"""<!DOCTYPE html>
<html lang="en">
{page_head('portfolio', page['meta'], preload_work=preload_target, preload_sizes=portfolio_card_sizes('lead'))}
  <body data-page="portfolio">
    {google_analytics_body()}
    <a class="skip-link" href="#main-content">Skip to content</a>
    {render_nav(raw)}
    <main id="main-content">
      {render_protocol_notice()}
      <section class="hero hero--portfolio">
        <div class="container hero__layout">
          <div class="hero__copy reveal">
            <p class="eyebrow">{esc(page['hero']['eyebrow'])}</p>
            <h1 class="display-title">{esc(page['hero']['title'])}</h1>
            <p class="hero__lead">{esc(page['hero']['lead'])}</p>
            <div class="hero__actions">{portfolio_actions}</div>
            <ul class="hero__notes" aria-label="Portfolio tools summary">{''.join(f'<li>{esc(note)}</li>' for note in portfolio_notes)}</ul>
          </div>
          {f'''<figure class="hero-figure reveal"><div class="hero__visual" style="--media-ratio: {aspect_ratio(hero_work, 'hero')};" data-protect-media="true">{responsive_image_html(hero_work, '(min-width: 1100px) 42vw, (min-width: 760px) 52vw, calc(100vw - 2rem)', loading='eager', fetchpriority='high')}</div>{render_media_caption('Lead image', hero_work['title'], work_media_meta(hero_work, store['series_lookup']))}</figure>''' if hero_work else ''}
        </div>
      </section>
      <section class="section section--compact" id="portfolio-grid" data-deferred="portfolio-grid">
        <div class="container portfolio-shell">
          <div class="section-head reveal section-head--portfolio">
            <div class="section-head__copy">
              <p class="eyebrow">{esc(str(grid_section.get('eyebrow') or 'Portfolio navigation'))}</p>
              <h2 class="section-title">{esc(str(grid_section.get('title') or 'Search, sort, and compare the portfolio.'))}</h2>
              <p class="section-intro">{esc(str(grid_section.get('intro') or 'Search across titles, places, and series, then move into individual sequences when a slower reading becomes necessary. The tools sit below the grid so the image field stays uninterrupted.'))}</p>
            </div>
          </div>
          <div class="work-grid work-grid--portfolio" data-work-grid>{render_portfolio_grid(store, portfolio_works)}</div>
        </div>
      </section>
      <section class="section section--compact section--bordered" data-deferred="portfolio-tools-bottom">
        <div class="container">{portfolio_tools}</div>
      </section>
    </main>
    {render_footer(raw)}
    {render_lightbox()}
    <script type="module" src="assets/js/app.js"></script>
  </body>
</html>
"""
def render_series(store: dict[str, Any]) -> str:
    raw = store["raw"]
    page = raw["pages"]["series"]
    related_series = page.get('related_series') if isinstance(page.get('related_series'), dict) else {}
    inquiry = page.get('inquiry') if isinstance(page.get('inquiry'), dict) else {}
    public_series = store['public_series_list']
    default_series = public_series[0] if public_series else None
    works = [store['works_by_id'][work_id] for work_id in (default_series['_work_ids'] if default_series else []) if work_id in store['works_by_id']]
    cover = None
    if default_series and (default_series.get('cardCoverWorkId') or default_series.get('coverWorkId')) in store['works_by_id']:
        cover = store['works_by_id'][default_series.get('cardCoverWorkId') or default_series['coverWorkId']]
    elif works:
        cover = works[0]
    page_hero_id = str(((page.get('hero') or {}).get('feature_work_id') if isinstance(page.get('hero'), dict) else '') or '').strip()
    public_work_ids = {item['id'] for item in store['site_data']['works']}
    hero_work = store['works_by_id'].get(page_hero_id) if page_hero_id in public_work_ids else None
    if hero_work is None and default_series and (default_series.get('heroWorkId') or default_series.get('coverWorkId')) in store['works_by_id']:
        hero_work = store['works_by_id'][default_series.get('heroWorkId') or default_series.get('coverWorkId')]
    if hero_work is None:
        hero_work = cover
    hero_caption = work_media_meta(hero_work, store['series_lookup'], include_series=False) if hero_work else ''
    page_eyebrow = str(page.get('hero_eyebrow') or '').strip()
    page_lead = str(page.get('hero_lead') or '').strip()
    eyebrow_html = ((esc(page_eyebrow) + ' / ') if page_eyebrow else '') + f'<span data-series-title>{esc(default_series["title"])}</span>' if default_series else '<span data-series-title></span>'
    return f"""<!DOCTYPE html>
<html lang="en">
{page_head('series', page['meta'], preload_work=cover if cover else None)}
  <body data-page="series">
    {google_analytics_body()}
    <a class="skip-link" href="#main-content">Skip to content</a>
    {render_nav(raw)}
    <main id="main-content">
      {render_protocol_notice()}
      {'<section class="section"><div class="container"><article class="panel reveal"><p class="eyebrow">Series</p><h1 class="display-title">No series on view are currently available</h1><p class="page-hero__lead">Private or draft series stay out of the generated public build until they are made public.</p></article></div></section>' if not default_series else ''}
      <section class="page-hero page-hero--series"{' hidden' if not default_series else ''}>
        <div class="container series-masthead">
          <div class="series-masthead__copy reveal">
            <p class="eyebrow" data-series-eyebrow-prefix="{esc(page_eyebrow)}">{eyebrow_html}</p>
            <h1 class="display-title" data-series-heading>{esc(default_series['title'] or page.get('hero_title', 'Where Presence Meets Distance'))}</h1>
            <p class="page-hero__lead" data-series-description data-series-lead-prefix="{esc(page_lead)}">{esc(default_series['description'] or page_lead)}</p>
            <div class="series-masthead__facts">
              <span data-series-years>{esc(default_series['years'])}</span>
              <span data-series-count>{str(len(works))} works</span>
              <span data-series-mood>{esc(default_series['mood'])}</span>
            </div>
            <div class="hero__actions">
              <a class="button" data-series-portfolio-link href="{portfolio_path(default_series['slug'])}">View {esc(default_series['title'])} in the portfolio grid</a>
              <a class="button button--secondary" href="{esc(str(inquiry.get('href') or 'contact.html'))}">{esc(str(inquiry.get('label') or 'Inquire'))}</a>
            </div>
          </div>
          <figure class="series-masthead__figure reveal" data-series-hero data-series-default-hero-id="{esc(page_hero_id)}">
            <div class="series-masthead__visual" style="--media-ratio: {aspect_ratio(hero_work, 'hero')};">
              {responsive_image_html(hero_work, '(min-width: 1100px) 42vw, (min-width: 760px) 52vw, 100vw', loading='eager', fetchpriority='high')}
            </div>
            {render_media_caption('Lead image', hero_work['title'], hero_caption)}
          </figure>
        </div>
      </section>
      <section class="section" data-deferred="series-main">
        <div class="container series-layout">
          <aside class="series-sidebar panel panel--soft reveal">
            <p class="eyebrow">Story index</p>
            <p class="series-sidebar__intro">Move through the stories one sequence at a time. Stage Works remain visible here because they belong to the same photographic world, even when their source is theatrical.</p>
            <ul class="series-index" data-series-index>{render_series_index_markup(store, default_series['slug'])}</ul>
          </aside>
          <div class="series-main">
            {render_series_story_map_markup(default_series, works)}
            <div class="series-gallery" data-series-gallery>{render_series_gallery_markup(store, default_series, works)}</div>
            <div class="section-head section-head--tight reveal related-head">
              <div>
                <p class="eyebrow">{esc(str(related_series.get('eyebrow') or 'Related series'))}</p>
                <h2 class="section-title">{esc(str(related_series.get('title') or 'Other sequences in the archive.'))}</h2>
              </div>
            </div>
            <div class="series-card-grid" data-related-series>{render_related_series_markup(store, default_series['slug'])}</div>
            <div class="series-pagination" data-series-pagination>{render_series_pagination_markup(store, default_series['slug'])}</div>
          </div>
        </div>
      </section>
    </main>
    {render_footer(raw)}
    {render_lightbox()}
    <script type="module" src="assets/js/app.js"></script>
  </body>
</html>
"""

def render_performance_project_cards(store: dict[str, Any], collection: dict[str, Any]) -> str:
    cards: list[str] = []
    for index, slug in enumerate(collection.get('seriesSlugs') or []):
        item = store['public_series_lookup'].get(slug)
        if not item:
            continue
        work = store['works_by_id'].get(item.get('cardCoverWorkId') or item.get('coverWorkId'))
        if not work:
            continue
        project_works = [store['works_by_id'][work_id] for work_id in item.get('_work_ids', []) if work_id in store['works_by_id']]
        opening_title = project_works[0]['title'] if project_works else work['title']
        closing_title = project_works[-1]['title'] if project_works else work['title']
        excerpt = summarize_story_text(item.get('cardSummary') or item.get('description') or item.get('mood') or '', fallback=item.get('mood') or '', limit=180)
        storyline = f'Opens with “{opening_title}” and closes with “{closing_title}”.' if project_works else 'Read as a complete sequenced story.'
        featured_class = ' series-card--story-featured' if index == 0 else ''
        cards.append(
            f'''<article class="series-card panel reveal series-card--performance{featured_class}">
              <a {media_attrs(work, 'series-card__media', context='cover')} href="{series_path(item['slug'])}" aria-label="Open the {esc(item['title'])} stage work">
                {responsive_image_html(work, '(min-width: 1100px) 28vw, (min-width: 760px) 48vw, 100vw', loading='lazy' if index else 'eager', fetchpriority='high' if index == 0 else 'auto')}
              </a>
              <div class="series-card__body">
                <div class="series-card__meta">
                  <span>Stage Work</span>
                  <span>{str(len(item['_work_ids'])).zfill(2)} works</span>
                </div>
                <h3>{esc(item['title'])}</h3>
                <p class="series-card__storyline">{esc(storyline)}</p>
                <p>{esc(excerpt)}</p>
                <div class="series-card__footer">
                  <span>{esc(item['years'])}</span>
                  <a href="{series_path(item['slug'])}">Read the sequence</a>
                </div>
              </div>
            </article>'''
        )
    if cards:
        return ''.join(cards)
    return '''<article class="empty-state panel reveal performance-empty">
      <p class="eyebrow">Stage Works</p>
      <h2>No public stage works yet.</h2>
      <p>The structure is ready. Create a stage-work series with <code>project_type: performance</code>, attach works to it, preserve the sequence order, and make the series public when it should appear here.</p>
      <a class="button button--secondary" href="series.html">View current series</a>
    </article>'''


def render_performance_structure_cards(page: dict[str, Any]) -> str:
    structure = page.get('structure') if isinstance(page.get('structure'), dict) else {}
    cards = structure.get('cards') if isinstance(structure.get('cards'), list) else []
    rendered: list[str] = []
    for item in cards:
        if not isinstance(item, dict):
            continue
        rendered.append(
            f'''<article class="info-card panel reveal">
              <p class="eyebrow">{esc(str(item.get('eyebrow') or 'Structure'))}</p>
              <h2>{esc(str(item.get('title') or ''))}</h2>
              <p>{esc(str(item.get('text') or ''))}</p>
            </article>'''
        )
    return ''.join(rendered)


def render_performance_guide_cards(page: dict[str, Any]) -> str:
    guide = page.get('content_builder_guide') if isinstance(page.get('content_builder_guide'), dict) else {}
    if guide.get('visible', False) is False:
        return ''
    cards = guide.get('items') if isinstance(guide.get('items'), list) else []
    rendered: list[str] = []
    for item in cards:
        if not isinstance(item, dict):
            continue
        rendered.append(
            f'''<article class="info-card panel reveal">
              <p class="eyebrow">{esc(str(item.get('eyebrow') or 'Stage Work guide'))}</p>
              <h2>{esc(str(item.get('title') or ''))}</h2>
              <p>{esc(str(item.get('text') or ''))}</p>
            </article>'''
        )
    return ''.join(rendered)


def render_performance(store: dict[str, Any]) -> str:
    raw = store["raw"]
    page = raw["pages"].get("performance", {})
    collection = store.get('collection_lookup', {}).get('performance') or {
        'slug': 'performance',
        'title': 'Stage Works',
        'eyebrow': 'Story route',
        'lead': '',
        'description': '',
        'seriesSlugs': [item['slug'] for item in store.get('public_series_list', []) if str(item.get('projectType') or '').strip() == 'performance'],
        'seriesCount': 0,
        'workCount': 0,
        'coverWorkId': '',
    }
    hero = page.get('hero') if isinstance(page.get('hero'), dict) else {}
    public_work_ids = {item['id'] for item in store['site_data']['works']}
    hero_work_id = str(hero.get('feature_work_id') or collection.get('coverWorkId') or '').strip()
    hero_work = store['works_by_id'].get(hero_work_id) if hero_work_id in public_work_ids else None
    if hero_work is None:
        for slug in collection.get('seriesSlugs') or []:
            series_item = store['public_series_lookup'].get(slug)
            candidate = store['works_by_id'].get(series_item.get('coverWorkId')) if series_item else None
            if candidate and candidate['id'] in public_work_ids:
                hero_work = candidate
                break
    if hero_work is None and store['public_portfolio_works']:
        hero_work = store['public_portfolio_works'][0]

    projects = page.get('projects') if isinstance(page.get('projects'), dict) else {}
    guide = page.get('content_builder_guide') if isinstance(page.get('content_builder_guide'), dict) else {}
    structure = page.get('structure') if isinstance(page.get('structure'), dict) else {}
    cta = page.get('cta') if isinstance(page.get('cta'), dict) else {}
    guide_cards = render_performance_guide_cards(page)
    notes = list(hero.get('notes') or [])
    if collection.get('seriesCount') or collection.get('workCount'):
        notes = [f"{str(collection.get('seriesCount') or 0).zfill(2)} stage works", f"{str(collection.get('workCount') or 0).zfill(2)} works", *notes]

    return f"""<!DOCTYPE html>
<html lang="en">
{page_head('performance', page['meta'], preload_work=hero_work if hero_work else None)}
  <body data-page="performance">
    {google_analytics_body()}
    <a class="skip-link" href="#main-content">Skip to content</a>
    {render_nav(raw)}
    <main id="main-content">
      {render_protocol_notice()}
      <section class="hero hero--home hero--performance">
        <div class="container hero__layout">
          <div class="hero__copy reveal">
            <p class="eyebrow">{esc(str(hero.get('eyebrow') or collection.get('title') or 'Stage Works'))}</p>
            <h1 class="display-title">{esc(str(hero.get('title') or collection.get('title') or 'Stage Works'))}</h1>
            <p class="hero__lead">{esc(str(hero.get('lead') or collection.get('lead') or collection.get('description') or ''))}</p>
            {'<div class="hero__actions">' + render_actions(hero.get('actions') or []) + '</div>' if isinstance(hero.get('actions'), list) and hero.get('actions') else ''}
            {'<ul class="hero__notes" aria-label="Performance structure summary">' + ''.join(f'<li>{esc(note)}</li>' for note in notes) + '</ul>' if notes else ''}
          </div>
          {f'''<figure class="hero-figure reveal">
            <div {media_attrs(hero_work, 'hero__visual', context='hero')}>
              {responsive_image_html(hero_work, '(min-width: 1100px) 42vw, (min-width: 760px) 52vw, calc(100vw - 2rem)', loading='eager', fetchpriority='high')}
            </div>
            {render_media_caption('Lead image', hero_work['title'], work_media_meta(hero_work, store['series_lookup']))}
          </figure>''' if hero_work else ''}
        </div>
      </section>
      <section class="section section--compact" id="performance-projects" data-deferred="performance-projects">
        <div class="container">
          <div class="section-head reveal section-head--tight">
            <div>
              <p class="eyebrow">{esc(str(projects.get('eyebrow') or 'Stage Works'))}</p>
              <h2 class="section-title">{esc(str(projects.get('title') or 'Stage Works.'))}</h2>
              <p class="section-intro">{esc(str(projects.get('intro') or collection.get('description') or ''))}</p>
            </div>
          </div>
          <div class="series-card-grid series-card-grid--performance" data-scroll-dots="false">{render_performance_project_cards(store, collection)}</div>
        </div>
      </section>
      {f'''<section class="section section--compact section--bordered" data-deferred="performance-guide">
        <div class="container">
          <div class="section-head reveal">
            <div>
              <p class="eyebrow">{esc(str(guide.get('eyebrow') or 'Guide scaffolds'))}</p>
              <h2 class="section-title">{esc(str(guide.get('title') or 'Draft Stage Works'))}</h2>
            </div>
            <p class="section-intro">{esc(str(guide.get('intro') or 'Private guide cards for shaping theatre and performance stories before they become public.'))}</p>
          </div>
          <div class="card-grid performance-structure-grid">{guide_cards}</div>
        </div>
      </section>''' if guide_cards else ''}
      <section class="section section--compact section--bordered" data-deferred="performance-structure">
        <div class="container">
          <div class="section-head reveal section-head--tight">
            <div>
              <p class="eyebrow">{esc(str(structure.get('eyebrow') or 'Structure'))}</p>
              <h2 class="section-title">{esc(str(structure.get('title') or 'A story route with project-level sequencing.'))}</h2>
              <p class="section-intro">{esc(str(structure.get('intro') or ''))}</p>
            </div>
          </div>
          <div class="card-grid performance-structure-grid">{render_performance_structure_cards(page)}</div>
        </div>
      </section>
      <section class="section section--bordered" data-deferred="performance-cta">
        <div class="container-narrow panel reveal cta-band">
          <p class="eyebrow">{esc(str(cta.get('eyebrow') or 'Inquiry'))}</p>
          <h2 class="section-title">{esc(str(cta.get('title') or 'Stage Works inquiries.'))}</h2>
          <p class="section-intro">{esc(str(cta.get('text') or ''))}</p>
          <div class="hero__actions">{render_actions(cta.get('actions') or [{'label': 'Start an inquiry', 'href': 'contact.html', 'style': 'primary'}])}</div>
        </div>
      </section>
    </main>
    {render_footer(raw)}
    {render_lightbox()}
    <script type="module" src="assets/js/app.js"></script>
  </body>
</html>
"""


def render_about(store: dict[str, Any]) -> str:
    raw = store["raw"]
    page = raw["pages"]["about"]
    hero_work = store["works_by_id"][page["hero"]["feature_work_id"]]
    document_block = page.get('document_block') if isinstance(page.get('document_block'), dict) else {}

    cards = []
    for card in page["practice_cards"]:
        if isinstance(card, dict) and card.get('visible', True) is False:
            continue
        cards.append(
            f"""
            <article class="info-card panel reveal">
              <p class="eyebrow">{esc(card['eyebrow'])}</p>
              <h2>{esc(card['title'])}</h2>
              <p>{esc(card['text'])}</p>
            </article>
            """.strip()
        )

    return f"""<!DOCTYPE html>
<html lang="en">
{page_head('about', page['meta'])}
  <body data-page="about">
    {google_analytics_body()}
    <a class="skip-link" href="#main-content">Skip to content</a>
    {render_nav(raw)}
    <main id="main-content">
      {render_protocol_notice()}
      <section class="page-hero">
        <div class="container about-hero">
          <div class="about-hero__copy reveal">
            <p class="eyebrow">{esc(page['hero']['eyebrow'])}</p>
            <h1 class="display-title">{esc(page['hero']['title'])}</h1>
            <p class="page-hero__lead">{esc(page['hero']['lead'])}</p>
            {'<div class="hero__actions">' + render_actions(page['hero']['actions']) + '</div>' if isinstance(page['hero'].get('actions'), list) and page['hero'].get('actions') else ''}
            {'<ul class="hero__notes" aria-label="About page highlights">' + ''.join(f'<li>{esc(note)}</li>' for note in page['hero']['notes']) + '</ul>' if isinstance(page['hero'].get('notes'), list) and page['hero'].get('notes') else ''}
          </div>
          <figure class="about-hero__figure reveal">
            <div class="about-hero__visual" style="--media-ratio: {aspect_ratio(hero_work, 'hero')};" data-protect-media="true">
              {responsive_image_html(hero_work, '(min-width: 1100px) 42vw, (min-width: 760px) 52vw, calc(100vw - 2rem)', loading='eager', fetchpriority='high')}
            </div>
            {render_media_caption('Lead image', hero_work['title'], work_media_meta(hero_work, store['series_lookup']))}
          </figure>
        </div>
      </section>
      <section class="section section--compact" data-deferred="about-statement">
        <div class="container statement-grid">
          <article class="statement-card panel reveal">
            <p class="eyebrow">{esc(page['statement']['eyebrow'])}</p>
            <h2 class="section-title">{esc(page['statement']['title'])}</h2>
            <p class="section-intro">{esc(page['statement']['text'])}</p>
          </article>
          <aside class="statement-card panel panel--soft reveal">
            <p class="eyebrow">Availability</p>
            <p>{esc(raw['artist']['status'])}</p>
            <p><strong>Base:</strong> {esc(build_public_identity(raw)['location'])}</p>
            <p><strong>Practice:</strong> {esc(raw['artist']['discipline'])}</p>
          </aside>
        </div>
      </section>
      <section class="section" data-deferred="about-cards">
        <div class="container card-grid">{' '.join(cards)}</div>
      </section>
      <section class="section section--compact" data-deferred="about-downloads" id="about-documents">
        <div class="container">
          <div class="section-head reveal section-head--tight">
            <div>
              <p class="eyebrow">{esc(str(document_block.get('eyebrow') or 'Documents'))}</p>
              <h2 class="section-title">{esc(str(document_block.get('title') or 'Press, exhibition, and profile PDFs.'))}</h2>
              <p class="section-intro">{esc(str(document_block.get('intro') or 'These downloadable files are part of the public build so editors, curators, and collaborators can review the supporting material without leaving the site blind.'))}</p>
            </div>
          </div>
          <div class="download-grid" data-downloads-static>{render_download_cards(resolve_page_downloads(store, document_block))}</div>
        </div>
      </section>
      <section class="section section--bordered" data-deferred="about-cta">
        <div class="container-narrow panel reveal cta-band">
          <p class="eyebrow">{esc(page['cta']['eyebrow'])}</p>
          <h2 class="section-title">{esc(page['cta']['title'])}</h2>
          <p class="section-intro">{esc(str(page['cta'].get('text') or '').strip() or 'For editions, licensing, exhibitions, or collaborations, move from the archive into a direct message built around specific works or series.')}</p>
          <div class="hero__actions">{render_actions(page['cta']['actions'])}</div>
        </div>
      </section>
    </main>
    {render_footer(raw)}
    {render_lightbox()}
    <script type="module" src="assets/js/app.js"></script>
  </body>
</html>
"""


def render_contact(store: dict[str, Any]) -> str:
    raw = store["raw"]
    page = raw["pages"]["contact"]
    document_block = page.get('document_block') if isinstance(page.get('document_block'), dict) else {}
    hero_config = page.get('hero', {}) if isinstance(page.get('hero'), dict) else {}
    hero_work = store['works_by_id'].get(hero_config.get('feature_work_id')) if hero_config.get('feature_work_id') else None
    options = "".join(f'<option>{esc(option)}</option>' for option in page['inquiry_types'])
    form_endpoint = str(page.get('form_endpoint') or '').strip()
    identity = build_public_identity(raw)
    email_address = str(identity.get('email') or '').strip()
    direct_email_block = ''
    if has_public_contact_email(email_address):
        direct_email_block = f'''
            <div class="contact-escape panel panel--soft">
              <p class="eyebrow">Direct email</p>
              <strong class="contact-escape__address">{esc(email_address)}</strong>
              <p class="muted-copy">If your mail client is blocked or the form cannot complete, use the email address directly.</p>
              <div class="contact-escape__actions">
                <a class="button button--secondary" href="mailto:{esc(email_address)}" data-contact-direct-email>Open email app</a>
                <button class="button button--ghost" type="button" data-copy-artist-email>Copy email address</button>
              </div>
            </div>'''
    return f"""<!DOCTYPE html>
<html lang="en">
{page_head('contact', page['meta'])}
  <body data-page="contact">
    {google_analytics_body()}
    <a class="skip-link" href="#main-content">Skip to content</a>
    {render_nav(raw)}
    <main id="main-content">
      {render_protocol_notice()}
      <section class="page-hero">
        <div class="container page-hero__layout">
          <div class="page-hero__copy reveal">
            <p class="eyebrow">{esc(page['hero']['eyebrow'])}</p>
            <h1 class="display-title">{esc(page['hero']['title'])}</h1>
            <p class="page-hero__lead">{esc(page['hero']['lead'])}</p>
            {'<div class="hero__actions">' + render_actions(page['hero']['actions']) + '</div>' if isinstance(page['hero'].get('actions'), list) and page['hero'].get('actions') else ''}
            {'<ul class="hero__notes" aria-label="Contact page highlights">' + ''.join(f'<li>{esc(note)}</li>' for note in page['hero']['notes']) + '</ul>' if isinstance(page['hero'].get('notes'), list) and page['hero'].get('notes') else ''}
          </div>
          {f'''<figure class="page-hero__figure reveal">
            <div class="page-hero__visual" style="--media-ratio: {aspect_ratio(hero_work, 'hero')};" data-protect-media="true">
              {responsive_image_html(hero_work, '(min-width: 1100px) 42vw, (min-width: 760px) 52vw, calc(100vw - 2rem)', loading='eager', fetchpriority='high')}
            </div>
            {render_media_caption('Lead image', hero_work['title'], work_media_meta(hero_work, store['series_lookup']))}
          </figure>''' if hero_work else ''}
        </div>
      </section>
      <section class="section section--compact" data-deferred="contact-main">
        <div class="container contact-grid">
          <article class="contact-card panel reveal">
            <p class="eyebrow">Details</p>
            <h2 class="section-title">{esc(page['details_title'])}</h2>
            <dl class="contact-list">
              <div>
                <dt>Email</dt>
                <dd>{f'<a href="mailto:{esc(identity['email'])}" data-artist-email>{esc(identity['email'])}</a>' if has_public_contact_email(identity.get('email')) else '<span data-artist-email-placeholder>Available on request</span>'}</dd>
              </div>
              <div>
                <dt>Location</dt>
                <dd>{esc(identity['location'])}</dd>
              </div>
              <div>
                <dt>Instagram</dt>
                <dd>{f'<a href="{esc(str(raw['artist'].get('instagram') or "").strip())}" data-artist-instagram target="_blank" rel="noreferrer">Instagram</a>' if has_public_profile_url(raw['artist'].get('instagram')) else '<span data-artist-instagram-placeholder>Not published on staging</span>'}</dd>
              </div>
              <div>
                <dt>Availability</dt>
                <dd>{esc(raw['artist']['status'])}</dd>
              </div>
            </dl>
          </article>
          <div class="contact-main-stack">
            <aside class="contact-downloads panel reveal" data-downloads-static="true" id="contact-documents">
              <p class="eyebrow">{esc(str(document_block.get('eyebrow') or 'Documents'))}</p>
              <h2 class="section-title">{esc(str(document_block.get('title') or 'Useful PDFs before you write.'))}</h2>
              <p class="section-intro">{esc(str(document_block.get('intro') or 'Press materials, exhibition details, and a short practice overview are gathered here so the essentials are easy to open before writing.'))}</p>
              <div class="contact-downloads__list">{render_download_cards(resolve_page_downloads(store, document_block, limit=3), compact=True)}</div>
            </aside>
            <form class="form-shell panel reveal" id="contact-form" data-contact-form data-contact-endpoint="{esc(form_endpoint)}" method="post" novalidate>
            <p class="eyebrow">Inquiry draft</p>
            <h2 class="section-title">Build a precise message.</h2>
            <p class="section-intro">{esc(str(page.get('form_intro') or '').strip() or 'Use the draft for precise requests. Editions, licensing context, exhibition timing, and collaboration scope are easiest to answer when the message is structured from the start.')}</p>
            <div class="field-grid">
              <label class="field">
                <span>Name</span>
                <input name="name" type="text" autocomplete="name" required>
              </label>
              <label class="field">
                <span>Email</span>
                <input name="email" type="email" inputmode="email" autocomplete="email" required>
              </label>
            </div>
            <div class="field-grid">
              <label class="field">
                <span>Inquiry type</span>
                <select name="inquiryType">{options}</select>
              </label>
              <label class="field">
                <span>Timeline</span>
                <input name="timeline" type="text" placeholder="Optional">
              </label>
            </div>
            <label class="field">
              <span>Message</span>
              <textarea name="message" rows="7" required></textarea>
            </label>
            {direct_email_block}
            <div class="form-actions">
              <button class="button" type="submit">{esc(page['form_button_label'])}</button>
              <p class="form-note" data-form-status aria-live="polite">{esc(page['form_note'])}</p>
            </div>
          </form>
        </div>
      </section>
    </main>
    <div class="mobile-contact-bar" data-mobile-contact-bar><a class="button" href="#contact-form">Send a message ↓</a></div>
    {render_footer(raw)}
    {render_lightbox()}
    <script type="module" src="assets/js/app.js"></script>
  </body>
</html>
"""


def render_data_js(store: dict[str, Any]) -> str:
    site_data_json = json.dumps(store["site_data"], ensure_ascii=False, indent=2)
    return f'''/*
  GENERATED FILE - do not edit manually.
  Edit the YAML files in content/ and run: python build_site.py
*/

export const siteData = {site_data_json};

const responsiveWidths = Object.freeze(
  [...new Set((siteData.imagePipeline?.widths || [])
    .map((width) => Number(width))
    .filter((width) => Number.isFinite(width) && width > 0))]
    .sort((a, b) => a - b)
);
const fallbackResponsiveWidth = responsiveWidths.at(-1) || 2048;

const publicWorks = Array.isArray(siteData.works) ? siteData.works : [];
const publicSeries = Array.isArray(siteData.series) ? siteData.series : [];
const publicCollections = Array.isArray(siteData.collections) ? siteData.collections : [];
const reviewWorks = Array.isArray(siteData.reviewWorks) ? siteData.reviewWorks : [];
const reviewSeries = Array.isArray(siteData.reviewSeries) ? siteData.reviewSeries : [];
const allWorks = [...publicWorks, ...reviewWorks.filter((work) => !publicWorks.some((item) => item.id === work.id))];
const allSeries = [...publicSeries, ...reviewSeries.filter((series) => !publicSeries.some((item) => item.slug === series.slug))];
const workById = new Map(allWorks.map((work) => [work.id, work]));
const seriesBySlug = new Map(allSeries.map((series) => [series.slug, series]));
const collectionBySlug = new Map(publicCollections.map((collection) => [collection.slug, collection]));

function compareNumber(a, b, fallback = 9999) {{
  const left = Number.isFinite(a) ? a : fallback;
  const right = Number.isFinite(b) ? b : fallback;
  return left - right;
}}

export const siteMetrics = Object.freeze({{
  workCount: publicWorks.length,
  seriesCount: publicSeries.length,
  collectionCount: publicCollections.length,
  inquiryPaths: 3
}});

export function escapeHtml(value = '') {{
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}}

function getAvailableWidths(work) {{
  const intrinsicWidth = Number(work?.width) || fallbackResponsiveWidth;
  const widths = responsiveWidths.filter((width) => width <= intrinsicWidth);
  const fallbackWidth = Math.min(intrinsicWidth, fallbackResponsiveWidth);

  if (!widths.includes(fallbackWidth)) {{
    widths.push(fallbackWidth);
  }}

  return [...new Set(widths)].sort((a, b) => a - b);
}}

function getPreferredWidth(work, preferred = 1200) {{
  const widths = getAvailableWidths(work);
  const match = [...widths].reverse().find((width) => width <= preferred);
  return match || widths[widths.length - 1];
}}

function getLargestWidth(work) {{
  const widths = getAvailableWidths(work);
  return widths[widths.length - 1];
}}

function sourceSet(work, extension) {{
  if (!work?.responsiveBase) return '';
  return getAvailableWidths(work)
    .map((width) => `${{work.responsiveBase}}-${{width}}.${{extension}} ${{width}}w`)
    .join(', ');
}}

export function getImagePath(work, width, extension = 'jpg') {{
  if (!work?.responsiveBase) return work?.src || '';
  const resolvedWidth = width || getPreferredWidth(work);
  return `${{work.responsiveBase}}-${{resolvedWidth}}.${{extension}}`;
}}

export function hasWorkImage(work) {{
  return Boolean(work?.src || work?.responsiveBase);
}}

export function getImageSourceSet(work, extension = 'jpg') {{
  return sourceSet(work, extension);
}}

export function getWorkOrientation(work) {{
  const ratio = (Number(work?.width) || 1) / (Number(work?.height) || 1);
  if (ratio > 1.12) return 'landscape';
  if (ratio < 0.88) return 'portrait';
  return 'square';
}}

export function getAspectRatioValue(work, context = 'default') {{
  const fallback = `${{Number(work?.width) || 1}} / ${{Number(work?.height) || 1}}`;
  const ratios = work?.displayRatios || {{}};
  const candidate = String((ratios && (ratios[context] || ratios.default)) || '').trim();
  return /^\\d+(?:\\.\\d+)?\\s*\\/\\s*\\d+(?:\\.\\d+)?$/.test(candidate) ? candidate : fallback;
}}

export function getFocalPoint(work) {{
  return {{
    x: Number.isFinite(Number(work?.focalPoint?.x)) ? Number(work.focalPoint.x) : 50,
    y: Number.isFinite(Number(work?.focalPoint?.y)) ? Number(work.focalPoint.y) : 50
  }};
}}

export function getObjectPosition(work) {{
  const point = getFocalPoint(work);
  return `${{point.x}}% ${{point.y}}%`;
}}

export function buildMediaShellAttributes(work, {{ className = '', context = 'default' }} = {{}}) {{
  const classes = [className].filter(Boolean).join(' ');
  const classAttr = classes ? ` class="${{classes}}"` : '';
  return `${{classAttr}} style="--media-ratio: ${{getAspectRatioValue(work, context)}}; --media-position: ${{getObjectPosition(work)}};" data-orientation="${{getWorkOrientation(work)}}"`;
}}

export function buildResponsiveImage(
  work,
  {{
    sizes = '(min-width: 1100px) 38vw, (min-width: 760px) 50vw, 100vw',
    className = '',
    loading = 'lazy',
    fetchpriority = 'auto'
  }} = {{}}
) {{
  const classAttr = className ? ` class="${{className}}"` : '';
  const priorityAttr = fetchpriority !== 'auto' ? ` fetchpriority="${{fetchpriority}}"` : '';
  const positionStyle = ` style="object-position: ${{getObjectPosition(work)}};"`;
  const jpgSrcset = sourceSet(work, 'jpg');
  const webpSrcset = sourceSet(work, 'webp');
  const hasImage = Boolean((jpgSrcset && webpSrcset) || work?.src);

  if (!hasImage) {{
    return `
      <div class="media-placeholder" role="img" aria-label="${{escapeHtml(work?.alt || work?.title || 'Image pending')}}">
        <span>Image pending</span>
        <strong>${{escapeHtml(work?.title || 'Untitled work')}}</strong>
        <small>${{escapeHtml(work?.alt || 'No image assigned yet.')}}</small>
      </div>
    `;
  }}

  if (jpgSrcset && webpSrcset) {{
    return `
      <picture>
        <source type="image/webp" srcset="${{webpSrcset}}" sizes="${{sizes}}">
        <img
          ${{classAttr}}
          src="${{getImagePath(work, getPreferredWidth(work), 'jpg')}}"
          srcset="${{jpgSrcset}}"
          sizes="${{sizes}}"
          width="${{work.width}}"
          height="${{work.height}}"
          alt="${{escapeHtml(work.alt)}}"
          loading="${{loading}}"
          decoding="async"${{priorityAttr}}${{positionStyle}}>
      </picture>
    `;
  }}

  return `
    <img
      ${{classAttr}}
      src="${{work.src || ''}}"
      width="${{work.width}}"
      height="${{work.height}}"
      alt="${{escapeHtml(work.alt)}}"
      loading="${{loading}}"
      decoding="async"${{priorityAttr}}${{positionStyle}}>
  `;
}}

export function buildLightboxMeta(work) {{
  const caption = (work.caption || '').trim();
  if (caption) return caption;
  const series = getSeriesBySlug(work.series);
  return `${{series?.title || 'Series'}} / ${{work.location}} / ${{work.year}}`;
}}

export function buildLightboxAttributes(
  work,
  {{
    sizes = '(min-width: 1100px) 74vw, (min-width: 760px) 88vw, 96vw',
    group = 'default'
  }} = {{}}
) {{
  if (!hasWorkImage(work)) {{
    return `
      data-image-pending="true"
      aria-label="${{escapeHtml(work?.alt || work?.title || 'Image pending')}}"
    `;
  }}

  return `
    data-lightbox-group="${{escapeHtml(group)}}"
    data-lightbox-src="${{getImagePath(work, getLargestWidth(work), 'jpg')}}"
    data-lightbox-jpg-srcset="${{sourceSet(work, 'jpg')}}"
    data-lightbox-webp-srcset="${{sourceSet(work, 'webp')}}"
    data-lightbox-sizes="${{sizes}}"
    data-lightbox-alt="${{escapeHtml(work.alt)}}"
    data-lightbox-title="${{escapeHtml(work.title)}}"
    data-lightbox-meta="${{escapeHtml(buildLightboxMeta(work))}}"
    data-lightbox-width="${{work.width}}"
    data-lightbox-height="${{work.height}}"
  `;
}}

export function buildAbsoluteUrl(path = '') {{
  const base = siteData.site.siteUrl || siteData.site.displayUrl || window.location.href;
  try {{
    return new URL(path, base).href;
  }} catch {{
    return path;
  }}
}}

export function getSeriesPath(slug) {{
  return `series.html?series=${{encodeURIComponent(slug)}}`;
}}

export function getPortfolioPath(slug = '') {{
  return slug ? `portfolio.html?series=${{encodeURIComponent(slug)}}` : 'portfolio.html';
}}

export function getWorkById(id) {{
  return workById.get(id);
}}


export function getSeriesBySlug(slug, {{ includePrivate = true }} = {{}}) {{
  const series = seriesBySlug.get(slug);
  if (!series) return undefined;
  if (!includePrivate && series.visibility === 'private') return undefined;
  return series;
}}

export function getSortedSeries({{ includePrivate = false }} = {{}}) {{
  const source = includePrivate ? allSeries : publicSeries;
  return [...source].sort((a, b) => compareNumber(a.order, b.order) || a.title.localeCompare(b.title));
}}

export function getSeriesWorks(slug, {{ includePrivate = true }} = {{}}) {{
  const source = includePrivate ? allWorks : publicWorks;
  return source
    .filter((work) => work.series === slug)
    .sort(
      (a, b) =>
        compareNumber(a.seriesOrder, b.seriesOrder) ||
        compareNumber(a.portfolioOrder, b.portfolioOrder) ||
        a.title.localeCompare(b.title)
    );
}}

export function getSeriesCover(series) {{
  return getWorkById(series.cardCoverWorkId || series.coverWorkId) || getSeriesWorks(series.slug, {{ includePrivate: true }})[0] || null;
}}

export function getSeriesCount(slug, {{ includePrivate = true }} = {{}}) {{
  return getSeriesWorks(slug, {{ includePrivate }}).length;
}}

export function getHeroWork() {{
  return getWorkById(siteData.site.heroWorkId) || publicWorks[0];
}}

export function getFeaturedSeries() {{
  return getSortedSeries().filter((series) => Number.isFinite(series.homeFeatureOrder));
}}

export function getHomeFeaturedWorks() {{
  return [...publicWorks]
    .filter((work) => Number.isFinite(work.homeFeatureOrder))
    .sort((a, b) => compareNumber(a.homeFeatureOrder, b.homeFeatureOrder));
}}

export function getPortfolioWorks() {{
  return [...publicWorks].sort(
    (a, b) => compareNumber(a.portfolioOrder, b.portfolioOrder) || a.title.localeCompare(b.title)
  );
}}

export function getSeriesNeighbors(slug, {{ includePrivate = false }} = {{}}) {{
  const ordered = getSortedSeries({{ includePrivate }});
  const index = ordered.findIndex((series) => series.slug === slug);
  if (index === -1) {{
    return {{ previous: ordered[0] || null, next: ordered[0] || null }};
  }}

  return {{
    previous: ordered[(index - 1 + ordered.length) % ordered.length],
    next: ordered[(index + 1) % ordered.length]
  }};
}}
'''




def render_sitemap_xml() -> str:
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


def render_readme() -> str:
    return """# STILLMRK - public static portfolio build

This package uses file-backed YAML content and responsive image generation to build the public website.

## What changed

The site uses small YAML files as the source of truth:

- `content/site.yaml`
- `content/artist.yaml`
- `content/navigation.yaml`
- `content/image-pipeline.yaml`
- `content/pages/*.yaml`
- `content/series/*.yaml`
- `content/works/*.yaml`

`build_site.py` now:
- loads content with `yaml.safe_load()`
- validates the assembled content against `content/schema/content.schema.json`
- checks cross-file references such as `series.work_ids`, series covers, homepage featured content, and duplicate responsive render names
- generates responsive images automatically
- removes stale generated responsive assets when works are removed or renamed
- rebuilds the HTML pages and `assets/js/data.js`
- refreshes the `public_upload/` folder after every successful build
- emits a branded `404.html` page and fallback Open Graph images when source photographs are not assigned yet
- avoids empty image preload tags in metadata-only builds

## Recommended local workflow

### Build the site
```bash
python build_site.py
```

### Preview the public site locally
```bash
python preview_server.py
```

Open:
- public site: `http://127.0.0.1:8000/`

Host upload target:
- upload only the contents of `public_upload/` to the host
- do not upload `content/` or the Python source files

## Content workflow

### Add a new photograph
1. Put one high-quality source file in `assets/images/originals/`
2. Create one YAML file in `content/works/`, ideally using the same id as the source filename
3. Add that work id to the correct series file in `content/series/`
4. Run `python build_site.py`

### Remove a photograph
1. Remove its id from any series file that references it
2. Delete its YAML file from `content/works/`
3. Delete the source image if you do not need it anymore
4. Run `python build_site.py`

### Reorder a series
Open the relevant file in `content/series/` and reorder the `work_ids` list.

## Validation

Run a full validation and build:

```bash
python build_site.py
```

Run validation only:

```bash
python build_site.py --validate-only
```

If validation fails, the build stops before it writes broken output.

## Folder structure

- `assets/images/originals/` → your source images
- `assets/images/responsive/` → generated site assets
- `content/works/` → one work per file
- `content/collections/` → parent collections such as Stage Works
- `content/series/` → one series/project per file
- `content/pages/` → page-level copy blocks
- `content/schema/content.schema.json` → structural validation
- `.stillmrk-build/responsive-assets.json` → manifest for generated responsive files
- `assets/images/social/` → generated social preview cards used by Open Graph/Twitter metadata

## Blunt note

This is a static-site workflow. It is simpler and safer because the public site is built directly from the same content files you keep locally.
"""

def update_app_js(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    text = text.replace(
        "      status.textContent = 'Update the contact email in assets/js/data.js before publishing. The draft cannot open until that address is real.';",
        "      status.textContent = 'Update the contact email in content/artist.yaml, then run python build_site.py before publishing. The draft cannot open until that address is real.';",
    )
    text = text.replace(
        "      status.textContent = 'Update the contact email in content/site_content.py, then run python build_site.py before publishing. The draft cannot open until that address is real.';",
        "      status.textContent = 'Update the contact email in content/artist.yaml, then run python build_site.py before publishing. The draft cannot open until that address is real.';",
    )
    text = text.replace(
        "  const loaders = {\n    home: () => import('./home.js'),\n    portfolio: () => import('./portfolio.js'),\n    series: () => import('./series.js')\n  };",
        "  const loaders = {\n    portfolio: () => import('./portfolio.js'),\n    series: () => import('./series.js')\n  };",
    )
    if 'const STILLMRK_DEBUG' not in text:
        text = text.replace(
            "const MAILTO_URL_LIMIT = 1800;",
            "const MAILTO_URL_LIMIT = 1800;\nconst STILLMRK_DEBUG = new URLSearchParams(window.location.search).has('debug') || window.localStorage?.getItem('stillmrk:debug') === '1';",
        )
    text = text.replace(
        "  } catch (error) {\n    console.error(`[STILLMRK] ${label} failed`, error);\n  }",
        "  } catch (error) {\n    if (STILLMRK_DEBUG) {\n      // Keep production quiet while still allowing explicit local diagnostics.\n      window.requestAnimationFrame(() => { throw new Error(`[STILLMRK] ${label} failed: ${error?.message || error}`); });\n    }\n  }",
    )
    text = text.replace(
        "      } catch (error) {\n        console.error(error);\n        setStatus('warning', 'The direct form submission did not complete. Use the direct email options below instead.');",
        "      } catch {\n        setStatus('warning', 'The direct form submission did not complete. Use the direct email options below instead.');",
    )

    text = text.replace(
        """  function syncNavA11y(isOpen = false) {\n    const isMobile = window.innerWidth <= mobileNavBreakpoint;\n    if (isMobile) {\n      nav.setAttribute('aria-hidden', String(!isOpen));\n      setInertState(nav, !isOpen);\n      setNavLinksTabbable(isOpen);\n    } else {\n      nav.removeAttribute('aria-hidden');\n      setInertState(nav, false);\n      setNavLinksTabbable(true);\n    }\n  }\n""",
        """  function syncNavA11y(isOpen = false) {\n    const isMobile = window.innerWidth <= mobileNavBreakpoint;\n    // Do not use native inert on the nav panel itself. Some mobile browser\n    // combinations keep inert descendants visually/semantically stale after\n    // toggling, which can produce an expanded empty black menu. CSS handles\n    // visibility; tabindex + aria-hidden handle keyboard/screen-reader state.\n    nav.removeAttribute('inert');\n    nav.removeAttribute('data-inert-fallback');\n    if (isMobile) {\n      nav.setAttribute('aria-hidden', String(!isOpen));\n      setNavLinksTabbable(isOpen);\n    } else {\n      nav.removeAttribute('aria-hidden');\n      setNavLinksTabbable(true);\n    }\n  }\n""",
    )
    text = text.replace(
        """function initSeriesScrollDots(root = document) {
  const tracks = [...root.querySelectorAll('.series-card-grid')].filter(
    (track) => !track.dataset.scrollDotsInit
  );
""",
        """function initSeriesScrollDots(root = document) {
  const tracks = [...root.querySelectorAll('.series-card-grid')].filter(
    (track) => !track.dataset.scrollDotsInit
      && !track.classList.contains('series-card-grid--performance')
      && track.dataset.scrollDots !== 'false'
      && track.closest('body')?.dataset.page !== 'performance'
  );
""",
    )
    path.write_text(text, encoding='utf-8')


def update_home_js(path: Path) -> None:
    path.write_text("document.dispatchEvent(new CustomEvent('stillmrk:refresh'));\n", encoding='utf-8')





def update_start_scripts() -> None:
    sh_path = ROOT / 'start-local-server.sh'
    sh_path.write_text("#!/usr/bin/env bash\nset -e\npython3 preview_server.py\n", encoding='utf-8')
    sh_path.chmod(0o755)

    bat_path = ROOT / 'start-local-server.bat'
    bat_path.write_text("@echo off\r\npython preview_server.py\r\n", encoding='utf-8')

    upload_sh_path = ROOT / 'prepare-host-upload.sh'
    upload_sh_path.write_text("#!/usr/bin/env bash\nset -e\npython3 build_site.py\nprintf '\nUpload the contents of ./public_upload to your host.\n'\n", encoding='utf-8')
    upload_sh_path.chmod(0o755)

    upload_bat_path = ROOT / 'prepare-host-upload.bat'
    upload_bat_path.write_text("@echo off\r\npython build_site.py\r\necho.\r\necho Upload the contents of the public_upload folder to your host.\r\n", encoding='utf-8')

    open_upload_bat_path = ROOT / 'open-public-upload-folder.bat'
    open_upload_bat_path.write_text('@echo off\r\nstart "" public_upload\r\n', encoding='utf-8')

    open_upload_sh_path = ROOT / 'open-public-upload-folder.sh'
    open_upload_sh_path.write_text("#!/usr/bin/env bash\nset -e\nprintf 'Open the public_upload folder in your file manager.\n'\n", encoding='utf-8')
    open_upload_sh_path.chmod(0o755)

def update_styles(path: Path) -> None:
    css = path.read_text(encoding='utf-8')
    additions = """

.feature-module-grid {
  display: grid;
  gap: 1.1rem;
  grid-template-columns: repeat(12, minmax(0, 1fr));
}

.feature-module {
  grid-column: span 6;
  display: grid;
  gap: 1rem;
  min-height: 100%;
}

.feature-module--spotlight {
  grid-column: span 12;
  grid-template-columns: minmax(0, 0.92fr) minmax(0, 1.08fr);
  align-items: center;
}

.feature-module__visual {
  position: relative;
  width: 100%;
  aspect-ratio: var(--media-ratio, 1 / 1);
  overflow: hidden;
  border-radius: var(--radius-xl);
  border: 1px solid var(--border);
  background: #101010;
  box-shadow: var(--shadow-lg);
}

.feature-module__visual img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.feature-module__body {
  display: grid;
  gap: 1rem;
}

.feature-module__title {
  margin: 0;
  font-family: var(--font-display);
  font-weight: 500;
  line-height: 1.05;
  letter-spacing: -0.02em;
  font-size: clamp(1.5rem, 2.8vw, 2.5rem);
}

@media (max-width: 980px) {
  .feature-module,
  .feature-module--spotlight {
    grid-column: span 12;
  }

  .feature-module--spotlight {
    grid-template-columns: 1fr;
  }
}
"""
    if ".feature-module-grid" not in css:
        css += additions

    batch2_additions = """

/* ─────────────────────────────────────────────────────────────
   Batch 2 — Responsive system and mobile polish
   Scope: safe areas, touch comfort, mobile navigation ergonomics,
   responsive type/grids, landscape viewing, LCP image priority,
   reveal thresholds, and native scroll momentum. Content untouched.
   ───────────────────────────────────────────────────────────── */
:root {
  --safe-top: env(safe-area-inset-top, 0px);
  --safe-right: env(safe-area-inset-right, 0px);
  --safe-bottom: env(safe-area-inset-bottom, 0px);
  --safe-left: env(safe-area-inset-left, 0px);
  --mobile-gutter: clamp(1rem, 5vw, 1.35rem);
  scroll-padding-top: calc(var(--actual-header-height, var(--header-height)) + 1rem);
}

html {
  min-height: 100%;
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
}

body {
  min-height: 100svh;
  -webkit-overflow-scrolling: touch;
}

@supports (min-height: 100dvh) {
  body {
    min-height: 100dvh;
  }
}

.skip-link:focus,
#main-content,
#contact-form,
:target {
  scroll-margin-top: calc(var(--actual-header-height, var(--header-height)) + var(--safe-top) + 1rem);
}

.site-header {
  padding-top: calc(0.35rem + var(--safe-top));
}

.site-header.is-scrolled {
  padding-top: calc(0.14rem + var(--safe-top));
}

.site-footer {
  padding-bottom: calc(clamp(2rem, 5vw, 2.8rem) + var(--safe-bottom));
}

.container,
.container-narrow,
.footer-shell {
  padding-left: max(0px, var(--safe-left));
  padding-right: max(0px, var(--safe-right));
}

button,
.button,
.nav-toggle,
.site-nav a,
.filter-chip,
.save-chip,
.text-link,
.pagination-link,
.series-index a,
.footer-links a,
.contact-downloads__item,
.series-card__footer a,
.work-card__footer a,
.lightbox__close,
.lightbox__nav,
.scroll-dots__dot,
.info-card__expand {
  touch-action: manipulation;
}

.button,
.nav-toggle,
.site-nav a,
.filter-chip,
.save-chip,
.pagination-link,
.series-index a,
.footer-links a,
.contact-downloads__item,
.series-card__footer a,
.work-card__footer a,
.lightbox__close,
.lightbox__nav,
.info-card__expand {
  min-width: 44px;
  min-height: 44px;
}

.text-link {
  display: inline-flex;
  align-items: center;
  min-height: 44px;
}

@media (hover: none) {
  .button:hover,
  .filter-chip:hover,
  .pagination-link:hover,
  .series-card:hover,
  .work-card:hover,
  .editorial-card:hover {
    transform: none;
  }
}

@media (max-width: 980px) {
  .site-header {
    position: sticky;
    top: 0;
  }

  .nav-shell {
    width: min(100% - (var(--mobile-gutter) * 2), 1360px);
    padding: 0.72rem 0.78rem;
  }

  .nav-toggle {
    width: 48px;
    height: 48px;
  }

  .site-nav {
    padding-bottom: max(0.8rem, var(--safe-bottom));
    scroll-padding-bottom: calc(1rem + var(--safe-bottom));
  }

  .site-nav a {
    min-height: 52px;
    padding-block: 1rem;
    -webkit-tap-highlight-color: transparent;
  }

  .site-nav a.site-nav__cta {
    justify-content: center;
  }
}

@media (max-width: 760px) {
  .container,
  .container-narrow,
  .footer-shell {
    width: min(100% - (var(--mobile-gutter) * 2), 100%);
  }

  .section {
    padding-block: clamp(2.6rem, 12vw, 4.2rem);
  }

  .section--compact {
    padding-block: clamp(2rem, 9vw, 3.2rem);
  }

  .display-title,
  .page-title {
    max-width: 11.5ch;
    font-size: clamp(2.6rem, 15vw, 4.6rem);
    line-height: 0.92;
    letter-spacing: -0.055em;
  }

  .section-title,
  .series-story-map .section-title,
  body[data-page="series"] .series-story-map .section-title {
    max-width: 13ch;
    font-size: clamp(1.8rem, 9.5vw, 2.65rem);
    line-height: 1.02;
    letter-spacing: -0.04em;
  }

  .hero__lead,
  .page-hero__lead,
  .section-intro,
  .statement-card p,
  .contact-card p,
  .info-card p,
  .series-frame__body p,
  .work-card__body p,
  .editorial-card__body p {
    font-size: clamp(1rem, 4vw, 1.08rem);
    line-height: 1.64;
  }

  .hero__layout,
  .about-hero,
  .page-hero__layout,
  .series-masthead,
  .contact-grid,
  .statement-grid,
  .about-band,
  .series-layout,
  .metrics-grid,
  .card-grid,
  .work-grid,
  .editorial-grid,
  .field-grid,
  .download-grid,
  .private-series-form__grid {
    grid-template-columns: minmax(0, 1fr) !important;
  }

  .work-grid > *,
  .card-grid > *,
  .editorial-grid > *,
  .metrics-grid > *,
  .field-grid > *,
  .download-grid > * {
    grid-column: auto !important;
    min-width: 0;
  }

  .work-grid--portfolio .work-card,
  .work-grid--portfolio .work-card--lead,
  .work-grid--portfolio .work-card--accent,
  .work-grid--portfolio .work-card--twin,
  .work-grid--portfolio .work-card--full,
  .work-grid--portfolio .work-card--layout-quiet,
  .work-grid--portfolio .work-card--layout-standard,
  .work-grid--portfolio .work-card--layout-medium,
  .work-grid--portfolio .work-card--layout-large,
  .work-grid--portfolio .work-card--layout-wide,
  .work-grid--portfolio .work-card--layout-full {
    grid-column: auto !important;
    width: 100%;
  }

  .portfolio-tools__row,
  .portfolio-tools__meta,
  .portfolio-shortlist-bar,
  .contact-shortlist,
  .private-series-form__actions,
  .series-frame__actions,
  .work-card__actions {
    grid-template-columns: minmax(0, 1fr) !important;
    align-items: stretch;
  }

  .button,
  .filter-chip,
  .save-chip,
  .text-link,
  .contact-downloads__item,
  .pagination-link {
    min-height: 48px;
  }

  input,
  select,
  textarea {
    font-size: 16px;
    min-height: 52px;
  }

  .hero__visual,
  .hero--home .hero__visual,
  .page-hero__visual,
  .about-hero__visual,
  .series-masthead__visual {
    max-height: none;
  }

  .series-card-grid:not(.series-card-grid--performance) {
    scroll-padding-inline: var(--mobile-gutter);
    padding-inline: var(--mobile-gutter);
    margin-inline: calc(var(--mobile-gutter) * -1);
  }

  .series-card-grid:not(.series-card-grid--performance) .series-card {
    flex-basis: min(86vw, 24rem);
  }

  .filter-row,
  .hero__notes,
  .series-card-grid:not(.series-card-grid--performance) {
    -webkit-overflow-scrolling: touch;
    overscroll-behavior-inline: contain;
  }

  .mobile-contact-bar {
    left: max(var(--mobile-gutter), var(--safe-left));
    right: max(var(--mobile-gutter), var(--safe-right));
    bottom: calc(0.9rem + var(--safe-bottom));
  }
}

@media (max-width: 360px) {
  :root {
    --mobile-gutter: 0.9rem;
  }

  .display-title,
  .page-title {
    font-size: clamp(2.25rem, 14vw, 3.2rem);
  }

  .section-title {
    font-size: clamp(1.55rem, 8.5vw, 2.1rem);
  }

  .site-nav a,
  .button,
  .filter-chip,
  .pagination-link {
    padding-inline: 0.85rem;
  }
}

@media (orientation: landscape) and (max-height: 500px) {
  .site-header {
    padding-top: calc(0.08rem + var(--safe-top));
  }

  .nav-shell {
    padding-block: 0.45rem;
  }

  .brand__eyebrow {
    display: none;
  }

  .nav-toggle {
    width: 44px;
    height: 44px;
  }

  .site-nav a {
    min-height: 44px;
    padding-block: 0.72rem;
  }

  .hero,
  .page-hero,
  .series-masthead {
    padding-top: clamp(0.75rem, 3vw, 1.25rem);
  }

  .hero__visual,
  .page-hero__visual,
  .about-hero__visual,
  .series-masthead__visual {
    aspect-ratio: 16 / 9;
    max-height: calc(100dvh - var(--actual-header-height, var(--header-height)) - 2.5rem);
  }

  .lightbox {
    height: 100dvh;
    max-height: 100dvh;
  }

  .lightbox__media {
    max-height: calc(100dvh - 6.5rem);
  }
}

@media (prefers-reduced-motion: reduce) {
  html {
    scroll-behavior: auto;
  }

  .filter-row,
  .series-card-grid {
    scroll-behavior: auto;
  }
}
"""
    if "Batch 2 — Responsive system and mobile polish" not in css:
        css += batch2_additions
    batch3_additions = '\n\n/* ─────────────────────────────────────────────────────────────\n   Batch 3 — Visual hierarchy and premium UI polish\n   Scope: typographic rhythm, atmospheric surfaces, restrained hover\n   states, brand lockup, captions, cards, filters, and color harmony.\n   Content and structure untouched.\n   ───────────────────────────────────────────────────────────── */\n:root {\n  --surface: rgba(255, 255, 255, 0.038);\n  --surface-strong: rgba(255, 255, 255, 0.068);\n  --surface-soft: rgba(255, 255, 255, 0.024);\n  --border: rgba(255, 255, 255, 0.085);\n  --border-strong: rgba(255, 255, 255, 0.16);\n  --border-soft: rgba(255, 255, 255, 0.055);\n  --text-soft: rgba(242, 239, 232, 0.8);\n  --text-secondary: rgba(242, 239, 232, 0.8);\n  --text-muted: rgba(242, 239, 232, 0.62);\n  --shadow-lg: 0 34px 96px rgba(0, 0, 0, 0.38);\n  --shadow-md: 0 18px 56px rgba(0, 0, 0, 0.24);\n  --shadow-card: 0 18px 54px rgba(0, 0, 0, 0.28);\n  --ease-premium: cubic-bezier(0.16, 1, 0.3, 1);\n  --transition: 220ms var(--ease-premium);\n  --transition-slow: 620ms var(--ease-premium);\n  --tracking-eyebrow: 0.215em;\n}\n\nbody {\n  background:\n    radial-gradient(circle at 16% 0%, rgba(216, 197, 162, 0.07), transparent 26rem),\n    radial-gradient(circle at 86% 8%, rgba(255, 255, 255, 0.034), transparent 25rem),\n    radial-gradient(circle at 50% 115%, rgba(216, 197, 162, 0.035), transparent 34rem),\n    linear-gradient(180deg, #0d0d0c 0%, #090909 46%, #070707 100%);\n}\n\nbody::before {\n  background:\n    linear-gradient(180deg, rgba(255, 255, 255, 0.016), transparent 20%),\n    radial-gradient(circle at 50% 12%, transparent 0%, rgba(0, 0, 0, 0.18) 84%),\n    repeating-linear-gradient(90deg, rgba(255, 255, 255, 0.006) 0 1px, transparent 1px 6px);\n  opacity: calc(0.34 + (var(--scroll-progress) * 0.05));\n}\n\n.display-title,\n.section-title,\n.work-card__title,\n.series-card h3,\n.editorial-card h3,\n.series-frame h2,\n.info-card h2,\n.empty-state h2,\n.feature-module__title,\n.hero-proof__title {\n  font-feature-settings: "kern" 1, "liga" 1;\n  text-wrap: balance;\n}\n\n.display-title {\n  line-height: 0.98;\n  letter-spacing: -0.035em;\n  max-width: 12.6ch;\n}\n\n.section-title {\n  line-height: 1;\n  letter-spacing: -0.026em;\n  max-width: 15ch;\n}\n\n.section-intro,\n.page-hero__lead,\n.hero__lead,\n.muted-copy,\n.hero-proof__text,\n.form-note,\n.toolbar-note,\n.footer-copy p,\n.series-card p,\n.work-card__body p,\n.editorial-card__body p,\n.series-frame__body p,\n.contact-card p,\n.info-card p,\n.statement-card p,\n.about-band__aside p {\n  line-height: 1.62;\n  letter-spacing: -0.006em;\n}\n\n.eyebrow,\n.brand__eyebrow,\n.field span,\n.pagination-link span,\n.media-caption span,\n.lightbox__counter,\n.lightbox__caption span {\n  font-family: var(--font-sans);\n  font-weight: 750;\n  letter-spacing: var(--tracking-eyebrow);\n  text-transform: uppercase;\n}\n\n.eyebrow {\n  color: rgba(216, 197, 162, 0.72);\n  font-size: clamp(0.72rem, 0.78vw, 0.8rem);\n}\n\n.section-head {\n  gap: clamp(1.4rem, 3vw, 2.6rem);\n  margin-bottom: clamp(1.7rem, 3vw, 2.6rem);\n}\n\n.section-head__copy {\n  gap: 0.9rem;\n}\n\n.site-header.is-solid .nav-shell,\n.site-header.is-scrolled .nav-shell,\n.nav-shell {\n  border-color: rgba(255, 255, 255, 0.075);\n}\n\n.nav-shell {\n  box-shadow: 0 10px 44px rgba(0, 0, 0, 0.16);\n}\n\n.brand {\n  gap: 0.06rem;\n  max-inline-size: min(22rem, 62vw);\n}\n\n.brand__eyebrow {\n  color: rgba(216, 197, 162, 0.74);\n  font-size: 0.64rem;\n  line-height: 1;\n}\n\n.brand__name {\n  font-weight: 600;\n  line-height: 1.05;\n  letter-spacing: -0.01em;\n  color: var(--text-primary);\n}\n\n.site-nav a {\n  letter-spacing: -0.006em;\n}\n\n.site-nav a.is-active {\n  color: #090909;\n  background: var(--accent);\n}\n\n.site-nav a:not(.site-nav__cta):hover {\n  background: rgba(216, 197, 162, 0.11);\n}\n\n.hero__layout,\n.hero--portfolio .hero__layout,\n.page-hero__layout,\n.about-hero,\n.series-masthead {\n  gap: clamp(1.4rem, 4vw, 3.2rem);\n}\n\n.hero__layout,\n.hero--portfolio .hero__layout {\n  grid-template-columns: minmax(0, 0.84fr) minmax(320px, 1.16fr);\n}\n\n.hero__copy,\n.page-hero__copy,\n.about-hero__copy,\n.series-masthead__copy {\n  gap: clamp(0.95rem, 1.8vw, 1.35rem);\n  padding-block-start: clamp(0.1rem, 1.4vw, 1rem);\n}\n\n.hero__lead-group {\n  gap: 1rem;\n}\n\n.hero__visual,\n.about-hero__visual,\n.series-masthead__visual,\n.page-hero__visual {\n  border-radius: clamp(1.45rem, 2.4vw, 2.55rem);\n  box-shadow: 0 34px 92px rgba(0, 0, 0, 0.36);\n}\n\n.hero-figure,\n.series-masthead__figure,\n.about-hero__figure,\n.page-hero__figure {\n  gap: 1rem;\n}\n\n.hero__notes li,\n.series-masthead__facts span {\n  border-color: rgba(255, 255, 255, 0.075);\n  background: rgba(255, 255, 255, 0.022);\n  color: var(--text-secondary);\n  font-size: 0.94rem;\n}\n\n.panel,\n.metric-card,\n.portfolio-tools--header,\n.portfolio-tools--footer,\n.contact-card,\n.info-card,\n.statement-card,\n.pagination-link {\n  border-color: var(--border-soft);\n  background:\n    linear-gradient(180deg, rgba(255, 255, 255, 0.054), rgba(255, 255, 255, 0.018)),\n    radial-gradient(circle at 22% 12%, rgba(216, 197, 162, 0.035), transparent 48%);\n  box-shadow: var(--shadow-card);\n}\n\n.panel--soft {\n  background:\n    linear-gradient(180deg, rgba(255, 255, 255, 0.038), rgba(255, 255, 255, 0.014)),\n    radial-gradient(circle at 18% 8%, rgba(216, 197, 162, 0.022), transparent 50%);\n}\n\n.series-card,\n.work-card,\n.editorial-card,\n.feature-module,\n.metric-card,\n.pagination-link,\n.contact-card,\n.info-card,\n.statement-card {\n  transition:\n    transform var(--transition),\n    border-color var(--transition),\n    background var(--transition),\n    box-shadow var(--transition);\n}\n\n.series-card__media,\n.work-card__media,\n.editorial-card__media,\n.series-frame__media,\n.feature-module__visual,\n.hero__visual,\n.about-hero__visual,\n.series-masthead__visual,\n.page-hero__visual {\n  border-color: rgba(255, 255, 255, 0.075);\n}\n\n.series-card__media::after,\n.work-card__media::after,\n.editorial-card__media::after,\n.series-frame__media::after,\n.feature-module__visual::after,\n.hero__visual::after,\n.about-hero__visual::after,\n.series-masthead__visual::after,\n.page-hero__visual::after {\n  content: "";\n  position: absolute;\n  inset: 0;\n  pointer-events: none;\n  background:\n    linear-gradient(180deg, rgba(255, 255, 255, 0.025), transparent 32%),\n    linear-gradient(0deg, rgba(0, 0, 0, 0.08), transparent 45%);\n  opacity: 0.52;\n  transition: opacity var(--transition-slow);\n}\n\n.hero__visual img,\n.about-hero__visual img,\n.series-masthead__visual img,\n.page-hero__visual img,\n.work-card__media img,\n.series-card__media img,\n.editorial-card__media img,\n.series-frame__media img,\n.feature-module__visual img {\n  transition: transform 760ms var(--ease-premium);\n}\n\n.series-card__body,\n.work-card__body,\n.editorial-card__body,\n.series-frame__body {\n  gap: 0.82rem;\n  padding: clamp(1.05rem, 1.6vw, 1.28rem) clamp(1.05rem, 1.7vw, 1.35rem) clamp(1.15rem, 1.8vw, 1.45rem);\n}\n\n.series-card__meta,\n.work-card__meta,\n.editorial-card__meta,\n.series-frame__meta,\n.work-card__footer,\n.series-card__footer {\n  color: var(--text-muted);\n  font-size: clamp(0.76rem, 0.86vw, 0.88rem);\n  letter-spacing: 0.055em;\n  font-variant-numeric: tabular-nums;\n}\n\n.series-card__meta span,\n.work-card__meta span,\n.editorial-card__meta span,\n.series-frame__meta span,\n.work-card__footer span,\n.series-card__footer span {\n  overflow-wrap: anywhere;\n}\n\n.work-card__title,\n.series-card h3,\n.editorial-card h3,\n.series-frame h2 {\n  line-height: 1.06;\n  letter-spacing: -0.024em;\n}\n\n.work-card__body p,\n.series-card p,\n.editorial-card__body p,\n.series-frame__body p {\n  color: rgba(242, 239, 232, 0.72);\n}\n\n.work-grid--portfolio .work-card__body p {\n  color: rgba(242, 239, 232, 0.64);\n}\n\n.media-caption {\n  gap: 0.28rem;\n  padding-inline: clamp(0.25rem, 1vw, 0.55rem);\n  max-inline-size: min(76ch, 100%);\n}\n\n.media-caption strong {\n  font-family: var(--font-display);\n  font-size: clamp(1.02rem, 1.25vw, 1.18rem);\n  font-weight: 600;\n  line-height: 1.12;\n  letter-spacing: -0.014em;\n}\n\n.media-caption small {\n  color: rgba(242, 239, 232, 0.72);\n  font-size: clamp(0.9rem, 0.95vw, 0.98rem);\n  line-height: 1.55;\n  max-width: 74ch;\n}\n\n.button,\n.site-nav a.site-nav__cta {\n  background: var(--accent);\n  color: #080807;\n  box-shadow: 0 10px 30px rgba(216, 197, 162, 0.12);\n}\n\n.button:hover,\n.site-nav a.site-nav__cta:hover {\n  background: #eadbbd;\n}\n\n.button--secondary,\n.button--ghost {\n  background: rgba(255, 255, 255, 0.035);\n  color: var(--text-primary);\n  border-color: rgba(255, 255, 255, 0.105);\n  box-shadow: none;\n}\n\n.button--secondary:hover,\n.button--ghost:hover {\n  background: rgba(216, 197, 162, 0.09);\n  border-color: rgba(216, 197, 162, 0.28);\n}\n\n.button:active,\n.filter-chip:active,\n.site-nav a:active,\n.series-card__footer a:active,\n.work-card__footer a:active {\n  transform: translateY(0) scale(0.985);\n}\n\n.field span {\n  color: rgba(216, 197, 162, 0.62);\n  font-size: 0.72rem;\n}\n\ninput,\nselect,\ntextarea {\n  border-color: rgba(255, 255, 255, 0.095);\n  background:\n    linear-gradient(180deg, rgba(255, 255, 255, 0.052), rgba(255, 255, 255, 0.026));\n  color: var(--text-primary);\n}\n\nselect {\n  appearance: none;\n  padding-right: 2.9rem;\n  background-image:\n    linear-gradient(45deg, transparent 50%, rgba(216, 197, 162, 0.82) 50%),\n    linear-gradient(135deg, rgba(216, 197, 162, 0.82) 50%, transparent 50%),\n    linear-gradient(180deg, rgba(255, 255, 255, 0.052), rgba(255, 255, 255, 0.026));\n  background-position:\n    calc(100% - 1.15rem) 55%,\n    calc(100% - 0.82rem) 55%,\n    0 0;\n  background-size: 0.34rem 0.34rem, 0.34rem 0.34rem, 100% 100%;\n  background-repeat: no-repeat;\n}\n\n.field__clear {\n  transition: transform var(--transition), border-color var(--transition), background var(--transition), color var(--transition);\n}\n\n.field__clear:hover {\n  border-color: rgba(216, 197, 162, 0.32);\n  background: rgba(216, 197, 162, 0.1);\n  color: var(--text-primary);\n}\n\n.portfolio-tools--header,\n.portfolio-tools--footer {\n  padding: clamp(1.05rem, 1.8vw, 1.45rem);\n}\n\n.portfolio-tools__row {\n  grid-template-columns: minmax(0, 1fr) minmax(13rem, 0.3fr);\n}\n\n.filter-row {\n  gap: 0.62rem;\n}\n\n.filter-chip {\n  min-height: 2.85rem;\n  padding: 0.65rem 0.9rem;\n  font-weight: 650;\n  letter-spacing: -0.006em;\n  border-color: rgba(255, 255, 255, 0.095);\n  background: rgba(255, 255, 255, 0.028);\n}\n\n.filter-chip small {\n  font-variant-numeric: tabular-nums;\n  color: rgba(242, 239, 232, 0.56);\n}\n\n.filter-chip:hover,\n.filter-chip:focus-visible {\n  border-color: rgba(216, 197, 162, 0.32);\n  background: rgba(216, 197, 162, 0.085);\n  color: var(--text-primary);\n}\n\n.filter-chip.is-active {\n  color: #080807;\n  background: var(--accent);\n  border-color: transparent;\n  box-shadow: 0 10px 32px rgba(216, 197, 162, 0.12), inset 0 1px 2px rgba(255, 255, 255, 0.22);\n}\n\n.filter-chip.is-active small {\n  color: rgba(8, 8, 7, 0.66);\n}\n\n.toolbar-note,\n.portfolio-tools__meta {\n  font-variant-numeric: tabular-nums;\n}\n\n.footer-shell {\n  border-top-color: rgba(255, 255, 255, 0.07);\n}\n\n.footer-copy strong,\n.footer-wordmark {\n  color: var(--text-primary);\n  letter-spacing: -0.014em;\n}\n\n.footer-links a {\n  border-radius: 999px;\n  transition: color var(--transition), background var(--transition), transform var(--transition);\n}\n\n.footer-links a:hover,\n.footer-links a:focus-visible {\n  color: var(--accent);\n  background: rgba(216, 197, 162, 0.07);\n}\n\n.nav-backdrop,\n.lightbox::backdrop {\n  will-change: auto;\n}\n\n@media (hover: hover) and (pointer: fine) {\n  .series-card.panel:hover,\n  .editorial-card.panel:hover,\n  .work-card.panel:hover,\n  .feature-module.panel:hover,\n  .pagination-link:hover {\n    transform: translateY(-3px);\n    border-color: rgba(216, 197, 162, 0.22);\n    box-shadow: 0 24px 70px rgba(0, 0, 0, 0.34);\n  }\n\n  .metric-card:hover,\n  .contact-card:hover,\n  .info-card:hover,\n  .statement-card:hover {\n    border-color: rgba(216, 197, 162, 0.16);\n  }\n\n  .series-card__media:hover::after,\n  .work-card__media:hover::after,\n  .editorial-card__media:hover::after,\n  .series-frame__media:hover::after,\n  .feature-module__visual:hover::after,\n  .hero__visual:hover::after,\n  .about-hero__visual:hover::after,\n  .series-masthead__visual:hover::after,\n  .page-hero__visual:hover::after {\n    opacity: 0.34;\n  }\n}\n\n@media (max-width: 1100px) {\n  .hero__layout,\n  .hero--portfolio .hero__layout,\n  .page-hero__layout,\n  .about-hero,\n  .series-masthead {\n    grid-template-columns: 1fr;\n  }\n\n  .hero__copy,\n  .page-hero__copy,\n  .about-hero__copy,\n  .series-masthead__copy {\n    padding-block-start: 0;\n  }\n}\n\n@media (max-width: 760px) {\n  :root {\n    --tracking-eyebrow: 0.18em;\n  }\n\n  body {\n    background:\n      radial-gradient(circle at 50% -8%, rgba(216, 197, 162, 0.055), transparent 18rem),\n      linear-gradient(180deg, #0d0d0c 0%, #080808 100%);\n  }\n\n  .display-title {\n    letter-spacing: -0.028em;\n    max-width: 11.5ch;\n  }\n\n  .section-title {\n    max-width: 12ch;\n  }\n\n  .series-card__meta,\n  .work-card__meta,\n  .editorial-card__meta,\n  .series-frame__meta,\n  .work-card__footer,\n  .series-card__footer {\n    gap: 0.42rem 0.75rem;\n    font-size: 0.78rem;\n  }\n\n  .portfolio-tools--header,\n  .portfolio-tools--footer {\n    border-radius: var(--radius-lg);\n  }\n\n  .filter-row {\n    flex-wrap: nowrap;\n    overflow-x: auto;\n    padding-bottom: 0.3rem;\n    scroll-snap-type: x proximity;\n    scrollbar-width: none;\n  }\n\n  .filter-row::-webkit-scrollbar {\n    display: none;\n  }\n\n  .filter-chip {\n    flex: 0 0 auto;\n    scroll-snap-align: start;\n  }\n\n  .media-caption {\n    padding-inline: 0.1rem;\n  }\n}\n\n@media (prefers-reduced-motion: reduce) {\n  .series-card,\n  .work-card,\n  .editorial-card,\n  .feature-module,\n  .metric-card,\n  .pagination-link,\n  .button,\n  .filter-chip,\n  .site-nav a,\n  .hero__visual img,\n  .about-hero__visual img,\n  .series-masthead__visual img,\n  .page-hero__visual img,\n  .work-card__media img,\n  .series-card__media img,\n  .editorial-card__media img,\n  .series-frame__media img,\n  .feature-module__visual img {\n    transition: none !important;\n    transform: none !important;\n  }\n}\n'
    if 'Batch 3 — Visual hierarchy and premium UI polish' not in css:
        css += batch3_additions

    batch4_additions = '''

/* ─────────────────────────────────────────────────────────────
   Batch 4 — Interaction, accessibility, and usability QA
   Scope: keyboard flow, focus visibility, ARIA state feedback,
   loading/error states, readable captions, consistent interactive
   affordances, and reduced-motion-safe scrolling. Content untouched.
   ───────────────────────────────────────────────────────────── */
:root {
  --focus-ring: 0 0 0 3px rgba(216, 197, 162, 0.34), 0 0 0 6px rgba(8, 8, 7, 0.88);
  --focus-outline: 2px solid rgba(216, 197, 162, 0.98);
  --error: #f0b8a8;
  --success: #b9d8bf;
}

html {
  scroll-behavior: smooth;
}

@media (prefers-reduced-motion: reduce) {
  html {
    scroll-behavior: auto;
  }
}

:focus:not(:focus-visible) {
  outline: none;
}

:where(a, button, input, select, textarea, summary, [tabindex]):focus-visible,
.filter-chip:focus-visible,
.save-chip:focus-visible,
.pagination-link:focus-visible,
.info-card__expand:focus-visible,
.lightbox__figure:focus-visible {
  outline: var(--focus-outline);
  outline-offset: 4px;
  box-shadow: var(--focus-ring);
}

.work-card:focus-within,
.series-card:focus-within,
.editorial-card:focus-within,
.contact-card:focus-within,
.info-card:focus-within,
.statement-card:focus-within,
.portfolio-tools:focus-within {
  border-color: rgba(216, 197, 162, 0.34);
  box-shadow: var(--shadow-card), 0 0 0 1px rgba(216, 197, 162, 0.12);
}

.skip-link:focus-visible {
  outline-offset: 6px;
}

.site-nav[aria-hidden="true"] {
  pointer-events: none;
}

.site-nav a[aria-current="page"],
.site-nav a.is-active,
.filter-chip[aria-current="true"] {
  text-decoration: none;
}

.button,
.button--secondary,
.button--ghost,
.text-link,
.filter-chip,
.save-chip,
.pagination-link,
.site-nav a,
.footer-links a,
.contact-downloads__item,
.info-card__expand,
.field__clear,
.lightbox__close,
.lightbox__nav {
  -webkit-tap-highlight-color: transparent;
}

.button:active,
.button--secondary:active,
.button--ghost:active,
.text-link:active,
.filter-chip:active,
.save-chip:active,
.pagination-link:active,
.site-nav a:active,
.footer-links a:active,
.contact-downloads__item:active,
.info-card__expand:active,
.field__clear:active,
.lightbox__close:active,
.lightbox__nav:active {
  transform: translateY(1px) scale(0.985);
}

input[aria-invalid="true"],
select[aria-invalid="true"],
textarea[aria-invalid="true"] {
  border-color: rgba(240, 184, 168, 0.74);
  box-shadow: 0 0 0 1px rgba(240, 184, 168, 0.24), 0 0 0 5px rgba(240, 184, 168, 0.08);
}

.form-note[data-state="warning"],
[data-series-access-status][data-state="warning"] {
  color: var(--error);
}

.form-note[data-state="success"],
[data-series-access-status][data-state="success"] {
  color: var(--success);
}

.hero__visual.is-loading,
.about-hero__visual.is-loading,
.series-masthead__visual.is-loading,
.page-hero__visual.is-loading,
.work-card__media.is-loading,
.series-card__media.is-loading,
.editorial-card__media.is-loading,
.series-frame__media.is-loading,
.feature-module__visual.is-loading {
  background:
    linear-gradient(100deg, rgba(255, 255, 255, 0.035) 0%, rgba(216, 197, 162, 0.06) 42%, rgba(255, 255, 255, 0.035) 78%),
    #10100f;
  background-size: 220% 100%, 100% 100%;
  animation: stillmark-media-pulse 1.4s ease-in-out infinite;
}

@keyframes stillmark-media-pulse {
  0% { background-position: 120% 0, 0 0; }
  100% { background-position: -120% 0, 0 0; }
}

.media-caption,
.lightbox__caption,
.work-card__body p,
.series-frame__body p {
  color: rgba(242, 239, 232, 0.78);
}

.media-caption small,
.lightbox__caption span {
  color: rgba(242, 239, 232, 0.74);
}

.lightbox[open] {
  outline: none;
}

.lightbox__hint {
  color: rgba(242, 239, 232, 0.72);
}

.protected-media-notice {
  pointer-events: none;
}

@media (max-width: 760px) {
  :where(a, button, input, select, textarea, summary, [tabindex]):focus-visible,
  .filter-chip:focus-visible,
  .save-chip:focus-visible,
  .pagination-link:focus-visible,
  .info-card__expand:focus-visible {
    outline-offset: 3px;
  }

  .media-caption small,
  .work-card__body p,
  .series-frame__body p {
    line-height: 1.62;
  }
}

@media (prefers-reduced-motion: reduce) {
  .hero__visual.is-loading,
  .about-hero__visual.is-loading,
  .series-masthead__visual.is-loading,
  .page-hero__visual.is-loading,
  .work-card__media.is-loading,
  .series-card__media.is-loading,
  .editorial-card__media.is-loading,
  .series-frame__media.is-loading,
  .feature-module__visual.is-loading {
    animation: none !important;
  }
}'''
    if 'Batch 4 — Interaction, accessibility, and usability QA' not in css:
        css += batch4_additions


    batch5_additions = '''

/* ─────────────────────────────────────────────────────────────
   Batch 5 — Performance, SEO-safe polish, and final QA
   Scope: critical-render stability, containment fallbacks, metadata-only
   share-card support, link/404 polish, and production cleanup.
   Content and core architecture untouched.
   ───────────────────────────────────────────────────────────── */
:root {
  --deferred-size: 960px;
  --not-found-min-height: min(72vh, 48rem);
}

picture > img,
.hero__visual > img,
.about-hero__visual > img,
.series-masthead__visual > img,
.page-hero__visual > img,
.work-card__media > img,
.series-card__media > img,
.editorial-card__media > img,
.series-frame__media > img,
.feature-module__visual > img {
  inline-size: 100%;
}

[data-deferred="portfolio-tools-bottom"] {
  --deferred-size: 320px;
}

[data-deferred="performance-guide"] {
  --deferred-size: 620px;
}

[data-deferred="about-downloads"] {
  --deferred-size: 760px;
}

@supports (content-visibility: auto) {
  [data-deferred] {
    contain: layout paint style;
  }
}

@supports not (content-visibility: auto) {
  [data-deferred] {
    contain: layout paint;
  }
}

.not-found-hero {
  min-block-size: var(--not-found-min-height);
  display: grid;
  align-items: center;
  text-align: center;
}

.not-found-hero .container-narrow {
  display: grid;
  justify-items: center;
  gap: clamp(1rem, 2.2vw, 1.5rem);
}

.not-found-hero .display-title {
  max-width: 12ch;
}

.not-found-hero .page-hero__lead {
  max-width: 44rem;
}

.not-found-hero .hero__actions {
  justify-content: center;
}

.media-placeholder {
  contain: layout paint;
  overflow: hidden;
}

.media-placeholder::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: radial-gradient(circle at 72% 18%, rgba(216, 197, 162, 0.08), transparent 32%);
}

@media (prefers-reduced-data: reduce) {
  body::before {
    display: none;
  }

  .hero__visual.is-loading,
  .about-hero__visual.is-loading,
  .series-masthead__visual.is-loading,
  .page-hero__visual.is-loading,
  .work-card__media.is-loading,
  .series-card__media.is-loading,
  .editorial-card__media.is-loading,
  .series-frame__media.is-loading,
  .feature-module__visual.is-loading {
    animation: none !important;
  }
}

@media (forced-colors: active) {
  .button,
  .button--secondary,
  .button--ghost,
  .filter-chip,
  .site-nav a,
  .pagination-link {
    border: 1px solid ButtonText;
  }

  :where(a, button, input, select, textarea, summary, [tabindex]):focus-visible {
    outline: 2px solid Highlight;
    box-shadow: none;
  }
}
'''
    if 'Batch 5 — Performance, SEO-safe polish, and final QA' not in css:
        css += batch5_additions

    hotfix_additions = '''

/* ─────────────────────────────────────────────────────────────
   Batch 5 Hotfix — visibility fallback and header spacing repair
   Fixes:
   1) Reveal fallback must beat the motion-ready hiding selector when JS modules
      fail or file:// preview blocks imports.
   2) Safe-area rules must not erase the nav shell's horizontal padding.
   ───────────────────────────────────────────────────────────── */
html.js.motion-ready.reveal-fallback .reveal,
html.js.reveal-fallback .reveal,
html.reveal-fallback .reveal,
html:not(.js) .reveal {
  opacity: 1 !important;
  transform: none !important;
  transition: none !important;
}

.nav-shell {
  padding-inline: calc(1rem + var(--safe-left, 0px)) calc(1rem + var(--safe-right, 0px));
}

@media (max-width: 980px) {
  .nav-shell {
    padding-inline: calc(0.78rem + var(--safe-left, 0px)) calc(0.78rem + var(--safe-right, 0px));
  }
}

@media (orientation: landscape) and (max-height: 500px) {
  .nav-shell {
    padding-inline: calc(0.78rem + var(--safe-left, 0px)) calc(0.78rem + var(--safe-right, 0px));
  }
}
'''
    if 'Batch 5 Hotfix — visibility fallback and header spacing repair' not in css:
        css += hotfix_additions

    above_fold_reveal_hotfix = '''

/* Above-fold safety: hero/page masthead content must never depend on JS reveal.
   This prevents the black first viewport when module loading is blocked or slow. */
html.js.motion-ready .hero .reveal,
html.js.motion-ready .page-hero .reveal,
html.js.motion-ready .about-hero.reveal,
html.js.motion-ready .series-masthead.reveal,
html.js.motion-ready .contact-grid > .reveal:first-child {
  opacity: 1 !important;
  transform: none !important;
}
'''
    if 'Above-fold safety: hero/page masthead content must never depend on JS reveal' not in css:
        css += above_fold_reveal_hotfix



    hotfix2_additions = '\n\n/* ─────────────────────────────────────────────────────────────\n   Batch 5 Hotfix 2 — image-fidelity overlay removal + mobile nav repair\n   Fixes:\n   1) Remove the visible top veil from lead/featured photography.\n   2) Keep the mobile menu in the header flow so it shows real links instead\n      of expanding as an empty full-screen black sheet.\n   ───────────────────────────────────────────────────────────── */\n.hero__visual::after,\n.about-hero__visual::after,\n.series-masthead__visual::after,\n.page-hero__visual::after,\n.work-card__media::after,\n.series-card__media::after,\n.editorial-card__media::after,\n.series-frame__media::after,\n.feature-module__visual::after,\n.media-placeholder::after {\n  content: none !important;\n  display: none !important;\n  opacity: 0 !important;\n  background: none !important;\n}\n\n@media (max-width: 980px) {\n  .site-header {\n    z-index: 10000 !important;\n    overflow: visible !important;\n  }\n\n  .site-header .nav-shell {\n    display: grid !important;\n    grid-template-columns: minmax(0, 1fr) auto !important;\n    align-items: center !important;\n    overflow: visible !important;\n  }\n\n  .site-header .nav-toggle {\n    display: grid !important;\n    grid-column: 2 !important;\n    grid-row: 1 !important;\n    justify-self: end !important;\n  }\n\n  .site-header .site-nav {\n    position: static !important;\n    inset: auto !important;\n    grid-column: 1 / -1 !important;\n    grid-row: 2 !important;\n    display: none !important;\n    visibility: hidden !important;\n    opacity: 0 !important;\n    width: 100% !important;\n    max-width: 100% !important;\n    max-height: 0 !important;\n    margin: 0 !important;\n    padding: 0 !important;\n    border: 0 !important;\n    border-radius: 0 !important;\n    background: transparent !important;\n    -webkit-backdrop-filter: none !important;\n    backdrop-filter: none !important;\n    box-shadow: none !important;\n    transform: none !important;\n    overflow: hidden !important;\n    pointer-events: none !important;\n    overscroll-behavior: auto !important;\n  }\n\n  .site-header.is-nav-open .site-nav,\n  .site-header .site-nav.is-open,\n  .site-header .nav-toggle[aria-expanded="true"] + .site-nav {\n    display: grid !important;\n    grid-template-columns: minmax(0, 1fr) !important;\n    gap: 0.55rem !important;\n    visibility: visible !important;\n    opacity: 1 !important;\n    max-height: min(75svh, 34rem) !important;\n    margin-top: 0.85rem !important;\n    padding-top: 0.75rem !important;\n    border-top: 1px solid rgba(255, 255, 255, 0.12) !important;\n    overflow-y: auto !important;\n    pointer-events: auto !important;\n  }\n\n  .site-header.is-nav-open .site-nav a,\n  .site-header .site-nav.is-open a,\n  .site-header .nav-toggle[aria-expanded="true"] + .site-nav a {\n    display: flex !important;\n    align-items: center !important;\n    justify-content: flex-start !important;\n    visibility: visible !important;\n    opacity: 1 !important;\n    width: 100% !important;\n    min-height: 52px !important;\n    margin: 0 !important;\n    padding: 1rem 1rem !important;\n    color: var(--text) !important;\n    background: rgba(255, 255, 255, 0.045) !important;\n    border: 1px solid rgba(255, 255, 255, 0.075) !important;\n    border-radius: 1rem !important;\n  }\n\n  .site-header.is-nav-open .site-nav a.is-active,\n  .site-header.is-nav-open .site-nav a:hover,\n  .site-header.is-nav-open .site-nav a:focus-visible {\n    color: #090909 !important;\n    background: var(--accent) !important;\n    border-color: rgba(216, 197, 162, 0.65) !important;\n  }\n\n  .nav-backdrop,\n  .nav-backdrop.is-visible {\n    display: none !important;\n    visibility: hidden !important;\n    opacity: 0 !important;\n    pointer-events: none !important;\n    background: transparent !important;\n    -webkit-backdrop-filter: none !important;\n    backdrop-filter: none !important;\n  }\n\n  body.nav-open,\n  body.mobile-nav-open {\n    position: static !important;\n    overflow: auto !important;\n    touch-action: auto !important;\n    width: auto !important;\n    left: auto !important;\n    right: auto !important;\n    padding-right: 0 !important;\n  }\n}\n'
    if 'Batch 5 Hotfix 2 — image-fidelity overlay removal + mobile nav repair' not in css:
        css += hotfix2_additions

    hotfix3_additions = '\n\n/* ─────────────────────────────────────────────────────────────\n   Batch 5 Hotfix 3 — mobile story order + Stage Works corrections\n   Fixes:\n   1) On mobile Series pages, keep the image sequence before the Story Index.\n   2) Remove non-functional carousel dots from Stage Works.\n   3) Preserve the Stage Works feature image ratio/focal point on mobile.\n   ───────────────────────────────────────────────────────────── */\n@media (max-width: 760px) {\n  body[data-page="series"] .series-layout {\n    display: flex !important;\n    flex-direction: column !important;\n  }\n\n  body[data-page="series"] .series-main {\n    order: 1 !important;\n  }\n\n  body[data-page="series"] .series-sidebar {\n    order: 2 !important;\n    margin-top: clamp(1.5rem, 8vw, 2.75rem) !important;\n  }\n\n  body[data-page="series"] .series-sidebar .eyebrow::before {\n    content: "After the sequence / ";\n  }\n\n  body[data-page="performance"] .hero--performance .hero__visual,\n  body[data-page="performance"] .hero--performance .hero-figure .hero__visual {\n    aspect-ratio: var(--media-ratio, 4 / 3) !important;\n    max-height: none !important;\n    min-height: 0 !important;\n  }\n\n  body[data-page="performance"] .hero--performance .hero__visual picture,\n  body[data-page="performance"] .hero--performance .hero__visual img,\n  body[data-page="performance"] .hero--performance .hero__visual .media-placeholder {\n    width: 100% !important;\n    height: 100% !important;\n  }\n\n  body[data-page="performance"] .hero--performance .hero__visual img {\n    object-fit: contain !important;\n    object-position: var(--media-position, center center) !important;\n    background: #030303 !important;\n  }\n\n  body[data-page="performance"] .series-card-grid--performance {\n    display: grid !important;\n    grid-template-columns: minmax(0, 1fr) !important;\n    overflow: visible !important;\n    padding-inline: 0 !important;\n    margin-inline: 0 !important;\n    scroll-snap-type: none !important;\n  }\n\n  body[data-page="performance"] .series-card-grid--performance .series-card {\n    width: 100% !important;\n    max-width: 100% !important;\n    flex: none !important;\n    scroll-snap-align: none !important;\n  }\n\n  body[data-page="performance"] .series-card-grid--performance + .scroll-dots,\n  body[data-page="performance"] .scroll-dots {\n    display: none !important;\n    visibility: hidden !important;\n    opacity: 0 !important;\n    pointer-events: none !important;\n  }\n}\n'
    if 'Batch 5 Hotfix 3 — mobile story order + Stage Works corrections' not in css:
        css += hotfix3_additions


    hotfix4_additions = '\n\n/* ─────────────────────────────────────────────────────────────\n   Batch 5 Hotfix 4 — mobile hero consistency + first Stage Work copy\n   Fixes:\n   1) On mobile, page feature images consistently appear before title/copy.\n   2) Stage Works first featured card keeps its description visible on mobile.\n   3) Series mastheads expose the active series description instead of hiding it\n      behind generic page-level copy.\n   ───────────────────────────────────────────────────────────── */\n@media (max-width: 760px) {\n  body[data-page] .hero__layout,\n  body[data-page] .page-hero__layout,\n  body[data-page] .about-hero,\n  body[data-page="series"] .series-masthead {\n    display: flex !important;\n    flex-direction: column !important;\n    align-items: stretch !important;\n    gap: clamp(1rem, 5vw, 1.55rem) !important;\n  }\n\n  body[data-page] .hero-figure,\n  body[data-page] .page-hero__figure,\n  body[data-page] .about-hero__figure,\n  body[data-page="series"] .series-masthead__figure {\n    order: -1 !important;\n    width: 100% !important;\n    max-width: 100% !important;\n    margin: 0 !important;\n  }\n\n  body[data-page] .hero__copy,\n  body[data-page] .page-hero__copy,\n  body[data-page] .about-hero__copy,\n  body[data-page="series"] .series-masthead__copy {\n    order: 1 !important;\n    width: 100% !important;\n    max-width: 100% !important;\n    padding-block-start: 0 !important;\n  }\n\n  body[data-page] .hero__visual,\n  body[data-page] .page-hero__visual,\n  body[data-page] .about-hero__visual,\n  body[data-page="series"] .series-masthead__visual {\n    width: 100% !important;\n    aspect-ratio: 3 / 2 !important;\n    max-height: 65vw !important;\n    min-height: 0 !important;\n  }\n\n  body[data-page] .hero__visual picture,\n  body[data-page] .page-hero__visual picture,\n  body[data-page] .about-hero__visual picture,\n  body[data-page="series"] .series-masthead__visual picture,\n  body[data-page] .hero__visual img,\n  body[data-page] .page-hero__visual img,\n  body[data-page] .about-hero__visual img,\n  body[data-page="series"] .series-masthead__visual img,\n  body[data-page] .hero__visual .media-placeholder,\n  body[data-page] .page-hero__visual .media-placeholder,\n  body[data-page] .about-hero__visual .media-placeholder,\n  body[data-page="series"] .series-masthead__visual .media-placeholder {\n    width: 100% !important;\n    height: 100% !important;\n  }\n\n  body[data-page="performance"] .hero--performance .hero__visual img {\n    object-fit: contain !important;\n    object-position: var(--media-position, center center) !important;\n    background: #030303 !important;\n  }\n\n  body[data-page="performance"] .series-card-grid--performance .series-card,\n  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured {\n    height: auto !important;\n    max-height: none !important;\n    min-height: 0 !important;\n  }\n\n  body[data-page="performance"] .series-card-grid--performance .series-card__body,\n  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured .series-card__body {\n    display: grid !important;\n    height: auto !important;\n    max-height: none !important;\n    min-height: 0 !important;\n    overflow: visible !important;\n  }\n\n  body[data-page="performance"] .series-card-grid--performance .series-card__body > p,\n  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured .series-card__body > p {\n    display: block !important;\n    visibility: visible !important;\n    opacity: 1 !important;\n    max-height: none !important;\n    overflow: visible !important;\n    -webkit-line-clamp: unset !important;\n    -webkit-box-orient: initial !important;\n  }\n}\n'
    if 'Batch 5 Hotfix 4 — mobile hero consistency + first Stage Work copy' not in css:
        css += hotfix4_additions


    hotfix4b_additions = '\n\n/* Hotfix 4 specificity guard: later/mobile hero sizing must beat older page-specific hotfixes. */\n@media (max-width: 760px) {\n  body[data-page="home"] .hero--home .hero__visual,\n  body[data-page="portfolio"] .hero--portfolio .hero__visual,\n  body[data-page="performance"] .hero--performance .hero__visual,\n  body[data-page="about"] .about-hero__visual,\n  body[data-page="contact"] .page-hero__visual,\n  body[data-page="series"] .series-masthead__visual {\n    aspect-ratio: 3 / 2 !important;\n    max-height: 65vw !important;\n    min-height: 0 !important;\n  }\n}\n'
    if 'Hotfix 4 specificity guard' not in css:
        css += hotfix4b_additions


    hotfix5_additions = '''

/* ─────────────────────────────────────────────────────────────
   Batch 5 Hotfix 5 — feature-work media fidelity + Stage Works card parity
   Fixes:
   1) Mobile feature-work/card images render without crop across pages/subpages.
   2) The first Stage Works card keeps its copy visible and no longer lets media
      consume the card body.
   3) Desktop Stage Works feature cards use the same card scale/language as the
      Portfolio grid instead of an oversized special-case card.
   ───────────────────────────────────────────────────────────── */
@media (max-width: 760px) {
  body[data-page] .hero__visual img,
  body[data-page] .page-hero__visual img,
  body[data-page] .about-hero__visual img,
  body[data-page="series"] .series-masthead__visual img,
  body[data-page] .work-card__media img,
  body[data-page] .series-card__media img,
  body[data-page] .editorial-card__media img,
  body[data-page] .series-frame__media img,
  body[data-page] .feature-module__visual img {
    object-fit: contain !important;
    object-position: var(--media-position, 50% 50%) !important;
    background: #030303 !important;
    transform: none !important;
  }

  body[data-page] .work-card__media,
  body[data-page] .series-card__media,
  body[data-page] .editorial-card__media,
  body[data-page] .series-frame__media,
  body[data-page] .feature-module__visual {
    aspect-ratio: 4 / 3 !important;
    min-height: 0 !important;
    max-height: none !important;
    background: #030303 !important;
  }

  body[data-page] .work-card__media picture,
  body[data-page] .series-card__media picture,
  body[data-page] .editorial-card__media picture,
  body[data-page] .series-frame__media picture,
  body[data-page] .feature-module__visual picture,
  body[data-page] .work-card__media img,
  body[data-page] .series-card__media img,
  body[data-page] .editorial-card__media img,
  body[data-page] .series-frame__media img,
  body[data-page] .feature-module__visual img {
    width: 100% !important;
    height: 100% !important;
  }

  body[data-page="performance"] .series-card-grid--performance,
  body[data-page="performance"] .series-card-grid--performance .series-card,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured {
    overflow: visible !important;
  }

  body[data-page="performance"] .series-card-grid--performance .series-card,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured {
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) !important;
    grid-template-rows: auto auto !important;
    height: auto !important;
    max-height: none !important;
    min-height: 0 !important;
  }

  body[data-page="performance"] .series-card-grid--performance .series-card__media,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured .series-card__media {
    height: auto !important;
    min-height: 0 !important;
    max-height: none !important;
    aspect-ratio: 4 / 3 !important;
  }

  body[data-page="performance"] .series-card-grid--performance .series-card__body,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured .series-card__body {
    display: grid !important;
    grid-template-rows: auto auto auto auto !important;
    gap: 0.72rem !important;
    height: auto !important;
    min-height: 0 !important;
    max-height: none !important;
    overflow: visible !important;
  }

  body[data-page="performance"] .series-card-grid--performance .series-card__body > p,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured .series-card__body > p,
  body[data-page="performance"] .series-card-grid--performance article:first-child .series-card__body > p {
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    height: auto !important;
    max-height: none !important;
    overflow: visible !important;
    -webkit-line-clamp: unset !important;
    -webkit-box-orient: initial !important;
  }
}

@media (min-width: 981px) {
  body[data-page="performance"] .series-card-grid--performance {
    grid-template-columns: repeat(12, minmax(0, 1fr)) !important;
    align-items: stretch !important;
  }

  body[data-page="performance"] .series-card-grid--performance .series-card,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured {
    grid-column: span 4 !important;
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) !important;
    grid-template-rows: auto 1fr !important;
    height: 100% !important;
    min-height: 0 !important;
  }

  body[data-page="performance"] .series-card-grid--performance .series-card__media,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured .series-card__media {
    aspect-ratio: 4 / 3 !important;
    height: auto !important;
    max-height: none !important;
  }

  body[data-page="performance"] .series-card-grid--performance .series-card__body,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured .series-card__body {
    display: grid !important;
    grid-template-rows: auto auto 1fr auto !important;
    height: auto !important;
    min-height: 0 !important;
    overflow: visible !important;
  }
}
'''
    if 'Batch 5 Hotfix 5 — feature-work media fidelity + Stage Works card parity' not in css:
        css += hotfix5_additions


    hotfix6_additions = r'''

/* ─────────────────────────────────────────────────────────────
   Batch 5 Hotfix 6 — mobile card image fit + focal-point framing
   The previous mobile fidelity fix used contain globally. That preserved
   full frames, but it created black side gutters and made cards feel uneven.
   Mobile cards now fill their frame again while respecting the focal point
   stored as --media-position on each media wrapper.
   ───────────────────────────────────────────────────────────── */
@media (max-width: 760px) {
  body[data-page] .hero__visual,
  body[data-page] .page-hero__visual,
  body[data-page] .about-hero__visual,
  body[data-page="series"] .series-masthead__visual,
  body[data-page] .work-card__media,
  body[data-page] .series-card__media,
  body[data-page] .editorial-card__media,
  body[data-page] .series-frame__media,
  body[data-page] .feature-module__visual {
    aspect-ratio: var(--media-ratio, 4 / 3) !important;
    min-height: 0 !important;
    max-height: none !important;
    overflow: hidden !important;
    background: #030303 !important;
  }

  body[data-page] .hero__visual picture,
  body[data-page] .page-hero__visual picture,
  body[data-page] .about-hero__visual picture,
  body[data-page="series"] .series-masthead__visual picture,
  body[data-page] .work-card__media picture,
  body[data-page] .series-card__media picture,
  body[data-page] .editorial-card__media picture,
  body[data-page] .series-frame__media picture,
  body[data-page] .feature-module__visual picture,
  body[data-page] .hero__visual img,
  body[data-page] .page-hero__visual img,
  body[data-page] .about-hero__visual img,
  body[data-page="series"] .series-masthead__visual img,
  body[data-page] .work-card__media img,
  body[data-page] .series-card__media img,
  body[data-page] .editorial-card__media img,
  body[data-page] .series-frame__media img,
  body[data-page] .feature-module__visual img {
    width: 100% !important;
    height: 100% !important;
  }

  body[data-page] .hero__visual img,
  body[data-page] .page-hero__visual img,
  body[data-page] .about-hero__visual img,
  body[data-page="series"] .series-masthead__visual img,
  body[data-page] .work-card__media img,
  body[data-page] .series-card__media img,
  body[data-page] .editorial-card__media img,
  body[data-page] .series-frame__media img,
  body[data-page] .feature-module__visual img {
    object-fit: cover !important;
    object-position: var(--media-position, 50% 50%) !important;
    transform: none !important;
  }

  /* Stage Works must not inherit the horizontal mobile carousel behavior. */
  body[data-page="performance"] .series-card-grid--performance {
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) !important;
    gap: clamp(1rem, 4vw, 1.25rem) !important;
    overflow: visible !important;
    scroll-snap-type: none !important;
    padding: 0 !important;
    margin-inline: 0 !important;
  }

  body[data-page="performance"] .series-card-grid--performance .series-card,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured {
    width: 100% !important;
    max-width: none !important;
    flex: none !important;
    scroll-snap-align: none !important;
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) !important;
    grid-template-rows: auto auto !important;
    height: auto !important;
    min-height: 0 !important;
    max-height: none !important;
    overflow: hidden !important;
  }

  body[data-page="performance"] .series-card-grid--performance .series-card__media,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured .series-card__media {
    display: block !important;
    aspect-ratio: var(--media-ratio, 4 / 3) !important;
    height: auto !important;
    min-height: 0 !important;
    max-height: min(76vw, 24rem) !important;
    overflow: hidden !important;
  }

  body[data-page="performance"] .series-card-grid--performance .series-card__media img,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured .series-card__media img {
    object-fit: cover !important;
    object-position: var(--media-position, 50% 50%) !important;
  }

  body[data-page="performance"] .series-card-grid--performance .series-card__body,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured .series-card__body {
    display: grid !important;
    grid-template-rows: auto auto auto auto !important;
    gap: 0.72rem !important;
    height: auto !important;
    min-height: 0 !important;
    max-height: none !important;
    overflow: visible !important;
  }

  body[data-page="performance"] .series-card-grid--performance .series-card__body > p,
  body[data-page="performance"] .series-card-grid--performance .series-card--story-featured .series-card__body > p,
  body[data-page="performance"] .series-card-grid--performance article:first-child .series-card__body > p {
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    height: auto !important;
    max-height: none !important;
    overflow: visible !important;
    -webkit-line-clamp: unset !important;
    -webkit-box-orient: initial !important;
  }
}
'''
    if 'Batch 5 Hotfix 6 — mobile card image fit + focal-point framing' not in css:
        css += hotfix6_additions

    footer_mark_additions = r'''

/* ─────────────────────────────────────────────────────────────
   Footer mark hotfix 9 — typographic colophon signature
   Scope: footer wordmark only. No footer copy, layout, links, or JS changed.
   ───────────────────────────────────────────────────────────── */
.footer-copy strong {
  display: inline-block;
  width: fit-content;
  max-width: 100%;
  line-height: 1;
}

.footer-wordmark--colophon {
  --footer-mark-cream: rgba(242, 239, 232, 0.96);
  --footer-mark-soft: rgba(242, 239, 232, 0.62);
  --footer-mark-gold: rgba(216, 197, 162, 0.86);
  position: relative;
  display: inline-grid;
  grid-template-columns: minmax(0, auto);
  gap: 0.06rem;
  width: fit-content;
  max-width: 100%;
  padding: 0;
  color: var(--footer-mark-cream);
  isolation: isolate;
}

.footer-wordmark--colophon::before {
  content: "";
  position: absolute;
  inset: -0.29rem -0.40rem -0.31rem -0.34rem;
  z-index: -1;
  border-radius: 0.66rem;
  background:
    radial-gradient(circle at 0% 18%, rgba(216, 197, 162, 0.07), transparent 1.35rem),
    linear-gradient(90deg, rgba(255, 255, 255, 0.025), transparent 68%);
  opacity: 0.82;
  pointer-events: none;
}

.footer-wordmark__overline {
  display: inline-flex;
  align-items: center;
  gap: 0.38rem;
  font-family: var(--font-sans);
  font-size: clamp(0.41rem, 0.47vw, 0.47rem);
  font-weight: 760;
  letter-spacing: 0.28em;
  line-height: 1;
  color: var(--footer-mark-gold);
  text-transform: uppercase;
  white-space: nowrap;
}

.footer-wordmark__overline::after {
  content: "";
  display: inline-block;
  width: clamp(1.55rem, 3.8vw, 3.0rem);
  height: 1px;
  background: linear-gradient(90deg, rgba(216, 197, 162, 0.66), rgba(216, 197, 162, 0));
  transform: translateY(0.02rem);
}

.footer-wordmark__name {
  display: inline-flex;
  align-items: baseline;
  gap: 0.02em;
  font-family: var(--font-display);
  font-size: clamp(0.95rem, 1.96vw, 2.11rem);
  font-weight: 600;
  line-height: 0.72;
  letter-spacing: -0.085em;
  color: var(--footer-mark-cream);
  text-rendering: optimizeLegibility;
  font-feature-settings: "kern" 1, "liga" 1;
  white-space: nowrap;
}

.footer-wordmark__still {
  color: rgba(242, 239, 232, 0.94);
}

.footer-wordmark__mark {
  color: rgba(216, 197, 162, 0.92);
  margin-left: -0.03em;
}

.footer-wordmark__trace {
  position: relative;
  display: block;
  width: min(100%, 8.8rem);
  height: 0.18rem;
  overflow: hidden;
}

.footer-wordmark__trace::before,
.footer-wordmark__trace::after,
.footer-wordmark__trace span {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  height: 1px;
  border-radius: 999px;
  pointer-events: none;
}

.footer-wordmark__trace::before {
  top: 0.035rem;
  background: linear-gradient(90deg, rgba(242, 239, 232, 0.5), rgba(216, 197, 162, 0.34) 42%, rgba(242, 239, 232, 0));
}

.footer-wordmark__trace span {
  top: 0.115rem;
  width: 58%;
  background: linear-gradient(90deg, rgba(216, 197, 162, 0.42), rgba(242, 239, 232, 0));
  opacity: 0.72;
}

.footer-wordmark__trace::after {
  top: 0.035rem;
  left: clamp(2.6rem, 24%, 4.3rem);
  right: auto;
  width: 0.16rem;
  height: 0.16rem;
  border: 1px solid rgba(216, 197, 162, 0.72);
  background: rgba(8, 8, 7, 0.9);
  border-radius: 50%;
  transform: translateY(-50%);
  box-shadow: 0 0 0 0.10rem rgba(216, 197, 162, 0.05);
}

.footer-copy p {
  margin-top: 0.30rem;
}

@media (hover: hover) and (pointer: fine) {
  .footer-wordmark--colophon {
    transition: transform var(--transition), filter var(--transition);
  }

  .footer-wordmark--colophon:hover {
    transform: translateY(-0.5px);
    filter: drop-shadow(0 8px 16px rgba(0, 0, 0, 0.22));
  }

  .footer-wordmark--colophon:hover .footer-wordmark__trace span {
    width: 72%;
  }

  .footer-wordmark__trace span {
    transition: width 520ms var(--ease-premium), opacity var(--transition);
  }
}

@media (max-width: 620px) {
  .footer-wordmark--colophon::before {
    inset: -0.25rem -0.31rem -0.27rem -0.27rem;
    border-radius: 0.64rem;
  }

  .footer-wordmark__overline {
    letter-spacing: 0.22em;
  }

  .footer-wordmark__overline::after {
    width: clamp(1.2rem, 9vw, 2.15rem);
  }

  .footer-wordmark__name {
    font-size: clamp(1.06rem, 5.4vw, 1.55rem);
    letter-spacing: -0.07em;
  }

  .footer-wordmark__trace {
    width: min(100%, 7.55rem);
  }
}

@media (max-width: 380px) {
  .footer-wordmark__overline {
    letter-spacing: 0.19em;
  }

  .footer-wordmark__name {
    font-size: clamp(0.95rem, 5.4vw, 1.31rem);
  }
}
'''

    if 'Footer mark hotfix 9 — typographic colophon signature' not in css:
        css += footer_mark_additions

    path.write_text(css, encoding='utf-8')


def write_all() -> None:
    store = normalize_content(SITE_CONTENT)
    cleanup_report = prune_generated_responsive_assets(store['generated_assets'])
    write_image_manifests(store, cleanup_report)

    (ROOT / 'assets/js/data.js').write_text(render_data_js(store), encoding='utf-8')
    (ROOT / 'index.html').write_text(render_home(store), encoding='utf-8')
    (ROOT / 'portfolio.html').write_text(render_portfolio(store), encoding='utf-8')
    (ROOT / 'series.html').write_text(render_series(store), encoding='utf-8')
    (ROOT / 'performance.html').write_text(render_performance(store), encoding='utf-8')
    (ROOT / 'about.html').write_text(render_about(store), encoding='utf-8')
    (ROOT / 'contact.html').write_text(render_contact(store), encoding='utf-8')
    (ROOT / '404.html').write_text(render_404(store), encoding='utf-8')
    (ROOT / 'robots.txt').write_text(render_robots_txt(), encoding='utf-8')
    (ROOT / 'sitemap.xml').write_text(render_sitemap_xml(), encoding='utf-8')
    (ROOT / 'site.webmanifest').write_text(render_site_manifest(), encoding='utf-8')
    (ROOT / 'README.md').write_text(render_readme(), encoding='utf-8')

    update_app_js(ROOT / 'assets/js/app.js')
    update_home_js(ROOT / 'assets/js/home.js')
    update_start_scripts()
    update_styles(ROOT / 'assets/css/styles.css')

    report = write_build_metadata(store)
    write_public_upload_bundle(store, report)
    write_public_upload_instructions(store, report)

    missing_assets = list(store.get('missing_assets') or [])
    if missing_assets:
        print(f"[STILLMRK build] Warning: {len(missing_assets)} work(s) are metadata-only because no source image is assigned yet.", flush=True)
    print('[STILLMRK build] Site rebuilt successfully.')


def main() -> None:
    parser = argparse.ArgumentParser(description='Build STILLMRK from YAML content files.')
    parser.add_argument('--validate-only', action='store_true', help='Validate content without writing site output.')
    args = parser.parse_args()

    if args.validate_only:
        normalize_content(SITE_CONTENT)
        print('[STILLMRK build] Content validation passed.')
        return

    write_all()


if __name__ == '__main__':
    main()


# Hotfix 7 CSS addition preserved in styles.css/assets/css/styles.css.
