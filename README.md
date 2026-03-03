# support-chat

Python FastAPI bridge for WhatsApp support bot:

`WhatsApp user -> Twilio webhook -> this service -> OpenAI Safe Support Agent -> Twilio reply`

## Stack

- Python 3.9+
- FastAPI + Uvicorn
- OpenAI Responses API (`file_search` + tool loop)
- Twilio WhatsApp webhook validation

## Quick start

1. Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Create env:

```bash
cp .env.example .env
```

3. Fill required variables:

- `OPENAI_API_KEY`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN` (required when `TWILIO_VALIDATE_SIGNATURE=true`)
- `FAQ_VECTOR_STORE_ID`
- `PUBLIC_BASE_URL` (required for stable signature validation behind proxy/ngrok)

4. Run service:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

5. Health check:

```bash
curl -i http://127.0.0.1:8080/health
```

## Local smoke test

Temporary local mode:

```env
TWILIO_VALIDATE_SIGNATURE=false
```

When signature validation is disabled, `AccountSid` check is also skipped to simplify local smoke testing.

Test webhook:

```bash
curl -i -X POST http://127.0.0.1:8080/webhooks/whatsapp \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "From=whatsapp:+77001234567" \
  --data-urlencode "Body=Как связаться с поддержкой?"
```

## Render deploy

This repo includes `render.yaml`.

1. Push to GitHub.
2. Render -> New -> Blueprint -> pick this repository.
3. Set secret envs in Render dashboard.
4. Configure Twilio webhook URL:

`https://<your-render-domain>/webhooks/whatsapp`

## Vercel deploy

This repository includes `vercel.json` and `api/index.py` as a FastAPI entrypoint for Vercel.

Set required environment variables in Vercel Project Settings:

- `OPENAI_API_KEY`
- `OPENAI_MODEL` (optional, default is `gpt-4o-mini`)
- `FAQ_VECTOR_STORE_ID` (optional; without it bot replies with operator review fallback)
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN` (required when `TWILIO_VALIDATE_SIGNATURE=true`)
- `TWILIO_VALIDATE_SIGNATURE=true`
- `PUBLIC_BASE_URL=https://<your-vercel-domain>`
- `STATE_FILE=/tmp/state.json`

Then verify:

```bash
curl -i https://<your-vercel-domain>/health
```
