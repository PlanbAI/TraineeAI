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

## AI/LLM Integration

Run analysis with `--llm-payload-output` to create one grounded, schema-constrained LLM request per candidate episode. The recommended workflow is to send `llm-payloads.jsonl`, not raw keyboard, mouse, browser, or RDP logs, to an AI system.

See [Functional Requirements](docs/functional-requirements.md) for implemented product behavior and [AI/LLM Integration Guide](docs/ai-llm-integration.md) for artifact contracts, prompting rules, redaction boundaries, RDP-specific interpretation, and human-review requirements.

### Windows

Run these commands in Command Prompt to start the Windows desktop, browser, and waiting RDP collectors in the background without PowerShell.

```bat
git clone --branch aplha-version https://github.com/PlanbAI/TraineeAI.git
cd TraineeAI
scripts\start_windows_collectors.cmd
```

To stop the background collectors, run `scripts\stop_windows_collectors.cmd`. Diagnostics are written to `windows-collectors.log`. The PowerShell launcher `scripts\run_windows_collectors.ps1` remains available for an interactive session.

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

Windows collectors and the browser CDP collector use only the Python standard library. No `pip` installation is required. On Ubuntu, the installer uses `apt-get` to install the native X11, AT-SPI, and Chromium packages required by the Linux desktop collector.

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

From the repository root, start the Windows desktop collector, the browser collector with its dedicated Chrome, Chromium, or Edge profile, and the waiting RDP collector in the background without PowerShell:

```bat
scripts\start_windows_collectors.cmd
```

Perform the workflow in the browser window started by the script. Stop the collectors with `scripts\stop_windows_collectors.cmd`, then run the manual analysis command below. The RDP collector waits until an `mstsc.exe` window becomes active, selects that window, and records only its input. Start the launcher only after RDP authentication and do not enter secrets while recording. The Windows desktop collector records foreground-window changes only: application name, executable path, PID, window class, title, and window ID. It does not yet collect Windows UI Automation control-level events.

RDP mouse movement is not logged by default. To restore detailed mouse movement logging, add `--record-mouse-moves` to `scripts\start_windows_collectors.cmd` or `-RecordMouseMoves` to either PowerShell RDP launcher.

### Windows RDP Recording And Replay

The RDP alpha records input only for one explicitly selected Microsoft Remote Desktop (`mstsc.exe`) window. Start recording after signing in to the remote system and stop it before entering credentials or secrets.

```powershell
.\scripts\run_rdp_recorder.ps1 -WindowTitle "server-01" -Shell powershell -Output rdp-events.jsonl
```

`Ctrl+Shift+F12` pauses or resumes recording. `Ctrl+Shift+F11` stops it. The recorder stores raw physical input for replay and creates `rdp.command_submitted` events when Enter is pressed. Clipboard contents are never read; pasted commands cannot be replayed automatically.

Analyze the resulting log with:

```powershell
python -m analysis.analyze --desktop rdp-events.jsonl --output test-output\rdp-episodes.jsonl --timeline-output test-output\rdp-timeline.jsonl
```

Replay is dry-run by default and requires the target RDP window to be focused and have the same client size as the recording:

```powershell
.\scripts\run_rdp_replay.ps1 -Scenario rdp-events.jsonl -WindowTitle "server-01"
```

After verifying the dry run, send input only to an authorized test session:

```powershell
.\scripts\run_rdp_replay.ps1 -Scenario rdp-events.jsonl -WindowTitle "server-01" -Execute -CheckpointBefore
```

See [RDP recorder requirements](docs/rdp-recorder-requirements.md) for privacy boundaries and known limits.

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

See [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) for the component map, [AI/LLM Integration Guide](docs/ai-llm-integration.md) for AI consumers, and [docs/ubuntu-virtualbox-test.md](docs/ubuntu-virtualbox-test.md) for the VirtualBox test environment.
