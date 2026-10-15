# NEPSE Notifier

Collects NEPSE market data on a schedule, validates it, analyses it with known
technical strategies, and emails the results.

**Stack:** Django + Django REST Framework, React (Vite), PostgreSQL (system of
record), Redis (Celery broker, cache and locks), Celery workers + Celery Beat.

**Architecture:** a domain-oriented modular monolith. See
[docs/market-data-pipeline.md](docs/market-data-pipeline.md) for the full design.

## Status

| Step | State |
|---|---|
| 1. Market data pipeline (fetch, raw landing, validation, Postgres, Redis cache, events, API) | Done; not yet run against the live sites |
| 2. Analysis engine (indicators, support/resistance, strategies, forecast, signals) | Done |
| 3. Email digests (subscribers, per-subscriber filters, SMTP, unsubscribe) | Done |
| 4. React dashboard (overview and signals, stock charts, quotes, pipeline health), watchlists, backtesting | Done |

## Layout

```
backend/
  config/                  settings (base/dev/prod/test), Celery app, URLs
  modules/
    shared/                market calendar, domain event bus, Redis locks
    marketdata/            domain/ application/ infrastructure/ api/ + public.py
    analysis/              indicators, levels, strategies, signals; publishes SignalsGenerated
    notifications/         subscribers, digests, email delivery; subscribes to SignalsGenerated
    accounts/              users and watchlists
  .importlinter            module boundary rules, checked in CI
frontend/                  React app (src/features/<domain>/)
docker-compose.yml         postgres, redis, api, 3 workers, beat, frontend
```

Modules talk to each other only through `public.py` and domain events. Run
`lint-imports` in `backend/` to check the boundaries.

## The pipeline

Beat triggers `ingest_market` at 11:15 and 14:15 (intraday) and 15:15 (end of
day) Nepal time, Sunday to Thursday. Each run goes through these stages:

1. **Schedule:** skip if the market is closed (weekends and the `TradingHoliday` table) or another run holds the Redis lock.
2. **Fetch:** sharesansar first, then merolagani. A Redis circuit breaker skips a source after 3 failures for 15 minutes.
3. **Land raw:** gzip the response into `RawPayload`. If it's identical to the last fetch, the run is marked stale and stops.
4. **Normalise:** parse into `Quote`s, matching columns by header name.
5. **Validate:** OHLC consistency, volume and turnover sanity, the ±10% price band, trading date, duplicates, and a cross-source check at end of day. Bad candles go to `CandleIssue` without failing the run.
6. **Persist:** idempotent upsert into `Candle` (3H snapshots and 1D bars).
7. **Cache:** latest quotes and the market summary go into Redis.
8. **Publish:** `CandlesIngested` is dispatched to subscribers after the commit.

Every run is recorded in `IngestionRun`, with per-stage status. You can see it in Django admin and at `/api/market/runs`.

## Analysis

When `CandlesIngested` arrives, `analysis` starts an `AnalysisRun` and fans out one
`analyze_symbol` task per symbol as a Celery chord. `finish_run` then publishes
`SignalsGenerated` for notifications. End-of-day runs analyse the closing bars.
Intraday runs append the latest snapshot as a provisional bar for today.

