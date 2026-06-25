from __future__ import annotations

from pathlib import Path

from app.ai.schemas import FinalProcessingResult, OracleAvailabilityOption


def write_quotation_pdf(result: FinalProcessingResult, path: Path) -> Path:
    lines = quotation_lines(result)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_simple_pdf(lines))
    return path


def should_create_quotation(result: FinalProcessingResult) -> bool:
    oracle = result.oracle_result
    return bool(
        oracle
        and oracle.success
        and oracle.operation in {"availability_checked", "booking_alternatives"}
        and oracle.options
    )


def quotation_lines(result: FinalProcessingResult) -> list[str]:
    oracle = result.oracle_result
    booking = result.intent.booking_request
    lines = [
        "Hotel Reservation Quotation",
        "",
        f"Customer: {booking.guest_name if booking and booking.guest_name else result.email.sender_name or 'Customer'}",
        f"Email: {result.email.sender_email}",
        f"Hotel code: {booking.hotel_code if booking and booking.hotel_code else 'GB0783'}",
        f"Requested stay: {oracle.requested_arrival_date if oracle else 'N/A'} to {oracle.requested_departure_date if oracle else 'N/A'}",
        f"Rooms: {booking.rooms if booking and booking.rooms is not None else 'Not provided'}",
        f"Adults: {booking.adults if booking and booking.adults is not None else 'Not provided'}",
        f"Children: {booking.children if booking and booking.children is not None else '0'}",
        "",
        "Quoted options",
    ]
    if oracle:
        for index, option in enumerate(oracle.options, start=1):
            lines.extend(_option_lines(index, option))
    lines.extend(
        [
            "",
            "Notes",
            "- Room type is fixed to the configured Oracle room type.",
            "- Amounts are before tax unless Oracle returned another basis.",
            "- Rates are subject to availability and final confirmation at the time of reservation.",
            "- This quotation is not a reservation confirmation.",
        ]
    )
    return lines


def _option_lines(index: int, option: OracleAvailabilityOption) -> list[str]:
    amount = "Not returned"
    if option.amount_before_tax is not None:
        currency = f" {option.currency_code}" if option.currency_code else ""
        amount = f"{option.amount_before_tax:g}{currency} before tax"
    return [
        "",
        f"{index}. Stay: {option.arrival_date} to {option.departure_date}",
        f"   Room type: {option.room_type}",
        f"   Rate plan: {option.rate_plan_code or 'Not returned'}",
        f"   Available units: {option.number_of_units if option.number_of_units is not None else 'Not returned'}",
        f"   Quoted amount: {amount}",
    ]


def _simple_pdf(lines: list[str]) -> bytes:
    content_lines: list[str] = ["BT", "/F1 16 Tf", "1 0 0 1 72 760 Tm", f"({_escape_pdf_text(lines[0])}) Tj"]
    content_lines.extend(["/F1 10 Tf"])
    y = 736
    for line in lines[1:]:
        if y < 72:
            break
        content_lines.append(f"1 0 0 1 72 {y} Tm")
        content_lines.append(f"({_escape_pdf_text(line)}) Tj")
        y -= 16
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
