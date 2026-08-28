#!/usr/bin/env python3

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import websocket


CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
OUTPUT_FILE = "browser-events.jsonl"

BINDING_NAME = "__pythonUserEvent"
SCRIPT_DIR = Path(__file__).resolve().parent
LISTENER_JS_FILE = SCRIPT_DIR / "browser_listener.js"


def load_listener_js() -> str:
    try:
        return LISTENER_JS_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"Cannot load browser listener JavaScript: {LISTENER_JS_FILE}"
        ) from exc


LISTENER_JS = load_listener_js()


def write_event(event):
    event["_collector_timestamp"] = datetime.now(
        timezone.utc
    ).isoformat()

    line = json.dumps(
        event,
        ensure_ascii=False
    )

    print(line)

    with open(
        OUTPUT_FILE,
        "a",
        encoding="utf-8"
    ) as f:
        f.write(line + "\n")


class CDPConnection:
    def __init__(self, target):
        self.target = target
        self.ws_url = target["webSocketDebuggerUrl"]
        self.message_id = 0
        self.ws = None

    def send(self, method, params=None):
        self.message_id += 1

        message = {
            "id": self.message_id,
            "method": method
        }

        if params:
            message["params"] = params

        self.ws.send(json.dumps(message))

    def run(self):
        title = self.target.get("title", "")
        url = self.target.get("url", "")

        print(f"[+] Attaching: {title} {url}")

        try:
            self.ws = websocket.create_connection(
                self.ws_url,
                timeout=None,
                suppress_origin=True
            )

            self.send("Runtime.enable")
            self.send("Page.enable")

            self.send(
                "Runtime.addBinding",
                {
                    "name": BINDING_NAME
                }
            )

            # Install listener automatically in every future document/frame.
            self.send(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": LISTENER_JS
                }
            )

            # Also install it in the page that is already loaded.
            self.send(
                "Runtime.evaluate",
                {
                    "expression": LISTENER_JS
                }
            )

            while True:
                raw = self.ws.recv()

                if not raw:
                    break

                message = json.loads(raw)
                method = message.get("method")

                if method == "Runtime.bindingCalled":
                    params = message.get("params", {})

                    if params.get("name") != BINDING_NAME:
                        continue

                    payload = params.get("payload")

                    try:
                        event = json.loads(payload)
                    except Exception:
                        event = {
                            "type": "raw",
                            "payload": payload
                        }

                    event["_tab"] = {
                        "targetId": self.target.get("id"),
                        "initialUrl": self.target.get("url"),
                        "initialTitle": self.target.get("title")
                    }

                    write_event(event)

                elif method == "Page.frameNavigated":
                    frame = (
                        message
                        .get("params", {})
                        .get("frame", {})
                    )

                    # Record only top-frame navigation here.
                    if not frame.get("parentId"):
                        write_event({
                            "type": "page_navigation",
                            "timestamp": datetime.now(
                                timezone.utc
                            ).isoformat(),
                            "page": {
                                "url": frame.get("url"),
                                "name": frame.get("name")
                            },
                            "_tab": {
                                "targetId": self.target.get("id"),
                                "initialUrl": self.target.get("url"),
                                "initialTitle": self.target.get("title")
                            }
                        })

        except Exception as e:
            print(
                f"[-] Disconnected "
                f"{self.target.get('id')}: {e}"
            )

        finally:
            if self.ws:
                try:
                    self.ws.close()
                except Exception:
                    pass


active_targets = set()
lock = threading.Lock()


def get_targets():
    url = f"http://{CDP_HOST}:{CDP_PORT}/json"

    response = requests.get(
        url,
        timeout=3
    )

    response.raise_for_status()
    return response.json()


def target_worker(target):
    try:
        CDPConnection(target).run()

    finally:
        with lock:
            active_targets.discard(
                target["id"]
            )


def monitor_targets():
    print(
        f"[*] Connecting to "
        f"http://{CDP_HOST}:{CDP_PORT}"
    )

    print(f"[*] Listener JS: {LISTENER_JS_FILE}")
    print(f"[*] Output: {OUTPUT_FILE}")

    while True:
        try:
            targets = get_targets()

            for target in targets:
                if target.get("type") != "page":
                    continue

                if not target.get("webSocketDebuggerUrl"):
                    continue

                target_id = target["id"]

                with lock:
                    if target_id in active_targets:
                        continue

                    active_targets.add(target_id)

                thread = threading.Thread(
                    target=target_worker,
                    args=(target,),
                    daemon=True
                )

                thread.start()

        except requests.ConnectionError:
            print(
                "[-] Chrome CDP unavailable "
                f"on {CDP_HOST}:{CDP_PORT}"
            )

        except Exception as e:
            print(
                f"[-] Target monitor error: {e}"
            )

        time.sleep(1)


if __name__ == "__main__":
    try:
        monitor_targets()

    except KeyboardInterrupt:
        print("\n[*] Stopped")
