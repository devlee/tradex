import { useEffect, useState } from "react";
import { ResultTable } from "./SecretaryPage";
import { bookUrl, useCoin } from "../coin";

const ADDON_NOTE = "表格每一行是仓位1。点开这一行，可以看到同一净目标下后来开出的仓位，以及这一仓建立时第一笔的开仓价。最后一行是总仓位，把这一净目标下各仓的数字加在一起。下跌只按仓位1当时那笔的开仓价计算，每再跌 10% 用 10,000 USDT 新开一仓，最多到跌 90%。新仓再被套不再加仓。";
const SWAP_NOTE = `这张表是 NEAR-USDT 永续。规则与秘书问题2相同，但平仓后不再等到第 2 个北京日。关单那根不再买入，从下一根起到当天晚 8 点做秘书选择；平仓早于早 8 点，就从当天早 8 点起。这段少于 10 根，或平仓时已经过了晚 8 点，就改到下一个北京日的早 8 点到晚 8 点。晚 8 点那根仍是末根。上一笔买价的限价单全天有效。每个仓位起始资金 10,000、挂单费率 0.02%，没有记录的资金费按 0.01%。净目标从 1% 到 50%，每档 1%。${ADDON_NOTE}`;
export default function Secretary3Page() {
  const { coin } = useCoin();
  const [book, setBook] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setBook(null);
    setError("");
    fetch(bookUrl(coin, "secretary3.json"))
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
        <h1>秘书问题3</h1>
        <p className="lede">在秘书问题2上，新周期不再等平仓日后的第 2 天。平仓后立刻在当天剩余的早 8 点到晚 8 点里选买点。比如早 8 点开单、早 9 点关单，就从 9:15 这根选到晚 8 点。</p>
        <ol className="rules">
          <li>第一笔用起点日期北京时间 0 点那根 15 分钟 K 线的开盘价。</li>
          <li>卖出规则不变：净赚到目标才卖，下跌不卖，卖完的余额是下一笔本金。</li>
          <li>一笔结束后立刻挂限价买单，价格是这张周期的买价。限价单全天有效，不受早 8 点到晚 8 点限制，并且优先成交。</li>
          <li>关单那根不再买入。下一根如果还在早 8 点到晚 8 点里，就从那里起到晚 8 点做秘书选择。平仓早于早 8 点，则从当天早 8 点起。</li>
          <li>这段候选 K 线少于 10 根，或者平仓时已经过了晚 8 点，当天不再做秘书选择，改到下一个北京日的早 8 点到晚 8 点。</li>
          <li>观察根数按这段候选根数的 1/e。之后第一根开盘价低于样本最低价就买入。晚 8 点那根是末根，还没买到就按它的开盘价成交。</li>
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
