export function formatTs(ms) {
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

export function formatTick(sec) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(sec * 1000));
}

export function money(value) {
  return Number(value).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function signedMoney(value) {
  const number = Number(value);
  const text = money(Math.abs(number));
  if (number > 0) return `+${text}`;
  if (number < 0) return `−${text}`;
  return text;
}

export function pct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const number = Number(value) * 100;
  const text = `${Math.abs(number).toFixed(2)}%`;
  if (number > 0) return `+${text}`;
  if (number < 0) return `−${text}`;
  return text;
}

export function priceOf(value, tick) {
  const text = String(tick);
  const decimals = text.includes(".") ? text.split(".")[1].length : 0;
  return Number(value).toFixed(decimals);
}

export function hold(hours) {
  if (hours == null) return "—";
  const total = Math.round(Number(hours));
  if (total < 48) return `${total} 小时`;
  const days = Math.floor(total / 24);
  const rest = total % 24;
  return rest ? `${days} 天 ${rest} 小时` : `${days} 天`;
}

export function tone(value) {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "";
}

export function compoundText(value) {
  return Math.round(value).toLocaleString("zh-CN");
}
