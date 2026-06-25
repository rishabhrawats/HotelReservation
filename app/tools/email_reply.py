from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from app.ai.schemas import EmailInput, ReplyResult
from app.config import Settings
from app.email.outlook_client import OutlookClient

logger = logging.getLogger(__name__)


def send_or_create_draft(email: EmailInput, reply: ReplyResult, settings: Settings) -> str:
    if settings.auto_send_emails and reply.should_send:
        client = OutlookClient(settings)
        client.send_reply(email.email_id, email.sender_email, reply.reply_subject, reply.reply_body)
        client.mark_email_as_read(email.email_id)
        logger.info("Reply sent for email_id=%s", email.email_id)
        return "SENT"
    _write_local_draft(email, reply, settings)
    print("\n--- Draft Reply ---")
    print(f"Subject: {reply.reply_subject}")
    print(reply.reply_body)
    print("--- End Draft Reply ---\n")
    return "DRAFT_ONLY"


def _write_local_draft(email: EmailInput, reply: ReplyResult, settings: Settings) -> Path:
    logs_dir = settings.sqlite_db_path.parent.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_id = "".join(ch for ch in email.email_id if ch.isalnum() or ch in {"-", "_"})[:80] or "email"
    path = logs_dir / f"draft_{timestamp}_{safe_id}.txt"
    path.write_text(
        f"To: {email.sender_email}\nSubject: {reply.reply_subject}\n\n{reply.reply_body}\n",
        encoding="utf-8",
    )
    logger.info("Local draft written to %s", path)
    return path

