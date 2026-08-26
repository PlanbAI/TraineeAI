#!/usr/bin/env python3

import json
import threading
import time
from datetime import datetime, timezone

import requests
import websocket


CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
OUTPUT_FILE = "browser-events.jsonl"

BINDING_NAME = "__pythonUserEvent"

# JS выполняется внутри каждой страницы.
# Код самой страницы на диске/сервере не изменяется.
LISTENER_JS = r"""
(() => {
    if (window.__pythonCdpListenerInstalled) {
        return;
    }

    window.__pythonCdpListenerInstalled = true;

    function safeText(el) {
        if (!el) return null;

        let text =
            el.innerText ||
            el.getAttribute?.("aria-label") ||
            el.getAttribute?.("title") ||
            el.getAttribute?.("placeholder") ||
            "";

        text = String(text)
            .replace(/\s+/g, " ")
            .trim();

        return text.substring(0, 500);
    }

    function selector(el) {
        if (!el || el.nodeType !== Node.ELEMENT_NODE) {
            return null;
        }

        if (el.id) {
            return "#" + CSS.escape(el.id);
        }

        const parts = [];
        let current = el;

        while (
            current &&
            current.nodeType === Node.ELEMENT_NODE &&
            parts.length < 6
        ) {
            let part = current.tagName.toLowerCase();

            if (current.classList && current.classList.length) {
                const classes = [...current.classList]
                    .slice(0, 3)
                    .map(c => "." + CSS.escape(c))
                    .join("");

                part += classes;
            }

            if (current.parentElement) {
                const sameTags = [...current.parentElement.children]
                    .filter(x => x.tagName === current.tagName);

                if (sameTags.length > 1) {
                    part += `:nth-of-type(${sameTags.indexOf(current) + 1})`;
                }
            }

            parts.unshift(part);
            current = current.parentElement;
        }

        return parts.join(" > ");
    }

    function elementInfo(el) {
        if (!el || el.nodeType !== Node.ELEMENT_NODE) {
            return null;
        }

        let value = null;

        // Не логируем пароли.
        if (
            (el.tagName === "INPUT" ||
             el.tagName === "TEXTAREA" ||
             el.tagName === "SELECT")
        ) {
            if (el.type === "password") {
                value = "<REDACTED>";
            } else {
                value = String(el.value ?? "").substring(0, 1000);
            }
        }

        return {
            tag: el.tagName?.toLowerCase() || null,
            id: el.id || null,
            name: el.getAttribute?.("name"),
            type: el.getAttribute?.("type"),
            role: el.getAttribute?.("role"),
            text: safeText(el),
            value: value,
            href: el.href || null,
            ariaLabel: el.getAttribute?.("aria-label"),
            placeholder: el.getAttribute?.("placeholder"),
            selector: selector(el)
        };
    }

    function send(type, event, extra = {}) {
        try {
            const target =
                event?.target?.nodeType === Node.ELEMENT_NODE
                    ? event.target
                    : document.activeElement;

            const data = {
                timestamp: new Date().toISOString(),
                type: type,

                page: {
                    url: location.href,
                    title: document.title
                },

                element: elementInfo(target),

                mouse: event && "clientX" in event ? {
                    x: event.clientX,
                    y: event.clientY,
                    button: event.button
                } : null,

                keyboard: event && "key" in event ? {
                    key: event.key,
                    code: event.code,
                    ctrl: event.ctrlKey,
                    alt: event.altKey,
                    shift: event.shiftKey,
                    meta: event.metaKey
                } : null,

                ...extra
            };

            window.__pythonUserEvent(JSON.stringify(data));

        } catch (e) {
            console.error("CDP listener error:", e);
        }
    }


    // ============================================================
    // Mouse
    // ============================================================

    document.addEventListener(
        "click",
        e => send("click", e),
        true
    );

    document.addEventListener(
        "dblclick",
        e => send("dblclick", e),
        true
    );

    document.addEventListener(
        "contextmenu",
        e => send("contextmenu", e),
        true
    );


    // ============================================================
    // Keyboard
    // ============================================================

    document.addEventListener(
        "keydown",
        e => send("keydown", e),
        true
    );


    // ============================================================
    // Form/input
    // ============================================================

    document.addEventListener(
        "change",
        e => send("change", e),
        true
    );

    document.addEventListener(
        "input",
        e => {
            // Не отправляем password contents.
            if (e.target?.type === "password") {
                send("input", e, {
                    valueRedacted: true
                });
            } else {
                send("input", e);
            }
        },
        true
    );

    document.addEventListener(
        "submit",
        e => send("submit", e),
        true
    );


    // ============================================================
    // Focus
    // ============================================================

    document.addEventListener(
        "focusin",
        e => send("focus", e),
        true
    );


    // ============================================================
    // Clipboard
    // ============================================================

    document.addEventListener(
        "copy",
        e => send("copy", e),
        true
    );

    document.addEventListener(
        "cut",
        e => send("cut", e),
        true
    );

    document.addEventListener(
        "paste",
        e => send("paste", e),
        true
    );


    // ============================================================
    // Navigation APIs used by SPA
    // ============================================================

    const originalPushState = history.pushState;

    history.pushState = function(...args) {
        const result = originalPushState.apply(this, args);

        send("navigation", null, {
            navigationType: "pushState"
        });

        return result;
    };


    const originalReplaceState = history.replaceState;

    history.replaceState = function(...args) {
        const result = originalReplaceState.apply(this, args);

        send("navigation", null, {
            navigationType: "replaceState"
        });

        return result;
    };


    window.addEventListener("popstate", () => {
        send("navigation", null, {
            navigationType: "popstate"
        });
    });


    window.addEventListener("hashchange", () => {
        send("navigation", null, {
            navigationType: "hashchange"
        });
    });


    console.log("Python CDP user listener installed");
})();
"""


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