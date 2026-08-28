#!/usr/bin/env bash
set -euo pipefail

COLLECTOR="${COLLECTOR:-$HOME/LinuxCollector.py}"

if [[ ! -f "$COLLECTOR" ]]; then
  echo "Collector not found: $COLLECTOR" >&2
  exit 1
fi

export DISPLAY="${DISPLAY:-:0}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

cd "$HOME"
echo "Writing events to: $HOME/events.jsonl"
exec python3 "$COLLECTOR"
