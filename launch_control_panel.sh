#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found on PATH. Install Python 3.11+ and retry." >&2
  exit 2
fi
python3 scripts/control_panel.py --doctor --launcher-check || {
  status=$?
  if [ "$status" -ge 2 ]; then
    echo "Control panel doctor found blocking issues. Fix the errors above before launching." >&2
    exit "$status"
  fi
}
exec python3 scripts/control_panel.py
