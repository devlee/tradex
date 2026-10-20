const statusEl = document.querySelector("#status");
const warningsEl = document.querySelector("#warnings");
const summaryEl = document.querySelector("#summary");
const openEl = document.querySelector("#open");
const statsEl = document.querySelector("#stats");
const explainEl = document.querySelector("#explain");
const rowsEl = document.querySelector("#rows");
const specEl = document.querySelector("#spec");
const form = document.querySelector("#controls");
const runButton = document.querySelector("#run");

let priceChart;
let equityChart;
let priceSeries;
let activeRow;
let gridData;

const chartBase = {
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

function formatTs(ms) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(ms));
}

function formatTick(sec) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(sec * 1000));
}

function money(value) {
  return Number(value).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function signedMoney(value) {
  const number = Number(value);
  const text = money(Math.abs(number));
  if (number > 0) return `+${text}`;
  if (number < 0) return `−${text}`;
  return text;
}

function pct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const number = Number(value) * 100;
  const text = Math.abs(number).toFixed(2) + "%";
  if (number > 0) return `+${text}`;
  if (number < 0) return `−${text}`;
  return text;
}

function priceOf(value, tick) {
  const text = String(tick);
  const decimals = text.includes(".") ? text.split(".")[1].length : 0;
  return Number(value).toFixed(decimals);
}

function hold(hours) {
  if (hours == null) return "—";
  const total = Math.round(Number(hours));
  if (total < 48) return `${total} 小时`;
  const days = Math.floor(total / 24);
  const rest = total % 24;
  return rest ? `${days} 天 ${rest} 小时` : `${days} 天`;
}

function tone(value) {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "";
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function stat(label, value, caption, className) {
  const card = el("article", "stat");
  card.append(el("span", "", label), el("strong", className || "", value), el("em", "", caption));
  return card;
}

function fact(label, value, className) {
  const wrap = document.createElement("div");
  const term = el("dt", "", label);
  const desc = el("dd", className || "", value);
  wrap.append(term, desc);
  return wrap;
}

function destroyCharts() {
  if (priceChart) priceChart.remove();
  if (equityChart) equityChart.remove();
  priceChart = null;
  equityChart = null;
  priceSeries = null;
}

function chartOptions() {
  return {
    ...chartBase,
    layout: { ...chartBase.layout },
    grid: {
      vertLines: { ...chartBase.grid.vertLines },
      horzLines: { ...chartBase.grid.horzLines },
    },
    rightPriceScale: { ...chartBase.rightPriceScale },
    timeScale: { ...chartBase.timeScale },
    localization: { ...chartBase.localization },
    crosshair: {
      vertLine: { ...chartBase.crosshair.vertLine },
      horzLine: { ...chartBase.crosshair.horzLine },
    },
  };
}

function drawCharts(data) {
  destroyCharts();
  const tick = data.market.tick_sz;
  priceChart = LightweightCharts.createChart(document.querySelector("#price-chart"), chartOptions());
  equityChart = LightweightCharts.createChart(document.querySelector("#equity-chart"), chartOptions());
  priceSeries = priceChart.addCandlestickSeries({
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
    open, high, low, close,
  })));
  const markerStyle = {
    buy: { position: "belowBar", color: "#3cba84", shape: "arrowUp", text: "买" },
    sell: { position: "aboveBar", color: "#e0b15a", shape: "arrowDown", text: "卖" },
    liq: { position: "aboveBar", color: "#e36a5d", shape: "arrowDown", text: "强平" },
  };
  priceSeries.setMarkers(data.markers.map(([ts, kind, level]) => ({
    time: Math.floor(ts / 1000),
    price: level,
    ...markerStyle[kind],
  })));
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
  requestAnimationFrame(showAll);
}

function focusRange(entryTs, exitTs, endTs) {
  if (!priceChart) return;
  const end = exitTs || endTs;
  const span = Math.max(end - entryTs, 24 * 3600 * 1000);
  const pad = span * 0.2;
  const from = Math.floor((entryTs - pad) / 1000);
  const to = Math.floor((end + pad) / 1000);
  priceChart.timeScale().setVisibleRange({ from, to });
  equityChart.timeScale().setVisibleRange({ from, to });
}

