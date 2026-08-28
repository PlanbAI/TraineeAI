#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CHROME_BIN="${CHROME_BIN:-}"
CDP_PORT="${CDP_PORT:-9222}"
CDP_PROFILE_DIR="${CDP_PROFILE_DIR:-$HOME/.traineeai-cdp-profile}"
DURATION_SEC="${DURATION_SEC:-0}"
COLLECTOR="$ROOT_DIR/collectors/BrowserCollector.py"
CDP_URL="http://127.0.0.1:${CDP_PORT}/json/version"
CHROME_PID=""
COLLECTOR_PID=""

find_chrome() {
  if [[ -n "$CHROME_BIN" ]]; then
    [[ -x "$CHROME_BIN" ]] && printf '%s\n' "$CHROME_BIN" && return 0
    command -v "$CHROME_BIN" 2>/dev/null && return 0
    echo "ERROR: CHROME_BIN is not executable: $CHROME_BIN" >&2
    return 1
  fi

  local candidate
  for candidate in chromium chromium-browser google-chrome google-chrome-stable chrome; do
    command -v "$candidate" 2>/dev/null && return 0
  done
  return 1
}

cdp_ready() {
  "$PYTHON_BIN" - <<PY >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("$CDP_URL", timeout=1).read()
PY
}

cleanup() {
  if [[ -n "$COLLECTOR_PID" ]] && kill -0 "$COLLECTOR_PID" 2>/dev/null; then
    kill "$COLLECTOR_PID" 2>/dev/null || true
  fi
  if [[ -n "$CHROME_PID" ]] && kill -0 "$CHROME_PID" 2>/dev/null; then
    kill "$CHROME_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

export CDP_HOST="127.0.0.1"
export CDP_PORT

[[ -f "$COLLECTOR" ]] || { echo "ERROR: Browser collector not found: $COLLECTOR" >&2; exit 2; }
command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "ERROR: Python not found: $PYTHON_BIN" >&2; exit 3; }
"$PYTHON_BIN" -c 'import requests, websocket' || { echo "ERROR: requests and websocket-client are required." >&2; exit 4; }

if ! cdp_ready; then
  CHROME_EXEC="$(find_chrome)" || { echo "ERROR: Chrome/Chromium was not found." >&2; exit 5; }
  mkdir -p "$CDP_PROFILE_DIR"
  "$CHROME_EXEC" \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port="$CDP_PORT" \
    --user-data-dir="$CDP_PROFILE_DIR" \
    --no-first-run \
    --no-default-browser-check \
    >/tmp/traineeai-browser.log 2>&1 &
  CHROME_PID=$!

  for _ in {1..40}; do
    cdp_ready && break
    sleep 0.25
  done
  cdp_ready || { echo "ERROR: CDP is unavailable at $CDP_URL" >&2; exit 6; }
fi

echo "Browser collector: $COLLECTOR"
echo "CDP endpoint: $CDP_URL"
echo "Events file: $ROOT_DIR/browser-events.jsonl"
cd "$ROOT_DIR"
"$PYTHON_BIN" "$COLLECTOR" &
COLLECTOR_PID=$!
sleep 1
kill -0 "$COLLECTOR_PID" 2>/dev/null || { echo "ERROR: Browser collector exited immediately." >&2; exit 7; }

if [[ "$DURATION_SEC" -gt 0 ]]; then
  echo "Collector will stop after $DURATION_SEC second(s)."
  sleep "$DURATION_SEC"
else
  echo "Collector is running. Press Ctrl+C to stop."
  wait "$COLLECTOR_PID"
fi
