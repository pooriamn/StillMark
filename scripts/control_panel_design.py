from __future__ import annotations

"""Design tokens and UI policy helpers for the Stillmark Qt control panel.

This module intentionally contains no public-site styling. It is only for the
local control panel and gives future UI work one stable place for spacing,
density, severity, and shell-behaviour decisions.
"""

CONTROL_PANEL_THEME: dict[str, str] = {
    # Typography tokens used by deterministic QSS construction.
    "font_family": "Inter, Segoe UI, Arial, sans-serif",
    "font_size": "13px",
    # Premium depth system: base -> surface -> elevated/card.
    "bg_primary": "#050a0f",
    "bg_depth_1": "#050a0f",
    "bg_surface": "#0a1420",
    "bg_depth_2": "#0a1420",
    "bg_elevated": "#0f1e2e",
    "bg_depth_3": "#0f1e2e",
    "bg_card": "#0c1926",
    "bg_panel": "#0a1420",
    "bg_dialog": "#050a0f",
    "bg_toolbar": "#050a0f",
    "bg_input": "#0b1723",
    "bg_button": "#102236",
    "bg_button_hover": "#173654",
    "bg_button_pressed": "#1f4569",
    "text_primary": "#eaf0f7",
    "text_strong": "#f7fbff",
    "text_muted": "#94a8bf",
    "text_header": "#afc0d3",
    "border": "#24384d",
    "border_soft": "#1b2c3e",
    "border_tabs": "#24384d",
    "border_button": "#2a4058",
    "accent": "#3d8cff",
    "accent_soft": "rgba(61, 140, 255, 0.18)",
    "accent_green": "#3dd68c",
    "focus_ring": "#6aaeff",
    "border_focus": "2px solid #3d8cff",
    "success": "#3dd68c",
    "warning": "#ffd166",
    "danger": "#ff6f7d",
    "info": "#66c7f4",
    "radius_input": "8px",
    "radius_card": "12px",
    "radius_pill": "99px",
}

CONTROL_PANEL_DENSITY_PROFILES: dict[str, dict[str, int]] = {
    "Compact": {"font": 12, "button_v": 6, "button_h": 10, "row": 24, "nav_v": 9, "side_nav": 212, "thumb": 44, "weight_label": 500, "weight_heading": 700, "weight_body": 400},
    "Comfortable": {"font": 13, "button_v": 8, "button_h": 12, "row": 30, "nav_v": 12, "side_nav": 238, "thumb": 52, "weight_label": 500, "weight_heading": 700, "weight_body": 400},
    "Focus": {"font": 14, "button_v": 10, "button_h": 14, "row": 36, "nav_v": 15, "side_nav": 260, "thumb": 60, "weight_label": 500, "weight_heading": 700, "weight_body": 400},
    "Review": {"font": 14, "button_v": 11, "button_h": 16, "row": 42, "nav_v": 16, "side_nav": 286, "thumb": 76, "weight_label": 500, "weight_heading": 700, "weight_body": 400},
}


STATUS_ACCENTS: dict[str, str] = {
    "error": CONTROL_PANEL_THEME["danger"],
    "failed": CONTROL_PANEL_THEME["danger"],
    "fail": CONTROL_PANEL_THEME["danger"],
    "blocked": CONTROL_PANEL_THEME["danger"],
    "missing": CONTROL_PANEL_THEME["danger"],
    "warning": CONTROL_PANEL_THEME["warning"],
    "warn": CONTROL_PANEL_THEME["warning"],
    "needs attention": CONTROL_PANEL_THEME["warning"],
    "watch": CONTROL_PANEL_THEME["warning"],
    "ok": CONTROL_PANEL_THEME["success"],
    "success": CONTROL_PANEL_THEME["success"],
    "ready": CONTROL_PANEL_THEME["success"],
    "clean": CONTROL_PANEL_THEME["success"],
    "info": CONTROL_PANEL_THEME["info"],
}


def normalize_density_mode(value: str | None) -> str:
    text = str(value or "Comfortable").strip().title()
    return text if text in CONTROL_PANEL_DENSITY_PROFILES else "Comfortable"


def density_profile(value: str | None) -> dict[str, int]:
    return CONTROL_PANEL_DENSITY_PROFILES[normalize_density_mode(value)]


def status_accent(status: str | None) -> str:
    return STATUS_ACCENTS.get(str(status or "info").strip().lower(), CONTROL_PANEL_THEME["info"])
