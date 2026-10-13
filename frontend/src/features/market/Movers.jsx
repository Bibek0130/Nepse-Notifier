import { stockHref } from "../../app/router";

function List({ title, rows, field }) {
  return (
    <div className="panel">
      <h3>{title}</h3>
      {!rows.length && <p className="muted small">None today.</p>}
      <table className="compact">
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol}>
              <td><a href={stockHref(r.symbol)}>{r.symbol}</a></td>
              <td>{r.close}</td>
              <td className={field === "change_percent" ? (r.change_percent > 0 ? "up" : "down") : ""}>
                {field === "change_percent" ? `${r.change_percent > 0 ? "+" : ""}${r.change_percent}%` : Math.round(Number(r.turnover)).toLocaleString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Movers({ summary }) {
  if (!summary?.symbols) return null;
  return (
    <section className="grid-3">
      <List title="Top gainers" rows={summary.top_gainers.filter((r) => r.change_percent > 0).slice(0, 5)} field="change_percent" />
      <List title="Top losers" rows={summary.top_losers.filter((r) => r.change_percent < 0).slice(0, 5)} field="change_percent" />
      <List title="Most traded" rows={summary.top_turnover.slice(0, 5)} field="turnover" />
    </section>
  );
}
