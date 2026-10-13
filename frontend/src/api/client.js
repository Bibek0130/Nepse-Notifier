// Thin wrapper over the DRF API. One module per backend domain lives next to it as it grows.
export async function getJson(path, params) {
  const url = new URL(`/api/${path}`, window.location.origin);
  Object.entries(params || {}).forEach(([k, v]) => v != null && url.searchParams.set(k, v));
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const marketApi = {
  latestQuotes: () => getJson("market/quotes/latest"),
  summary: () => getJson("market/summary"),
  candles: (symbol, tf = "1D") => getJson("market/candles", { symbol, tf }),
};
