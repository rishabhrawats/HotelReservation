# Runbook

## 1. Set Up Python

```powershell
cd "C:\AI Labs\AI\hotel-ai-agent"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Expected output:

- Dependencies install successfully.
- `.env` exists.

## 2. Configure `.env`

Minimum sample-mode config:

```env
USE_SAMPLE_EMAIL=true
AUTO_SEND_EMAILS=false
ENABLE_ORACLE_API=false
STRICT_REAL_MODE=false
ALLOW_LOCAL_AI_FALLBACK=true
POLICY_DIR=data/policy
CHROMA_DIR=data/chroma
SQLITE_DB_PATH=data/hotel_agent.db
```

Optional OpenAI config:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Outlook mode config:

```env
USE_SAMPLE_EMAIL=false
STRICT_REAL_MODE=true
ALLOW_LOCAL_AI_FALLBACK=false
MS_AUTH_MODE=delegated
MS_TENANT_ID=
MS_CLIENT_ID=
MS_CLIENT_SECRET=
MS_USER_EMAIL=
OUTLOOK_FOLDER=Inbox
```

For delegated mode, only `MS_CLIENT_ID` is required for Microsoft login. Leave `MS_TENANT_ID`, `MS_CLIENT_SECRET`, and `MS_USER_EMAIL` empty unless you later switch back to application mode.

Real file-mode config when Microsoft Graph access is blocked:

```env
EMAIL_SOURCE=file
EMAIL_FILE_PATH=data/sample_inbox/latest_email.json
USE_SAMPLE_EMAIL=false
STRICT_REAL_MODE=true
ALLOW_LOCAL_AI_FALLBACK=false
AUTO_SEND_EMAILS=false
ENABLE_ORACLE_API=false
USE_OPENAI_POLICY_ANSWER=false
FORCE_POLICY_REINGEST=false
```

Cost rule: keep `USE_OPENAI_POLICY_ANSWER=false` unless you explicitly need LLM-written policy answers. Keep `FORCE_POLICY_REINGEST=false` unless the PDF changed and you intentionally want to re-embed.

## 3. Add Policy PDF

Copy the policy PDF to:

```text
data/policy/Enhanced_Hotel_Reservation_OTA_Policy_Document_v4_FULL_EXCEL_COVERAGE.pdf
```

Excel files are ignored.

## 4. Ingest Policy

```powershell
python -m app.rag.ingest_policy
```

Expected output:

```text
{'blocks': <number greater than 0>, 'chunks': <number greater than 0>}
```

In strict real mode this requires `OPENAI_API_KEY`, because embeddings must be real OpenAI embeddings.

## 5. Run Sample Mode

```powershell
$env:USE_SAMPLE_EMAIL='true'
$env:AUTO_SEND_EMAILS='false'
$env:ENABLE_ORACLE_API='false'
python -m app.main
```

Expected output:

- Booking request detected.
- Early check-in question detected.
- Luggage-storage question detected.
- Booking details extracted.
- PDF RAG answers generated if policy context exists.
- Safe booking acknowledgement generated.
- No real email sent.
- SQLite log saved.

## 6. Run Outlook Mode

Set:

```env
USE_SAMPLE_EMAIL=false
STRICT_REAL_MODE=true
ALLOW_LOCAL_AI_FALLBACK=false
```

Ensure Microsoft Graph credentials are configured, then run:

```powershell
python -m app.main
```

Expected output:

- Newest Outlook email is fetched.
- Reply is drafted locally when `AUTO_SEND_EMAILS=false`.
- Intent, policy answering, and reply generation use real OpenAI structured outputs.
- First run may prompt device-code sign-in and save `data/msal_token_cache.json`.

## 6A. Run File Mode Instead Of Outlook

Use this when Microsoft Graph access is blocked:

```powershell
python -m app.main
```

Expected output:

- The email is loaded from `data/sample_inbox/latest_email.json`.
- OpenAI structured outputs are used.
- PDF RAG is used.
- Local draft is written under `logs/`.
- No real email is sent.

## 7. Run Tests

```powershell
python -m pytest
```

Expected output:

```text
36 passed
```

## 8. Enable Email Sending Safely

Only after draft behavior is verified, set:

```env
AUTO_SEND_EMAILS=true
```

Then run one controlled test email through Outlook mode.

Safety expectations:

- Oracle is not called.
- Booking is not confirmed.
- The reply says the request was received.
- The email is marked read only after successful send.
