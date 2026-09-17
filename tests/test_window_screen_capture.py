import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collectors.WindowScreenCapture import WindowScreenCapture


class FakeOcr:
    def __init__(self):
        self.calls = 0

    def recognize(self, rgba: bytes, width: int, height: int):
        self.calls += 1
        lines = [{"x": 0, "y": 0, "w": 10, "h": 5, "text": "hello", "words": [{"x": 0, "y": 0, "w": 10, "h": 5, "text": "hello"}]}]
        return "hello", lines


@unittest.skipUnless(sys.platform == "win32", "Window capture uses the Windows GDI")
class WindowScreenCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="trainee-screenshot-"))
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.screenshot_dir = self.temp_dir / "screenshots"
        self.rgba = bytes(range(256)) * (16 * 16)  # 16x16 RGBA

    def capture(self, ocr=None, recognize_text=True):
        return WindowScreenCapture(self.screenshot_dir, recognize_text=recognize_text, ocr=ocr)

    @patch("collectors.WindowScreenCapture.capture_window_rgba", return_value=(b"", 16, 16))
    def test_stores_png_and_txt_when_text_recognized(self, _capture):
        fake = FakeOcr()
        screen = self.capture(ocr=fake)
        event = screen.capture_window_forced(1, command_id=3)

        self.assertFalse(event["duplicate"])
        self.assertIsNotNone(event["screenshot_path"])
        png_path = Path(event["screenshot_path"])
        self.assertTrue(png_path.exists())
        self.assertEqual(png_path.suffix, ".png")
        self.assertEqual(png_path.stem[:6], "000003")
        self.assertTrue(png_path.with_suffix(".txt").exists())
        self.assertEqual(png_path.with_suffix(".txt").read_text(encoding="utf-8"), "hello")
        self.assertEqual(event["text"], "hello")
        self.assertEqual(event["lines"][0]["text"], "hello")
        self.assertEqual(fake.calls, 1)

    @patch("collectors.WindowScreenCapture.capture_window_rgba", return_value=(b"", 16, 16))
    def test_duplicate_frames_store_only_one_file(self, _capture):
        screen = self.capture(ocr=FakeOcr())
        first = screen.capture_window_forced(1, command_id=1)
        second = screen.capture_window_forced(1, command_id=2)

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["screenshot_path"], second["screenshot_path"])
        self.assertEqual(unsigned_files(screen.screenshot_dir, ".png"), 1)
        self.assertEqual(unsigned_files(screen.screenshot_dir, ".txt"), 1)

    @patch("collectors.WindowScreenCapture.capture_window_rgba", return_value=(b"", 16, 16))
    def test_rate_limited_capture_returns_none(self, _capture):
        screen = self.capture()
        first = screen.capture_window(1)
        second = screen.capture_window(1)

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    @patch("collectors.WindowScreenCapture.capture_window_rgba", return_value=(b"", 16, 16))
    def test_forced_capture_bypasses_rate_limit(self, _capture):
        screen = self.capture(ocr=FakeOcr())
        first = screen.capture_window(1)
        forced = screen.capture_window_forced(1, command_id=1)

        self.assertIsNotNone(first)
        self.assertIsNotNone(forced)

    @patch("collectors.WindowScreenCapture.capture_window_rgba", return_value=None)
    def test_unavailable_window_returns_none(self, _capture):
        screen = self.capture()
        self.assertIsNone(screen.capture_window_forced(1))

    def test_no_ocr_writes_png_without_txt(self):
        rgba = b"\x00\x00\x00\xff" * (16 * 16)
        with patch("collectors.WindowScreenCapture.capture_window_rgba", return_value=(rgba, 16, 16)):
            screen = WindowScreenCapture(self.screenshot_dir, recognize_text=False, ocr=None)
            event = screen.capture_window_forced(1)

        self.assertEqual(event["text"], "")
        self.assertEqual(event["lines"], [])
        png_path = Path(event["screenshot_path"])
        self.assertTrue(png_path.exists())
        self.assertFalse(png_path.with_suffix(".txt").exists())


def unsigned_files(directory: Path, suffix: str) -> int:
    return sum(1 for _ in directory.glob(f"*{suffix}"))


if __name__ == "__main__":
    unittest.main()