import { compoundText, money } from "../format";
import { heatStyle } from "../spectrum";

function mean(numbers) {
  return numbers.reduce((sum, value) => sum + value, 0) / numbers.length;
}

function Cell({ value, low, high, current, meanCell, title }) {
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

export default function HeatGrid({ grid, applied }) {
  if (!grid) return null;
  const flat = grid.values.flat();
  const low = Math.min(...flat);
  const high = Math.max(...flat);
  const columnMeans = grid.targets.map((_, columnIndex) => mean(grid.values.map((row) => row[columnIndex])));
  const grand = mean(flat);
  const sameBook = applied
    && applied.initial_equity === grid.equity
    && Math.abs(applied.fee_rate - grid.fee_rate) < 1e-12
    && applied.start === grid.start;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>已完成复利</h2>
        <p>横轴是单周期净目标，从 1% 到 50%，每档 1%。纵轴是北京时间进场钟点。数字是 {grid.coin || "NEAR"}-USDT 永续的已完成复利，单位 USDT，按起点 2026-03-13、起始资金 10,000、挂单费率 0.02% 事先算好。没有记录的资金费按 0.01%。最右一列是这个钟点在各净目标上的均值，最下一行是这个净目标在各钟点上的均值，右下角是全部格子的均值。</p>
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
              const row = grid.values[rowIndex];
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
