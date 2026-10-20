"""下载并缓存 OKX 永续和现货的 15 分钟 K 线、资金费。页面只读本地文件。"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backtest import Candle, Funding

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CACHE_VERSION = 2
BAR_MS = 15 * 60 * 1000
SHANGHAI = timezone(timedelta(hours=8))

COINS = {
    "NEAR": {
        "base": "NEAR",
        "swap_id": "NEAR-USDT-SWAP",
        "spot_id": "NEAR-USDT",
        "uly": "NEAR-USDT",
        "swap_cache": DATA / "near-usdt-swap-15m.json",
        "spot_cache": DATA / "near-usdt-spot-15m.json",
    },
    "PUMP": {
        "base": "PUMP",
        "swap_id": "PUMP-USDT-SWAP",
        "spot_id": "PUMP-USDT",
        "uly": "PUMP-USDT",
        "swap_cache": DATA / "pump-usdt-swap-15m.json",
        "spot_cache": DATA / "pump-usdt-spot-15m.json",
    },
    "HYPE": {
        "base": "HYPE",
        "swap_id": "HYPE-USDT-SWAP",
        "spot_id": "HYPE-USDT",
        "uly": "HYPE-USDT",
        "swap_cache": DATA / "hype-usdt-swap-15m.json",
        "spot_cache": DATA / "hype-usdt-spot-15m.json",
    },
}
CACHE_PATH = COINS["NEAR"]["swap_cache"]
INST_ID = COINS["NEAR"]["swap_id"]

_SWAP: dict[str, dict] = {}
_SPOT: dict[str, dict] = {}


def _get(path: str, params: dict[str, str]) -> dict:
    query = urllib.parse.urlencode(params)
    url = f"https://www.okx.com{path}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "tradex-demo/0.1"})
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode())
            if payload.get("code") != "0":
                raise RuntimeError(payload.get("msg") or "OKX 返回了错误")
            return payload
        except (urllib.error.URLError, TimeoutError, RuntimeError) as error:
            last_error = error
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"读取 OKX 数据失败：{last_error}")


def default_start_ms() -> int:
    return int(datetime(2026, 3, 13, tzinfo=SHANGHAI).timestamp() * 1000)


def _pages(path: str, params: dict[str, str], start_ms: int, time_key: str) -> list[dict]:
    rows: list[dict] = []
    after: str | None = None
    for page in range(600):
        query = dict(params)
        if after:
            query["after"] = after
        data = _get(path, query).get("data") or []
        if not data:
            break
        oldest = None
        for item in data:
            ts = int(item[time_key] if isinstance(item, dict) else item[0])
            oldest = ts if oldest is None else min(oldest, ts)
            if ts >= start_ms:
                rows.append(item)
        if page % 20 == 0:
            print(f"  {path} 已读取 {len(rows)} 条", flush=True)
        if oldest is None or oldest <= start_ms or (after and int(after) == oldest):
            break
        after = str(oldest)
        time.sleep(0.12)
    return rows


def coin_spec(coin: str) -> dict:
    key = coin.upper()
    spec = COINS.get(key)
    if spec is None:
        names = "、".join(COINS)
        raise ValueError(f"币种只能是 {names}。")
    return spec


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def _read(path: Path, label: str) -> dict:
    if not path.exists():
        raise RuntimeError(f"本地没有 {label} 的 K 线，请先线下拉取。")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{label} 的本地行情文件无法读取。") from error
    if not payload.get("candles"):
        raise RuntimeError(f"{label} 的本地行情是空的。")
    return payload


def _candles(rows: list, now_ms: int) -> list[list]:
    by_ts: dict[int, list[float]] = {}
    for row in rows:
        ts = int(row[0])
        if ts + BAR_MS > now_ms:
            continue
        by_ts[ts] = [float(row[1]), float(row[2]), float(row[3]), float(row[4])]
    return [[ts, *by_ts[ts]] for ts in sorted(by_ts)]


def fetch_swap(coin: str = "NEAR", now_ms: int | None = None, start_ms: int | None = None) -> dict:
    spec = coin_spec(coin)
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    start_ms = start_ms if start_ms is not None else default_start_ms()
    inst_id = spec["swap_id"]
    print(f"正在从 OKX 下载 {inst_id} 15 分钟行情…", flush=True)
    instrument = _get(
        "/api/v5/public/instruments",
        {"instType": "SWAP", "instId": inst_id},
    )["data"][0]
    tiers = _get(
        "/api/v5/public/position-tiers",
        {"instType": "SWAP", "tdMode": "cross", "uly": spec["uly"]},
    )["data"]
    candle_rows = _pages(
        "/api/v5/market/history-candles",
        {"instId": inst_id, "bar": "15m", "limit": "100"},
        start_ms,
        "0",
    )
    funding_rows = _pages(
        "/api/v5/public/funding-rate-history",
        {"instId": inst_id, "limit": "100"},
        start_ms,
        "fundingTime",
    )
    candles = _candles(candle_rows, now_ms)
    funding_by_ts = {int(row["fundingTime"]): float(row["fundingRate"]) for row in funding_rows}
    payload = {
        "version": CACHE_VERSION,
        "coin": spec["base"],
        "fetched_at": now_ms,
        "start_ms": start_ms,
        "bar_ms": BAR_MS,
        "inst_id": inst_id,
        "ct_val": float(instrument["ctVal"]),
        "lot_sz": float(instrument["lotSz"]),
        "min_sz": float(instrument["minSz"]),
        "tick_sz": float(instrument["tickSz"]),
        "tiers": [
            {
                "min_sz": float(item["minSz"]),
                "max_sz": float(item["maxSz"]),
                "mmr": float(item["mmr"]),
            }
            for item in tiers
        ],
        "candles": candles,
        "fundings": [[ts, funding_by_ts[ts]] for ts in sorted(funding_by_ts)],
    }
    _write(spec["swap_cache"], payload)
    _SWAP[spec["base"]] = payload
    print(f"已缓存 {len(candles)} 根 15 分钟线、{len(payload['fundings'])} 条资金费。", flush=True)
    return payload


def fetch_spot(coin: str = "NEAR", now_ms: int | None = None, start_ms: int | None = None) -> dict:
    spec = coin_spec(coin)
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    start_ms = start_ms if start_ms is not None else default_start_ms()
    inst_id = spec["spot_id"]
    print(f"正在从 OKX 下载 {inst_id} 现货 15 分钟行情…", flush=True)
    instrument = _get(
        "/api/v5/public/instruments",
        {"instType": "SPOT", "instId": inst_id},
    )["data"][0]
    candle_rows = _pages(
        "/api/v5/market/history-candles",
        {"instId": inst_id, "bar": "15m", "limit": "100"},
        start_ms,
        "0",
    )
    payload = {
        "coin": spec["base"],
        "inst_id": inst_id,
        "bar_ms": BAR_MS,
        "start_ms": start_ms,
        "fetched_at": now_ms,
        "tick_sz": float(instrument["tickSz"]),
        "lot_sz": float(instrument["lotSz"]),
        "min_sz": float(instrument["minSz"]),
        "ct_val": 1,
        "candles": _candles(candle_rows, now_ms),
    }
    _write(spec["spot_cache"], payload)
    _SPOT[spec["base"]] = payload
    print(f"已缓存 {len(payload['candles'])} 根现货 15 分钟线。", flush=True)
    return payload


def fetch_market(now_ms: int | None = None, start_ms: int | None = None, coin: str = "NEAR") -> dict:
    return fetch_swap(coin, now_ms, start_ms)


def load_swap(coin: str = "NEAR") -> dict:
    spec = coin_spec(coin)
    cached = _SWAP.get(spec["base"])
    if cached is not None:
        return cached
    payload = _read(spec["swap_cache"], f"{spec['base']} 永续")
    _SWAP[spec["base"]] = payload
    return payload


def load_spot(coin: str = "NEAR") -> dict:
    spec = coin_spec(coin)
    cached = _SPOT.get(spec["base"])
    if cached is not None:
        return cached
    payload = _read(spec["spot_cache"], f"{spec['base']} 现货")
    _SPOT[spec["base"]] = payload
    return payload


def load_market(start_ms: int | None = None, force: bool = False, coin: str = "NEAR") -> dict:
    if force:
        return fetch_swap(coin, start_ms=start_ms)
    return load_swap(coin)


def candles_from(payload: dict) -> list[Candle]:
    return [Candle(int(row[0]), row[1], row[2], row[3], row[4]) for row in payload["candles"]]


def fundings_from(payload: dict) -> list[Funding]:
    return [Funding(int(row[0]), row[1]) for row in payload["fundings"]]


def mmr_for(payload: dict, contracts: float) -> float:
    tiers = payload.get("tiers") or [{"mmr": 0.01}]
    chosen = float(tiers[0]["mmr"])
    for tier in tiers:
        if float(tier["min_sz"]) <= contracts <= float(tier["max_sz"]):
            return float(tier["mmr"])
        chosen = float(tier["mmr"])
    return chosen


def missing_bars(candles: list[Candle], bar_ms: int = BAR_MS) -> int:
    missing = 0
    for prev, nxt in zip(candles, candles[1:]):
        gap = nxt.ts - prev.ts
        if gap > bar_ms:
            missing += gap // bar_ms - 1
    return missing


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main() -> None:
    parser = argparse.ArgumentParser(description="线下拉取一只币的 15 分钟 K 线到 data/")
    parser.add_argument("coin", choices=sorted(COINS))
    args = parser.parse_args()
    fetch_swap(args.coin)
    fetch_spot(args.coin)


if __name__ == "__main__":
    main()
