from __future__ import annotations

import json

from .models import Episode


EPISODE_ANALYZER_SYSTEM_PROMPT = """You analyze a compact timeline of user activity collected from desktop and browser applications.

Your goal is to infer the user task represented by ONE episode.

Do not describe low-level clicks unless they are semantically important. Infer intent from application context, UI element semantics, navigation, entities, and outcomes.

Multiple applications may belong to the same task. Do not split a task merely because the active application changes.

Values such as issue IDs, build numbers, filenames, dates, names, search strings and URLs may be task parameters rather than constants.

Return only structured JSON with these fields:
- intent
- goal
- steps
- inputs
- outputs
- parameters
- success_criteria
- applications
- evidence
- confidence

Do not invent actions or outcomes that are not supported by the events. If the episode is ambiguous, lower confidence and explain the ambiguity in evidence.
"""


def build_episode_analyzer_payload(episode: Episode) -> dict:
    return {
        "system_prompt": EPISODE_ANALYZER_SYSTEM_PROMPT,
        "user_prompt": "Analyze this episode:\n\n" + json.dumps(
            episode.to_dict(), ensure_ascii=False, indent=2
        ),
        "output_schema": {
            "intent": "string",
            "goal": "string",
            "steps": ["string"],
            "inputs": ["object"],
            "outputs": ["string"],
            "parameters": ["object"],
            "success_criteria": ["string"],
            "applications": ["string"],
            "evidence": ["string"],
            "confidence": "number 0..1",
        },
    }
