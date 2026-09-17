#!/usr/bin/env python3
"""Local text recognition on top of the Windows 10/11 OCR engine.

Uses the ``winrt-Windows.Media.Ocr`` package (Microsoft's WinRT OCR), which
recognizes text locally using the languages installed with the operating
system. The engine is created once and reused; each call recognizes a raw
BGRA8 image and returns (full_text, line_details).
"""


class WindowOcr:
    def __init__(self, language_tag: str | None = None):
        self._engine = None
        self._compress_result = False
        if language_tag:
            self.language_tag = language_tag
        else:
            self.language_tag = None

    def _load_engine(self):
        if self._engine is not None:
            return self._engine
        from winrt.windows.media.ocr import OcrEngine

        if self.language_tag:
            from winrt.windows.globalization import Language

            engine = OcrEngine.try_create_from_language(Language(self.language_tag))
            if engine is None:
                raise RuntimeError(f"OCR engine for '{self.language_tag}' is not installed")
            self._engine = engine
            return engine
        engines = OcrEngine.available_recognizer_languages
        if not engines:
            raise RuntimeError("No Windows OCR languages are installed")
        self._engine = OcrEngine.try_create_from_language(engines[0])
        if self._engine is None:
            raise RuntimeError("Unable to create the Windows OCR engine")
        return self._engine

    def _recognize_async(self, software_bitmap):
        import asyncio

        async def run():
            result = await self._load_engine().recognize_async(software_bitmap)
            return result

        return asyncio.run(run())

    def _to_software_bitmap(self, rgba: bytes, width: int, height: int):
        from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
        from winrt.windows.storage.streams import DataWriter

        # Windows OCR expects BGRA8; reorder the RGBA bytes we capture.
        bgra = bytearray(len(rgba))
        for i in range(0, len(rgba), 4):
            bgra[i] = rgba[i + 2]
            bgra[i + 1] = rgba[i + 1]
            bgra[i + 2] = rgba[i]
            bgra[i + 3] = rgba[i + 3]
        writer = DataWriter()
        writer.write_bytes(bytes(bgra))
        buffer = writer.detach_buffer()
        return SoftwareBitmap.create_copy_from_buffer(buffer, BitmapPixelFormat.BGRA8, width, height)

    def recognize(self, rgba: bytes, width: int, height: int) -> tuple[str, list[dict]]:
        """Recognize text in an RGBA8 image.

        Returns (full_text, lines) where each line is
        {"x","y","w","h","text","words":[{"x","y","w","h","text"}]}.
        """
        from winrt.windows.foundation import Rect

        bitmap = self._to_software_bitmap(rgba, width, height)
        result = self._recognize_async(bitmap)
        lines: list[dict] = []
        for line in result.lines:
            line_rect = line.bounding_rect
            words = []
            for word in line.words:
                word_rect = word.bounding_rect
                words.append(
                    {
                        "x": round(word_rect.x),
                        "y": round(word_rect.y),
                        "w": round(word_rect.width),
                        "h": round(word_rect.height),
                        "text": word.text,
                    }
                )
            lines.append(
                {
                    "x": round(line_rect.x),
                    "y": round(line_rect.y),
                    "w": round(line_rect.width),
                    "h": round(line_rect.height),
                    "text": line.text,
                    "words": words,
                }
            )
        return result.text, lines


class NoOcr:
    """Fallback used when OCR is unavailable; stores the raw screenshot only."""

    def recognize(self, rgba: bytes, width: int, height: int) -> tuple[str, list[dict]]:
        return "", []


def create_ocr(language_tag: str | None = None, enabled: bool = True) -> object:
    """Create a WindowOcr or NoOcr instance based on availability."""
    if not enabled:
        return NoOcr()
    try:
        import winrt.windows.media.ocr  # noqa: F401
    except ImportError:
        return NoOcr()
    try:
        return WindowOcr(language_tag)
    except Exception:
        return NoOcr()