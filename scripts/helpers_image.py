from __future__ import annotations

import hashlib
import json
import shutil
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageOps

try:
    from helpers_content import register_created_path, snapshot_path, guarded_copy2, guarded_move, record_transaction_step
    from control_panel_io import atomic_write_json
except ImportError:  # pragma: no cover
    from scripts.helpers_content import register_created_path, snapshot_path, guarded_copy2, guarded_move, record_transaction_step
    from scripts.control_panel_io import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content"
SOURCE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")

_PIPELINE_CACHE: dict[str, Any] | None = None
_PIPELINE_CACHE_MTIME_NS: int | None = None


def clear_pipeline_cache() -> None:
    """Invalidate the cached image-pipeline settings.

    The control panel reads image-pipeline.yaml from many asset-health paths.
    Keeping this cache local and mtime-aware avoids hundreds of repeated YAML
    parses during dashboard/source refreshes while still picking up file edits.
    """
    global _PIPELINE_CACHE, _PIPELINE_CACHE_MTIME_NS
    _PIPELINE_CACHE = None
    _PIPELINE_CACHE_MTIME_NS = None


def load_pipeline(*, force: bool = False) -> dict[str, Any]:
    path = CONTENT_DIR / "image-pipeline.yaml"
    try:
        mtime_ns = path.stat().st_mtime_ns
    except FileNotFoundError:
        mtime_ns = -1
    global _PIPELINE_CACHE, _PIPELINE_CACHE_MTIME_NS
    if not force and _PIPELINE_CACHE is not None and _PIPELINE_CACHE_MTIME_NS == mtime_ns:
        return copy.deepcopy(_PIPELINE_CACHE)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    _PIPELINE_CACHE = dict(data or {})
    _PIPELINE_CACHE_MTIME_NS = mtime_ns
    return copy.deepcopy(_PIPELINE_CACHE)


def incoming_root(pipeline: dict[str, Any] | None = None) -> Path:
    pipeline = pipeline or load_pipeline()
    return ROOT / str(pipeline.get("incoming_dir") or "assets/images/incoming")


def source_root(pipeline: dict[str, Any] | None = None) -> Path:
    pipeline = pipeline or load_pipeline()
    return ROOT / str(pipeline.get("source_dir") or "assets/images/originals/series")


def generated_root(pipeline: dict[str, Any] | None = None) -> Path:
    pipeline = pipeline or load_pipeline()
    return ROOT / str(pipeline.get("generated_dir") or pipeline.get("responsive_dir") or "assets/images/generated/series")


def manifest_root(pipeline: dict[str, Any] | None = None) -> Path:
    pipeline = pipeline or load_pipeline()
    return ROOT / str(pipeline.get("manifest_dir") or "assets/images/manifests")


def unassigned_root() -> Path:
    return ROOT / "assets/images/originals/unassigned"


def _cleanup_empty_series_dir(path: Path, root: Path) -> None:
    """Remove an empty series asset directory after moving files out of it."""
    try:
        resolved_path = path.resolve(strict=False)
        resolved_root = root.resolve(strict=False)
    except Exception:
        return
    if resolved_path == resolved_root:
        return
    try:
        resolved_path.relative_to(resolved_root)
    except Exception:
        return
    if not path.exists() or not path.is_dir():
        return
    try:
        path.rmdir()
        record_transaction_step("rmdir_empty", target=path, detail="remove empty old series asset folder")
    except OSError:
        return


def prepare_source_image(source_path: Path) -> Image.Image:
    with Image.open(source_path) as raw_image:
        image = ImageOps.exif_transpose(raw_image)
        if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        if image.mode != "RGB":
            return image.convert("RGB")
        return image.copy()


def compute_image_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        return image.size


