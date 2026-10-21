"""实盘进程。只读 live/ 里的账本，不读模拟盘状态，也不给模拟盘下单。

启动：python -m live
必须设置 OKX_LIVE=1。进程一开始就为仓位1挂第一笔限价。
"""

from __future__ import annotations

import json
import os
import signal
import time
import traceback
from pathlib import Path

from live.client import LiveClient, OkxError, public_get
from live.notify import emit
from live.strategy import (
    BAR_MS,
    INST_ID,
    MAX_BOOKS,
    SPEC,
    accept_birth,
    cash_shortfall,
    close_position,
    decide,
    fresh_book,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "live"
STOP = False
ORDER_SEQ = 0


def main() -> None:
    def stop(_signum, _frame) -> None:
        global STOP
        STOP = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    load_env()
    if os.environ.get("OKX_LIVE") != "1":
        print("未设置 OKX_LIVE=1，实盘进程不会连接账户，也不会下单。", flush=True)
        return
    books = [load_book(index) for index in range(1, MAX_BOOKS + 1)]
    if books[0] is None:
        print("仓位1没有钥匙。在 .env 里写 LIVE_BOOK_1_KEY、LIVE_BOOK_1_SECRET、LIVE_BOOK_1_PASSPHRASE。", flush=True)
        return
    clients = {book["index"]: connect(book) for book in books if book is not None}
    main_client = connect_main()
    print("实盘进程已启动。仓位1按当前这根 5 分钟 K 线的开盘价挂限价。", flush=True)
    while not STOP:
        try:
            tick(books, clients, main_client)
        except Exception:
            traceback.print_exc()
        for _ in range(5):
            if STOP:
                break
            time.sleep(1)
    publish(books)
    print("实盘进程已停止。", flush=True)


def tick(books: list[dict | None], clients: dict[int, LiveClient], main_client: LiveClient | None) -> None:
    candle = latest_candle()
    last = float(candle["c"]) if candle else None
    spec = instrument_spec()
    for book in books:
        if book is None:
            continue
        try:
            step_book(book, books, clients, main_client, candle, last, spec)
        except Exception:
            traceback.print_exc()
    publish(books)


def step_book(book, books, clients, main_client, candle, last, spec) -> None:
    client = clients.get(book["index"])
    view = build_view(book, client, candle, last, spec)
    if client is not None and not book.get("lever_ready"):
        prepare_account(book, client)
    if view["lever_above"]:
        emit(book, "alert:leverage", f"【告警】仓位{book['index']} 杠杆高于 1 倍，本拍不再开新仓。")
    elif fund_shortfall(book, view, main_client) and client is not None:
        view["available"] = available_usdt(client)
    if book.get("position") and view["contracts"] <= 0:
        exit_price = float(view.get("exit_price") or last or book["position"]["entry"])
        ended = close_position(book, int(view["exit_bar"]), exit_price)
        emit(
            book,
            f"close:{view['exit_bar']}",
            f"【实盘】仓位{book['index']} 平仓，价格 {exit_price}，本金 {ended}",
        )
    opening = book.get("position") is None and view["contracts"] > 0
    actions = decide(book, view)
    if view["lever_above"]:
        actions = [action for action in actions if action["op"] in {"amend_sell", "place_sell", "spawn"}]
    if opening and book.get("position"):
        position = book["position"]
        emit(
            book,
            f"open:{position['entry_ts']}",
            f"【实盘】仓位{book['index']} 开仓 {position['contracts']} 张 @ {position['entry']}",
        )
    for action in actions:
        if action["op"] != "spawn":
            continue
        slot = books[action["level"]] if action["level"] < len(books) else None
        if slot is not None and accept_birth(slot, action["price"], action["bar_ts"]):
            emit(
                book,
                f"spawn:{action['level']}",
                f"【实盘】仓位1 跌到第 {action['level']} 档，仓位{slot['index']} 等待限价 {action['price']}",
            )
            save_book(slot)
    execute(book, client, actions, view)
    if book["role"] == "primary" or book.get("born"):
        save_book(book)


def build_view(book: dict, client: LiveClient | None, candle: dict | None, last: float | None, spec: dict) -> dict:
    orders: dict[str, dict] = {}
    contracts = 0.0
    avg_px = 0.0
    funding = 0.0
    available = 0.0
    exit_price = None
    lever_above = False
    shorts = False
    if client is not None:
        available = available_usdt(client)
        for row in client.positions(INST_ID):
            size = abs(_float(row.get("pos")) or 0)
            if size <= 0:
                continue
            if _float(row.get("pos")) < 0 or str(row.get("posSide") or "") == "short":
                shorts = True
                continue
            contracts = size
            avg_px = _float(row.get("avgPx")) or 0
            lever = _float(row.get("lever")) or 0
            if lever > 1:
                lever_above = True
        for row in client.leverage(INST_ID):
            lever = _float(row.get("lever")) or 0
            if lever > 1:
                lever_above = True
        pending = client.pending_orders(INST_ID)
        for row in pending:
            orders[row.get("clOrdId") or ""] = row
        tracked = [signal.get("cl_id") for signal in book["signals"] if signal.get("cl_id")]
        sell_id = (book.get("position") or {}).get("sell_id")
        if sell_id:
            tracked.append(sell_id)
        for cl_id in tracked:
            if cl_id and cl_id not in orders:
                row = client.order(INST_ID, cl_id)
                if row:
                    orders[cl_id] = row
                    if row.get("side") == "sell" and _float(row.get("accFillSz")):
                        exit_price = _float(row.get("avgPx"))
        if book.get("position"):
            entry_ts = int(book["position"].get("entry_ts") or 0)
            for bill in client.funding_bills(INST_ID):
                if int(bill.get("ts") or 0) >= entry_ts:
                    funding += _float(bill.get("balChg")) or 0
    if shorts:
        emit(book, "alert:short", f"【告警】仓位{book['index']} 出现空单。")
    now_ms = int(time.time() * 1000)
    exit_bar = int(candle["ts"]) if candle else now_ms - (now_ms % BAR_MS)
    return {
        "now_ms": now_ms,
        "candle": candle,
        "last": last,
        "available": available,
        "contracts": contracts,
        "avg_px": avg_px,
        "funding": round(funding, 8),
        "orders": orders,
        "exit_price": exit_price,
        "exit_bar": exit_bar,
        "lever_above": lever_above,
        "ct_val": spec["ct_val"],
        "lot_sz": spec["lot_sz"],
        "min_sz": spec["min_sz"],
        "tick_sz": spec["tick_sz"],
    }


def execute(book: dict, client: LiveClient | None, actions: list[dict], view: dict) -> None:
    if client is None:
        return
    for action in actions:
        op = action["op"]
        if op == "spawn":
            continue
        if op == "cancel":
            safe_cancel(client, action["cl_id"])
        elif op == "market_remainder":
            safe_cancel(client, action["cancel_id"])
            cl_id = client_id(book["index"], "m")
            place(client, book, order_body(book, view, "buy", action["contracts"], None, cl_id, False, market=True))
            _bind_signal(book, action["signal_id"], cl_id)
            emit(book, f"market:{cl_id}", f"【实盘】仓位{book['index']} 限价未完，市价买入剩余 {action['contracts']} 张")
        elif op == "amend_sell":
            try:
                client.amend(
                    INST_ID,
                    action["cl_id"],
                    format_step(action["price"], view["tick_sz"]),
                    format_step(action["contracts"], view["lot_sz"]),
                )
            except OkxError:
                safe_cancel(client, action["cl_id"])
                book["position"]["sell_id"] = None
        elif op == "place_sell":
            cl_id = client_id(book["index"], "s")
            place(client, book, order_body(book, view, "sell", action["contracts"], action["price"], cl_id, True, market=False))
            book["position"]["sell_id"] = cl_id
            emit(
                book,
                f"sell:{cl_id}",
                f"【实盘】仓位{book['index']} 挂卖单 {action['contracts']} 张 @ {action['price']}",
            )
        elif op == "place_limit":
            cl_id = client_id(book["index"], "b")
            place(client, book, order_body(book, view, "buy", action["contracts"], action["price"], cl_id, False, market=False))
            _bind_signal(book, action["signal_id"], cl_id)
            emit(
                book,
                f"buy:{cl_id}",
                f"【实盘】仓位{book['index']} 挂限价买 {action['contracts']} 张 @ {action['price']}",
            )


def prepare_account(book: dict, client: LiveClient) -> None:
    config = client.config()
    book["pos_mode"] = config.get("posMode") or "net_mode"
    side = "long" if book["pos_mode"] == "long_short_mode" else None
    client.set_leverage(INST_ID, "1", side)
    book["lever_ready"] = True


def fund_shortfall(book: dict, view: dict, main_client: LiveClient | None) -> bool:
    if main_client is None:
        return False
    creds = credentials(book["index"])
    sub = (creds or {}).get("sub") or ""
    if not sub:
        return False
    need = cash_shortfall(book, view)
    if need <= 0:
        return False
    main_cash = available_usdt(main_client)
    amount = min(need, main_cash)
    if amount <= 0:
        return False
    main_client.transfer_to_sub(sub, f"{amount:.4f}")
    emit(book, f"transfer:{int(time.time())}", f"【实盘】主账户划入仓位{book['index']} {amount:.4f} USDT")
    return True


def latest_candle() -> dict | None:
    rows = public_get("/api/v5/market/candles", {"instId": INST_ID, "bar": "5m", "limit": "2"}).get("data") or []
    if not rows:
        return None
    row = rows[0]
    return {"ts": int(row[0]), "o": float(row[1]), "h": float(row[2]), "l": float(row[3]), "c": float(row[4])}


def instrument_spec() -> dict:
    rows = public_get("/api/v5/public/instruments", {"instType": "SWAP", "instId": INST_ID}).get("data") or []
    if not rows:
        return dict(SPEC)
    row = rows[0]
    return {
        "ct_val": float(row["ctVal"]),
        "lot_sz": float(row["lotSz"]),
        "min_sz": float(row["minSz"]),
        "tick_sz": float(row["tickSz"]),
    }


def order_body(book: dict, view: dict, side: str, contracts: float, price: float | None, cl_id: str, reduce_only: bool, market: bool) -> dict:
    body = {
        "instId": INST_ID,
        "tdMode": "cross",
        "side": side,
        "ordType": "market" if market else "limit",
        "sz": format_step(contracts, view["lot_sz"]),
        "clOrdId": cl_id,
    }
    if price is not None and not market:
        body["px"] = format_step(price, view["tick_sz"])
    if reduce_only:
        body["reduceOnly"] = True
    if book.get("pos_mode") == "long_short_mode":
        body["posSide"] = "long"
    return body


def place(client: LiveClient, book: dict, body: dict) -> None:
    client.place(body)
    contracts = _float(body.get("sz")) or 0
    if body.get("side") == "buy" and body.get("ordType") == "limit":
        return
    if contracts > 0 and book.get("position") is None and body.get("side") == "buy":
        emit(book, f"open:{body['clOrdId']}", f"【实盘】仓位{book['index']} 开仓委托已提交")


def safe_cancel(client: LiveClient, cl_id: str | None) -> None:
    if not cl_id:
        return
    try:
        client.cancel(INST_ID, cl_id)
    except OkxError:
        return


def available_usdt(client: LiveClient) -> float:
    details = client.balance().get("details") or [{}]
    usdt = next((item for item in details if item.get("ccy") == "USDT"), details[0])
    return _float(usdt.get("availBal")) or 0.0


def load_book(index: int) -> dict | None:
    path = DATA / f"book-{index}.json"
    if path.is_file():
        saved = json.loads(path.read_text())
        if saved.get("trading") != "live":
            print(f"book-{index}.json 不是实盘账本，这一仓跳过，文件保持原样。", flush=True)
            return None
        base = fresh_book(index)
        base.update(saved)
        base["trading"] = "live"
        base["index"] = index
        return base
    if credentials(index) is None and index != 1:
        return fresh_book(index)
    if credentials(index) is None:
        return None
    return fresh_book(index)


def save_book(book: dict) -> None:
    if book.get("trading") != "live":
        return
    write_json(DATA / f"book-{book['index']}.json", book)


def publish(books: list[dict | None]) -> None:
    rows = []
    for book in books:
        if book is None:
            continue
        position = book.get("position")
        rows.append({
            "index": book["index"],
            "role": book["role"],
            "phase": book["phase"],
            "book_equity": book["book_equity"],
            "entry": None if not position else position.get("entry"),
            "target": None if not position else position.get("target"),
            "contracts": None if not position else position.get("contracts"),
            "signals": len(book.get("signals") or []),
        })
    write_json(DATA / "status.json", {"heartbeat": int(time.time() * 1000), "trading": "live", "books": rows})


def connect(book: dict) -> LiveClient | None:
    creds = credentials(book["index"])
    if creds is None:
        return None
    return LiveClient(creds["key"], creds["secret"], creds["phrase"])


def connect_main() -> LiveClient | None:
    key = os.environ.get("LIVE_MAIN_KEY", "")
    secret = os.environ.get("LIVE_MAIN_SECRET", "")
    phrase = os.environ.get("LIVE_MAIN_PASSPHRASE", "")
    if not (key and secret and phrase):
        return None
    return LiveClient(key, secret, phrase)


def credentials(index: int) -> dict | None:
    key = os.environ.get(f"LIVE_BOOK_{index}_KEY", "")
    secret = os.environ.get(f"LIVE_BOOK_{index}_SECRET", "")
    phrase = os.environ.get(f"LIVE_BOOK_{index}_PASSPHRASE", "")
    if not (key and secret and phrase):
        return None
    return {
        "key": key,
        "secret": secret,
        "phrase": phrase,
        "sub": os.environ.get(f"LIVE_BOOK_{index}_SUB", ""),
    }


def load_env() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


def client_id(index: int, suffix: str) -> str:
    global ORDER_SEQ
    ORDER_SEQ += 1
    return f"l{index:02d}{int(time.time() * 1000) % 10**10}{ORDER_SEQ % 100:02d}{suffix}"


def _bind_signal(book: dict, signal_id: str, cl_id: str) -> None:
    for signal in book["signals"]:
        if signal["id"] == signal_id:
            signal["cl_id"] = cl_id
            signal["partial_bar"] = None


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    tmp.replace(path)


def format_step(value: float, step: float) -> str:
    text = f"{step:.12f}".rstrip("0")
    digits = 0 if "." not in text else len(text.split(".")[1])
    return f"{value:.{digits}f}"


def _float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


if __name__ == "__main__":
    main()
