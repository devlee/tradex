import { useEffect, useState } from "react";
import { hold, money, pct, signedMoney } from "../format";
import { heatStyle } from "../spectrum";

const NOTE = "第一笔仍是 2026-03-13 北京时间 0 点的开盘价。之后一笔结束就在该笔买价挂限价单，价格回到这个买价或更低就成交。到平仓日之后第 2 个北京日还没成交，就把当天 96 根 15 分钟线的开盘价按秘书问题处理：前 35 根只记最低价，不买；之后第一根开盘价低于这个最低价就买入；直到最后一根还没有，就买最后一根。限价单在这一天仍然有效。表内是起始资金 10,000、挂单费率 0.02%、缺记录资金费按 0.01% 事先算好的结果。限价买、秘书买、末根买都不含第一笔。";

export default function SecretaryPage() {
  const [book, setBook] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/secretary.json")
      .then((response) => {
        if (!response.ok) throw new Error("秘书问题表没有读到");
        return response.json();
      })
      .then(setBook)
      .catch((reason) => setError(reason.message || "秘书问题表没有读到"));
  }, []);

  const compounds = book?.rows.map((row) => row.compounded) || [];
  const low = compounds.length ? Math.min(...compounds) : 0;
  const high = compounds.length ? Math.max(...compounds) : 1;

  return (
    <div className="layout">
      <aside>
        <h1>秘书问题进场</h1>
        <p className="lede">周期结束后先在上一笔买价挂限价单。到平仓日之后第 2 个北京日还没买到，就用秘书问题在当天的 15 分钟开盘价里选一个更低的买点。</p>
        <ol className="rules">
          <li>第一笔用起点日期北京时间 0 点那根 15 分钟 K 线的开盘价。</li>
          <li>卖出规则与钟点进场相同：净赚到目标才卖，下跌不卖，卖完的余额是下一笔本金。</li>
          <li>一笔结束后立刻挂限价买单，价格是这张周期的买价。之后价格小于或等于这个买价就成交。</li>
          <li>平仓当天和后一天只等这张限价单。同一根 K 线不既卖又买。</li>
          <li>第 2 个北京日仍未成交时，前 35 根开盘价只作为样本。之后第一根低于样本最低价的开盘价买入。</li>
          <li>当天直到最后一根都没有更低的开盘价，就按最后一根的开盘价买入。限价单在这一天仍然优先。</li>
        </ol>
      </aside>
      <main>
        <section className="panel">
          <div className="panel-head">
            <h2>回测结果</h2>
            <p>{error || NOTE}</p>
          </div>
          <div className="table-wrap">
            <table className="secretary">
              <thead>
                <tr>
                  <th>净目标</th>
                  <th>已完成复利</th>
                  <th>市值权益</th>
                  <th>卖出</th>
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
                {book?.rows.map((row) => (
                  <tr key={row.target}>
                    <td>{Math.round(row.target * 100)}%</td>
                    <td className="heat-cell" style={heatStyle(row.compounded, low, high)} title={`${money(row.compounded)} USDT`}>
                      {money(row.compounded)}
                    </td>
                    <td>{money(row.mark)}</td>
                    <td>{row.sells}</td>
                    <td>{row.limit_entries}</td>
                    <td>{row.secretary_entries}</td>
                    <td>{row.last_entries}</td>
                    <td>{hold(row.longest_hours)}</td>
                    <td>{pct(-row.max_drawdown)}</td>
                    <td>{money(row.fees)}</td>
                    <td>{signedMoney(row.funding)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
