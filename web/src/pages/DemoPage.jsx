import { useEffect, useState } from "react";
import { formatTs, money, priceOf, signedMoney, tone } from "../format";

const TICK = 0.001;

function price(value) {
  if (value == null || value === "") return "—";
  return priceOf(value, TICK);
}

function when(ms) {
  if (ms == null) return "—";
  return formatTs(ms);
}

export default function DemoPage() {
  const [book, setBook] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stop = false;
    const load = () => {
      fetch("/api/demo")
        .then((response) => response.json())
        .then((payload) => {
          if (!stop) {
            setBook(payload);
            setError(payload.error || "");
          }
        })
        .catch(() => {
          if (!stop) setError("实盘状态读不出来。");
        });
    };
    load();
    const timer = setInterval(load, 5000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, []);

  const position = book?.position;
  const order = book?.order;

  return (
    <main className="layout">
      <section className="panel">
        <p className="eyebrow">OKX 实盘 · NEAR-USDT 永续 · 秘书问题4</p>
        <h1>实盘</h1>
        <p className="lede">
          后台进程开着就盯 NEAR 永续，关掉进程就停止。页面只展示状态，不下单。
          请求不带模拟盘标记。必须设置 OKX_LIVE=1 才会连接账户，再设置 OKX_ARM=1 才会开第一笔。
          K 线是 5 分钟，窗口固定 32 根，也就是 2 小时 40 分。净目标 2%，手续费按 0.02% 计算卖价。
          第一笔本金只用 10,000 USDT。平仓后这笔账上的余额才是下一笔本金。
        </p>
        {error && <p className="warning">{error}</p>}
        {book?.last_error && <p className="warning">{book.last_error}</p>}
        <p className={book?.running ? "demo-live" : "warning"}>
          {book ? book.phase_text : "正在读取实盘状态。"}
        </p>
        <div className="stats">
          <div className="stat"><span>状态</span><strong>{book?.running ? "运行中" : "未运行"}</strong></div>
          <div className="stat"><span>账户权益</span><strong>{book?.equity == null ? "—" : money(book.equity)}</strong></div>
          <div className="stat"><span>本笔本金</span><strong>{book?.book_equity == null ? "—" : money(book.book_equity)}</strong></div>
          <div className="stat"><span>最新价</span><strong>{price(book?.last_price)}</strong></div>
        </div>
        <div className="facts">
          <div><span>合约</span><strong>{book?.inst_id || "NEAR-USDT-SWAP"}</strong></div>
          <div><span>K 线</span><strong>5 分钟</strong></div>
          <div><span>净目标</span><strong>2%</strong></div>
          <div><span>环境</span><strong>实盘</strong></div>
          <div><span>电报</span><strong>{book?.telegram ? "已接入" : "未配置"}</strong></div>
          <div><span>杠杆</span><strong>1 倍全仓 · 只做多</strong></div>
          <div><span>限价买价</span><strong>{price(book?.limit_price)}</strong></div>
          <div><span>下一钟点</span><strong>{when(book?.scheduled)}</strong></div>
          <div><span>窗口起点</span><strong>{when(book?.secretary_start)}</strong></div>
          <div><span>样本最低开盘</span><strong>{price(book?.sample_min)}</strong></div>
          <div><span>心跳</span><strong>{when(book?.heartbeat)}</strong></div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>当前仓位</h2>
        </div>
        {position ? (
          <div className="stats">
            <div className="stat"><span>张数</span><strong>{position.contracts}</strong></div>
            <div className="stat"><span>开仓价</span><strong>{price(position.entry)}</strong></div>
            <div className="stat"><span>卖价</span><strong>{price(position.target)}</strong></div>
            <div className="stat"><span>未实现</span><strong className={tone(position.upl)}>{position.upl == null ? "—" : signedMoney(position.upl)}</strong></div>
          </div>
        ) : <p className="note">当前没有持仓。</p>}
        {order && (
          <p className="note">
            委托 {order.side === "sell" ? "卖出" : "买入"} {order.sz} 张
            {order.px ? ` @ ${order.px}` : " 市价"} · {order.state || "live"}
          </p>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>已平仓</h2>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>结果</th>
                <th>开仓</th>
                <th>开仓价</th>
                <th>平仓价</th>
                <th>平仓前权益</th>
                <th>平仓后权益</th>
              </tr>
            </thead>
            <tbody>
              {(book?.cycles || []).length === 0 && (
                <tr><td colSpan={6}>还没有完成的交易。</td></tr>
              )}
              {(book?.cycles || []).map((cycle) => (
                <tr key={`${cycle.entry_ts}-${cycle.exit_ts}`}>
                  <td>{cycle.status === "target" ? "卖出" : "强平"}</td>
                  <td>{when(cycle.entry_ts)}</td>
                  <td>{price(cycle.entry)}</td>
                  <td>{price(cycle.exit)}</td>
                  <td>{cycle.equity_before == null ? "—" : money(cycle.equity_before)}</td>
                  <td>{cycle.equity_after == null ? "—" : money(cycle.equity_after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="footnote">{book?.note}</p>
      </section>
    </main>
  );
}
