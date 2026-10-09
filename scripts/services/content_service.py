from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class ContentService:
    """Small content-path service for future qt_backend extraction."""

    root: Path = ROOT

    @property
    def content_dir(self) -> Path:
        return self.root / "content"

    @property
    def works_dir(self) -> Path:
        return self.content_dir / "works"

    @property
    def series_dir(self) -> Path:
        return self.content_dir / "series"

    def work_files(self) -> list[Path]:
        return sorted(self.works_dir.glob("*.yaml")) if self.works_dir.exists() else []

    def series_files(self) -> list[Path]:
        return sorted(self.series_dir.glob("*.yaml")) if self.series_dir.exists() else []

    def load_yaml(self, path: Path) -> Any:
        if yaml is None:
            raise RuntimeError("PyYAML is required to load content YAML.")
        return yaml.safe_load(path.read_text(encoding="utf-8"))
