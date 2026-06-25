# Status

Last updated: 2026-06-25

## Current State

- Project structure is in place under `hotel-ai-agent/`.
- LangGraph orchestrates the workflow in `app/graph/workflow.py`.
- Intent extraction and reply generation use the direct OpenAI SDK with Pydantic structured outputs when `OPENAI_API_KEY` is configured.
- Local deterministic fallbacks keep tests and sample mode runnable without OpenAI credentials.
- RAG uses ChromaDB directly.
- RAG ingestion is PDF-only.
- Excel files, including `Dry run.xlsx`, are ignored.
- Oracle booking functions are stubs and raise `NotImplementedError`.
- Email sending is disabled by default with `AUTO_SEND_EMAILS=false`.
- Strict real mode is configured in `.env` with `STRICT_REAL_MODE=true` and `ALLOW_LOCAL_AI_FALLBACK=false`.
- Outlook now supports delegated device-code login with `MS_AUTH_MODE=delegated`, so tenant admin consent is not required for the test path.
- File email source is implemented with `EMAIL_SOURCE=file` for real copied/exported email content when Microsoft Graph access is blocked.
- Cost controls are active: unchanged policy PDFs skip re-embedding, and policy-answer LLM calls are off by default.
- SQLite logging is implemented.
- FastAPI endpoints are implemented.

## Verified

- `python -m pytest` passed: 22 tests passed.
- `python -m pytest` passed: 36 tests passed.
- `python -m app.rag.ingest_policy` reads the policy PDF and creates 55 chunks from 24 PDF page blocks.
- `python -m app.main` works in sample mode with `USE_SAMPLE_EMAIL=true`.
- Sample mode creates a local draft and does not send real email.
- Sample mode detects booking request, early check-in question, and luggage-storage question.
- Replies use PDF RAG answers, do not confirm booking, and do not say booked.

## Pending

- Configure Microsoft Graph credentials before Outlook mode.
- For delegated Outlook mode, configure only `MS_CLIENT_ID` and sign in via the device-code prompt.
- Configure `OPENAI_API_KEY` before strict real ingestion and strict real processing.
- For immediate CEO demo without Microsoft access, use `EMAIL_SOURCE=file` and update `data/sample_inbox/latest_email.json`.
- Decide whether to keep testing in sample mode or move to Outlook mode.

## Latest Test Result

```text
36 passed
```
