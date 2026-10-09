# Series Slug Asset Sync Hotfix

Applied to the uploaded `V2 - Copy` package.

## Bug fixed
Changing a series slug/title in the Series tab updated the series YAML, but could leave related work YAML and image asset folders under the historical slug, for example:

- `a-kingdom-after-silence` instead of `hamlet`
- `blood-wedding-series-slug-blood-wedding` instead of `blood-wedding`
- `othello-series-slug-othello` instead of `othello`

The root cause was that `work_to_series_map()` resolves membership from the series sequence first. That made the backend think works already belonged to the renamed series even when the individual work YAML still had the old `series:` value.

## What changed

### 1. Series save now repairs work YAML directly
When saving a series, the backend now checks every work listed in that series sequence and forces the work YAML `series:` field to match the current series slug.

### 2. Original image folders now move with slug changes
When a work moves from an old series slug to a new one, original images are moved from:

```text
assets/images/originals/series/<old-slug>/
```

to:

```text
assets/images/originals/series/<new-slug>/
```

### 3. Generated derivative folders now move too
Generated derivatives are moved from:

```text
assets/images/generated/series/<old-slug>/
```

to:

```text
assets/images/generated/series/<new-slug>/
```

The move uses each work's `image.render_name` when available, not only the work ID.

### 4. Empty old slug folders are cleaned up
After files/directories are moved out, empty historical series folders are removed.

### 5. Image manifests are refreshed after save
After a series save, the backend refreshes the image manifest tables so the control panel preview paths and asset health checks do not stay stale.

### 6. One-time repair script added
Added:

```text
scripts/repair_series_asset_folders.py
```

Use it manually if needed:

```bash
python scripts/repair_series_asset_folders.py --dry-run
python scripts/repair_series_asset_folders.py
```

## Existing content repaired in this package
The package had 31 work YAML files still pointing to old series slugs. They were repaired so their `series:` values now match the authoritative series sequence.

Examples repaired:

- Hamlet works now use `series: hamlet`
- Blood Wedding works now use `series: blood-wedding`
- Othello review works now use `series: othello`

## Files changed

```text
scripts/helpers_image.py
scripts/qt_backend.py
scripts/repair_series_asset_folders.py
content/works/*.yaml where stale series references existed
rebuilt generated site/public output
```

## Validation

Passed:

```text
python -m py_compile scripts/helpers_image.py scripts/qt_backend.py scripts/repair_series_asset_folders.py scripts/control_panel.py build_site.py
node --check assets/js/series.js
node --check assets/js/portfolio.js
python build_site.py
python scripts/repair_series_asset_folders.py --dry-run
```

Expected warnings remain for intentionally missing images/social OG assets and non-public works in the lightweight package.
