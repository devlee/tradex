"""本地回测页面。在项目目录运行：python3 server.py"""

from __future__ import annotations

import argparse
import json
import threading
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backtest import fill_missing_funding, run_backtest
from okx_data import (
    BAR_MS,
    SHANGHAI,
    candles_from,
    fundings_from,
    load_market,
    missing_bars,
)

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
LOAD_LOCK = threading.Lock()

RULES = [
    "NEAR-USDT 永续，1 倍，只做多，一次只持有一笔。K 线是 15 分钟。",
    "第一笔在起点日期的进场钟点买入，价格是那根 15 分钟 K 线的开盘价。",
    "之后每一笔，在上一笔平仓日（北京时间）之后的第 2 天、同一个钟点的开盘价买入。",
    "进场钟点可以改，范围是 0 点到 23 点，每次 1 小时。",
    "卖出价按整笔资金的净目标反推。开仓、平仓手续费和已经结算的资金费都算进去，再向上对齐到最小报价单位。",
    "持仓以后不因为下跌卖出。每 8 小时资金费结算后重算卖价。这根 K 线的最高价碰到卖价，就按卖价成交。卖出后的余额是下一笔本金。",
]


def _num(value, digits=8):
    if value is None:
        return None
    return round(float(value), digits)


def _cycle_dict(cycle) -> dict:
    return {
        "status": cycle.status,
        "entry_ts": cycle.entry_ts,
        "exit_ts": cycle.exit_ts,
        "entry": _num(cycle.entry),
        "target": _num(cycle.target),
        "initial_target": _num(cycle.initial_target),
        "exit_price": _num(cycle.exit_price),
        "contracts": _num(cycle.contracts, 4),
        "coin_qty": _num(cycle.coin_qty, 4),
        "equity_before": _num(cycle.equity_before, 4),
        "equity_after": _num(cycle.equity_after, 4),
        "fees": _num(cycle.fees, 4),
        "funding": _num(cycle.funding, 4),
        "net_pnl": _num(cycle.net_pnl, 4),
        "net_return": _num(cycle.net_return),
        "hold_hours": _num(cycle.hold_hours, 2),
        "mae_return": _num(cycle.mae_return),
    }


def _open_dict(cycle) -> dict | None:
    if cycle is None:
        return None
    return {
        "entry_ts": cycle.entry_ts,
        "entry": _num(cycle.entry),
        "target": _num(cycle.target),
        "initial_target": _num(cycle.initial_target),
        "contracts": _num(cycle.contracts, 4),
        "coin_qty": _num(cycle.coin_qty, 4),
        "equity_before": _num(cycle.equity_before, 4),
        "last_price": _num(cycle.last_price),
        "equity": _num(cycle.equity, 4),
        "upl": _num(cycle.upl, 4),
        "fees": _num(cycle.fees, 4),
        "funding": _num(cycle.funding, 4),
        "hold_hours": _num(cycle.hold_hours, 2),
        "mae_return": _num(cycle.mae_return),
    }


