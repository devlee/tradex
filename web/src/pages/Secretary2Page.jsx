import { useEffect, useState } from "react";
import { ResultTable } from "./SecretaryPage";

const SWAP_NOTE = "这张表是 NEAR-USDT 永续。规则与秘书问题相同，但第 2 个北京日的秘书选点只看早 8 点到晚 8 点的 49 根 15 分钟线：前 18 根只记最低开盘价，之后第一根更低的开盘价买入；晚 8 点那根是末根，还没买到就按它的开盘价成交。上一笔买价的限价单全天有效，不受这个时段限制。起始资金 10,000、挂单费率 0.02%，没有记录的资金费按 0.01%。净目标从 1% 到 100%，每档 1%。";
const SPOT_NOTE = "这张表是 NEAR-USDT 现货，进场时段与上面相同。起始资金 10,000，挂单费率 0.08%。买入的是现货，没有资金费，也不会强平。净目标从 1% 到 100%，每档 1%。";

export default function Secretary2Page() {
  const [book, setBook] = useState(null);
  const [spot, setSpot] = useState(null);
  const [error, setError] = useState("");
  const [spotError, setSpotError] = useState("");

  useEffect(() => {
    fetch("/secretary2.json")
      .then((response) => {
        if (!response.ok) throw new Error("永续表没有读到");
        return response.json();
      })
      .then(setBook)
      .catch((reason) => setError(reason.message || "永续表没有读到"));
    fetch("/secretary2-spot.json")
      .then((response) => {
        if (!response.ok) throw new Error("现货表没有读到");
        return response.json();
      })
      .then(setSpot)
      .catch((reason) => setSpotError(reason.message || "现货表没有读到"));
  }, []);

  return (
    <div className="layout">
      <aside>
        <h1>秘书问题2</h1>
        <p className="lede">在秘书问题之上，把选买点的时间收成北京时间早 8 点到晚 8 点。上一笔的限价单全天都能成交。晚 8 点那根 K 线如果还没买到，就按那根成交。</p>
        <ol className="rules">
          <li>第一笔用起点日期北京时间 0 点那根 15 分钟 K 线的开盘价。</li>
          <li>卖出规则不变：净赚到目标才卖，下跌不卖，卖完的余额是下一笔本金。</li>
          <li>一笔结束后立刻挂限价买单，价格是这张周期的买价。这个限价单全天有效，早 8 点之前和晚 8 点之后也能成交。</li>
          <li>到平仓日之后第 2 个北京日，秘书问题只看 8:00 到 20:00 的 49 根 K 线。前 18 根只记最低开盘价。</li>
          <li>18 根之后，第一根开盘价低于样本最低价就买入。限价单在这个时段里仍然优先。</li>
          <li>晚 8 点那根是末根。到这里还没买到，就按这根 K 线的开盘价买入。</li>
          <li>现货按 NEAR-USDT 的价格买入并持有，挂单费率 0.08%，没有资金费，也不会强平。</li>
        </ol>
      </aside>
      <main>
        <section className="panel">
          <div className="panel-head">
            <h2>永续合约</h2>
            <p>{error || SWAP_NOTE}</p>
          </div>
          {book ? <ResultTable rows={book.rows} equity={book.equity} /> : null}
        </section>
        <section className="panel">
          <div className="panel-head">
            <h2>现货</h2>
            <p>{spotError || SPOT_NOTE}</p>
          </div>
          {spot ? <ResultTable rows={spot.rows} equity={spot.equity} /> : null}
        </section>
      </main>
    </div>
  );
}
