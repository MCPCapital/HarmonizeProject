#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi
if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /path/to/client.json" >&2
  exit 2
fi

source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
credentials=$(readlink -f -- "$1")
capture=/dev/v4l/by-id/usb-MACROSILICON_WARRKY_USB_3.0_62196249-video-index0

[[ -f "$credentials" ]] || { echo "Credential file not found." >&2; exit 2; }
[[ -e "$capture" ]] || { echo "Stable capture device not found: $capture" >&2; exit 2; }
for target in /opt/harmonize /etc/harmonize /etc/systemd/system/harmonize.service; do
  [[ ! -e "$target" ]] || {
    echo "Refusing to replace existing path: $target" >&2
    exit 2
  }
done
if getent passwd harmonize >/dev/null || getent group harmonize >/dev/null; then
  echo "Refusing to reuse existing harmonize account or group." >&2
  exit 2
fi

useradd --system --user-group --home-dir /var/lib/harmonize \
  --shell /usr/sbin/nologin harmonize
usermod --append --groups video harmonize
install -d -o root -g root -m 0755 /opt/harmonize/app /opt/harmonize/venv
install -d -o root -g harmonize -m 0750 /etc/harmonize

rsync -a --delete \
  --exclude=.git --exclude=client.json --exclude=run \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='*.local.toml' \
  "$source_root/" /opt/harmonize/app/
rsync -a --delete /home/pi/harmonize_env/ /opt/harmonize/venv/
chown -R root:root /opt/harmonize
chmod -R u=rwX,go=rX /opt/harmonize

install -o root -g harmonize -m 0640 \
  "$source_root/deploy/harmonize.toml" /etc/harmonize/harmonize.toml
install -o harmonize -g harmonize -m 0600 \
  "$credentials" /etc/harmonize/client.json
install -o root -g root -m 0644 \
  "$source_root/deploy/harmonize.service" /etc/systemd/system/harmonize.service

systemctl daemon-reload
systemctl enable --now harmonize.service
