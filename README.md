# TraineeAI

TraineeAI records activity in a Linux or Windows desktop session and Chromium, then builds a normalized timeline and candidate user-task episodes. This alpha version supports Ubuntu Desktop with X11 and Windows 10 or 11.

## Quick Start

### Ubuntu

Run these commands in an Ubuntu Desktop terminal. Use test data only.

```bash
git clone --branch aplha-version https://github.com/PlanbAI/TraineeAI.git
cd TraineeAI
PROJECT_DIR="$PWD" bash scripts/ubuntu/install_linux_collector.sh
bash scripts/run_full_test.sh
```

The script opens a separate Chromium profile, starts the desktop and browser collectors, and waits for you to press Enter. Perform the workflow in the Chromium window opened by the script. When finished, return to the terminal and press Enter.

Results are written to `test-output/`:

- `timeline.jsonl`: normalized, reduced event timeline.
- `episodes.jsonl`: candidate user-task episodes.
- `llm-payloads.jsonl`: one analysis payload per episode.
- `*-collector.stdout.log` and `*-collector.stderr.log`: collector diagnostics.

### Windows

Run these commands in PowerShell. The two collector commands run in separate PowerShell windows.

```powershell
git clone --branch aplha-version https://github.com/PlanbAI/TraineeAI.git
cd TraineeAI
py -m pip install -r requirements.txt
python .\collectors\WindowsCollector.py
```

In a second PowerShell window opened in the same repository, run:

```powershell
.\scripts\run_browser_collector.ps1
```

When the workflow is complete, stop both collectors with Ctrl+C and run the manual analysis command in [Manual Analysis](#manual-analysis).

## What Is Captured

- Linux active-window context and accessible UI events through X11 and AT-SPI.
- Chromium navigation, clicks, focus, keyboard events, form submission, and ordinary text input through Chrome DevTools Protocol.
- Browser and desktop events are normalized into a shared timeline before episode construction.

Password fields and fields whose metadata indicates common sensitive data, such as tokens, card numbers, or CVV values, are marked for redaction. This is an alpha build, so do not use credentials, personal data, payment data, production accounts, or secret tokens.

## Detailed Setup

### Supported Environment

- Ubuntu Desktop with an active X11 graphical session.
- Python 3.
- Chromium or Google Chrome. Ubuntu's Snap Chromium is supported.
- A local terminal session, not SSH or a headless server.

The installer installs the required system dependencies:

```bash
PROJECT_DIR="$PWD" bash scripts/ubuntu/install_linux_collector.sh
```

`PROJECT_DIR="$PWD"` is required after cloning the repository normally. If the repository is mounted into a VirtualBox guest at `/media/sf_TraineeAI`, the default installer command also works:

```bash
bash /media/sf_TraineeAI/scripts/ubuntu/install_linux_collector.sh
```

### Full Capture And Analysis

From the repository root, run:

```bash
bash scripts/run_full_test.sh
```

The script performs the following steps:

1. Finds Chromium or Chrome and launches a dedicated CDP-enabled profile.
2. Starts `collectors/LinuxCollector.py` and `collectors/BrowserCollector.py`.
3. Waits for Enter while the workflow is performed in the dedicated browser window.
4. Stops the collectors and runs `python3 -m analysis.analyze`.

The CDP browser profile is separate from the user's normal browser profile. With Snap Chromium, the script automatically stores it under `~/snap/chromium/common/` because Snap restricts profile locations.

### Manual Browser-Only Capture

To test browser collection independently, run:

```bash
bash scripts/run_browser_collector.sh
```

Set `DURATION_SEC` for an automatic stop:

```bash
DURATION_SEC=60 bash scripts/run_browser_collector.sh
```

This writes `browser-events.jsonl` in the repository root. To connect to an already CDP-enabled browser, set `CDP_PORT` and start the collector; otherwise the script starts its own browser instance.

### Windows Capture

Open two PowerShell windows in the repository root. In the first window, start the Windows desktop collector:

```powershell
python .\collectors\WindowsCollector.py
```

In the second window, start the browser collector and its dedicated Chrome, Chromium, or Edge profile:

```powershell
.\scripts\run_browser_collector.ps1
```

Perform the workflow in the browser window started by the script. Stop both collectors with Ctrl+C, then run the manual analysis command below. The Windows desktop collector records foreground-window changes only: application name, executable path, PID, window class, title, and window ID. It does not yet collect Windows UI Automation control-level events.

### Manual Analysis

Existing collector logs can be analyzed without starting collectors:

```bash
python3 -m analysis.analyze \
  --desktop events.jsonl \
  --browser browser-events.jsonl \
  --output test-output/episodes.jsonl \
  --timeline-output test-output/timeline.jsonl \
  --llm-payload-output test-output/llm-payloads.jsonl
```

At least one of `--desktop` or `--browser` must be supplied.

## Alpha Testing

Use a short, reproducible workflow with public or synthetic data. Suggested workflow:

1. Open a public search page in the dedicated Chromium window.
2. Search for a non-sensitive term and open one result.
3. Use ordinary navigation, buttons, and a non-sensitive form field.
4. Stop the capture with Enter.
5. Compare `test-output/timeline.jsonl` and `test-output/episodes.jsonl` with the actions actually performed.

When reporting feedback, include:

- Ubuntu version, desktop session type, browser, and browser version.
- The intended workflow in plain language.
- Which action was missing, duplicated, or described incorrectly.
- The relevant files from `test-output/` and collector diagnostic logs, after checking them for sensitive data.

Known alpha limitations:

- Modern web applications can emit duplicate input events through visible and internal form elements.
- Keyboard navigation produces many focus and key events that may not correspond to distinct user tasks.
- Opening a context menu is captured, but the specific menu command selected is not always observable.
- Page text and long URLs can add noise to raw browser logs.

## Development Checks

Run the unit tests and shell syntax checks from the repository root:

```bash
python -m unittest discover -s tests -v
bash -n scripts/run_browser_collector.sh scripts/run_full_test.sh
```

## Project Layout

See [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) for the component map and [docs/ubuntu-virtualbox-test.md](docs/ubuntu-virtualbox-test.md) for the VirtualBox test environment.
