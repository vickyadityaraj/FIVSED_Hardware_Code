#!/bin/sh
set -eu
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
sudo install -m 0755 "$ROOT_DIR/pi-appliance/fivsed-reboot-button.py" /usr/local/bin/fivsed-reboot-button.py
SERVICE_TMP=$(mktemp)
trap 'rm -f "$SERVICE_TMP"' EXIT
sed "s#/home/fivsed/FIVSED_GUI#${ROOT_DIR}#g" "$ROOT_DIR/pi-appliance/fivsed-reboot-button.service" > "$SERVICE_TMP"
sudo install -m 0644 "$SERVICE_TMP" /etc/systemd/system/fivsed-reboot-button.service
sudo systemctl daemon-reload
sudo systemctl enable --now fivsed-reboot-button.service
printf '%s\n' "FIVSED GPIO13 reboot button service installed and enabled."
