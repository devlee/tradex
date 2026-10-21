import { Fragment, useEffect, useState } from "react";
import { hold, priceOf } from "../format";
import { heatStyle } from "../spectrum";
import { bookUrl, useCoin } from "../coin";

const ADDON_NOTE = "表格每一行是仓位1。点开这一行，可以看到同一净目标下后来开出的仓位，以及这一仓建立时第一笔的开仓价。最后一行是总仓位，把这一净目标下各仓的数字加在一起。下跌只按仓位1当时那笔的开仓价计算，每再跌 10% 用 10,000 USDT 新开一仓，最多到跌 90%。新仓再被套不再加仓。";
const SWAP_NOTE = `这张表是 NEAR-USDT 永续。第一笔仍是 2026-03-13 北京时间 0 点的开盘价。之后一笔结束就在该笔买价挂限价单，价格回到这个买价或更低就成交。到平仓日之后第 2 个北京日还没成交，就把当天 96 根 15 分钟线的开盘价按秘书问题处理：前 35 根只记最低价，不买；之后第一根开盘价低于这个最低价就买入；直到最后一根还没有，就买最后一根。限价单在这一天仍然有效。每个仓位起始资金 10,000、挂单费率 0.02%，没有记录的资金费按 0.01%。净目标从 1% 到 50%，每档 1%。限价买、秘书买、末根买都不含第一笔。${ADDON_NOTE}`;
function idealSells(equity, target, sells, times) {
  return equity * (1 + target) ** (sells * times);
}

function mean(numbers) {
  const usable = numbers.filter((value) => value != null && Number.isFinite(value));
  if (!usable.length) return null;
  return usable.reduce((sum, value) => sum + value, 0) / usable.length;
}

const PRICE_TICK = { NEAR: 0.001, PUMP: 0.000001, HYPE: 0.001 };

function booksOf(row) {
  if (row.books?.length) return row.books;
  return [row];
}

function idealsOf(item, equity, fallbackTarget) {
  if (!item || item.sells == null) return [null, null, null];
  const target = item.target ?? fallbackTarget;
  return [2, 3, 4].map((times) => idealSells(equity, target, item.sells, times));
}

function summedIdeals(books, equity, fallbackTarget) {
  const parts = books.map((item) => idealsOf(item, equity, fallbackTarget));
  return [0, 1, 2].map((slot) => {
    const numbers = parts.map((item) => item[slot]).filter((value) => value != null && Number.isFinite(value));
    if (!numbers.length) return null;
    return numbers.reduce((sum, value) => sum + value, 0);
  });
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

function scale(numbers) {
  const usable = numbers.filter((value) => value != null && Number.isFinite(value));
  if (!usable.length) return [0, 0];
  return [Math.min(...usable), Math.max(...usable)];
}

function heatCell(value, low, high) {
  if (value == null || !Number.isFinite(value)) return <td>—</td>;
  return (
    <td className="heat-cell" style={heatStyle(value, low, high)} title={`${whole(value)} USDT`}>
      {whole(value)}
    </td>
  );
}

function plain(value, format) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return format(value);
}

function statCells(view, doubled, tripled, quadrupled, low, high, doubleLow, doubleHigh, tripleLow, tripleHigh, quadrupleLow, quadrupleHigh, heated = true) {
  const money = (value, scaleLow, scaleHigh) => (
    heated ? heatCell(value, scaleLow, scaleHigh) : <td>{plain(value, whole)}</td>
  );
  return (
    <>
      {money(view?.compounded, low, high)}
      <td>{plain(view?.mark, whole)}</td>
      <td>{view ? view.sells : "—"}</td>
      {money(doubled, doubleLow, doubleHigh)}
      {money(tripled, tripleLow, tripleHigh)}
      {money(quadrupled, quadrupleLow, quadrupleHigh)}
      <td>{view ? view.limit_entries : "—"}</td>
      <td>{view ? view.secretary_entries : "—"}</td>
      <td>{view ? view.last_entries : "—"}</td>
      <td>{view ? hold(view.longest_hours) : "—"}</td>
      <td>{view ? pctWhole(-view.max_drawdown) : "—"}</td>
      <td>{plain(view?.fees, whole)}</td>
      <td>{view ? signedWhole(view.funding) : "—"}</td>
    </>
  );
}

