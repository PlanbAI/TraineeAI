#!/usr/bin/env python3
"""Replay a previously recorded RDP JSONL scenario into a selected mstsc window."""

import argparse
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", INPUT_UNION)]


def process_name(pid: int) -> str | None:
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    return None


def active_target(title_substring: str) -> tuple[int, dict] | None:
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if (process_name(pid.value) or "").casefold() != "mstsc.exe":
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title, len(title))
    if title_substring.casefold() not in title.value.casefold():
        return None
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return int(hwnd), {"title": title.value, "client_size": {"width": rect.right - rect.left, "height": rect.bottom - rect.top}}


def load_events(path: Path) -> list[dict]:
    events = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_number}: {exc}") from exc
            if event.get("type") == "rdp.input":
                events.append(event)
            elif event.get("type") == "rdp.paste_detected":
                raise ValueError("Scenarios containing pasted content cannot be replayed safely")
    return events


def send_input(input_event: INPUT) -> None:
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(input_event), ctypes.sizeof(INPUT))
    if sent != 1:
        raise OSError("SendInput failed")


def move_to_client(hwnd: int, payload: dict) -> None:
    point = wintypes.POINT(payload["x"], payload["y"])
    user32 = ctypes.windll.user32
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    left = user32.GetSystemMetrics(76)
    top = user32.GetSystemMetrics(77)
    width = user32.GetSystemMetrics(78) - 1
    height = user32.GetSystemMetrics(79) - 1
    dx = round((point.x - left) * 65535 / max(width, 1))
    dy = round((point.y - top) * 65535 / max(height, 1))
    send_input(
        INPUT(
            type=INPUT_MOUSE,
            mi=MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, None),
        )
    )


def replay_event(hwnd: int, event: dict) -> None:
    payload = event["input"]
    if payload["kind"] == "key":
        flags = KEYEVENTF_SCANCODE if payload.get("scan_code") else 0
        if payload.get("action") == "up":
            flags |= KEYEVENTF_KEYUP
        send_input(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, payload.get("scan_code", 0), flags, 0, None)))
        return
    if payload["kind"] == "wheel":
        move_to_client(hwnd, payload)
        send_input(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, payload["detail"], MOUSEEVENTF_WHEEL, 0, None)))
        return
    if payload["kind"] == "move":
        move_to_client(hwnd, payload)
        return
    button_flags = {
        "left_down": MOUSEEVENTF_LEFTDOWN,
        "left_up": MOUSEEVENTF_LEFTUP,
        "right_down": MOUSEEVENTF_RIGHTDOWN,
        "right_up": MOUSEEVENTF_RIGHTUP,
        "middle_down": MOUSEEVENTF_MIDDLEDOWN,
        "middle_up": MOUSEEVENTF_MIDDLEUP,
    }
    if payload["kind"] == "button" and payload["detail"] in button_flags:
        move_to_client(hwnd, payload)
        send_input(INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, button_flags[payload["detail"]], 0, None)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a local RDP input scenario into a selected mstsc window.")
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--window-title", required=True, help="Required substring of the selected RDP window title")
    parser.add_argument("--execute", action="store_true", help="Send input; without this flag the command is a dry run")
    parser.add_argument("--allow-geometry-mismatch", action="store_true")
    parser.add_argument("--checkpoint-before", action="store_true", help="Require Enter before sending input")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("WindowsRdpReplay.py must run on Windows")
    events = load_events(args.scenario)
    if not events:
        parser.error("No replayable rdp.input events were found")
    target = active_target(args.window_title)
    if not target:
        parser.error("Focus the matching mstsc window before replay")
    hwnd, context = target
    recorded_size = events[0].get("window", {}).get("client_size")
    if recorded_size and context["client_size"] != recorded_size and not args.allow_geometry_mismatch:
        parser.error("RDP client size differs from the recording; resize it or use --allow-geometry-mismatch")
    print(f"Target: {context['title']}")
    print(f"Replayable input events: {len(events)}")
    if not args.execute:
        print("Dry run only. Re-run with --execute to send input.")
        return
    if args.checkpoint_before:
        input("Checkpoint: confirm the remote screen is ready, then press Enter...")
    previous_time = None
    for event in events:
        target = active_target(args.window_title)
        if not target:
            raise RuntimeError("Replay stopped because the selected mstsc window lost focus")
        current_time = event.get("timestamp")
        if previous_time and current_time:
            delay = max(0.0, min(2.0, (parse_time(current_time) - parse_time(previous_time))))
            time.sleep(delay)
        replay_event(hwnd, event)
        previous_time = current_time
    print("Replay completed.")


def parse_time(value: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


if __name__ == "__main__":
    main()
