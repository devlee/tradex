import { useEffect, useRef, useState } from "react";
import Charts from "../components/Charts";
import HeatGrid from "../components/HeatGrid";
import { bookUrl, useCoin } from "../coin";
import {
  formatTs,
  hold,
  money,
  pct,
  priceOf,
  signedMoney,
  tone,
} from "../format";

const RULES = [
  "NEAR-USDT 永续，1 倍，只做多，一次只持有一笔。K 线是 15 分钟。",
  "第一笔在起点日期的进场钟点买入，价格是那根 15 分钟 K 线的开盘价。",
  "之后每一笔，在上一笔平仓日（北京时间）之后的第 2 天、同一个钟点的开盘价买入。",
  "进场钟点可以改，范围是 0 点到 23 点，每次 1 小时。",
  "卖出价按整笔资金的净目标反推。开仓、平仓手续费和已经结算的资金费都算进去，再向上对齐到最小报价单位。",
  "持仓以后不因为下跌卖出。每 8 小时资金费结算后重算卖价。这根 K 线的最高价碰到卖价，就按卖价成交。卖出后的余额是下一笔本金。",
];

const INITIAL_FORM = {
  equity: "10000",
  net: "2",
  fee: "0.02",
  start: "2026-03-13",
  hour: "0",
};

function summaryText(data) {
  const stats = data.stats;
  const bits = [
    `${formatTs(data.market.start)} 到 ${formatTs(data.market.end)}，共 ${data.market.count} 根 15 分钟 K 线。进场钟点是北京时间 ${data.params.entry_hour} 点。`,
    `正常卖出 ${stats.completed} 笔。`,
  ];
  if (stats.completed) {
    bits.push(`这些周期连乘后的余额是 ${money(stats.compounded_equity)} USDT。`);
    if (stats.theoretical_equity != null) {
      bits.push(`每笔刚好达到净目标时，连乘结果是 ${money(stats.theoretical_equity)} USDT。`);
    }
    if (stats.max_hold_hours >= 48) {
      bits.push(`最长的一笔拿了 ${hold(stats.max_hold_hours)}。`);
    }
  }
  if (data.open_cycle) {
    bits.push(`结束时还有一笔没卖掉，按最后收盘价算，市值权益是 ${money(stats.final_equity)} USDT。`);
  } else if (stats.completed) {
    bits.push(`结束时是空仓，市值权益是 ${money(stats.final_equity)} USDT。`);
  }
  if (stats.liquidations) bits.push(`另外有 ${stats.liquidations} 笔被强平。`);
  if (!data.open_cycle && stats.next_entry_ts) {
    bits.push(`下一笔计划在 ${formatTs(stats.next_entry_ts)} 的开盘价。`);
  }
  return bits.join("");
}

