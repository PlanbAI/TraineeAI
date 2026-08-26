#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DESKTOP_LOG="${DESKTOP_LOG:-events.jsonl}"
BROWSER_LOG="${BROWSER_LOG:-browser-events.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-test-output}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/run_analysis_test.sh [desktop_log] [browser_log] [output_dir]

Defaults:
  desktop_log = events.jsonl
  browser_log = browser-events.jsonl
  output_dir  = test-output

Environment overrides:
  PYTHON_BIN=/path/to/python
  DESKTOP_LOG=/path/to/events.jsonl
  BROWSER_LOG=/path/to/browser-events.jsonl
  OUTPUT_DIR=/path/to/output

Examples:
  ./scripts/run_analysis_test.sh
  ./scripts/run_analysis_test.sh logs/events.jsonl logs/browser-events.jsonl
  PYTHON_BIN=.venv/bin/python ./scripts/run_analysis_test.sh
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ge 1 ]]; then DESKTOP_LOG="$1"; fi
if [[ $# -ge 2 ]]; then BROWSER_LOG="$2"; fi
if [[ $# -ge 3 ]]; then OUTPUT_DIR="$3"; fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python executable not found: $PYTHON_BIN" >&2
  echo "Tip: PYTHON_BIN=.venv/bin/python ./scripts/run_analysis_test.sh" >&2
  exit 2
fi

if [[ ! -f "$DESKTOP_LOG" ]]; then
  echo "ERROR: Desktop log not found: $DESKTOP_LOG" >&2
  exit 3
fi

if [[ ! -f "$BROWSER_LOG" ]]; then
  echo "ERROR: Browser log not found: $BROWSER_LOG" >&2
  exit 4
fi

mkdir -p "$OUTPUT_DIR"

EPISODES_FILE="$OUTPUT_DIR/episodes.jsonl"
TIMELINE_FILE="$OUTPUT_DIR/timeline.jsonl"
LLM_PAYLOAD_FILE="$OUTPUT_DIR/llm-payloads.jsonl"

rm -f "$EPISODES_FILE" "$TIMELINE_FILE" "$LLM_PAYLOAD_FILE"

echo "=== TraineeAI analysis test ==="
echo "Desktop log : $DESKTOP_LOG"
echo "Browser log : $BROWSER_LOG"
echo "Output dir  : $OUTPUT_DIR"
echo "Python      : $PYTHON_BIN"
echo

"$PYTHON_BIN" -m analysis.analyze \
  --desktop "$DESKTOP_LOG" \
  --browser "$BROWSER_LOG" \
  --output "$EPISODES_FILE" \
  --timeline-output "$TIMELINE_FILE" \
  --llm-payload-output "$LLM_PAYLOAD_FILE"

count_lines() {
  local file="$1"
  if [[ -f "$file" ]]; then
    wc -l < "$file" | tr -d ' '
  else
    echo 0
  fi
}

episodes_count="$(count_lines "$EPISODES_FILE")"
timeline_count="$(count_lines "$TIMELINE_FILE")"
llm_payload_count="$(count_lines "$LLM_PAYLOAD_FILE")"

echo
echo "=== Result ==="
echo "Timeline events : $timeline_count"
echo "Episodes        : $episodes_count"
echo "LLM payloads    : $llm_payload_count"
echo
echo "Files:"
echo "  $TIMELINE_FILE"
echo "  $EPISODES_FILE"
echo "  $LLM_PAYLOAD_FILE"

if [[ "$episodes_count" -eq 0 ]]; then
  echo
  echo "WARNING: no episodes were produced. Inspect timeline.jsonl and segmentation heuristics."
  exit 5
fi

echo
echo "OK: analysis pipeline completed successfully."
