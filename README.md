# STILLMRK

Monochrome photography portfolio by Pooria Moozarm Nia, live at https://stillmark.art.

The site is static. Content lives in small YAML files; `build_site.py` turns them
into finished pages and responsive images in `dist/`, which is what gets hosted.

## Quick start

```bash
pip install -r requirements.txt     # Python 3.10+
python preview_server.py            # build, then open http://127.0.0.1:8000/
```

On Windows you can double-click `start-local-server.bat` instead.

## Everyday commands

| Task | Command |
| --- | --- |
| Preview the site locally | `python preview_server.py` |
| Build into `dist/` | `python build_site.py` |
| Check content only (seconds, writes nothing) | `python build_site.py --validate-only` |
| Find content and image problems | `python scripts/content_doctor.py` |
| Run all tests | `pip install -r requirements-dev.txt` then `python -m pytest` |
| Open the desktop control panel | `pip install -r requirements-qt.txt` then `python scripts/control_panel.py` |

The first build renders every image and takes a few minutes. After that the
build reuses cached images and finishes in seconds; only new or changed
photographs are rendered again.

## Project layout

```
content/                 the source of truth: one YAML file per work, series and page
templates/               page templates (Jinja2) for redesigned pages
assets/css/site.css      the design system: tokens, type, layout (redesigned pages)
assets/css/styles.css    legacy stylesheet, removed once every page is redesigned
assets/js                site scripts (site.js for redesigned pages)
assets/fonts             self-hosted Bodoni Moda and Schibsted Grotesk (OFL)
assets/images/originals  full-resolution source photographs
assets/icons, documents  favicons and downloadable PDFs
build_site.py            the build: content → dist/
scripts/                 control panel, content doctor and other tools
tests/                   automated checks run locally and in CI
dist/                    build output (git-ignored; upload or deploy this)
```

Every public series has its own page at `/series/<slug>/` and every published
photograph at `/works/<id>/`; old `series.html?series=<slug>` links redirect
there. All site links start from the root (`/assets/...`), so preview the site
through `preview_server.py` rather than opening HTML files from disk.

Images are published at most 2,560 px wide, as AVIF (up to 1,600 px), WebP and
JPEG. Captions and descriptions may use `*italics*` and `**bold**`.

Generated files never go back into the source tree. Image derivatives and social
cards are cached in `assets/images/generated` and `assets/images/social`, which
git ignores.

## Adding and changing work

1. Put the source photograph in `assets/images/originals/series/<series-slug>/`.
2. Create `content/works/<work-id>.yaml` (copy `content/templates/work.example.yaml`).
3. Add the work id to `work_ids` in `content/series/<series-slug>.yaml`, in the order you want.
4. Run `python preview_server.py` and check it.

To hide a work without deleting it, set `published: false`. To reorder a series,
reorder its `work_ids` list.

## Publishing

Pushing to GitHub runs `.github/workflows/site.yml`: it validates content, runs the
content doctor, builds the site and runs the tests. When the Cloudflare secrets
described at the top of that file are set, it then deploys `main` to production
and every other branch to its own preview URL.

Until automatic deploys are set up, run `python build_site.py` and upload the
contents of `dist/` to the host.

## Privacy

- Google Analytics only loads after a visitor accepts the consent banner. Remove
  `analytics_id` from `content/site.yaml` to turn analytics off completely.
- Series with `visibility: private` stay locked on the public site. Never put an
  `access_code` in content files: this repository may be public, and a code
  checked in the browser is not real protection. Share private work through a
  password-protected link on the host instead.
