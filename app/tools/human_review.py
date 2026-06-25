from __future__ import annotations

from app.ai.schemas import IntentResult


def needs_human_review(intent: IntentResult) -> bool:
    return intent.requires_human_review or intent.confidence < 0.75

