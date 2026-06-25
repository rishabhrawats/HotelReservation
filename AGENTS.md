# Coding Rules

- No hardcoded secrets.
- No Oracle real calls.
- No booking confirmation without Oracle.
- No retry.
- No waitlist.
- No invented hotel policy answers.
- RAG must use only PDF policy documents; ignore Excel files completely.
- All LLM outputs must be validated with Pydantic.
- RAG answers must be based on retrieved policy chunks.
- Email sending is disabled by default.
- Customer replies must be professional and safe.
- Tests must pass before changes are considered complete.
