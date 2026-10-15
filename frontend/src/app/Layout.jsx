import { useThemePreference } from "../hooks/useColorScheme";

const NAV = [
  ["strategies", "Strategies", "#/"],
  ["market", "Market", "#/market"],
  ["quotes", "Quotes", "#/quotes"],
  ["stock", "Stock", "#/stock"],
  ["backtest", "Backtest", "#/backtest"],
  ["status", "Pipeline", "#/status"],
];

const THEME_LABEL = { auto: "Auto", light: "☀ Light", dark: "☾ Dark" };

export default function Layout({ page, children }) {
  const [theme, cycleTheme] = useThemePreference();
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
          <button type="button" className="theme-switch" onClick={cycleTheme} title="Switch theme: auto, light, dark">
            <span className="sr-only">Theme: </span>{THEME_LABEL[theme]}
          </button>
        </div>
      </header>
      <main>{children}</main>
    </>
  );
}
