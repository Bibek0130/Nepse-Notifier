const NAV = [
  ["overview", "Overview", "#/"],
  ["quotes", "Quotes", "#/quotes"],
  ["stock", "Stock", "#/stock"],
  ["backtest", "Backtest", "#/backtest"],
  ["status", "Pipeline", "#/status"],
];

export default function Layout({ page, children }) {
  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="#/">NEPSE Notifier</a>
          <nav>
            {NAV.map(([key, label, href]) => (
              <a key={key} href={href} className={page === key ? "active" : ""} aria-current={page === key ? "page" : undefined}>
                {label}
              </a>
            ))}
          </nav>
        </div>
      </header>
      <main>{children}</main>
    </>
  );
}
