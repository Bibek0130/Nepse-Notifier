import { stockHref } from "../../app/router";
import { analysisApi } from "../../api/client";
import { useApi } from "../../hooks/useApi";
import { DirectionBadge, STRATEGY_LABELS } from "../signals/SignalsTable.jsx";

const num = (v, suffix = "", signed = false) =>
  v == null ? "–" : `${signed && v > 0 ? "+" : ""}${v}${suffix}`;

// How much to trust a strategy: does its average return after costs beat random buys on the same days?
function verdict(e) {
  if (!e) return null;
  if (e.settled < 20) return { tone: "muted", text: "Too few calls to judge" };
  const better = e.random_avg_return_pct != null ? e.avg_return_pct > e.random_avg_return_pct : e.hit_rate > e.chance_hit_rate;
  if (e.p_value != null && e.p_value < 0.05 && better) return { tone: "up", text: "Beats random buys" };
  if (e.p_value != null && e.p_value < 0.05) return { tone: "down", text: "Worse than random buys" };
  return { tone: "muted", text: "No better than random buys" };
}

function Metrics({ e, title }) {
  if (!e) return null;
  const v = verdict(e);
  return (
    <div className="strategy-metrics">
      <div className="strategy-metrics-head">
        <span className="muted small">{title}</span>
        {v && <span className={`small ${v.tone}`}>{v.text}</span>}
      </div>
      <dl className="facts">
        <div className="fact"><dt>Hit rate</dt><dd>{num(e.hit_rate, "%")} <span className="muted small">vs {num(e.chance_hit_rate, "%")} random</span></dd></div>
        <div className="fact"><dt>Calls settled</dt><dd>{e.settled}</dd></div>
        <div className="fact"><dt>Avg return per buy, after costs</dt><dd>{num(e.avg_return_pct, "%", true)}</dd></div>
        <div className="fact"><dt>Profit factor</dt><dd>{num(e.profit_factor)}</dd></div>
        <div className="fact"><dt>Max drawdown</dt><dd>{num(e.max_drawdown_pct, "%")}</dd></div>
        {e.mae_pct != null && <div className="fact"><dt>Target error (MAE)</dt><dd>{num(e.mae_pct, "%")}</dd></div>}
        {e.ms_per_bar != null && <div className="fact"><dt>Speed</dt><dd>{e.ms_per_bar} ms / stock-day</dd></div>}
      </dl>
    </div>
  );
}

function StrategyCard({ s }) {
  const ev = s.evaluation;
  const evalUrl = s.admin_id ? `/admin/quant/quantstrategy/${s.admin_id}/change/` : "/admin/quant/quantstrategy/";
  return (
    <section className={`panel strategy-card${s.featured ? " featured" : ""}${s.enabled ? "" : " off"}`}>
      <div className="strategy-head">
        <h3>{STRATEGY_LABELS[s.name] || s.name}</h3>
        <span className={`pill ${s.enabled ? "on" : ""}`}>{s.enabled ? "On" : "Off"}</span>
      </div>
      <p className="muted small strategy-desc">{s.description}</p>

      <div className="strategy-today">
        <strong>{s.today.count}</strong> <span className="muted">call{s.today.count === 1 ? "" : "s"} in the latest run</span>
        {s.today.signals.length > 0 && (
          <ul>
            {s.today.signals.map((x) => (
              <li key={`${x.symbol}-${x.direction}`}>
                <a href={stockHref(x.symbol)}>{x.symbol}</a> <DirectionBadge direction={x.direction} />
              </li>
            ))}
          </ul>
        )}
      </div>

      {ev ? (
        <>
          <Metrics e={ev.replay} title={`Replay ${ev.start_date} to ${ev.end_date}`} />
          <Metrics e={ev.live} title="Live predictions, same period" />
          {!ev.replay && !ev.live && <p className="muted small">Evaluated, but no settled calls in that period yet.</p>}
        </>
      ) : s.live && s.live.settled ? (
        <p className="small">Live hit rate {num(s.live.hit_rate, "%")} over {s.live.settled} settled calls. Not evaluated yet.</p>
      ) : (
        <p className="muted small">Not evaluated yet.</p>
      )}
      <a className="small" href={evalUrl}>{ev ? "Full evaluation" : "Evaluate accuracy and speed"} →</a>
    </section>
  );
}

export default function StrategiesPage() {
  const { loading, error, data } = useApi(() => analysisApi.strategies(), []);
  if (loading) return <p className="muted">Loading…</p>;
  if (error) return <p className="error">Could not load strategies: {error.message}</p>;
  const featured = data.strategies.filter((s) => s.featured);
  const others = data.strategies.filter((s) => !s.featured);
  return (
    <>
      <div className="section-head">
        <h1>Strategies</h1>
        {data.trading_date && (
          <span className="muted">
            Latest run {data.trading_date}
            {data.provisional ? " (intraday, provisional)" : " (end of day)"}
          </span>
        )}
      </div>
      <p className="muted">
        What each strategy is calling now and how accurate it has been. Accuracy comes from the latest evaluation in the
        Quant section of admin: a replay over past prices and the predictions actually sent, each checked against real prices.
      </p>
      <div className="strategy-grid">{featured.map((s) => <StrategyCard key={s.name} s={s} />)}</div>
      <h2>Other strategies</h2>
      <div className="strategy-grid">{others.map((s) => <StrategyCard key={s.name} s={s} />)}</div>
    </>
  );
}
