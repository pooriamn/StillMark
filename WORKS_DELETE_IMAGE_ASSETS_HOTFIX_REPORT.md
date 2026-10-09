# V2 Works Delete Image + Assets Hotfix

Applied on top of:
- `V2_series_slug_asset_sync_hotfix.zip`

## What changed

### 1. Restored an explicit Works-tab delete control

A visible button was added in the Works tab library toolbar:

- `Delete image…`

The same action is also available from:

- Library tools menu
- Work context menu
- Command palette action

### 2. Full deletion now removes the real work, not just metadata

Choosing **Delete image + assets** now removes:

- the work YAML file in `content/works/`
- the work reference from every series sequence
- the work as a series cover, with fallback to the next available work
- homepage/relationship references
- exact work references from page YAML payloads
- original/source image file candidates
- generated derivative folders and generated derivative file candidates
- now-empty work asset folders
- editor draft for that work
- stale image manifest rows by refreshing manifests after deletion

### 3. Safer destructive flow

The control panel still offers **Archive only** for non-destructive hiding.

Full deletion requires a second confirmation and uses transaction backups. It is intentionally clear that it is a destructive storage-cleanup action.

### 4. Stronger asset cleanup

The backend now searches multiple known asset sources before deleting:

- current source folder
- legacy originals folders
- manifest source paths
- render-name / work-id original candidates
- generated derivative folders
- generated derivative files from manifest
- historical generated candidates

Deletion is constrained to known `assets/images/...` roots so it does not remove arbitrary files outside the image pipeline.

## Files changed

- `scripts/control_panel.py`
- `scripts/qt_backend.py`

## Validation

Passed:

```text
python -m py_compile scripts/*.py build_site.py
node --check assets/js/series.js
node --check assets/js/portfolio.js
node --check public_upload/assets/js/series.js
node --check public_upload/assets/js/portfolio.js
python build_site.py
python scripts/repair_series_asset_folders.py --dry-run
python scripts/verify_control_panel_package.py
```

Expected build warnings remain about missing social/OG images and non-public referenced works in the lightweight package. Those are unrelated to this hotfix.
