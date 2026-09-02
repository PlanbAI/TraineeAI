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
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT_DIR / "windows-collectors-state.json"
LOG_FILE = ROOT_DIR / "windows-collectors.log"


def log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {message}\n")


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


def start_process(arguments: list[str], environment: dict[str, str], output) -> subprocess.Popen:
    return subprocess.Popen(
        arguments,
        cwd=ROOT_DIR,
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
    browser_collector = ROOT_DIR / "collectors" / "BrowserCollector.py"
    for collector in (desktop_collector, rdp_collector, browser_collector):
        if not collector.is_file():
            raise RuntimeError(f"Collector was not found: {collector}")

    environment = os.environ.copy()
    environment["CDP_HOST"] = "127.0.0.1"
    environment["CDP_PORT"] = str(args.cdp_port)
    processes: list[subprocess.Popen] = []
    started_browser: subprocess.Popen | None = None
    stop_requested = False

    def request_stop(_signal: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        with LOG_FILE.open("a", encoding="utf-8") as output:
            log("Starting Windows desktop, browser, and RDP collectors.")
            processes.append(start_process(
                [sys.executable, str(desktop_collector), "--output", args.desktop_output, "--interval", str(args.desktop_interval)],
                environment,
                output,
            ))
            rdp_arguments = [sys.executable, str(rdp_collector), "--auto-select", "--output", args.rdp_output, "--shell", args.rdp_shell]
            if args.record_mouse_moves:
                rdp_arguments.append("--record-mouse-moves")
            processes.append(start_process(
                rdp_arguments,
                environment,
                output,
            ))
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

        state = {
            "manager_pid": os.getpid(),
            "processes": [{"name": "desktop", "pid": processes[0].pid}, {"name": "rdp", "pid": processes[1].pid}, {"name": "browser", "pid": processes[2].pid}],
        }
        if started_browser:
            state["processes"].append({"name": "cdp_browser", "pid": started_browser.pid})
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
    parser.add_argument("--record-mouse-moves", action="store_true")
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
