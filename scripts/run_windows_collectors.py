#!/usr/bin/env python3
"""Run standard Windows collectors without requiring PowerShell."""

import argparse
import ctypes
import json
import os
import signal
import socket
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT_DIR / "windows-collectors-state.json"
LOG_FILE = ROOT_DIR / "windows-collectors.log"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log(message: str, output=None) -> None:
    timestamp = now_iso()
    line = f"{timestamp} {message}\n"
    if output is not None:
        output.write(line)
        output.flush()
        return
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line)


def cdp_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def find_browser(configured_path: str | None) -> Path:
    if configured_path:
        browser = Path(configured_path)
        if browser.is_file():
            return browser
        raise RuntimeError(f"Browser executable was not found: {browser}")

    candidates = []
    for environment_variable, relative_path in (
        ("ProgramFiles", "Google\\Chrome\\Application\\chrome.exe"),
        ("ProgramFiles(x86)", "Google\\Chrome\\Application\\chrome.exe"),
        ("LocalAppData", "Google\\Chrome\\Application\\chrome.exe"),
        ("ProgramFiles", "Microsoft\\Edge\\Application\\msedge.exe"),
    ):
        directory = os.environ.get(environment_variable)
        if directory:
            candidates.append(Path(directory) / relative_path)

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("Chrome, Chromium, or Edge was not found. Pass --chrome-bin with its executable path.")


def process_is_running(pid: int) -> bool:
    process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not ctypes.windll.kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
            return False
        return exit_code.value == 259
    finally:
        ctypes.windll.kernel32.CloseHandle(process)


def load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def stop_process(pid: int) -> None:
    if process_is_running(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)


def stop_collectors() -> int:
    state = load_state()
    if not state:
        print("Windows collectors are not running.")
        return 0

    stop_process(state.get("manager_pid", 0))
    for process in reversed(state.get("processes", [])):
        stop_process(process["pid"])
    STATE_FILE.unlink(missing_ok=True)
    log("Windows collectors stopped.")
    print("Windows collectors stopped.")
    return 0


