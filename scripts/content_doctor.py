"""Content doctor: report content and image problems without changing anything.

Usage:
    python scripts/content_doctor.py            # human-readable report
    python scripts/content_doctor.py --json     # machine-readable report
    python scripts/content_doctor.py --strict   # exit 1 if any error is found

What it checks:
  errors   - works whose image file cannot be found
  warnings - series that list draft/archived works (hidden on the public site)
           - original images that no work uses
           - leftover `.replaced-<timestamp>` backups in originals/
           - originals folders that match no series slug
It never moves or deletes files; it tells you what to look at.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_site  # noqa: E402  (loads content/ once, read-only)

ORIGINALS = ROOT / 'assets' / 'images' / 'originals'


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def run_checks() -> dict[str, Any]:
    content = build_site.SITE_CONTENT
    works = content['works']
    series = content['series']
    works_by_id = {str(w.get('id')): w for w in works}
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    used_sources: set[Path] = set()
    for work in works:
        work_id = str(work.get('id'))
        image_config = build_site.resolve_image_definition(work)
        explicit = str(image_config.get('source') or image_config.get('original') or image_config.get('master') or '').strip()
        try:
            source = build_site.resolve_source_path(work, image_config)
            used_sources.add(source.resolve())
        except FileNotFoundError as exc:
            if explicit or work.get('published', True) is not False:
                errors.append({'check': 'missing-image', 'item': work_id, 'detail': str(exc).splitlines()[0]})

    for entry in series:
        slug = str(entry.get('slug'))
        for work_id in entry.get('work_ids') or []:
            work = works_by_id.get(str(work_id))
            if work is None:
                errors.append({'check': 'missing-work', 'item': slug, 'detail': f"lists unknown work '{work_id}'"})
            elif work.get('published', True) is False:
                status = str(work.get('review_status') or 'draft')
                warnings.append({'check': 'hidden-work-in-series', 'item': slug, 'detail': f"'{work_id}' is {status} and hidden on the site"})

    slugs = {str(entry.get('slug')) for entry in series}
    series_root = ORIGINALS / 'series'
    if series_root.exists():
        for folder in sorted(p for p in series_root.iterdir() if p.is_dir()):
            if folder.name not in slugs:
                warnings.append({'check': 'unknown-folder', 'item': _rel(folder), 'detail': 'no series has this slug'})

    for path in sorted(ORIGINALS.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in build_site.SOURCE_EXTENSIONS:
            continue
        if '.replaced-' in path.name:
            warnings.append({'check': 'replaced-backup', 'item': _rel(path), 'detail': 'backup left by an image replacement'})
        elif path.resolve() not in used_sources:
            warnings.append({'check': 'unused-original', 'item': _rel(path), 'detail': 'no work uses this file'})

    return {'ok': not errors, 'errors': errors, 'warnings': warnings}


def print_report(report: dict[str, Any]) -> None:
    for label, rows in (('ERROR', report['errors']), ('WARN ', report['warnings'])):
        for row in rows:
            print(f"{label} {row['check']:<22} {row['item']}: {row['detail']}")
    print(f"\n{len(report['errors'])} error(s), {len(report['warnings'])} warning(s). Nothing was changed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--strict', action='store_true', help='exit with status 1 when errors are found')
    args = parser.parse_args()
    report = run_checks()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 1 if (args.strict and report['errors']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
