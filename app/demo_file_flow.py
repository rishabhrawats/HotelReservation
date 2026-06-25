from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.ai.schemas import EmailInput, FinalProcessingResult, OracleOperationResult
from app.config import Settings, load_settings
from app.db.session import init_db
from app.graph.workflow import run_workflow_for_email
from app.rag.ingest_policy import ingest_policy, policy_pdf_files
from app.rag.vector_store import get_vector_store
from app.tools.quotation_pdf import should_create_quotation, write_quotation_pdf
from app.utils.logging import configure_logging


def run_demo_file_flow(settings: Settings | None = None) -> tuple[FinalProcessingResult, Path]:
    settings = settings or load_settings()
    settings = replace(settings, auto_send_emails=False)
    _ensure_runtime_ready(settings)
    email = _email_from_body_file(settings.demo_email_body_path)
    state = run_workflow_for_email(email, settings)
    result = state["final_result"]
    output_path = _write_demo_output(result, settings)
    return result, output_path


def _ensure_runtime_ready(settings: Settings) -> None:
    init_db(settings)
    settings.demo_email_body_path.parent.mkdir(parents=True, exist_ok=True)
    settings.demo_output_dir.mkdir(parents=True, exist_ok=True)
    settings.policy_dir.mkdir(parents=True, exist_ok=True)

    policy_files = policy_pdf_files(settings.policy_dir)
    try:
        store = get_vector_store(settings)
        if store.count() == 0 and policy_files:
            ingest_policy(settings)
    except Exception:
        if settings.strict_real_mode:
            raise


def _email_from_body_file(path: Path) -> EmailInput:
    if not path.exists():
        raise RuntimeError(
            f"Demo input file not found: {path}. Create it or use DEMO_EMAIL_BODY_PATH to point to another file."
        )
    raw_body = path.read_text(encoding="utf-8").strip()
    if not raw_body:
        raise RuntimeError(f"Demo input file is empty: {path}")

    subject, body = _extract_subject(raw_body)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return EmailInput(
        email_id=f"demo-file-{timestamp}",
        internet_message_id=f"<demo-file-{timestamp}@local>",
        subject=subject,
        sender_name="Demo Customer",
        sender_email="demo.customer@example.com",
        received_datetime=datetime.now(timezone.utc).isoformat(),
        body_text=body,
        is_read=False,
    )


def _extract_subject(raw_body: str) -> tuple[str, str]:
    lines = raw_body.splitlines()
    first = lines[0].strip() if lines else ""
    if first.lower().startswith("subject:"):
        subject = first.split(":", 1)[1].strip() or "Demo customer request"
        body = "\n".join(lines[1:]).strip()
        return subject, body or subject
    return "Demo customer request", raw_body


def _write_demo_output(result: FinalProcessingResult, settings: Settings) -> Path:
    settings.demo_output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_status = "".join(ch for ch in result.final_status.lower() if ch.isalnum() or ch in {"-", "_"})
    path = settings.demo_output_dir / f"reply_{timestamp}_{safe_status}.txt"
    pdf_path = path.with_name(f"quotation_{timestamp}_{safe_status}.pdf")
    quote_pdf_path = write_quotation_pdf(result, pdf_path) if should_create_quotation(result) else None
    path.write_text(_format_demo_output(result, quote_pdf_path), encoding="utf-8")
    return path


