#!/usr/bin/env python3
"""Record global keyboard input through a Windows low-level hook as JSONL events."""

import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path


WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
LLKHF_EXTENDED = 0x01
LLKHF_INJECTED = 0x10
LLKHF_ALTDOWN = 0x20
LLKHF_UP = 0x80
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_CAPITAL = 0x14
VK_NUMLOCK = 0x90
VK_SCROLL = 0x91
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_BACK = 0x08
VK_RETURN = 0x0D
VK_TAB = 0x09
LRESULT = ctypes.c_ssize_t
VK_NO_CHAR = {
    VK_BACK, VK_TAB, VK_RETURN, VK_SHIFT, VK_CONTROL, VK_MENU, VK_CAPITAL,
    0x1B, 0x2C, VK_LWIN, VK_RWIN, 0x5D, VK_NUMLOCK, VK_SCROLL,
    VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU,
}
VK_NAMES = {
    VK_BACK: "Backspace", VK_TAB: "Tab", VK_RETURN: "Enter", VK_SHIFT: "Shift",
    VK_CONTROL: "Ctrl", VK_MENU: "Alt", VK_CAPITAL: "CapsLock", 0x1B: "Escape",
    0x20: "Space", 0x21: "PageUp", 0x22: "PageDown", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2D: "Insert",
    0x2E: "Delete", VK_LWIN: "WinLeft", VK_RWIN: "WinRight", 0x5D: "Apps",
    0x90: "NumLock", 0x91: "ScrollLock",
    0xA0: "LShift", 0xA1: "RShift", 0xA2: "LCtrl", 0xA3: "RCtrl",
    0xA4: "LAlt", 0xA5: "RAlt",
}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def key_name(vk_code: int) -> str:
    named_keys = {
        0x08: "Backspace",
        0x09: "Tab",
        0x0D: "Enter",
        0x10: "Shift",
        0x11: "Ctrl",
        0x12: "Alt",
        0x14: "CapsLock",
        0x1B: "Escape",
        0x20: "Space",
        0x21: "PageUp",
        0x22: "PageDown",
        0x23: "End",
        0x24: "Home",
        0x25: "Left",
        0x26: "Up",
        0x27: "Right",
        0x28: "Down",
        0x2D: "Insert",
        0x2E: "Delete",
        0x5B: "WinLeft",
        0x5C: "WinRight",
        0x5D: "Apps",
        0x90: "NumLock",
        0x91: "ScrollLock",
        0xA0: "LShift",
        0xA1: "RShift",
        0xA2: "LCtrl",
        0xA3: "RCtrl",
        0xA4: "LAlt",
        0xA5: "RAlt",
    }
    if 0x30 <= vk_code <= 0x39 or 0x41 <= vk_code <= 0x5A:
        return chr(vk_code)
    if 0x60 <= vk_code <= 0x69:
        return f"Numpad{vk_code - 0x60}"
    if 0x70 <= vk_code <= 0x87:
        return f"F{vk_code - 0x6F}"
    return named_keys.get(vk_code, f"VK_{vk_code:02X}")


