from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import argparse
import json
import sys

try:
    import yaml
except Exception as exc:
    print(f'PyYAML is required: {exc}', file=sys.stderr)
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / 'content'
SERIES_DIR = CONTENT / 'series'
WORKS_DIR = CONTENT / 'works'
PAGES_DIR = CONTENT / 'pages'
ASSETS_DIR = ROOT / 'assets'
DEFAULT_MD = ROOT / 'PUBLISHING_READINESS_REPORT.md'
DEFAULT_JSON = ROOT / '.stillmrk-build' / 'meta' / 'publishing-readiness-report.json'


def load_yaml(path: Path) -> dict:
    with path.open('r', encoding='utf-8') as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def iter_yaml(directory: Path):
    if not directory.exists():
        return
    for path in sorted(directory.glob('*.yaml')):
        yield path, load_yaml(path)


def as_bool(value, default=True) -> bool:
    if value is None:
        return default
    return value is not False


def is_public_series(series: dict) -> bool:
    return as_bool(series.get('published'), True) and str(series.get('visibility') or 'public').strip().lower() == 'public'


def is_public_work(work: dict) -> bool:
    return as_bool(work.get('published'), True)


def source_path_for_work(work: dict) -> Path:
    series = str(work.get('series') or '').strip()
    work_id = str(work.get('id') or '').strip()
    image = work.get('image') if isinstance(work.get('image'), dict) else {}
    master = str(image.get('master') or '').strip() or f'{work_id}.jpg'
    return ASSETS_DIR / 'images' / 'originals' / 'series' / series / master


def generated_dir_for_work(work: dict) -> Path:
    series = str(work.get('series') or '').strip()
    work_id = str(work.get('id') or '').strip()
    image = work.get('image') if isinstance(work.get('image'), dict) else {}
    render_name = str(image.get('render_name') or work.get('render_name') or work_id).strip()
    return ASSETS_DIR / 'images' / 'generated' / 'series' / series / render_name


