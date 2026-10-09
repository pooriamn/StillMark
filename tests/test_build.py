from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

from conftest import DIST, ROOT

PAGES = ['index.html', 'portfolio.html', 'series.html', 'performance.html', 'about.html', 'contact.html', '404.html']


def test_build_never_modifies_source_files(build):
    assert build['after'] == build['before']


def test_nothing_generated_into_source_tree(build):
    for name in PAGES + ['robots.txt', 'sitemap.xml', 'site.webmanifest', 'app.js', 'styles.css', 'data.js']:
        assert not (ROOT / name).exists(), f'{name} was written to the project root; output belongs in dist/'
    assert not (ROOT / 'assets' / 'js' / 'data.js').exists(), 'data.js is generated and belongs in dist/ only'
    assert not (ROOT / 'public_upload').exists()


def test_all_pages_and_files_exist(build):
    for name in PAGES + ['robots.txt', 'sitemap.xml', 'site.webmanifest', 'upload-manifest.json', 'assets/js/data.js', 'assets/css/styles.css']:
        path = DIST / name
        assert path.exists() and path.stat().st_size > 0, f'dist/{name} missing or empty'


def test_second_build_reuses_image_cache(build):
    match = re.search(r'Images: (\d+) rendered, (\d+) reused', build['second'].stdout)
    assert match, build['second'].stdout[-1500:]
    assert int(match.group(1)) == 0, 'an unchanged rebuild re-rendered images'


def test_originals_are_never_published(build):
    assert not (DIST / 'assets' / 'images' / 'originals').exists()
    assert not list(DIST.rglob('.derivatives.json'))


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs: list[str] = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if not value:
                continue
            if key in ('href', 'src'):
                self.refs.append(value)
            elif key in ('srcset', 'imagesrcset'):
                self.refs.extend(part.strip().split(' ')[0] for part in value.split(',') if part.strip())


def all_pages() -> list[str]:
    return sorted(path.relative_to(DIST).as_posix() for path in DIST.rglob('*.html'))


def test_every_local_link_and_asset_resolves(build):
    broken = []
    for page in all_pages():
        parser = _Refs()
        parser.feed((DIST / page).read_text(encoding='utf-8'))
        for ref in parser.refs:
            parsed = urlparse(ref)
            if parsed.scheme or ref.startswith(('#', 'mailto:', 'tel:', '//', 'data:')):
                continue
            target = DIST / unquote(parsed.path).lstrip('/')
            if parsed.path.endswith('/'):
                target = target / 'index.html'
            if not target.exists():
                broken.append(f'{page}: {ref}')
    assert not broken, 'broken local references:\n' + '\n'.join(sorted(set(broken))[:50])


def test_analytics_waits_for_consent(build):
    for page in PAGES:
        html = (DIST / page).read_text(encoding='utf-8')
        assert 'googletagmanager.com' not in html, f'{page} loads Google Analytics before consent'
    assert (DIST / 'assets' / 'js' / 'consent.js').exists()


def test_no_access_hash_is_published(build):
    data = (DIST / 'assets' / 'js' / 'data.js').read_text(encoding='utf-8')
    hashes = re.findall(r'"accessHash":\s*"([^"]*)"', data)
    assert hashes and all(value == '' for value in hashes)


def test_sitemap_and_manifest_are_valid(build):
    tree = ET.parse(DIST / 'sitemap.xml')
    urls = [el.text for el in tree.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    assert urls and all(url.startswith('https://') for url in urls)
    json.loads((DIST / 'site.webmanifest').read_text(encoding='utf-8'))
    manifest = json.loads((DIST / 'upload-manifest.json').read_text(encoding='utf-8'))
    assert manifest['uploadFolder'] == 'dist'


def test_pages_have_core_metadata(build):
    for page in PAGES:
        html = (DIST / page).read_text(encoding='utf-8')
        assert re.search(r'<title>[^<]+</title>', html), page
        assert '<html lang="en">' in html, page
        assert 'name="viewport"' in html, page


def _site_data():
    import json as _json
    text = (DIST / 'assets' / 'js' / 'data.js').read_text(encoding='utf-8')
    start = text.index('export const siteData = ') + len('export const siteData = ')
    obj, _ = _json.JSONDecoder().raw_decode(text[start:])
    return obj


def test_every_public_series_and_work_has_its_own_page(build):
    data = _site_data()
    sitemap = (DIST / 'sitemap.xml').read_text(encoding='utf-8')
    for series in data['series']:
        assert (DIST / 'series' / series['slug'] / 'index.html').exists(), series['slug']
        assert f"/series/{series['slug']}/" in sitemap
    for work in data['works']:
        assert (DIST / 'works' / work['id'] / 'index.html').exists(), work['id']
        assert f"/works/{work['id']}/" in sitemap


def test_local_urls_are_root_relative(build):
    """Pages live at several depths, so a relative 'assets/...' URL would break."""
    offenders = []
    for page in all_pages():
        parser = _Refs()
        parser.feed((DIST / page).read_text(encoding='utf-8'))
        for ref in parser.refs:
            if ref.startswith(('/', '#', 'http:', 'https:', 'mailto:', 'tel:', 'data:', '?')):
                continue
            offenders.append(f'{page}: {ref}')
    assert not offenders, '\n'.join(offenders[:20])
    data_js = (DIST / 'assets' / 'js' / 'data.js').read_text(encoding='utf-8')
    assert '"assets/' not in data_js


def test_no_raw_markdown_in_output(build):
    pattern = re.compile(r'(?<![\w*])\*[A-Z][^*<>]{1,60}\*(?![\w*])')
    hits = [page for page in all_pages() if pattern.search(re.sub(r'<script.*?</script>', '', (DIST / page).read_text(encoding='utf-8'), flags=re.S))]
    data_hits = pattern.findall((DIST / 'assets' / 'js' / 'data.js').read_text(encoding='utf-8'))
    assert not hits and not data_hits, (hits[:5], data_hits[:5])


def test_structured_data_is_built_into_every_page(build):
    for page in all_pages():
        html = (DIST / page).read_text(encoding='utf-8')
        blocks = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S)
        assert len(blocks) == 2, page
        for block in blocks:
            assert block.strip(), f'{page}: empty JSON-LD'
            json.loads(block)


def test_work_pages_describe_a_visual_artwork(build):
    html = (DIST / 'works' / 'mirror-shore' / 'index.html').read_text(encoding='utf-8')
    assert '"@type":"VisualArtwork"' in html
    assert '<link rel="canonical" href="https://stillmark.art/works/mirror-shore/">' in html


def test_old_series_query_links_redirect(build):
    html = (DIST / 'series.html').read_text(encoding='utf-8')
    assert "location.replace('/series/'" in html


def test_image_derivatives_are_capped_and_include_avif(build):
    from PIL import Image
    generated = ROOT / 'assets' / 'images' / 'generated'
    widths = [int(p.stem.rsplit('-', 1)[-1]) for p in (DIST / 'assets' / 'images' / 'generated').rglob('*.jpg')]
    assert widths and max(widths) <= 2560
    assert list((DIST / 'assets' / 'images' / 'generated').rglob('*.avif'))
