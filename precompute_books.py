"""线下重算钟点和秘书表的分仓数据，写进 static。页面不跑这张表。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from backtest import fill_missing_funding
from okx_data import BAR_MS, SHANGHAI, candles_from, coin_spec, fundings_from, load_spot, load_swap
from portfolio import combined_curve, run_positions

ROOT = Path(__file__).resolve().parent
START = "2026-03-13"
EQUITY = 10_000
FIELDS = (
    "target",
    "compounded",
    "mark",
    "sells",
    "liquidations",
    "limit_entries",
    "secretary_entries",
    "last_entries",
    "longest_hours",
    "max_drawdown",
    "fees",
    "funding",
)
SECRETARY_FILES = (
    ("secretary", "secretary.json", False),
    ("secretary", "secretary-spot.json", True),
    ("secretary2", "secretary2.json", False),
    ("secretary2", "secretary2-spot.json", True),
    ("secretary3", "secretary3.json", False),
    ("secretary3", "secretary3-spot.json", True),
)


def static_path(coin: str, filename: str) -> Path:
    if coin == "NEAR":
        return ROOT / "static" / filename
    return ROOT / "static" / coin.lower() / filename


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def snapshot(row: dict) -> dict:
    return {key: row[key] for key in FIELDS if key in row}


def first_entry(result):
    opened = result.cycles[0] if result.cycles else result.open_cycle
    return None if opened is None else float(opened.entry)


def tick_digits(tick: float) -> int:
    digits = 0
    value = float(tick)
    while value < 1 - 1e-12 and digits < 12:
        value *= 10
        digits += 1
    return digits


def summarize(result, target: float) -> dict:
    normal = [cycle for cycle in result.cycles if cycle.status == "target"]
    holds = [cycle.hold_hours for cycle in result.cycles]
    if result.open_cycle is not None:
        holds.append(result.open_cycle.hold_hours)
    return {
        "target": target,
        "compounded": round(result.compounded_equity, 2),
        "mark": round(result.final_equity, 2),
        "sells": len(normal),
        "liquidations": result.liquidations,
        "limit_entries": result.entries_limit,
        "secretary_entries": result.entries_secretary,
        "last_entries": result.entries_secretary_last,
        "longest_hours": None if not holds else round(max(holds), 2),
        "max_drawdown": round(result.max_drawdown, 6),
        "fees": round(result.total_fees, 2),
        "funding": round(result.total_funding, 2),
    }


def matches(computed: dict, stored: dict) -> bool:
    for key in ("compounded", "mark", "fees", "funding"):
        if abs(float(computed[key]) - float(stored[key])) > 0.02:
            return False
    for key in ("sells", "liquidations", "limit_entries", "secretary_entries", "last_entries"):
        if computed[key] != stored[key]:
            return False
    if stored.get("longest_hours") is not None:
        if abs(float(computed["longest_hours"]) - float(stored["longest_hours"])) > 0.05:
            return False
    if abs(float(computed["max_drawdown"]) - float(stored["max_drawdown"])) > 5e-4:
        return False
    return True


def prepare(coin: str, spot: bool):
    spec = coin_spec(coin)
    payload = load_spot(coin) if spot else load_swap(coin)
    day = datetime.fromisoformat(START).replace(tzinfo=SHANGHAI)
    day_start = int(day.timestamp() * 1000)
    candles = [candle for candle in candles_from(payload) if candle.ts >= day_start]
    if spot:
        fundings = []
    else:
        observed = [item for item in fundings_from(payload) if item.ts >= day_start]
        fundings, _ = fill_missing_funding(observed, candles[0].ts, candles[-1].ts)
    tiers = []
    if not spot:
        tiers = sorted(
            (
                (float(item["min_sz"]), float(item["max_sz"]), float(item["mmr"]))
                for item in payload.get("tiers") or []
            ),
            key=lambda item: item[0],
        )
    common = dict(
        initial_equity=EQUITY,
        fee_rate=0.0008 if spot else 0.0002,
        bar_ms=BAR_MS,
        ct_val=float(payload.get("ct_val") or 1),
        lot_sz=float(payload["lot_sz"]),
        min_sz=float(payload["min_sz"]),
        tick_sz=float(payload["tick_sz"]),
        mmr=1.0 if spot else (tiers[0][2] if tiers else 0.01),
        entry_delay_days=2,
        tiers=tiers or None,
    )
    return candles, fundings, common, day_start


def run_books(candles, fundings, common, day_start, target, hour, mode, record_curve):
    return run_positions(
        candles,
        fundings,
        net_target=target,
        first_entry_ts=day_start + hour * 3_600_000,
        entry_hour=hour,
        entry_mode=mode,
        record_curve=record_curve,
        **common,
    )


def total_row(base: dict, addons: list[dict], drawdown: float) -> dict:
    rows = [base, *addons]
    longest = [row["longest_hours"] for row in rows if row["longest_hours"] is not None]
    return {
        "target": base["target"],
        "compounded": round(sum(row["compounded"] for row in rows), 2),
        "mark": round(sum(row["mark"] for row in rows), 2),
        "sells": sum(row["sells"] for row in rows),
        "liquidations": sum(row["liquidations"] for row in rows),
        "limit_entries": sum(row["limit_entries"] for row in rows),
        "secretary_entries": sum(row["secretary_entries"] for row in rows),
        "last_entries": sum(row["last_entries"] for row in rows),
        "longest_hours": None if not longest else round(max(longest), 2),
        "max_drawdown": round(drawdown, 6),
        "fees": round(sum(row["fees"] for row in rows), 2),
        "funding": round(sum(row["funding"] for row in rows), 2),
    }


def update_grid(coin: str) -> None:
    path = static_path(coin, "grid.json")
    book = load_json(path)
    candles, fundings, common, day_start = prepare(coin, False)
    hours = book["hours"]
    targets = book["targets"]
    layers_by_cell = []
    totals = []
    widest = 0
    for row_index, hour in enumerate(hours):
        total_row_values = []
        extra_rows = []
        for column_index, target in enumerate(targets):
            books = run_books(candles, fundings, common, day_start, target, hour, "clock", False)
            stored = book["values"][row_index][column_index]
            fresh = round(books[0].compounded_equity, 2)
            if abs(fresh - stored) > 0.02:
                raise SystemExit(f"{coin} 钟点 {hour} 目标 {target} 仓位1是 {fresh}，表里是 {stored}")
            extras = [round(item.compounded_equity, 2) for item in books[1:]]
            extra_rows.append(extras)
            widest = max(widest, len(extras))
            total_row_values.append(round(stored + sum(extras), 2))
        layers_by_cell.append(extra_rows)
        totals.append(total_row_values)
        print(f"{coin} 钟点 {hour} 点完成，最多额外 {widest} 仓", flush=True)
    layers = []
    for depth in range(widest):
        matrix = []
        for extra_rows in layers_by_cell:
            matrix.append([row[depth] if depth < len(row) else None for row in extra_rows])
        layers.append(matrix)
    book["layers"] = layers
    book["totals"] = totals
    book["addon_step"] = 0.1
    book["addon_max_levels"] = 9
    write_json(path, book)
    print(f"wrote {path}", flush=True)


def update_secretary(coin: str, mode: str, filename: str, spot: bool) -> None:
    path = static_path(coin, filename)
    book = load_json(path)
    candles, fundings, common, day_start = prepare(coin, spot)
    for index, row in enumerate(book["rows"]):
        target = row["target"]
        books = run_books(candles, fundings, common, day_start, target, 0, mode, True)
        base = snapshot(row)
        fresh = summarize(books[0], target)
        if not matches(fresh, base):
            raise SystemExit(f"{coin} {filename} 目标 {target} 仓位1对不上：{fresh} / {base}")
        addons = [summarize(item, target) for item in books[1:]]
        if addons:
            _, drawdown, _ = combined_curve(books)
            row["total"] = total_row(base, addons, drawdown)
        else:
            row["total"] = dict(base)
        row["books"] = [base, *addons]
        digits = tick_digits(common["tick_sz"])
        for slot, result in enumerate(books):
            row["books"][slot]["entry"] = round(first_entry(result), digits)
        row["entry"] = row["books"][0]["entry"]
        if index % 10 == 9 or index == len(book["rows"]) - 1:
            print(f"{coin} {filename} {index + 1}/{len(book['rows'])} 仓位数 {len(books)}", flush=True)
    book["addon_step"] = 0.1
    book["addon_max_levels"] = 9
    write_json(path, book)
    print(f"wrote {path}", flush=True)


def patch_entries(coin: str) -> None:
    """只补每个仓位的第一次开仓价，不改已写好的复利数字。"""
    print(f"补开仓价 {coin}", flush=True)
    for mode, filename, spot in SECRETARY_FILES:
        path = static_path(coin, filename)
        book = load_json(path)
        candles, fundings, common, day_start = prepare(coin, spot)
        digits = tick_digits(common["tick_sz"])
        for index, row in enumerate(book["rows"]):
            target = row["target"]
            books = run_books(candles, fundings, common, day_start, target, 0, mode, False)
            fresh = summarize(books[0], target)
            if not matches(fresh, snapshot(row)):
                raise SystemExit(f"{coin} {filename} 目标 {target} 仓位1对不上：{fresh} / {snapshot(row)}")
            stored = row.get("books") or []
            if len(stored) != len(books):
                raise SystemExit(f"{coin} {filename} 目标 {target} 仓位数 {len(books)}，表里是 {len(stored)}")
            for slot, result in enumerate(books):
                stored[slot]["entry"] = round(first_entry(result), digits)
            row["entry"] = stored[0]["entry"]
            if index % 20 == 19 or index == len(book["rows"]) - 1:
                print(f"{coin} {filename} {index + 1}/{len(book['rows'])}", flush=True)
        book["tick_sz"] = common["tick_sz"]
        write_json(path, book)
        print(f"wrote {path}", flush=True)
    print(f"开仓价完成 {coin}", flush=True)


def process_coin(coin: str) -> None:
    print(f"开始 {coin}", flush=True)
    update_grid(coin)
    for mode, filename, spot in SECRETARY_FILES:
        update_secretary(coin, mode, filename, spot)
    print(f"完成 {coin}", flush=True)


if __name__ == "__main__":
    from concurrent.futures import ProcessPoolExecutor

    list(ProcessPoolExecutor(max_workers=3).map(process_coin, ("NEAR", "PUMP", "HYPE")))
    print("全部写完", flush=True)