def start_process(
    arguments: list[str], environment: dict[str, str], output, cwd: Path = ROOT_DIR
) -> subprocess.Popen:
    return subprocess.Popen(
        arguments,
        cwd=cwd,
        env=environment,
        stdout=output,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def terminate_processes(processes: list[subprocess.Popen]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def run_collectors(args: argparse.Namespace) -> int:
    if sys.platform != "win32":
        raise RuntimeError("run_windows_collectors.py must run on Windows")

    state = load_state()
    if state and process_is_running(state.get("manager_pid", 0)):
        raise RuntimeError("Windows collectors are already running. Use stop_windows_collectors.cmd first.")
    STATE_FILE.unlink(missing_ok=True)

    desktop_collector = ROOT_DIR / "collectors" / "WindowsCollector.py"
    rdp_collector = ROOT_DIR / "collectors" / "WindowsRdpCollector.py"
    cyberark_collector = ROOT_DIR / "collectors" / "WindowsCyberArkCollector.py"
    browser_collector = ROOT_DIR / "collectors" / "BrowserCollector.py"
    keyboard_collector = ROOT_DIR / "collectors" / "KeyboardCollector.py"
    for collector in (desktop_collector, rdp_collector, cyberark_collector, browser_collector, keyboard_collector):
        if not collector.is_file():
            raise RuntimeError(f"Collector was not found: {collector}")
    environment = os.environ.copy()
    environment["CDP_HOST"] = "127.0.0.1"
    environment["CDP_PORT"] = str(args.cdp_port)
    environment["PYTHONIOENCODING"] = "utf-8"
    if args.cyberark_browser_url_pattern and args.cyberark_browser_selector:
        environment["CYBERARK_TERMINAL_URL_PATTERN"] = args.cyberark_browser_url_pattern
        environment["CYBERARK_TERMINAL_SELECTOR"] = args.cyberark_browser_selector
        environment["CYBERARK_TERMINAL_SHELL"] = args.cyberark_browser_shell
    processes: list[subprocess.Popen] = []
    started_browser: subprocess.Popen | None = None
    kb_collector_process: subprocess.Popen | None = None
    stop_requested = False

    def request_stop(_signal: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        with LOG_FILE.open("a", encoding="utf-8") as output:
            log("Starting Windows desktop, browser, RDP, and keyboard collectors.")
            processes.append(start_process(
                [sys.executable, str(desktop_collector), "--output", args.desktop_output, "--interval", str(args.desktop_interval)],
                environment,
                output,
            ))
            rdp_arguments = [sys.executable, str(rdp_collector), "--auto-select", "--output", args.rdp_output, "--shell", args.rdp_shell]
            if args.record_mouse_moves:
                rdp_arguments.append("--record-mouse-moves")
            if args.record_injected_key_events:
                rdp_arguments.append("--record-injected-key-events")
            if args.no_screenshots:
                rdp_arguments.append("--no-screenshots")
            else:
                if args.screenshot_dir:
                    rdp_arguments.extend(("--screenshot-dir", str(Path(args.screenshot_dir).resolve())))
                if args.ocr_language:
                    rdp_arguments.extend(("--ocr-language", args.ocr_language))
            processes.append(start_process(
                rdp_arguments,
                environment,
                output,
            ))
            cyberark_arguments = [sys.executable, str(cyberark_collector), "--output", args.cyberark_output, "--shell", args.cyberark_shell]
            for process_name in args.cyberark_process_name:
                cyberark_arguments.extend(("--process-name", process_name))
            if args.record_mouse_moves:
                cyberark_arguments.append("--record-mouse-moves")
            processes.append(start_process(cyberark_arguments, environment, output))
            time.sleep(1)
            if any(process.poll() is not None for process in processes):
                raise RuntimeError(f"A collector exited immediately. See {LOG_FILE}")

            if not cdp_ready(args.cdp_port):
                browser = find_browser(args.chrome_bin)
                profile_directory = Path(args.profile_directory)
                profile_directory.mkdir(parents=True, exist_ok=True)
                started_browser = subprocess.Popen([
                    str(browser),
                    "--remote-debugging-address=127.0.0.1",
                    f"--remote-debugging-port={args.cdp_port}",
                    f"--user-data-dir={profile_directory}",
                    "--new-window",
                    "about:blank",
                    "--no-first-run",
                    "--no-default-browser-check",
                ], cwd=ROOT_DIR)
                for _ in range(40):
                    if cdp_ready(args.cdp_port):
                        break
                    time.sleep(0.25)
                if not cdp_ready(args.cdp_port):
                    raise RuntimeError(f"Browser started but CDP is unavailable on port {args.cdp_port}.")

            processes.append(start_process([sys.executable, str(browser_collector)], environment, output))
            time.sleep(1)
            if processes[-1].poll() is not None:
                raise RuntimeError(f"Browser collector exited immediately. See {LOG_FILE}")

            if not args.no_keyboard_collector:
                keyboard_output_path = Path(args.keyboard_output).resolve()
                keyboard_output_path.parent.mkdir(parents=True, exist_ok=True)
                kb_collector_process = start_process(
                    [
                        sys.executable,
                        str(keyboard_collector),
                        "--output",
                        str(keyboard_output_path),
                        "--quiet",
                    ],
                    environment,
                    output,
                )
                processes.append(kb_collector_process)
                time.sleep(1)
                if kb_collector_process.poll() is not None:
                    raise RuntimeError(f"Keyboard collector exited immediately. See {LOG_FILE}")
                log(f"Keyboard collector started. Output: {keyboard_output_path}")

        state = {
            "manager_pid": os.getpid(),
            "processes": [
                {"name": "desktop", "pid": processes[0].pid},
                {"name": "rdp", "pid": processes[1].pid},
                {"name": "cyberark", "pid": processes[2].pid},
                {"name": "browser", "pid": processes[3].pid},
            ],
        }
        if started_browser:
            state["processes"].append({"name": "cdp_browser", "pid": started_browser.pid})
        if kb_collector_process:
            state["processes"].append({"name": "keyboard", "pid": kb_collector_process.pid})
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        log(f"Windows collectors started. State: {STATE_FILE}")

        deadline = time.monotonic() + args.duration_seconds if args.duration_seconds else None
        while not stop_requested and (deadline is None or time.monotonic() < deadline):
            if any(process.poll() is not None for process in processes):
                raise RuntimeError(f"A collector stopped unexpectedly. See {LOG_FILE}")
            time.sleep(1)
    finally:
        terminate_processes(processes)
        if started_browser and started_browser.poll() is None:
            started_browser.terminate()
        STATE_FILE.unlink(missing_ok=True)
        log("Windows collector manager stopped.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Windows collectors in the background without PowerShell.")
    parser.add_argument("--background", action="store_true", help="Detach the collector manager from the calling process")
    parser.add_argument("--stop", action="store_true", help="Stop collectors started by this launcher")
    parser.add_argument("--chrome-bin", help="Path to Chrome, Chromium, or Edge")
    parser.add_argument("--cdp-port", type=int, default=9222)
    parser.add_argument("--profile-directory", default=str(Path.home() / ".traineeai-cdp-profile"))
    parser.add_argument("--duration-seconds", type=int, default=0)
    parser.add_argument("--desktop-output", default="events.jsonl")
    parser.add_argument("--desktop-interval", type=float, default=0.2)
    parser.add_argument("--rdp-output", default="rdp-events.jsonl")
    parser.add_argument("--rdp-shell", choices=("unknown", "powershell", "bash"), default="unknown")
    parser.add_argument("--cyberark-output", default="cyberark-events.jsonl")
    parser.add_argument("--cyberark-shell", choices=("unknown", "powershell", "bash"), default="unknown")
    parser.add_argument("--cyberark-process-name", action="append", default=[])
    parser.add_argument("--cyberark-browser-url-pattern")
    parser.add_argument("--cyberark-browser-selector")
    parser.add_argument("--cyberark-browser-shell", choices=("unknown", "powershell", "bash"), default="unknown")
    parser.add_argument(
        "--no-keyboard-collector",
        action="store_true",
        help="Do not start the local keyboard collector (it runs by default; use only synthetic or public data).",
    )
    parser.add_argument(
        "--keyboard-output",
        default="keyboard-events.jsonl",
        help="Output file for the local keyboard collector.",
    )
    parser.add_argument("--record-mouse-moves", action="store_true")
    parser.add_argument("--record-injected-key-events", action="store_true")
    parser.add_argument("--screenshot-dir", help="Directory for RDP window screenshots (default: <rdp-output>/screenshots)")
    parser.add_argument("--ocr-language", help="Windows OCR language tag for screen text, e.g. en-US or ru-RU")
    parser.add_argument(
        "--no-screenshots",
        action="store_true",
        help="Disable RDP window screenshot capture with OCR",
    )
    args = parser.parse_args()
    if args.background:
        if args.stop:
            parser.error("--background cannot be combined with --stop")
        command = [sys.executable, str(Path(__file__).resolve())]
        command.extend(argument for argument in sys.argv[1:] if argument != "--background")
        subprocess.Popen(
            command,
            cwd=ROOT_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            ),
        )
        return 0
    if args.stop:
        return stop_collectors()
    if args.duration_seconds < 0:
        parser.error("--duration-seconds must not be negative")
    if args.desktop_interval <= 0:
        parser.error("--desktop-interval must be greater than zero")
    return run_collectors(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        log(f"ERROR: {error}")
        raise SystemExit(f"ERROR: {error}")
