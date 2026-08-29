#!/usr/bin/env python3

import argparse
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
OUTPUT_FILE = Path("events.jsonl")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def process_path(pid: int) -> str | None:
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None

    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)

    return None


def active_window() -> dict | None:
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    title_length = user32.GetWindowTextLengthW(hwnd)
    title_buffer = ctypes.create_unicode_buffer(title_length + 1)
    user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))

    class_buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))

    executable = process_path(pid.value)
    return {
        "id": int(hwnd),
        "pid": pid.value,
        "title": title_buffer.value,
        "class_name": class_buffer.value,
        "executable": executable,
    }


def emit_event(output_file: Path, window: dict) -> None:
    executable = window.pop("executable")
    event = {
        "timestamp": now_iso(),
        "type": "window.focused",
        "source": "desktop",
        "application": {
            "name": os.path.basename(executable) if executable else "unknown",
            "pid": window.pop("pid"),
            "executable": executable,
        },
        "window": window,
    }
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with output_file.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Record foreground Windows application changes as desktop JSONL events."
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    parser.add_argument("--interval", type=float, default=0.2)
    args = parser.parse_args()

    if sys.platform != "win32":
        parser.error("WindowsCollector.py must run on Windows")
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")

    print(f"Windows collector output: {args.output.resolve()}")
    print("Press Ctrl+C to stop.")
    last_window_id = None

    try:
        while True:
            window = active_window()
            if window and window["id"] != last_window_id:
                last_window_id = window["id"]
                emit_event(args.output, window)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nWindows collector stopped.")


if __name__ == "__main__":
    main()