function render(data) {
  const tick = data.market.tick_sz;
  const stats = data.stats;
  clear(warningsEl);
  data.market.warnings.forEach((text) => warningsEl.append(el("p", "warning", text)));
  if (stats.note) warningsEl.append(el("p", "warning", stats.note));

  const bits = [
    `${formatTs(data.market.start)} 到 ${formatTs(data.market.end)}，共 ${data.market.count} 根 15 分钟 K 线。进场钟点是北京时间 ${data.params.entry_hour} 点。`,
    `正常卖出 ${stats.completed} 笔。`,
  ];
  if (stats.completed) {
    bits.push(`这些周期连乘后的余额是 ${money(stats.compounded_equity)} USDT。`);
    if (stats.theoretical_equity != null) {
      bits.push(`每笔刚好达到净目标时，连乘结果是 ${money(stats.theoretical_equity)} USDT。`);
    }
    if (stats.max_hold_hours >= 48) {
      bits.push(`最长的一笔拿了 ${hold(stats.max_hold_hours)}。`);
    }
  }
  if (data.open_cycle) {
    bits.push(`结束时还有一笔没卖掉，按最后收盘价算，市值权益是 ${money(stats.final_equity)} USDT。`);
  } else if (stats.completed) {
    bits.push(`结束时是空仓，市值权益是 ${money(stats.final_equity)} USDT。`);
  }
  if (stats.liquidations) bits.push(`另外有 ${stats.liquidations} 笔被强平。`);
  if (!data.open_cycle && stats.next_entry_ts) {
    bits.push(`下一笔计划在 ${formatTs(stats.next_entry_ts)} 的开盘价。`);
  }
  summaryEl.textContent = bits.join("");

  clear(statsEl);
  const funding = Number(stats.total_funding);
  statsEl.append(
    stat("市值权益", money(stats.final_equity), "最后一根收盘价下的账户价值", "sand"),
    stat("已完成复利", money(stats.compounded_equity), "已平仓周期连乘后的余额", "sand"),
    stat("正常卖出", String(stats.completed), stats.avg_net_return == null ? "还没有完成的周期" : `单笔净利率 ${pct(stats.min_net_return)} 到 ${pct(stats.max_net_return)}`),
    stat("最长持仓", hold(stats.max_hold_hours), stats.avg_hold_hours == null ? "含未平仓的这一笔" : `已完成周期平均 ${hold(stats.avg_hold_hours)}`),
    stat("收盘最大回撤", stats.max_drawdown ? `−${(stats.max_drawdown * 100).toFixed(2)}%` : "0.00%", "按每根 K 线收盘时的市值，从高点回落的最大幅度", "down"),
    stat("单笔最大浮亏", pct(stats.worst_mae), "按持仓期间 K 线最低价估计", "down"),
    stat("手续费合计", money(stats.total_fees), "开仓和平仓挂单费", ""),
    stat("资金费收支", signedMoney(funding), funding < 0 ? "负数是净付出" : "正数是净收到", tone(funding)),
  );

  clear(openEl);
  if (!data.open_cycle) {
    openEl.hidden = true;
  } else {
    const open = data.open_cycle;
    openEl.hidden = false;
    const gap = (open.target - open.last_price) / open.last_price;
    const head = el("div", "open-head");
    head.append(el("h2", "", "有一笔还在持仓"));
    head.append(el("p", "", gap > 0
      ? `最新价到卖单还差 ${(gap * 100).toFixed(2)}%`
      : "最新价已经在卖单之上，卖出留到下一根 K 线"));
    const facts = el("dl", "facts");
    facts.append(
      fact("开仓", formatTs(open.entry_ts)),
      fact("开仓价", priceOf(open.entry, tick)),
      fact("数量", `${open.coin_qty} NEAR`),
      fact("当前卖价", priceOf(open.target, tick), "sand"),
      fact("最新价", priceOf(open.last_price, tick)),
      fact("浮动盈亏", signedMoney(open.upl), tone(open.upl)),
      fact("这笔市值", money(open.equity), "sand"),
      fact("已持有", hold(open.hold_hours)),
      fact("这笔最大浮亏", pct(open.mae_return), "down"),
      fact("开仓手续费", money(open.fees)),
      fact("这笔资金费", signedMoney(open.funding), tone(open.funding)),
    );
    openEl.append(head, facts);
  }

  const sample = [...data.cycles].reverse().find((cycle) => cycle.status === "target") || data.open_cycle;
  if (!sample) {
    explainEl.hidden = true;
  } else {
    explainEl.hidden = false;
    clear(explainEl);
    explainEl.append(el("h2", "", sample.exit_ts ? "最近一笔完成的账" : "当前这笔的账"));
    const line = el("p", "explain");
    if (sample.exit_ts) {
      line.textContent = `开仓前权益 ${money(sample.equity_before)} USDT，买入 ${sample.coin_qty} NEAR，价格 ${priceOf(sample.entry, tick)}。卖出价格 ${priceOf(sample.exit_price, tick)}。手续费 ${money(sample.fees)} USDT，资金费 ${signedMoney(sample.funding)} USDT。结束后权益 ${money(sample.equity_after)} USDT，净利率 ${pct(sample.net_return)}。`;
    } else {
      line.textContent = `开仓前权益 ${money(sample.equity_before)} USDT，买入 ${sample.coin_qty} NEAR，价格 ${priceOf(sample.entry, tick)}。当前目标卖价 ${priceOf(sample.target, tick)}。已经付出开仓手续费 ${money(sample.fees)} USDT，资金费 ${signedMoney(sample.funding)} USDT。按最新价算，这笔市值是 ${money(sample.equity)} USDT。`;
    }
    explainEl.append(line);
  }

  clear(rowsEl);
  const display = data.open_cycle
    ? [...data.cycles, { ...data.open_cycle, status: "open" }]
    : data.cycles;
  display.forEach((cycle, index) => {
    const tr = document.createElement("tr");
    if (cycle.status === "open") tr.classList.add("open-row");
    if (cycle.status === "liquidated") tr.classList.add("liq-row");
    tr.tabIndex = 0;
    const marked = cycle.equity_after == null ? cycle.equity - cycle.equity_before : cycle.net_pnl;
    const rate = cycle.net_return == null ? marked / cycle.equity_before : cycle.net_return;
    const cells = [
      cycle.status === "open" ? "持仓" : String(index + 1),
      formatTs(cycle.entry_ts),
      cycle.exit_ts ? formatTs(cycle.exit_ts) : "未平",
      priceOf(cycle.entry, tick),
      priceOf(cycle.target, tick),
      signedMoney(marked),
      pct(rate),
      money(cycle.equity_after == null ? cycle.equity : cycle.equity_after),
      signedMoney(cycle.funding),
      money(cycle.fees),
      hold(cycle.hold_hours),
      pct(cycle.mae_return),
    ];
    const tones = {
      5: marked,
      6: rate,
      8: cycle.funding,
      11: cycle.mae_return,
    };
    cells.forEach((text, cellIndex) => {
      const td = document.createElement("td");
      td.textContent = text;
      if (cellIndex in tones) td.className = tone(tones[cellIndex]);
      tr.append(td);
    });
    const select = () => {
      if (activeRow) activeRow.classList.remove("active");
      tr.classList.add("active");
      activeRow = tr;
      focusRange(cycle.entry_ts, cycle.exit_ts, data.market.end);
    };
    tr.addEventListener("click", select);
    tr.addEventListener("keydown", (event) => {
      if (event.key === "Enter") select();
    });
    rowsEl.append(tr);
  });

  const targetText = String(Math.round(data.params.net_target * 1000) / 10).replace(/\.0$/, "");
  document.querySelector("#target-label").textContent = `${targetText}%`;
  specEl.textContent = `合约 ${data.market.inst_id}，1 张 = ${data.market.ct_val} NEAR，最小 ${data.market.lot_sz} 张，报价步进 ${data.market.tick_sz}。小仓位维持保证金 ${(data.market.mmr * 100).toFixed(2)}%。行情更新于 ${formatTs(data.market.fetched_at)}。`;
  drawCharts(data);
  markGridCell();
  statusEl.textContent = "回测完成。这是历史行情的重放，用来观察这条规则，不是对以后收益的预测。";
}

