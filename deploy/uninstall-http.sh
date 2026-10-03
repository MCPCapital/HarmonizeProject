#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi
if [[ $# -ne 0 ]]; then
  echo "Usage: $0" >&2
  exit 2
fi

source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
unit=/etc/systemd/system/harmonize-http.service
installed_tool=/opt/harmonize/app/tools/harmonize_http.py
installed_doc=/opt/harmonize/app/docs/milestone-8-http.md

if [[ ! -f "$unit" ]] || \
   ! cmp -s "$source_root/deploy/harmonize-http.service" "$unit"; then
  echo "Refusing to remove an unrecognized Harmonize HTTP unit." >&2
  exit 2
fi
if [[ ! -f "$installed_tool" ]] || \
   ! cmp -s "$source_root/tools/harmonize_http.py" "$installed_tool"; then
  echo "Refusing to remove an unrecognized Harmonize HTTP tool." >&2
  exit 2
fi
if [[ ! -f "$installed_doc" ]] || \
   ! cmp -s "$source_root/docs/milestone-8-http.md" "$installed_doc"; then
  echo "Refusing to remove unrecognized Harmonize HTTP documentation." >&2
  exit 2
fi

systemctl disable --now harmonize-http.service
rm -f "$unit" "$installed_tool" "$installed_doc"
systemctl daemon-reload
systemctl reset-failed harmonize-http.service || true
