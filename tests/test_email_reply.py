from app.ai.schemas import EmailInput, ReplyResult
from app.tools.email_reply import send_or_create_draft


def test_auto_send_false_does_not_send_real_email(monkeypatch, test_settings):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("OutlookClient should not be used when AUTO_SEND_EMAILS=false")

    monkeypatch.setattr("app.tools.email_reply.OutlookClient", fail_if_called)
    email = EmailInput(
        email_id="email-local-draft",
        internet_message_id=None,
        subject="Test",
        sender_name="Customer",
        sender_email="customer@example.com",
        received_datetime="2026-06-25T10:00:00Z",
        body_text="Hello",
    )
    reply = ReplyResult(
        reply_subject="Re: Test",
        reply_body="Draft body",
        reply_type="unknown_request",
        should_send=False,
        requires_human_review=False,
    )

    status = send_or_create_draft(email, reply, test_settings)

    assert status == "DRAFT_ONLY"

