from __future__ import annotations

from pathlib import Path

from app.ai.schemas import EmailInput


def load_email_from_file(path: Path) -> EmailInput:
    if not path.exists():
        raise RuntimeError(
            f"Email file not found: {path}. Create it with a real email payload before running EMAIL_SOURCE=file."
        )
    try:
        email = EmailInput.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Email file is not valid EmailInput JSON: {path}. Error: {exc}") from exc
    if not email.body_text.strip():
        raise RuntimeError(f"Email file has empty body_text: {path}")
    return email

