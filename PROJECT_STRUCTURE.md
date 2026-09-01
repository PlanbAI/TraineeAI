# Project Structure

## Purpose

The project records Linux and Windows desktop activity, Chromium browser activity, and optional Windows RDP input, then deterministically builds candidate user-task episodes.

## File Tree

```text
Trainee/
|- analysis/
|  |- analyze.py
|  |- llm_payload.py
|  |- models.py
|  |- normalize.py
|  `- pipeline.py
|- collectors/
|  |- __init__.py
|  |- BrowserCollector.py
|  |- LinuxCollector.py
|  |- WindowsCollector.py
|  |- WindowsRdpCollector.py
|  `- WindowsRdpReplay.py
|  |- watcher_x11.py
|  `- watcher_x11_gi.py
|- scripts/
|  |- run_analysis_test.sh
|  |- run_browser_collector.ps1
|  |- run_browser_collector.sh
|  |- run_rdp_recorder.ps1
|  |- run_rdp_replay.ps1
|  |- run_capture.sh
|  `- run_full_test.sh
|- docs/
|  |- ai-llm-integration.md
|  |- rdp-recorder-requirements.md
|  `- ubuntu-virtualbox-test.md
|- tests/
|  `- test_preprocessing.py
|- browser_listener.js
|- .idea/
|- .venv/
`- .git/
```

## Components

- `collectors/watcher_x11.py` polls the X11 active-window property and prints a timestamp, window ID, process ID, and title when the focused window changes.
- `collectors/watcher_x11_gi.py` uses AT-SPI through PyGObject to list applications and print the selected application's accessibility tree.
- `collectors/BrowserCollector.py` connects to Chrome DevTools Protocol on `127.0.0.1:9222`, injects `browser_listener.js` into browser pages, and writes captured events to `browser-events.jsonl`.
- `collectors/LinuxCollector.py` combines X11 window context and AT-SPI UI semantics, writing privacy-preserving desktop events to `events.jsonl`.
- `collectors/WindowsCollector.py` records foreground Windows application changes in the same desktop JSONL format.
- `collectors/WindowsRdpCollector.py` records input for one explicitly selected `mstsc.exe` window, and `collectors/WindowsRdpReplay.py` provides guarded replay.
- `analysis/` normalizes both logs, enriches the unified timeline, reduces input noise, segments sessions and builds candidate episodes.
- `scripts/` provides manual capture and end-to-end analysis commands.
- Windows and browser collectors use only the Python standard library. The Ubuntu installer installs native X11 and AT-SPI packages with `apt-get`.

## Service Directories

- `.idea/` contains PyCharm project settings.
- `.venv/` is the local Python virtual environment.
- `.git/` contains Git repository metadata.

## Notes

- `browser-events.jsonl` and `events.jsonl` are generated at runtime and are not currently present in the repository.
