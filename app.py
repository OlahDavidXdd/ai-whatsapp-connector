import hashlib
import hmac
import json
import logging
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import requests
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("whatsapp-ai")

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=4)

# Configure these as environment variables, not in your GitHub repo.
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WA_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
WA_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v22.0")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-nano")  # smallest GPT model
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

DATABASE_PATH = os.getenv("DATABASE_PATH", "data.sqlite3")
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "16"))
ALLOWED_NUMBERS = {
    number.strip()
    for number in os.getenv("ALLOWED_PHONE_NUMBERS", "").split(",")
    if number.strip()
}

FALLBACK_REPLY = "I couldn't produce a text response."

PROVIDERS = ("gpt", "claude")
DEFAULT_MODELS = {"gpt": OPENAI_MODEL, "claude": ANTHROPIC_MODEL}

# Shortcuts for `/use <provider> <shortcut> <effort>`. Any raw model ID also works.
MODEL_ALIASES = {
    "gpt": {
        "small": "gpt-5.4-nano",
        "nano": "gpt-5.4-nano",
        "mini": "gpt-5.4-mini",
        "best": "gpt-6-astra",
        "astra": "gpt-6-astra",
    },
    "claude": {
        "sonnet": "claude-sonnet-5-5",
        "opus": "claude-opus-5-5",
        "haiku": "claude-haiku-5-5",
        "fable": "claude-fable-5-1",
    },
}
# Reasoning effort levels each API accepts ("default" clears the setting).
EFFORTS = {
    "gpt": {"none", "low", "medium", "high", "xhigh", "max"},
    "claude": {"low", "medium", "high", "xhigh", "max"},
}
ALL_EFFORTS = EFFORTS["gpt"] | EFFORTS["claude"]


@contextmanager
def db():
    """Open a connection, commit on success, always close it."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=20)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                phone TEXT PRIMARY KEY,
                provider TEXT NOT NULL DEFAULT 'gpt'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS provider_settings (
                phone TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                effort TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (phone, provider)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                provider TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS turns_lookup
            ON turns(phone, provider, id)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS inbound_ids (
                message_id TEXT PRIMARY KEY
            )
        """)


# Initialize tables for both `python app.py` and Gunicorn.
init_db()


def get_default_provider(phone):
    with db() as conn:
        row = conn.execute(
            "SELECT provider FROM settings WHERE phone = ?", (phone,)
        ).fetchone()
    return row[0] if row else "gpt"


def set_default_provider(phone, provider):
    with db() as conn:
        conn.execute("""
            INSERT INTO settings(phone, provider) VALUES(?, ?)
            ON CONFLICT(phone) DO UPDATE SET provider = excluded.provider
        """, (phone, provider))


def get_provider_settings(phone, provider):
    """Return (model, effort); effort is None when unset."""
    with db() as conn:
        row = conn.execute(
            "SELECT model, effort FROM provider_settings WHERE phone = ? AND provider = ?",
            (phone, provider),
        ).fetchone()
    model, effort = row if row else ("", "")
    return model or DEFAULT_MODELS[provider], effort or None


def set_provider_settings(phone, provider, model=None, effort=None):
    """Update only the fields given. effort="" clears it."""
    cur_model, cur_effort = get_provider_settings(phone, provider)
    model = model or cur_model
    effort = cur_effort if effort is None else effort
    with db() as conn:
        conn.execute("""
            INSERT INTO provider_settings(phone, provider, model, effort)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(phone, provider) DO UPDATE SET
                model = excluded.model, effort = excluded.effort
        """, (phone, provider, model, effort or ""))


def describe_settings(phone, provider):
    model, effort = get_provider_settings(phone, provider)
    return f"{model} ({effort} effort)" if effort else model


def get_history(phone, provider):
    with db() as conn:
        rows = conn.execute("""
            SELECT role, text FROM turns
            WHERE phone = ? AND provider = ?
            ORDER BY id DESC LIMIT ?
        """, (phone, provider, MAX_HISTORY_MESSAGES)).fetchall()

    rows.reverse()
    # The history window can start mid-conversation; APIs expect it to open
    # with a user message.
    while rows and rows[0][0] != "user":
        rows.pop(0)
    return [{"role": role, "content": text} for role, text in rows]


def save_turns(phone, provider, turns):
    with db() as conn:
        conn.executemany(
            "INSERT INTO turns(phone, provider, role, text) VALUES(?, ?, ?, ?)",
            [(phone, provider, role, text) for role, text in turns],
        )


def clear_history(phone, provider):
    with db() as conn:
        conn.execute(
            "DELETE FROM turns WHERE phone = ? AND provider = ?",
            (phone, provider),
        )


def ask_gpt(history, model, effort=None):
    body = {"model": model, "input": history}
    if effort:
        body["reasoning"] = {"effort": effort}

    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("output_text"):
        return data["output_text"].strip()

    text = []
    for item in data.get("output", []):
        for block in item.get("content", []):
            if block.get("type") == "output_text":
                text.append(block.get("text", ""))

    return "\n".join(text).strip() or FALLBACK_REPLY


