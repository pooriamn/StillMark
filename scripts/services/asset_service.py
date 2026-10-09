from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class AssetService:
    """Asset-path service for source/derivative workflows."""

    root: Path = ROOT

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    @property
    def build_meta_dir(self) -> Path:
        return self.root / ".stillmrk-build" / "meta"

    def public_image_dirs(self) -> list[Path]:
        return [path for path in [self.assets_dir / "images", self.root / "public_upload" / "assets" / "images"] if path.exists()]