| Strategy | Signal |
|---|---|
| `trend` | Golden or death cross: the 50-day SMA crosses the 200-day SMA (strength 3) |
| `ma_cross` | Close crosses the 50-day SMA (2) |
| `rsi` | RSI(14) at or above 70 is overbought, at or below 30 is oversold (1), and recovering out of either zone is stronger (2) |
| `macd` | MACD(12,26,9) crosses its signal line (2) |
| `ema_5_8_13` | 5-8-13 EMA strategy from [switchmarkets.com](https://www.switchmarkets.com/learn/technical-analysis-strategies): the 5-day EMA crosses above the 8 and 13 with price above all three is a buy, with a stop under the 5-day low and a 1:1 target; the mirror is an exit (2) |
| `breakout` | Close goes through yesterday's resistance or support: 3 with at least 1.5x average volume, 1 without |
| `volume` / `transactions` | Today's volume or number of trades is at least 2x the 20-day average |
| `pairs` | Pairs trading (statistical arbitrage): two stocks in the same sector (or, without sectors, among the 60 most traded) whose log-price spread is cointegrated over 120 sessions (Engle-Granger ADF t below -3.34, half-life up to 30 sessions, return correlation at least 0.5) and is now stretched 2 to 3.5 standard deviations. The stock that ran ahead is bearish, the one left behind bullish; target is the price where the spread is back at its mean, stop where it reaches 3.5 sd (2, or 3 at 3+ sd) |
| `basket_reversion` | Basket mean reversion: the same test of a stock against the equal-weighted basket of its sector peers (2, or 3 at 3+ sd) |
| `quant_momentum` | Momentum leg of [Poudel & Paudel (2025)](https://www.nepjol.info/index.php/qjmss/article/view/87782), a backtest on NEPSE: RSI(14) crosses above 60 while price is above its 240-day average; stop 4% under entry, target at 1:4.5 risk-reward, 4-day cooldown. A close back below the 240-day average is the exit (2) |
| `quant_reversion` | Mean-reversion leg of the same paper: close at least 1.5 standard deviations under its 15-day mean (z-score) with RSI at or below 35, still above the 240-day average; stop at the 70-day average (4% if that is above the price, never more than 8%), 1:4.5 target, 3-day cooldown (2) |
| `forecast` | A linear trend over 20 sessions with a good fit (R² ≥ 0.6) is projected 5 sessions ahead. It describes the trend and is not a prediction |

`pairs` and `basket_reversion` compare stocks with each other, so they run once over the
whole run in `finish_run` rather than per symbol (`modules/analysis/domain/stat_arb.py`).
Sectors come from `Instrument.sector`, which is filled in through Django admin.

Every strategy can be switched on or off in Django admin under **Analysis > Strategy
settings** (a row per strategy is created on the next run; new strategies start on).

The paper doesn't publish its exact entry thresholds, so the quant strategies use its base
case where it gives one and common defaults elsewhere (all in `StrategyConfig`). They need
about 240 sessions of history per stock and stay silent until it exists. Their predictions
use a 20-session horizon, since a 1:4.5 target needs room.

### Quant section in admin: accuracy and speed per strategy

Django admin has a **Quant** section listing every strategy with its latest hit rate,
p-value, profit factor, max drawdown and speed. Open one and press **Evaluate accuracy and
speed** (pick a period and, optionally, symbols). The evaluation runs in the background
(a Celery worker, or a thread on a laptop in local mode) and the page refreshes until it's done:

- **Replay over history** (per-stock strategies): walk-forward, each day seeing only the bars
  up to that day, with every call settled exactly like a live prediction (target, stop or horizon).
- **Accuracy**: hit rate with a 95% confidence interval, the chance level (calling every day the
  same way) and a p-value against it; how calls ended (target, stop, expired).
- **Forecast vs actual**: for calls with a price target, MAE, RMSE and bias between the target
  and the actual close at the horizon, and how often the target was reached.
- **Returns and risk**: average and median return, win/loss sizes, profit factor, edge over
  buying on any day, Sharpe and Sortino, an equity curve (25% of capital per call) with total
  return, CAGR and max drawdown, losing streaks, and a 1,000-run Monte Carlo bootstrap.
- **Speed**: milliseconds per stock-day for the whole analysis and for the strategy alone,
  sessions until calls resolve, and the live pipeline's time per run and per stock.
- **Live predictions**: the same measures over the predictions the system actually stored.
  `pairs` and `basket_reversion` compare stocks with each other, so they are scored on live
  predictions only.

Results are kept in `QuantEvaluation` (logic in `modules/analysis/domain/evaluation.py`).
A one-year replay over all ~350 stocks takes a few minutes (about 1.2 ms per stock-day).

### Predictions and the live track record

Each directional signal from a market-close run is stored as a `Prediction`: entry at the
close, the strategy's target and stop when it names them, and a horizon of 10 sessions
(5 for `forecast`). After every market-close run, open predictions are settled from the
actual daily prices: the first of target or stop touched decides it (stop if a bar touches
both), otherwise the close at the horizon. Each one records its exit, return and whether the
price moved the predicted way. The per-strategy track record (hit rate, average return in the
predicted direction, targets and stops hit) is at `GET /api/analysis/scorecard?days=180`,
in the closing email, and from `python manage.py score_predictions`. Predictions can be
browsed in admin. Unlike the weekly backtest, this measures what the system actually sent.

Support and resistance are clustered swing highs and lows (within 1.5%) from the
last 120 sessions. Thresholds live in `StrategyConfig`
(`modules/analysis/domain/strategies.py`).

Every analysed stock also gets trade levels (`modules/analysis/domain/trade_plan.py`),
stored in `SymbolAnalysis.trade_plan` and shown in the email digest:

| Level | How it is worked out |
|---|---|
| LTP, movement | Last price, change on the day and over 5 sessions; uptrend, downtrend or sideways from the 5-8-13 EMA ribbon |
| Buy zone | Nearest support up to half an ATR(14) above it (the 60-day swing low when there is no support) |
| Sell zone | Nearest resistance and half an ATR below it (the swing high, or 3 ATRs up at new highs, when there is none) |
| Correction zone | 38.2%-61.8% Fibonacci retracement of the 60-day swing |
| Stop loss / target | One ATR under the buy zone / the top of the sell zone |
| Risk : reward | (target - LTP) / (LTP - stop), for a buy at today's price |

## Email digests

`SignalsGenerated` triggers `on_signals_generated` on the `notify` queue. It builds one
`Digest` per analysis run and a personalised `Delivery` for each active `Subscriber`,
then sends each email as its own task, rate-limited to 30 a minute and retried on SMTP errors.
Re-running a digest never emails anyone twice.

Manage subscribers in Django admin (**Notifications → Subscribers**). Each subscriber has:

* **Min strength:** 1 for every signal, 2 for moderate and strong (the default), 3 for strong only.
* **Watchlist:** comma-separated symbols. Leave it blank to get all stocks.
* **Include intraday:** also receive the midday updates, not only the market-close digest.

Subscribers who have no matching signals that run get no email. Every email has a
one-click unsubscribe link (also in the `List-Unsubscribe` header).

Set `EMAIL_HOST` and related settings in `.env` to send through SMTP (Gmail, SES,
Mailgun and so on). Without `EMAIL_HOST`, emails print to the worker console. To check
the setup:

```bash
python manage.py send_test_digest you@example.com
```

## Watchlists in email

Every digest links to a settings page (`/notifications/preferences/<token>`) where a subscriber can set their watchlist, which signal strengths they get, and whether they get midday updates, or turn digests back on after unsubscribing. Symbols are checked against the listed stocks. Subscribers with a watchlist get a "Your watchlist" section with each watched stock's price and change. At market close they get it even on days with no signals; midday updates still go out only when there are signals.

## Backtesting

Every Friday at 03:00 (market closed) Beat replays all strategies over the past year, one day at a time, with the engine seeing only the bars it would have had on that day. Each signal is scored on the close-to-close return 5, 10 and 20 trading days later: a hit is a rise for a bullish signal and a fall for a bearish one. The baseline is the same measure over every day, signal or not, so a strategy is only useful if it beats it. Results are stored in `BacktestRun`, served at `GET /api/analysis/backtest`, and shown on the dashboard's Backtest page.

Run one by hand:

```bash
python manage.py backtest --days 365 [--end 2026-10-12] [--symbols NABIL NICA] [--min-strength 2]
```

## Dashboard

The React app (`frontend/`) has four pages, using hash routes so it can be served as static files:

| Page | Shows |
|---|---|
| Strategies (`#/`, the opening page) | Every strategy, the paper's quant strategies first: on or off, its calls in the latest run, and its latest Quant evaluation (hit rate against chance, average return, profit factor, drawdown, target error, speed), linking to the full evaluation in admin. Served by `GET /api/analysis/strategies` |
| Market (`#/market`) | Advancers, decliners and turnover, top movers, and the latest signals with direction and strength filters |
| Stock (`#/stock/NABIL`) | A year of daily candles with SMA 20/50/200 and support/resistance lines, volume and RSI charts that scroll together, the latest indicators, trend projection and signals |
| Quotes (`#/quotes`) | The latest snapshot for every symbol, filterable |
| Backtest (`#/backtest`) | How each strategy's past signals played out after 5, 10 and 20 trading days, against prices moving that way on any day |
| Pipeline (`#/status`) | The latest intraday, end-of-day and backfill run |

Star a stock (☆) on its page or in Quotes to add it to your watchlist. The Market page then shows your starred stocks' prices and signal counts, and Market and Quotes can be filtered to the watchlist. Starred stocks are saved in the browser.

Charts use [lightweight-charts](https://github.com/tradingview/lightweight-charts) and follow the OS light or dark setting.

## Run with Docker

```bash
cp .env.example .env
docker compose up --build
docker compose exec api python manage.py createsuperuser
docker compose exec api python manage.py ingest_market --force       # first fetch, creates instruments
docker compose exec api python manage.py backfill_history --days 365 # a year of daily bars
```

Then open the dashboard at http://localhost:5173, admin at http://localhost:8000/admin/, and the API at http://localhost:8000/api/market/summary.

## Run on a laptop with nothing else installed

`config.settings.local` needs only Python: data goes in `backend/local.sqlite3`, the cache in `backend/.cache/`, and each pipeline step (fetch, analyse, email) runs in the same process instead of on a Celery worker. Emails print to the terminal unless `EMAIL_HOST` is set. Works on Windows, macOS and Linux.

**On Windows, one command does all of it.** From the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-local.ps1
```

It creates the venv, installs packages, sets up the database, asks for an admin login the first time, fetches prices (and a year of history on the first run), then opens the server and the dashboard in their own windows. Run it again to fetch the latest prices. `-SkipFetch` starts the servers without fetching; `-NoServers` fetches without starting them.

To get digests by email instead of in the window:

```powershell
.\run-local.ps1 -Subscribe you@gmail.com   # add a subscriber
.\run-local.ps1 -SetupEmail                # once: Gmail address + app password, then a test email
```

Gmail needs an [app password](https://myaccount.google.com/apppasswords) (2-Step Verification must be on), not your normal password. It is saved in `backend/.env`, which git ignores and `config.settings.local` reads.

The same steps by hand:

```powershell
cd backend
python -m venv venv; .\venv\Scripts\activate      # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
$env:DJANGO_SETTINGS_MODULE = "config.settings.local"   # macOS/Linux: export DJANGO_SETTINGS_MODULE=config.settings.local
python manage.py migrate
python manage.py createsuperuser                     # to add subscribers in /admin
python manage.py backfill_history --days 365         # a year of prices, so the indicators have history
python manage.py ingest_market --kind eod --force    # today's prices, then analysis and the digest
python manage.py runserver                           # admin and API at http://localhost:8000
```

Without Beat there is no schedule: run `ingest_market` yourself, or from Windows Task Scheduler / cron at 11:15, 14:15 (`--kind intraday`) and 15:15 (`--kind eod`) Nepal time, Sunday to Thursday. For a server that runs on its own, use Docker or the setup below.

## Run without Docker

You need Postgres and Redis running locally (see `.env.example`).

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py ingest_market --force
celery -A config worker -Q default,ingest,analysis,notify -l info
celery -A config beat -l info

cd ../frontend && npm install && npm run dev
```

## Tests

```bash
cd backend
python manage.py test --settings=config.settings.test                    # SQLite + in-memory cache
TEST_WITH_POSTGRES=1 python manage.py test --settings=config.settings.test # against Postgres
lint-imports
```

## API

| Endpoint | Source |
|---|---|
| `GET /api/market/quotes/latest` | Redis, with a Postgres fallback |
| `GET /api/market/summary` | Redis, with a Postgres fallback |
| `GET /api/market/instruments` | Postgres |
| `GET /api/market/candles?symbol=NABIL&tf=1D&start=&end=` | Postgres |
| `GET /api/market/status` | Latest run of each kind, without error details |
| `GET /api/market/runs` (staff only) | Postgres |
| `GET /api/analysis/signals?direction=&min_strength=&run=` | Latest analysis run |
| `GET /api/analysis/backtest` | Latest backtest: per-strategy hit rates and returns by horizon and minimum strength |
| `GET /api/analysis/symbols/NABIL` | Latest indicators, levels, forecast and signals for one symbol |

## Caveats

* NEPSE has no official public API. Both sources are public websites whose
  layout can change. The scrapers are tested against sample pages modelled on
  each site but haven't been run against the live sites yet. When a layout
  changes, runs fall back to the next source and the failure shows up in
  `IngestionRun`. The raw page is kept for 30 days so it can be re-parsed after a fix.
