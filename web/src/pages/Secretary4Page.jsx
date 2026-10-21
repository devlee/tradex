import { useEffect, useState } from "react";
import { ResultTable } from "./SecretaryPage";
import { bookUrl, useCoin } from "../coin";

const ADDON_NOTE = "表格每一行是仓位1。点开这一行，可以看到同一净目标下后来开出的仓位，以及这一仓建立时第一笔的开仓价。最后一行是总仓位，把这一净目标下各仓的数字加在一起。下跌只按仓位1当时那笔的开仓价计算，每再跌 10% 用 10,000 USDT 新开一仓，最多到跌 90%。新仓再被套不再加仓。";
const SWAP_NOTE = `这张表是 NEAR-USDT 永续。规则与秘书问题3相同，但秘书选点改成平仓后的 32 根 K 线。关单那根不再买入，从下一根 15 分钟 K 线起一共 32 根，可以跨过午夜。这 32 根在 15 分钟线下是 8 小时。前 12 根只记最低开盘价，之后第一根更低的开盘价买入。第 32 根是末根，它的开盘在起点之后 7 小时 45 分，收盘刚好满 8 小时，还没买到就按它的开盘价成交。上一笔买价的限价单在这 32 根里仍然优先。每个仓位起始资金 10,000、挂单费率 0.02%，没有记录的资金费按 0.01%。净目标从 1% 到 50%，每档 1%。${ADDON_NOTE}`;
export default function Secretary4Page() {
  const { coin } = useCoin();
  const [book, setBook] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setBook(null);
    setError("");
    fetch(bookUrl(coin, "secretary4.json"))
      .then((response) => {
        if (!response.ok) throw new Error("永续表没有读到");
        return response.json();
      })
      .then(setBook)
      .catch((reason) => setError(reason.message || "永续表没有读到"));
  }, [coin]);

  const swapNote = SWAP_NOTE.replaceAll("NEAR", coin);

  return (
    <div className="layout">
      <aside>
        <h1>秘书问题4</h1>
        <p className="lede">在秘书问题3上，秘书进场不再卡在当天早 8 点到晚 8 点。每个周期结束后，从下一根 K 线起固定看 32 根。15 分钟线下这 32 根是 8 小时，可以跨过午夜。</p>
        <ol className="rules">
          <li>第一笔用起点日期北京时间 0 点那根 15 分钟 K 线的开盘价。</li>
          <li>卖出规则不变：净赚到目标才卖，下跌不卖，卖完的余额是下一笔本金。</li>
          <li>一笔结束后立刻挂限价买单，价格是这张周期的买价。限价单优先于秘书选点，观察的那 12 根里碰到买价也成交。</li>
          <li>关单那根不再买入。下一根是第一根，往后固定 32 根，根数不随 K 线周期改变。</li>
          <li>前 12 根只记最低开盘价。这个 12 是 32 根按 1/e 取整。之后第一根开盘价低于样本最低价就买入。</li>
          <li>第 32 根是末根。15 分钟线下，它的开盘在起点之后 7 小时 45 分，收盘刚好满 8 小时。到这里还没买到，就按这根的开盘价买入。</li>
          <li>仓位1的持仓价相对开仓价每再跌 10%，就用最初的 10,000 USDT 新开一个独立仓位。新仓不并进被套的那一笔，之后自己复利。新仓再被套不再加仓。</li>
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
      </main>
    </div>
  );
}
