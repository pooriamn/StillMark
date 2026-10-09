# Works Preview Selection Hotfix

## Problem
In the Works tab, the selected image preview could blink repeatedly and then jump back to a previously selected work after the user clicked a different work.

## Root cause
The deferred visible-asset-health checker was running shortly after the Works gallery loaded. In gallery mode, it reused the normal save-row patch path. That path owns selection and, when the hidden legacy tree did not contain the row, it could call a Works refresh and `select_work(work_id)` from a background health result.

A second related issue was that async Works refresh results used the work selection captured when the refresh was queued. If the user selected a different work before the async result returned, the older result could still try to restore the older selection.

## What changed
- Deferred asset-health row patches now update only model/payload/status metadata.
- Background asset-health updates no longer call the save-row patcher.
- Background asset-health updates no longer refresh the Works list.
- Background asset-health updates no longer call `select_work()`.
- Async Works refresh apply now prefers the live current selection over the stale selection captured at query start.
- Gallery card metadata/tooltips can be patched without rebuilding the card grid.

## Files changed
- `scripts/control_panel.py`

## Expected effect
- Selecting a different work should keep that work selected.
- The right-side image preview should stop blinking from the deferred health scan.
- Works gallery thumbnails/status can still update in the background without stealing focus or selection.
- No website content or website UI was changed.

## Validation
- Python compile check passed.
- Batch D regression test passed.
- Backend regression contracts passed.
- Behavior regression checks passed.
- Preview pipeline regression checks passed.
- Work gallery stability checks passed.
- Works performance regression checks passed.
- General control-panel regression checks passed.
- Control-panel doctor: OK, 0 errors. PySide6 warning is environment-only in this container.
