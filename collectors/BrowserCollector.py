#!/usr/bin/env python3

import base64
import json
import os
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path


CDP_HOST = os.environ.get("CDP_HOST", "127.0.0.1")
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
OUTPUT_FILE = "browser-events.jsonl"

BINDING_NAME = "__pythonUserEvent"

# JS выполняется внутри каждой страницы.
# Код самой страницы на диске/сервере не изменяется.
LISTENER_PATH = Path(__file__).resolve().parents[1] / "browser_listener.js"
LISTENER_JS = LISTENER_PATH.read_text(encoding="utf-8")


class LocalWebSocket:
    """Minimal WebSocket client for the local Chrome DevTools endpoint."""

    def __init__(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or not parsed.hostname:
            raise ValueError(f"Unsupported CDP WebSocket URL: {url}")
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self.path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
        self.sock = None
        self.buffer = b""

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        host = f"{self.host}:{self.port}"
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = self._read_until(b"\r\n\r\n")
        status = response.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise ConnectionError(f"CDP WebSocket upgrade failed: {status.decode(errors='replace')}")
        self.sock.settimeout(None)

    def _read_until(self, delimiter):
        while delimiter not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("CDP WebSocket closed during handshake")
            self.buffer += chunk
        value, self.buffer = self.buffer.split(delimiter, 1)
        return value + delimiter

    def _read_exact(self, size):
        while len(self.buffer) < size:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("CDP WebSocket closed")
            self.buffer += chunk
        value, self.buffer = self.buffer[:size], self.buffer[size:]
        return value

    def send(self, text):
        payload = text.encode("utf-8")
        size = len(payload)
        mask = os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        if size < 126:
            header = struct.pack("!BB", 0x81, 0x80 | size)
        elif size < 65536:
            header = struct.pack("!BBH", 0x81, 0x80 | 126, size)
        else:
            header = struct.pack("!BBQ", 0x81, 0x80 | 127, size)
        self.sock.sendall(header + mask + masked)

    def recv(self):
        fragments = []
        while True:
            first, second = struct.unpack("!BB", self._read_exact(2))
            final = bool(first & 0x80)
            opcode = first & 0x0F
            size = second & 0x7F
            if size == 126:
                size = struct.unpack("!H", self._read_exact(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if second & 0x80 else None
            payload = self._read_exact(size)
            if mask:
                payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
            if opcode == 0x8:
                return ""
            if opcode == 0x9:
                self._send_control(0xA, payload)
                continue
            if opcode not in (0x0, 0x1):
                continue
            fragments.append(payload)
            if final:
                return b"".join(fragments).decode("utf-8")

    def _send_control(self, opcode, payload):
        mask = os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(struct.pack("!BB", 0x80 | opcode, 0x80 | len(payload)) + mask + masked)

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None


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
            self.ws = LocalWebSocket(self.ws_url)
            self.ws.connect()

            # Включаем необходимые CDP domains
            self.send("Runtime.enable")
            self.send("Page.enable")

            # Создаём канал JS -> Python
            self.send(
                "Runtime.addBinding",
                {
                    "name": BINDING_NAME
                }
            )

            # Для всех будущих document/frame.
            self.send(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": LISTENER_JS
                }
            )

            # А также текущая уже загруженная страница.
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

                    # Только top frame
                    if not frame.get("parentId"):
                        write_event({
                            "type": "page_navigation",
                            "timestamp": datetime.now(
                                timezone.utc
                            ).isoformat(),
                            "page": {
                                "url": frame.get("url"),
                                "name": frame.get("name")
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
    url = (
        f"http://{CDP_HOST}:{CDP_PORT}/json"
    )

    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


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

    print(
        f"[*] Output: {OUTPUT_FILE}"
    )

    while True:
        try:
            targets = get_targets()

            for target in targets:

                if target.get("type") != "page":
                    continue

                if not target.get(
                    "webSocketDebuggerUrl"
                ):
                    continue

                target_id = target["id"]

                with lock:
                    if target_id in active_targets:
                        continue

                    active_targets.add(
                        target_id
                    )

                thread = threading.Thread(
                    target=target_worker,
                    args=(target,),
                    daemon=True
                )

                thread.start()

        except urllib.error.URLError:
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
