from pathlib import Path

import pytest

from app.ai.intent_agent import classify_email
from app.ai.schemas import EmailInput
from app.config import Settings
from app.email.outlook_client import OutlookClient
from app.main import _validate_real_mode_config
from app.rag.ingest_policy import ingest_policy
from app.email.file_source import load_email_from_file


def test_strict_real_mode_rejects_sample_mode(test_settings):
    settings = _settings(test_settings, strict_real_mode=True, use_sample_email=True)

    with pytest.raises(RuntimeError, match="USE_SAMPLE_EMAIL=false"):
        _validate_real_mode_config(settings, has_policy_pdf=True)


def test_strict_real_mode_requires_openai_key(test_settings):
    settings = _settings(
        test_settings,
        strict_real_mode=True,
        use_sample_email=False,
        ms_tenant_id="tenant",
        ms_client_id="client",
        ms_client_secret="secret",
        ms_user_email="hotel@example.com",
        openai_api_key=None,
    )

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        _validate_real_mode_config(settings, has_policy_pdf=True)


def test_no_local_ai_fallback_without_openai_key(test_settings):
    settings = _settings(
        test_settings,
        use_sample_email=False,
        strict_real_mode=False,
        allow_local_ai_fallback=False,
        openai_api_key=None,
    )
    email = EmailInput(
        email_id="real-test",
        internet_message_id=None,
        subject="Booking request",
        sender_name="Customer",
        sender_email="customer@example.com",
        received_datetime="2026-06-25T10:00:00Z",
        body_text="Please book one double room for John Smith.",
    )

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        classify_email(email, settings)


def test_strict_real_mode_requires_openai_for_ingestion(test_settings):
    settings = _settings(test_settings, strict_real_mode=True, openai_api_key=None)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        ingest_policy(settings)


def test_policy_answer_openai_is_opt_in_even_in_strict_mode(test_settings):
    from app.ai.schemas import PolicyQuestion
    from app.rag.answer_policy import answer_policy_question
    from app.rag.retriever import RetrievedChunk

    settings = _settings(
        test_settings,
        strict_real_mode=True,
        use_openai_policy_answer=False,
        openai_api_key=None,
    )
    answer = answer_policy_question(
        PolicyQuestion(question="Can I check in early?", category="early check-in", needs_rag_answer=True),
        [
            RetrievedChunk(
                text="Actual Message: early check-in request. Category: Arrival Time.",
                metadata={"source_file": "policy.pdf", "source_type": "pdf", "page_number": 1},
            )
        ],
        settings,
    )

    assert answer.insufficient_policy_context is False


def test_delegated_graph_mode_requires_only_client_id(test_settings):
    settings = _settings(
        test_settings,
        ms_auth_mode="delegated",
        ms_client_id="client-id",
        ms_tenant_id=None,
        ms_client_secret=None,
        ms_user_email=None,
    )

    assert settings.has_graph_credentials is True
    settings.require_graph_credentials()


def test_delegated_graph_mode_uses_me_urls(test_settings):
    settings = _settings(
        test_settings,
        ms_auth_mode="delegated",
        ms_client_id="client-id",
        ms_tenant_id=None,
        ms_client_secret=None,
        ms_user_email=None,
    )
    client = OutlookClient(settings)

    assert client._user_url("/messages") == "https://graph.microsoft.com/v1.0/me/messages"


def test_strict_real_file_mode_does_not_require_graph_credentials(test_settings):
    settings = _settings(
        test_settings,
        strict_real_mode=True,
        use_sample_email=False,
        email_source="file",
        openai_api_key="sk-test",
        ms_auth_mode="application",
        ms_tenant_id=None,
        ms_client_id=None,
        ms_client_secret=None,
        ms_user_email=None,
        auto_send_emails=False,
    )

    _validate_real_mode_config(settings, has_policy_pdf=True)


def test_strict_real_file_mode_rejects_auto_send(test_settings):
    settings = _settings(
        test_settings,
        strict_real_mode=True,
        use_sample_email=False,
        email_source="file",
        openai_api_key="sk-test",
        auto_send_emails=True,
    )

    with pytest.raises(RuntimeError, match="AUTO_SEND_EMAILS"):
        _validate_real_mode_config(settings, has_policy_pdf=True)


def test_load_email_from_file(test_settings):
    path = test_settings.email_file_path
    path.parent.mkdir(parents=True)
    path.write_text(
        EmailInput(
            email_id="file-email",
            internet_message_id=None,
            subject="Question",
            sender_name="Customer",
            sender_email="customer@example.com",
            received_datetime="2026-06-25T10:00:00Z",
            body_text="Can I check in early?",
        ).model_dump_json(),
        encoding="utf-8",
    )

    email = load_email_from_file(path)

    assert email.email_id == "file-email"
    assert email.body_text == "Can I check in early?"


def _settings(base: Settings, **updates) -> Settings:
    data = base.__dict__.copy()
    data.update(updates)
    return Settings(**data)
