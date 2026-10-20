import { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";
import { formatTick, formatTs, priceOf } from "../format";

const ENTRY_COLORS = ["#e0b15a", "#3cba84", "#7eb6ff", "#e36a5d", "#c58bff", "#f0d7a2", "#5ec8c5", "#f2a35e"];

function chartOptions() {
  return {
    autoSize: true,
    layout: {
      background: { color: "transparent" },
      textColor: "#93a096",
      fontFamily: '"Avenir Next", "PingFang SC", sans-serif',
    },
    grid: {
      vertLines: { color: "rgba(44, 53, 48, 0.65)" },
      horzLines: { color: "rgba(44, 53, 48, 0.65)" },
    },
    rightPriceScale: { borderColor: "#2c3530" },
    timeScale: {
      borderColor: "#2c3530",
      timeVisible: true,
      secondsVisible: false,
      minBarSpacing: 0.001,
      tickMarkFormatter: (time) => formatTick(time),
    },
    localization: {
      timeFormatter: (time) => formatTs(time * 1000),
    },
    crosshair: {
      vertLine: { color: "rgba(224, 177, 90, 0.35)" },
      horzLine: { color: "rgba(224, 177, 90, 0.35)" },
    },
  };
}

export default function Charts({ data, focus, base = "价格", entries = [] }) {
  const priceHost = useRef(null);
  const equityHost = useRef(null);
  const api = useRef(null);
  const tick = data?.market.tick_sz ?? 0.001;

  useEffect(() => {
    if (!data?.candles?.length || !priceHost.current || !equityHost.current) return undefined;
    const priceChart = createChart(priceHost.current, chartOptions());
    const equityChart = createChart(equityHost.current, chartOptions());
    const priceSeries = priceChart.addCandlestickSeries({
      upColor: "#3cba84",
      downColor: "#e36a5d",
      borderVisible: false,
      wickUpColor: "#3cba84",
      wickDownColor: "#e36a5d",
      priceFormat: { type: "price", precision: 3, minMove: Number(tick) },
    });
    const equitySeries = equityChart.addLineSeries({
      color: "#e0b15a",
      lineWidth: 2,
      priceLineVisible: false,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    const cashSeries = equityChart.addLineSeries({
      color: "#9eb0a4",
      lineWidth: 2,
      priceLineVisible: false,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    priceSeries.setData(data.candles.map(([ts, open, high, low, close]) => ({
      time: Math.floor(ts / 1000),
      open,
      high,
      low,
      close,
    })));
    const markerStyle = {
      buy: { position: "belowBar", color: "#3cba84", shape: "arrowUp", text: "买" },
      sell: { position: "aboveBar", color: "#e0b15a", shape: "arrowDown", text: "卖" },
      liq: { position: "aboveBar", color: "#e36a5d", shape: "arrowDown", text: "强平" },
    };
    const markers = [];
    data.markers.forEach(([ts, kind, level, book]) => {
      const time = Math.floor(ts / 1000);
      const style = markerStyle[kind] || markerStyle.buy;
      const entry = kind === "buy"
        ? entries.find((item) => Math.floor(item.ts / 1000) === time && (!book || item.name === book))
        : null;
      const text = entry ? `${entry.name} ${priceOf(entry.price, tick)}` : (book ? `${book}${style.text}` : style.text);
      const previous = markers.find((marker) => marker.time === time);
      if (previous) {
        previous.text = `${previous.text} ${text}`;
        return;
      }
      markers.push({ time, price: level, ...style, text });
    });
    markers.sort((left, right) => left.time - right.time);
    priceSeries.setMarkers(markers);
    entries.forEach((entry, index) => {
      priceSeries.createPriceLine({
        price: Number(entry.price),
        color: ENTRY_COLORS[index % ENTRY_COLORS.length],
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: `${entry.name} ${priceOf(entry.price, tick)}`,
      });
    });
    equitySeries.setData(data.curve.map(([ts, equity]) => ({
      time: Math.floor(ts / 1000),
      value: equity,
    })));
    cashSeries.setData(data.curve.map(([ts, , cash]) => ({
      time: Math.floor(ts / 1000),
      value: cash,
    })));
    const showAll = () => {
      const from = Math.floor(data.candles[0][0] / 1000);
      const to = Math.floor(data.candles[data.candles.length - 1][0] / 1000);
      priceChart.timeScale().setVisibleRange({ from, to });
      equityChart.timeScale().setVisibleRange({ from, to });
    };
    showAll();
    const frame = requestAnimationFrame(showAll);
    api.current = { priceChart, equityChart };
    return () => {
      cancelAnimationFrame(frame);
      priceChart.remove();
      equityChart.remove();
      api.current = null;
    };
  }, [data, entries]);

  useEffect(() => {
    if (!focus || !api.current) return;
    const end = focus.exitTs || focus.endTs;
    const span = Math.max(end - focus.entryTs, 24 * 3600 * 1000);
    const pad = span * 0.2;
    const range = {
      from: Math.floor((focus.entryTs - pad) / 1000),
      to: Math.floor((end + pad) / 1000),
    };
    api.current.priceChart.timeScale().setVisibleRange(range);
    api.current.equityChart.timeScale().setVisibleRange(range);
  }, [focus, data]);

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>价格和成交</h2>
          <p>虚线标出每个仓位第一次开仓的价格。下跌只按仓位1的开仓价每 10% 计算，仓位2再跌不会再开新仓。绿箭头是买入，金色箭头是按目标卖出。</p>
        </div>
        {entries.length ? (
          <ul className="entry-marks">
            {entries.map((entry, index) => (
              <li key={entry.name}>
                <i style={{ background: ENTRY_COLORS[index % ENTRY_COLORS.length] }} />
                <span>{entry.name}</span>
                <strong>{priceOf(entry.price, tick)}</strong>
                <em>{formatTs(entry.ts)}</em>
              </li>
            ))}
          </ul>
        ) : null}
        <div ref={priceHost} className="chart chart-price" aria-label={`${base} 价格与买卖点`} />
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>账户权益</h2>
          <p>金色是市值权益，含浮动盈亏。灰色是现金余额，不含浮动盈亏。两条线重合时是空仓。</p>
        </div>
        <div ref={equityHost} className="chart chart-equity" aria-label="市值权益与现金余额" />
      </section>
    </>
  );
}
