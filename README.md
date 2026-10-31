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
| `/use` | Show your current default and its model/effort |
| `/use claude sonnet medium` | Default to Claude Sonnet 5.5 at medium effort |
| `/use gpt best low` | Default to the best GPT model at low effort |
| `/use gpt small` | Default to the smallest GPT model |
| `/use claude high` | Change only the effort (keeps the model) |
| `/reset` | Clear your default model's history |
| `/help` | Show commands |

`/use <gpt\|claude> [model] [effort]` takes the model and effort in any order, and each provider remembers its own settings per phone number.

- **GPT models:** `small` (`gpt-5.4-nano`, the default), `mini` (`gpt-5.4-mini`), `best` (`gpt-6-astra`)
- **Claude models:** `sonnet` (`claude-sonnet-5-5`, the default), `opus`, `haiku`, `fable`
- **Any model ID** also works, e.g. `/use gpt gpt-5.4-mini`
- **Effort:** `low`, `medium`, `high`, `xhigh`, `max` (GPT also accepts `none`); `default` clears it. Which levels a given model accepts is up to the API; if it rejects one, the reply shows the error.

Set `ALLOWED_PHONE_NUMBERS` to restrict who can use the bot. `GET /health` returns `{"ok": true}`.
