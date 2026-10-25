# Isolated hackathon reasoning integration

Branch: `feat/litellm-reasoning`.
Worktree: `/tmp/nyayalens-litellm-reasoning`.

This worktree is intentionally separate from the in-progress production speech and UI deployment. It selects the real `gpt-6-luna` LiteLLM deployment for the analysis agents that call `_pro_llm()`, when `LITELLM_API_KEY` is configured. Intake, lightweight extraction, speech, and research remain on their existing providers. Without a LiteLLM key, the existing Gemini pro model is retained.

The key is held only in the ignored `backend/.env`, with filesystem mode 0600. No key is included in code or browser output. Configuration includes `LITELLM_BASE_URL`, `LITELLM_MODEL`, and `LITELLM_TEAM_CODE` (sent as `X-Team-Code`).

To run this isolated branch with the existing Python environment:

```bash
cd /tmp/nyayalens-litellm-reasoning/backend
/home/manav/Downloads/Sarcathon/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Port 8001 is used to keep the production-worktree verification server on port 8000 untouched. A complete branch deployment still requires the existing Gemini and Indian Kanoon configuration. Only final response content is returned; private reasoning fields are never exposed. Structured results are validated using the caller's Pydantic model.

## Verified against the live API

- Model discovery: HTTP 200; `gpt-6-luna` is listed.
- Chat completion: HTTP 200 in 2.68 seconds; deployment returned the requested JSON.
- Structured legal reasoning: passed Pydantic validation. Correctly identified conflicting accident dates, kept the absent FIR unresolved, distinguished the client's witness claim from independent confirmation, and declined an unsupported numerical outcome probability.
- Python compilation and `git diff --check`: passed.

This verifies the provider adapter and reasoning contract. It does not claim to have tested this separate branch's entire legacy voice/deployment flow.
