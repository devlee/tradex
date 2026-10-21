"""实盘决策。这里只改账本状态、返回要执行的动作，不访问网络。

规则以 live/LOGIC.md 为准。卖价、张数和秘书窗口的根数复用回测里的同一套函数。
"""

from __future__ import annotations

from backtest import (
    SECRETARY4_BARS,
    plan_secretary4,
    secretary_reject_count,
    size_contracts,
    target_price,
)

BAR_MS = 300_000

FEE_RATE = 0.0002
NET_TARGET = 0.02
BASE_EQUITY = 10_000.0
MAX_BOOKS = 10
ADDON_LEVELS = 9
ADDON_STEP = 0.10
INST_ID = "NEAR-USDT-SWAP"

SPEC = {"ct_val": 10.0, "lot_sz": 0.1, "min_sz": 0.1, "tick_sz": 0.001}


def fresh_book(index: int) -> dict:
    primary = index == 1
    return {
        "trading": "live",
        "index": index,
        "role": "primary" if primary else "addon",
        "level": 0 if primary else index - 1,
        "phase": "flat",
        "book_equity": BASE_EQUITY,
        "awaiting_first": primary,
        "born": primary,
        "signals": [],
        "position": None,
        "secretary_start": None,
        "sample_min": None,
        "seen_bar": None,
        "window_bars": SECRETARY4_BARS,
        "reject_bars": secretary_reject_count(BAR_MS, SECRETARY4_BARS),
        "block_entry_until": None,
        "spawned": {},
        "pos_mode": "net_mode",
        "lever_ready": False,
        "cycles": [],
        "sent": [],
    }


def book_after(position: dict, exit_price: float, fee_rate: float = FEE_RATE) -> float:
    """这笔账平仓后的本金。只计算这一笔的现金，不把账户里的其他钱算进来。"""
    qty = float(position["coin_qty"])
    entry = float(position["entry"])
    cash = (
        float(position["equity_before"])
        - qty * entry * fee_rate
        + float(position.get("funding_pnl") or 0)
        + qty * (exit_price - entry)
        - qty * exit_price * fee_rate
    )
    return round(max(cash, 0.0), 8)


def close_position(book: dict, exit_bar_ts: int, exit_price: float) -> float:
    """仓位平掉。立刻按这一笔的开仓价挂限价。秘书窗口从下一根才开始选点。"""
    position = book["position"]
    ended = book_after(position, exit_price)
    book["cycles"].insert(0, {
        "entry": position["entry"],
        "exit": exit_price,
        "equity_before": position["equity_before"],
        "equity_after": ended,
        "exit_bar_ts": exit_bar_ts,
    })
    book["cycles"] = book["cycles"][:40]
    book["book_equity"] = ended
    book["position"] = None
    book["phase"] = "flat"
    book["signals"] = [_signal("limit", float(position["entry"]), exit_bar_ts, ended)]
    start, bars, reject = plan_secretary4(exit_bar_ts, BAR_MS)
    book["secretary_start"] = start
    book["window_bars"] = bars
    book["reject_bars"] = reject
    book["sample_min"] = None
    book["seen_bar"] = None
    book["block_entry_until"] = None
    book["awaiting_first"] = False
    return ended


def accept_birth(book: dict, price: float, bar_ts: int) -> bool:
    """下跌档第一次触发。已经诞生过的子账户不再塞一笔新的 10,000。"""
    if book.get("born"):
        return False
    book["born"] = True
    book["book_equity"] = BASE_EQUITY
    book["signals"].append(_signal("addon", price, bar_ts, BASE_EQUITY))
    return True


def cash_shortfall(book: dict, view: dict) -> float:
    """开仓前还要从主账户划入的 USDT。够用时返回 0。"""
    available = float(view.get("available") or 0)
    if _needs_entry_cash(book):
        return round(max(0.0, float(book["book_equity"]) - available), 8)
    remainder = _remainder_need(book, view)
    if remainder <= 0:
        return 0.0
    return round(max(0.0, remainder - available), 8)


