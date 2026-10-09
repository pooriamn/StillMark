from __future__ import annotations

"""Lightweight tab registry for the Qt control-panel shell.

The registry is deliberately small. It does not change page routing or public
site output. It gives side navigation, commands, and future plug-in style tabs
one common source of truth.
"""

TAB_REGISTRY: tuple[dict[str, str], ...] = (
    {"key": "dashboard", "label": "Dashboard", "group": "Overview", "purpose": "Live cockpit for readiness, tasks, and next actions."},
    {"key": "works", "label": "Works", "group": "Content", "purpose": "Create, review, filter, and repair individual photographs."},
    {"key": "series", "label": "Series", "group": "Content", "purpose": "Sequence and assess series-level storytelling health."},
    {"key": "relationships", "label": "Relationships", "group": "Curation", "purpose": "Understand links between works, series, pages, and features."},
    {"key": "pages", "label": "Content Builder", "group": "Content", "purpose": "Edit structured page content without changing public templates."},
    {"key": "authority", "label": "Content Authority", "group": "Authority", "purpose": "Manage controlled editorial and authority metadata."},
    {"key": "validation", "label": "Validation", "group": "Quality", "purpose": "Audit blocking and practical content issues."},
    {"key": "studio", "label": "Studio", "group": "Advanced Tools", "purpose": "Advanced preview-led review of pages, image sequencing, validation blockers, and source truth."},
    {"key": "publish", "label": "Publish", "group": "Release", "purpose": "Guided release workflow: validate, build, and package with blockers separated from advisories."},
)

TAB_BY_LABEL: dict[str, dict[str, str]] = {row["label"]: row for row in TAB_REGISTRY}
TAB_GROUP_BY_LABEL: dict[str, str] = {row["label"]: row["group"] for row in TAB_REGISTRY}


def tab_group(label: str) -> str:
    clean = str(label or "").replace("✓", "").replace("●", "").strip()
    return TAB_GROUP_BY_LABEL.get(clean, "Panel")


def tab_purpose(label: str) -> str:
    clean = str(label or "").replace("✓", "").replace("●", "").strip()
    return TAB_BY_LABEL.get(clean, {}).get("purpose", clean)
