from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class PublishService:
    """Publish/release path service for future qt_backend extraction."""

    root: Path = ROOT

    @property
    def build_dir(self) -> Path:
        return self.root / ".stillmrk-build"

    @property
    def public_upload_dir(self) -> Path:
        return self.root / "public_upload"

    def release_report_path(self) -> Path:
        return self.build_dir / "meta" / "release-report.json"
