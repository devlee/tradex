import { useMemo, useState } from "react";

const VIEW_W = 900;
const VIEW_H = 420;
const PAD = { l: 72, r: 16, t: 20, b: 46 };

const COLOR = {
  clock: "#e0b15a",
  secretary: "#7ec8ff",
  secretary2: "#3cba84",
  secretary3: "#e36a5d",
  secretary4: "#c084fc",
};

const DASH = {
  "15m": undefined,
  "5m": "7 5",
};

function seriesKey(item) {
  return `${item.strategy}:${item.span}`;
}

function axisMax(value) {
  const padded = Math.max(1, Math.ceil(value * 1.08));
  const rough = padded / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const error = rough / power;
  const step = [1, 2, 5, 10].find((item) => item >= error - 1e-9) * power;
  return step * 4;
}

function formatTick(tick) {
  if (Number.isInteger(tick)) return String(tick);
  return String(Math.round(tick * 10) / 10);
}

function xTickIndexes(count) {
  const marks = [0];
  for (let index = 9; index < count; index += 10) marks.push(index);
  if (marks[marks.length - 1] !== count - 1) marks.push(count - 1);
  return marks;
}

export default function SellChart({ targets, series }) {
  const [hidden, setHidden] = useState(() => new Set());
  const [hover, setHover] = useState(null);
  const plotW = VIEW_W - PAD.l - PAD.r;
  const plotH = VIEW_H - PAD.t - PAD.b;
  const visible = series.filter((item) => !hidden.has(seriesKey(item)));
  const maxSell = Math.max(0, ...visible.flatMap((item) => item.sells));
  const yMax = axisMax(maxSell);
  const yTicks = [0, 1, 2, 3, 4].map((step) => (yMax * step) / 4);
  const xTicks = xTickIndexes(targets.length);

  const geometry = useMemo(() => {
    return series.map((item) => {
      const points = item.sells.map((count, index) => {
        const x = PAD.l + (targets.length === 1 ? plotW / 2 : (index / (targets.length - 1)) * plotW);
        const y = PAD.t + (1 - count / yMax) * plotH;
        return [x, y];
      });
      return { item, points, d: points.map(([x, y]) => `${x},${y}`).join(" ") };
    });
  }, [series, targets.length, plotW, plotH, yMax]);

  function toggle(item) {
    const key = seriesKey(item);
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function indexAt(event) {
    const box = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - box.left) / box.width) * VIEW_W;
    if (x < PAD.l || x > VIEW_W - PAD.r) return null;
    const ratio = (x - PAD.l) / plotW;
    const index = Math.round(ratio * (targets.length - 1));
    return Math.min(targets.length - 1, Math.max(0, index));
  }

  const hoverTarget = hover == null ? null : targets[hover];
  const hoverLabel = hoverTarget == null ? "" : `${Math.round(hoverTarget * 100)}%`;

  return (
    <div className="sell-chart">
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        role="img"
        aria-label="净目标从 1% 到 50% 的卖出次数折线"
        onPointerMove={(event) => setHover(indexAt(event))}
        onPointerLeave={() => setHover(null)}
      >
        {yTicks.map((tick) => {
          const y = PAD.t + (1 - tick / yMax) * plotH;
          return (
            <g key={tick}>
              <line x1={PAD.l} x2={VIEW_W - PAD.r} y1={y} y2={y} stroke="#2c3530" />
              <text x={PAD.l - 8} y={y + 4} textAnchor="end" fill="#93a096" fontSize="12">
                {formatTick(tick)}
              </text>
            </g>
          );
        })}
        {xTicks.map((index) => {
          const x = PAD.l + (index / (targets.length - 1)) * plotW;
          const label = `${Math.round(targets[index] * 100)}%`;
          const anchor = index === 0 ? "start" : index === targets.length - 1 ? "end" : "middle";
          return (
            <text key={label} x={x} y={VIEW_H - 16} textAnchor={anchor} fill="#93a096" fontSize="12">
              {label}
            </text>
          );
        })}
        <text x={VIEW_W / 2} y={VIEW_H - 2} textAnchor="middle" fill="#93a096" fontSize="12">净目标</text>
        <text
          x={14}
          y={PAD.t + plotH / 2}
          textAnchor="middle"
          fill="#93a096"
          fontSize="12"
          transform={`rotate(-90 14 ${PAD.t + plotH / 2})`}
        >
          卖出次数
        </text>
        {geometry.map(({ item, d }) => (
          hidden.has(seriesKey(item)) ? null : (
            <polyline
              key={seriesKey(item)}
              points={d}
              fill="none"
              stroke={COLOR[item.strategy] || "#e7efe9"}
              strokeWidth="2.2"
              strokeLinejoin="round"
              strokeLinecap="round"
              strokeDasharray={DASH[item.span]}
            />
          )
        ))}
        {hover != null && geometry.map(({ item, points }) => (
          hidden.has(seriesKey(item)) ? null : (
            <circle
              key={seriesKey(item)}
              cx={points[hover][0]}
              cy={points[hover][1]}
              r="4"
              fill={COLOR[item.strategy] || "#e7efe9"}
              stroke="#101410"
              strokeWidth="1.5"
            />
          )
        ))}
        {hover != null && (
          <line
            x1={PAD.l + (hover / (targets.length - 1)) * plotW}
            x2={PAD.l + (hover / (targets.length - 1)) * plotW}
            y1={PAD.t}
            y2={PAD.t + plotH}
            stroke="#e0b15a"
            strokeOpacity="0.45"
          />
        )}
      </svg>
      <p className="sell-readout">
        {hover == null ? "在图上移动，查看某一档净目标的卖出次数。" : `净目标 ${hoverLabel}`}
      </p>
      {hover != null && (
        <ul className="sell-values">
          {series.map((item) => (
            hidden.has(seriesKey(item)) ? null : (
              <li key={seriesKey(item)}>
                <i style={{ background: COLOR[item.strategy] || "#e7efe9" }} />
                <span>{item.name} · {item.span_name}</span>
                <strong>{item.sells[hover].toLocaleString("zh-CN")}</strong>
              </li>
            )
          ))}
        </ul>
      )}
      <ul className="sell-legend">
        {series.map((item) => {
          const on = !hidden.has(seriesKey(item));
          return (
            <li key={seriesKey(item)}>
              <button type="button" aria-pressed={on} onClick={() => toggle(item)}>
                <i
                  style={{
                    borderTopColor: COLOR[item.strategy] || "#e7efe9",
                    borderTopStyle: item.span === "5m" ? "dashed" : "solid",
                  }}
                />
                {item.name} · {item.span_name}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
