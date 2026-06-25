from __future__ import annotations

from typing import TypedDict

from app.ai.schemas import (
    EmailInput,
    FinalProcessingResult,
    IntentResult,
    OracleOperationResult,
    PolicyAnswer,
    ReplyResult,
)
from app.config import Settings
from app.rag.retriever import RetrievedChunk


class HotelAgentState(TypedDict, total=False):
    settings: Settings
    email: EmailInput
    intent: IntentResult
    policy_contexts: dict[str, list[RetrievedChunk]]
    policy_answers: list[PolicyAnswer]
    oracle_result: OracleOperationResult
    reply: ReplyResult
    reply_status: str
    final_status: str
    final_result: FinalProcessingResult
    log_id: int
    errors: list[str]
