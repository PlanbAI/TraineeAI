#!/usr/bin/env python3
"""Record explicitly selected mstsc input without elevated permissions."""

import argparse
import ctypes
import json
import os
import re
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path


WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x00000001
VK_BACK = 0x08
VK_RETURN = 0x0D
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_V = 0x56
VK_F11 = 0x7A
VK_F12 = 0x7B
SENSITIVE_COMMAND_RE = re.compile(
    r"password|passcode|secret|token|api[ _-]?key|authorization|bearer|"
    r"private[ _-]?key|credit[ _-]?card|card[ _-]?number|cvv|cvc|ssn",
    re.IGNORECASE,
)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


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


def window_context(hwnd: int) -> dict | None:
    if not hwnd:
        return None
    user32 = ctypes.windll.user32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    title_length = user32.GetWindowTextLengthW(hwnd)
    title = ctypes.create_unicode_buffer(title_length + 1)
    user32.GetWindowTextW(hwnd, title, len(title))
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return {
        "id": int(hwnd),
        "title": title.value,
        "process": process_name(pid.value),
        "pid": pid.value,
        "client_size": {"width": rect.right - rect.left, "height": rect.bottom - rect.top},
    }


class RdpRecorder:
    def __init__(self, output: Path, title_substring: str, shell: str):
        self.output = output
        self.title_substring = title_substring.casefold()
        self.shell = shell
        self.command_buffer: list[str] = []
        self.paused = False
        self.paste_key_active = False
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.keyboard_hook = None
        self.mouse_hook = None
        self.keyboard_callback = None
        self.mouse_callback = None

    def target_context(self) -> dict | None:
        context = window_context(self.user32.GetForegroundWindow())
        if not context or (context["process"] or "").casefold() != "mstsc.exe":
            return None
        if self.title_substring not in context["title"].casefold():
            return None
        return context

    def emit(self, event_type: str, context: dict, **extra: object) -> None:
        event = {
            "timestamp": now_iso(),
            "type": event_type,
            "source": "desktop",
            "application": {"name": "mstsc.exe", "pid": context["pid"]},
            "window": {
                "id": context["id"],
                "title": context["title"],
                "client_size": context["client_size"],
            },
            **extra,
        }
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self.output.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)

    def modifier_state(self) -> dict[str, bool]:
        return {
            "ctrl": bool(self.user32.GetAsyncKeyState(VK_CONTROL) & 0x8000),
            "shift": bool(self.user32.GetAsyncKeyState(VK_SHIFT) & 0x8000),
            "alt": bool(self.user32.GetAsyncKeyState(VK_MENU) & 0x8000),
        }

    def key_text(self, vk_code: int, scan_code: int) -> str:
        state = (ctypes.c_byte * 256)()
        if not self.user32.GetKeyboardState(ctypes.byref(state)):
            return ""
        buffer = ctypes.create_unicode_buffer(8)
        layout = self.user32.GetKeyboardLayout(0)
        count = self.user32.ToUnicodeEx(vk_code, scan_code, state, buffer, len(buffer), 0, layout)
        return buffer.value if count > 0 else ""

    def submit_command(self, context: dict) -> None:
        command = "".join(self.command_buffer).strip()
        self.command_buffer.clear()
        if not command:
            return
        redacted = bool(SENSITIVE_COMMAND_RE.search(command))
        self.emit(
            "rdp.command_submitted",
            context,
            terminal={
                "shell": self.shell,
                "command": "<REDACTED_COMMAND>" if redacted else command,
                "content_redacted": redacted,
            },
        )

    def keyboard_proc(self, code: int, message: int, data: int) -> int:
        if code != HC_ACTION:
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        key = ctypes.cast(data, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if key.flags & LLKHF_INJECTED:
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        context = self.target_context()
        if not context:
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        is_down = message in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = message in (WM_KEYUP, WM_SYSKEYUP)
        if not (is_down or is_up):
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        modifiers = self.modifier_state()
        if is_down and modifiers["ctrl"] and modifiers["shift"] and key.vkCode == VK_F11:
            self.emit("rdp.recording_stopped", context)
            self.user32.PostQuitMessage(0)
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        if is_down and modifiers["ctrl"] and modifiers["shift"] and key.vkCode == VK_F12:
            self.paused = not self.paused
            self.emit("rdp.recording_resumed" if not self.paused else "rdp.recording_paused", context)
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        if self.paused:
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        if is_down and modifiers["ctrl"] and key.vkCode == VK_V:
            self.paste_key_active = True
            self.command_buffer.append("<PASTED_CONTENT_NOT_CAPTURED>")
            self.emit("rdp.paste_detected", context, input={"kind": "paste", "modifiers": modifiers})
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        if is_up and key.vkCode == VK_V and self.paste_key_active:
            self.paste_key_active = False
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        self.emit(
            "rdp.input",
            context,
            input={
                "kind": "key",
                "action": "down" if is_down else "up",
                "vk_code": key.vkCode,
                "scan_code": key.scanCode,
                "modifiers": modifiers,
            },
        )
        if is_down:
            if key.vkCode == VK_RETURN:
                self.submit_command(context)
            elif key.vkCode == VK_BACK:
                if self.command_buffer:
                    self.command_buffer.pop()
            elif key.vkCode not in (VK_CONTROL, VK_SHIFT, VK_MENU):
                self.command_buffer.append(self.key_text(key.vkCode, key.scanCode))
        return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)

    def mouse_proc(self, code: int, message: int, data: int) -> int:
        if code != HC_ACTION or self.paused:
            return self.user32.CallNextHookEx(self.mouse_hook, code, message, data)
        mouse = ctypes.cast(data, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        if mouse.flags & LLMHF_INJECTED:
            return self.user32.CallNextHookEx(self.mouse_hook, code, message, data)
        context = self.target_context()
        if not context:
            return self.user32.CallNextHookEx(self.mouse_hook, code, message, data)
        point = wintypes.POINT(mouse.pt.x, mouse.pt.y)
        self.user32.ScreenToClient(context["id"], ctypes.byref(point))
        mapping = {
            WM_MOUSEMOVE: ("move", None),
            WM_LBUTTONDOWN: ("button", "left_down"),
            WM_LBUTTONUP: ("button", "left_up"),
            WM_RBUTTONDOWN: ("button", "right_down"),
            WM_RBUTTONUP: ("button", "right_up"),
            WM_MBUTTONDOWN: ("button", "middle_down"),
            WM_MBUTTONUP: ("button", "middle_up"),
            WM_MOUSEWHEEL: ("wheel", ctypes.c_short(mouse.mouseData >> 16).value),
        }
        if message in mapping:
            kind, detail = mapping[message]
            self.emit("rdp.input", context, input={"kind": kind, "detail": detail, "x": point.x, "y": point.y})
        return self.user32.CallNextHookEx(self.mouse_hook, code, message, data)

    def run(self) -> None:
        hook_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        self.keyboard_callback = hook_type(self.keyboard_proc)
        self.mouse_callback = hook_type(self.mouse_proc)
        self.kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        self.kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        self.user32.SetWindowsHookExW.argtypes = (ctypes.c_int, hook_type, ctypes.c_void_p, wintypes.DWORD)
        self.user32.SetWindowsHookExW.restype = ctypes.c_void_p
        self.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        module = self.kernel32.GetModuleHandleW(None)
        self.keyboard_hook = self.user32.SetWindowsHookExW(WH_KEYBOARD_LL, self.keyboard_callback, module, 0)
        self.mouse_hook = self.user32.SetWindowsHookExW(WH_MOUSE_LL, self.mouse_callback, module, 0)
        if not self.keyboard_hook or not self.mouse_hook:
            raise OSError("Unable to install the RDP input hooks")
        print("RDP recording active. Ctrl+Shift+F12 pauses/resumes; Ctrl+Shift+F11 stops.")
        message = wintypes.MSG()
        try:
            while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                self.user32.TranslateMessage(ctypes.byref(message))
                self.user32.DispatchMessageW(ctypes.byref(message))
        finally:
            self.user32.UnhookWindowsHookEx(self.keyboard_hook)
            self.user32.UnhookWindowsHookEx(self.mouse_hook)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record input for one selected mstsc RDP window.")
    parser.add_argument("--window-title", required=True, help="Required substring of the selected RDP window title")
    parser.add_argument("--output", type=Path, default=Path("rdp-events.jsonl"))
    parser.add_argument("--shell", choices=("unknown", "powershell", "bash"), default="unknown")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("WindowsRdpCollector.py must run on Windows")
    if not args.window_title.strip():
        parser.error("--window-title must not be blank")
    print("RDP capture records keyboard and mouse input only for the selected mstsc window.")
    print("Do not record passwords, tokens, or other secrets.")
    RdpRecorder(args.output, args.window_title, args.shell).run()


if __name__ == "__main__":
    main()
