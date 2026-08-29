# Project Structure

## Purpose

The project records Linux desktop and Chrome browser activity, then deterministically builds candidate user-task episodes.

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
|  |- watcher_x11.py
|  `- watcher_x11_gi.py
|- scripts/
|  |- run_analysis_test.sh
|  |- run_browser_collector.ps1
|  |- run_browser_collector.sh
|  |- run_capture.sh
|  `- run_full_test.sh
|- docs/
|  `- ubuntu-virtualbox-test.md
|- tests/
|  `- test_preprocessing.py
|- browser_listener.js
|- requirements.txt
|- .idea/
|- .venv/
`- .git/
```

## Components

- `collectors/watcher_x11.py` polls the X11 active-window property and prints a timestamp, window ID, process ID, and title when the focused window changes.
- `collectors/watcher_x11_gi.py` uses AT-SPI through PyGObject to list applications and print the selected application's accessibility tree.
- `collectors/BrowserCollector.py` connects to Chrome DevTools Protocol on `127.0.0.1:9222`, injects `browser_listener.js` into browser pages, and writes captured events to `browser-events.jsonl`.
- `collectors/LinuxCollector.py` combines X11 window context and AT-SPI UI semantics, writing privacy-preserving desktop events to `events.jsonl`.
- `analysis/` normalizes both logs, enriches the unified timeline, reduces input noise, segments sessions and builds candidate episodes.
- `scripts/` provides manual capture and end-to-end analysis commands.
- `requirements.txt` lists Python dependencies, including Linux-only X11 and AT-SPI bindings.

## Service Directories

- `.idea/` contains PyCharm project settings.
- `.venv/` is the local Python virtual environment.
- `.git/` contains Git repository metadata.

## Notes

- `browser-events.jsonl` and `events.jsonl` are generated at runtime and are not currently present in the repository.
