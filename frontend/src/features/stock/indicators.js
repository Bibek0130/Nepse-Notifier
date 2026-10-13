// Client-side series for chart overlays. The backend stores only the latest values;
// the chart needs the full line, so we recompute with the same formulas.

export function sma(values, period) {
  const out = new Array(values.length).fill(null);
  let sum = 0;
  values.forEach((v, i) => {
    sum += v;
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  });
  return out;
}

/** Wilder's RSI, matching modules/analysis/domain/indicators.py. */
export function rsi(values, period = 14) {
  const out = new Array(values.length).fill(null);
  if (values.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i += 1) {
    const d = values[i] - values[i - 1];
    gain += Math.max(d, 0);
    loss += Math.max(-d, 0);
  }
  gain /= period;
  loss /= period;
  const value = () => (loss === 0 ? 100 : 100 - 100 / (1 + gain / loss));
  out[period] = value();
  for (let i = period + 1; i < values.length; i += 1) {
    const d = values[i] - values[i - 1];
    gain = (gain * (period - 1) + Math.max(d, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-d, 0)) / period;
    out[i] = value();
  }
  return out;
}