def decide(book: dict, view: dict) -> list[dict]:
    """返回本拍要执行的动作，并推进窗口、信号和持仓目标。"""
    if book.get("trading") != "live":
        return []
    contracts = float(view.get("contracts") or 0)
    if contracts > 0:
        return _while_long(book, view)
    if book.get("role") == "addon" and not book.get("born"):
        return []
    actions: list[dict] = []
    _ensure_startup(book, view)
    _advance_window(book, view.get("candle"))
    _queue_orders(book, view, actions)
    return actions


def _while_long(book: dict, view: dict) -> list[dict]:
    _ensure_position(book, view)
    position = book["position"]
    funding = float(view.get("funding") or 0)
    position["funding_pnl"] = funding
    position["contracts"] = float(view["contracts"])
    if view.get("avg_px"):
        position["entry"] = float(view["avg_px"])
    position["coin_qty"] = round(position["contracts"] * _ct(view), 8)
    position["target"] = target_price(
        position["entry"],
        position["coin_qty"],
        position["equity_before"],
        FEE_RATE,
        funding,
        NET_TARGET,
        _tick(view),
    )
    book["phase"] = "long"
    book["awaiting_first"] = False
    actions = _cancel_other_buys(book, view)
    actions.extend(_complete_partial(book, view))
    actions.extend(_sell_actions(book, view))
    actions.extend(_spawn_levels(book, view))
    return actions


def _ensure_startup(book: dict, view: dict) -> None:
    candle = view.get("candle")
    if book.get("role") != "primary" or not book.get("awaiting_first") or not candle:
        return
    book["signals"].append(_signal("startup", float(candle["o"]), int(candle["ts"]), BASE_EQUITY))
    book["awaiting_first"] = False


def _advance_window(book: dict, candle: dict | None) -> None:
    start = book.get("secretary_start")
    if start is None or candle is None:
        return
    bars = int(book["window_bars"])
    ts = int(candle["ts"])
    last = start + (bars - 1) * BAR_MS
    while ts > last:
        start = last + BAR_MS
        book["secretary_start"] = start
        book["sample_min"] = None
        book["seen_bar"] = None
        last = start + (bars - 1) * BAR_MS
    if ts < start or book.get("seen_bar") == ts:
        return
    slot = (ts - start) // BAR_MS
    reject = int(book["reject_bars"])
    opened = float(candle["o"])
    if slot < reject:
        sample = book.get("sample_min")
        book["sample_min"] = opened if sample is None else min(sample, opened)
    elif slot < bars - 1:
        sample = book.get("sample_min")
        if sample is not None and opened < sample:
            _add_signal(book, "secretary", opened, ts)
    else:
        _add_signal(book, "secretary_last", opened, ts)
    book["seen_bar"] = ts


def _queue_orders(book: dict, view: dict, actions: list[dict]) -> None:
    actions.extend(_complete_partial(book, view))
    incoming = [
        signal for signal in book["signals"]
        if not signal.get("cl_id") and signal["kind"] in {"secretary", "secretary_last"}
    ]
    if incoming:
        _place_secretary(book, view, actions, incoming[-1])
        return
    _place_resting(book, view, actions)


def _place_secretary(book: dict, view: dict, actions: list[dict], chosen: dict) -> None:
    """秘书要挂新单时，先让出已经占住保证金的买单。"""
    orders = view.get("orders") or {}
    equity = float(book["book_equity"])
    pool = float(view.get("available") or 0)
    if pool + 1e-9 < equity:
        kept = []
        for signal in book["signals"]:
            if signal["id"] == chosen["id"]:
                kept.append(signal)
                continue
            row = orders.get(signal.get("cl_id") or "")
            filled = _qty(row.get("accFillSz")) if row else 0
            if signal.get("cl_id") and filled <= 0 and signal["kind"] in {"limit", "secretary", "secretary_last", "startup", "addon"}:
                actions.append({"op": "cancel", "cl_id": signal["cl_id"], "signal_id": signal["id"]})
                pool += equity
                continue
            kept.append(signal)
        book["signals"] = kept
    if pool + 1e-9 < equity:
        return
    if not _append_limit(actions, view, chosen, equity):
        return
    book["signals"] = [
        signal for signal in book["signals"]
        if signal["id"] == chosen["id"] or signal.get("cl_id") or signal["kind"] not in {"limit", "secretary", "secretary_last"}
    ]


