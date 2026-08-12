"""Minimal Telegram Bot API client — stdlib only, HTML formatting."""

import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.telegram.org"
MAX_LEN = 4096  # Telegram's hard limit per message


def escape(text: str) -> str:
    """Escape text for Telegram's HTML parse mode."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    """Split on blank lines, then single lines, so no chunk exceeds `limit`.

    Never splits mid-line, which would break an open HTML tag.
    """
    if len(text) <= limit:
        return [text]

    chunks, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(block) <= limit:
            current = block
            continue
        # Single block too long on its own — fall back to line-by-line.
        for line in block.split("\n"):
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) <= limit:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = line[:limit]
    if current:
        chunks.append(current)
    return chunks


def _post(token: str, method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{API}/bot{token}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def send_message(text: str, token: str | None = None, chat_id: str | None = None) -> int:
    """Send `text` (HTML) to the chat, splitting and retrying as needed.

    Returns the number of Telegram messages sent.
    """
    token = token or os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = chat_id or os.environ["TELEGRAM_CHAT_ID"]

    sent = 0
    for i, chunk in enumerate(split_message(text)):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        for attempt in range(4):
            try:
                _post(token, "sendMessage", payload)
                sent += 1
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:400]
                # 429 carries retry_after; anything else is likely permanent.
                if e.code == 429 and attempt < 3:
                    retry_after = 5
                    try:
                        retry_after = json.loads(body)["parameters"]["retry_after"]
                    except Exception:
                        pass
                    print(f"Rate limited, retrying in {retry_after}s", file=sys.stderr)
                    time.sleep(retry_after)
                    continue
                raise RuntimeError(f"Telegram {method_err(e.code)}: {body}") from e
            except Exception as e:
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"Telegram send failed: {e}") from e
        if i:
            time.sleep(1)  # stay under Telegram's per-chat message rate
    return sent


def method_err(code: int) -> str:
    return {
        400: "400 (bad request — check chat_id and HTML markup)",
        401: "401 (invalid bot token)",
        403: "403 (bot blocked, or it has never been messaged by this chat)",
    }.get(code, str(code))
