"""Rules for pages on the new design system (templates/ + assets/css/site.css)."""
from __future__ import annotations

import re

from conftest import DIST, ROOT

def _pages():
    return sorted(p.relative_to(DIST).as_posix() for p in DIST.rglob('*.html'))


REDESIGNED = ['index.html', 'portfolio.html', 'series.html', 'performance.html', 'about.html', 'contact.html', '404.html',
              'series/hamlet/index.html', 'works/mirror-shore/index.html']


def test_site_css_has_no_important_overrides():
    css = (ROOT / 'assets' / 'css' / 'site.css').read_text(encoding='utf-8')
    assert '!important' not in css


def test_fonts_are_self_hosted_and_licensed():
    fonts = ROOT / 'assets' / 'fonts'
    assert list(fonts.glob('*.woff2'))
    assert list(fonts.glob('OFL-*.txt')), 'ship the font licences with the fonts'


def test_every_page_loads_only_the_new_assets(build):
    for page in _pages():
        html = (DIST / page).read_text(encoding='utf-8')
        assert '/assets/css/site.css' in html, page
        assert 'styles.css' not in html, f'{page} still loads the old stylesheet'
        assert 'data.js' not in html and 'assets/js/app.js' not in html, f'{page} loads the 288 KB data file'
        assert 'fonts.googleapis.com' not in html, page


def test_no_page_has_inline_code(build):
    """Inline scripts and style blocks would block a strict Content Security Policy."""
    for page in _pages():
        html = (DIST / page).read_text(encoding='utf-8')
        inline_scripts = [m for m in re.findall(r'<script(?![^>]*\bsrc=)([^>]*)>', html) if 'application/ld+json' not in m and 'application/json' not in m]
        assert not inline_scripts, f'{page}: inline <script>'
        assert '<style' not in html, f'{page}: inline <style>'


def test_photographs_are_never_cropped(build):
    css = (ROOT / 'assets' / 'css' / 'site.css').read_text(encoding='utf-8')
    assert 'object-fit: cover' not in css, 'site.css must not crop photographs'


def test_one_h1_per_page_and_landmarks(build):
    for page in _pages():
        html = (DIST / page).read_text(encoding='utf-8')
        assert html.count('<h1') == 1, page
        assert '<main id="main">' in html and 'href="#main"' in html, page
        assert '<nav class="site-nav"' in html, page


def test_legacy_frontend_is_gone():
    for name in ('assets/js/app.js', 'assets/js/portfolio.js', 'assets/js/series.js', 'assets/js/collection-tools.js', 'assets/css/styles.css'):
        assert not (ROOT / name).exists(), name


def test_pages_carry_inline_styles_only_for_photo_ratios(build):
    for page in _pages():
        html = (DIST / page).read_text(encoding='utf-8')
        for style in re.findall(r'style="([^"]*)"', html):
            assert re.fullmatch(r'\s*--(ratio|r):\s*\d+ / \d+;\s*', style), f'{page}: style="{style}"'
