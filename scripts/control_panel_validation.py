from __future__ import annotations

"""Compatibility stub for the archived Tkinter module `control_panel_validation.py`.

The active Stillmark control panel is Qt-only. The original Tkinter implementation
was moved to `scripts/_legacy_tk/control_panel_validation.py` so accidental imports fail clearly
instead of silently pulling legacy UI code into the modern panel.
"""

ARCHIVED_MODULE = "scripts/_legacy_tk/control_panel_validation.py"


def __getattr__(name: str):
    raise RuntimeError(
        f"Legacy Tkinter module '{name}' is archived at {ARCHIVED_MODULE} and is not part of the active Qt control panel."
    )