def _place_resting(book: dict, view: dict, actions: list[dict]) -> None:
    pool = float(view.get("available") or 0)
    equity = float(book["book_equity"])
    for signal in book["signals"]:
        if signal.get("cl_id") or signal["kind"] not in {"limit", "startup", "addon"}:
            continue
        if pool + 1e-9 < equity:
            return
        if not _append_limit(actions, view, signal, equity):
            return
        pool -= equity


def _append_limit(actions: list[dict], view: dict, signal: dict, equity: float) -> bool:
    contracts = size_contracts(equity, float(signal["price"]), FEE_RATE, _ct(view), _lot(view), _min(view))
    if contracts <= 0:
        return False
    signal["equity"] = equity
    actions.append({
        "op": "place_limit",
        "signal_id": signal["id"],
        "kind": signal["kind"],
        "price": float(signal["price"]),
        "contracts": contracts,
        "equity": equity,
    })
    return True


def _complete_partial(book: dict, view: dict) -> list[dict]:
    orders = view.get("orders") or {}
    candle = view.get("candle")
    now_ms = int(view["now_ms"])
    bar_ts = int(candle["ts"]) if candle else now_ms - (now_ms % BAR_MS)
    actions = []
    for signal in book["signals"]:
        row = orders.get(signal.get("cl_id") or "")
        if not row or row.get("side") != "buy":
            continue
        filled = _qty(row.get("accFillSz"))
        size = _qty(row.get("sz"))
        if filled <= 0 or filled + 1e-12 >= size:
            continue
        if signal.get("partial_bar") is None:
            signal["partial_bar"] = bar_ts
        if now_ms < int(signal["partial_bar"]) + 2 * BAR_MS:
            continue
        remainder = round(size - filled, 8)
        if remainder + 1e-12 < _min(view):
            continue
        price = float(view.get("last") or (candle or {}).get("c") or signal["price"])
        need = remainder * _ct(view) * price * (1 + FEE_RATE)
        if float(view.get("available") or 0) + 1e-9 < need:
            continue
        actions.append({
            "op": "market_remainder",
            "signal_id": signal["id"],
            "cancel_id": signal["cl_id"],
            "contracts": remainder,
        })
    return actions


def _cancel_other_buys(book: dict, view: dict) -> list[dict]:
    orders = view.get("orders") or {}
    keeper = None
    for signal in book["signals"]:
        row = orders.get(signal.get("cl_id") or "")
        if not row:
            continue
        filled = _qty(row.get("accFillSz"))
        size = _qty(row.get("sz"))
        if 0 < filled + 1e-12 < size:
            keeper = signal["id"]
            break
    actions = []
    kept = []
    for signal in list(book["signals"]):
        if keeper and signal["id"] == keeper:
            kept.append(signal)
            continue
        cl_id = signal.get("cl_id")
        if cl_id and cl_id not in orders:
            kept.append(signal)
            continue
        row = orders.get(cl_id) if cl_id else None
        filled = _qty(row.get("accFillSz")) if row else 0
        size = _qty(row.get("sz")) if row else 0
        if row and size > 0 and filled + 1e-12 >= size:
            continue
        if cl_id:
            actions.append({"op": "cancel", "cl_id": cl_id, "signal_id": signal["id"]})
    book["signals"] = kept
    return actions


def _sell_actions(book: dict, view: dict) -> list[dict]:
    position = book["position"]
    orders = view.get("orders") or {}
    price = float(position["target"])
    contracts = float(position["contracts"])
    sell_id = position.get("sell_id")
    row = orders.get(sell_id) if sell_id else None
    if row and row.get("side") == "sell" and _near(row.get("px"), price, _tick(view)) and _near(row.get("sz"), contracts, _lot(view)):
        return []
    if row and row.get("side") == "sell":
        return [{"op": "amend_sell", "cl_id": sell_id, "price": price, "contracts": contracts}]
    return [{"op": "place_sell", "price": price, "contracts": contracts}]


