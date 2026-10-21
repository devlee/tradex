"""线下重算钟点和秘书表的分仓数据，写进 static。页面不跑这张表。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from backtest import SECRETARY4_BARS, fill_missing_funding, run_backtest
from okx_data import BAR_MS, SHANGHAI, candles_from, fundings_from, load_swap
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
    ("secretary", "secretary.json"),
    ("secretary2", "secretary2.json"),
    ("secretary3", "secretary3.json"),
    ("secretary4", "secretary4.json"),
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


FIVE_MIN_MS = 5 * 60 * 1000
SPAN_NAMES = {BAR_MS: ("15m", "15分钟"), FIVE_MIN_MS: ("5m", "5分钟")}


def prepare(coin: str, bar_ms: int = BAR_MS):
    swap = load_swap(coin)
    if bar_ms == BAR_MS:
        candles_payload = swap
    elif bar_ms == FIVE_MIN_MS:
        path = ROOT / "data" / f"{coin.lower()}-usdt-swap-5m.json"
        if not path.exists():
            raise SystemExit(f"本地没有 {coin} 的 5 分钟 K 线")
        candles_payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise SystemExit(f"不支持的 K 线周期 {bar_ms}")
    day = datetime.fromisoformat(START).replace(tzinfo=SHANGHAI)
    day_start = int(day.timestamp() * 1000)
    candles = [candle for candle in candles_from(candles_payload) if candle.ts >= day_start]
    if not candles or candles[0].ts != day_start:
        raise SystemExit(f"{coin} 的 K 线没有 {START} 北京时间 0 点这一根")
    observed = [item for item in fundings_from(swap) if item.ts >= day_start]
    fundings, _ = fill_missing_funding(observed, candles[0].ts, candles[-1].ts)
    tiers = sorted(
        (
            (float(item["min_sz"]), float(item["max_sz"]), float(item["mmr"]))
            for item in swap.get("tiers") or []
        ),
        key=lambda item: item[0],
    )
    common = dict(
        initial_equity=EQUITY,
        fee_rate=0.0002,
        bar_ms=bar_ms,
        ct_val=float(candles_payload.get("ct_val") or swap.get("ct_val") or 1),
        lot_sz=float(candles_payload.get("lot_sz") or swap["lot_sz"]),
        min_sz=float(candles_payload.get("min_sz") or swap["min_sz"]),
        tick_sz=float(candles_payload.get("tick_sz") or swap["tick_sz"]),
        mmr=tiers[0][2] if tiers else 0.01,
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
    candles, fundings, common, day_start = prepare(coin)
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


def update_secretary(coin: str, mode: str, filename: str) -> None:
    path = static_path(coin, filename)
    book = load_json(path)
    candles, fundings, common, day_start = prepare(coin)
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
    for mode, filename in SECRETARY_FILES:
        path = static_path(coin, filename)
        book = load_json(path)
        candles, fundings, common, day_start = prepare(coin)
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


def build_secretary(coin: str, mode: str, filename: str, targets: list[float]) -> None:
    path = static_path(coin, filename)
    candles, fundings, common, day_start = prepare(coin)
    digits = tick_digits(common["tick_sz"])
    rows = []
    for index, target in enumerate(targets):
        books = run_books(candles, fundings, common, day_start, target, 0, mode, True)
        base = summarize(books[0], target)
        addons = [summarize(item, target) for item in books[1:]]
        row = dict(base)
        if addons:
            _, drawdown, _ = combined_curve(books)
            row["total"] = total_row(base, addons, drawdown)
        else:
            row["total"] = dict(base)
        row["books"] = [dict(base), *addons]
        for slot, result in enumerate(books):
            row["books"][slot]["entry"] = round(first_entry(result), digits)
        row["entry"] = row["books"][0]["entry"]
        rows.append(row)
        if index % 10 == 9 or index == len(targets) - 1:
            print(f"{coin} {filename} {index + 1}/{len(targets)} 仓位数 {len(books)}", flush=True)
    write_json(path, {
        "coin": coin,
        "equity": EQUITY,
        "start": START,
        "first_hour": 0,
        "entry_mode": mode,
        "window": "next bar plus 32 bars",
        "window_bars": SECRETARY4_BARS if mode == "secretary4" else None,
        "tick_sz": common["tick_sz"],
        "fee_rate": common["fee_rate"],
        "addon_step": 0.1,
        "addon_max_levels": 9,
        "rows": rows,
    })
    print(f"wrote {path}", flush=True)


def build_secretary4(coin: str) -> None:
    targets = [round(step / 100, 2) for step in range(1, 51)]
    build_secretary(coin, "secretary4", "secretary4.json", targets)


STAT_SERIES = (
    ("clock", "钟点进场", None),
    ("secretary", "秘书问题", "secretary.json"),
    ("secretary2", "秘书问题2", "secretary2.json"),
    ("secretary3", "秘书问题3", "secretary3.json"),
    ("secretary4", "秘书问题4", "secretary4.json"),
)


def _percent_targets() -> list[float]:
    return [round(step / 100, 2) for step in range(1, 51)]


def _stored_sells(path: Path) -> list[int]:
    book = load_json(path)
    expected = _percent_targets()
    found = [round(float(row["target"]), 2) for row in book["rows"]]
    if found != expected:
        raise SystemExit(f"{path.name} 净目标不是 1% 到 50%")
    sells = []
    for row in book["rows"]:
        count = int(row["sells"])
        books = row.get("books") or []
        if books and int(books[0]["sells"]) != count:
            raise SystemExit(f"{path.name} 目标 {row['target']} 的卖出次数和仓位1不一致")
        sells.append(count)
    return sells


def _series_sells(coin: str, bar_ms: int) -> list[dict]:
    candles, fundings, common, day_start = prepare(coin, bar_ms)
    span, span_name = SPAN_NAMES[bar_ms]
    targets = _percent_targets()
    print(f"{coin} {span_name} {len(candles)} 根", flush=True)
    series = []
    for strategy, name, _filename in STAT_SERIES:
        counts = []
        for index, target in enumerate(targets):
            result = run_backtest(
                candles,
                fundings,
                net_target=target,
                first_entry_ts=day_start,
                entry_hour=0,
                entry_mode=strategy,
                record_curve=False,
                **common,
            )
            counts.append(len([cycle for cycle in result.cycles if cycle.status == "target"]))
            if index % 10 == 9 or index == len(targets) - 1:
                print(f"{coin} {span_name} {name} {index + 1}/{len(targets)}", flush=True)
        series.append({
            "strategy": strategy,
            "name": name,
            "span": span,
            "span_name": span_name,
            "sells": counts,
        })
    return series


def add_stats_span(coin: str, bar_ms: int = FIVE_MIN_MS) -> None:
    """把一档 K 线的仓位1卖出次数写进已有统计。15 分钟的数字保持不动。"""
    path = static_path(coin, "stats.json")
    book = load_json(path)
    span, _span_name = SPAN_NAMES[bar_ms]
    fresh = _series_sells(coin, bar_ms)
    kept = [item for item in book["series"] if item.get("span") != span]
    book["series"] = kept + fresh
    book["spans"] = []
    for item in book["series"]:
        if item["span"] not in book["spans"]:
            book["spans"].append(item["span"])
    write_json(path, book)
    print(f"wrote {path} {span}", flush=True)


def replace_stats_strategy(coin: str, strategy: str, bar_ms: int = FIVE_MIN_MS) -> None:
    """只重写统计里某一策略、某一档 K 线的卖出次数。"""
    candles, fundings, common, day_start = prepare(coin, bar_ms)
    span, span_name = SPAN_NAMES[bar_ms]
    name = next(item[1] for item in STAT_SERIES if item[0] == strategy)
    targets = _percent_targets()
    counts = []
    for index, target in enumerate(targets):
        result = run_backtest(
            candles,
            fundings,
            net_target=target,
            first_entry_ts=day_start,
            entry_hour=0,
            entry_mode=strategy,
            record_curve=False,
            **common,
        )
        counts.append(len([cycle for cycle in result.cycles if cycle.status == "target"]))
        if index % 10 == 9 or index == len(targets) - 1:
            print(f"{coin} {span_name} {name} {index + 1}/{len(targets)}", flush=True)
    path = static_path(coin, "stats.json")
    book = load_json(path)
    matched = False
    for item in book["series"]:
        if item.get("strategy") == strategy and item.get("span") == span:
            item["sells"] = counts
            matched = True
    if not matched:
        raise SystemExit(f"{coin} 统计里没有 {strategy} {span}")
    write_json(path, book)
    print(f"wrote {path} {strategy} {span}", flush=True)


def build_stats(coin: str) -> None:
    """首页折线：仓位1在各净目标下的卖出次数。页面不重算。"""
    candles, fundings, common, day_start = prepare(coin)
    grid_path = static_path(coin, "grid.json")
    grid = load_json(grid_path)
    hours = [int(hour) for hour in grid["hours"]]
    if 0 not in hours:
        raise SystemExit(f"{coin} 钟点表没有 0 点")
    row_index = hours.index(0)
    grid_targets = [round(float(item), 2) for item in grid["targets"]]
    targets = _percent_targets()
    clock_sells = []
    for index, target in enumerate(targets):
        result = run_backtest(
            candles,
            fundings,
            net_target=target,
            first_entry_ts=day_start,
            entry_hour=0,
            entry_mode="clock",
            record_curve=False,
            **common,
        )
        fresh = round(result.compounded_equity, 2)
        stored = float(grid["values"][row_index][grid_targets.index(target)])
        if abs(fresh - stored) > 0.02:
            raise SystemExit(f"{coin} 钟点 0 点目标 {target} 仓位1是 {fresh}，表里是 {stored}")
        clock_sells.append(len([cycle for cycle in result.cycles if cycle.status == "target"]))
        if index % 10 == 9 or index == len(targets) - 1:
            print(f"{coin} 钟点 {index + 1}/{len(targets)}", flush=True)
    series = []
    for strategy, name, filename in STAT_SERIES:
        counts = clock_sells if filename is None else _stored_sells(static_path(coin, filename))
        series.append({
            "strategy": strategy,
            "name": name,
            "span": "15m",
            "span_name": "15分钟",
            "sells": counts,
        })
    path = static_path(coin, "stats.json")
    write_json(path, {
        "coin": coin,
        "equity": EQUITY,
        "start": START,
        "fee_rate": 0.0002,
        "book": "仓位1",
        "clock_hour": 0,
        "targets": targets,
        "series": series,
    })
    print(f"wrote {path}", flush=True)


def process_coin(coin: str) -> None:
    print(f"开始 {coin}", flush=True)
    update_grid(coin)
    fresh_targets = [round(step / 100, 2) for step in range(1, 51)]
    for mode, filename in SECRETARY_FILES:
        if mode == "secretary4" and not static_path(coin, filename).exists():
            build_secretary(coin, mode, filename, fresh_targets)
        else:
            update_secretary(coin, mode, filename)
    print(f"完成 {coin}", flush=True)


if __name__ == "__main__":
    from concurrent.futures import ProcessPoolExecutor

    list(ProcessPoolExecutor(max_workers=3).map(process_coin, ("NEAR", "PUMP", "HYPE")))
    print("全部写完", flush=True)
