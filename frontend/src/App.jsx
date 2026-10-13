import MarketSummary from "./features/market/MarketSummary.jsx";
import QuotesTable from "./features/market/QuotesTable.jsx";
import { useMarket } from "./features/market/useMarket";

export default function App() {
  const { loading, error, quotes, summary } = useMarket();

  return (
    <main>
      <header>
        <h1>NEPSE Notifier</h1>
        {summary?.as_of && <span className="muted">As of {new Date(summary.as_of).toLocaleString()}</span>}
      </header>
      {loading && <p className="muted">Loading market data…</p>}
      {error && <p className="error">Could not load market data: {error.message}</p>}
      {!loading && !error && quotes.length === 0 && <p className="muted">No data yet. Run an ingestion first.</p>}
      <MarketSummary summary={summary} />
      {quotes.length > 0 && <QuotesTable quotes={quotes} />}
    </main>
  );
}
