#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
CHROME_BIN="${CHROME_BIN:-}"
CDP_PORT="${CDP_PORT:-9222}"
CDP_PROFILE_DIR="${CDP_PROFILE_DIR:-$HOME/.chrome-cdp-profile}"
OUTPUT_DIR="${OUTPUT_DIR:-test-output}"
DESKTOP_LOG="${DESKTOP_LOG:-events.jsonl}"
BROWSER_LOG="${BROWSER_LOG:-browser-events.jsonl}"
CLEAR_LOGS="${CLEAR_LOGS:-1}"

CHROME_PID=""
LINUX_COLLECTOR_PID=""
BROWSER_COLLECTOR_PID=""

find_chrome() {
  if [[ -n "$CHROME_BIN" ]]; then
    if command -v "$CHROME_BIN" >/dev/null 2>&1; then
      command -v "$CHROME_BIN"
      return 0
    fi
    if [[ -x "$CHROME_BIN" ]]; then
      printf '%s\n' "$CHROME_BIN"
      return 0
    fi
    echo "ERROR: CHROME_BIN is set but not executable/found: $CHROME_BIN" >&2
    return 1
  fi

  local candidate
  for candidate in chromium chromium-browser google-chrome google-chrome-stable chrome; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done

  return 1
}

wait_for_cdp() {
  local attempts=40
  local i
  for ((i=1; i<=attempts; i++)); do
    if "$PYTHON_BIN" - <<PY >/dev/null 2>&1
import urllib.request
urllib.request.urlopen("http://127.0.0.1:${CDP_PORT}/json/version", timeout=0.5).read()
PY
    then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

stop_pid() {
  local pid="${1:-}"
  local name="${2:-process}"
  if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
    echo "[*] Stopping $name (pid=$pid)"
    kill "$pid" >/dev/null 2>&1 || true
    for _ in {1..20}; do
      if ! kill -0 "$pid" >/dev/null 2>&1; then
        return 0
      fi
      sleep 0.1
    done
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
}

cleanup() {
  set +e
  stop_pid "$BROWSER_COLLECTOR_PID" "browser collector"
  stop_pid "$LINUX_COLLECTOR_PID" "linux collector"
  stop_pid "$CHROME_PID" "CDP browser"
}

trap cleanup EXIT INT TERM

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python executable not found: $PYTHON_BIN" >&2
  echo "Tip: PYTHON_BIN=.venv/bin/python ./scripts/run_full_test.sh" >&2
  exit 2
fi

if [[ ! -f collectors/LinuxCollector.py ]]; then
  echo "ERROR: collectors/LinuxCollector.py not found" >&2
  exit 3
fi

if [[ ! -f collectors/BrowserCollector.py ]]; then
  echo "ERROR: collectors/BrowserCollector.py not found" >&2
  exit 4
fi

if [[ "$CLEAR_LOGS" == "1" ]]; then
  rm -f "$DESKTOP_LOG" "$BROWSER_LOG"
fi
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

CHROME_EXEC="$(find_chrome || true)"
if [[ -z "$CHROME_EXEC" ]]; then
  echo "ERROR: Could not find Chrome/Chromium." >&2
  echo "Set CHROME_BIN, for example:" >&2
  echo "  CHROME_BIN=/usr/bin/chromium ./scripts/run_full_test.sh" >&2
  exit 5
fi

echo "=== TraineeAI full test ==="
echo "Python        : $PYTHON_BIN"
echo "Browser       : $CHROME_EXEC"
echo "CDP port      : $CDP_PORT"
echo "CDP profile   : $CDP_PROFILE_DIR"
echo "Desktop log   : $DESKTOP_LOG"
echo "Browser log   : $BROWSER_LOG"
echo "Output dir    : $OUTPUT_DIR"
echo

mkdir -p "$CDP_PROFILE_DIR"

# Launch a separate browser instance so we do not interfere with the user's normal profile.
"$CHROME_EXEC" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="$CDP_PORT" \
  --user-data-dir="$CDP_PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check \
  >/tmp/traineeai-chrome.log 2>&1 &
CHROME_PID=$!

echo "[*] Browser started (pid=$CHROME_PID)"

if ! wait_for_cdp; then
  echo "ERROR: Browser started but CDP did not become available on 127.0.0.1:$CDP_PORT" >&2
  echo "Browser log: /tmp/traineeai-chrome.log" >&2
  exit 6
fi

echo "[*] CDP is ready"

"$PYTHON_BIN" collectors/LinuxCollector.py >"$OUTPUT_DIR/linux-collector.stdout.log" 2>"$OUTPUT_DIR/linux-collector.stderr.log" &
LINUX_COLLECTOR_PID=$!
echo "[*] Linux collector started (pid=$LINUX_COLLECTOR_PID)"

"$PYTHON_BIN" collectors/BrowserCollector.py >"$OUTPUT_DIR/browser-collector.stdout.log" 2>"$OUTPUT_DIR/browser-collector.stderr.log" &
BROWSER_COLLECTOR_PID=$!
echo "[*] Browser collector started (pid=$BROWSER_COLLECTOR_PID)"

sleep 1

if ! kill -0 "$LINUX_COLLECTOR_PID" >/dev/null 2>&1; then
  echo "ERROR: Linux collector exited immediately." >&2
  echo "See: $OUTPUT_DIR/linux-collector.stderr.log" >&2
  exit 7
fi

if ! kill -0 "$BROWSER_COLLECTOR_PID" >/dev/null 2>&1; then
  echo "ERROR: Browser collector exited immediately." >&2
  echo "See: $OUTPUT_DIR/browser-collector.stderr.log" >&2
  exit 8
fi

echo
echo "Collectors are running."
echo "Perform the workflow you want to record in the CDP browser window."
echo "Desktop activity outside the browser is also being collected."
echo
echo "Press ENTER when the test workflow is finished..."
read -r _

echo
echo "[*] Capture finished; stopping collectors..."
stop_pid "$BROWSER_COLLECTOR_PID" "browser collector"
BROWSER_COLLECTOR_PID=""
stop_pid "$LINUX_COLLECTOR_PID" "linux collector"
LINUX_COLLECTOR_PID=""

if [[ ! -s "$DESKTOP_LOG" ]]; then
  echo "WARNING: desktop log is missing or empty: $DESKTOP_LOG" >&2
fi
if [[ ! -s "$BROWSER_LOG" ]]; then
  echo "WARNING: browser log is missing or empty: $BROWSER_LOG" >&2
fi

if [[ ! -s "$DESKTOP_LOG" && ! -s "$BROWSER_LOG" ]]; then
  echo "ERROR: both collectors produced no events; analysis cannot continue." >&2
  exit 9
fi

echo "[*] Running analysis pipeline..."

"$PYTHON_BIN" -m analysis.analyze \
  --desktop "$DESKTOP_LOG" \
  --browser "$BROWSER_LOG" \
  --output "$OUTPUT_DIR/episodes.jsonl" \
  --timeline-output "$OUTPUT_DIR/timeline.jsonl" \
  --llm-payload-output "$OUTPUT_DIR/llm-payloads.jsonl"

count_lines() {
  local file="$1"
  if [[ -f "$file" ]]; then
    wc -l < "$file" | tr -d ' '
  else
    echo 0
  fi
}

echo
echo "=== Completed ==="
echo "Desktop events : $(count_lines "$DESKTOP_LOG")"
echo "Browser events : $(count_lines "$BROWSER_LOG")"
echo "Timeline events: $(count_lines "$OUTPUT_DIR/timeline.jsonl")"
echo "Episodes       : $(count_lines "$OUTPUT_DIR/episodes.jsonl")"
echo "LLM payloads   : $(count_lines "$OUTPUT_DIR/llm-payloads.jsonl")"
echo
echo "Results:"
echo "  $OUTPUT_DIR/timeline.jsonl"
echo "  $OUTPUT_DIR/episodes.jsonl"
echo "  $OUTPUT_DIR/llm-payloads.jsonl"
echo
echo "Collector diagnostics:"
echo "  $OUTPUT_DIR/linux-collector.stdout.log"
echo "  $OUTPUT_DIR/linux-collector.stderr.log"
echo "  $OUTPUT_DIR/browser-collector.stdout.log"
echo "  $OUTPUT_DIR/browser-collector.stderr.log"

# Browser is intentionally closed at script exit because it uses the dedicated CDP profile.
