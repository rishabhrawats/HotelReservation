# Next Steps

Run these commands from:

```powershell
cd "C:\AI Labs\AI\hotel-ai-agent"
```

## 1. Add the Policy PDF

Place this exact file in `data/policy/`:

```text
Enhanced_Hotel_Reservation_OTA_Policy_Document_v4_FULL_EXCEL_COVERAGE.pdf
```

Expected result:

- `data/policy/Enhanced_Hotel_Reservation_OTA_Policy_Document_v4_FULL_EXCEL_COVERAGE.pdf` exists.
- `Dry run.xlsx` may exist, but it will be ignored.

If it fails:

- Check the filename spelling.
- Check that the file is inside `hotel-ai-agent\data\policy`, not another folder.

## 2. Fill Real Credentials

Open `.env` and fill:

```env
OPENAI_API_KEY=
MS_CLIENT_ID=
```

Keep these values:

```env
EMAIL_SOURCE=file
EMAIL_FILE_PATH=data/sample_inbox/latest_email.json
MS_AUTH_MODE=delegated
MS_TENANT_ID=
MS_CLIENT_SECRET=
MS_USER_EMAIL=
USE_SAMPLE_EMAIL=false
STRICT_REAL_MODE=true
ALLOW_LOCAL_AI_FALLBACK=false
AUTO_SEND_EMAILS=false
ENABLE_ORACLE_API=false
USE_OPENAI_POLICY_ANSWER=false
FORCE_POLICY_REINGEST=false
```

Expected result:

- The app uses real OpenAI calls.
- The app reads real copied/exported email content from `data/sample_inbox/latest_email.json`.
- The app creates drafts only.
- Oracle remains disabled.
- API cost stays low: no policy-answer LLM calls by default, and unchanged PDF ingestion skips embeddings.

If it fails:

- Missing OpenAI key means ingestion and AI processing will stop.
- Missing or invalid `latest_email.json` means the email file needs to be created or fixed.

## 3. Ingest Policy With Real OpenAI Embeddings

```powershell
python -m app.rag.ingest_policy
```

Expected output:

```text
{'blocks': <number greater than 0>, 'chunks': <number greater than 0>}
```

If it says `0` blocks or `0` chunks:

- The PDF is missing, empty, encrypted, or not text-extractable.
- Re-check the file path and try opening the PDF manually.

If it says `skipped: 1`, that is good. It means the PDF has not changed and the app avoided re-embedding cost.

## 4. Create Or Replace The Real Email File

Edit:

```text
data/sample_inbox/latest_email.json
```

Use this shape:

```json
{
  "email_id": "manual-real-email-001",
  "internet_message_id": null,
  "subject": "Hotel Booking and Early Check-in Request",
  "sender_name": "Customer Name",
  "sender_email": "customer@example.com",
  "received_datetime": "2026-06-25T10:00:00Z",
  "body_text": "Paste the real Outlook email body here.",
  "is_read": false
}
```

Expected:

- This file contains real email text copied from Outlook.
- It does not need Microsoft Graph access.

## 5. Run Real File-Mode Draft Flow

```powershell
$env:USE_SAMPLE_EMAIL='false'
$env:EMAIL_SOURCE='file'
$env:AUTO_SEND_EMAILS='false'
$env:ENABLE_ORACLE_API='false'
$env:STRICT_REAL_MODE='true'
$env:ALLOW_LOCAL_AI_FALLBACK='false'
python -m app.main
```

Expected output:

- Final JSON result is printed.
- Reply subject and body are printed.
- A local draft is created under `logs/`.
- No real email is sent.
- The real copied email file is processed.
- The reply acknowledges receipt only.
- The reply does not say confirmed, booked successfully, or confirmation number.

If policy answers still say context is insufficient:

- Run `python -m app.rag.ingest_policy` again after adding the PDF.
- Confirm `CHROMA_DIR=data/chroma` in `.env`.
- Delete `data/chroma/` and re-ingest if the vector store was created before the PDF was added.

## 6. Run Tests

```powershell
python -m pytest
```

Expected output:

```text
36 passed
```

If tests fail:

- Read the first failing test.
- Fix the named code path only.
- Re-run `python -m pytest`.
