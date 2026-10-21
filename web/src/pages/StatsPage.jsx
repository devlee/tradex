import { useEffect, useState } from "react";
import SellChart from "../components/SellChart";
import SellTable from "../components/SellTable";
import { bookUrl, useCoin } from "../coin";

const SPANS = [
  { id: "15m", name: "15分钟" },
  { id: "5m", name: "5分钟" },
];

export default function StatsPage() {
  const { coin } = useCoin();
  const [book, setBook] = useState(null);
  const [error, setError] = useState("");
  const [span, setSpan] = useState("15m");

  useEffect(() => {
    setBook(null);
    setError("");
    fetch(bookUrl(coin, "stats.json"))
      .then((response) => {
        if (!response.ok) throw new Error("统计没有读到");
        return response.json();
      })
      .then(setBook)
      .catch((reason) => setError(reason.message || "统计没有读到"));
  }, [coin]);

  const shown = book?.coin === coin ? book.series.filter((item) => item.span === span) : [];

  return (
    <div className="layout">
      <aside>
        <h1>统计</h1>
        <p className="lede">
          横轴是净目标，从 1% 到 50%。纵轴是该净目标下仓位1已经按目标卖出的次数。每条线是一种策略。K 线在 15 分钟和 5 分钟之间切换，图和表一起换。
        </p>
        <ol className="rules">
          <li>五种策略各一条线。切换 K 线只换事先算好的结果，页面不再重算。</li>
          <li>钟点进场这一条用北京时间 0 点。第一笔是 2026-03-13 当天 0 点那根 K 线的开盘价。5 分钟用 0 点那根 5 分钟线，15 分钟用 0 点那根 15 分钟线。</li>
          <li>15 分钟这一档的卖出次数，与各策略页表格里仓位1的「卖出」相同。秘书问题4固定 32 根：15 分钟是 8 小时，5 分钟是 2 小时 40 分。其余策略的时间区间不变。起始资金 10,000 USDT，永续挂单费率 0.02%。</li>
          <li>右上角切换币种，这张图换成该币种的同一套统计。点图例可以单独隐藏一条线。</li>
          <li>表格在每种策略下给出卖出次数，以及复利值。复利值是 (1 + 净目标) 的卖出次数次方。1% 卖出 10 次就是 1.01 的 10 次方。底色按这一列自己的最低到最高，从紫到红。</li>
        </ol>
      </aside>
      <main>
        <section className="panel">
          <div className="panel-head">
            <h2>卖出次数</h2>
            <div className="span-switch">
              <label>
                K线
                <select value={span} onChange={(event) => setSpan(event.target.value)}>
                  {SPANS.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </label>
              <p>{coin}-USDT 永续 · 仓位1 · {SPANS.find((item) => item.id === span).name}</p>
            </div>
          </div>
          {error && <p className="warning">{error}</p>}
          {book?.coin !== coin && !error && <p className="status">正在读取统计。</p>}
          {book?.coin === coin && shown.length > 0 && (
            <SellChart key={`${coin}-${span}`} targets={book.targets} series={shown} />
          )}
          {book?.coin === coin && shown.length === 0 && <p className="warning">这一档 K 线还没有离线结果。</p>}
        </section>
        {book?.coin === coin && shown.length > 0 && (
          <section className="panel">
            <div className="panel-head">
              <h2>复利值</h2>
              <p>(1 + 净目标) 的卖出次数次方。每种策略的复利列按自己的最小和最大上色。</p>
            </div>
            <SellTable targets={book.targets} series={shown} />
          </section>
        )}
      </main>
    </div>
  );
}
