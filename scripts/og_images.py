from __future__ import annotations

import textwrap
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

try:
    from helpers_image import load_pipeline, prepare_source_image, source_path_for_work
except ImportError:  # pragma: no cover
    from scripts.helpers_image import load_pipeline, prepare_source_image, source_path_for_work

ROOT = Path(__file__).resolve().parents[1]
OG_SIZE = (1200, 630)
BRAND = "STILLMRK"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _cover_crop(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def _darken(image: Image.Image) -> Image.Image:
    image = image.filter(ImageFilter.GaussianBlur(radius=1.5))
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 120))
    image_rgba = image.convert("RGBA")
    image_rgba.alpha_composite(overlay)
    gradient = Image.new("L", image.size, 0)
    grad_draw = ImageDraw.Draw(gradient)
    width, height = image.size
    for y in range(height):
        alpha = int(190 * (y / max(1, height - 1)))
        grad_draw.line((0, y, width, y), fill=alpha)
    shade = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shade.putalpha(gradient)
    image_rgba.alpha_composite(shade)
    return image_rgba.convert("RGB")


def _resolve_work_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for work in content.get("works", []) or []:
        work_id = str(work.get("id") or "").strip()
        if work_id:
            mapping[work_id] = work
    return mapping


def _resolve_series_map(content: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for series in content.get("series", []) or []:
        slug = str(series.get("slug") or "").strip()
        for work_id in series.get("work_ids", []) or []:
            work_text = str(work_id or "").strip()
            if slug and work_text:
                mapping[work_text] = slug
    return mapping


def _choose_series_page_work(content: dict[str, Any]) -> tuple[str | None, str | None]:
    for series in content.get("series", []) or []:
        visibility = str(series.get("visibility") or "public").strip().lower()
        if visibility != "public":
            continue
        cover = str(series.get("cover_work_id") or "").strip()
        slug = str(series.get("slug") or "").strip()
        if cover and slug:
            return slug, cover
    return None, None


def _page_targets(content: dict[str, Any]) -> list[dict[str, str]]:
    pages = content.get("pages", {}) or {}
    site = content.get("site", {}) or {}
    series_slug, series_work_id = _choose_series_page_work(content)
    series_map = _resolve_series_map(content)
    targets: list[dict[str, str]] = []

    def add(key: str, title: str, subtitle: str, og_path: str, page_path: str, series_slug: str | None, work_id: str | None) -> None:
        if og_path and series_slug and work_id:
            targets.append({
                "key": key,
                "title": title,
                "subtitle": subtitle,
                "og_path": og_path,
                "page_path": page_path,
                "series_slug": series_slug,
                "work_id": work_id,
            })

    home = pages.get("home") or {}
    home_feature_work = str(((home.get("hero") or {}).get("feature_work_id") or "")).strip()
    add(
        "home",
        str(((home.get("hero") or {}).get("title") or site.get("title") or BRAND)).strip(),
        str(((home.get("meta") or {}).get("og_description") or (home.get("meta") or {}).get("description") or "Monochrome photography portfolio")).strip(),
        str(((home.get("meta") or {}).get("og_image") or site.get("og_image") or "assets/images/social/quiet-lens-og-home.jpg")).strip(),
        "content/pages/home.yaml",
        series_map.get(home_feature_work),
        home_feature_work or None,
    )
    for key in ["portfolio", "performance", "about", "contact"]:
        page = pages.get(key) or {}
        feature = str(((page.get("hero") or {}).get("feature_work_id") or "")).strip()
        add(
            key,
            str(((page.get("hero") or {}).get("title") or key.title())).strip(),
            str(((page.get("meta") or {}).get("og_description") or (page.get("meta") or {}).get("description") or "")).strip(),
            str(((page.get("meta") or {}).get("og_image") or "")).strip(),
            f"content/pages/{key}.yaml",
            series_map.get(feature),
            feature or None,
        )
    series_page = pages.get("series") or {}
    add(
        "series",
        str(series_page.get("hero_title") or "Series").strip(),
        str(((series_page.get("meta") or {}).get("og_description") or (series_page.get("meta") or {}).get("description") or "")).strip(),
        str(((series_page.get("meta") or {}).get("og_image") or "")).strip(),
        "content/pages/series.yaml",
        series_slug,
        series_work_id,
    )
    work_map = _resolve_work_map(content)
    for target in targets:
        work = work_map.get(target["work_id"], {})
        target["social_safe"] = bool(work.get("social_safe", False))
    return targets


def _draw_wrapped(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, x: int, y: int, width: int, fill: tuple[int, int, int]) -> int:
    line_height = int(getattr(font, "size", 18) * 1.18)
    current_y = y
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    for line in lines:
        draw.text((x, current_y), line, font=font, fill=fill)
        current_y += line_height
    return current_y


def render_og_card(*, source_image_path: Path, output_path: Path, title: str, subtitle: str, eyebrow: str) -> None:
    source_image = prepare_source_image(source_image_path)
    canvas = _darken(_cover_crop(source_image, OG_SIZE))
    draw = ImageDraw.Draw(canvas)
    width, _ = canvas.size
    margin_x = 72
    title_font = _font(54, bold=True)
    eyebrow_font = _font(24, bold=True)
    subtitle_font = _font(25, bold=False)
    footer_font = _font(20, bold=False)

    draw.text((margin_x, 58), BRAND, font=eyebrow_font, fill=(242, 242, 242))
    draw.text((margin_x, 98), eyebrow.upper(), font=footer_font, fill=(208, 208, 208))
    _draw_wrapped(draw, title, title_font, margin_x, 330, width - (margin_x * 2), (255, 255, 255))
    subtitle_text = textwrap.shorten(subtitle, width=130, placeholder="…") if subtitle else ""
    if subtitle_text:
        _draw_wrapped(draw, subtitle_text, subtitle_font, margin_x, 500, width - (margin_x * 2), (220, 220, 220))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=88, optimize=True, progressive=True)



