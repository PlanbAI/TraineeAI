import io
import sys
import unittest

from collectors import configure_stdio_utf8


class StdioEncodingTests(unittest.TestCase):
    def test_configure_stdio_utf8_reconfigures_text_streams(self):
        original_stdout = sys.stdout
        try:
            captured = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
            sys.stdout = captured
            configure_stdio_utf8()
            self.assertEqual(captured.encoding, "utf-8")
            self.assertEqual(captured.errors, "backslashreplace")
        finally:
            sys.stdout = original_stdout

    def test_configure_stdio_utf8_tolerates_unconfigurable_streams(self):
        class NoReconfigure:
            pass

        original_stdout = sys.stdout
        try:
            sys.stdout = NoReconfigure()  # type: ignore[assignment]
            configure_stdio_utf8()
        finally:
            sys.stdout = original_stdout


if __name__ == "__main__":
    unittest.main()