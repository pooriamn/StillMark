#!/usr/bin/env bash
set -e
python3 build_site.py
printf '
Upload the contents of ./public_upload to your host.
'
