#!/usr/bin/env python3
from __future__ import annotations

"""Static regression checks for Works gallery card stability.

These checks stay non-GUI so they can run in environments without PySide6.
They prove the hotfix contract that caused the user-visible instability:
resize events must not rebuild the gallery immediately, gallery rebuilds must be
signature-gated, stale thumbnail failures must be generation-guarded, and card
geometry must stay vertically stable while thumbnails arrive.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL_PANEL = ROOT / "scripts" / "control_panel.py"
COMPONENTS = ROOT / "scripts" / "control_panel_components.py"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    panel = CONTROL_PANEL.read_text(encoding="utf-8")
    components = COMPONENTS.read_text(encoding="utf-8")

    resize_block = panel.split("def _gallery_resize(event):", 1)[1].split("self.work_gallery_scroll.resizeEvent", 1)[0]
    require("_schedule_work_gallery_reflow()" in resize_block, "resizeEvent must debounce gallery reflow")
    require("_populate_work_gallery" not in resize_block, "resizeEvent must not directly rebuild gallery cards")

    require("_gallery_last_layout_signature" in panel, "gallery must track a layout/content signature")
    require("signature == getattr(self, \"_gallery_last_layout_signature\"" in panel, "gallery rebuild must be signature-gated")
    require("def _populate_work_gallery(self, works: list[dict[str, Any]], *, force: bool = False)" in panel, "gallery populate must support forced reflow only when needed")
    require("_work_gallery_column_count" in panel and "available_width // 248" in panel, "column count must use a stable threshold")
    require("gen=queued_generation" in panel, "thumbnail error callbacks must carry generation")
    require("generation is not None" in panel and "_gallery_thumbnail_generation" in panel, "stale thumbnail failures must be ignored")
    require("animation.stop()" in panel, "skeleton animations must be stopped before card deletion")
    require("gallery_view and not getattr(self, \"_gallery_cards_by_work_id\"" in panel, "refresh must not show skeletons over existing cards")

    require("self.setMaximumHeight(252)" in components, "work cards must have a fixed maximum height")
    require("self._image_label.setFixedHeight(150)" in components, "thumbnail label must have a fixed height")
    require("self._title_label.setWordWrap(False)" in components, "title wrapping must not change card height")
    require("self._series_label.setWordWrap(False)" in components, "series wrapping must not change card height")
    require("max(130, self._image_label.height())" in components, "pixmap scaling must use the actual stable label height")

    print("control_panel_work_gallery_stability_tests: OK")


if __name__ == "__main__":
    main()
