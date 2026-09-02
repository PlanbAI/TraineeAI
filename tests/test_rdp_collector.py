import ctypes
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from collectors.WindowsRdpCollector import (
    HC_ACTION,
    KBDLLHOOKSTRUCT,
    LLKHF_INJECTED,
    MSLLHOOKSTRUCT,
    RdpRecorder,
    WM_KEYDOWN,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MOUSEMOVE,
    WM_MOUSEWHEEL,
)


@unittest.skipUnless(sys.platform == "win32", "Windows hook behavior is Windows-only")
class RdpMouseRecordingTests(unittest.TestCase):
    def recorder(self, record_mouse_moves: bool, record_injected_key_events: bool = False):
        recorder = RdpRecorder(Path("unused.jsonl"), None, "unknown", record_mouse_moves, record_injected_key_events)
        recorder.user32 = type("User32", (), {
            "CallNextHookEx": staticmethod(lambda *_: 0),
            "ScreenToClient": staticmethod(lambda *_: 1),
        })()
        recorder.mouse_hook = 1
        recorder.target_context = lambda: {"id": 1, "pid": 2, "title": "test", "client_size": {"width": 1, "height": 1}}
        events = []
        recorder.emit = lambda _event_type, _context, **extra: events.append(extra["input"])
        return recorder, events

    @staticmethod
    def mouse_data(x: int, y: int):
        mouse = MSLLHOOKSTRUCT()
        mouse.pt.x = x
        mouse.pt.y = y
        return mouse, ctypes.addressof(mouse)

    def test_default_logs_only_button_down_coordinates(self):
        recorder, events = self.recorder(record_mouse_moves=False)
        mouse, data = self.mouse_data(20, 30)
        recorder.mouse_proc(HC_ACTION, WM_MOUSEMOVE, data)
        recorder.mouse_proc(HC_ACTION, WM_LBUTTONDOWN, data)
        recorder.mouse_proc(HC_ACTION, WM_LBUTTONUP, data)
        recorder.mouse_proc(HC_ACTION, WM_MOUSEWHEEL, data)

        self.assertEqual(events[0], {"kind": "button", "detail": "left_down", "x": 20, "y": 30})
        self.assertEqual(events[1], {"kind": "button", "detail": "left_up"})
        self.assertEqual(events[2], {"kind": "wheel", "detail": 0})

    def test_opt_in_restores_mouse_move_coordinates(self):
        recorder, events = self.recorder(record_mouse_moves=True)
        mouse, data = self.mouse_data(20, 30)
        recorder.mouse_proc(HC_ACTION, WM_MOUSEMOVE, data)

        self.assertEqual(events, [{"kind": "move", "detail": None, "x": 20, "y": 30}])

    def test_records_physical_keydown(self):
        recorder, events = self.recorder(record_mouse_moves=False)
        recorder.modifier_state = lambda: {"ctrl": False, "shift": False, "alt": False}
        recorder.key_text = lambda *_: "a"
        key = KBDLLHOOKSTRUCT()
        key.vkCode = 0x41
        key.scanCode = 0x1E

        recorder.keyboard_proc(HC_ACTION, WM_KEYDOWN, ctypes.addressof(key))

        self.assertEqual(events, [{
            "kind": "key",
            "action": "down",
            "vk_code": 0x41,
            "scan_code": 0x1E,
            "modifiers": {"ctrl": False, "shift": False, "alt": False},
        }])

    def test_records_injected_keydown_only_when_enabled(self):
        key = KBDLLHOOKSTRUCT()
        key.vkCode = 0x41
        key.scanCode = 0x1E
        key.flags = LLKHF_INJECTED

        disabled_recorder, disabled_events = self.recorder(record_mouse_moves=False)
        disabled_recorder.keyboard_proc(HC_ACTION, WM_KEYDOWN, ctypes.addressof(key))

        enabled_recorder, enabled_events = self.recorder(record_mouse_moves=False, record_injected_key_events=True)
        enabled_recorder.modifier_state = lambda: {"ctrl": False, "shift": False, "alt": False}
        enabled_recorder.key_text = lambda *_: "a"
        enabled_recorder.keyboard_proc(HC_ACTION, WM_KEYDOWN, ctypes.addressof(key))

        self.assertEqual(disabled_events, [])
        self.assertEqual(enabled_events[0]["kind"], "key")

    def test_accepts_configured_cyberark_client_process(self):
        recorder = RdpRecorder(
            Path("unused.jsonl"),
            None,
            "unknown",
            False,
            True,
            ("psmrdp.exe",),
        )
        recorder.user32 = type("User32", (), {"GetForegroundWindow": staticmethod(lambda: 1)})()
        context = {"id": 1, "pid": 2, "title": "CyberArk session", "process": "PsmRdp.exe", "client_size": {"width": 1, "height": 1}}

        with patch("collectors.WindowsRdpCollector.window_context", return_value=context):
            self.assertEqual(recorder.target_context(), context)
