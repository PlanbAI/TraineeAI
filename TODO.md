# TODO

- [ ] Add multi-session RDP capture: run one collector per `mstsc.exe` window, bind it to the window HWND, write separate JSONL logs, and stop it when the window closes.
- [ ] Compare `rdp.command_submitted` against `app.screen_text` from FR-27 and pick a deduplication strategy: keep both event types or drop one when they overlap.