def source_path_for_work(series_slug: str, work_id: str, pipeline: dict[str, Any] | None = None) -> Path | None:
    """Find an original/source image in the current and legacy asset layouts.

    Current Stillmark originals live under:
    assets/images/originals/series/<series>/<work-id>.<ext>
    Older content may still point at assets/images/originals/<work-id>.<ext>.
    Search both direct paths and recursive descendants so GUI previews do not
    falsely report missing assets after folder reorganisation.
    """
    pipeline = pipeline or load_pipeline()
    search_roots = [
        source_root(pipeline) / series_slug,
        ROOT / "assets/images/originals/series" / series_slug,
        source_root(pipeline),
        ROOT / "assets/images/originals/series",
        ROOT / "assets/images/originals",
        ROOT / "assets/images/originals/unassigned",
        ROOT / "assets/images",
    ]
    seen_roots: set[str] = set()
    for root_path in search_roots:
        key = str(root_path.resolve(strict=False))
        if key in seen_roots or not root_path.exists():
            continue
        seen_roots.add(key)
        for ext in SOURCE_EXTENSIONS:
            direct = root_path / f"{work_id}{ext}"
            if direct.exists():
                return direct
        for ext in SOURCE_EXTENSIONS:
            matches = sorted(root_path.rglob(f"{work_id}{ext}"))
            if matches:
                return matches[0]
    return None


def derivative_dir_for_work(series_slug: str, render_name: str, pipeline: dict[str, Any] | None = None) -> Path:
    pipeline = pipeline or load_pipeline()
    clean_name = render_name.replace("/", "-")
    return generated_root(pipeline) / series_slug / clean_name


def derivative_base_for_work(series_slug: str, render_name: str, pipeline: dict[str, Any] | None = None) -> Path:
    work_dir = derivative_dir_for_work(series_slug, render_name, pipeline=pipeline)
    clean_name = render_name.replace("/", "-")
    return work_dir / clean_name


def move_original_between_series(work_id: str, old_series_slug: str | None, new_series_slug: str, pipeline: dict[str, Any] | None = None) -> Path | None:
    pipeline = pipeline or load_pipeline()
    if old_series_slug == new_series_slug:
        return source_path_for_work(new_series_slug, work_id, pipeline=pipeline)
    source_path = source_path_for_work(old_series_slug or new_series_slug, work_id, pipeline=pipeline) if old_series_slug else source_path_for_work(new_series_slug, work_id, pipeline=pipeline)
    if not source_path or not source_path.exists():
        return None
    destination_dir = source_root(pipeline) / new_series_slug
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source_path.name
    snapshot_path(source_path)
    if destination.exists() and destination.resolve() != source_path.resolve():
        snapshot_path(destination)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = destination.with_name(f"{destination.stem}.replaced-{timestamp}{destination.suffix}")
        shutil.move(str(destination), str(backup))
        register_created_path(backup)
    old_parent = source_path.parent
    shutil.move(str(source_path), str(destination))
    register_created_path(destination)
    if old_series_slug:
        _cleanup_empty_series_dir(old_parent, source_root(pipeline))
    return destination


def move_generated_between_series(
    work_id: str,
    old_series_slug: str | None,
    new_series_slug: str,
    pipeline: dict[str, Any] | None = None,
    *,
    render_name: str | None = None,
) -> Path | None:
    pipeline = pipeline or load_pipeline()
    asset_name = (render_name or work_id).replace("/", "-")
    if not old_series_slug or old_series_slug == new_series_slug:
        return derivative_dir_for_work(new_series_slug, asset_name, pipeline=pipeline)
    source_dir = derivative_dir_for_work(old_series_slug, asset_name, pipeline=pipeline)
    if not source_dir.exists():
        return None
    destination_dir = derivative_dir_for_work(new_series_slug, asset_name, pipeline=pipeline)
    old_parent = source_dir.parent
    snapshot_path(source_dir)
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    if destination_dir.exists():
        snapshot_path(destination_dir)
        shutil.rmtree(destination_dir)
    shutil.move(str(source_dir), str(destination_dir))
    register_created_path(destination_dir)
    _cleanup_empty_series_dir(old_parent, generated_root(pipeline))
    return destination_dir


