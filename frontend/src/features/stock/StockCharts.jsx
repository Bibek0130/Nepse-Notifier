import { ColorType, CrosshairMode, LineStyle, createChart } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

import { cssVar, useColorScheme } from "../../hooks/useColorScheme";
import { rsi, sma } from "./indicators";

export const OVERLAYS = [
  { key: "sma20", label: "SMA 20", period: 20, color: "--series-1" },
  { key: "sma50", label: "SMA 50", period: 50, color: "--series-2" },
  { key: "sma200", label: "SMA 200", period: 200, color: "--series-3" },
];

function baseOptions(height, logo = false) {
  return {
    height,
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: cssVar("--panel") },
      textColor: cssVar("--muted"),
      fontFamily: getComputedStyle(document.body).fontFamily,
      attributionLogo: logo,
    },
    grid: { vertLines: { visible: false }, horzLines: { color: cssVar("--grid") } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false },
    crosshair: { mode: CrosshairMode.Normal },
    handleScroll: { vertTouchDrag: false },
  };
}

// Gaps stay as whitespace points so every chart has the same bar indexes and scrolls in step.
const line = (times, values) => values.map((v, i) => (v == null ? { time: times[i] } : { time: times[i], value: v }));

/** Price (candles + SMAs + support/resistance), volume and RSI as three stacked charts sharing one time axis. */
export default function StockCharts({ candles, analysis }) {
  const scheme = useColorScheme();
  const priceEl = useRef(null);
  const volumeEl = useRef(null);
  const rsiEl = useRef(null);
  const [hover, setHover] = useState(null);

  const data = useMemo(() => {
    const times = candles.map((c) => c.trading_date);
    const closes = candles.map((c) => Number(c.close));
    return {
      times,
      bars: candles.map((c, i) => ({
        time: times[i],
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: closes[i],
        volume: c.volume,
      })),
      overlays: Object.fromEntries(OVERLAYS.map((o) => [o.key, sma(closes, o.period)])),
      rsi: rsi(closes),
    };
  }, [candles]);

  useEffect(() => {
    const up = cssVar("--up");
    const down = cssVar("--down");
    const price = createChart(priceEl.current, baseOptions(340, true));
    const volume = createChart(volumeEl.current, baseOptions(110));
    const rsiChart = createChart(rsiEl.current, baseOptions(130));
    const charts = [price, volume, rsiChart];

    const candleSeries = price.addCandlestickSeries({
      upColor: up,
      downColor: down,
      wickUpColor: up,
      wickDownColor: down,
      borderVisible: false,
    });
    candleSeries.setData(data.bars);
    OVERLAYS.forEach((o) => {
      const s = price.addLineSeries({
        color: cssVar(o.color),
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      s.setData(line(data.times, data.overlays[o.key]));
    });
    if (analysis?.support != null) {
      candleSeries.createPriceLine({
        price: analysis.support, color: up, lineWidth: 1, lineStyle: LineStyle.Dashed, title: "Support",
      });
    }
    if (analysis?.resistance != null) {
      candleSeries.createPriceLine({
        price: analysis.resistance, color: down, lineWidth: 1, lineStyle: LineStyle.Dashed, title: "Resistance",
      });
    }

    const volSeries = volume.addHistogramSeries({ priceFormat: { type: "volume" }, priceLineVisible: false });
    volSeries.setData(
      data.bars.map((b) => ({ time: b.time, value: b.volume, color: b.close >= b.open ? up : down })),
    );

    const rsiSeries = rsiChart.addLineSeries({ color: cssVar("--series-1"), lineWidth: 2, priceLineVisible: false });
    rsiSeries.setData(line(data.times, data.rsi));
    [70, 30].forEach((level) =>
      rsiSeries.createPriceLine({ price: level, color: cssVar("--muted"), lineWidth: 1, lineStyle: LineStyle.Dotted, title: String(level) }),
    );
    rsiSeries.applyOptions({ autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) });

    // Keep the three charts scrolled and zoomed together.
    let syncing = false;
    charts.forEach((src) =>
      src.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (syncing || !range) return;
        syncing = true;
        charts.filter((c) => c !== src).forEach((c) => c.timeScale().setVisibleLogicalRange(range));
        syncing = false;
      }),
    );
    const index = Object.fromEntries(data.times.map((t, i) => [t, i]));
    charts.forEach((c) =>
      c.subscribeCrosshairMove((param) => setHover(param.time != null ? index[param.time] ?? null : null)),
    );
    price.timeScale().fitContent();

    return () => charts.forEach((c) => c.remove());
  }, [data, analysis, scheme]);

  const i = hover ?? data.bars.length - 1;
  const bar = data.bars[i];
  const fmt = (v) => (v == null ? "-" : v.toLocaleString(undefined, { maximumFractionDigits: 2 }));

  return (
    <div className="charts">
      <div className="chart-legend" aria-live="polite">
        <span className="muted">{bar?.time}</span>
        <span>O {fmt(bar?.open)}</span>
        <span>H {fmt(bar?.high)}</span>
        <span>L {fmt(bar?.low)}</span>
        <span className={bar && bar.close >= bar.open ? "up" : "down"}>C {fmt(bar?.close)}</span>
        {OVERLAYS.map((o) => (
          <span key={o.key} className="legend-item">
            <span className="swatch" style={{ background: `var(${o.color})` }} />
            {o.label} {fmt(data.overlays[o.key][i])}
          </span>
        ))}
      </div>
      <div ref={priceEl} className="chart" role="img" aria-label="Daily candles with moving averages" />
      <div className="chart-label">Volume <span className="muted">{fmt(bar?.volume)}</span></div>
      <div ref={volumeEl} className="chart" role="img" aria-label="Daily volume" />
      <div className="chart-label">RSI 14 <span className="muted">{fmt(data.rsi[i])}</span></div>
      <div ref={rsiEl} className="chart" role="img" aria-label="RSI 14" />
    </div>
  );
}
