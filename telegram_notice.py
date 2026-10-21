"""模拟单的 Telegram 通知和告警。没配钥匙时不发送，也不打断下单。"""

from __future__ import annotations

import json
import os
import urllib.request

INST_LABEL = "NEAR-USDT-SWAP"


def configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send(text: str) -> bool:
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat:
        return False
    payload = _call("sendMessage", {"chat_id": chat, "text": text})
    return bool(payload.get("ok"))


def set_commands() -> bool:
    payload = _call("setMyCommands", {"commands": [
        {"command": "status", "description": "查看当前仓位"},
        {"command": "help", "description": "查看命令"},
    ]})
    return bool(payload.get("ok"))


def updates(offset: int | None) -> tuple[list[dict], int | None]:
    body: dict = {"timeout": 0, "allowed_updates": ["message"]}
    if offset:
        body["offset"] = offset
    payload = _call("getUpdates", body)
    if not payload.get("ok"):
        return [], offset
    rows = payload.get("result") or []
    next_offset = offset
    for row in rows:
        next_offset = int(row.get("update_id") or 0) + 1
    return rows, next_offset


def command_of(text: str) -> str:
    token = (text or "").strip().split(" ", 1)[0]
    return token.split("@", 1)[0].lower()


def status_text(phase_text: str, book, last_price, position: dict | None, order: dict | None) -> str:
    lines = [
        f"【状态】{phase_text}",
        f"本金 {_money(book)}",
        f"最新价 {last_price if last_price is not None else '—'}",
    ]
    if position:
        lines.append(
            f"持仓 {position.get('contracts')} 张，开仓价 {position.get('entry')}，卖价 {position.get('target')}"
        )
        if position.get("upl") is not None:
            lines.append(f"未实现 {_money(position.get('upl'))}")
    else:
        lines.append("当前没有持仓。")
    if order:
        side = "买入" if order.get("side") == "buy" else "卖出"
        price = order.get("px") or "市价"
        lines.append(f"委托 {side} {order.get('sz')} 张 @ {price}")
    return "\n".join(lines)


def _call(method: str, payload: dict) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {}
    body = json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "tradex-demo/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode())
        return data if isinstance(data, dict) else {}
    except Exception:
        print("电报发送失败", flush=True)
        return {}


class Ledger:
    """同一件事只发一次。告警条件消失后清掉，再次出现会再发。"""

    def __init__(self, keys: list[str]) -> None:
        self.keys = keys

    def once(self, key: str, text: str, sender=send) -> bool:
        if key in self.keys:
            return False
        if not sender(text):
            return False
        self.keys.append(key)
        del self.keys[:-300]
        return True

    def latch(self, key: str, active: bool, text: str, sender=send) -> None:
        if active:
            self.once(key, text, sender)
        elif key in self.keys:
            self.keys.remove(key)


def is_short(row: dict) -> bool:
    pos = _num(row.get("pos"))
    if abs(pos) <= 0:
        return False
    side = row.get("posSide") or ""
    if side == "short":
        return True
    return side in ("", "net") and pos < 0


def lever_above_one(row: dict) -> float | None:
    lever = _num(row.get("lever"))
    if lever > 1 + 1e-9:
        return lever
    return None


def partial_fill(row: dict) -> tuple[float, float] | None:
    size = _num(row.get("sz"))
    filled = _num(row.get("accFillSz"))
    if size <= 0 or filled <= 0 or filled + 1e-8 >= size:
        return None
    if row.get("state") not in (None, "live", "partially_filled"):
        return None
    return filled, size


def is_full_fill(row: dict) -> bool:
    size = _num(row.get("sz"))
    filled = _num(row.get("accFillSz"))
    return size > 0 and filled + 1e-8 >= size and row.get("state") == "filled"


def placed_text(order: dict) -> str:
    side = "买入" if order.get("side") == "buy" else "卖出"
    price = order.get("px") or "市价"
    return f"【通知】挂单 {side} {order.get('sz')} 张 @ {price} {INST_LABEL}"


def filled_text(row: dict) -> str:
    side = "买入" if row.get("side") == "buy" else "卖出"
    return f"【通知】全部成交 {side} {row.get('accFillSz')} 张，均价 {row.get('avgPx')} {INST_LABEL}"


def open_text(contracts, entry, equity) -> str:
    return f"【通知】开仓 {contracts} 张，开仓价 {entry}，本金 {_money(equity)} {INST_LABEL}"


def close_text(contracts, entry, exit_price, equity) -> str:
    return (
        f"【通知】平仓 {contracts} 张，开仓价 {entry}，平仓价 {exit_price}，"
        f"平仓后本金 {_money(equity)} {INST_LABEL}"
    )


def leverage_text(lever: float) -> str:
    return f"【告警】杠杆 {lever:g} 倍，高于 1 倍 {INST_LABEL}"


def short_text(contracts: float) -> str:
    return f"【告警】出现空单 {contracts:g} 张 {INST_LABEL}"


def partial_text(row: dict, filled: float, size: float) -> str:
    side = "买入" if row.get("side") == "buy" else "卖出"
    return f"【告警】部分成交 {side} 已成 {filled:g} 张，委托 {size:g} 张 {INST_LABEL}"


def _money(value) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
