"""下载并缓存 OKX NEAR-USDT 永续的 15 分钟 K 线和资金费。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backtest import Candle, Funding

ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "data" / "near-usdt-swap-15m.json"
CACHE_VERSION = 2
INST_ID = "NEAR-USDT-SWAP"
BAR_MS = 15 * 60 * 1000
SHANGHAI = timezone(timedelta(hours=8))

_CACHE: dict | None = None


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


def fetch_market(now_ms: int | None = None, start_ms: int | None = None) -> dict:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    start_ms = start_ms if start_ms is not None else default_start_ms()
    print("正在从 OKX 下载 NEAR-USDT 永续 15 分钟行情…", flush=True)
    instrument = _get(
        "/api/v5/public/instruments",
        {"instType": "SWAP", "instId": INST_ID},
    )["data"][0]
    tiers = _get(
        "/api/v5/public/position-tiers",
        {"instType": "SWAP", "tdMode": "cross", "uly": "NEAR-USDT"},
    )["data"]
    candle_rows = _pages(
        "/api/v5/market/history-candles",
        {"instId": INST_ID, "bar": "15m", "limit": "100"},
        start_ms,
        "0",
    )
    funding_rows = _pages(
        "/api/v5/public/funding-rate-history",
        {"instId": INST_ID, "limit": "100"},
        start_ms,
        "fundingTime",
    )
    by_ts: dict[int, list[float]] = {}
    for row in candle_rows:
        ts = int(row[0])
        if ts + BAR_MS > now_ms:
            continue
        by_ts[ts] = [float(row[1]), float(row[2]), float(row[3]), float(row[4])]
    candles = [[ts, *by_ts[ts]] for ts in sorted(by_ts)]
    funding_by_ts: dict[int, float] = {}
    for row in funding_rows:
        funding_by_ts[int(row["fundingTime"])] = float(row["fundingRate"])
    fundings = [[ts, funding_by_ts[ts]] for ts in sorted(funding_by_ts)]
    payload = {
        "version": CACHE_VERSION,
        "fetched_at": now_ms,
        "start_ms": start_ms,
        "bar_ms": BAR_MS,
        "inst_id": INST_ID,
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
        "fundings": fundings,
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(
        f"已缓存 {len(candles)} 根 15 分钟线、{len(fundings)} 条资金费。",
        flush=True,
    )
    return payload


def load_market(start_ms: int | None = None, force: bool = False) -> dict:
    global _CACHE
    need = start_ms if start_ms is not None else default_start_ms()
    now_ms = int(time.time() * 1000)
    if _CACHE is not None and not force and int(_CACHE.get("start_ms", 0)) <= need:
        return _CACHE
    payload = None
    if CACHE_PATH.exists() and not force:
        try:
            payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
    stale = (
        payload is None
        or payload.get("version") != CACHE_VERSION
        or payload.get("bar_ms") != BAR_MS
        or int(payload.get("start_ms", 10**18)) > need
        or now_ms - int(payload.get("fetched_at", 0)) > 6 * 3_600_000
        or not payload.get("candles")
    )
    if stale:
        payload = fetch_market(now_ms, min(need, default_start_ms()))
    _CACHE = payload
    return payload


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