class KeyboardRecorder:
    def __init__(
        self,
        output: Path,
        phrase_timeout_ms: int = 500,
        raw: bool = False,
        quiet: bool = False,
    ):
        self.output = output
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.phrase_timeout = max(50, int(phrase_timeout_ms)) / 1000.0
        self.raw = raw
        self.quiet = quiet
        self.user32 = ctypes.windll.user32
        self.keyboard_hook = None
        self.keyboard_callback = None
        self._kb_state = (ctypes.c_ubyte * 256)()
        self._caps_on = bool(self.user32.GetAsyncKeyState(VK_CAPITAL) & 0x01)
        self._num_on = bool(self.user32.GetAsyncKeyState(VK_NUMLOCK) & 0x01)
        self._scr_on = bool(self.user32.GetAsyncKeyState(VK_SCROLL) & 0x01)
        self._kb_state[VK_CAPITAL] = 0x01 if self._caps_on else 0x00
        self._kb_state[VK_NUMLOCK] = 0x01 if self._num_on else 0x00
        self._kb_state[VK_SCROLL] = 0x01 if self._scr_on else 0x00
        self._phrase_chars: list[str] = []
        self._phrase_start = 0.0
        self._last_text_time = 0.0
        self._phrase_window = None
        self._raw_file = None

    def emit(self, event_type: str, **extra: object) -> None:
        event = {"timestamp": now_iso(), "type": event_type, "source": "keyboard", **extra}
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self.output.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        if not self.quiet:
            print(line, flush=True)

    def modifier_state(self) -> dict[str, bool]:
        return {
            "ctrl": bool(self.user32.GetAsyncKeyState(VK_CONTROL) & 0x8000),
            "shift": bool(self.user32.GetAsyncKeyState(VK_SHIFT) & 0x8000),
            "alt": bool(self.user32.GetAsyncKeyState(VK_MENU) & 0x8000),
        }

    def _update_kb_state(self, vk_code: int, is_up: bool) -> None:
        generic = {
            VK_LSHIFT: VK_SHIFT, VK_RSHIFT: VK_SHIFT,
            VK_LCONTROL: VK_CONTROL, VK_RCONTROL: VK_CONTROL,
            VK_LMENU: VK_MENU, VK_RMENU: VK_MENU,
        }
        if not is_up:
            if vk_code == VK_CAPITAL:
                self._caps_on = not self._caps_on
            elif vk_code == VK_NUMLOCK:
                self._num_on = not self._num_on
            elif vk_code == VK_SCROLL:
                self._scr_on = not self._scr_on
            self._kb_state[vk_code] = 0x80
        else:
            self._kb_state[vk_code] = 0x00
        if vk_code in generic:
            self._kb_state[generic[vk_code]] = self._kb_state[vk_code]
        self._kb_state[VK_CAPITAL] = 0x01 if self._caps_on else 0x00
        self._kb_state[VK_NUMLOCK] = 0x01 if self._num_on else 0x00
        self._kb_state[VK_SCROLL] = 0x01 if self._scr_on else 0x00

    def _foreground_layout(self) -> int:
        foreground = self.user32.GetForegroundWindow()
        thread_id = self.user32.GetWindowThreadProcessId(foreground, None)
        return self.user32.GetKeyboardLayout(thread_id)

    def _decode_char(self, vk_code: int, scan_code: int) -> tuple[str | None, bool]:
        if vk_code in VK_NO_CHAR:
            return None, False
        layout = self._foreground_layout()
        buffer = (ctypes.c_wchar * 8)()
        count = self.user32.ToUnicodeEx(
            vk_code, scan_code, self._kb_state, buffer, 8, 1, layout
        )
        if count == -1:
            count = self.user32.ToUnicodeEx(
                vk_code, scan_code, self._kb_state, buffer, 8, 1, layout
            )
            chars = [c for c in buffer[: max(count, 0)] if c]
            return (chars[0] if chars else None, True)
        if count <= 0:
            return None, False
        chars = [c for c in buffer[:count] if c and 0x20 <= ord(c) <= 0x10FFFF and ord(c) != 0x7F]
        return ("".join(chars), False) if chars else (None, False)

    def close_phrase(self) -> None:
        if not self._phrase_chars:
            self._phrase_chars.clear()
            return
        text = "".join(self._phrase_chars)
        start = datetime.fromtimestamp(self._phrase_start, timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        self._phrase_chars.clear()
        self._phrase_start = 0.0
        self.emit("keyboard.phrase_submitted", text=text, words=text.split(), phrase_start=start)

    def flush_pending(self) -> None:
        """Called by the message-loop timer, even when no keys arrive."""
        if self._phrase_chars and (
            time.monotonic() - self._last_text_time >= self.phrase_timeout
            or self.user32.GetForegroundWindow() != self._phrase_window
        ):
            self.close_phrase()

    def handle_key(self, vk_code: int, scan_code: int, is_down: bool, is_up: bool) -> None:
        self._update_kb_state(vk_code, is_up)
        # Key releases update modifiers but must not decode or duplicate text.
        if not is_down or is_up:
            return
        self.flush_pending()
        char, is_dead = self._decode_char(vk_code, scan_code)
        modifiers = self.modifier_state()
        now = time.monotonic()

        self.emit(
            "keyboard.key_down",
            key={
                "name": key_name(vk_code),
                "vk_code": vk_code,
                "scan_code": scan_code,
                "char": char,
                "is_dead": is_dead,
                "modifiers": modifiers,
            },
        )
        if self.raw and self._raw_file and not self._raw_file.closed:
            marker = "dead" if is_dead else "char"
            detail = f" {marker}='{char}'" if char is not None else ""
            self._raw_file.write(
                f"{now_iso()} [{('DOWN' if is_down else 'UP')}] {key_name(vk_code)} vk=0x{vk_code:02X}{detail}\n"
            )
            self._raw_file.flush()

        if not is_up:
            if self._phrase_chars and now - self._last_text_time > self.phrase_timeout:
                self.close_phrase()
            altgr = bool(self._kb_state[VK_RMENU] & 0x80)
            shortcut = (
                (modifiers["ctrl"] or modifiers["alt"]) and not altgr
            ) or bool(self._kb_state[VK_LWIN] & 0x80 or self._kb_state[VK_RWIN] & 0x80)
            if vk_code in (VK_RETURN, VK_TAB, 0x1B, 0x21, 0x22, 0x23, 0x24,
                           0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E) or shortcut:
                self.close_phrase()
                self._last_text_time = now
                return
            if vk_code == VK_BACK:
                if self._phrase_chars:
                    self._phrase_chars.pop()
                if not self._phrase_chars:
                    self._phrase_start = 0.0
                self._last_text_time = now
                return
            if char is None or is_dead:
                return
            if not self._phrase_chars:
                self._phrase_start = time.time()
                self._phrase_window = self.user32.GetForegroundWindow()
            self._phrase_chars.extend(char)
            self._last_text_time = now

    def keyboard_proc(self, code: int, message: int, data: int) -> int:
        if code != HC_ACTION:
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        key = ctypes.cast(data, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        is_down = message in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = message in (WM_KEYUP, WM_SYSKEYUP)
        if not (is_down or is_up):
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        self.handle_key(key.vkCode, key.scanCode, is_down, is_up)
        return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)

    def safe_keyboard_proc(self, code: int, message: int, data: int) -> int:
        try:
            return self.keyboard_proc(code, message, data)
        except Exception as error:
            print(f"Keyboard hook error: {error}", file=sys.stderr, flush=True)
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)

    def run(self) -> None:
        self.user32.SetWindowsHookExW.restype = ctypes.c_void_p
        self.user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD)
        self.user32.CallNextHookEx.restype = LRESULT
        self.user32.CallNextHookEx.argtypes = (ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        module = None
        self.keyboard_callback = HOOKPROC(self.safe_keyboard_proc)
        self.keyboard_hook = self.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self.keyboard_callback, module, 0
        )
        if not self.keyboard_hook:
            raise OSError("Unable to install the keyboard hook")
        if self.raw:
            base = self.output.with_name("events_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S.txt"))
            self._raw_file = base.open("a", encoding="utf-8")
            self._raw_file.write(f"=== Keyboard Raw Log ===\nStarted: {now_iso()}\n{'=' * 50}\n")
            self._raw_file.flush()
        print(f"Keyboard collector output: {self.output.resolve()}", flush=True)
        print("KBD hook active. Ctrl+C stops. Do not record passwords, tokens, or other secrets.", flush=True)
        message = wintypes.MSG()
        self.user32.SetTimer.argtypes = (wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p)
        self.user32.SetTimer.restype = ctypes.c_size_t
        self.user32.KillTimer.argtypes = (wintypes.HWND, ctypes.c_size_t)
        timer = self.user32.SetTimer(None, 0, 50, None)
        try:
            if not timer:
                raise OSError("Unable to install the phrase timeout timer")
            while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                self.flush_pending()
                self.user32.TranslateMessage(ctypes.byref(message))
                self.user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if timer:
                self.user32.KillTimer(None, timer)
            if self.keyboard_hook:
                self.user32.UnhookWindowsHookEx(self.keyboard_hook)
            self.close_phrase()
            if self._raw_file and not self._raw_file.closed:
                self._raw_file.write(f"\n{'=' * 50}\nStopped: {now_iso()}\n")
                self._raw_file.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Record global Windows keyboard input as JSONL events.")
    parser.add_argument("--output", type=Path, default=Path("keyboard-events.jsonl"))
    parser.add_argument("--phrase-timeout", type=int, default=500, help="Pause in ms that ends a phrase")
    parser.add_argument("--raw", action="store_true", help="Also write a raw per-event log next to output")
    parser.add_argument("--quiet", action="store_true", help="Suppress JSONL echoes on stdout")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("KeyboardCollector.py must run on Windows")
    print("Keyboard capture records all input on this machine.")
    print("Do not record passwords, tokens, or other secrets.")
    KeyboardRecorder(args.output, args.phrase_timeout, args.raw, args.quiet).run()


if __name__ == "__main__":
    main()
