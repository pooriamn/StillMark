from __future__ import annotations

import json
from dataclasses import asdict
import re
from jsonschema import Draft202012Validator
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from content_models import PageModel, ValidationIssue, ValidationReport
    from helpers_content import CONTENT_DIR, ROOT, available_download_ids, available_page_keys, available_series_slugs, available_work_ids, load_artist_profile, load_home_relationships, load_navigation_payload, load_page_model, load_page_payload, load_resources_payload, load_series_entries, load_site_settings, load_work_entries, work_to_series_map
    from helpers_image import load_pipeline, source_path_for_work
except ImportError:  # pragma: no cover
    from scripts.content_models import PageModel, ValidationIssue, ValidationReport  # type: ignore
    from scripts.helpers_content import CONTENT_DIR, ROOT, available_download_ids, available_page_keys, available_series_slugs, available_work_ids, load_artist_profile, load_home_relationships, load_navigation_payload, load_page_model, load_page_payload, load_resources_payload, load_series_entries, load_site_settings, load_work_entries, work_to_series_map  # type: ignore
    from scripts.helpers_image import load_pipeline, source_path_for_work  # type: ignore

REPORT_PATH = ROOT / '.stillmrk-build' / 'meta' / 'validation-report.json'
SCHEMA_PATH = CONTENT_DIR / 'schema' / 'content.schema.json'


def _load_content_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))


def _format_error_path(parts: list[Any]) -> str:
    if not parts:
        return '<root>'
    formatted: list[str] = []
    for part in parts:
        if isinstance(part, int):
            formatted.append(f'[{part}]')
        else:
            formatted.append(str(part) if not formatted else f'.{part}')
    return ''.join(formatted)


