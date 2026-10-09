# Control-panel tab migration map

Phase 14 establishes a conservative split boundary for the monolithic Qt control panel without rewriting the live website or changing public content.

| Tab | Boundary module | Current state | Compatibility guarantee | Next safe extraction |
| --- | --- | --- | --- | --- |
| Dashboard | `dashboard.py` | Delegates to existing builder | Same `build_dashboard_tab()` entry point | Move readiness/next-action rendering |
| Works | `works.py` | Controller-delegated | Same `build_works_tab()`, same selection/save signals | Move work list model, filters, and editor state |
| Series | `series.py` | Controller-delegated | Same `build_series_tab()` and sequence handlers | Move sequence board and cover logic |
| Pages | `pages.py` | Controller-delegated | Same `build_pages_tab()` and builder/raw editor bridge | Move page block editor |
| Publish | `publish.py` | Delegates to existing builder | Same `build_publish_tab()` and task queue | Move stepper/release checks |
| Studio | `control_panel.py` | Legacy shared tab | Kept in shell because it shares publish/asset workflows | Extract after Works + Publish are stable |

`registry.py` now records these boundaries as data. The shell uses that registry to build tab specs, so future extraction can be tested by replacing one controller at a time rather than editing global navigation code.
