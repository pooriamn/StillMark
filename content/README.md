# Content editing guide

This project keeps public copy and image metadata in YAML. The public UI is built from `content/`, while the image workflow now separates incoming files, archived originals, generated web derivatives, and manifests.

## Canonical source of truth

Use files under `content/` as the editable source of truth.

Do not treat these legacy root-level mirrors as primary sources:
- `pages/`
- `series/`
- `works/`
- `templates/`
- `schema/`

## Main editing workflow

- Edit site-wide settings in `site.yaml`, `artist.yaml`, `navigation.yaml`, and `image-pipeline.yaml`
- Edit page copy in `pages/*.yaml`
- Edit the narrative sequence in `series/*.yaml`
- Edit work metadata in `works/*.yaml`
- Drop new source images in `../assets/images/incoming/`
- Run `python scripts/ingest_work.py` to place a new image automatically
- Run `python build_site.py` after changes

## Image folders

- `../assets/images/incoming/` → temporary drop zone for new uploads
- `../assets/images/originals/series/<series-slug>/` → one archived master per published work
- `../assets/images/originals/unassigned/` → originals not yet attached to a series
- `../assets/images/generated/series/<series-slug>/<work-id>/` → generated JPG/WebP derivatives for the public site
- `../assets/images/manifests/` → generated JSON manifests for auditing and rebuilds

## Rules

- Put new files only in `assets/images/incoming/`
- Do not manually edit anything in `assets/images/generated/`
- Do not upload `assets/images/originals/` to the host
- Prefer one master image per work id
- Use clear work ids such as `threshold-walker` or `pale-road`, never camera filenames

## New image workflow

1. Drop the original file in `assets/images/incoming/`
2. Run `python scripts/ingest_work.py`
3. Answer the prompts for title, series, work id, alt text, caption, and focal point
4. Review the generated YAML file in `content/works/`
5. Rebuild with `python build_site.py`

## Maintenance scripts

- `python scripts/ingest_work.py` → add a new image and create/update metadata
- `python scripts/regenerate_derivatives.py --all` → rebuild all derivatives
- `python scripts/regenerate_derivatives.py --series winter-silence` → rebuild one series
- `python scripts/regenerate_derivatives.py --work pale-road` → rebuild one work
- `python scripts/audit_library.py` → report missing originals, derivatives, or orphaned files

## Templates

- `templates/work.example.yaml`
- `templates/series.example.yaml`

Copy one of these when you add a new file so you do not have to guess the shape.

## Stage Works collection model

Use `content/collections/performance.yaml` as the Stage Works parent collection. Each individual theatre/performance project should be created as a normal file in `content/series/` with `project_type: performance`. The internal `performance` value is kept for build compatibility, while the public label is Stage Works. Each image remains a normal work in `content/works/` and is assigned to that stage-work series.

Do not put every stage image into one giant `Stage Works` series. That flattens project identity and makes sequencing, captions, and future navigation weaker.


## Story curation fields

Series and Stage Works can now carry a small set of optional narrative metadata to improve public presentation without changing sequence order:

- `card_summary` - short summary used on index cards and overview surfaces
- `story_opening_text` - optional opening note for the story map
- `story_sequence_text` - optional sequence note for the story map
- `story_closing_text` - optional ending note for the story map
- `card_cover_work_id` - optional card/index cover override
- `hero_work_id` - optional series-page hero override

If these are omitted, the build falls back to existing descriptions, captions, and `cover_work_id`.


## Per-image layout control

Each work can optionally control its presentation size without using arbitrary pixel values:

```yaml
portfolio_layout: standard
series_layout: large
```

Allowed values:

- `auto` - keep the site-generated rhythm
- `quiet` - smaller supporting image
- `standard` - normal card
- `medium` - gentle emphasis
- `large` - strong image without dominating the page
- `wide` - cinematic horizontal emphasis
- `full` - full-row pause / major story beat

Optional crop ratios can be set per context:

```yaml
display_ratios:
  portfolio: 4 / 3
  series: 3 / 2
  hero: 16 / 10
```

Use this sparingly. The goal is authorship and rhythm, not a random mosaic.
