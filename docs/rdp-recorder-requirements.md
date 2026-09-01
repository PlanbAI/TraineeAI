# RDP Recorder And Replay Requirements

## Scope

TraineeAI records and replays input sent from a local Windows 10 or 11 machine to one explicitly selected `mstsc.exe` window. The remote desktop may run Windows or Linux. The first alpha requires no administrator privileges and no agent on the remote machine.

## User Controls

- Recording starts only after the user supplies a required RDP window-title substring.
- Only physical keyboard and mouse events while that matching `mstsc.exe` window is foreground are written.
- `Ctrl+Shift+F12` pauses or resumes recording. `Ctrl+Shift+F11` stops it.
- Replay is dry-run by default. Sending input requires an explicit `--execute` flag.
- Replay stops when the selected RDP window loses focus. It can require a manual checkpoint before sending input.

## Data Handling

- Keyboard and mouse input is recorded for replay fidelity.
- A terminal-like command buffer produces `rdp.command_submitted` after Enter. It labels commands as PowerShell, Bash, or unknown according to user configuration.
- Commands containing common secret markers are redacted before they are written.
- Clipboard contents are never read. Ctrl+V is recorded only as a paste marker, and scenarios containing paste markers cannot be replayed automatically.
- Command output, remote screen contents, and source code are not captured by the local-only alpha.

## Known Limits

- The local client cannot distinguish a remote terminal from a remote password prompt. Users must start recording only after authentication and stop it before entering secrets.
- Replay is sensitive to RDP client size, DPI, keyboard layout, remote UI state, and network delay. The recorder stores client size; replay rejects a size mismatch unless explicitly overridden.
- The local client cannot confirm that a remote application processed an action. A future optional user-level remote agent can provide execution confirmation and richer PowerShell/Bash semantics.

## Validation Status

The controller has passed compilation, unit tests, PowerShell parsing, local `mstsc` window targeting, physical input recording, JSONL analysis, and dry-run replay. It has not yet been tested against a live authorized RDP session, including end-to-end recording and `--execute` replay.
