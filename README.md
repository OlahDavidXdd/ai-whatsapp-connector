# ai-whatsapp-connector

Chat with GPT or Claude from WhatsApp. A small Flask app that receives WhatsApp Cloud API webhooks, forwards your message to OpenAI or Anthropic, and replies in the same chat. History is kept per phone number and per model in SQLite.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your keys
python app.py          # or: gunicorn -b 0.0.0.0:8000 app:app
```

Expose it over HTTPS (host it, or use a tunnel such as `ngrok http 8000` for testing), then in the Meta developer dashboard set the webhook callback URL to `https://<your-host>/webhook`, the verify token to your `WHATSAPP_VERIFY_TOKEN`, and subscribe to the `messages` field.

## Commands

| Message | Effect |
| --- | --- |
| any text | Sent to your default model |
| `/gpt <msg>` | One message to GPT |
| `/claude <msg>` | One message to Claude |
| `/use gpt` / `/use claude` | Change your default model |
| `/reset` | Clear your default model's history |
| `/help` | Show commands |

Set `ALLOWED_PHONE_NUMBERS` to restrict who can use the bot. `GET /health` returns `{"ok": true}`.
