import { marketApi } from "../../api/client";
import { useApi } from "../../hooks/useApi";

const KINDS = [
  ["intraday", "Intraday snapshot", "11:15 and 14:15 Nepal time, Sunday to Thursday"],
  ["eod", "End of day", "15:15 Nepal time, Sunday to Thursday"],
  ["backfill", "History backfill", "Run by hand"],
];

const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "-");

function tone(status) {
  if (status === "ok") return "up";
  if (status === "failed") return "down";
  return "muted";
}

export default function StatusPage() {
  const { loading, error, data } = useApi(() => marketApi.status(), []);
  return (
    <>
      <h1>Pipeline</h1>
      <p className="muted">The latest run of each kind. Full error details are in Django admin.</p>
      {loading && <p className="muted">Loading…</p>}
      {error && <p className="error">Could not load pipeline status: {error.message}</p>}
      {data && (
        <section className="grid-3">
          {KINDS.map(([kind, title, schedule]) => {
            const run = data[kind];
            return (
              <div className="panel" key={kind}>
                <h3>{title}</h3>
                <p className="muted small">{schedule}</p>
                {!run ? (
                  <p className="muted">Never run.</p>
                ) : (
                  <dl className="facts">
                    <dt>Status</dt>
                    <dd className={tone(run.status)}>{run.status}</dd>
                    <dt>Source</dt>
                    <dd>{run.source || "-"}</dd>
                    <dt>Trading date</dt>
                    <dd>{run.trading_date || "-"}</dd>
                    <dt>Started</dt>
                    <dd>{fmt(run.started_at)}</dd>
                    <dt>Finished</dt>
                    <dd>{fmt(run.finished_at)}</dd>
                    <dt>Candles accepted</dt>
                    <dd>{run.accepted}</dd>
                    <dt>Quarantined</dt>
                    <dd className={run.quarantined ? "down" : ""}>{run.quarantined}</dd>
                  </dl>
                )}
              </div>
            );
          })}
        </section>
      )}
    </>
  );
}
