from app.email.email_cleaner import clean_email_body


def test_email_cleaner_removes_html_and_quoted_trail():
    body = """
    <html><body><p>Hello,<br>Please book a room.</p>
    <p>Thanks</p>
    <p>From: Old Sender</p>
    <p>Sent: Yesterday</p>
    <p>Old reply chain</p></body></html>
    """

    cleaned = clean_email_body(body)

    assert "Please book a room." in cleaned
    assert "Old reply chain" not in cleaned
    assert "<p>" not in cleaned