export function ResultTable({ rows, equity }) {
  const { coin } = useCoin();
  const tick = PRICE_TICK[coin] || 0.001;
  const [open, setOpen] = useState(() => new Set());
  const views = rows.map((row) => booksOf(row)[0]);
  const idealRows = views.map((view, index) => idealsOf(view, equity, rows[index].target));
  const compounds = views.map((row) => row?.compounded ?? null);
  const doubled = idealRows.map((item) => item[0]);
  const tripled = idealRows.map((item) => item[1]);
  const quadrupled = idealRows.map((item) => item[2]);
  const [low, high] = scale(compounds);
  const [doubleLow, doubleHigh] = scale(doubled);
  const [tripleLow, tripleHigh] = scale(tripled);
  const [quadrupleLow, quadrupleHigh] = scale(quadrupled);
  const meanCompound = mean(compounds);
  const meanDouble = mean(doubled);
  const meanTriple = mean(tripled);
  const meanQuadruple = mean(quadrupled);
  const meanMark = mean(views.map((row) => row?.mark ?? null));
  const meanSells = mean(views.map((row) => row?.sells ?? null));
  const meanLimit = mean(views.map((row) => row?.limit_entries ?? null));
  const meanSecretary = mean(views.map((row) => row?.secretary_entries ?? null));
  const meanLast = mean(views.map((row) => row?.last_entries ?? null));
  const meanHold = mean(views.map((row) => row?.longest_hours ?? null));
  const meanDrawdown = mean(views.map((row) => row?.max_drawdown ?? null));
  const meanFees = mean(views.map((row) => row?.fees ?? null));
  const meanFunding = mean(views.map((row) => row?.funding ?? null));
  const idealTitle = "按这一仓的卖出次数计算";

  function toggle(target) {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(target)) next.delete(target);
      else next.add(target);
      return next;
    });
  }

  return (
    <div className="table-wrap">
      <table className="secretary">
        <thead>
          <tr>
            <th>净目标</th>
            <th>仓位</th>
            <th title="这一仓建立时第一笔的开仓价。仓位2及以后按仓位1当时那笔开仓价的下跌计算。">开仓价</th>
            <th>已完成复利</th>
            <th>市值权益</th>
            <th>卖出</th>
            <th title={`${idealTitle}。卖出次数翻倍，且每笔刚好达到净目标。`}>卖出2</th>
            <th title={`${idealTitle}。卖出次数变为 3 倍，且每笔刚好达到净目标。`}>卖出3</th>
            <th title={`${idealTitle}。卖出次数变为 4 倍，且每笔刚好达到净目标。`}>卖出4</th>
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
          <tr className="mean">
            <td>均值</td>
            <td>—</td>
            <td>—</td>
            {heatCell(meanCompound, low, high)}
            <td>{plain(meanMark, whole)}</td>
            <td>{plain(meanSells, whole)}</td>
            {heatCell(meanDouble, doubleLow, doubleHigh)}
            {heatCell(meanTriple, tripleLow, tripleHigh)}
            {heatCell(meanQuadruple, quadrupleLow, quadrupleHigh)}
            <td>{plain(meanLimit, whole)}</td>
            <td>{plain(meanSecretary, whole)}</td>
            <td>{plain(meanLast, whole)}</td>
            <td>{plain(meanHold, hold)}</td>
            <td>{meanDrawdown == null ? "—" : pctWhole(-meanDrawdown)}</td>
            <td>{plain(meanFees, whole)}</td>
            <td>{meanFunding == null ? "—" : signedWhole(meanFunding)}</td>
          </tr>
          {rows.map((row, index) => {
            const view = views[index];
            const extra = booksOf(row).slice(1);
            const expanded = open.has(row.target);
            const [double, triple, quadruple] = idealRows[index];
            return (
              <Fragment key={row.target}>
                <tr
                  className={extra.length ? "foldable" : undefined}
                  aria-expanded={extra.length ? expanded : undefined}
                  tabIndex={extra.length ? 0 : undefined}
                  onClick={extra.length ? () => toggle(row.target) : undefined}
                  onKeyDown={extra.length ? (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      toggle(row.target);
                    }
                  } : undefined}
                >
                  <td>
                    <span className="fold-mark" aria-hidden="true">{extra.length ? (expanded ? "▾" : "▸") : ""}</span>
                    {Math.round(row.target * 100)}%
                  </td>
                  <td>仓位1</td>
                  <td>{view?.entry == null ? "—" : priceOf(view.entry, tick)}</td>
                  {statCells(view, double, triple, quadruple, low, high, doubleLow, doubleHigh, tripleLow, tripleHigh, quadrupleLow, quadrupleHigh)}
                </tr>
                {expanded ? extra.map((item, extraIndex) => {
                  const [childDouble, childTriple, childQuadruple] = idealsOf(item, equity, row.target);
                  return (
                    <tr className="fold-row" key={`${row.target}-${extraIndex + 2}`}>
                      <td />
                      <td>{`仓位${extraIndex + 2}`}</td>
                      <td>{item?.entry == null ? "—" : priceOf(item.entry, tick)}</td>
                      {statCells(item, childDouble, childTriple, childQuadruple, low, high, doubleLow, doubleHigh, tripleLow, tripleHigh, quadrupleLow, quadrupleHigh)}
                    </tr>
                  );
                }) : null}
                {expanded && row.total ? (() => {
                  const [totalDouble, totalTriple, totalQuadruple] = summedIdeals(booksOf(row), equity, row.target);
                  return (
                    <tr className="fold-row fold-total" key={`${row.target}-total`}>
                      <td />
                      <td>总仓位</td>
                      <td>—</td>
                      {statCells(row.total, totalDouble, totalTriple, totalQuadruple, low, high, doubleLow, doubleHigh, tripleLow, tripleHigh, quadrupleLow, quadrupleHigh, false)}
                    </tr>
                  );
                })() : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function SecretaryPage() {
  const { coin } = useCoin();
  const [book, setBook] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setBook(null);
    setError("");
    fetch(bookUrl(coin, "secretary.json"))
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
        <h1>秘书问题进场</h1>
        <p className="lede">周期结束后先在上一笔买价挂限价单。到平仓日之后第 2 个北京日还没买到，就用秘书问题在当天的 15 分钟开盘价里选一个更低的买点。</p>
        <ol className="rules">
          <li>第一笔用起点日期北京时间 0 点那根 15 分钟 K 线的开盘价。</li>
          <li>卖出规则与钟点进场相同：净赚到目标才卖，下跌不卖，卖完的余额是下一笔本金。</li>
          <li>一笔结束后立刻挂限价买单，价格是这张周期的买价。之后价格小于或等于这个买价就成交。</li>
          <li>平仓当天和后一天只等这张限价单。同一根 K 线不既卖又买。</li>
          <li>第 2 个北京日仍未成交时，前 35 根开盘价只作为样本。之后第一根低于样本最低价的开盘价买入。</li>
          <li>当天直到最后一根都没有更低的开盘价，就按最后一根的开盘价买入。限价单在这一天仍然优先。</li>
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