function compoundText(value) {
  return Math.round(value).toLocaleString("zh-CN");
}

function markGridCell() {
  if (!gridData) return;
  const equity = Number(document.querySelector("#equity").value);
  const fee = Number(document.querySelector("#fee").value) / 100;
  const start = document.querySelector("#start").value;
  const hour = Number(document.querySelector("#hour").value);
  const net = Number(document.querySelector("#net").value) / 100;
  const sameBook = equity === gridData.equity
    && Math.abs(fee - gridData.fee_rate) < 1e-12
    && start === gridData.start;
  document.querySelectorAll("#grid-body td[data-hour]").forEach((cell) => {
    const matched = sameBook
      && Number(cell.dataset.hour) === hour
      && Math.abs(Number(cell.dataset.target) - net) < 1e-9;
    cell.classList.toggle("current", matched);
  });
}

function mean(numbers) {
  return numbers.reduce((sum, value) => sum + value, 0) / numbers.length;
}

const SPECTRUM = [
  [0, [49, 10, 140]],
  [0.16, [16, 78, 214]],
  [0.33, [0, 168, 196]],
  [0.5, [32, 176, 86]],
  [0.66, [226, 206, 32]],
  [0.82, [236, 112, 22]],
  [1, [196, 24, 36]],
];

function spectrumColor(ratio) {
  const clamped = Math.min(1, Math.max(0, ratio));
  let upper = SPECTRUM.length - 1;
  for (let index = 1; index < SPECTRUM.length; index += 1) {
    if (clamped <= SPECTRUM[index][0]) {
      upper = index;
      break;
    }
  }
  const [fromStop, from] = SPECTRUM[upper - 1];
  const [toStop, to] = SPECTRUM[upper];
  const span = toStop - fromStop || 1;
  const blend = (clamped - fromStop) / span;
  return from.map((channel, index) => Math.round(channel + (to[index] - channel) * blend));
}

