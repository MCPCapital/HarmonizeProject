#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi

source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
unit=/etc/systemd/system/harmonize.service
if [[ ! -f "$unit" ]] || ! cmp -s "$source_root/deploy/harmonize.service" "$unit"; then
  echo "Refusing to remove an unrecognized Harmonize unit." >&2
  exit 2
fi
account=$(getent passwd harmonize || true)
group=$(getent group harmonize || true)
[[ "$account" == harmonize:*:/var/lib/harmonize:/usr/sbin/nologin ]] || {
  echo "Refusing to remove an unrecognized harmonize account." >&2
  exit 2
}
[[ "$group" == harmonize:* ]] || {
  echo "Refusing to remove an unrecognized harmonize group." >&2
  exit 2
}

systemctl disable --now harmonize.service
rm -f /etc/systemd/system/harmonize.service
rm -rf /opt/harmonize /etc/harmonize /var/lib/harmonize /run/harmonize
userdel harmonize
systemctl daemon-reload
systemctl reset-failed harmonize.service || true
