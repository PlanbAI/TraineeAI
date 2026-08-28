#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/media/sf_TraineeAI}"

if [[ ! -f "$PROJECT_DIR/collectors/LinuxCollector.py" ]]; then
  echo "ERROR: TraineeAI shared folder is unavailable at $PROJECT_DIR." >&2
  echo "Install VirtualBox Guest Additions, then log out and back in before retrying." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y \
  at-spi2-core \
  gir1.2-atspi-2.0 \
  python3-gi \
  python3-requests \
  python3-websocket \
  python3-xlib \
  chromium-browser

echo "Dependencies installed. Start Chromium with CDP in the Ubuntu desktop session:"
echo '  chromium-browser --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="$HOME/.traineeai-cdp-profile"'
echo "Then run the collectors from the shared project folder:"
echo "  python3 collectors/LinuxCollector.py"
echo "  python3 collectors/BrowserCollector.py"
