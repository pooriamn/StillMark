from __future__ import annotations

"""Archived Tk control-panel compatibility stub.

The active Stillmark control panel is the Qt implementation in
`scripts/control_panel.py`. The former Tk implementation was intentionally
removed from release packages because keeping a second 10k-line UI controller
in the active scripts folder caused confusion, slower scans, and higher risk of
editing the wrong implementation.
"""

ARCHIVED_MODULE = "control_panel_tk_legacy"


def main() -> None:
    raise RuntimeError(
        "The Tk control panel is archived. Use launch_control_panel.bat, "
        "launch_control_panel.sh, or python scripts/control_panel.py."
    )


if __name__ == "__main__":
    main()
