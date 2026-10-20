import { compoundText, money } from "../format";
import { heatStyle } from "../spectrum";

function usable(numbers) {
  return numbers.filter((value) => value != null && Number.isFinite(value));
}

function mean(numbers) {
  const values = usable(numbers);
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function matrixFor(grid, book) {
  if (book === "total") return grid.totals || null;
  if (book === 0 || book == null) return grid.values;
  return grid.layers?.[book - 1] || null;
}

function bookLabel(book) {
  if (book === "total") return "总仓位";
  if (book === 0 || book == null) return "仓位1";
  return `仓位${book + 1}`;
}

function Cell({ value, low, high, current, meanCell, title }) {
  if (value == null || !Number.isFinite(value)) {
    return <td className={meanCell ? "mean" : ""}>—</td>;
  }
  return (
    <td
      className={[meanCell ? "mean" : "", current ? "current" : ""].filter(Boolean).join(" ")}
      title={title || `${money(value)} USDT`}
      style={heatStyle(value, low, high)}
    >
      {compoundText(value)}
    </td>
  );
}

export default function HeatGrid({ grid, applied, book = 0 }) {
  if (!grid) return null;
  const matrix = matrixFor(grid, book);
  const label = bookLabel(book);
  if (!matrix) {
    return (
      <section className="panel">
        <div className="panel-head">
          <h2>已完成复利 · {label}</h2>
          <p>这张事先算好的表里还没有{label}。仓位1的持仓价相对开仓价每再跌 10%，才会用 10,000 USDT 新开下一仓。</p>
        </div>
      </section>
    );
  }
  const flat = usable(matrix.flat());
  if (!flat.length) {
    return (
      <section className="panel">
        <div className="panel-head">
          <h2>已完成复利 · {label}</h2>
          <p>这张表里没有开出{label}。</p>
        </div>
      </section>
    );
  }
  const low = Math.min(...flat);
  const high = Math.max(...flat);
  const columnMeans = grid.targets.map((_, columnIndex) => mean(matrix.map((row) => row[columnIndex])));
  const grand = mean(flat);
  const sameBook = applied
    && applied.initial_equity === grid.equity
    && Math.abs(applied.fee_rate - grid.fee_rate) < 1e-12
    && applied.start === grid.start;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>已完成复利 · {label}</h2>
        <p>横轴是单周期净目标，从 1% 到 50%，每档 1%。纵轴是北京时间进场钟点。数字是 {grid.coin || "NEAR"}-USDT 永续{label}的已完成复利，单位 USDT，按起点 2026-03-13、每个仓位起始资金 10,000、挂单费率 0.02% 事先算好。仓位1的持仓价相对开仓价每再跌 10%，就用这 10,000 新开下一仓，最多到跌 90%。没有开出的格子是 —。总仓位是各仓已完成复利相加。没有记录的资金费按 0.01%。最右一列是这个钟点在各净目标上的均值，最下一行是这个净目标在各钟点上的均值，右下角是全部有数字格子的均值。</p>
      </div>
      <div className="table-wrap heat-wrap">
        <table className="heat">
          <thead>
            <tr>
              <th>钟点</th>
              {grid.targets.map((target) => (
                <th key={target}>{Math.round(target * 100)}%</th>
              ))}
              <th className="mean">均值</th>
            </tr>
          </thead>
          <tbody>
            {grid.hours.map((hour, rowIndex) => {
              const row = matrix[rowIndex];
              return (
                <tr key={hour}>
                  <td>{hour} 点</td>
                  {row.map((value, columnIndex) => {
                    const target = grid.targets[columnIndex];
                    const current = sameBook
                      && applied.entry_hour === hour
                      && Math.abs(applied.net_target - target) < 1e-9;
                    return (
                      <Cell
                        key={target}
                        value={value}
                        low={low}
                        high={high}
                        current={current}
                      />
                    );
                  })}
                  <Cell value={mean(row)} low={low} high={high} meanCell />
                </tr>
              );
            })}
            <tr className="mean">
              <td>均值</td>
              {columnMeans.map((value, columnIndex) => (
                <Cell key={grid.targets[columnIndex]} value={value} low={low} high={high} meanCell />
              ))}
              <Cell value={grand} low={low} high={high} meanCell />
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
