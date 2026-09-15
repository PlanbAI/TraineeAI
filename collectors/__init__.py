"""Shared helpers and data collectors for browser, Linux, and Windows activity."""

import sys


def configure_stdio_utf8() -> None:
    """Force UTF-8 output on Windows regardless of the system code page.

    Without this, ``print`` on a pipe or console whose ANSI code page is
    cp1252 (or another legacy code page) raises UnicodeEncodeError for
    characters it cannot represent, taking the collector down.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError):
            pass
