import { marketApi } from "../../api/client";
import { stockHref } from "../../app/router";
import { useApi } from "../../hooks/useApi";
import { useWatchlist } from "../../hooks/useWatchlist";
import StarButton from "./StarButton.jsx";

/** Latest price of each starred stock, with how many of today's signals mention it. */
export default function WatchlistPanel({ signals }) {
  const { symbols } = useWatchlist();
  const quotes = useApi(() => marketApi.latestQuotes(), []);
  const bySymbol = Object.fromEntries((quotes.data || []).map((q) => [q.symbol, q]));
  const counts = {};
  (signals || []).forEach((s) => {
    counts[s.symbol] = (counts[s.symbol] || 0) + 1;
  });

  return (
    <section className="panel watchlist">
      <h3>Your watchlist</h3>
      {!symbols.length ? (
        <p className="muted small">
          Star a stock (☆) on its page or in Quotes to keep an eye on it here. Starred stocks are saved in this browser.
        </p>
      ) : (
        <table className="compact">
          <tbody>
            {symbols.map((symbol) => {
              const q = bySymbol[symbol];
              const change = q?.change_percent;
              return (
                <tr key={symbol}>
                  <td><StarButton symbol={symbol} /> <a href={stockHref(symbol)}>{symbol}</a></td>
                  <td>{q ? q.close : <span className="muted">no price</span>}</td>
                  <td className={change > 0 ? "up" : change < 0 ? "down" : "muted"}>
                    {change == null ? "" : `${change > 0 ? "+" : ""}${change}%`}
                  </td>
                  <td className="muted small">
                    {counts[symbol] ? `${counts[symbol]} signal${counts[symbol] === 1 ? "" : "s"}` : "no signals"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