def build_report() -> tuple[str, dict]:
    works_by_id = {str(item.get('id') or '').strip(): item for _, item in iter_yaml(WORKS_DIR) if str(item.get('id') or '').strip()}
    series_by_slug = {str(item.get('slug') or path.stem).strip(): item for path, item in iter_yaml(SERIES_DIR)}
    pages = {path.stem: item for path, item in iter_yaml(PAGES_DIR)}

    blockers: list[dict] = []
    warnings: list[dict] = []

    def add(bucket: list[dict], code: str, where: str, message: str):
        bucket.append({'code': code, 'where': where, 'message': message})

    public_series = {slug: series for slug, series in series_by_slug.items() if is_public_series(series)}
    public_works = {wid: work for wid, work in works_by_id.items() if is_public_work(work)}

    for slug, series in sorted(public_series.items(), key=lambda kv: (kv[1].get('order', 9999), kv[0])):
        work_ids = [str(item).strip() for item in (series.get('work_ids') or []) if str(item).strip()]
        if not work_ids:
            add(blockers, 'empty-series', slug, 'Public series has no work_ids.')
            continue
        for work_id, count in sorted(Counter(work_ids).items()):
            if count > 1:
                add(blockers, 'duplicate-work-id', slug, f'Work `{work_id}` appears {count} times in the sequence.')
        public_sequence = []
        for position, work_id in enumerate(work_ids, start=1):
            work = works_by_id.get(work_id)
            if not work:
                add(blockers, 'missing-work-yaml', slug, f'Position {position}: `{work_id}` has no content/works YAML file.')
                continue
            if not is_public_work(work):
                status = str(work.get('review_status') or 'draft')
                add(warnings, 'non-public-work-in-public-series', slug, f'Position {position}: `{work_id}` exists but is not public (`published: false`, review_status: `{status}`).')
                continue
            public_sequence.append(work_id)
            declared_series = str(work.get('series') or '').strip()
            if declared_series and declared_series != slug:
                add(warnings, 'series-mismatch', slug, f'Public work `{work_id}` declares series `{declared_series}`, but is sequenced in `{slug}`.')
        if len(public_sequence) < 3:
            add(warnings, 'thin-public-sequence', slug, f'Only {len(public_sequence)} public works are available after filtering drafts/private works.')
        for field in ['cover_work_id', 'card_cover_work_id', 'hero_work_id']:
            value = str(series.get(field) or '').strip()
            if not value:
                if field == 'cover_work_id':
                    add(blockers, 'missing-cover', slug, 'Public series has no cover_work_id.')
                continue
            if value not in works_by_id:
                add(blockers, 'missing-curation-work', slug, f'{field}: `{value}` does not exist in content/works.')
            elif value not in public_works:
                add(warnings, 'non-public-curation-work', slug, f'{field}: `{value}` exists but is not public.')
            elif value not in work_ids:
                add(warnings, 'curation-work-outside-sequence', slug, f'{field}: `{value}` is public but not present in this story sequence.')
        for field in ['card_summary', 'story_opening_text', 'story_sequence_text', 'story_closing_text']:
            if not str(series.get(field) or '').strip():
                add(warnings, 'missing-story-field', slug, f'Missing optional storytelling field `{field}`. Fallback text will be used.')

    for wid, work in sorted(public_works.items()):
        for field in ['title', 'alt', 'caption', 'year', 'location']:
            if not str(work.get(field) or '').strip():
                add(warnings, 'missing-work-field', wid, f'Public work is missing `{field}`.')
        if len(str(work.get('alt') or '').strip()) < 35:
            add(warnings, 'weak-alt-text', wid, 'Alt text is very short; check whether it describes the visual content clearly.')
        if len(str(work.get('caption') or '').strip()) < 40:
            add(warnings, 'weak-caption', wid, 'Caption is very short; check whether it supports storytelling.')
        source = source_path_for_work(work)
        if not source.exists():
            add(warnings, 'missing-original-source', wid, f'Original source image not found at `{source.relative_to(ROOT)}`. This may be expected in the lightweight ZIP.')
        generated_dir = generated_dir_for_work(work)
        if not generated_dir.exists():
            add(warnings, 'missing-generated-dir', wid, f'Generated derivative directory not found at `{generated_dir.relative_to(ROOT)}`. Run the derivative/build pipeline with real images.')

    site = load_yaml(CONTENT / 'site.yaml') if (CONTENT / 'site.yaml').exists() else {}
    site_meta = site.get('meta') if isinstance(site.get('meta'), dict) else {}
    site_og = str(site_meta.get('og_image') or site.get('og_image') or '').strip()
    if site_og and not (ROOT / site_og).exists():
        add(warnings, 'missing-site-og-image', 'site', f'Site OG image does not exist: `{site_og}`.')
    for page_name, page in sorted(pages.items()):
        meta = page.get('meta') if isinstance(page.get('meta'), dict) else {}
        if not str(meta.get('title') or '').strip():
            add(blockers, 'missing-page-title', page_name, 'Page meta title is missing.')
        if not str(meta.get('description') or '').strip():
            add(blockers, 'missing-page-description', page_name, 'Page meta description is missing.')
        og = str(meta.get('og_image') or '').strip()
        if og and not (ROOT / og).exists():
            add(warnings, 'missing-page-og-image', page_name, f'Page OG image does not exist: `{og}`.')

    performance_collection = CONTENT / 'collections' / 'performance.yaml'
    if performance_collection.exists():
        collection = load_yaml(performance_collection)
        listed = [str(item).strip() for item in (collection.get('series_slugs') or collection.get('seriesSlugs') or []) if str(item).strip()]
        auto = collection.get('auto_include_project_type', False) is True
        if not listed and not auto:
            add(blockers, 'empty-stage-works-collection', 'Stage Works', 'Performance collection has no listed series and auto_include_project_type is not enabled.')
        for slug in listed:
            if slug not in series_by_slug:
                add(blockers, 'missing-stage-work-series', 'Stage Works', f'Collection references missing series `{slug}`.')
    else:
        add(blockers, 'missing-stage-works-collection', 'Stage Works', 'content/collections/performance.yaml is missing.')

    status = 'BLOCKED' if blockers else ('PASS_WITH_WARNINGS' if warnings else 'PASS')
    lines = ['# Publishing Readiness Report', '', f'Overall status: **{status}**', '', '## Summary', '', f'- Public series: `{len(public_series)}`', f'- Public works: `{len(public_works)}`', f'- Blockers: `{len(blockers)}`', f'- Warnings: `{len(warnings)}`', '']

    def section(title: str, items: list[dict], empty: str):
        lines.append(f'## {title}')
        lines.append('')
        if not items:
            lines.append(empty)
            lines.append('')
            return
        grouped: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            grouped[item['where']].append(item)
        for where, group in sorted(grouped.items()):
            lines.append(f'### {where}')
            lines.append('')
            for item in group:
                lines.append(f'- `{item["code"]}` — {item["message"]}')
            lines.append('')

    section('Blockers', blockers, 'No blocking issues found.')
    section('Warnings', warnings, 'No warnings found.')
    lines += ['## Recommended publication checklist', '', '1. Resolve blockers before publishing.', '2. Review warnings marked `non-public-work-in-public-series`: either publish the work intentionally or remove it from the public sequence until ready.', '3. Replace lightweight/missing OG images before public launch.', '4. Re-run `python scripts/publishing_readiness_audit.py` after adding the real image folders.', '']
    payload = {'status': status, 'summary': {'publicSeries': len(public_series), 'publicWorks': len(public_works), 'blockers': len(blockers), 'warnings': len(warnings)}, 'blockers': blockers, 'warnings': warnings}
    return '\n'.join(lines), payload


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit public content, curation fields, and asset readiness before publishing.')
    parser.add_argument('--markdown', default=str(DEFAULT_MD), help='Markdown report output path')
    parser.add_argument('--json', default=str(DEFAULT_JSON), help='JSON report output path')
    parser.add_argument('--fail-on-blockers', action='store_true', help='Exit non-zero if blockers are found')
    args = parser.parse_args()
    markdown, payload = build_report()
    md_path = Path(args.markdown)
    json_path = Path(args.json)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding='utf-8')
    json_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print(f'Wrote {md_path}')
    print(f'Wrote {json_path}')
    print(f"Status: {payload['status']} · blockers={payload['summary']['blockers']} · warnings={payload['summary']['warnings']}")
    if args.fail_on_blockers and payload['blockers']:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