def _spawn_levels(book: dict, view: dict) -> list[dict]:
    if book.get("role") != "primary":
        return []
    candle = view.get("candle")
    entry = float((book.get("position") or {}).get("entry") or 0)
    if candle is None or entry <= 0:
        return []
    spawned = book.setdefault("spawned", {})
    actions = []
    for level in range(1, ADDON_LEVELS + 1):
        key = str(level)
        if key in spawned:
            continue
        threshold = entry * (1 - ADDON_STEP * level)
        if threshold <= 0:
            spawned[key] = 0
            continue
        if float(candle["l"]) > threshold:
            continue
        opened = float(candle["o"])
        fill = opened if opened <= threshold else threshold
        spawned[key] = fill
        actions.append({
            "op": "spawn",
            "level": level,
            "price": fill,
            "bar_ts": int(candle["ts"]),
        })
    return actions


def _ensure_position(book: dict, view: dict) -> None:
    if book.get("position"):
        return
    equity = float(book["book_equity"])
    entry_ts = int(view.get("now_ms") or 0)
    for signal in book["signals"]:
        if signal.get("equity"):
            equity = float(signal["equity"])
        if signal.get("bar_ts"):
            entry_ts = int(signal["bar_ts"])
            break
    contracts = float(view["contracts"])
    entry = float(view.get("avg_px") or 0)
    book["position"] = {
        "entry_ts": entry_ts,
        "entry": entry,
        "contracts": contracts,
        "coin_qty": round(contracts * _ct(view), 8),
        "equity_before": equity,
        "funding_pnl": float(view.get("funding") or 0),
        "target": 0.0,
        "sell_id": None,
    }


def _needs_entry_cash(book: dict) -> bool:
    if book.get("position"):
        return False
    if book.get("role") == "addon" and not book.get("born"):
        return False
    if book.get("awaiting_first"):
        return True
    return any(not signal.get("cl_id") for signal in book["signals"])


def _remainder_need(book: dict, view: dict) -> float:
    orders = view.get("orders") or {}
    now_ms = int(view.get("now_ms") or 0)
    candle = view.get("candle") or {}
    price = float(view.get("last") or candle.get("c") or 0)
    for signal in book["signals"]:
        row = orders.get(signal.get("cl_id") or "")
        if not row:
            continue
        filled = _qty(row.get("accFillSz"))
        size = _qty(row.get("sz"))
        partial_bar = signal.get("partial_bar")
        if partial_bar is None or now_ms < int(partial_bar) + 2 * BAR_MS:
            continue
        remainder = size - filled
        if remainder > 0 and price > 0:
            return remainder * _ct(view) * price * (1 + FEE_RATE)
    return 0.0


def _add_signal(book: dict, kind: str, price: float, bar_ts: int) -> None:
    signal = _signal(kind, price, bar_ts, float(book["book_equity"]))
    if any(item["id"] == signal["id"] for item in book["signals"]):
        return
    book["signals"].append(signal)


def _signal(kind: str, price: float, bar_ts: int, equity: float) -> dict:
    return {
        "id": f"{kind}:{bar_ts}:{price}",
        "kind": kind,
        "price": price,
        "bar_ts": bar_ts,
        "equity": equity,
        "cl_id": None,
        "partial_bar": None,
    }


def _ct(view: dict) -> float:
    return float(view.get("ct_val") or SPEC["ct_val"])


def _lot(view: dict) -> float:
    return float(view.get("lot_sz") or SPEC["lot_sz"])


def _min(view: dict) -> float:
    return float(view.get("min_sz") or SPEC["min_sz"])


def _tick(view: dict) -> float:
    return float(view.get("tick_sz") or SPEC["tick_sz"])


def _qty(value) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _near(left, right, step: float) -> bool:
    if left is None or left == "":
        return False
    return abs(float(left) - float(right)) <= step / 2 + 1e-12
