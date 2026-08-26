#!/usr/bin/env python3

import json
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi
from Xlib import X, display, error

OUTPUT_FILE = Path("events.jsonl")

IGNORED_APPLICATIONS = {
    "gnome-shell",
    "ibus",
    "xdg-desktop-portal",
    "gnome-settings-daemon",
}

stop_event = threading.Event()
write_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def read_process_name(pid: Optional[int]) -> Optional[str]:
    if not pid:
        return None
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
    except (OSError, PermissionError):
        return None


def normalize_name(name: Optional[str]) -> str:
    return name.strip().lower() if name else ""


def is_ignored(*names: Optional[str]) -> bool:
    normalized = {normalize_name(name) for name in names if name}
    return bool(normalized & IGNORED_APPLICATIONS)


def emit_event(event: dict) -> None:
    event.setdefault("timestamp", now_iso())

    app = event.get("application") or {}
    if is_ignored(app.get("name"), app.get("wm_class"), app.get("atspi_name")):
        return

    line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    with write_lock:
        with OUTPUT_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(line, flush=True)


class X11Collector:
    def __init__(self):
        self.display = display.Display()
        self.root = self.display.screen().root
        self.atom_active_window = self.display.intern_atom("_NET_ACTIVE_WINDOW")
        self.atom_wm_pid = self.display.intern_atom("_NET_WM_PID")
        self.atom_net_wm_name = self.display.intern_atom("_NET_WM_NAME")
        self.atom_utf8 = self.display.intern_atom("UTF8_STRING")
        self.last_window_id = None

    def start(self) -> None:
        self.root.change_attributes(event_mask=X.PropertyChangeMask)
        self.emit_active_window()

        while not stop_event.is_set():
            try:
                event = self.display.next_event()
            except Exception:
                if stop_event.is_set():
                    return
                raise

            if event.type == X.PropertyNotify and event.atom == self.atom_active_window:
                self.emit_active_window()

    def _active_window_id(self) -> Optional[int]:
        prop = self.root.get_full_property(self.atom_active_window, X.AnyPropertyType)
        if not prop or not prop.value:
            return None
        return int(prop.value[0])

    def emit_active_window(self) -> None:
        window_id = self._active_window_id()
        if not window_id or window_id == self.last_window_id:
            return

        self.last_window_id = window_id

        try:
            window = self.display.create_resource_object("window", window_id)
        except error.XError:
            return

        pid = None
        title = ""
        wm_class = None

        try:
            prop = window.get_full_property(self.atom_wm_pid, X.AnyPropertyType)
            if prop and prop.value:
                pid = int(prop.value[0])
        except error.XError:
            pass

        try:
            prop = window.get_full_property(self.atom_net_wm_name, self.atom_utf8)
            if prop and prop.value:
                value = prop.value
                title = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
            else:
                title = window.get_wm_name() or ""
        except Exception:
            pass

        try:
            cls = window.get_wm_class()
            if cls:
                wm_class = cls[-1]
        except Exception:
            pass

        process_name = read_process_name(pid)
        if is_ignored(process_name, wm_class):
            return

        emit_event({
            "type": "window.focused",
            "source": "desktop",
            "application": {
                "name": process_name or wm_class or "unknown",
                "pid": pid,
                "wm_class": wm_class,
            },
            "window": {
                "id": window_id,
                "title": title,
            },
        })


class AtspiCollector:
    EVENT_TYPES = (
        "object:state-changed:focused",
        "object:state-changed:checked",
        "object:state-changed:selected",
        "object:selection-changed",
        "object:active-descendant-changed",
        "object:property-change:accessible-name",
        "object:property-change:accessible-value",
        "object:text-changed",
        "window:activate",
        "window:create",
        "window:close",
    )

    def __init__(self):
        Atspi.init()
        self.listener = Atspi.EventListener.new(self._on_event)

    def register(self) -> None:
        for event_type in self.EVENT_TYPES:
            try:
                self.listener.register(event_type)
            except Exception as exc:
                print(f"Cannot register AT-SPI event {event_type}: {exc}", file=sys.stderr)

    def stop(self) -> None:
        for event_type in self.EVENT_TYPES:
            try:
                self.listener.deregister(event_type)
            except Exception:
                pass
        try:
            Atspi.event_quit()
        except Exception:
            pass

    @staticmethod
    def _translate(native_type: str) -> str:
        mapping = (
            ("object:state-changed:focused", "ui.focus"),
            ("object:state-changed:checked", "ui.checked_changed"),
            ("object:state-changed:selected", "ui.selected_changed"),
            ("object:text-changed", "ui.text_changed"),
            ("object:selection-changed", "ui.selection_changed"),
            ("object:active-descendant-changed", "ui.active_descendant_changed"),
            ("object:property-change:accessible-name", "ui.name_changed"),
            ("object:property-change:accessible-value", "ui.value_changed"),
            ("window:activate", "window.activated"),
            ("window:create", "window.created"),
            ("window:close", "window.closed"),
        )
        for prefix, normalized in mapping:
            if native_type.startswith(prefix):
                return normalized
        return "ui.event"

    def _on_event(self, event) -> None:
        try:
            source = event.source
            if source is None:
                return

            try:
                name = source.get_name() or ""
            except Exception:
                name = ""

            try:
                role = source.get_role_name() or ""
            except Exception:
                role = ""

            try:
                description = source.get_description() or ""
            except Exception:
                description = ""

            try:
                pid = source.get_process_id()
            except Exception:
                pid = None

            process_name = read_process_name(pid)

            try:
                app_obj = source.get_application()
                atspi_name = app_obj.get_name() if app_obj else ""
                atspi_name = atspi_name or ""
            except Exception:
                atspi_name = ""

            if is_ignored(process_name, atspi_name):
                return

            payload = {
                "type": self._translate(event.type),
                "source": "desktop",
                "native_event": event.type,
                "application": {
                    "name": process_name or atspi_name or "unknown",
                    "pid": pid,
                    "atspi_name": atspi_name,
                },
                "element": {
                    "role": role,
                    "name": name,
                    "description": description,
                },
            }

            if event.type.startswith("object:text-changed"):
                payload["content_redacted"] = True

            emit_event(payload)

        except Exception as exc:
            print(f"AT-SPI event error: {exc}", file=sys.stderr)


def main() -> None:
    print(f"Linux collector output: {OUTPUT_FILE.resolve()}")
    print("Press Ctrl+C to stop.")

    x11 = X11Collector()
    atspi = AtspiCollector()

    x11_thread = threading.Thread(target=x11.start, name="x11-collector", daemon=True)

    def shutdown(*_):
        if stop_event.is_set():
            return
        stop_event.set()
        atspi.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    atspi.register()
    x11_thread.start()

    try:
        Atspi.event_main()
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