def generate_derivatives(source_path: Path, series_slug: str, render_name: str, pipeline: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
    pipeline = pipeline or load_pipeline()
    prepared = prepare_source_image(source_path)
    intrinsic_width, intrinsic_height = prepared.size
    widths = sorted(set(int(width) for width in (pipeline.get("widths") or [480, 768, 1200, 1600, 2048])))
    target_widths = [width for width in widths if width < intrinsic_width]
    target_widths.append(intrinsic_width)
    target_widths = sorted(set(target_widths))

    jpg_quality = int(pipeline.get("jpg_quality", 86))
    webp_quality = int(pipeline.get("webp_quality", 82))
    output_dir = derivative_dir_for_work(series_slug, render_name, pipeline=pipeline)
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
        register_created_path(output_dir)
    base_name = render_name.replace("/", "-")
    source_mtime = source_path.stat().st_mtime_ns
    generated_files: list[str] = []

    for width in target_widths:
        if width == intrinsic_width:
            variant = prepared.copy()
        else:
            height = max(1, round(intrinsic_height * width / intrinsic_width))
            variant = prepared.resize((width, height), Image.Resampling.LANCZOS)

        jpg_path = output_dir / f"{base_name}-{width}.jpg"
        webp_path = output_dir / f"{base_name}-{width}.webp"
        if force or not jpg_path.exists() or jpg_path.stat().st_mtime_ns < source_mtime:
            jpg_existed = jpg_path.exists()
            if jpg_existed:
                snapshot_path(jpg_path)
            variant.save(jpg_path, format="JPEG", quality=jpg_quality, optimize=True, progressive=True)
            if not jpg_existed:
                register_created_path(jpg_path)
        if force or not webp_path.exists() or webp_path.stat().st_mtime_ns < source_mtime:
            webp_existed = webp_path.exists()
            if webp_existed:
                snapshot_path(webp_path)
            variant.save(webp_path, format="WEBP", quality=webp_quality, method=6)
            if not webp_existed:
                register_created_path(webp_path)
        generated_files.extend([
            jpg_path.relative_to(ROOT).as_posix(),
            webp_path.relative_to(ROOT).as_posix(),
        ])

    largest_width = target_widths[-1]
    src = (output_dir / f"{base_name}-{largest_width}.jpg").relative_to(ROOT).as_posix()
    return {
        "width": intrinsic_width,
        "height": intrinsic_height,
        "src": src,
        "responsiveBase": derivative_base_for_work(series_slug, render_name, pipeline=pipeline).relative_to(ROOT).as_posix(),
        "generatedFiles": generated_files,
    }


def safe_move_to_originals(source_path: Path, series_slug: str, destination_name: str, pipeline: dict[str, Any] | None = None) -> Path:
    pipeline = pipeline or load_pipeline()
    destination_dir = source_root(pipeline) / series_slug
    if not destination_dir.exists():
        destination_dir.mkdir(parents=True, exist_ok=True)
        register_created_path(destination_dir)
    destination = destination_dir / destination_name
    snapshot_path(source_path)
    if destination.exists():
        snapshot_path(destination)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = destination.with_name(f"{destination.stem}.replaced-{timestamp}{destination.suffix}")
        shutil.move(str(destination), str(backup))
        register_created_path(backup)
    shutil.move(str(source_path), str(destination))
    register_created_path(destination)
    return destination


def safe_copy_to_originals(source_path: Path, series_slug: str, destination_name: str, pipeline: dict[str, Any] | None = None) -> Path:
    pipeline = pipeline or load_pipeline()
    destination_dir = source_root(pipeline) / series_slug
    if not destination_dir.exists():
        destination_dir.mkdir(parents=True, exist_ok=True)
        register_created_path(destination_dir)
    destination = destination_dir / destination_name
    try:
        same_file = source_path.exists() and destination.exists() and source_path.resolve() == destination.resolve()
    except Exception:
        same_file = False
    if same_file:
        return destination
    if destination.exists():
        snapshot_path(destination)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = destination.with_name(f"{destination.stem}.replaced-{timestamp}{destination.suffix}")
        guarded_move(destination, backup, detail="backup replaced source original")
    guarded_copy2(source_path, destination, detail="copy source into originals")
    if not destination.exists():
        raise FileNotFoundError(f"Failed to copy image into originals: {destination}")
    return destination


def write_ingestion_log(entry: dict[str, Any], pipeline: dict[str, Any] | None = None) -> None:
    pipeline = pipeline or load_pipeline()
    root = manifest_root(pipeline)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "ingestion-log.json"
    payload: list[dict[str, Any]] = []
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                payload = []
        except json.JSONDecodeError:
            payload = []
    payload.append(entry)
    atomic_write_json(path, payload)
