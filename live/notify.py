"""实盘通知。没配电报时不发送，也不影响下单。"""

from __future__ import annotations

import json
import os
import urllib.request


def configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def emit(book: dict, key: str, text: str) -> None:
    sent = book.setdefault("sent", [])
    if key in sent:
        return
    if send(text):
        sent.append(key)
        del sent[:-300]


def send(text: str) -> bool:
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not chat or not token:
        return False
    body = json.dumps({"chat_id": chat, "text": text}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode())
    except Exception:
        print("电报发送失败", flush=True)
        return False
    return bool(payload.get("ok"))
