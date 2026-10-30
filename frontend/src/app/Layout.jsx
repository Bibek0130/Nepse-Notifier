import { marketApi } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useThemePreference } from "../hooks/useColorScheme";

// Set VITE_DEMO=1 when building the hosted demo (Dockerfile.demo).
const DEMO = import.meta.env.VITE_DEMO === "1";

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
      {DEMO && <DemoNotice />}
      <main>{children}</main>
    </>
  );
}

function DemoNotice() {
  const { data } = useApi(() => marketApi.summary(), []);
  const asOf = data?.as_of ? new Date(data.as_of).toLocaleDateString(undefined, { dateStyle: "medium" }) : null;
  return (
    <p className="demo-notice" role="note">
      Demo with real NEPSE prices{asOf ? ` up to ${asOf}` : ""}. Read-only: live fetching and emails are off.
      {" "}<a href="/admin/">Admin (view only)</a>
    </p>
  );
}