def _format_demo_output(result: FinalProcessingResult, quote_pdf_path: Path | None = None) -> str:
    intent = result.intent
    lines = [
        "HOTEL AI AGENT DEMO OUTPUT",
        "",
        "INPUT EMAIL",
        f"From: {result.email.sender_name or result.email.sender_email} <{result.email.sender_email}>",
        f"Subject: {result.email.subject}",
        "",
        result.email.body_text,
        "",
        "WHAT THE SYSTEM DETECTED",
        f"Primary intent: {intent.primary_intent}",
        f"Next action: {intent.next_action}",
        f"Summary: {intent.customer_message_summary}",
    ]
    if intent.booking_request:
        booking = intent.booking_request
        lines.extend(
            [
                "",
                "BOOKING DETAILS EXTRACTED",
                f"Guest: {booking.guest_name or 'Not provided'}",
                f"Arrival: {booking.arrival_date or 'Not provided'}",
                f"Departure: {booking.departure_date or 'Not provided'}",
                f"Adults: {booking.adults if booking.adults is not None else 'Not provided'}",
                f"Children: {booking.children if booking.children is not None else 'Not provided'}",
                f"Rooms: {booking.rooms if booking.rooms is not None else 'Not provided'}",
                f"Reference: {booking.booking_reference or booking.ota_reference or booking.custom_reference or 'Not provided'}",
                f"Missing fields: {', '.join(booking.missing_fields) if booking.missing_fields else 'None'}",
            ]
        )
    if result.oracle_result:
        lines.extend(["", "ORACLE ACTION", *_oracle_lines(result.oracle_result)])
    if quote_pdf_path:
        lines.extend(["", "QUOTE PDF", str(quote_pdf_path)])
    if result.policy_answers:
        lines.extend(["", "POLICY ANSWERS USED"])
        for index, answer in enumerate(result.policy_answers, start=1):
            source_text = ", ".join(answer.sources) if answer.sources else "No source label"
            lines.extend(
                [
                    f"{index}. {answer.question}",
                    f"   Answer: {answer.answer}",
                    f"   Sources: {source_text}",
                ]
            )
    lines.extend(
        [
            "",
            "CUSTOMER REPLY",
            f"To: {result.email.sender_email}",
            f"Subject: {result.reply.reply_subject}",
            "",
            result.reply.reply_body,
            "",
            "FINAL STATUS",
            result.final_status,
        ]
    )
    if result.errors:
        lines.extend(["", "ERRORS", *result.errors])
    return "\n".join(lines).rstrip() + "\n"


def _oracle_lines(oracle: OracleOperationResult) -> list[str]:
    lines = [
        f"Operation: {oracle.operation}",
        f"Success: {oracle.success}",
        f"Message: {oracle.message}",
    ]
    if oracle.requested_arrival_date or oracle.requested_departure_date:
        lines.append(f"Requested stay: {oracle.requested_arrival_date} to {oracle.requested_departure_date}")
    if oracle.reservation_id:
        lines.append(f"Reservation ID: {oracle.reservation_id}")
    if oracle.confirmation_number:
        lines.append(f"Confirmation number: {oracle.confirmation_number}")
    if oracle.cancellation_id:
        lines.append(f"Cancellation ID: {oracle.cancellation_id}")
    if oracle.custom_reference:
        lines.append(f"Custom reference: {oracle.custom_reference}")
    if oracle.options:
        lines.append("Available options:")
        for option in oracle.options:
            price = "price not returned"
            if option.amount_before_tax is not None:
                currency = f" {option.currency_code}" if option.currency_code else ""
                price = f"{option.amount_before_tax:g}{currency} before tax"
            lines.append(
                "  - "
                f"{option.arrival_date} to {option.departure_date}, "
                f"room {option.room_type or 'configured room'}, {price}"
            )
    if oracle.error:
        lines.append(f"Oracle error: {oracle.error}")
    return lines


def cli() -> int:
    configure_logging()
    try:
        result, output_path = run_demo_file_flow()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Demo output written to: {output_path}")
    quote_pdf = _quote_pdf_for_output(output_path)
    if quote_pdf.exists():
        print(f"Quotation PDF written to: {quote_pdf}")
    print("\nReply Subject:")
    print(result.reply.reply_subject)
    print("\nReply Body:")
    print(result.reply.reply_body)
    return 0


def _quote_pdf_for_output(output_path: Path) -> Path:
    return output_path.with_name(output_path.name.replace("reply_", "quotation_")).with_suffix(".pdf")


if __name__ == "__main__":
    raise SystemExit(cli())
