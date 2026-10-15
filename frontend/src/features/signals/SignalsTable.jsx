import { stockHref } from "../../app/router";

export const STRATEGY_LABELS = {
  trend: "Trend",
  ma_cross: "MA cross",
  rsi: "RSI",
  macd: "MACD",
  breakout: "Breakout",
  volume: "Volume",
  transactions: "Transactions",
  forecast: "Forecast",
  ema_5_8_13: "5-8-13 EMA",
  pairs: "Pairs trading",
  basket_reversion: "Basket reversion",
  pca_leaders: "PCA sector leaders",
  quant_momentum: "Quant momentum",
  quant_reversion: "Quant mean reversion",
};

const ARROWS = { bullish: "▲", bearish: "▼", neutral: "■" };

export function DirectionBadge({ direction }) {
  const tone = direction === "bullish" ? "up" : direction === "bearish" ? "down" : "muted";
  return (
    <span className={`badge ${tone}`}>
      <span aria-hidden="true">{ARROWS[direction]}</span> {direction}
    </span>
  );
}

export function Strength({ value }) {
  return (
    <span className="strength" title={`Strength ${value} of 3`} aria-label={`Strength ${value} of 3`}>
      {[1, 2, 3].map((i) => (
        <span key={i} className={i <= value ? "on" : ""} />
      ))}
    </span>
  );
}

export default function SignalsTable({ signals, showSymbol = true }) {
  return (
    <div className="table-wrap">
      <table className="signals">
        <thead>
          <tr>
            {showSymbol && <th>Symbol</th>}
            <th>Strategy</th>
            <th>Direction</th>
            <th>Strength</th>
            <th>What happened</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s, i) => (
            <tr key={`${s.symbol}-${s.strategy}-${i}`}>
              {showSymbol && <td><a href={stockHref(s.symbol)}>{s.symbol}</a></td>}
              <td>{STRATEGY_LABELS[s.strategy] || s.strategy}</td>
              <td><DirectionBadge direction={s.direction} /></td>
              <td><Strength value={s.strength} /></td>
              <td className="message">{s.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
