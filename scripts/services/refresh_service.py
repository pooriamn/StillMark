from __future__ import annotations

"""Dependency-aware refresh scopes for the Qt control panel.

The UI still owns actual widget refresh methods. This service owns the mapping
from content-change events to affected panels so the mapping is not copied into
random save handlers.
"""

from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterable

REFRESH_DEPENDENCIES: dict[str, set[str]] = {
    "work_saved": {"works", "series", "relationships", "dashboard", "validation", "studio", "publish"},
    "work_asset_changed": {"works", "dashboard", "validation", "studio", "publish"},
    "work_quick_state": {"dashboard", "validation", "studio", "publish"},
    "series_saved": {"series", "works", "relationships", "dashboard", "validation", "studio"},
    "page_saved": {"pages", "dashboard", "validation"},
    "authority_saved": {"authority", "dashboard", "validation"},
    "relationships_saved": {"relationships", "dashboard", "validation"},
    "validation_changed": {"validation", "dashboard"},
    "studio_changed": {"studio", "dashboard"},
    "publish_changed": {"publish", "dashboard", "validation"},
    "dashboard": {"dashboard"},
    "works": {"works", "series", "relationships", "dashboard", "validation", "studio", "publish"},
    "series": {"series", "works", "relationships", "dashboard", "validation", "studio"},
    "relationships": {"relationships", "dashboard", "validation"},
    "pages": {"pages", "dashboard", "validation"},
    "authority": {"authority", "dashboard", "validation"},
    "validation": {"validation", "dashboard"},
    "studio": {"studio", "dashboard"},
    "publish": {"publish", "dashboard", "validation"},
}

ORDERED_SCOPES = ["works", "series", "relationships", "pages", "authority", "validation", "dashboard", "studio", "publish"]


@dataclass(frozen=True, slots=True)
class RefreshEvent:
    name: str
    reason: str = ""
    force: bool = False


@dataclass(slots=True)
class RefreshCoordinator:
    pending: set[str] = field(default_factory=set)
    last_request_at: float = 0.0
    last_elapsed_ms: dict[str, float] = field(default_factory=dict)

    def expand(self, scope: Iterable[str] | None = None, *, event: str | None = None) -> set[str]:
        requested: set[str] = set()
        if event:
            requested.update(REFRESH_DEPENDENCIES.get(str(event), {str(event)}))
        if scope is None and not requested:
            requested.update({"works", "series", "pages", "studio", "publish", "dashboard"})
        elif scope is not None:
            requested.update(str(item) for item in scope if str(item).strip())
        expanded = set(requested)
        for item in list(requested):
            expanded.update(REFRESH_DEPENDENCIES.get(item, {item}))
        return {item for item in expanded if item}

    def ordered(self, scopes: Iterable[str]) -> list[str]:
        scope_set = set(scopes)
        ordered = [item for item in ORDERED_SCOPES if item in scope_set]
        ordered.extend(sorted(scope_set.difference(ordered)))
        return ordered

    def remember_dirty(self, scopes: Iterable[str]) -> set[str]:
        expanded = self.expand(scopes)
        self.pending.update(expanded)
        self.last_request_at = perf_counter()
        return expanded

    def clear(self, scope: str) -> None:
        self.pending.discard(str(scope or ""))

    def record_elapsed(self, label: str, elapsed_ms: float) -> None:
        self.last_elapsed_ms[str(label or "refresh")] = float(elapsed_ms)