def build_result(
    equity: float,
    net_target: float,
    fee_rate: float,
    start: str,
    entry_hour: int,
) -> dict:
    try:
        day = datetime.fromisoformat(start)
    except ValueError as error:
        raise ValueError("起点日期格式应为 YYYY-MM-DD。") from error
    if day.year < 2020 or day.year > 2035:
        raise ValueError("起点日期超出可回测范围。")
    if not 0 <= entry_hour <= 23:
        raise ValueError("进场钟点需要在 0 到 23 之间。")
    if equity <= 0:
        raise ValueError("起始资金需要大于 0。")
    if not 0.001 <= net_target <= 0.5:
        raise ValueError("净目标需要在 0.1% 和 50% 之间。")
    if not 0 <= fee_rate < 0.02:
        raise ValueError("挂单费率需要在 0 和 2% 之间。")

    day_start = int(day.replace(tzinfo=SHANGHAI).timestamp() * 1000)
    first_entry = day_start + entry_hour * 3_600_000
    with LOAD_LOCK:
        payload = load_market(day_start)
    candles = [candle for candle in candles_from(payload) if candle.ts >= day_start]
    observed = [item for item in fundings_from(payload) if item.ts >= day_start]
    if len(candles) < 2:
        raise RuntimeError("行情不足，无法回测。")
    fundings, assumed_fundings = fill_missing_funding(
        observed, candles[0].ts, candles[-1].ts
    )
    tiers = sorted(
        (
            (float(item["min_sz"]), float(item["max_sz"]), float(item["mmr"]))
            for item in payload.get("tiers") or []
        ),
        key=lambda item: item[0],
    )
    result = run_backtest(
        candles,
        fundings,
        initial_equity=equity,
        net_target=net_target,
        fee_rate=fee_rate,
        bar_ms=BAR_MS,
        ct_val=float(payload["ct_val"]),
        lot_sz=float(payload["lot_sz"]),
        min_sz=float(payload["min_sz"]),
        tick_sz=float(payload["tick_sz"]),
        mmr=tiers[0][2] if tiers else 0.01,
        first_entry_ts=first_entry,
        entry_hour=entry_hour,
        tiers=tiers or None,
    )
    normal = [cycle for cycle in result.cycles if cycle.status == "target"]
    holds = [cycle.hold_hours for cycle in normal]
    holds_for_max = [cycle.hold_hours for cycle in result.cycles]
    if result.open_cycle is not None:
        holds_for_max.append(result.open_cycle.hold_hours)
    warnings = []
    missed = missing_bars(candles, BAR_MS)
    if missed:
        warnings.append(f"15 分钟线缺了 {missed} 根，缺口里的价格没有重放。")
    if candles[0].ts > first_entry:
        warnings.append("起点钟点没有对应的 K 线，第一笔会顺延到之后最近的同一个钟点。")
    if assumed_fundings:
        warnings.append(
            f"有 {assumed_fundings} 次 8 小时资金费没有记录，按 0.01% 计入。"
        )
    theoretical = None
    if result.liquidations == 0 and normal:
        theoretical = equity * ((1 + net_target) ** len(normal))
    markers = []
    for cycle in result.cycles:
        markers.append([cycle.entry_ts, "buy", _num(cycle.entry)])
        kind = "sell" if cycle.status == "target" else "liq"
        markers.append([cycle.exit_ts, kind, _num(cycle.exit_price)])
    if result.open_cycle is not None:
        markers.append([result.open_cycle.entry_ts, "buy", _num(result.open_cycle.entry)])

    return {
        "rules": RULES,
        "market": {
            "inst_id": payload["inst_id"],
            "bar": "15m",
            "start": candles[0].ts,
            "end": candles[-1].ts,
            "count": len(candles),
            "funding_points": len(fundings),
            "ct_val": payload["ct_val"],
            "lot_sz": payload["lot_sz"],
            "min_sz": payload["min_sz"],
            "tick_sz": payload["tick_sz"],
            "mmr": tiers[0][2] if tiers else 0.01,
            "fetched_at": payload.get("fetched_at"),
            "warnings": warnings,
        },
        "params": {
            "initial_equity": equity,
            "net_target": net_target,
            "fee_rate": fee_rate,
            "leverage": 1,
            "start": start,
            "entry_hour": entry_hour,
            "entry_delay_days": 2,
        },
        "stats": {
            "completed": len(normal),
            "liquidations": result.liquidations,
            "final_equity": _num(result.final_equity, 4),
            "final_cash": _num(result.final_cash, 4),
            "compounded_equity": _num(result.compounded_equity, 4),
            "max_drawdown": _num(result.max_drawdown),
            "max_drawdown_ts": result.max_drawdown_ts,
            "worst_mae": _num(result.worst_mae),
            "max_hold_hours": _num(max(holds_for_max), 2) if holds_for_max else None,
            "avg_hold_hours": _num(sum(holds) / len(holds), 2) if holds else None,
            "total_fees": _num(result.total_fees, 4),
            "total_funding": _num(result.total_funding, 4),
            "min_net_return": _num(min(cycle.net_return for cycle in normal)) if normal else None,
            "avg_net_return": _num(sum(cycle.net_return for cycle in normal) / len(normal)) if normal else None,
            "max_net_return": _num(max(cycle.net_return for cycle in normal)) if normal else None,
            "theoretical_equity": _num(theoretical, 4) if theoretical is not None else None,
            "note": result.note,
            "next_entry_ts": result.next_entry_ts,
        },
        "cycles": [_cycle_dict(cycle) for cycle in result.cycles],
        "open_cycle": _open_dict(result.open_cycle),
        "candles": [
            [candle.ts, _num(candle.o), _num(candle.h), _num(candle.l), _num(candle.c)]
            for candle in candles
        ],
        "curve": [
            [point.ts, _num(point.equity, 4), _num(point.cash, 4)] for point in result.curve
        ],
        "markers": markers,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self._send(code, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                self._json(200, {"ok": True})
                return
            if parsed.path == "/api/backtest":
                query = parse_qs(parsed.query)
                equity = float(query.get("equity", ["10000"])[0])
                net_target = float(query.get("net", ["0.02"])[0])
                fee_rate = float(query.get("fee", ["0.0002"])[0])
                start = query.get("start", ["2026-03-13"])[0]
                entry_hour = int(query.get("hour", ["0"])[0])
                self._json(200, build_result(equity, net_target, fee_rate, start, entry_hour))
                return
            self._file(parsed.path)
        except ValueError as error:
            self._json(400, {"error": str(error)})
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            self._json(500, {"error": str(error)})

    def _file(self, path: str) -> None:
        rel = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (STATIC / rel).resolve()
        if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
            self._json(404, {"error": "找不到页面文件。"})
            return
        kind = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), kind)


def main() -> None:
    parser = argparse.ArgumentParser(description="NEAR 周期回测演示")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"打开 http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止", flush=True)


if __name__ == "__main__":
    main()
