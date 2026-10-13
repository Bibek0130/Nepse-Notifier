import { marketApi } from "../../api/client";
import { useApi } from "../../hooks/useApi";
import QuotesTable from "./QuotesTable.jsx";

export default function QuotesPage() {
  const { loading, error, data } = useApi(() => marketApi.latestQuotes(), []);
  return (
    <>
      <h1>Latest quotes</h1>
      {loading && <p className="muted">Loading…</p>}
      {error && <p className="error">Could not load quotes: {error.message}</p>}
      {!loading && !error && !data?.length && <p className="muted">No snapshot yet. Run an ingestion first.</p>}
      {data?.length > 0 && <QuotesTable quotes={data} />}
    </>
  );
}
