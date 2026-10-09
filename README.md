# STILLMRK - public static portfolio build

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
