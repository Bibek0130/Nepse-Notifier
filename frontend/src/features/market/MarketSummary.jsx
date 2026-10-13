export default function MarketSummary({ summary }) {
  if (!summary || !summary.symbols) return null;
  const tiles = [
    ["Symbols", summary.symbols],
    ["Advancers", summary.advancers],
    ["Decliners", summary.decliners],
    ["Unchanged", summary.unchanged],
    ["Turnover (Rs)", Number(summary.total_turnover).toLocaleString()],
  ];
  return (
    <section className="tiles">
      {tiles.map(([label, value]) => (
        <div className="tile" key={label}>
          <div className="tile-label">{label}</div>
          <div className="tile-value">{value}</div>
        </div>
      ))}
    </section>
  );
}