function heatCell(value, low, high) {
  const td = document.createElement("td");
  const ratio = high === low ? 0.5 : (value - low) / (high - low);
  const [red, green, blue] = spectrumColor(ratio);
  const luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255;
  td.textContent = compoundText(value);
  td.title = `${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT`;
  td.style.background = `rgb(${red}, ${green}, ${blue})`;
  td.style.color = luminance > 0.62 ? "#1a1408" : "#f7f4ee";
  return td;
}

function renderGrid(grid) {
  gridData = grid;
  const head = document.querySelector("#grid-head");
  const body = document.querySelector("#grid-body");
  clear(head);
  clear(body);
  const header = document.createElement("tr");
  header.append(el("th", "", "钟点"));
  grid.targets.forEach((target) => header.append(el("th", "", `${Math.round(target * 100)}%`)));
  header.append(el("th", "mean", "均值"));
  head.append(header);
  const flat = grid.values.flat();
  const low = Math.min(...flat);
  const high = Math.max(...flat);
  const columnMeans = grid.targets.map((_, columnIndex) => mean(grid.values.map((row) => row[columnIndex])));
  grid.hours.forEach((hour, rowIndex) => {
    const tr = document.createElement("tr");
    tr.append(el("td", "", `${hour} 点`));
    grid.values[rowIndex].forEach((value, columnIndex) => {
      const td = heatCell(value, low, high);
      td.dataset.hour = String(hour);
      td.dataset.target = String(grid.targets[columnIndex]);
      tr.append(td);
    });
    const rowMean = heatCell(mean(grid.values[rowIndex]), low, high);
    rowMean.classList.add("mean");
    tr.append(rowMean);
    body.append(tr);
  });
  const meanRow = document.createElement("tr");
  meanRow.className = "mean";
  meanRow.append(el("td", "", "均值"));
  columnMeans.forEach((value) => {
    const td = heatCell(value, low, high);
    td.classList.add("mean");
    meanRow.append(td);
  });
  const grand = heatCell(mean(flat), low, high);
  grand.classList.add("mean");
  meanRow.append(grand);
  body.append(meanRow);
  document.querySelector("#grid-note").textContent = "横轴是单周期净目标，纵轴是北京时间进场钟点。数字是已完成复利，单位 USDT，按起点 2026-03-13、起始资金 10,000、挂单费率 0.02% 事先算好。没有记录的资金费按 0.01%。最右一列是这个钟点在各净目标上的均值，最下一行是这个净目标在各钟点上的均值，右下角是全部格子的均值。";
  markGridCell();
}

async function loadGrid() {
  const response = await fetch("/grid.json");
  if (!response.ok) throw new Error("复利表没有读到");
  renderGrid(await response.json());
}

async function loadBacktest() {
  const equity = document.querySelector("#equity").value;
  const net = Number(document.querySelector("#net").value) / 100;
  const fee = Number(document.querySelector("#fee").value) / 100;
  const start = document.querySelector("#start").value;
  const hour = document.querySelector("#hour").value;
  runButton.disabled = true;
  statusEl.textContent = "正在读取 NEAR 永续 15 分钟行情并重放规则。第一次会从 2026-03-13 下载到现在。";
  try {
    const response = await fetch(`/api/backtest?equity=${encodeURIComponent(equity)}&net=${encodeURIComponent(net)}&fee=${encodeURIComponent(fee)}&start=${encodeURIComponent(start)}&hour=${encodeURIComponent(hour)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "回测失败");
    render(data);
  } catch (error) {
    statusEl.textContent = error.message || "回测失败";
  } finally {
    runButton.disabled = false;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  loadBacktest();
});

loadGrid().catch((error) => {
  document.querySelector("#grid-note").textContent = error.message || "复利表没有读到";
});
loadBacktest();
