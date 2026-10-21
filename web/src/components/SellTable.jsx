import { Fragment } from "react";
import { heatStyle } from "../spectrum";

function seriesKey(item) {
  return `${item.strategy}:${item.span}`;
}

function percentOf(target) {
  return Math.round(target * 100);
}

function compoundValue(sells, target) {
  return (1 + percentOf(target) / 100) ** sells;
}

function whole(value) {
  return Math.round(Number(value)).toLocaleString("zh-CN");
}

function factorText(value) {
  return Number(value).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default function SellTable({ targets, series }) {
  const compounds = series.map((item) => item.sells.map((count, index) => compoundValue(count, targets[index])));
  const scales = compounds.map((column) => [Math.min(...column), Math.max(...column)]);

  return (
    <div className="table-wrap">
      <table className="stats-table">
        <thead>
          <tr>
            <th rowSpan={2}>净目标</th>
            {series.map((item) => (
              <th key={seriesKey(item)} colSpan={2}>{item.name} · {item.span_name}</th>
            ))}
          </tr>
          <tr>
            {series.map((item) => (
              <Fragment key={seriesKey(item)}>
                <th>卖出次数</th>
                <th title="(1 + 净目标) 的卖出次数次方。1% 卖出 10 次就是 1.01 的 10 次方。">复利值</th>
              </Fragment>
            ))}
          </tr>
        </thead>
        <tbody>
          {targets.map((target, index) => (
            <tr key={target}>
              <td>{percentOf(target)}%</td>
              {series.map((item, seriesIndex) => {
                const sells = item.sells[index];
                const compound = compounds[seriesIndex][index];
                const [low, high] = scales[seriesIndex];
                const base = (1 + percentOf(target) / 100).toFixed(2);
                return (
                  <Fragment key={seriesKey(item)}>
                    <td>{whole(sells)}</td>
                    <td
                      className="heat-cell"
                      style={heatStyle(compound, low, high)}
                      title={`${base}^${sells} = ${factorText(compound)}`}
                    >
                      {factorText(compound)}
                    </td>
                  </Fragment>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
