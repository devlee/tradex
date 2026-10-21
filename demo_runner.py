"""秘书问题4的 OKX 实盘程序。一直轮询，直到进程被关掉。

只做 NEAR-USDT-SWAP 多单，1 倍全仓。请求不带模拟盘标记。
必须设置 OKX_LIVE=1 才会连接账户。必须再设置 OKX_ARM=1 才会开第一笔。
模拟盘的 data/demo-state.json 不会被读取。
第一笔只用 10,000 USDT。平仓后这笔账上的余额才是下一笔本金。
"""

from __future__ import annotations

import json
import os
import signal
import time
import traceback
from datetime import datetime
from pathlib import Path

from backtest import (
    DAY_MS,
    SECRETARY4_BARS,
    beijing_day_start,
    plan_secretary4,
    size_contracts,
    target_price,
)
from okx_data import SHANGHAI
from okx_demo import LiveClient, OkxError, public_get
import telegram_notice as tg

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
STATE_PATH = DATA / "live-state.json"
STATUS_PATH = DATA / "live-status.json"
INST_ID = "NEAR-USDT-SWAP"
FEE_RATE = 0.0002
NET_TARGET = 0.02
BOOK_EQUITY = 10_000.0
ENTRY_HOUR = 0
BAR = "5m"
BAR_MS = 5 * 60 * 1000
STOP = False


def load_env(path: Path | None = None) -> None:
    file = path or (ROOT / ".env")
    if not file.is_file():
        return
    for line in file.read_text().splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def next_entry_bar(now_ms: int, hour: int = ENTRY_HOUR, bar_ms: int = BAR_MS) -> int:
    """下一根还没走完的进场钟点 K 线。正在走的这根也算。"""
    day = beijing_day_start(now_ms)
    ts = day + hour * 3_600_000
    if now_ms >= ts + bar_ms:
        ts += DAY_MS
    return ts


def step_text(step: float) -> int:
    raw = f"{step:.10f}".rstrip("0")
    return len(raw.split(".")[1]) if "." in raw else 0


def format_step(value: float, step: float) -> str:
    return f"{value:.{step_text(step)}f}"


def beijing_text(ms: int | None) -> str:
    if ms is None:
        return "—"
    return datetime.fromtimestamp(ms / 1000, SHANGHAI).strftime("%m-%d %H:%M")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False))
    tmp.replace(path)


def fresh_state(now_ms: int) -> dict:
    return {
        "phase": "standby",
        "trading": "live",
        "scheduled": next_entry_bar(now_ms),
        "limit_price": None,
        "secretary_start": None,
        "sample_min": None,
        "window_bars": SECRETARY4_BARS,
        "reject_bars": plan_secretary4(now_ms, BAR_MS)[2],
        "seen_bar": None,
        "order": None,
        "position": None,
        "cycles": [],
        "book_equity": BOOK_EQUITY,
        "pos_mode": "net_mode",
        "lever_ready": False,
        "last_error": "",
        "notices": [],
    }