def render_fallback_og_card(*, output_path: Path, title: str, subtitle: str, eyebrow: str) -> None:
    """Render a deterministic social card when no photograph source exists yet.

    This keeps Open Graph/Twitter previews valid in metadata-only builds without
    inventing fake artwork or changing portfolio content. When a real source
    image is later added, render_og_card() takes precedence and replaces it.
    """
    canvas = Image.new("RGB", OG_SIZE, (8, 8, 7))
    draw = ImageDraw.Draw(canvas)
    width, height = canvas.size

    # Restrained exhibition-card atmosphere: soft dark gradients and a fine grid.
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    for y in range(height):
        alpha = int(112 * (y / max(1, height - 1)))
        overlay_draw.line((0, y, width, y), fill=(0, 0, 0, alpha))
    for radius, alpha in [(920, 36), (620, 24), (360, 18)]:
        overlay_draw.ellipse((width - radius, -radius // 2, width + radius // 5, radius), fill=(216, 197, 162, alpha))
    for x in range(0, width, 48):
        overlay_draw.line((x, 0, x, height), fill=(255, 255, 255, 7))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)

    margin_x = 72
    title_font = _font(58, bold=True)
    eyebrow_font = _font(24, bold=True)
    subtitle_font = _font(25, bold=False)
    footer_font = _font(20, bold=False)

    draw.text((margin_x, 58), BRAND, font=eyebrow_font, fill=(242, 239, 232))
    draw.text((margin_x, 98), eyebrow.upper(), font=footer_font, fill=(216, 197, 162))
    draw.line((margin_x, 160, width - margin_x, 160), fill=(242, 239, 232), width=1)
    _draw_wrapped(draw, title or BRAND, title_font, margin_x, 300, width - (margin_x * 2), (255, 255, 255))
    subtitle_text = textwrap.shorten(subtitle or "Monochrome photography portfolio", width=132, placeholder="…")
    if subtitle_text:
        _draw_wrapped(draw, subtitle_text, subtitle_font, margin_x, 500, width - (margin_x * 2), (220, 220, 220))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=86, optimize=True, progressive=True)


OG_STAMP_PATH = ROOT / ".stillmrk-build" / "og-stamps.json"


def _load_stamps() -> dict[str, Any]:
    try:
        return json.loads(OG_STAMP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _stamp_for(target: dict[str, str], source_path: Path | None) -> dict[str, Any]:
    stamp: dict[str, Any] = {
        "title": target["title"],
        "subtitle": target["subtitle"],
        "eyebrow": target["key"],
        "source": source_path.relative_to(ROOT).as_posix() if source_path and source_path.exists() else "",
    }
    if source_path and source_path.exists():
        stamp["source_mtime_ns"] = source_path.stat().st_mtime_ns
        stamp["source_size"] = source_path.stat().st_size
    return stamp


def ensure_og_images_from_content(content: dict[str, Any], *, force: bool = False) -> list[str]:
    """Render social cards only when their title, subtitle or photo changed.

    The previous version compared against page modification times, and pages
    are rewritten on every build, so every build re-rendered every card.
    """
    pipeline = load_pipeline()
    stamps = _load_stamps()
    generated: list[str] = []
    for target in _page_targets(content):
        og_path = ROOT / target["og_path"].lstrip("/")
        source_path = source_path_for_work(target["series_slug"], target["work_id"], pipeline=pipeline)
        has_source = bool(source_path and source_path.exists())
        key = og_path.relative_to(ROOT).as_posix()
        stamp = _stamp_for(target, source_path if has_source else None)
        if not force and og_path.exists() and stamps.get(key) == stamp:
            continue
        if has_source:
            render_og_card(source_image_path=source_path, output_path=og_path, title=target["title"], subtitle=target["subtitle"], eyebrow=target["key"])
        else:
            render_fallback_og_card(output_path=og_path, title=target["title"], subtitle=target["subtitle"], eyebrow=target["key"])
        stamps[key] = stamp
        generated.append(key)
    if generated:
        OG_STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        OG_STAMP_PATH.write_text(json.dumps(stamps, indent=2) + "\n", encoding="utf-8")
    return generated


def load_content_for_og() -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required to generate OG images") from exc

    content_dir = ROOT / "content"
    def load_yaml(path: Path) -> Any:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    pages: dict[str, Any] = {}
    for path in sorted((content_dir / "pages").glob("*.yaml")):
        pages[path.stem] = load_yaml(path)
    series = [load_yaml(path) for path in sorted((content_dir / "series").glob("*.yaml"))]
    works = [load_yaml(path) for path in sorted((content_dir / "works").glob("*.yaml"))]
    return {
        "site": load_yaml(content_dir / "site.yaml"),
        "pages": pages,
        "series": series,
        "works": works,
    }


def main() -> None:
    content = load_content_for_og()
    created = ensure_og_images_from_content(content, force=True)
    if created:
        print("Generated OG images:")
        for item in created:
            print(f"- {item}")
    else:
        print("No OG images were generated. Check that your source images exist for the current page selections.")


if __name__ == "__main__":
    main()
