# Troubleshooting

## Missing OpenAI API Key

Symptom:

```text
OPENAI_API_KEY is empty
```

Impact:

- In strict real mode, the app stops immediately.
- In sample/demo fallback mode, the app can still use local fallbacks.

Fix:

```env
OPENAI_API_KEY=your_key_here
```

Then run:

```powershell
python -m app.rag.ingest_policy
python -m app.main
```

For strict real mode, also keep:

```env
STRICT_REAL_MODE=true
ALLOW_LOCAL_AI_FALLBACK=false
```

## Missing Microsoft Graph Credentials

Symptom:

```text
Missing Microsoft Graph credentials.
```

Fix:

For delegated mode, set:

```env
MS_AUTH_MODE=delegated
MS_CLIENT_ID=
MS_TENANT_ID=
MS_CLIENT_SECRET=
MS_USER_EMAIL=
```

For old application mode, set:

```env
MS_AUTH_MODE=application
MS_TENANT_ID=
MS_CLIENT_ID=
MS_CLIENT_SECRET=
MS_USER_EMAIL=
```

For demos without Outlook, set:

```env
EMAIL_SOURCE=file
USE_SAMPLE_EMAIL=false
```

Then put a real copied email into `data/sample_inbox/latest_email.json`.

## Email File Errors

Symptom:

```text
Email file not found
```

Fix:

Create:

```text
data/sample_inbox/latest_email.json
```

Use the `EmailInput` JSON shape shown in `NEXT_STEPS.md`.

Symptom:

```text
Email file is not valid EmailInput JSON
```

Fix:

- Check commas and quotes.
- Ensure required fields exist: `email_id`, `subject`, `sender_email`, `received_datetime`, `body_text`.

## Policy PDF Not Found

Symptom:

```text
Policy PDF not found. Add Enhanced_Hotel_Reservation_OTA_Policy_Document_v4_FULL_EXCEL_COVERAGE.pdf
```

Fix:

Place the PDF here:

```text
data/policy/Enhanced_Hotel_Reservation_OTA_Policy_Document_v4_FULL_EXCEL_COVERAGE.pdf
```

Then run:

```powershell
python -m app.rag.ingest_policy
```

## ChromaDB Errors

Symptoms:

- Collection dimension mismatch.
- Embedding function errors.
- Old policy context appears after changing files.

Fix:

```powershell
Remove-Item -Recurse -Force data\chroma
python -m app.rag.ingest_policy
```

If OpenAI embeddings fail, verify `OPENAI_API_KEY`. Without a key, the app falls back to Chroma defaults where available.

## Cost Control

Default low-cost settings:

```env
USE_OPENAI_POLICY_ANSWER=false
FORCE_POLICY_REINGEST=false
```

Expected behavior:

- `python -m app.rag.ingest_policy` embeds the PDF once.
- If the PDF and embedding model are unchanged, ingestion returns `skipped: 1` and does not call embeddings again.
- Policy answers are extracted from retrieved PDF context without extra policy-answer LLM calls.
- The normal per-email OpenAI calls are intent extraction, query embeddings, and final reply generation.

## Import Or Module Errors

Symptom:

```text
ModuleNotFoundError
```

Fix:

Run from the project root:

```powershell
cd "C:\AI Labs\AI\hotel-ai-agent"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest
```

## Pytest Failures

Fix order:

1. Read the first failure.
2. Fix only the failing behavior.
3. Run `python -m pytest` again.

Expected healthy result:

```text
36 passed
```

## Outlook Permission Issues

Symptoms:

- Graph authentication fails.
- Graph request returns `401`, `403`, or permission-related JSON.

Fix:

- Verify Azure app registration values.
- Confirm application permissions for Microsoft Graph mail access.
- Confirm admin consent has been granted.
- Confirm `MS_USER_EMAIL` is the mailbox the app can access.
- Keep `AUTO_SEND_EMAILS=false` until draft behavior is verified.

For delegated mode:

- Ensure the app registration supports personal Microsoft accounts if using Outlook.com.
- Ensure public client/device-code flow is enabled.
- Ensure delegated Microsoft Graph permissions include `User.Read`, `Mail.ReadWrite`, `Mail.Send`, and `offline_access`.
- If you logged into the wrong account, delete `data/msal_token_cache.json` and run again.
