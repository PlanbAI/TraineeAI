from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class UnifiedEvent:
    timestamp: str
    ts_epoch: float
    source: str
    event_type: str
    app_name: str | None = None
    pid: int | None = None
    window_title: str | None = None
    url: str | None = None
    page_title: str | None = None
    target_id: str | None = None
    target: dict[str, Any] | None = None
    data: dict[str, Any] = field(default_factory=dict)
    entities: list[dict[str, str]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result.pop("raw", None)
        return result


@dataclass
class Episode:
    episode_id: str
    start: str
    end: str
    duration_sec: float
    applications: list[str]
    entities: list[dict[str, str]]
    actions: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
