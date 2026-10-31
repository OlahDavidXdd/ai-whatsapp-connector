# ai-whatsapp-connector

Chat with GPT or Claude from WhatsApp. A small Flask app that receives WhatsApp Cloud API webhooks, forwards your message to OpenAI or Anthropic, and replies in the same chat. History is kept per phone number and per model in SQLite. Pick the model and reasoning effort from the chat, e.g. `/use claude sonnet medium` or `/use gpt best low`.

## Docs

- **[USAGE.md](USAGE.md)**: the usage manual (all commands, models, effort levels)
- **[DEPLOY.md](DEPLOY.md)**: run it in the cloud so your PC doesn't need to stay on, plus the Meta/WhatsApp setup

## Quick start (local)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your keys
python app.py          # or: gunicorn -w 1 --threads 4 -b 0.0.0.0:8000 app:app
```

Expose it over HTTPS (a tunnel such as `ngrok http 8000` works for testing), then in the Meta developer dashboard set the webhook callback URL to `https://<your-host>/webhook`, the verify token to your `WHATSAPP_VERIFY_TOKEN`, and subscribe to the `messages` field. For hosting it permanently, see [DEPLOY.md](DEPLOY.md).

## Commands (short version)

| Message | Effect |
| --- | --- |
| any text | Sent to your default model |
| `/gpt <msg>` / `/claude <msg>` | One message to that model |
| `/use` | Show your current default |
| `/use claude sonnet medium` | Claude Sonnet 5.5 on medium effort |
| `/use gpt best low` | Best GPT model on low effort |
| `/use gpt small` | Smallest GPT model (starting default) |
| `/reset` | Clear your default model's history |
| `/help` | Show commands |

Full details in [USAGE.md](USAGE.md). Set `ALLOWED_PHONE_NUMBERS` to restrict who can use the bot. `GET /health` returns `{"ok": true}`.
