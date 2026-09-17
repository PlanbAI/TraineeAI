#!/usr/bin/env python3
"""Capture a selected window as PNG and recognize text, with deduplication.

The screenshot is stored next to the JSONL output and the recognized text is
written to a ``.txt`` file with the same base name. Consecutive identical
frames are stored only once (the event still points at the stored file).
"""

import ctypes
import hashlib
import struct
import time
import zlib
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path


MAX_FRAMES_PER_SECOND = 2.0
MIN_INTERVAL_SECONDS = 1.0 / MAX_FRAMES_PER_SECOND


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def capture_window_rgba(hwnd: int) -> tuple[bytes, int, int] | None:
    """Capture a window's client area as raw RGBA bytes.

    Uses PrintWindow when available so occluded windows are still captured,
    then falls back to a plain BitBlt of the window DC.
    Returns (rgba_bytes, width, height) or None when the window is not
    visible or the capture fails.
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    screen_dc = user32.GetDC(0)
    window_dc = user32.GetDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    old_bitmap = gdi32.SelectObject(memory_dc, bitmap)

    PW_RENDERFULLCONTENT = 0x00000002
    ok = user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT)
    if not ok:
        ok = gdi32.BitBlt(memory_dc, 0, 0, width, height, window_dc, 0, 0, 0x00CC0020)

    rgba = None
    if ok:
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # top-down
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        rows = gdi32.GetDIBits(window_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
        if rows == height:
            raw = bytes(buffer.raw[: width * height * 4])
            rgba = _bgra_to_rgba(raw)

    gdi32.SelectObject(memory_dc, old_bitmap)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(hwnd, window_dc)
    user32.ReleaseDC(0, screen_dc)
    if rgba is None:
        return None
    return rgba, width, height


def _bgra_to_rgba(raw: bytes) -> bytes:
    return b"".join(bytes((raw[i + 2], raw[i + 1], raw[i], raw[i + 3])) for i in range(0, len(raw), 4))


def rgba_to_png(rgba: bytes, width: int, height: int) -> bytes:
    """Encode raw RGBA bytes into PNG without third-party image libraries."""
    rows = b"".join(b"\x00" + rgba[y * width * 4 : (y + 1) * width * 4] for y in range(height))
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )


def frame_hash(rgba: bytes) -> str:
    return hashlib.sha256(rgba).hexdigest()


class WindowScreenCapture:
    def __init__(
        self,
        screenshot_dir: Path,
        recognize_text: bool = True,
        ocr=None,
    ):
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.recognize_text = recognize_text
        self.ocr = ocr
        self.last_frame_hash: str | None = None
        self.last_stored_path: Path | None = None
        self._last_text = ""
        self._last_lines: list[dict] = []
        self._last_capture_at = 0.0
        self._command_seq = 0

    def _rate_limited(self) -> bool:
        now = time.monotonic()
        if now - self._last_capture_at < MIN_INTERVAL_SECONDS:
            return True
        self._last_capture_at = now
        return False

    def _next_filename(self, suffix: str, command_id: int | None) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3]
        if command_id is not None:
            return f"{command_id:06d}_{stamp}{suffix}"
        return f"{stamp}{suffix}"

    def capture_window(
        self,
        hwnd: int,
        command_id: int | None = None,
    ) -> dict | None:
        """Capture one window frame and run OCR.

        Returns event payload dict or None when rate-limited or unchanged.
        Public method used by collectors; calls private capture when not
        rate-limited.
        """
        if self._rate_limited():
            return None
        return self._capture(hwnd, command_id)

    def capture_window_forced(self, hwnd: int, command_id: int | None = None) -> dict | None:
        """Capture one window frame, bypassing the rate limit.

        Used for event-triggered shots (Enter, focus change) that must not
        be dropped even if a periodic frame fired a moment ago.
        """
        return self._capture(hwnd, command_id)

    def _capture(self, hwnd: int, command_id: int | None) -> dict | None:
        captured = capture_window_rgba(hwnd)
        if captured is None:
            return None
        rgba, width, height = captured
        digest = frame_hash(rgba)

        if self.last_frame_hash is not None and self.last_frame_hash == digest and self.last_stored_path is not None:
            # Identical to the previous frame: reuse the stored file, do not
            # write a new PNG or re-run OCR.
            return {
                "screenshot": self.last_stored_path.name,
                "screenshot_path": str(self.last_stored_path),
                "width": width,
                "height": height,
                "text": self._last_text or "",
                "lines": self._last_lines or [],
                "duplicate": True,
                "size_bytes": self.last_stored_path.stat().st_size,
            }

        self.last_frame_hash = digest

        name = self._next_filename(".png", command_id)
        png_path = self.screenshot_dir / name
        png_path.write_bytes(rgba_to_png(rgba, width, height))

        text = ""
        lines: list[dict] = []
        if self.recognize_text and self.ocr is not None:
            text, lines = self.ocr.recognize(rgba, width, height)
            txt_path = png_path.with_suffix(".txt")
            txt_path.write_text(text, encoding="utf-8")
        self._last_text = text
        self._last_lines = lines
        self.last_stored_path = png_path

        return {
            "screenshot": png_path.name,
            "screenshot_path": str(png_path),
            "width": width,
            "height": height,
            "text": text,
            "lines": lines,
            "duplicate": False,
            "size_bytes": png_path.stat().st_size,
        }