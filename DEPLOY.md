# Deploy (Railway, Fly or Render)

Build from the repo root with `infra/Dockerfile`. The service listens on `$PORT` (default 8000).

Environment variables to set on the host (never in the repo):

| Variable | Value |
|---|---|
| `TEAM_TOKEN` | the team token from the platform card |
| `OPENROUTER_API_KEY` | the OpenRouter key |
| `MODEL_FAST` | `anthropic/claude-sonnet-5.5` |
| `MODEL_STRONG` | `anthropic/claude-opus-5.5` |
| `BUDGET_USD` | `40` (hard stop; the account cap is 45) |

Check from outside (token in the header, as the evaluator sends it):

    curl -H "Authorization: Bearer $TEAM_TOKEN" https://<public-url>/health   # {"ok":true,"model_ready":true}

Do not add a platform health check that calls `/health` without the token: it answers 401 by contract.
Register the public URL and the team token on the platform before 19:00 MDT.

Run one replica only: the task registry and budget ledger live on local disk under `DATA_DIR`.