export default function ClockPage() {
  const { coin } = useCoin();
  const [form, setForm] = useState(INITIAL_FORM);
  const formRef = useRef(form);
  formRef.current = form;
  const [data, setData] = useState(null);
  const [grid, setGrid] = useState(null);
  const [gridError, setGridError] = useState("");
  const [status, setStatus] = useState("正在准备行情。");
  const [running, setRunning] = useState(false);
  const [activeKey, setActiveKey] = useState(null);
  const requestId = useRef(0);

  async function loadBacktest(nextForm, nextCoin) {
    const id = ++requestId.current;
    const equity = nextForm.equity;
    const net = Number(nextForm.net) / 100;
    const fee = Number(nextForm.fee) / 100;
    const { start, hour } = nextForm;
    setRunning(true);
    setStatus(`正在读取本地的 ${nextCoin} 永续 15 分钟行情并重放规则。`);
    try {
      const response = await fetch(`/api/backtest?equity=${encodeURIComponent(equity)}&net=${encodeURIComponent(net)}&fee=${encodeURIComponent(fee)}&start=${encodeURIComponent(start)}&hour=${encodeURIComponent(hour)}&coin=${encodeURIComponent(nextCoin)}`);
      const payload = await response.json();
      if (id !== requestId.current) return;
      if (!response.ok) throw new Error(payload.error || "回测失败");
      setData(payload);
      setActiveKey(null);
      setStatus("回测完成。这是本地行情的重放，用来观察这条规则，不是对以后收益的预测。");
    } catch (error) {
      if (id !== requestId.current) return;
      setData(null);
      setStatus(error.message || "回测失败");
    } finally {
      if (id === requestId.current) setRunning(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    loadBacktest(formRef.current, coin);
    setGrid(null);
    setGridError("");
    fetch(bookUrl(coin, "grid.json"))
      .then((response) => {
        if (!response.ok) throw new Error("复利表没有读到");
        return response.json();
      })
      .then((payload) => {
        if (!cancelled) setGrid(payload);
      })
      .catch((error) => {
        if (!cancelled) setGridError(error.message || "复利表没有读到");
      });
    return () => {
      cancelled = true;
    };
  }, [coin]);

  function update(event) {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  }

  const base = data?.market.coin || coin;
  const stats = data?.stats;
  const tick = data?.market.tick_sz ?? 0.001;
  const targetText = data
    ? String(Math.round(data.params.net_target * 1000) / 10).replace(/\.0$/, "")
    : form.net;
  const funding = Number(stats?.total_funding || 0);
  const sample = data
    ? [...data.cycles].reverse().find((cycle) => cycle.status === "target") || data.open_cycle
    : null;
  const rows = data
    ? (data.open_cycle ? [...data.cycles, { ...data.open_cycle, status: "open" }] : data.cycles)
    : [];
  const focus = activeKey == null ? null : {
    entryTs: rows[activeKey].entry_ts,
    exitTs: rows[activeKey].exit_ts,
    endTs: data.market.end,
  };

  return (
    <div className="layout">
      <aside>
        <h1>{base} 永续<br /><span>{targetText}%</span> 净收益周期</h1>
        <p className="lede">用 15 分钟 K 线重放：在指定钟点的开盘价买入，净赚到目标就卖，没赚到就继续拿着，卖完用新的余额做下一笔。</p>
        <ol className="rules">
          {(data?.rules || RULES).map((rule) => <li key={rule}>{rule.replaceAll("NEAR", base)}</li>)}
        </ol>
        <details className="formula">
          <summary>卖出价怎么算</summary>
          <p>卖出价 = ［开仓价 × (1 + 费率) + (净目标金额 − 资金费收支) / 持仓数量］ / (1 − 费率)，再向上取到报价步进。</p>
          <p>净目标金额 = 开仓前权益 × 净目标。资金费收支为正表示已经收到，为负表示已经付出。</p>
        </details>
        <form onSubmit={(event) => { event.preventDefault(); loadBacktest(form, coin); }}>
          <label>起始资金（USDT）
            <input name="equity" type="number" min="10" step="1" value={form.equity} onChange={update} />
          </label>
          <label>单周期净目标（%）
            <input name="net" type="number" min="0.1" max="50" step="0.1" value={form.net} onChange={update} />
          </label>
          <label>挂单费率（%）
            <input name="fee" type="number" min="0" max="1" step="0.01" value={form.fee} onChange={update} />
          </label>
          <label>起点日期
            <input name="start" type="date" value={form.start} required onChange={update} />
          </label>
          <label>进场钟点（北京时间）
            <input name="hour" type="number" min="0" max="23" step="1" value={form.hour} onChange={update} />
          </label>
          <button type="submit" disabled={running}>重新回测</button>
          <p className="hint">K 线固定为 15 分钟。例如 3 月 13 日平仓、钟点为 0，下一笔就在 3 月 15 日 0 点那根 K 线的开盘价买入。费率按页面上的数字计，默认 0.02%。</p>
        </form>
        {data ? (
          <p className="spec">合约 {data.market.inst_id}，1 张 = {data.market.ct_val} {base}，最小 {data.market.lot_sz} 张，报价步进 {data.market.tick_sz}。小仓位维持保证金 {(data.market.mmr * 100).toFixed(2)}%。行情文件更新于 {formatTs(data.market.fetched_at)}。</p>
        ) : null}
      </aside>
      <main>
        <p className="status" role="status">{status}</p>
        {data?.market.warnings.map((text) => <p className="warning" key={text}>{text}</p>)}
        {stats?.note ? <p className="warning">{stats.note}</p> : null}
        {data ? <p className="summary">{summaryText(data)}</p> : null}
        {data?.open_cycle ? <OpenPosition open={data.open_cycle} tick={tick} base={base} /> : null}
        {stats ? (
          <section className="stats">
            <Stat label="市值权益" value={money(stats.final_equity)} caption="最后一根收盘价下的账户价值" className="sand" />
            <Stat label="已完成复利" value={money(stats.compounded_equity)} caption="已平仓周期连乘后的余额" className="sand" />
            <Stat label="正常卖出" value={String(stats.completed)} caption={stats.avg_net_return == null ? "还没有完成的周期" : `单笔净利率 ${pct(stats.min_net_return)} 到 ${pct(stats.max_net_return)}`} />
            <Stat label="最长持仓" value={hold(stats.max_hold_hours)} caption={stats.avg_hold_hours == null ? "含未平仓的这一笔" : `已完成周期平均 ${hold(stats.avg_hold_hours)}`} />
            <Stat label="收盘最大回撤" value={stats.max_drawdown ? `−${(stats.max_drawdown * 100).toFixed(2)}%` : "0.00%"} caption="按每根 K 线收盘时的市值，从高点回落的最大幅度" className="down" />
            <Stat label="单笔最大浮亏" value={pct(stats.worst_mae)} caption="按持仓期间 K 线最低价估计" className="down" />
            <Stat label="手续费合计" value={money(stats.total_fees)} caption="开仓和平仓挂单费" />
            <Stat label="资金费收支" value={signedMoney(funding)} caption={funding < 0 ? "负数是净付出" : "正数是净收到"} className={tone(funding)} />
          </section>
        ) : null}
        {data ? <Charts data={data} focus={focus} base={base} /> : null}
        {sample ? (
          <section className="panel">
            <h2>{sample.exit_ts ? "最近一笔完成的账" : "当前这笔的账"}</h2>
            <p className="explain">
              {sample.exit_ts
                ? `开仓前权益 ${money(sample.equity_before)} USDT，买入 ${sample.coin_qty} ${base}，价格 ${priceOf(sample.entry, tick)}。卖出价格 ${priceOf(sample.exit_price, tick)}。手续费 ${money(sample.fees)} USDT，资金费 ${signedMoney(sample.funding)} USDT。结束后权益 ${money(sample.equity_after)} USDT，净利率 ${pct(sample.net_return)}。`
                : `开仓前权益 ${money(sample.equity_before)} USDT，买入 ${sample.coin_qty} ${base}，价格 ${priceOf(sample.entry, tick)}。当前目标卖价 ${priceOf(sample.target, tick)}。已经付出开仓手续费 ${money(sample.fees)} USDT，资金费 ${signedMoney(sample.funding)} USDT。按最新价算，这笔市值是 ${money(sample.equity)} USDT。`}
            </p>
          </section>
        ) : null}
        <section className="panel">
          <div className="panel-head">
            <h2>每个周期</h2>
            <p>点一行，价格图会移到这笔的区间。时间是北京时间。</p>
          </div>
          <div className="table-wrap">
            <table className="cycles">
              <thead>
                <tr>
                  <th>#</th>
                  <th>开仓</th>
                  <th>平仓</th>
                  <th>开仓价</th>
                  <th>卖出价</th>
                  <th>净收益</th>
                  <th>净利率</th>
                  <th>结束后权益</th>
                  <th>资金费</th>
                  <th>手续费</th>
                  <th>持仓</th>
                  <th>最大浮亏</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((cycle, index) => {
                  const marked = cycle.equity_after == null ? cycle.equity - cycle.equity_before : cycle.net_pnl;
                  const rate = cycle.net_return == null ? marked / cycle.equity_before : cycle.net_return;
                  const cells = [
                    cycle.status === "open" ? "持仓" : String(index + 1),
                    formatTs(cycle.entry_ts),
                    cycle.exit_ts ? formatTs(cycle.exit_ts) : "未平",
                    priceOf(cycle.entry, tick),
                    priceOf(cycle.target, tick),
                    signedMoney(marked),
                    pct(rate),
                    money(cycle.equity_after == null ? cycle.equity : cycle.equity_after),
                    signedMoney(cycle.funding),
                    money(cycle.fees),
                    hold(cycle.hold_hours),
                    pct(cycle.mae_return),
                  ];
                  const tones = { 5: marked, 6: rate, 8: cycle.funding, 11: cycle.mae_return };
                  return (
                    <tr
                      key={`${cycle.entry_ts}-${cycle.status}`}
                      className={[
                        cycle.status === "open" ? "open-row" : "",
                        cycle.status === "liquidated" ? "liq-row" : "",
                        activeKey === index ? "active" : "",
                      ].filter(Boolean).join(" ")}
                      tabIndex={0}
                      onClick={() => setActiveKey(index)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") setActiveKey(index);
                      }}
                    >
                      {cells.map((text, cellIndex) => (
                        <td key={cellIndex} className={cellIndex in tones ? tone(tones[cellIndex]) : ""}>{text}</td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
        {gridError ? <p className="warning">{gridError}</p> : <HeatGrid grid={grid} applied={data?.params} />}
      </main>
    </div>
  );
}

function Stat({ label, value, caption, className }) {
  return (
    <article className="stat">
      <span>{label}</span>
      <strong className={className || ""}>{value}</strong>
      <em>{caption}</em>
    </article>
  );
}

function OpenPosition({ open, tick, base }) {
  const gap = (open.target - open.last_price) / open.last_price;
  const facts = [
    ["开仓", formatTs(open.entry_ts)],
    ["开仓价", priceOf(open.entry, tick)],
    ["数量", `${open.coin_qty} ${base}`],
    ["当前卖价", priceOf(open.target, tick), "sand"],
    ["最新价", priceOf(open.last_price, tick)],
    ["浮动盈亏", signedMoney(open.upl), tone(open.upl)],
    ["这笔市值", money(open.equity), "sand"],
    ["已持有", hold(open.hold_hours)],
    ["这笔最大浮亏", pct(open.mae_return), "down"],
    ["开仓手续费", money(open.fees)],
    ["这笔资金费", signedMoney(open.funding), tone(open.funding)],
  ];
  return (
    <section className="open">
      <div className="open-head">
        <h2>有一笔还在持仓</h2>
        <p>{gap > 0 ? `最新价到卖单还差 ${(gap * 100).toFixed(2)}%` : "最新价已经在卖单之上，卖出留到下一根 K 线"}</p>
      </div>
      <dl className="facts">
        {facts.map(([label, value, className]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd className={className || ""}>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
