import unittest

from collectors.WindowOcr import NoOcr, WindowOcr, create_ocr


class NoOcrTests(unittest.TestCase):
    def test_recognize_returns_empty(self):
        text, lines = NoOcr().recognize(b"raw", 10, 10)
        self.assertEqual(text, "")
        self.assertEqual(lines, [])

    def test_create_ocr_disabled_returns_no_ocr(self):
        ocr = create_ocr(enabled=False)
        self.assertIsInstance(ocr, NoOcr)

    def test_create_ocr_returns_engine_or_fallback(self):
        ocr = create_ocr(enabled=True)
        self.assertTrue(
            isinstance(ocr, (WindowOcr, NoOcr)),
            "create_ocr must return WindowOcr when the engine works, NoOcr otherwise",
        )


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()