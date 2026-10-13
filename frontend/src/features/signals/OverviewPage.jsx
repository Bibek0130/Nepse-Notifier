import { useState } from "react";

import { analysisApi, marketApi } from "../../api/client";
import { useApi } from "../../hooks/useApi";
import MarketSummary from "../market/MarketSummary.jsx";
import Movers from "../market/Movers.jsx";
import SignalsTable from "./SignalsTable.jsx";

export default function OverviewPage() {
  const summary = useApi(() => marketApi.summary(), []);
  const [direction, setDirection] = useState("");
  const [minStrength, setMinStrength] = useState(1);
  const signals = useApi(
    () => analysisApi.signals({ direction, min_strength: minStrength }),
    [direction, minStrength],
  );
  const report = signals.data;

  return (
    <>
      <h1>Market overview</h1>
      {summary.error && <p className="error">Could not load the market summary: {summary.error.message}</p>}
      {!summary.loading && !summary.data?.symbols && !summary.error && (
        <p className="muted">No market snapshot yet. Run an ingestion first.</p>
      )}
      <MarketSummary summary={summary.data} />
      <Movers summary={summary.data} />

      <div className="section-head">
        <h2>Latest signals</h2>
        {report?.trading_date && (
          <span className="muted">
            {report.trading_date}
            {report.provisional ? " (intraday, provisional)" : " (end of day)"} · {report.symbols_analyzed} stocks analysed
          </span>
        )}
      </div>
      <div className="filters">
        <label>
          Direction{" "}
          <select value={direction} onChange={(e) => setDirection(e.target.value)}>
            <option value="">All</option>
            <option value="bullish">Bullish</option>
            <option value="bearish">Bearish</option>
            <option value="neutral">Neutral</option>
          </select>
        </label>
        <label>
          Strength{" "}
          <select value={minStrength} onChange={(e) => setMinStrength(Number(e.target.value))}>
            <option value={1}>Any</option>
            <option value={2}>Medium and strong</option>
            <option value={3}>Strong only</option>
          </select>
        </label>
      </div>
      {signals.error && <p className="error">Could not load signals: {signals.error.message}</p>}
      {report && !report.signals.length && <p className="muted">No signals match these filters.</p>}
      {report?.signals.length > 0 && <SignalsTable signals={report.signals} />}
    </>
  );
}
