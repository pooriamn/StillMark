from __future__ import annotations

"""Runtime helpers for the Qt control panel.

This module deliberately stays narrow: shell grouping, fixed layout-density tokens, and
performance-budget policy for the local control panel only.
"""

from control_panel_design import CONTROL_PANEL_DENSITY_PROFILES
from control_panel_tab_registry import TAB_GROUP_BY_LABEL, tab_group

CONTROL_PANEL_NAV_GROUPS: dict[str, str] = dict(TAB_GROUP_BY_LABEL)
DENSITY_PROFILES: dict[str, dict[str, int]] = CONTROL_PANEL_DENSITY_PROFILES

try:
    from control_panel_performance_budgets import PERFORMANCE_BUDGETS_MS, budget_for
except Exception:  # pragma: no cover
    PERFORMANCE_BUDGETS_MS: dict[str, int] = {
        "startup": 2500,
        "cached dashboard refresh": 200,
        "dashboard refresh": 500,
        "works filter": 250,
        "works refresh": 1200,
    }
    def budget_for(label: str) -> int | None:  # type: ignore[no-redef]
        return PERFORMANCE_BUDGETS_MS.get(str(label or "").lower())



def performance_budget_status(label: str, elapsed_seconds: float) -> str:
    budget = budget_for(str(label or ""))
    if budget is None:
        return "unbudgeted"
    return "ok" if elapsed_seconds * 1000 <= budget else "slow"
