from __future__ import annotations

import argparse
import json
from pathlib import Path

from .llm_payload import build_episode_analyzer_payload
from .normalize import normalize_events
from .pipeline import build_candidate_episodes, enrich_timeline, reduce_noise, sessionize


def read_jsonl(path: Path | None) -> list[dict]:
    if path is None:
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}:{line_number}: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize TraineeAI collector logs and build candidate user-task episodes."
    )
    parser.add_argument("--desktop", type=Path, help="Desktop/Linux collector JSONL")
    parser.add_argument("--browser", type=Path, help="Browser CDP collector JSONL")
    parser.add_argument("--output", type=Path, default=Path("episodes.jsonl"))
    parser.add_argument(
        "--timeline-output",
        type=Path,
        help="Optional normalized/reduced unified timeline JSONL",
    )
    parser.add_argument(
        "--llm-payload-output",
        type=Path,
        help="Optional JSONL with one ready-to-send LLM payload per episode",
    )
    args = parser.parse_args()

    if not args.desktop and not args.browser:
        parser.error("At least one of --desktop or --browser is required")

    desktop_rows = read_jsonl(args.desktop)
    browser_rows = read_jsonl(args.browser)

    timeline = normalize_events(desktop_rows, browser_rows)
    timeline = enrich_timeline(timeline)
    timeline = reduce_noise(timeline)

    if args.timeline_output:
        write_jsonl(args.timeline_output, [event.to_dict() for event in timeline])

    episodes = []
    for session in sessionize(timeline):
        episodes.extend(build_candidate_episodes(session))

    # Re-number after session-level construction so IDs stay globally unique.
    for index, episode in enumerate(episodes, start=1):
        episode.episode_id = f"ep-{index:05d}"

    write_jsonl(args.output, [episode.to_dict() for episode in episodes])

    if args.llm_payload_output:
        write_jsonl(
            args.llm_payload_output,
            [build_episode_analyzer_payload(episode) for episode in episodes],
        )

    print(f"Desktop events: {len(desktop_rows)}")
    print(f"Browser events: {len(browser_rows)}")
    print(f"Reduced timeline events: {len(timeline)}")
    print(f"Candidate episodes: {len(episodes)}")
    print(f"Episodes written to: {args.output}")


if __name__ == "__main__":
    main()