class Runner:
    def __init__(self) -> None:
        self.client: LiveClient | None = None
        self.spec = {"ct_val": 10.0, "lot_sz": 0.1, "min_sz": 0.1, "tick_sz": 0.001}
        self._block_save = False
        self.state = self._load_state()
        self.equity = None
        self.available = None
        self.last_price = None
        self.orders: list[dict] = []
        self.candles: list[dict] = []

    def _load_state(self) -> dict:
        now_ms = int(time.time() * 1000)
        if not STATE_PATH.is_file():
            return fresh_state(now_ms)
        try:
            saved = json.loads(STATE_PATH.read_text())
        except json.JSONDecodeError:
            return fresh_state(now_ms)
        if saved.get("trading") != "live":
            self._block_save = True
            locked = fresh_state(now_ms)
            locked["phase"] = "live_locked"
            locked["last_error"] = "live-state.json 不是实盘账本，已停止下单，文件保持原样。"
            return locked
        base = fresh_state(now_ms)
        base.update(saved)
        base["trading"] = "live"
        return base

    def save(self) -> None:
        if self._block_save:
            self.publish()
            return
        write_json(STATE_PATH, self.state)
        self.publish()

    def publish(self) -> None:
        position = self.state.get("position")
        slot = self._slot()
        write_json(STATUS_PATH, {
            "heartbeat": int(time.time() * 1000),
            "simulated": False,
            "trading": "live",
            "inst_id": INST_ID,
            "strategy": "秘书问题4",
            "bar": BAR,
            "window_bars": SECRETARY4_BARS,
            "reject_bars": self.state.get("reject_bars"),
            "net_target": NET_TARGET,
            "fee_rate": FEE_RATE,
            "phase": self.state.get("phase"),
            "phase_text": self.phase_text(slot),
            "scheduled": self.state.get("scheduled"),
            "limit_price": self.state.get("limit_price"),
            "secretary_start": self.state.get("secretary_start"),
            "secretary_slot": slot,
            "sample_min": self.state.get("sample_min"),
            "equity": self.equity,
            "available": self.available,
            "book_equity": self._book_equity(),
            "last_price": self.last_price,
            "position": position,
            "order": self._public_order(),
            "cycles": (self.state.get("cycles") or [])[:20],
            "last_error": self.state.get("last_error") or "",
            "telegram": tg.configured(),
            "note": "实盘。未设置 OKX_ARM=1 时不会开第一笔。第一笔本金 10,000 USDT。",
        })

    def phase_text(self, slot: int | None) -> str:
        phase = self.state.get("phase")
        if phase == "live_locked":
            return "未设置 OKX_LIVE=1。实盘进程不会连接账户，也不会下单。"
        if phase == "missing_keys":
            return "还没有实盘钥匙。把 OKX_API_KEY、OKX_SECRET_KEY、OKX_PASSPHRASE 写进 .env，并设置 OKX_LIVE=1。"
        if phase == "standby":
            return "实盘已连接，还没有开第一笔。设置 OKX_ARM=1 后才会按市价开仓。"
        if phase == "wait_clock":
            return "正在按市价开第一笔，本金 10,000 USDT。"
        if phase == "long" and self.state.get("position"):
            pos = self.state["position"]
            return f"持仓 {pos['contracts']} 张，卖单 {pos['target']}。"
        if phase == "pending_buy":
            order = self.state.get("order") or {}
            return f"买单挂在 {order.get('px') or '市价'}，用途是{self._purpose_text(order.get('purpose'))}。"
        if phase == "armed":
            if slot is None:
                return f"空仓。上一笔开仓价 {self.state.get('limit_price')} 的买单挂着，秘书窗口还没开始。"
            if slot < (self.state.get("reject_bars") or 0):
                return f"空仓。限价单挂着，正在观察第 {slot + 1} 根，样本最低开盘 {self.state.get('sample_min') or '—'}。"
            return f"空仓。观察结束，正在第 {slot + 1} 根里等更低的开盘价，限价单仍然优先。"
        return "正在同步实盘。"

    def _purpose_text(self, purpose: str | None) -> str:
        return {
            "clock": "立即开仓",
            "limit": "上一笔开仓价",
            "secretary": "秘书开盘",
            "secretary_last": "窗口最后一根",
        }.get(purpose or "", "进场")

    def _slot(self) -> int | None:
        start = self.state.get("secretary_start")
        if start is None or self.state.get("phase") not in {"armed", "pending_buy"}:
            return None
        now_ms = int(time.time() * 1000)
        if now_ms < start:
            return None
        return (now_ms - start) // BAR_MS

    def _public_order(self) -> dict | None:
        order = self.state.get("order")
        if not order:
            return None
        return {
            "side": order.get("side"),
            "px": order.get("px"),
            "sz": order.get("sz"),
            "purpose": order.get("purpose"),
            "state": order.get("state") or "live",
        }

    def fail(self, message: str) -> None:
        self.state["last_error"] = message
        self.publish()
        print(message, flush=True)

    def tick(self) -> None:
        load_env()
        if self._block_save:
            self.publish()
            return
        if os.environ.get("OKX_LIVE") != "1":
            self.publish_locked("未设置 OKX_LIVE=1。实盘进程不会连接账户，也不会下单。")
            return
        if not self._ensure_client():
            self.state["phase"] = "missing_keys"
            self.save()
            return
        self._refresh_public()
        self._refresh_private()
        self.state["last_error"] = ""
        if self.state.get("phase") == "missing_keys":
            self.state["phase"] = "standby"
        if self.state.get("phase") == "standby" and os.environ.get("OKX_ARM") == "1":
            self.state["phase"] = "wait_clock"
            self.state["scheduled"] = next_entry_bar(int(time.time() * 1000))
        if self.state.get("phase") not in ("standby", "live_locked"):
            self._ensure_leverage()
        self._sync()
        try:
            self._watch_risk()
        except Exception:
            traceback.print_exc()
        try:
            self._poll_telegram()
        except Exception:
            traceback.print_exc()
        self.save()

    def _ensure_client(self) -> bool:
        load_env()
        key = os.environ.get("OKX_API_KEY", "")
        secret = os.environ.get("OKX_SECRET_KEY", "")
        phrase = os.environ.get("OKX_PASSPHRASE", "")
        if os.environ.get("OKX_LIVE") != "1" or not (key and secret and phrase):
            self.client = None
            return False
        if self.client is None:
            self.client = LiveClient(key, secret, phrase)
            try:
                self._bootstrap()
            except Exception:
                self.client = None
                raise
        return True

    def _bootstrap(self) -> None:
        assert self.client is not None
        rows = public_get(
            "/api/v5/public/instruments", {"instType": "SWAP", "instId": INST_ID}
        ).get("data") or []
        if rows:
            row = rows[0]
            self.spec = {
                "ct_val": float(row["ctVal"]),
                "lot_sz": float(row["lotSz"]),
                "min_sz": float(row["minSz"]),
                "tick_sz": float(row["tickSz"]),
            }
        config = self.client.config()
        self.state["pos_mode"] = config.get("posMode") or "net_mode"

    def _ensure_leverage(self) -> None:
        assert self.client is not None
        if self.state.get("lever_ready"):
            return
        side = "long" if self.state.get("pos_mode") == "long_short_mode" else None
        self.client.set_leverage(INST_ID, "1", side)
        self.state["lever_ready"] = True

    def publish_locked(self, text: str) -> None:
        self.publish()
        status = json.loads(STATUS_PATH.read_text())
        status["phase"] = "live_locked"
        status["phase_text"] = text
        status["running"] = True
        write_json(STATUS_PATH, status)

    def _refresh_public(self) -> None:
        rows = public_get(
            "/api/v5/market/candles", {"instId": INST_ID, "bar": BAR, "limit": "40"}
        ).get("data") or []
        candles = []
        for row in rows:
            candles.append({
                "ts": int(row[0]),
                "o": float(row[1]),
                "h": float(row[2]),
                "l": float(row[3]),
                "c": float(row[4]),
            })
        candles.sort(key=lambda item: item["ts"])
        self.candles = candles
        if candles:
            self.last_price = candles[-1]["c"]

    def _refresh_private(self) -> None:
        assert self.client is not None
        account = (self.client.balance().get("data") or [{}])[0]
        details = account.get("details") or [{}]
        usdt = next((item for item in details if item.get("ccy") == "USDT"), details[0])
        self.equity = _float(usdt.get("eq"))
        self.available = _float(usdt.get("availBal"))
        self.orders = self.client.pending_orders(INST_ID)

    def _book_equity(self) -> float:
        value = self.state.get("book_equity")
        return BOOK_EQUITY if value is None else float(value)

    def _sizing_equity(self) -> float:
        book = self._book_equity()
        if self.available is None:
            return book
        return min(book, self.available)

    def _poll_telegram(self) -> None:
        if not tg.configured():
            return
        if not self.state.get("telegram_menu"):
            self.state["telegram_menu"] = tg.set_commands()
        rows, offset = tg.updates(self.state.get("telegram_offset"))
        if offset:
            self.state["telegram_offset"] = offset
        allowed = str(os.environ.get("TELEGRAM_CHAT_ID", ""))
        for row in rows:
            message = row.get("message") or {}
            chat = str((message.get("chat") or {}).get("id", ""))
            if chat != allowed:
                continue
            command = tg.command_of(message.get("text") or "")
            if command in {"/status", "/pos", "/position", "/仓位", "/状态"}:
                tg.send(self._status_reply())
            elif command in {"/help", "/start"}:
                tg.send("发送 /status 查看当前仓位、挂单和本金。")

    def _status_reply(self) -> str:
        return tg.status_text(
            self.phase_text(self._slot()),
            self._book_equity(),
            self.last_price,
            self.state.get("position"),
            self._public_order(),
        )

    def _ledger(self) -> tg.Ledger:
        notices = self.state.setdefault("notices", [])
        return tg.Ledger(notices)

    def _report_remote(self, cl_id: str) -> None:
        if not cl_id or self.client is None:
            return
        try:
            row = self.client.order(INST_ID, cl_id)
        except OkxError:
            return
        if row:
            self._report_row(row)

    def _report_row(self, row: dict) -> None:
        cl_id = row.get("clOrdId") or row.get("ordId") or ""
        if not cl_id:
            return
        part = tg.partial_fill(row)
        if part:
            self._ledger().latch(
                f"partial:{cl_id}", True, tg.partial_text(row, part[0], part[1])
            )
        else:
            self._ledger().latch(f"partial:{cl_id}", False, "")
        if tg.is_full_fill(row):
            self._ledger().once(f"filled:{cl_id}", tg.filled_text(row))

    def _watch_risk(self) -> None:
        if self.client is None:
            return
        levers: list[float] = []
        shorts: list[float] = []
        for row in self.client.positions(INST_ID):
            lever = tg.lever_above_one(row)
            if lever:
                levers.append(lever)
            if tg.is_short(row):
                shorts.append(abs(_float(row.get("pos")) or 0))
        try:
            for row in self.client.leverage(INST_ID):
                lever = tg.lever_above_one(row)
                if lever:
                    levers.append(lever)
        except OkxError:
            pass
        ledger = self._ledger()
        if levers:
            ledger.latch("alert:leverage", True, tg.leverage_text(max(levers)))
        else:
            ledger.latch("alert:leverage", False, "")
        if shorts:
            ledger.latch("alert:short", True, tg.short_text(sum(shorts)))
        else:
            ledger.latch("alert:short", False, "")
        seen = set()
        for row in self.orders:
            self._report_row(row)
            seen.add(row.get("clOrdId"))
        current = (self.state.get("order") or {}).get("clOrdId")
        if current and current not in seen:
            self._report_remote(current)

    def _position_row(self) -> dict | None:
        assert self.client is not None
        for row in self.client.positions(INST_ID):
            if tg.is_short(row):
                continue
            if abs(_float(row.get("pos")) or 0) > 0:
                return row
        return None

    def _sync(self) -> None:
        if self.state.get("phase") in ("standby", "live_locked"):
            return
        row = self._position_row()
        if row is not None:
            self._on_long(row)
            return
        if self.state.get("phase") == "long":
            self._on_flat_after_long()
            return
        self._while_flat()

    def _on_long(self, row: dict) -> None:
        contracts = abs(_float(row.get("pos")) or 0)
        entry = _float(row.get("avgPx")) or 0
        local = self.state.get("position") or {}
        buy_id = (self.state.get("order") or {}).get("clOrdId")
        if self.state.get("phase") != "long" or not local:
            equity_before = (self.state.get("order") or {}).get("equity_before") or self._book_equity()
            coin_qty = round(contracts * self.spec["ct_val"], 8)
            funding = 0.0
            target = target_price(entry, coin_qty, equity_before, FEE_RATE, funding, NET_TARGET, self.spec["tick_sz"])
            local = {
                "entry_ts": (self.state.get("order") or {}).get("bar_ts") or int(time.time() * 1000),
                "entry": entry,
                "contracts": contracts,
                "coin_qty": coin_qty,
                "equity_before": equity_before,
                "funding_pnl": funding,
                "target": target,
                "sell_id": None,
            }
            self.state["position"] = local
            self.state["phase"] = "long"
            self.state["order"] = None
            self.state["limit_price"] = None
            self._ledger().once(
                f"open:{local['entry_ts']}",
                tg.open_text(contracts, entry, local["equity_before"]),
            )
            if buy_id:
                self._report_remote(buy_id)
        funding = self._funding_since(local["entry_ts"])
        if abs(funding - local.get("funding_pnl", 0)) > 1e-8:
            local["funding_pnl"] = funding
            local["target"] = target_price(
                local["entry"], local["coin_qty"], local["equity_before"],
                FEE_RATE, funding, NET_TARGET, self.spec["tick_sz"],
            )
        local["upl"] = _float(row.get("upl"))
        self.state["position"] = local
        self._ensure_sell(local)

    def _funding_since(self, entry_ts: int) -> float:
        assert self.client is not None
        total = 0.0
        for bill in self.client.funding_bills(INST_ID):
            if int(bill.get("ts") or 0) >= entry_ts:
                total += _float(bill.get("balChg")) or 0
        return round(total, 8)

    def _ensure_sell(self, position: dict) -> None:
        assert self.client is not None
        price = format_step(position["target"], self.spec["tick_sz"])
        size = format_step(position["contracts"], self.spec["lot_sz"])
        live = self._find_order(position.get("sell_id"))
        if live and live.get("px") == price and live.get("side") == "sell":
            self.state["order"] = {
                "clOrdId": position["sell_id"], "side": "sell", "px": price,
                "sz": size, "purpose": "target", "state": live.get("state"),
            }
            return
        if live:
            try:
                self.client.amend(INST_ID, position["sell_id"], price)
            except OkxError:
                self.client.cancel(INST_ID, position["sell_id"])
                position["sell_id"] = None
            else:
                self.state["order"] = {
                    "clOrdId": position["sell_id"], "side": "sell", "px": price,
                    "sz": size, "purpose": "target", "state": "live",
                }
                return
        cl_id = _client_id("s")
        self.client.place(self._order_body("sell", size, price, cl_id, reduce_only=True))
        position["sell_id"] = cl_id
        self.state["order"] = {
            "clOrdId": cl_id, "side": "sell", "px": price, "sz": size,
            "purpose": "target", "state": "live",
        }
        self._ledger().once(f"place:{cl_id}", tg.placed_text(self.state["order"]))

    def _on_flat_after_long(self) -> None:
        position = self.state.get("position") or {}
        exit_price, status = self._exit_fill(position.get("sell_id"))
        ended = _book_after(position, exit_price)
        now_ms = int(time.time() * 1000)
        bar_ts = now_ms - (now_ms % BAR_MS)
        self.state["cycles"].insert(0, {
            "status": status,
            "entry_ts": position.get("entry_ts"),
            "exit_ts": now_ms,
            "entry": position.get("entry"),
            "exit": exit_price,
            "contracts": position.get("contracts"),
            "equity_before": position.get("equity_before"),
            "equity_after": ended,
        })
        self.state["book_equity"] = ended
        self.state["cycles"] = self.state["cycles"][:40]
        self._ledger().once(
            f"close:{now_ms}",
            tg.close_text(position.get("contracts"), position.get("entry"), exit_price, ended),
        )
        if position.get("sell_id"):
            self._report_remote(position["sell_id"])
        start, bars, reject = plan_secretary4(bar_ts, BAR_MS)
        self.state.update({
            "phase": "armed",
            "position": None,
            "order": None,
            "scheduled": None,
            "limit_price": position.get("entry"),
            "secretary_start": start,
            "sample_min": None,
            "window_bars": bars,
            "reject_bars": reject,
            "seen_bar": None,
        })
        self._place_limit_buy(position.get("entry"), "limit", None)

    def _exit_fill(self, sell_id: str | None) -> tuple[float | None, str]:
        assert self.client is not None
        if sell_id:
            row = self.client.order(INST_ID, sell_id)
            if row and float(row.get("accFillSz") or 0) > 0:
                return _float(row.get("avgPx")), "target"
        for row in self.client.fills_history(INST_ID):
            if row.get("side") == "sell" and float(row.get("accFillSz") or 0) > 0:
                return _float(row.get("avgPx")), "target"
        return self.last_price, "liquidated"

    def _while_flat(self) -> None:
        now_ms = int(time.time() * 1000)
        phase = self.state.get("phase")
        if phase in ("standby", "live_locked"):
            return
        if phase == "blocked":
            self.state["phase"] = "armed" if self.state.get("limit_price") else "standby"
            phase = self.state["phase"]
        if phase == "pending_buy":
            self._watch_buy(now_ms)
            return
        if phase == "wait_clock":
            self._watch_clock(now_ms)
            return
        if phase == "armed":
            self._watch_secretary(now_ms)

    def _watch_clock(self, now_ms: int) -> None:
        """第一笔不等下一个 0 点。当前这根 K 线直接市价开仓。"""
        candle = self._forming(now_ms)
        bar_ts = candle["ts"] if candle else now_ms - (now_ms % BAR_MS)
        self.state["scheduled"] = bar_ts
        self._place_market_buy("clock", bar_ts)

    def _watch_buy(self, now_ms: int) -> None:
        order = self.state.get("order") or {}
        if order.get("purpose") == "limit":
            self.state["phase"] = "armed"
            self._watch_secretary(now_ms)
            return
        live = self._find_order(order.get("clOrdId"))
        if live:
            order["state"] = live.get("state")
            self.state["order"] = order
            bar_ts = order.get("bar_ts")
            if order.get("purpose") != "secretary_last" and bar_ts is not None and now_ms >= bar_ts + BAR_MS:
                self._cancel(order.get("clOrdId"))
                self._missed_entry(order)
            return
        remote = None
        if order.get("clOrdId") and self.client is not None:
            remote = self.client.order(INST_ID, order["clOrdId"])
        filled = remote and float(remote.get("accFillSz") or 0) > 0
        if filled:
            return
        self._missed_entry(order)

    def _missed_entry(self, order: dict) -> None:
        purpose = order.get("purpose")
        if purpose == "clock":
            self.state["phase"] = "wait_clock"
            self.state["order"] = None
            return
        if purpose == "secretary_last":
            self._place_market_buy("secretary_last", order.get("bar_ts"))
            return
        self.state["phase"] = "armed"
        self.state["order"] = None
        if self.state.get("limit_price"):
            self._place_limit_buy(self.state["limit_price"], "limit", None)

    def _watch_secretary(self, now_ms: int) -> None:
        if self.state.get("limit_price") and not self._buy_is_working():
            self._place_limit_buy(self.state["limit_price"], "limit", None)
            return
        start = self.state.get("secretary_start")
        if start is None or now_ms < start:
            return
        candle = self._forming(now_ms)
        if candle is None or candle["ts"] < start:
            return
        if self.state.get("seen_bar") == candle["ts"]:
            return
        limit = self.state.get("limit_price") or 0
        if candle["o"] <= limit:
            self.state["seen_bar"] = candle["ts"]
            return
        last_ts = start + (SECRETARY4_BARS - 1) * BAR_MS
        slot = (candle["ts"] - start) // BAR_MS
        if candle["ts"] > last_ts:
            self._switch_to_entry("secretary_last", None, candle["ts"], market=True)
            return
        if slot < self.state.get("reject_bars", 0):
            current = self.state.get("sample_min")
            self.state["sample_min"] = candle["o"] if current is None else min(current, candle["o"])
            self.state["seen_bar"] = candle["ts"]
            return
        sample = self.state.get("sample_min")
        if slot < SECRETARY4_BARS - 1 and sample is not None and candle["o"] < sample:
            self._switch_to_entry("secretary", candle["o"], candle["ts"], market=False)
            return
        if slot >= SECRETARY4_BARS - 1:
            self._switch_to_entry("secretary_last", candle["o"], candle["ts"], market=True)

    def _switch_to_entry(self, purpose: str, price: float | None, bar_ts: int, market: bool) -> None:
        resting = self.state.get("order") or {}
        if resting.get("clOrdId"):
            self._cancel(resting["clOrdId"])
            self.orders = [row for row in self.orders if row.get("clOrdId") != resting["clOrdId"]]
        self.state["order"] = None
        self.state["seen_bar"] = bar_ts
        row = self._position_row()
        if row is not None:
            self._on_long(row)
            return
        if market:
            self._place_market_buy(purpose, bar_ts)
        else:
            self._place_limit_buy(price, purpose, bar_ts)

    def _place_limit_buy(self, price: float | None, purpose: str, bar_ts: int | None) -> None:
        if price is None or price <= 0 or self._buy_is_working():
            return
        equity = self._sizing_equity()
        contracts = size_contracts(
            equity, price, FEE_RATE, self.spec["ct_val"], self.spec["lot_sz"], self.spec["min_sz"]
        )
        if contracts <= 0:
            self.state["phase"] = "blocked"
            self.fail("可用余额不够最小下单量。")
            return
        assert self.client is not None
        cl_id = _client_id("b")
        px = format_step(price, self.spec["tick_sz"])
        sz = format_step(contracts, self.spec["lot_sz"])
        self.client.place(self._order_body("buy", sz, px, cl_id, reduce_only=False))
        self.state["order"] = {
            "clOrdId": cl_id, "side": "buy", "px": px, "sz": sz, "purpose": purpose,
            "bar_ts": bar_ts, "equity_before": equity, "state": "live",
        }
        self.state["phase"] = "armed" if purpose == "limit" else "pending_buy"
        self._ledger().once(f"place:{cl_id}", tg.placed_text(self.state["order"]))

    def _place_market_buy(self, purpose: str, bar_ts: int | None) -> None:
        if self._buy_is_working():
            return
        price = self.last_price or 0
        equity = self._sizing_equity()
        contracts = size_contracts(
            equity, price, FEE_RATE, self.spec["ct_val"], self.spec["lot_sz"], self.spec["min_sz"]
        )
        if contracts <= 0:
            self.state["phase"] = "blocked"
            self.fail("可用余额不够最小下单量。")
            return
        assert self.client is not None
        cl_id = _client_id("b")
        sz = format_step(contracts, self.spec["lot_sz"])
        body = self._order_body("buy", sz, None, cl_id, reduce_only=False)
        body["ordType"] = "market"
        body.pop("px", None)
        self.client.place(body)
        self.state["order"] = {
            "clOrdId": cl_id, "side": "buy", "px": None, "sz": sz, "purpose": purpose,
            "bar_ts": bar_ts, "equity_before": equity, "state": "live",
        }
        self.state["phase"] = "pending_buy"
        self._ledger().once(f"place:{cl_id}", tg.placed_text(self.state["order"]))

    def _order_body(self, side: str, size: str, price: str | None, cl_id: str, reduce_only: bool) -> dict:
        body = {
            "instId": INST_ID,
            "tdMode": "cross",
            "side": side,
            "ordType": "limit",
            "sz": size,
            "clOrdId": cl_id,
        }
        if price is not None:
            body["px"] = price
        if reduce_only:
            body["reduceOnly"] = True
        if self.state.get("pos_mode") == "long_short_mode":
            body["posSide"] = "long"
        return body

    def _cancel(self, cl_id: str | None) -> None:
        if not cl_id or self.client is None:
            return
        try:
            self.client.cancel(INST_ID, cl_id)
        except OkxError:
            return

    def _buy_is_working(self) -> bool:
        order = self.state.get("order") or {}
        if order.get("side") != "buy" or not order.get("clOrdId"):
            return False
        if self._find_order(order["clOrdId"]):
            return True
        if self.client is None:
            return False
        remote = self.client.order(INST_ID, order["clOrdId"])
        return bool(remote and remote.get("state") in {"live", "partially_filled"})

    def _find_order(self, cl_id: str | None) -> dict | None:
        if not cl_id:
            return None
        for row in self.orders:
            if row.get("clOrdId") == cl_id:
                return row
        return None

    def _candle(self, ts: int) -> dict | None:
        for candle in self.candles:
            if candle["ts"] == ts:
                return candle
        return None

    def _forming(self, now_ms: int) -> dict | None:
        for candle in reversed(self.candles):
            if candle["ts"] <= now_ms < candle["ts"] + BAR_MS:
                return candle
        return None


