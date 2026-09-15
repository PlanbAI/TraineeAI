import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from collectors.KeyboardCollector import KeyboardRecorder, VK_BACK, VK_RETURN, VK_TAB


class KeyboardAggregationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "keyboard.jsonl"
        self.user32 = Mock()
        self.user32.GetAsyncKeyState.return_value = 0
        self.user32.GetForegroundWindow.return_value = 1
        with patch("collectors.KeyboardCollector.ctypes.windll.user32", self.user32):
            self.recorder = KeyboardRecorder(self.output, quiet=True)
        self.clock = patch("collectors.KeyboardCollector.time.monotonic", return_value=10.0).start()
        self.addCleanup(patch.stopall)

    def key(self, char=None, vk=65, up=False):
        with patch.object(self.recorder, "_decode_char", return_value=(char, False)) as decode:
            self.recorder.handle_key(vk, 0, not up, up)
            if up:
                decode.assert_not_called()

    def phrases(self):
        return [event for event in self.events() if event["type"] == "keyboard.phrase_submitted"]

    def events(self):
        return [json.loads(line) for line in self.output.read_text(encoding="utf-8").splitlines()]

    def test_idle_flush_preserves_unicode_words_and_ignores_releases(self):
        for char in "Привет café!":
            self.key(char)
            self.key(char, up=True)
        self.assertEqual(self.phrases(), [])
        self.clock.return_value = 10.6
        self.recorder.flush_pending()
        self.recorder.flush_pending()
        phrase, = self.phrases()
        self.assertEqual(phrase["text"], "Привет café!")
        self.assertEqual(phrase["words"], ["Привет", "café!"])
        self.assertTrue(phrase["phrase_start"].endswith("Z"))
        self.assertEqual(sum(e["type"] == "keyboard.key_down" for e in self.events()), 12)

    def test_backspace_and_enter(self):
        self.key("ab")
        self.key(vk=VK_BACK)
        self.key("c")
        self.key(vk=VK_RETURN)
        self.assertEqual(self.phrases()[0]["text"], "ac")

    def test_tab_navigation_and_shortcut_split_phrases(self):
        for boundary in (VK_TAB, 0x25, 0x2E):
            self.key("word")
            self.key(vk=boundary)
        self.key("last")
        with patch.object(self.recorder, "modifier_state", return_value={"ctrl": True, "alt": False, "shift": False}):
            self.key("v", vk=86)
        self.assertEqual([p["text"] for p in self.phrases()], ["word", "word", "word", "last"])

    def test_window_change_and_shutdown_flush_once(self):
        self.key("first")
        self.user32.GetForegroundWindow.return_value = 2
        self.recorder.flush_pending()
        self.key("second")
        self.recorder.close_phrase()
        self.recorder.close_phrase()
        self.assertEqual([p["text"] for p in self.phrases()], ["first", "second"])

    def test_message_loop_timer_flushes_without_another_key(self):
        self.key("idle")
        self.clock.return_value = 10.6
        self.user32.SetWindowsHookExW.return_value = 123
        self.user32.SetTimer.return_value = 456

        calls = []

        def message_result(*args):
            calls.append(True)
            if len(calls) == 1:
                return 1
            self.assertEqual(self.phrases()[0]["text"], "idle")
            return 0

        self.user32.GetMessageW.side_effect = message_result
        with patch("builtins.print"):
            self.recorder.run()
        self.user32.SetTimer.assert_called_once_with(None, 0, 50, None)
        self.user32.KillTimer.assert_called_once_with(None, 456)
        self.user32.UnhookWindowsHookEx.assert_called_once_with(123)


if __name__ == "__main__":
    unittest.main()
