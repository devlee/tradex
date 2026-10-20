import { useEffect, useState } from "react";
import { ResultTable } from "./SecretaryPage";
import { bookUrl, useCoin } from "../coin";

const SWAP_NOTE = "这张表是 NEAR-USDT 永续。规则与秘书问题2相同，但平仓后不再等到第 2 个北京日。关单那根不再买入，从下一根起到当天晚 8 点做秘书选择；平仓早于早 8 点，就从当天早 8 点起。这段少于 10 根，或平仓时已经过了晚 8 点，就改到下一个北京日的早 8 点到晚 8 点。晚 8 点那根仍是末根。上一笔买价的限价单全天有效。起始资金 10,000、挂单费率 0.02%，没有记录的资金费按 0.01%。净目标从 1% 到 100%，每档 1%。";
const SPOT_NOTE = "这张表是 NEAR-USDT 现货，进场时段与上面相同。起始资金 10,000，挂单费率 0.08%。买入的是现货，没有资金费，也不会强平。净目标从 1% 到 100%，每档 1%。";

export default function Secretary3Page() {
  const { coin } = useCoin();
  const [book, setBook] = useState(null);
  const [spot, setSpot] = useState(null);
  const [error, setError] = useState("");
  const [spotError, setSpotError] = useState("");

  useEffect(() => {
    setBook(null);
    setSpot(null);
    setError("");
    setSpotError("");
    fetch(bookUrl(coin, "secretary3.json"))
      .then((response) => {
        if (!response.ok) throw new Error("永续表没有读到");
        return response.json();
      })
      .then(setBook)
      .catch((reason) => setError(reason.message || "永续表没有读到"));
    fetch(bookUrl(coin, "secretary3-spot.json"))
      .then((response) => {
        if (!response.ok) throw new Error("现货表没有读到");
        return response.json();
      })
      .then(setSpot)
      .catch((reason) => setSpotError(reason.message || "现货表没有读到"));
  }, [coin]);

  const swapNote = SWAP_NOTE.replaceAll("NEAR", coin);
  const spotNote = SPOT_NOTE.replaceAll("NEAR", coin);

  return (
    <div className="layout">
      <aside>
        <h1>秘书问题3</h1>
        <p className="lede">在秘书问题2上，新周期不再等平仓日后的第 2 天。平仓后立刻在当天剩余的早 8 点到晚 8 点里选买点。比如早 8 点开单、早 9 点关单，就从 9:15 这根选到晚 8 点。</p>
        <ol className="rules">
          <li>第一笔用起点日期北京时间 0 点那根 15 分钟 K 线的开盘价。</li>
          <li>卖出规则不变：净赚到目标才卖，下跌不卖，卖完的余额是下一笔本金。</li>
          <li>一笔结束后立刻挂限价买单，价格是这张周期的买价。限价单全天有效，不受早 8 点到晚 8 点限制，并且优先成交。</li>
          <li>关单那根不再买入。下一根如果还在早 8 点到晚 8 点里，就从那里起到晚 8 点做秘书选择。平仓早于早 8 点，则从当天早 8 点起。</li>
          <li>这段候选 K 线少于 10 根，或者平仓时已经过了晚 8 点，当天不再做秘书选择，改到下一个北京日的早 8 点到晚 8 点。</li>
          <li>观察根数按这段候选根数的 1/e。之后第一根开盘价低于样本最低价就买入。晚 8 点那根是末根，还没买到就按它的开盘价成交。</li>
          <li>现货按 {coin}-USDT 的价格买入并持有，挂单费率 0.08%，没有资金费，也不会强平。</li>
        </ol>
      </aside>
      <main>
        <section className="panel">
          <div className="panel-head">
            <h2>永续合约</h2>
            <p>{error || swapNote}</p>
          </div>
          {book ? <ResultTable rows={book.rows} equity={book.equity} /> : null}
        </section>
        <section className="panel">
          <div className="panel-head">
            <h2>现货</h2>
            <p>{spotError || spotNote}</p>
          </div>
          {spot ? <ResultTable rows={spot.rows} equity={spot.equity} /> : null}
        </section>
      </main>
    </div>
  );
}