def _book_after(position: dict, fill: float | None) -> float:
    """这笔账平仓后的本金。不用账户里的其余资金。"""
    equity_before = float(position.get("equity_before") or BOOK_EQUITY)
    coin_qty = float(position.get("coin_qty") or 0)
    entry = float(position.get("entry") or 0)
    if fill is None or coin_qty <= 0 or entry <= 0:
        return equity_before
    funding = float(position.get("funding_pnl") or 0)
    cash = equity_before - coin_qty * entry * FEE_RATE + funding
    cash += coin_qty * (fill - entry) - coin_qty * fill * FEE_RATE
    return round(max(cash, 0.0), 8)


def _float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _client_id(suffix: str) -> str:
    return f"n{int(time.time() * 1000)}{suffix}"


def main() -> None:
    def stop(_signum, _frame) -> None:
        global STOP
        STOP = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    load_env()
    runner = Runner()
    runner.publish()
    print("实盘进程已启动。未设置 OKX_LIVE=1 不会连接账户；未设置 OKX_ARM=1 不会开第一笔。", flush=True)
    while not STOP:
        try:
            runner.tick()
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            runner.fail(str(error))
        for _ in range(5):
            if STOP:
                break
            time.sleep(1)
    runner.publish()
    print("实盘进程已停止。", flush=True)


if __name__ == "__main__":
    main()
