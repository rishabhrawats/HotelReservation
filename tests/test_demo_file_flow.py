from __future__ import annotations

from dataclasses import replace

from app.ai.schemas import (
    EmailInput,
    FinalProcessingResult,
    IntentResult,
    OracleAvailabilityOption,
    OracleOperationResult,
    ReplyResult,
)
from app.demo_file_flow import run_demo_file_flow
from app.graph.nodes import load_newest_email


def test_demo_file_flow_reads_plain_email_body_and_writes_output(tmp_path, test_settings, monkeypatch):
    input_path = tmp_path / "demo_input" / "email_body.txt"
    output_dir = tmp_path / "demo_output"
    input_path.parent.mkdir(parents=True)
    input_path.write_text(
        "Subject: CEO demo request\n\nPlease check availability for 2 adults from 10 September 2026 to 12 September 2026.",
        encoding="utf-8",
    )
    settings = replace(test_settings, demo_email_body_path=input_path, demo_output_dir=output_dir)
    captured: dict[str, EmailInput] = {}

    def fake_run_workflow_for_email(email, workflow_settings):
        captured["email"] = email
        intent = IntentResult(
            primary_intent="availability_check",
            secondary_intents=[],
            confidence=0.94,
            requires_human_review=False,
            customer_message_summary="Customer is checking availability.",
            booking_request=None,
            questions=[],
            next_action="acknowledge_booking_request",
        )
        oracle = OracleOperationResult(
            operation="booking_alternatives",
            success=True,
            message="Requested dates were not available. Nearby alternatives were found.",
            requested_arrival_date="2026-09-10",
            requested_departure_date="2026-09-12",
            options=[
                OracleAvailabilityOption(
                    arrival_date="2026-09-11",
                    departure_date="2026-09-13",
                    room_type="DSPN",
                    rate_plan_code="BARFLEX",
                    amount_before_tax=218,
                    currency_code="GBP",
                )
            ],
        )
        reply = ReplyResult(
            reply_subject="Re: CEO demo request",
            reply_body="We found an alternative stay from 11 September to 13 September.",
            reply_type="booking_alternatives",
            should_send=False,
            requires_human_review=False,
        )
        return {
            "final_result": FinalProcessingResult(
                email=email,
                intent=intent,
                oracle_result=oracle,
                reply=reply,
                final_status="BOOKING_ALTERNATIVES",
            )
        }

    monkeypatch.setattr("app.demo_file_flow._ensure_runtime_ready", lambda _: None)
    monkeypatch.setattr("app.demo_file_flow.run_workflow_for_email", fake_run_workflow_for_email)

    result, output_path = run_demo_file_flow(settings)

    assert result.final_status == "BOOKING_ALTERNATIVES"
    assert captured["email"].subject == "CEO demo request"
    assert "Please check availability" in captured["email"].body_text
    assert output_path.parent == output_dir
    output = output_path.read_text(encoding="utf-8")
    assert "HOTEL AI AGENT DEMO OUTPUT" in output
    assert "WHAT THE SYSTEM DETECTED" in output
    assert "ORACLE ACTION" in output
    assert "QUOTE PDF" in output
    assert "CUSTOMER REPLY" in output
    assert "We found an alternative stay" in output
    quote_pdf = output_path.with_name(output_path.name.replace("reply_", "quotation_")).with_suffix(".pdf")
    assert quote_pdf.exists()
    assert quote_pdf.read_bytes().startswith(b"%PDF-")


def test_workflow_loader_keeps_preloaded_demo_email(test_settings):
    email = EmailInput(
        email_id="demo",
        internet_message_id=None,
        subject="Preloaded",
        sender_name="Demo Customer",
        sender_email="demo.customer@example.com",
        received_datetime="2026-06-25T10:00:00Z",
        body_text="Hello",
    )

    assert load_newest_email({"settings": test_settings, "email": email}) == {}
