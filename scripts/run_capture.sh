#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
LINUX_COLLECTOR="${LINUX_COLLECTOR:-LinuxCollector.py}"
BROWSER_COLLECTOR="${BROWSER_COLLECTOR:-BrowserListener.py.pyi}"
DESKTOP_LOG="${DESKTOP_LOG:-events.jsonl}"
BROWSER_LOG="${BROWSER_LOG:-browser-events.jsonl}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python executable not found: $PYTHON_BIN" >&2
  exit 2
fi

if [[ ! -f "$LINUX_COLLECTOR" ]]; then
  echo "ERROR: Linux collector not found: $LINUX_COLLECTOR" >&2
  exit 3
fi

if [[ ! -f "$BROWSER_COLLECTOR" ]]; then
  echo "ERROR: Browser collector not found: $BROWSER_COLLECTOR" >&2
  exit 4
fi

cleanup() {
  trap - INT TERM EXIT
  echo
  echo "Stopping collectors..."

  if [[ -n "${LINUX_PID:-}" ]] && kill -0 "$LINUX_PID" 2>/dev/null; then
    kill -TERM "$LINUX_PID" 2>/dev/null || true
  fi

  if [[ -n "${BROWSER_PID:-}" ]] && kill -0 "$BROWSER_PID" 2>/dev/null; then
    kill -TERM "$BROWSER_PID" 2>/dev/null || true
  fi

  wait "${LINUX_PID:-}" 2>/dev/null || true
  wait "${BROWSER_PID:-}" 2>/dev/null || true

  echo "Collectors stopped."
  echo "Desktop log: $DESKTOP_LOG"
  echo "Browser log: $BROWSER_LOG"
}

trap cleanup INT TERM EXIT

rm -f "$DESKTOP_LOG" "$BROWSER_LOG"

echo "=== TraineeAI capture ==="
echo "Python            : $PYTHON_BIN"
echo "Linux collector   : $LINUX_COLLECTOR"
echo "Browser collector : $BROWSER_COLLECTOR"
echo "Desktop log       : $DESKTOP_LOG"
echo "Browser log       : $BROWSER_LOG"
echo
echo "Make sure Chrome/Chromium was started with CDP enabled, e.g.:"
echo '  chromium --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="$HOME/.chrome-cdp-profile"'
echo
echo "Press Ctrl+C when the test workflow is finished."
echo

"$PYTHON_BIN" "$LINUX_COLLECTOR" &
LINUX_PID=$!

"$PYTHON_BIN" "$BROWSER_COLLECTOR" &
BROWSER_PID=$!

sleep 1

if ! kill -0 "$LINUX_PID" 2>/dev/null; then
  echo "ERROR: Linux collector exited immediately." >&2
  exit 5
fi

if ! kill -0 "$BROWSER_PID" 2>/dev/null; then
  echo "ERROR: Browser collector exited immediately." >&2
  exit 6
fi

echo "Linux collector PID : $LINUX_PID"
echo "Browser collector PID: $BROWSER_PID"
echo "Capture is running..."

while true; do
  if ! kill -0 "$LINUX_PID" 2>/dev/null; then
    echo "ERROR: Linux collector stopped unexpectedly." >&2
    exit 7
  fi

  if ! kill -0 "$BROWSER_PID" 2>/dev/null; then
    echo "ERROR: Browser collector stopped unexpectedly." >&2
    exit 8
  fi

  sleep 1
done
