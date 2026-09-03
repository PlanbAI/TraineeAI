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
WM_INPUT = 0x00FF
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x00000001
LRESULT = ctypes.c_ssize_t
RIM_TYPEKEYBOARD = 1
RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x00000100
RI_KEY_BREAK = 0x0001
HWND_MESSAGE = -3
INVALID_RAW_INPUT = 0xFFFFFFFF
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


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.WORD),
        ("usUsage", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", ctypes.c_void_p),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", ctypes.c_void_p),
        ("wParam", wintypes.WPARAM),
    ]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", wintypes.WORD),
        ("Flags", wintypes.WORD),
        ("Reserved", wintypes.WORD),
        ("VKey", wintypes.WORD),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.DWORD),
    ]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
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
    def __init__(
        self,
        output: Path,
        title_substring: str | None,
        shell: str,
        record_mouse_moves: bool,
        record_injected_key_events: bool,
        process_names: tuple[str, ...] = ("mstsc.exe",),
        use_raw_keyboard: bool = False,
    ):
        self.output = output
        self.title_substring = title_substring.casefold() if title_substring else None
        self.shell = shell
        self.record_mouse_moves = record_mouse_moves
        self.record_injected_key_events = record_injected_key_events
        self.process_names = {process_name.casefold() for process_name in process_names}
        self.use_raw_keyboard = use_raw_keyboard
        self.target_window_id: int | None = None
        self.command_buffer: list[str] = []
        self.paused = False
        self.paste_key_active = False
        self.last_mouse_move_at = 0.0
        self.last_mouse_position: tuple[int, int] | None = None
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.keyboard_hook = None
        self.mouse_hook = None
        self.keyboard_callback = None
        self.mouse_callback = None
        self.raw_window_callback = None
        self.raw_window = None
        self.raw_window_class = None

    def target_context(self) -> dict | None:
        context = window_context(self.user32.GetForegroundWindow())
        if not context or (context["process"] or "").casefold() not in self.process_names:
            return None
        if self.target_window_id is not None:
            return context if context["id"] == self.target_window_id else None
        if self.title_substring and self.title_substring not in context["title"].casefold():
            return None
        self.target_window_id = context["id"]
        print(f"RDP window selected: {context['title']}", flush=True)
        return context

    def forward_event(self, hook: int, code: int, message: int, data: int) -> int:
        try:
            return self.user32.CallNextHookEx(hook, code, message, data)
        except Exception as error:
            print(f"Unable to forward hook event: {error}", file=sys.stderr, flush=True)
            # Returning zero tells Windows that this hook did not handle the event.
            return 0

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

    def record_key_event(self, vk_code: int, scan_code: int, is_down: bool, is_up: bool, context: dict) -> None:
        modifiers = self.modifier_state()
        if is_down and modifiers["ctrl"] and modifiers["shift"] and vk_code == VK_F11:
            self.emit("rdp.recording_stopped", context)
            self.user32.PostQuitMessage(0)
            return
        if is_down and modifiers["ctrl"] and modifiers["shift"] and vk_code == VK_F12:
            self.paused = not self.paused
            self.emit("rdp.recording_resumed" if not self.paused else "rdp.recording_paused", context)
            return
        if self.paused:
            return
        if is_down and modifiers["ctrl"] and vk_code == VK_V:
            self.paste_key_active = True
            self.command_buffer.append("<PASTED_CONTENT_NOT_CAPTURED>")
            self.emit("rdp.paste_detected", context, input={"kind": "paste", "modifiers": modifiers})
            return
        if is_up and vk_code == VK_V and self.paste_key_active:
            self.paste_key_active = False
            return
        self.emit(
            "rdp.input",
            context,
            input={
                "kind": "key",
                "action": "down" if is_down else "up",
                "vk_code": vk_code,
                "scan_code": scan_code,
                "modifiers": modifiers,
            },
        )
        if is_down:
            if vk_code == VK_RETURN:
                self.submit_command(context)
            elif vk_code == VK_BACK:
                if self.command_buffer:
                    self.command_buffer.pop()
            elif vk_code not in (VK_CONTROL, VK_SHIFT, VK_MENU):
                self.command_buffer.append(self.key_text(vk_code, scan_code))

    def keyboard_proc(self, code: int, message: int, data: int) -> int:
        if code != HC_ACTION:
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        key = ctypes.cast(data, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if self.use_raw_keyboard and not key.flags & LLKHF_INJECTED:
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        if key.flags & LLKHF_INJECTED and not self.record_injected_key_events:
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        context = self.target_context()
        if not context:
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        is_down = message in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = message in (WM_KEYUP, WM_SYSKEYUP)
        if not (is_down or is_up):
            return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)
        self.record_key_event(key.vkCode, key.scanCode, is_down, is_up, context)
        return self.user32.CallNextHookEx(self.keyboard_hook, code, message, data)

    def safe_keyboard_proc(self, code: int, message: int, data: int) -> int:
        try:
            return self.keyboard_proc(code, message, data)
        except Exception as error:
            print(f"Keyboard hook error: {error}", file=sys.stderr, flush=True)
            return self.forward_event(self.keyboard_hook, code, message, data)

    def raw_keyboard_proc(self, data: int) -> None:
        size = wintypes.UINT()
        header_size = ctypes.sizeof(RAWINPUTHEADER)
        if self.user32.GetRawInputData(ctypes.c_void_p(data), RID_INPUT, None, ctypes.byref(size), header_size) == INVALID_RAW_INPUT:
            return
        buffer = ctypes.create_string_buffer(size.value)
        if self.user32.GetRawInputData(ctypes.c_void_p(data), RID_INPUT, ctypes.cast(buffer, ctypes.c_void_p), ctypes.byref(size), header_size) == INVALID_RAW_INPUT:
            return
        header = ctypes.cast(buffer, ctypes.POINTER(RAWINPUTHEADER)).contents
        if header.dwType != RIM_TYPEKEYBOARD:
            return
        keyboard_address = ctypes.addressof(buffer) + header_size
        keyboard = ctypes.cast(keyboard_address, ctypes.POINTER(RAWKEYBOARD)).contents
        if keyboard.VKey == 0xFF:
            return
        context = self.target_context()
        if not context:
            return
        is_up = bool(keyboard.Flags & RI_KEY_BREAK)
        self.record_key_event(keyboard.VKey, keyboard.MakeCode, not is_up, is_up, context)

    def raw_window_proc(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        try:
            if message == WM_INPUT:
                self.raw_keyboard_proc(lparam)
        except Exception as error:
            print(f"Raw keyboard input error: {error}", file=sys.stderr, flush=True)
        return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def install_raw_keyboard_window(self, module: int) -> None:
        self.raw_window_class = f"TraineeRawKeyboard{os.getpid()}"
        self.raw_window_callback = WNDPROC(self.raw_window_proc)
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = self.raw_window_callback
        window_class.hInstance = module
        window_class.lpszClassName = self.raw_window_class
        if not self.user32.RegisterClassW(ctypes.byref(window_class)):
            raise OSError("Unable to register the raw keyboard window class")
        self.raw_window = self.user32.CreateWindowExW(
            0,
            self.raw_window_class,
            None,
            0,
            0,
            0,
            0,
            0,
            ctypes.c_void_p(HWND_MESSAGE),
            None,
            module,
            None,
        )
        if not self.raw_window:
            raise OSError("Unable to create the raw keyboard input window")
        device = RAWINPUTDEVICE(1, 6, RIDEV_INPUTSINK, self.raw_window)
        if not self.user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(RAWINPUTDEVICE)):
            raise OSError("Unable to register raw keyboard input")

    def remove_raw_keyboard_window(self, module: int) -> None:
        if self.raw_window:
            self.user32.DestroyWindow(self.raw_window)
            self.raw_window = None
        if self.raw_window_class:
            self.user32.UnregisterClassW(self.raw_window_class, module)
            self.raw_window_class = None

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
            if kind == "move":
                if not self.record_mouse_moves:
                    return self.user32.CallNextHookEx(self.mouse_hook, code, message, data)
                now = time.monotonic()
                position = (point.x, point.y)
                if position == self.last_mouse_position or now - self.last_mouse_move_at < 0.05:
                    return self.user32.CallNextHookEx(self.mouse_hook, code, message, data)
                self.last_mouse_move_at = now
                self.last_mouse_position = position
            input_event = {"kind": kind, "detail": detail}
            if self.record_mouse_moves or detail in ("left_down", "right_down", "middle_down"):
                input_event.update({"x": point.x, "y": point.y})
            self.emit("rdp.input", context, input=input_event)
        return self.user32.CallNextHookEx(self.mouse_hook, code, message, data)

    def safe_mouse_proc(self, code: int, message: int, data: int) -> int:
        try:
            return self.mouse_proc(code, message, data)
        except Exception as error:
            print(f"Mouse hook error: {error}", file=sys.stderr, flush=True)
            return self.forward_event(self.mouse_hook, code, message, data)

    def run(self) -> None:
        hook_type = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        self.mouse_callback = hook_type(self.safe_mouse_proc)
        if not self.use_raw_keyboard or self.record_injected_key_events:
            self.keyboard_callback = hook_type(self.safe_keyboard_proc)
        self.kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        self.kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        self.user32.SetWindowsHookExW.argtypes = (ctypes.c_int, hook_type, ctypes.c_void_p, wintypes.DWORD)
        self.user32.SetWindowsHookExW.restype = ctypes.c_void_p
        self.user32.CallNextHookEx.argtypes = (ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        self.user32.CallNextHookEx.restype = LRESULT
        self.user32.GetRawInputData.argtypes = (ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(wintypes.UINT), wintypes.UINT)
        self.user32.GetRawInputData.restype = wintypes.UINT
        self.user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
        self.user32.RegisterClassW.restype = wintypes.WORD
        self.user32.CreateWindowExW.argtypes = (
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        self.user32.CreateWindowExW.restype = ctypes.c_void_p
        self.user32.RegisterRawInputDevices.argtypes = (ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT)
        self.user32.RegisterRawInputDevices.restype = wintypes.BOOL
        self.user32.DefWindowProcW.argtypes = (ctypes.c_void_p, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.user32.DefWindowProcW.restype = LRESULT
        self.user32.DestroyWindow.argtypes = (ctypes.c_void_p,)
        self.user32.DestroyWindow.restype = wintypes.BOOL
        self.user32.UnregisterClassW.argtypes = (wintypes.LPCWSTR, ctypes.c_void_p)
        self.user32.UnregisterClassW.restype = wintypes.BOOL
        module = self.kernel32.GetModuleHandleW(None)
        if self.use_raw_keyboard:
            self.install_raw_keyboard_window(module)
        if self.keyboard_callback:
            self.keyboard_hook = self.user32.SetWindowsHookExW(WH_KEYBOARD_LL, self.keyboard_callback, module, 0)
        self.mouse_hook = self.user32.SetWindowsHookExW(WH_MOUSE_LL, self.mouse_callback, module, 0)
        if not self.mouse_hook or (not self.use_raw_keyboard and not self.keyboard_hook):
            raise OSError("Unable to install the RDP input hooks")
        print("RDP recording active. Ctrl+Shift+F12 pauses/resumes; Ctrl+Shift+F11 stops.")
        message = wintypes.MSG()
        try:
            while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                self.user32.TranslateMessage(ctypes.byref(message))
                self.user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if self.keyboard_hook:
                self.user32.UnhookWindowsHookEx(self.keyboard_hook)
            if self.mouse_hook:
                self.user32.UnhookWindowsHookEx(self.mouse_hook)
            if self.use_raw_keyboard:
                self.remove_raw_keyboard_window(module)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record input for one selected mstsc RDP window.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--window-title", help="Required substring of the selected RDP window title")
    selection.add_argument("--auto-select", action="store_true", help="Select the first mstsc window made active")
    parser.add_argument("--output", type=Path, default=Path("rdp-events.jsonl"))
    parser.add_argument("--shell", choices=("unknown", "powershell", "bash"), default="unknown")
    parser.add_argument("--record-mouse-moves", action="store_true", help="Record mouse movement and all mouse coordinates")
    parser.add_argument("--record-injected-key-events", action="store_true", help="Record injected keyboard events for diagnostics")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("WindowsRdpCollector.py must run on Windows")
    if args.window_title is not None and not args.window_title.strip():
        parser.error("--window-title must not be blank")
    if args.auto_select:
        print("Waiting for an active mstsc window to select.")
    else:
        print("RDP capture records keyboard and mouse input only for the selected mstsc window.")
    print("Do not record passwords, tokens, or other secrets.")
    RdpRecorder(args.output, args.window_title, args.shell, args.record_mouse_moves, args.record_injected_key_events).run()


if __name__ == "__main__":
    main()
