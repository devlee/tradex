import { useEffect, useState } from "react";
import { hold } from "../format";
import { heatStyle } from "../spectrum";

const SWAP_NOTE = "这张表是 NEAR-USDT 永续。第一笔仍是 2026-03-13 北京时间 0 点的开盘价。之后一笔结束就在该笔买价挂限价单，价格回到这个买价或更低就成交。到平仓日之后第 2 个北京日还没成交，就把当天 96 根 15 分钟线的开盘价按秘书问题处理：前 35 根只记最低价，不买；之后第一根开盘价低于这个最低价就买入；直到最后一根还没有，就买最后一根。限价单在这一天仍然有效。起始资金 10,000、挂单费率 0.02%，没有记录的资金费按 0.01%。净目标从 1% 到 100%，每档 1%。限价买、秘书买、末根买都不含第一笔。";
const SPOT_NOTE = "这张表是 NEAR-USDT 现货，进场和卖出规则与上面相同。用现货 15 分钟线，从 2026-03-13 北京时间 0 点起。起始资金 10,000，挂单费率 0.08%。买入的是现货，没有资金费，也不会强平。净目标从 1% 到 100%，每档 1%。";

function idealSells(equity, target, sells, times) {
  return equity * (1 + target) ** (sells * times);
}

function whole(value) {
  return Math.round(Number(value)).toLocaleString("zh-CN");
}

function signedWhole(value) {
  const number = Number(value);
  const text = whole(Math.abs(number));
  if (number > 0) return `+${text}`;
  if (number < 0) return `−${text}`;
  return text;
}

function pctWhole(value) {
  const number = Number(value) * 100;
  const text = `${Math.round(Math.abs(number))}%`;
  if (number > 0) return `+${text}`;
  if (number < 0) return `−${text}`;
  return text;
}

export function ResultTable({ rows, equity }) {
  const compounds = rows.map((row) => row.compounded);
  const doubled = rows.map((row) => idealSells(equity, row.target, row.sells, 2));
  const tripled = rows.map((row) => idealSells(equity, row.target, row.sells, 3));
  const quadrupled = rows.map((row) => idealSells(equity, row.target, row.sells, 4));
  const low = Math.min(...compounds);
  const high = Math.max(...compounds);
  const doubleLow = Math.min(...doubled);
  const doubleHigh = Math.max(...doubled);
  const tripleLow = Math.min(...tripled);
  const tripleHigh = Math.max(...tripled);
  const quadrupleLow = Math.min(...quadrupled);
  const quadrupleHigh = Math.max(...quadrupled);
  return (
    <div className="table-wrap">
      <table className="secretary">
        <thead>
          <tr>
            <th>净目标</th>
            <th>已完成复利</th>
            <th>市值权益</th>
            <th>卖出</th>
            <th title="卖出次数翻倍，且每笔刚好达到净目标时的已完成复利">卖出2</th>
            <th title="卖出次数变为 3 倍，且每笔刚好达到净目标时的已完成复利">卖出3</th>
            <th title="卖出次数变为 4 倍，且每笔刚好达到净目标时的已完成复利">卖出4</th>
            <th>限价买</th>
            <th>秘书买</th>
            <th>末根买</th>
            <th>最长持仓</th>
            <th>最大回撤</th>
            <th>手续费</th>
            <th>资金费</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.target}>
              <td>{Math.round(row.target * 100)}%</td>
              <td className="heat-cell" style={heatStyle(row.compounded, low, high)} title={`${whole(row.compounded)} USDT`}>
                {whole(row.compounded)}
              </td>
              <td>{whole(row.mark)}</td>
              <td>{row.sells}</td>
              <td className="heat-cell" style={heatStyle(doubled[index], doubleLow, doubleHigh)} title={`${whole(doubled[index])} USDT`}>
                {whole(doubled[index])}
              </td>
              <td className="heat-cell" style={heatStyle(tripled[index], tripleLow, tripleHigh)} title={`${whole(tripled[index])} USDT`}>
                {whole(tripled[index])}
              </td>
              <td className="heat-cell" style={heatStyle(quadrupled[index], quadrupleLow, quadrupleHigh)} title={`${whole(quadrupled[index])} USDT`}>
                {whole(quadrupled[index])}
              </td>
              <td>{row.limit_entries}</td>
              <td>{row.secretary_entries}</td>
              <td>{row.last_entries}</td>
              <td>{hold(row.longest_hours)}</td>
              <td>{pctWhole(-row.max_drawdown)}</td>
              <td>{whole(row.fees)}</td>
              <td>{signedWhole(row.funding)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function SecretaryPage() {
  const [book, setBook] = useState(null);
  const [spot, setSpot] = useState(null);
  const [error, setError] = useState("");
  const [spotError, setSpotError] = useState("");

  useEffect(() => {
    fetch("/secretary.json")
      .then((response) => {
        if (!response.ok) throw new Error("永续表没有读到");
        return response.json();
      })
      .then(setBook)
      .catch((reason) => setError(reason.message || "永续表没有读到"));
    fetch("/secretary-spot.json")
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
        <h1>秘书问题进场</h1>
        <p className="lede">周期结束后先在上一笔买价挂限价单。到平仓日之后第 2 个北京日还没买到，就用秘书问题在当天的 15 分钟开盘价里选一个更低的买点。下面两张表用同一套买卖规则，一张是永续，一张是现货。</p>
        <ol className="rules">
          <li>第一笔用起点日期北京时间 0 点那根 15 分钟 K 线的开盘价。</li>
          <li>卖出规则与钟点进场相同：净赚到目标才卖，下跌不卖，卖完的余额是下一笔本金。</li>
          <li>一笔结束后立刻挂限价买单，价格是这张周期的买价。之后价格小于或等于这个买价就成交。</li>
          <li>平仓当天和后一天只等这张限价单。同一根 K 线不既卖又买。</li>
          <li>第 2 个北京日仍未成交时，前 35 根开盘价只作为样本。之后第一根低于样本最低价的开盘价买入。</li>
          <li>当天直到最后一根都没有更低的开盘价，就按最后一根的开盘价买入。限价单在这一天仍然优先。</li>
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
