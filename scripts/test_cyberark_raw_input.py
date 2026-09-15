#!/usr/bin/env python3
"""Interactively verify CyberArk Raw Input capture using local Notepad."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT_DIR / "collectors" / "WindowsCyberArkCollector.py"


def load_raw_key_count(output: Path) -> int:
    if not output.exists():
        return 0
    count = 0
    for line in output.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("input", {}).get("capture_source") == "raw_input":
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify CyberArk Raw Input capture with local Notepad.")
    parser.add_argument("--output", type=Path, default=ROOT_DIR / "test-output" / "cyberark-raw-input-test.jsonl")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("test_cyberark_raw_input.py must run on Windows")
    if not COLLECTOR.is_file():
        parser.error(f"CyberArk collector was not found: {COLLECTOR}")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    log_file = output.with_suffix(".log")
    notepad = subprocess.Popen(["notepad.exe"])
    collector = None
    try:
        time.sleep(1)
        with log_file.open("w", encoding="utf-8") as log:
            collector = subprocess.Popen(
                [
                    sys.executable,
                    str(COLLECTOR),
                    "--process-name",
                    "notepad.exe",
                    "--output",
                    str(output),
                ],
                cwd=ROOT_DIR,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            time.sleep(1)
            if collector.poll() is not None:
                parser.error(f"CyberArk collector exited immediately. See {log_file}")
            print("Focus Notepad, type rawinput-test, and press Enter.")
            print("Use no credentials or other sensitive data. Return here and press Enter to finish.")
            input()
        time.sleep(1)
    finally:
        if collector and collector.poll() is None:
            collector.terminate()
            try:
                collector.wait(timeout=3)
            except subprocess.TimeoutExpired:
                collector.kill()

    raw_key_count = load_raw_key_count(output)
    if raw_key_count:
        print(f"PASS: captured {raw_key_count} Raw Input keyboard event(s) in {output}")
        return 0
    print(f"FAIL: no Raw Input keyboard events were captured. See {log_file}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
