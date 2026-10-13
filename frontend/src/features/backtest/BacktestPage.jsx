import { useState } from "react";

import { analysisApi } from "../../api/client";
import { useApi } from "../../hooks/useApi";
import { DirectionBadge, STRATEGY_LABELS } from "../signals/SignalsTable.jsx";

const FEW = 20; // below this many measured signals, a hit rate says little

const pct = (v) => (v == null ? "-" : `${Math.round(v * 100)}%`);
const ret = (v) => (v == null ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);

function HitBar({ value, reference }) {
  if (value == null) return null;
  return (
    <span className="hitbar" aria-hidden="true">
      <span className="fill" style={{ width: `${value * 100}%` }} />
      {reference != null && <span className="ref" style={{ left: `${reference * 100}%` }} />}
    </span>
  );
}

export default function BacktestPage() {
  const { loading, error, data } = useApi(() => analysisApi.backtest(), []);
  const [horizon, setHorizon] = useState(10);
  const [strength, setStrength] = useState("1");

  if (loading) return <p className="muted">Loading…</p>;
  if (error) return <p className="error">Could not load the backtest: {error.message}</p>;
  if (!data) {
    return (
      <>
        <h1>Backtest</h1>
        <p className="muted">No backtest yet. It runs every Friday, or run <code>python manage.py backtest</code>.</p>
      </>
    );
  }

  const hIndex = Math.max(0, data.horizons.indexOf(horizon));
  const base = data.baseline[hIndex];
  const rows = (data.results[strength] || []).map((r) => ({ ...r, h: r.horizons[hIndex] }));
  // Rows with too few measured signals go last: their hit rates are mostly luck.
  const few = (r) => (r.h.samples < FEW ? 1 : 0);
  rows.sort((a, b) => few(a) - few(b) || (b.h.hit_rate ?? -1) - (a.h.hit_rate ?? -1) || b.signals - a.signals);

  return (
    <>
      <div className="section-head">
        <h1>Backtest</h1>
        <span className="muted">
          {data.start_date} to {data.end_date} · {data.symbols_tested} stocks · {data.signals_evaluated.toLocaleString()} signals
        </span>
      </div>
      <p className="muted small explain">
        Every strategy was replayed day by day over past prices, seeing only the data it would have had on each day.
        A signal counts as a hit when the price had moved its way after the chosen number of trading days: up for bullish, down
        for bearish. The marker on each bar is how often prices moved that way anyway, on any day: the rate a strategy has to beat to be worth anything.
        Past results do not promise future ones.
      </p>
      <div className="filters">
        <label>
          After{" "}
          <select value={data.horizons[hIndex]} onChange={(e) => setHorizon(Number(e.target.value))}>
            {data.horizons.map((h) => <option key={h} value={h}>{h} trading days</option>)}
          </select>
        </label>
        <label>
          Strength{" "}
          <select value={strength} onChange={(e) => setStrength(e.target.value)}>
            <option value="1">Any</option>
            <option value="2">Medium and strong</option>
            <option value="3">Strong only</option>
          </select>
        </label>
      </div>
      <div className="table-wrap">
        <table className="backtest">
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Direction</th>
              <th>Signals</th>
              <th>Hit rate</th>
              <th className="bar-col"><span className="sr-only">Hit rate bar</span></th>
              <th>Avg return</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isFew = few(r) === 1;
              return (
                <tr key={`${r.strategy}-${r.direction}`} className={isFew ? "few" : ""}>
                  <td>{STRATEGY_LABELS[r.strategy] || r.strategy}</td>
                  <td><DirectionBadge direction={r.direction} /></td>
                  <td>
                    {r.signals.toLocaleString()}
                    {isFew && <span className="muted small" title={`Only ${r.h.samples} could be measured`}> few</span>}
                  </td>
                  <td>{r.direction === "neutral" ? <span className="muted">n/a</span> : pct(r.h.hit_rate)}</td>
                  <td className="bar-col">
                    {r.direction !== "neutral" && <HitBar value={r.h.hit_rate} reference={r.direction === "bearish" ? 1 - base.hit_rate : base.hit_rate} />}
                  </td>
                  <td className={r.h.avg_return > 0 ? "up" : r.h.avg_return < 0 ? "down" : ""}>{ret(r.h.avg_return)}</td>
                </tr>
              );
            })}
            <tr className="baseline">
              <td colSpan={3}>Every day, no strategy</td>
              <td>{pct(base.hit_rate)} rose</td>
              <td className="bar-col"><HitBar value={base.hit_rate} /></td>
              <td className={base.avg_return > 0 ? "up" : base.avg_return < 0 ? "down" : ""}>{ret(base.avg_return)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Neutral signals (unusual volume or trades) have no direction to be right about, so only their average return is shown.
        Rows marked "few" have fewer than {FEW} measured signals.
      </p>
    </>
  );
}
