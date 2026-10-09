#!/usr/bin/env bash
# Build the site into dist/. Upload the contents of dist/ to the host,
# or push to GitHub and let the deploy workflow publish it.
set -euo pipefail
cd "$(dirname "$0")"
python3 build_site.py
printf "\nUpload the contents of ./dist to your host.\n"
