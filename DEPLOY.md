# Running it without your own PC

The bot is a small web server that WhatsApp calls whenever you send a message, so it has to be reachable on the internet whenever you might message it. Host it on a cloud service instead of your computer.

## Pick a host

Prices and limits as of Nov 2026; check the provider's page before relying on them.

| Host | Cost | Catch |
| --- | --- | --- |
| [Render](https://render.com) free web service | $0 | Sleeps after 15 min idle and takes about a minute to wake. The disk is wiped on every restart or sleep, so history and `/use` settings reset. Fine for trying it out. |
| [Railway](https://railway.com) Hobby | about $5/month | Always on. Attach a volume so the SQLite file survives restarts. |
| [Fly.io](https://fly.io) | about $4/month | Always on, but needs a Dockerfile and `fly.toml` (not included in this repo). |

No host keeps a Flask server awake for free indefinitely, so for daily use plan on roughly $5/month. For a quick test, Render free is enough.

## 1. Get your WhatsApp credentials (Meta)

1. Go to [developers.facebook.com](https://developers.facebook.com), create an app of type **Business**, and add the **WhatsApp** product.
2. On **WhatsApp > API Setup** you'll find the **Phone number ID** and a temporary **access token** (it expires after about a day). Add your own number as a recipient so the test number can message you.
3. For a token that doesn't expire, create a **system user** in Business Settings, give it access to the app and the WhatsApp account, and generate a token with the `whatsapp_business_messaging` permission.
4. **App settings > Basic** has the **App secret**.

## 2. Deploy

Any host that runs a `Procfile` works. The repo includes one:

```
web: gunicorn -w 1 --threads 4 -b 0.0.0.0:$PORT app:app
```

**Render (free test)**

1. New > Web Service > connect this GitHub repo.
2. Build command `pip install -r requirements.txt`, start command `gunicorn -w 1 --threads 4 -b 0.0.0.0:$PORT app:app`, instance type Free.
3. Add the environment variables below, then deploy. Your URL will look like `https://<name>.onrender.com`.

**Railway (always on)**

1. New project > deploy from GitHub repo, then add the environment variables below.
2. Add a volume mounted at `/data` and set `DATABASE_PATH=/data/data.sqlite3`.
3. Generate a public domain for the service.

**Environment variables**

| Variable | Value |
| --- | --- |
| `WHATSAPP_VERIFY_TOKEN` | Any random string you choose (used in step 3) |
| `WHATSAPP_ACCESS_TOKEN` | From step 1 |
| `WHATSAPP_PHONE_NUMBER_ID` | From step 1 |
| `META_APP_SECRET` | From step 1 |
| `OPENAI_API_KEY` | Your OpenAI key |
| `ANTHROPIC_API_KEY` | Your Anthropic key |
| `ALLOWED_PHONE_NUMBERS` | Your number, digits only, e.g. `40712345678` (strongly recommended) |

Check that `https://<your-url>/health` returns `{"ok": true}`.

## 3. Connect WhatsApp to your server

In the Meta dashboard go to **WhatsApp > Configuration**:

1. Callback URL: `https://<your-url>/webhook`
2. Verify token: the same `WHATSAPP_VERIFY_TOKEN` you set on the host.
3. Click **Verify and save**, then subscribe to the **messages** field.

Send `/help` to the bot's number. If you get the command list back, it's working. See [USAGE.md](USAGE.md) for everything you can do.

## Troubleshooting

- **Verify fails:** the verify token doesn't match, or the host is still waking up. Open `/health` first, then retry.
- **No reply:** check the host's logs. A 403 on `/webhook` means `META_APP_SECRET` is wrong or unset.
- **"Sorry, that request failed (401 ...)":** an API key is wrong. The error text in the reply says which service rejected it.
- **Replies stop after a day:** you're using the temporary access token; create the system user token from step 1.
