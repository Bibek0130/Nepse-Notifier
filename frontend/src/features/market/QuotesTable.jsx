import { useMemo, useState } from "react";

import { stockHref } from "../../app/router";
import { useWatchlist } from "../../hooks/useWatchlist";
import StarButton from "../watchlist/StarButton.jsx";

export default function QuotesTable({ quotes }) {
  const [filter, setFilter] = useState("");
  const [watchOnly, setWatchOnly] = useState(false);
  const watchlist = useWatchlist();
  const rows = useMemo(
    () => quotes.filter((q) => q.symbol.includes(filter.trim().toUpperCase()) && (!watchOnly || watchlist.has(q.symbol))),
    [quotes, filter, watchOnly, watchlist],
  );

  return (
    <section>
      <div className="filters">
        <input className="filter" placeholder="Filter symbol" aria-label="Filter symbol" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <label className="check">
          <input type="checkbox" checked={watchOnly} onChange={(e) => setWatchOnly(e.target.checked)} /> Watchlist only
        </label>
      </div>
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
                <td><StarButton symbol={q.symbol} /> <a href={stockHref(q.symbol)}>{q.symbol}</a></td>
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
