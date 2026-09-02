# TraineeAI: Instructions for OpenCode

## Project Purpose

TraineeAI collects local desktop, browser, and optional RDP activity, then builds a normalized timeline and candidate task episodes. Read `docs/functional-requirements.md` before changing behavior. It is the bilingual baseline of implemented functionality.

## Supported Environments

- Windows 10 or 11 with Python 3 and an interactive desktop session.
- Ubuntu Desktop with an active X11 session, Python 3, and Chromium or Google Chrome.
- Do not treat SSH, headless sessions, macOS, or Wayland-only Linux sessions as supported capture environments.

## Running on a New Computer

Before running collectors, inspect the operating system, Python availability, repository files, and whether a virtual environment exists. Do not install packages unless a project command or an explicit user request requires it.

### Windows

From the repository root, start all standard Windows collectors in the background without PowerShell with:

```bat
scripts\start_windows_collectors.cmd
```

- The launcher starts desktop, browser, and waiting RDP collectors. Stop them with `scripts\stop_windows_collectors.cmd`.
- Inspect `windows-collectors.log` if the background launcher fails or a collector stops unexpectedly.
- It uses `.venv\Scripts\python.exe` when present, otherwise `python` from `PATH`.
- The browser launcher finds Chrome or Edge automatically. If it cannot, pass the installed executable through `--chrome-bin` to `scripts\start_windows_collectors.cmd`.
- For an interactive PowerShell session, use:

```powershell
.\scripts\run_windows_collectors.ps1
```

- The RDP recorder observes physical keyboard and mouse input. For RDP capture, start the launcher only after RDP authentication and stop it before entering passwords, tokens, or other secrets.
- Do not run replay with `-Execute` unless the user explicitly authorizes the target test session.

### Ubuntu

From the repository root, install system dependencies and run the full capture-and-analysis flow:

```bash
PROJECT_DIR="$PWD" bash scripts/ubuntu/install_linux_collector.sh
bash scripts/run_full_test.sh
```

The full test opens a dedicated CDP browser profile and waits for user interaction. Use only public or synthetic data.

## Verification

Run the unit tests after code changes:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

If `.venv` is absent, use `python -m unittest discover -s tests -v` after confirming that `python` is Python 3. On Ubuntu, also validate the shell scripts when relevant:

```bash
bash -n scripts/run_browser_collector.sh scripts/run_full_test.sh
```

## Safety and Data Handling

- Use only test, public, or synthetic data. Do not collect credentials, personal data, payment data, production accounts, or secret tokens.
- Do not read clipboard contents or add behavior that collects remote screens, remote command output, or source code without an explicit approved requirement.
- RDP capture is one selected `mstsc.exe` window per recorder. Multi-session RDP capture is planned in `TODO.md` and must not be described as implemented.

## Handling Launch Problems on Another Computer

When a launch, collector, dependency, browser discovery, PowerShell policy, or platform check fails:

1. Report the exact failing command, error text, operating system/version, Python version, and relevant collector log or stack trace.
2. Apply only a documented, low-risk remedy that matches the error, such as passing `--chrome-bin` to `run_windows_collectors.py` or using the interactive PowerShell launcher.
3. If the problem remains, or the required behavior is unsupported, explicitly offer to create a bug report or change request. Do not create an external issue unless the user asks.
4. A proposed bug/change request must include reproduction steps, expected and actual behavior, environment details, sanitized diagnostics, and a link to the applicable functional requirement when one exists.

## Documentation

- `docs/functional-requirements.md`: implemented functional requirements in Russian and English.
- `docs/rdp-recorder-requirements.md`: RDP capture and replay boundaries.
- `README.md`: setup and operator commands.
- `TODO.md`: planned but unimplemented work.
