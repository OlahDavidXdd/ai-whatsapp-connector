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
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
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


def ask_gpt(history):
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": OPENAI_MODEL, "input": history},
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


def ask_claude(history):
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1200,
            "messages": history,
        },
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
    "/use gpt\n"
    "/use claude\n"
    "/reset\n"
    "/help"
)


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

        if command in ("/use gpt", "/use claude"):
            provider = command.split()[1]
            set_default_provider(phone, provider)
            send_whatsapp(phone, f"Default model set to {provider}.")
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
        answer = ask_gpt(history) if provider == "gpt" else ask_claude(history)
        save_turns(phone, provider, [("user", prompt), ("assistant", answer)])
        send_whatsapp(phone, f"[{provider.upper()}]\n{answer}")

    except Exception:
        log.exception("Failed to process incoming message")
        try:
            send_whatsapp(
                phone,
                "Sorry, that request failed. Check the connector's server logs and try again.",
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
