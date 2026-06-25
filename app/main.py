from __future__ import annotations

import json
import logging
import sys
from typing import Any

from fastapi import FastAPI

from app.config import Settings, load_settings
from app.db.models import latest_log
from app.db.session import init_db
from app.graph.workflow import run_workflow
from app.rag.ingest_policy import EXPECTED_POLICY_PDF, ingest_policy, policy_pdf_files
from app.rag.vector_store import get_vector_store
from app.utils.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Hotel AI Agent", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/process-newest-email")
def process_newest_email() -> dict[str, Any]:
    settings = load_settings()
    _ensure_policy_store(settings)
    state = run_workflow(settings)
    return state["final_result"].model_dump(mode="json")


@app.post("/ingest-policy")
def ingest_policy_endpoint() -> dict[str, int]:
    return ingest_policy(load_settings())


@app.get("/logs/latest")
def logs_latest() -> dict[str, Any] | None:
    return latest_log(load_settings())


def _ensure_policy_store(settings: Settings) -> None:
    settings.policy_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings)
    policy_files = policy_pdf_files(settings.policy_dir)
    if settings.strict_real_mode:
        _validate_real_mode_config(settings, bool(policy_files))
    try:
        store = get_vector_store(settings)
        if store.count() == 0 and policy_files:
            ingest_policy(settings)
            store = get_vector_store(settings)
        if settings.strict_real_mode and store.count() == 0:
            raise RuntimeError(
                "Strict real mode requires an ingested PDF policy vector store. "
                "Run: python -m app.rag.ingest_policy"
            )
    except Exception as exc:
        if settings.strict_real_mode:
            raise
        logger.warning("Policy vector store is not ready: %s", exc)


def _validate_real_mode_config(settings: Settings, has_policy_pdf: bool) -> None:
    if settings.use_sample_email:
        raise RuntimeError("STRICT_REAL_MODE=true requires USE_SAMPLE_EMAIL=false.")
    if settings.email_source == "file" and settings.auto_send_emails:
        raise RuntimeError("AUTO_SEND_EMAILS must remain false when EMAIL_SOURCE=file.")
    settings.require_openai_credentials()
    if settings.email_source == "outlook":
        settings.require_graph_credentials()
    elif settings.email_source != "file":
        raise RuntimeError("EMAIL_SOURCE must be either outlook or file.")
    if not has_policy_pdf:
        raise RuntimeError(
            f"Strict real mode requires {EXPECTED_POLICY_PDF} in {settings.policy_dir}."
        )


def cli() -> int:
    settings = load_settings()
    try:
        _ensure_policy_store(settings)
        state = run_workflow(settings)
        result = state["final_result"]
        print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
        print("\nReply Subject:")
        print(result.reply.reply_subject)
        print("\nReply Body:")
        print(result.reply.reply_body)
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
