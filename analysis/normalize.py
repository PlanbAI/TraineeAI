from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import UnifiedEvent


JIRA_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
GIT_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s\"'<>]+")
BUILD_RE = re.compile(r"\b(?:build[-_ ]?)?(\d{3,})\b", re.IGNORECASE)
SENSITIVE_TARGET_RE = re.compile(
    r"password|passcode|secret|token|api[ _-]?key|authorization|bearer|"
    r"private[ _-]?key|credit[ _-]?card|card[ _-]?number|cvv|cvc|ssn",
    re.IGNORECASE,
)


def _parse_timestamp(value: str | None) -> tuple[str, float]:
    if not value:
        dt = datetime.now(timezone.utc)
    else:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z"), dt.timestamp()


def _entity_values(*values: object) -> list[dict[str, str]]:
    text = "\n".join(str(v) for v in values if v not in (None, ""))
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: str) -> None:
        key = (kind, value)
        if key not in seen:
            seen.add(key)
            found.append({"type": kind, "value": value})

    for value in JIRA_RE.findall(text):
        add("jira_issue_id", value)
    for value in GIT_SHA_RE.findall(text):
        add("git_sha", value)
    for value in URL_RE.findall(text):
        add("url", value)
    for match in BUILD_RE.finditer(text):
        raw = match.group(0)
        if raw.isdigit() and len(raw) < 4:
            continue
        add("build_number", match.group(1))

    return found


def _redact_sensitive_target(element: dict | None) -> dict | None:
    if not element:
        return None

    target = dict(element)
    metadata = " ".join(
        str(target.get(key) or "")
        for key in ("id", "name", "type", "autocomplete", "ariaLabel", "placeholder", "command")
    )
    if str(target.get("type") or "").lower() == "hidden" or SENSITIVE_TARGET_RE.search(metadata):
        target["value"] = "<REDACTED>"
        if "command" in target:
            target["command"] = "<REDACTED_COMMAND>"
        target["valueRedacted"] = True
    return target


def normalize_browser(event: dict) -> UnifiedEvent:
    timestamp, epoch = _parse_timestamp(
        event.get("timestamp") or event.get("_collector_timestamp")
    )
    page = event.get("page") or {}
    element = _redact_sensitive_target(event.get("element") or None)
    tab = event.get("_tab") or {}
    event_type = event.get("type", "browser.unknown")

    data = {
        "mouse": event.get("mouse"),
        "keyboard": event.get("keyboard"),
        "navigation_type": event.get("navigationType"),
        "value_redacted": event.get("valueRedacted", False)
        or bool(element and element.get("valueRedacted")),
    }

    entities = _entity_values(
        page.get("url"),
        page.get("title"),
        element,
    )

    return UnifiedEvent(
        timestamp=timestamp,
        ts_epoch=epoch,
        source="browser",
        event_type=event_type,
        app_name="browser",
        url=page.get("url"),
        page_title=page.get("title") or page.get("name"),
        target_id=tab.get("targetId"),
        target=element,
        data={k: v for k, v in data.items() if v not in (None, False)},
        entities=entities,
        raw=event,
    )


def normalize_desktop(event: dict) -> UnifiedEvent:
    timestamp, epoch = _parse_timestamp(event.get("timestamp"))
    application = event.get("application") or {}
    window = event.get("window") or {}
    element = event.get("element") or event.get("terminal") or None
    element = _redact_sensitive_target(element)

    app_name = application.get("name") or event.get("process") or event.get("app")
    pid = application.get("pid") or event.get("pid")
    title = window.get("title") or event.get("title")
    event_type = event.get("type") or event.get("event_type") or "desktop.unknown"

    data = {}
    if event.get("input"):
        data["input"] = event["input"]
    if element and (element.get("content_redacted") or element.get("valueRedacted")):
        data["value_redacted"] = True

    entities = _entity_values(title, element)

    return UnifiedEvent(
        timestamp=timestamp,
        ts_epoch=epoch,
        source="desktop",
        event_type=event_type,
        app_name=app_name,
        pid=pid,
        window_title=title,
        target=element,
        data=data,
        entities=entities,
        raw=event,
    )


def normalize_events(desktop: Iterable[dict], browser: Iterable[dict]) -> list[UnifiedEvent]:
    events = [normalize_desktop(x) for x in desktop]
    events.extend(normalize_browser(x) for x in browser)
    events.sort(key=lambda x: x.ts_epoch)
    return events
