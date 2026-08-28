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

    function isSensitiveField(el) {
        if (!el || el.nodeType !== Node.ELEMENT_NODE) {
            return false;
        }

        const type = String(el.type || "").toLowerCase();
        if (type === "password" || type === "hidden") {
            return true;
        }

        const metadata = [
            el.id,
            el.getAttribute?.("name"),
            el.getAttribute?.("autocomplete"),
            el.getAttribute?.("aria-label"),
            el.getAttribute?.("placeholder")
        ].filter(Boolean).join(" ").toLowerCase();

        return /password|passcode|secret|token|api[ _-]?key|authorization|bearer|private[ _-]?key|credit[ _-]?card|card[ _-]?number|cvv|cvc|ssn/.test(metadata);
    }

    function elementInfo(el) {
        if (!el || el.nodeType !== Node.ELEMENT_NODE) {
            return null;
        }

        let value = null;

        if (
            el.tagName === "INPUT" ||
            el.tagName === "TEXTAREA" ||
            el.tagName === "SELECT"
        ) {
            if (isSensitiveField(el)) {
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
            autocomplete: el.getAttribute?.("autocomplete"),
            role: el.getAttribute?.("role"),
            text: safeText(el),
            value,
            valueRedacted: isSensitiveField(el),
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
                type,

                page: {
                    url: location.href,
                    title: document.title
                },

                element: elementInfo(target),

                mouse:
                    event && "clientX" in event
                        ? {
                            x: event.clientX,
                            y: event.clientY,
                            button: event.button
                        }
                        : null,

                keyboard:
                    event && "key" in event
                        ? {
                            key: event.key,
                            code: event.code,
                            ctrl: event.ctrlKey,
                            alt: event.altKey,
                            shift: event.shiftKey,
                            meta: event.metaKey
                        }
                        : null,

                ...extra
            };

            window.__pythonUserEvent(JSON.stringify(data));
        } catch (e) {
            console.error("CDP listener error:", e);
        }
    }

    document.addEventListener("click", e => send("click", e), true);
    document.addEventListener("dblclick", e => send("dblclick", e), true);
    document.addEventListener("contextmenu", e => send("contextmenu", e), true);

    document.addEventListener("keydown", e => send("keydown", e), true);

    document.addEventListener("change", e => send("change", e), true);

    document.addEventListener(
        "input",
        e => {
            if (isSensitiveField(e.target)) {
                send("input", e, { valueRedacted: true });
            } else {
                send("input", e);
            }
        },
        true
    );

    document.addEventListener("submit", e => send("submit", e), true);
    document.addEventListener("focusin", e => send("focus", e), true);

    document.addEventListener("copy", e => send("copy", e), true);
    document.addEventListener("cut", e => send("cut", e), true);
    document.addEventListener("paste", e => send("paste", e), true);

    const originalPushState = history.pushState;

    history.pushState = function(...args) {
        const result = originalPushState.apply(this, args);
        send("navigation", null, { navigationType: "pushState" });
        return result;
    };

    const originalReplaceState = history.replaceState;

    history.replaceState = function(...args) {
        const result = originalReplaceState.apply(this, args);
        send("navigation", null, { navigationType: "replaceState" });
        return result;
    };

    window.addEventListener("popstate", () => {
        send("navigation", null, { navigationType: "popstate" });
    });

    window.addEventListener("hashchange", () => {
        send("navigation", null, { navigationType: "hashchange" });
    });

    console.log("TraineeAI CDP user listener installed");
})();
