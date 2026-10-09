from __future__ import annotations

from pathlib import Path
import argparse
import yaml

ROOT = Path(__file__).resolve().parents[1]
SERIES_DIR = ROOT / 'content' / 'series'
WORKS_DIR = ROOT / 'content' / 'works'
OUTPUT_DEFAULT = ROOT / '.stillmrk-build' / 'meta' / 'story-curation-report.md'


def load_yaml(path: Path):
    with path.open('r', encoding='utf-8') as fh:
        return yaml.safe_load(fh) or {}


def get_work_title(work_id: str) -> str:
    path = WORKS_DIR / f'{work_id}.yaml'
    if not path.exists():
        return f'{work_id} (missing)'
    data = load_yaml(path)
    return str(data.get('title') or work_id)


def build_report() -> str:
    series_files = sorted(SERIES_DIR.glob('*.yaml'))
    lines: list[str] = []
    lines.append('# Story Curation Report')
    lines.append('')
    lines.append('This report helps review sequencing and cover curation across public and private stories.')
    lines.append('')
    for path in series_files:
        series = load_yaml(path)
        title = str(series.get('title') or path.stem)
        slug = str(series.get('slug') or path.stem)
        visibility = str(series.get('visibility') or 'public')
        project_type = str(series.get('project_type') or 'fine-art')
        work_ids = [str(item).strip() for item in (series.get('work_ids') or []) if str(item).strip()]
        cover_id = str(series.get('cover_work_id') or '').strip()
        card_cover_id = str(series.get('card_cover_work_id') or '').strip()
        hero_id = str(series.get('hero_work_id') or '').strip()
        lines.append(f'## {title}')
        lines.append('')
        lines.append(f'- Slug: `{slug}`')
        lines.append(f'- Visibility: `{visibility}`')
        lines.append(f'- Type: `{project_type}`')
        lines.append(f'- Work count: `{len(work_ids)}`')
        if work_ids:
            lines.append(f'- Opening work: `{work_ids[0]}` - {get_work_title(work_ids[0])}')
            lines.append(f'- Closing work: `{work_ids[-1]}` - {get_work_title(work_ids[-1])}')
        if cover_id:
            lines.append(f'- Cover work: `{cover_id}` - {get_work_title(cover_id)}')
        if card_cover_id:
            lines.append(f'- Card cover override: `{card_cover_id}` - {get_work_title(card_cover_id)}')
        if hero_id:
            lines.append(f'- Hero override: `{hero_id}` - {get_work_title(hero_id)}')
        if series.get('card_summary'):
            lines.append(f'- Card summary: {series.get("card_summary")}')
        if series.get('story_opening_text'):
            lines.append(f'- Opening note: {series.get("story_opening_text")}')
        if series.get('story_sequence_text'):
            lines.append(f'- Sequence note: {series.get("story_sequence_text")}')
        if series.get('story_closing_text'):
            lines.append(f'- Closing note: {series.get("story_closing_text")}')

        warnings = []
        missing = [wid for wid in work_ids if not (WORKS_DIR / f'{wid}.yaml').exists()]
        if missing:
            warnings.append('Missing works in this package: ' + ', '.join(f'`{wid}`' for wid in missing))
        if cover_id and cover_id not in work_ids:
            warnings.append('cover_work_id is not included in work_ids')
        if card_cover_id and card_cover_id not in work_ids:
            warnings.append('card_cover_work_id is not included in work_ids')
        if hero_id and hero_id not in work_ids:
            warnings.append('hero_work_id is not included in work_ids')
        if not cover_id and work_ids:
            warnings.append('No cover_work_id set; build will fall back to the first resolved work')
        if not series.get('card_summary'):
            warnings.append('No card_summary set; cards will fall back to description/mood excerpts')

        if warnings:
            lines.append('')
            lines.append('### Notes')
            for warning in warnings:
                lines.append(f'- {warning}')
        lines.append('')
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate a story curation report for series and stage works.')
    parser.add_argument('--output', default=str(OUTPUT_DEFAULT), help='Output markdown path')
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_report(), encoding='utf-8')
    print(f'Wrote {output_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