def ask_claude(history, model, effort=None):
    body = {"model": model, "max_tokens": 1200, "messages": history}
    if effort:
        body["output_config"] = {"effort": effort}

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body,
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()

    return "\n".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ).strip() or FALLBACK_REPLY


def send_whatsapp(phone, text):
    url = (
        f"https://graph.facebook.com/{WA_API_VERSION}/"
        f"{PHONE_NUMBER_ID}/messages"
    )
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {WA_TOKEN}",
            "Content-Type": "application/json",
        },
        json={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "text",
            "text": {"preview_url": False, "body": text[:4096]},
        },
        timeout=30,
    )
    response.raise_for_status()


HELP_TEXT = (
    "Text normally to use your default AI. Commands:\n"
    "/gpt your message\n"
    "/claude your message\n"
    "/use - show current settings\n"
    "/use claude sonnet medium\n"
    "/use gpt best low\n"
    "/use gpt small\n"
    "/use claude high (effort only)\n"
    "Models: gpt small|mini|best, claude sonnet|opus|haiku|fable, or any model ID. "
    "Effort: low|medium|high|xhigh|max (gpt also none), default = clear.\n"
    "/reset\n"
    "/help"
)


def handle_use(phone, args):
    """/use [provider] [model] [effort] -> reply text."""
    if not args:
        provider = get_default_provider(phone)
        return f"Default: {provider} - {describe_settings(phone, provider)}"

    provider = args[0]
    if provider not in PROVIDERS:
        return "Use /use gpt or /use claude, optionally followed by a model and effort. Send /help for examples."

    model, effort = None, None
    for token in args[1:]:
        if token == "default":
            effort = ""
        elif token in ALL_EFFORTS:
            if token not in EFFORTS[provider]:
                return f"{provider} doesn't support '{token}' effort."
            effort = token
        else:
            model = MODEL_ALIASES[provider].get(token, token)

    set_default_provider(phone, provider)
    set_provider_settings(phone, provider, model, effort)
    return f"Default set to {provider} - {describe_settings(phone, provider)}"


def handle_message(phone, text):
    try:
        command = text.strip().lower()

        if command in ("/help", "help"):
            send_whatsapp(phone, HELP_TEXT)
            return

        if command == "/reset":
            clear_history(phone, get_default_provider(phone))
            send_whatsapp(phone, "Cleared your default model's chat history.")
            return

        if command == "/use" or command.startswith("/use "):
            send_whatsapp(phone, handle_use(phone, command.split()[1:]))
            return

        provider = get_default_provider(phone)
        prompt = text.strip()

        parts = prompt.split(None, 1)
        if parts and parts[0].lower() in ("/gpt", "/claude"):
            provider = parts[0].lower()[1:]
            prompt = parts[1].strip() if len(parts) > 1 else ""

        if not prompt:
            send_whatsapp(phone, "Add a message after the command.")
            return

        # Only save the exchange once the model has answered, so a failed
        # request never leaves a dangling user message in the history.
        history = get_history(phone, provider) + [
            {"role": "user", "content": prompt}
        ]
        model, effort = get_provider_settings(phone, provider)
        ask = ask_gpt if provider == "gpt" else ask_claude
        answer = ask(history, model, effort)
        save_turns(phone, provider, [("user", prompt), ("assistant", answer)])
        send_whatsapp(phone, f"[{model}{' · ' + effort if effort else ''}]\n{answer}")

    except Exception as exc:
        log.exception("Failed to process incoming message")
        detail = ""
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            detail = f" ({exc.response.status_code}: {exc.response.text[:200]})"
        try:
            send_whatsapp(
                phone,
                f"Sorry, that request failed{detail}. Check the connector's server logs and try again.",
            )
        except Exception:
            log.exception("Could not send error reply")


def verify_signature(raw_body):
    if not META_APP_SECRET:
        return False

    supplied = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(
        META_APP_SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(supplied, expected)


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/webhook")
def verify_webhook():
    if (
        VERIFY_TOKEN
        and request.args.get("hub.mode") == "subscribe"
        and hmac.compare_digest(
            request.args.get("hub.verify_token", ""),
            VERIFY_TOKEN,
        )
    ):
        return request.args.get("hub.challenge", ""), 200

    return "Forbidden", 403


@app.post("/webhook")
def receive_webhook():
    raw_body = request.get_data()

    if not verify_signature(raw_body):
        abort(403)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        abort(400)

    if payload.get("object") != "whatsapp_business_account":
        return jsonify({"ok": True})

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for message in change.get("value", {}).get("messages", []):
                if message.get("type") != "text":
                    continue

                phone = message.get("from")
                message_id = message.get("id")
                text = message.get("text", {}).get("body", "").strip()

                if not phone or not message_id or not text:
                    continue

                if ALLOWED_NUMBERS and phone not in ALLOWED_NUMBERS:
                    continue

                # WhatsApp may retry webhook events. Process each message once.
                try:
                    with db() as conn:
                        conn.execute(
                            "INSERT INTO inbound_ids(message_id) VALUES(?)",
                            (message_id,),
                        )
                except sqlite3.IntegrityError:
                    continue

                executor.submit(handle_message, phone, text)

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
