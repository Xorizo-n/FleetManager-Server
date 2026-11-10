#!/bin/sh
# Bootstrap only. Application releases never replace a running privileged updater.
set -eu
test "$(id -u)" = 0
cd "$(dirname "$0")/.."
command -v python3 >/dev/null
command -v docker >/dev/null
command -v curl >/dev/null
docker compose version >/dev/null
install -d -m 755 /opt/fleet-updater/updater /run/fleet-updater
install -d -m 700 /var/lib/fleet-updater
install -m 644 updater/*.py /opt/fleet-updater/updater/
install -m 644 updater/fleet-updater.service /etc/systemd/system/fleet-updater.service
systemctl daemon-reload
systemctl enable --now fleet-updater
