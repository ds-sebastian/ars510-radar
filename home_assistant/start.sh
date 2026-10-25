#!/usr/bin/env bash
# Starts the Home Assistant bridge with openpilot's Python and cereal; /data/continue.sh calls it on boot
# (ha_bridge.py --install-autostart). Settings come from /data/ars510_ha.json, the log goes to /tmp/ars510_ha.log.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=/usr/local/venv/bin/python
[ -x "$PY" ] || PY=python3
export PYTHONPATH=/data/openpilot
exec nohup "$PY" "$DIR/ha_bridge.py" --config /data/ars510_ha.json > /tmp/ars510_ha.log 2>&1
