import { useWatchlist } from "../../hooks/useWatchlist";

export default function StarButton({ symbol, withLabel = false }) {
  const { has, toggle } = useWatchlist();
  const on = has(symbol);
  const label = on ? `Remove ${symbol} from watchlist` : `Add ${symbol} to watchlist`;
  return (
    <button type="button" className={`star ${on ? "on" : ""}`} aria-pressed={on} aria-label={label} title={label} onClick={() => toggle(symbol)}>
      <span aria-hidden="true">{on ? "★" : "☆"}</span>
      {withLabel && <span>{on ? " Watching" : " Watch"}</span>}
    </button>
  );
}
