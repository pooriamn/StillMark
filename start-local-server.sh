#!/usr/bin/env bash
# Build the site and preview it at http://127.0.0.1:8000/
set -euo pipefail
cd "$(dirname "$0")"
python3 preview_server.py "$@"
