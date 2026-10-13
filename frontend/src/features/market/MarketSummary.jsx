export default function MarketSummary({ summary }) {
  if (!summary || !summary.symbols) return null;
  const tiles = [
    ["Advancers", summary.advancers, "up"],
    ["Decliners", summary.decliners, "down"],
    ["Unchanged", summary.unchanged, ""],
    ["Turnover (Rs)", Math.round(Number(summary.total_turnover)).toLocaleString(), ""],
  ];
  return (
    <section className="tiles" aria-label="Market summary">
      {tiles.map(([label, value, tone]) => (
        <div className="tile" key={label}>
          <div className="tile-label">{label}</div>
          <div className={`tile-value ${tone}`}>{value}</div>
        </div>
      ))}
    </section>
  );
}