def _content_bundle_with_page_override(page_key: str | None = None, page_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    navigation_payload = load_navigation_payload()
    navigation_items = navigation_payload.get('items') if isinstance(navigation_payload.get('items'), list) else navigation_payload if isinstance(navigation_payload, list) else []
    pages: dict[str, Any] = {}
    for key in available_page_keys():
        if page_key and page_payload is not None and key == page_key:
            pages[key] = page_payload
        else:
            pages[key] = load_page_payload(key)
    image_pipeline_path = CONTENT_DIR / 'image-pipeline.yaml'
    release_path = CONTENT_DIR / 'release.yaml'
    image_pipeline = yaml.safe_load(image_pipeline_path.read_text(encoding='utf-8')) if image_pipeline_path.exists() else {}
    release = yaml.safe_load(release_path.read_text(encoding='utf-8')) if release_path.exists() else {}
    return {
        'site': load_site_settings(),
        'artist': load_artist_profile(),
        'navigation': navigation_items,
        'image_pipeline': image_pipeline if isinstance(image_pipeline, dict) else {},
        'resources': load_resources_payload(),
        'release': release if isinstance(release, dict) else {},
        'pages': pages,
        'series': load_series_entries(),
        'works': load_work_entries(),
    }


class ContentValidator:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def validate_schema_bundle(self, content: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        try:
            validator = Draft202012Validator(_load_content_schema())
        except Exception as exc:
            issues.append(ValidationIssue('schema_load_failed', 'error', 'publish', 'schema', 'schema', f'Could not load content schema: {exc}', 'Repair the schema file before validating content.'))
            return issues
        for error in sorted(validator.iter_errors(content), key=lambda item: list(item.absolute_path)):
            path_text = _format_error_path(list(error.absolute_path))
            issues.append(ValidationIssue('schema_invalid', 'error', 'publish', 'schema', path_text, f'Schema validation failed at {path_text}: {error.message}', 'Fix the invalid field in content or resave it through the control panel.'))
        return issues

    def validate_page_payload_schema(self, page_key: str, payload: dict[str, Any]) -> list[ValidationIssue]:
        bundle = _content_bundle_with_page_override(page_key, payload)
        issues = self.validate_schema_bundle(bundle)
        filtered: list[ValidationIssue] = []
        page_prefix = f'pages.{page_key}'
        for issue in issues:
            if issue.field_path == '<root>' or issue.field_path.startswith(page_prefix):
                filtered.append(issue)
        return filtered

    def validate_site_payload(self, payload: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not str(payload.get('name') or '').strip():
            issues.append(ValidationIssue('site_name_missing', 'error', 'site', 'site', 'name', 'Site name is empty.', 'Set a site name in Content Authority.'))
        url = str(payload.get('site_url') or '').strip()
        if url and not re.match(r'^https?://', url):
            issues.append(ValidationIssue('site_url_invalid', 'error', 'site', 'site', 'site_url', 'Canonical base URL must start with http:// or https://.', 'Use an absolute URL.'))
        analytics_id = str(payload.get('analytics_id') or '').strip()
        if analytics_id and not re.match(r'^(G|UA)-[A-Z0-9-]+$', analytics_id, re.I):
            issues.append(ValidationIssue('analytics_invalid', 'warning', 'site', 'site', 'analytics_id', 'Analytics ID does not look like a normal GA identifier.', 'Check the GA4 measurement ID.'))
        return issues

    def validate_artist_payload(self, payload: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not str(payload.get('name') or '').strip():
            issues.append(ValidationIssue('artist_name_missing', 'error', 'artist', 'artist', 'name', 'Artist name is empty.', 'Set the artist name.'))
        email = str(payload.get('email') or '').strip()
        if email and '@' not in email:
            issues.append(ValidationIssue('artist_email_invalid', 'error', 'artist', 'artist', 'email', 'Artist email does not look valid.', 'Use a valid email address.'))
        if not str(payload.get('location') or '').strip():
            issues.append(ValidationIssue('artist_location_missing', 'warning', 'artist', 'artist', 'location', 'Artist location is empty.', 'Set the public location in Artist.'))
        return issues

    def validate_navigation_payload(self, payload: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        items = payload.get('items') if isinstance(payload.get('items'), list) else []
        seen: set[str] = set()
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            label = str(item.get('label') or '').strip()
            href = str(item.get('href') or '').strip()
            page = str(item.get('page') or '').strip()
            ident = str(item.get('id') or label.lower().replace(' ', '-')).strip()
            if ident in seen:
                issues.append(ValidationIssue('nav_id_duplicate', 'error', 'navigation', ident, f'items[{idx}]', f"Navigation item id '{ident}' is duplicated.", 'Give each navigation item a unique id.'))
            seen.add(ident)
            if not label or not href or not page:
                issues.append(ValidationIssue('nav_incomplete', 'error', 'navigation', ident or f'row-{idx}', f'items[{idx}]', 'Navigation item is missing label, href, or page.', 'Complete all fields or remove the item.'))
        return issues

    def validate_resources_payload(self, payload: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        docs = payload.get('downloads') if isinstance(payload.get('downloads'), list) else []
        seen: set[str] = set()
        allowed_kinds = {'press', 'cv', 'exhibitions', 'tearsheet', 'licensing', 'client'}
        allowed_audiences = {'public', 'client', 'press'}
        for idx, item in enumerate(docs):
            if not isinstance(item, dict):
                continue
            ident = str(item.get('id') or '').strip()
            title = str(item.get('title') or '').strip()
            file_ref = str(item.get('file') or '').strip()
            kind = str(item.get('kind') or '').strip().lower()
            audience = str(item.get('audience') or 'public').strip().lower()
            if not ident or not title:
                issues.append(ValidationIssue('resource_incomplete', 'error', 'resource', ident or f'row-{idx}', f'downloads[{idx}]', 'Document is missing id or title.', 'Fill the required fields.'))
            if ident in seen:
                issues.append(ValidationIssue('resource_duplicate', 'error', 'resource', ident, f'downloads[{idx}]', f"Document id '{ident}' is duplicated.", 'Use a unique document id.'))
            seen.add(ident)
            if not kind:
                issues.append(ValidationIssue('resource_kind_required', 'error', 'resource', ident or title or f'row-{idx}', 'kind', 'Document kind is empty.', 'Choose a valid document kind.'))
            elif kind not in allowed_kinds:
                issues.append(ValidationIssue('resource_kind_invalid', 'error', 'resource', ident or title or f'row-{idx}', 'kind', f"Document kind '{kind}' is not allowed.", f"Use one of: {', '.join(sorted(allowed_kinds))}."))
            if not file_ref:
                issues.append(ValidationIssue('resource_file_required', 'error', 'resource', ident or title or f'row-{idx}', 'file', 'Document file path is empty.', 'Set the document file path.'))
            else:
                candidate = (ROOT / file_ref.lstrip('/')).resolve()
                if not candidate.exists():
                    issues.append(ValidationIssue('resource_file_missing', 'error', 'resource', ident or title, 'file', f"Document file '{file_ref}' is missing.", 'Fix the file path or add the file.'))
            if audience not in allowed_audiences:
                issues.append(ValidationIssue('resource_audience_invalid', 'error', 'resource', ident or title or f'row-{idx}', 'audience', f"Audience '{audience}' is not allowed.", f"Use one of: {', '.join(sorted(allowed_audiences))}."))
        return issues

    def validate_page_model(self, page_key: str, model: PageModel) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not model.meta.title.strip():
            issues.append(ValidationIssue('page_meta_title_missing', 'error', 'page', page_key, 'meta.title', 'Meta title is empty.', 'Fill the page meta title.'))
        if not model.meta.description.strip():
            issues.append(ValidationIssue('page_meta_description_missing', 'error', 'page', page_key, 'meta.description', 'Meta description is empty.', 'Fill the page meta description.'))
        if not model.hero.title.strip():
            issues.append(ValidationIssue('page_hero_title_missing', 'error', 'page', page_key, 'hero.title', 'Hero title is empty.', 'Fill the hero title.'))
        try:
            from page_blocks import page_model_to_payload
        except ImportError:  # pragma: no cover
            from scripts.page_blocks import page_model_to_payload  # type: ignore
        payload = page_model_to_payload(model, load_page_payload(page_key))
        issues.extend(self.validate_page_payload_schema(page_key, payload))
        seen_ids: set[str] = set()
        allowed_series = set(available_series_slugs())
        allowed_works = set(available_work_ids())
        resources = load_resources_payload().get('downloads') if isinstance(load_resources_payload().get('downloads'), list) else []
        resource_ids = {str(item.get('id') or '').strip() for item in resources if isinstance(item, dict)}
        for idx, section in enumerate(model.sections):
            if section.id in seen_ids:
                issues.append(ValidationIssue('section_duplicate_id', 'error', 'page', page_key, f'sections[{idx}].id', f"Section id '{section.id}' is duplicated.", 'Use unique section ids.'))
            seen_ids.add(section.id)
            if section.type == 'featured_series':
                for slug in section.data.get('series_slugs') or []:
                    if slug not in allowed_series:
                        issues.append(ValidationIssue('series_ref_missing', 'error', 'page', page_key, f'sections[{idx}].series_slugs', f"Featured series '{slug}' does not exist.", 'Pick an existing series.'))
            if section.type == 'featured_works':
                for work_id in section.data.get('work_ids') or []:
                    if work_id not in allowed_works:
                        issues.append(ValidationIssue('work_ref_missing', 'error', 'page', page_key, f'sections[{idx}].work_ids', f"Featured work '{work_id}' does not exist.", 'Pick an existing work.'))
            if section.type == 'work_spotlight':
                work_id = str(section.data.get('work_id') or '').strip()
                if work_id and work_id not in allowed_works:
                    issues.append(ValidationIssue('work_ref_missing', 'error', 'page', page_key, f'sections[{idx}].work_id', f"Spotlight work '{work_id}' does not exist.", 'Pick an existing work.'))
            if section.type == 'document_list':
                for doc_id in section.data.get('document_ids') or []:
                    if doc_id not in resource_ids:
                        issues.append(ValidationIssue('document_ref_missing', 'error', 'page', page_key, f'sections[{idx}].document_ids', f"Document '{doc_id}' does not exist.", 'Pick an existing document.'))
        return issues

    def validate_page_references(self, page_key: str, model: PageModel) -> list[ValidationIssue]:
        return self.validate_page_model(page_key, model)

    def validate_series_relationships(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        series_entries = load_series_entries()
        allowed_series = {str(item.get('slug') or '').strip() for item in series_entries if str(item.get('slug') or '').strip()}
        allowed_downloads = set(available_download_ids())
        membership: dict[str, list[str]] = {}
        owners: dict[str, list[str]] = {}
        for series in series_entries:
            slug = str(series.get('slug') or '').strip()
            if not slug:
                continue
            work_ids = [str(item).strip() for item in (series.get('work_ids') or []) if str(item).strip()]
            membership[slug] = work_ids
            if len(work_ids) != len(set(work_ids)):
                issues.append(ValidationIssue('series_work_duplicate', 'error', 'series', slug, 'work_ids', 'Series work_ids contains duplicates.', 'Remove duplicate work ids.'))
            cover_id = str(series.get('cover_work_id') or '').strip()
            if cover_id and cover_id not in work_ids:
                issues.append(ValidationIssue('series_cover_outside_sequence', 'error', 'series', slug, 'cover_work_id', f"Cover work '{cover_id}' is not present in work_ids.", 'Choose a cover that is inside the series sequence.'))
            related = [str(item).strip() for item in (series.get('related_series_slugs') or []) if str(item).strip()]
            if slug in related:
                issues.append(ValidationIssue('series_related_self', 'error', 'series', slug, 'related_series_slugs', 'A series cannot relate to itself.', 'Remove the current series from related series.'))
            for related_slug in related:
                if related_slug not in allowed_series:
                    issues.append(ValidationIssue('series_related_missing', 'error', 'series', slug, 'related_series_slugs', f"Related series '{related_slug}' does not exist.", 'Pick an existing public or private series.'))
            for download_id in [str(item).strip() for item in (series.get('download_ids') or []) if str(item).strip()]:
                if download_id not in allowed_downloads:
                    issues.append(ValidationIssue('series_download_missing', 'error', 'series', slug, 'download_ids', f"Download id '{download_id}' does not exist.", 'Pick an existing document id.'))
            for work_id in work_ids:
                owners.setdefault(work_id, []).append(slug)
        works_by_file = {str(item.get('id') or '').strip(): item for item in load_work_entries() if str(item.get('id') or '').strip()}
        for work_id, payload in works_by_file.items():
            file_series = str(payload.get('series') or '').strip()
            owner_series = owners.get(work_id, [])
            if not owner_series:
                issues.append(ValidationIssue('work_unassigned', 'error', 'work', work_id, 'series', 'Work is not assigned inside any series work_ids list.', 'Assign the work to exactly one series.'))
                continue
            if len(owner_series) > 1:
                issues.append(ValidationIssue('work_multi_series', 'error', 'work', work_id, 'series', f"Work appears in multiple series: {', '.join(owner_series)}.", 'A work should belong to exactly one series.'))
            canonical_series = owner_series[0]
            if file_series and file_series != canonical_series:
                issues.append(ValidationIssue('work_series_mismatch', 'error', 'work', work_id, 'series', f"Work file series '{file_series}' does not match series membership '{canonical_series}'.", 'Resave the relationship so the work file and series list agree.'))
        return issues

    def validate_home_relationships(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        home = load_home_relationships()
        valid_series = {str(item.get('slug') or '').strip(): str(item.get('visibility') or 'public').strip().lower() for item in load_series_entries() if str(item.get('slug') or '').strip()}
        valid_works = set(available_work_ids())
        for slug in home.get('featured_series', []):
            if slug not in valid_series:
                issues.append(ValidationIssue('home_featured_series_missing', 'error', 'page', 'home', 'featured_series', f"Homepage featured series '{slug}' does not exist.", 'Pick an existing series.'))
            elif valid_series.get(slug) == 'private':
                issues.append(ValidationIssue('home_featured_series_private', 'warning', 'page', 'home', 'featured_series', f"Homepage featured series '{slug}' is private.", 'Remove private series from public homepage features.'))
        for work_id in home.get('featured_works', []):
            if work_id not in valid_works:
                issues.append(ValidationIssue('home_featured_work_missing', 'error', 'page', 'home', 'featured_works', f"Homepage featured work '{work_id}' does not exist.", 'Pick an existing work.'))
        return issues

    def validate_asset_references(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        pipeline = load_pipeline()
        series_lookup = work_to_series_map()
        for work in load_work_entries():
            work_id = str(work.get('id') or '').strip()
            series_slug = str(work.get('series') or series_lookup.get(work_id) or '').strip()
            image_value = work.get('image') if isinstance(work.get('image'), dict) else {}
            if image_value:
                render_name = str(image_value.get('render_name') or work_id).strip()
                if not render_name:
                    issues.append(ValidationIssue('work_render_name_missing', 'warning', 'asset', work_id, 'image.render_name', 'Responsive render name is empty.', 'Set a render_name or remove the override.'))
            if work_id and series_slug:
                source_path = source_path_for_work(series_slug, work_id, pipeline=pipeline)
                if not source_path or not source_path.exists():
                    issues.append(ValidationIssue('work_source_missing', 'error', 'asset', work_id, 'source', f"Original image for work '{work_id}' is missing.", 'Restore the original image file before publishing.'))
        return issues

    def validate_document_files(self, resources_payload: dict[str, Any]) -> list[ValidationIssue]:
        return self.validate_resources_payload(resources_payload)

    def validate_publish_state(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        build_status_path = ROOT / '.stillmrk-build' / 'meta' / 'build-status.json'
        if not build_status_path.exists():
            issues.append(ValidationIssue('build_status_missing', 'warning', 'publish', 'build', 'build-status', 'No build status file exists yet.', 'Run a full build.'))
        return issues

    def validate_all(self) -> ValidationReport:
        issues: list[ValidationIssue] = []
        issues.extend(self.validate_schema_bundle(_content_bundle_with_page_override()))
        issues.extend(self.validate_site_payload(load_site_settings()))
        issues.extend(self.validate_artist_payload(load_artist_profile()))
        issues.extend(self.validate_navigation_payload(load_navigation_payload()))
        resources_payload = load_resources_payload()
        issues.extend(self.validate_resources_payload(resources_payload))
        for page_key in available_page_keys():
            issues.extend(self.validate_page_model(page_key, load_page_model(page_key)))
        issues.extend(self.validate_series_relationships())
        issues.extend(self.validate_home_relationships())
        issues.extend(self.validate_asset_references())
        issues.extend(self.validate_publish_state())
        return ValidationReport(issues=issues, generated_at=datetime.now(timezone.utc).isoformat())


def write_validation_report(report: ValidationReport, report_path: Path | None = None) -> Path:
    path = report_path or REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'generated_at': report.generated_at,
        'issues': [asdict(item) for item in report.issues],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def load_validation_report(report_path: Path | None = None) -> ValidationReport:
    path = report_path or REPORT_PATH
    if not path.exists():
        return ValidationReport()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return ValidationReport()
    issues = [ValidationIssue(**item) for item in data.get('issues') or [] if isinstance(item, dict)]
    return ValidationReport(issues=issues, generated_at=str(data.get('generated_at') or ''))


def summarize_validation_report(report: ValidationReport) -> dict[str, int]:
    return {
        'errors': report.error_count(),
        'warnings': report.warning_count(),
        'total': len(report.issues),
    }
