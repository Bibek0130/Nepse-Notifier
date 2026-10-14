// Thin wrapper over the DRF API, one object per backend module.
export async function getJson(path, params) {
  const url = new URL(`/api/${path}`, window.location.origin);
  Object.entries(params || {}).forEach(([k, v]) => v != null && v !== "" && url.searchParams.set(k, v));
  const res = await fetch(url, { credentials: "include" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const marketApi = {
  latestQuotes: () => getJson("market/quotes/latest"),
  summary: () => getJson("market/summary"),
  instruments: () => getJson("market/instruments"),
  candles: (symbol, tf = "1D", start) => getJson("market/candles", { symbol, tf, start }),
  status: () => getJson("market/status"),
};

export const analysisApi = {
  signals: (params) => getJson("analysis/signals", params),
  symbol: (symbol) => getJson(`analysis/symbols/${encodeURIComponent(symbol)}`),
  backtest: () => getJson("analysis/backtest"),
};
