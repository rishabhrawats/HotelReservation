from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import Settings, load_settings


CREATE_LOGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS email_processing_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL,
    internet_message_id TEXT,
    sender_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_datetime TEXT NOT NULL,
    primary_intent TEXT NOT NULL,
    secondary_intents_json TEXT NOT NULL,
    extracted_json TEXT NOT NULL,
    policy_answers_json TEXT NOT NULL,
    reply_subject TEXT NOT NULL,
    reply_body TEXT NOT NULL,
    reply_status TEXT NOT NULL,
    final_status TEXT NOT NULL,
    requires_human_review INTEGER NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection(settings: Settings | None = None) -> sqlite3.Connection:
    settings = settings or load_settings()
    db_path = Path(settings.sqlite_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(settings: Settings | None = None) -> None:
    with get_connection(settings) as conn:
        conn.execute(CREATE_LOGS_TABLE_SQL)
        conn.commit()

