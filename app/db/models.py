from __future__ import annotations

import json
from typing import Any

from app.ai.schemas import FinalProcessingResult, ReplyStatus
from app.config import Settings
from app.db.session import get_connection, init_db


def insert_processing_log(
    result: FinalProcessingResult,
    reply_status: ReplyStatus,
    settings: Settings,
    error_message: str | None = None,
) -> int:
    init_db(settings)
    extracted_json = result.intent.model_dump_json()
    policy_answers_json = json.dumps(
        [answer.model_dump(mode="json") for answer in result.policy_answers],
        ensure_ascii=False,
    )
    with get_connection(settings) as conn:
        cursor = conn.execute(
            """
            INSERT INTO email_processing_logs (
                email_id,
                internet_message_id,
                sender_email,
                subject,
                received_datetime,
                primary_intent,
                secondary_intents_json,
                extracted_json,
                policy_answers_json,
                reply_subject,
                reply_body,
                reply_status,
                final_status,
                requires_human_review,
                error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.email.email_id,
                result.email.internet_message_id,
                result.email.sender_email,
                result.email.subject,
                result.email.received_datetime,
                result.intent.primary_intent,
                json.dumps(result.intent.secondary_intents),
                extracted_json,
                policy_answers_json,
                result.reply.reply_subject,
                result.reply.reply_body,
                reply_status,
                result.final_status,
                int(result.reply.requires_human_review),
                error_message or "; ".join(result.errors) or None,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def latest_log(settings: Settings) -> dict[str, Any] | None:
    init_db(settings)
    with get_connection(settings) as conn:
        row = conn.execute(
            "SELECT * FROM email_processing_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None

