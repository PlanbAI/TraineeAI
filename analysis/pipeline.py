from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .models import Episode, UnifiedEvent


SESSION_IDLE_SEC = 600
EPISODE_IDLE_SEC = 120
CONTEXT_CHANGE_GAP_SEC = 20
INPUT_AGGREGATION_SEC = 3


def enrich_timeline(events: list[UnifiedEvent]) -> list[UnifiedEvent]:
    """Carry the latest desktop window context into browser events."""
    active_app = None
    active_pid = None
    active_window = None
    result: list[UnifiedEvent] = []

    for event in events:
        if event.source == "desktop" and event.event_type.startswith("window."):
            active_app = event.app_name
            active_pid = event.pid
            active_window = event.window_title
            result.append(event)
            continue

        if event.source == "browser":
            result.append(
                replace(
                    event,
                    app_name=active_app or event.app_name,
                    pid=active_pid or event.pid,
                    window_title=active_window or event.window_title,
                )
            )
        else:
            result.append(event)

    return result


def _same_target(a: UnifiedEvent, b: UnifiedEvent) -> bool:
    if not a.target or not b.target:
        return False
    for key in ("selector", "id", "name", "ariaLabel", "placeholder"):
        av = a.target.get(key)
        bv = b.target.get(key)
        if av and bv and av == bv:
            return True
    return a.target.get("tag") == b.target.get("tag") and a.target.get("text") == b.target.get("text")


def reduce_noise(events: list[UnifiedEvent]) -> list[UnifiedEvent]:
    """Drop or aggregate low-value browser events before LLM analysis."""
    result: list[UnifiedEvent] = []
    pending_input: UnifiedEvent | None = None

    def flush_input() -> None:
        nonlocal pending_input
        if pending_input is not None:
            result.append(replace(pending_input, event_type="fill"))
            pending_input = None

    for event in events:
        if event.source != "browser":
            flush_input()
            result.append(event)
            continue

        if event.event_type == "keydown":
            keyboard = event.data.get("keyboard") or {}
            key = keyboard.get("key")
            modifiers = any(keyboard.get(x) for x in ("ctrl", "alt", "meta"))
            if key not in ("Enter", "Escape", "Tab") and not modifiers:
                continue
            flush_input()
            result.append(replace(event, event_type="keyboard_action"))
            continue

        if event.event_type == "focus":
            # Focus is usually implied by the following click/fill. Keep it only
            # when no more meaningful event follows on the same element.
            flush_input()
            result.append(event)
            continue

        if event.event_type == "input":
            if (
                pending_input is not None
                and event.ts_epoch - pending_input.ts_epoch <= INPUT_AGGREGATION_SEC
                and _same_target(pending_input, event)
            ):
                pending_input = event
            else:
                flush_input()
                pending_input = event
            continue

        if event.event_type == "change":
            if pending_input is not None and _same_target(pending_input, event):
                pending_input = event
                flush_input()
                continue

        flush_input()

        mapped = {
            "page_navigation": "navigate",
            "navigation": "navigate",
            "click": "click",
            "dblclick": "double_click",
            "contextmenu": "context_menu",
            "submit": "submit",
            "copy": "copy",
            "cut": "cut",
            "paste": "paste",
        }.get(event.event_type, event.event_type)

        result.append(replace(event, event_type=mapped))

    flush_input()
    return _dedupe_adjacent(result)


def _dedupe_adjacent(events: list[UnifiedEvent]) -> list[UnifiedEvent]:
    result: list[UnifiedEvent] = []
    for event in events:
        if result:
            previous = result[-1]
            if (
                event.event_type == previous.event_type
                and event.source == previous.source
                and event.url == previous.url
                and _same_target(event, previous)
                and event.ts_epoch - previous.ts_epoch < 0.5
            ):
                continue
        result.append(event)
    return result


def sessionize(events: list[UnifiedEvent]) -> list[list[UnifiedEvent]]:
    if not events:
        return []

    sessions: list[list[UnifiedEvent]] = [[events[0]]]
    for event in events[1:]:
        previous = sessions[-1][-1]
        if event.ts_epoch - previous.ts_epoch >= SESSION_IDLE_SEC:
            sessions.append([event])
        else:
            sessions[-1].append(event)
    return sessions


def _entity_keys(events: Iterable[UnifiedEvent]) -> set[tuple[str, str]]:
    return {
        (entity["type"], entity["value"])
        for event in events
        for entity in event.entities
        if entity.get("type") and entity.get("value")
    }


def _should_split(current: list[UnifiedEvent], event: UnifiedEvent) -> bool:
    previous = current[-1]
    gap = event.ts_epoch - previous.ts_epoch
    if gap >= EPISODE_IDLE_SEC:
        return True

    if gap < CONTEXT_CHANGE_GAP_SEC:
        return False

    current_entities = _entity_keys(current[-20:])
    next_entities = _entity_keys([event])
    if current_entities & next_entities:
        return False

    previous_context = previous.url or previous.window_title or previous.app_name
    new_context = event.url or event.window_title or event.app_name
    if previous_context and new_context and previous_context != new_context:
        return True

    return False


def build_candidate_episodes(events: list[UnifiedEvent]) -> list[Episode]:
    episodes: list[Episode] = []
    episode_events: list[UnifiedEvent] = []

    def finish() -> None:
        nonlocal episode_events
        if not episode_events:
            return
        idx = len(episodes) + 1
        apps = list(dict.fromkeys(e.app_name for e in episode_events if e.app_name))
        entity_map: dict[tuple[str, str], dict[str, str]] = {}
        for e in episode_events:
            for entity in e.entities:
                if entity.get("type") and entity.get("value"):
                    entity_map[(entity["type"], entity["value"])] = entity

        actions = []
        for e in episode_events:
            action = {
                "timestamp": e.timestamp,
                "source": e.source,
                "app": e.app_name,
                "type": e.event_type,
            }
            if e.url:
                action["url"] = e.url
            if e.window_title:
                action["window_title"] = e.window_title
            if e.target:
                action["target"] = e.target
            if e.entities:
                action["entities"] = e.entities
            actions.append(action)

        first, last = episode_events[0], episode_events[-1]
        episodes.append(
            Episode(
                episode_id=f"ep-{idx:05d}",
                start=first.timestamp,
                end=last.timestamp,
                duration_sec=round(last.ts_epoch - first.ts_epoch, 3),
                applications=apps,
                entities=list(entity_map.values()),
                actions=actions,
            )
        )
        episode_events = []

    for event in events:
        if episode_events and _should_split(episode_events, event):
            finish()
        episode_events.append(event)
    finish()
    return episodes
