const SPECTRUM = [
  [0, [49, 10, 140]],
  [0.16, [16, 78, 214]],
  [0.33, [0, 168, 196]],
  [0.5, [32, 176, 86]],
  [0.66, [226, 206, 32]],
  [0.82, [236, 112, 22]],
  [1, [196, 24, 36]],
];

export function spectrumStyle(ratio) {
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
  const rgb = from.map((channel, index) => Math.round(channel + (to[index] - channel) * blend));
  const luminance = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
  return {
    background: `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`,
    color: luminance > 0.62 ? "#1a1408" : "#f7f4ee",
  };
}

export function heatStyle(value, low, high) {
  const ratio = high === low ? 0.5 : (value - low) / (high - low);
  return spectrumStyle(ratio);
}
