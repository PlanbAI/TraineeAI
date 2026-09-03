#!/usr/bin/env python3
"""Record input for CyberArk PSM client windows using the shared RDP hooks."""

import argparse
import sys
from pathlib import Path

from WindowsRdpCollector import RdpRecorder


DEFAULT_PROCESS_NAMES = (
    "psmrdp.exe",
    "psmconnect.exe",
    "cyberarkpsm.exe",
    "cyberarkpsmclient.exe",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record input for one selected CyberArk PSM client window.")
    parser.add_argument("--window-title", help="Optional substring of the selected CyberArk window title")
    parser.add_argument(
        "--process-name",
        action="append",
        default=list(DEFAULT_PROCESS_NAMES),
        help="CyberArk PSM client executable name; may be passed more than once",
    )
    parser.add_argument("--output", type=Path, default=Path("cyberark-events.jsonl"))
    parser.add_argument("--shell", choices=("unknown", "powershell", "bash"), default="unknown")
    parser.add_argument("--record-mouse-moves", action="store_true", help="Record mouse movement and all mouse coordinates")
    parser.add_argument(
        "--ignore-injected-key-events",
        action="store_true",
        help="Disable the default CyberArk diagnostic capture of injected keyboard events",
    )
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("WindowsCyberArkCollector.py must run on Windows")
    if args.window_title is not None and not args.window_title.strip():
        parser.error("--window-title must not be blank")
    process_names = tuple(process_name.casefold() for process_name in args.process_name if process_name.strip())
    if not process_names:
        parser.error("at least one non-blank --process-name is required")

    print("Waiting for an active CyberArk PSM client window to select.")
    print("Injected keyboard events are recorded for CyberArk diagnostics.")
    print("Do not record passwords, tokens, or other secrets.")
    RdpRecorder(
        args.output,
        args.window_title,
        args.shell,
        args.record_mouse_moves,
        not args.ignore_injected_key_events,
        process_names,
        use_raw_keyboard=True,
    ).run()


if __name__ == "__main__":
    main()
