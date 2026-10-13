import { useMemo, useState } from "react";

import { stockHref } from "../../app/router";

export default function QuotesTable({ quotes }) {
  const [filter, setFilter] = useState("");
  const rows = useMemo(
    () => quotes.filter((q) => q.symbol.includes(filter.trim().toUpperCase())),
    [quotes, filter],
  );

  return (
    <section>
      <input className="filter" placeholder="Filter symbol" value={filter} onChange={(e) => setFilter(e.target.value)} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>LTP</th>
              <th>Change %</th>
              <th>High</th>
              <th>Low</th>
              <th>Volume</th>
              <th>Trades</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((q) => (
              <tr key={q.symbol}>
                <td><a href={stockHref(q.symbol)}>{q.symbol}</a></td>
                <td>{q.close}</td>
                <td className={q.change_percent > 0 ? "up" : q.change_percent < 0 ? "down" : ""}>
                  {q.change_percent ?? "-"}
                </td>
                <td>{q.high}</td>
                <td>{q.low}</td>
                <td>{q.volume.toLocaleString()}</td>
                <td>{q.trades ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
