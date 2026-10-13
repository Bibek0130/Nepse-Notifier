import { analysisApi, marketApi } from "../../api/client";
import { stockHref } from "../../app/router";
import { useApi } from "../../hooks/useApi";
import SignalsTable from "../signals/SignalsTable.jsx";
import StarButton from "../watchlist/StarButton.jsx";
import StockCharts from "./StockCharts.jsx";

const num = (v, digits = 2) => (v == null ? "-" : Number(v).toLocaleString(undefined, { maximumFractionDigits: digits }));

const touches = (n) => `${n} ${n === 1 ? "touch" : "touches"}`;

function oneYearAgo() {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 1);
  return d.toISOString().slice(0, 10);
}

function SymbolPicker({ symbol }) {
  const { data } = useApi(() => marketApi.instruments(), []);
  return (
    <label className="picker">
      <span className="muted">Stock</span>{" "}
      <select value={symbol || ""} onChange={(e) => (window.location.hash = stockHref(e.target.value))}>
        <option value="" disabled>Pick a stock</option>
        {(data || []).map((i) => (
          <option key={i.symbol} value={i.symbol}>{i.symbol}{i.name ? ` – ${i.name}` : ""}</option>
        ))}
      </select>
    </label>
  );
}

function Indicators({ analysis }) {
  const ind = analysis.indicators || {};
  const rows = [
    ["Close", num(ind.close)],
    ["SMA 20 / 50 / 200", `${num(ind.sma20)} / ${num(ind.sma50)} / ${num(ind.sma200)}`],
    ["RSI 14", num(ind.rsi14, 1)],
    ["MACD / signal", `${num(ind.macd)} / ${num(ind.macd_signal)}`],
    ["Volume vs 20-day avg", `${num(ind.volume, 0)} / ${num(ind.avg_volume20, 0)}`],
    ["Trades vs 20-day avg", `${num(ind.trades, 0)} / ${num(ind.avg_trades20, 0)}`],
    ["Support", analysis.support == null ? "-" : `${num(analysis.support)} (${touches(analysis.support_touches)})`],
    ["Resistance", analysis.resistance == null ? "-" : `${num(analysis.resistance)} (${touches(analysis.resistance_touches)})`],
  ];
  return (
    <div className="panel">
      <h3>Indicators</h3>
      <dl className="facts">
        {rows.map(([k, v]) => (
          <div key={k} className="fact"><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
    </div>
  );
}

function Forecast({ forecast }) {
  return (
    <div className="panel">
      <h3>Trend projection</h3>
      {!forecast ? (
        <p className="muted">Not enough history yet.</p>
      ) : (
        <>
          <p className="big">
            {num(forecast.projected_close)}{" "}
            <span className={forecast.slope_per_day >= 0 ? "up" : "down"}>
              {forecast.slope_pct_per_day >= 0 ? "+" : ""}{forecast.slope_pct_per_day}% a day
            </span>
          </p>
          <p className="muted small">
            Straight line through the last {forecast.lookback} closes, extended {forecast.horizon_days} trading days.
            Fit R² {forecast.r_squared}{forecast.r_squared < 0.5 ? ", which is weak, so treat this loosely" : ""}.
            It describes the recent trend; it is not a prediction.
          </p>
        </>
      )}
    </div>
  );
}

export default function StockPage({ symbol }) {
  const candles = useApi(() => (symbol ? marketApi.candles(symbol, "1D", oneYearAgo()) : Promise.resolve(null)), [symbol]);
  const analysis = useApi(() => (symbol ? analysisApi.symbol(symbol) : Promise.resolve(null)), [symbol]);
  const a = analysis.data;

  return (
    <>
      <div className="section-head">
        <h1>{symbol || "Stock"} {symbol && <StarButton symbol={symbol} withLabel />}</h1>
        <SymbolPicker symbol={symbol} />
      </div>
      {!symbol && <p className="muted">Pick a stock to see its chart, indicators and signals.</p>}
      {candles.error && <p className="error">Could not load prices: {candles.error.message}</p>}
      {symbol && candles.data && !candles.data.length && <p className="muted">No daily prices for {symbol} yet. Run a backfill first.</p>}
      {candles.data?.length > 0 && (
        <section className="panel">
          <StockCharts candles={candles.data} analysis={a} />
        </section>
      )}
      {a && (
        <>
          <section className="grid-2">
            <Indicators analysis={a} />
            <Forecast forecast={a.forecast} />
          </section>
          <div className="section-head">
            <h2>Signals</h2>
            <span className="muted">{a.trading_date}{a.provisional ? " (intraday, provisional)" : ""}</span>
          </div>
          {a.signals.length ? <SignalsTable signals={a.signals} showSymbol={false} /> : <p className="muted">No signals today.</p>}
        </>
      )}
      {symbol && !analysis.loading && !a && !analysis.error && <p className="muted">No analysis for {symbol} yet.</p>}
    </>
  );
}
