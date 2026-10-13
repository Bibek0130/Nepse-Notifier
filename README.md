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
| 4. React dashboard (overview and signals, stock charts, quotes, pipeline health) | Done, with watchlists; backtesting still to come |

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
| `breakout` | Close goes through yesterday's resistance or support: 3 with at least 1.5x average volume, 1 without |
| `volume` / `transactions` | Today's volume or number of trades is at least 2x the 20-day average |
| `forecast` | A linear trend over 20 sessions with a good fit (R² ≥ 0.6) is projected 5 sessions ahead. It describes the trend and is not a prediction |

Support and resistance are clustered swing highs and lows (within 1.5%) from the
last 120 sessions. Thresholds live in `StrategyConfig`
(`modules/analysis/domain/strategies.py`).

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

## Dashboard

The React app (`frontend/`) has four pages, using hash routes so it can be served as static files:

| Page | Shows |
|---|---|
| Overview (`#/`) | Advancers, decliners and turnover, top movers, and the latest signals with direction and strength filters |
| Stock (`#/stock/NABIL`) | A year of daily candles with SMA 20/50/200 and support/resistance lines, volume and RSI charts that scroll together, the latest indicators, trend projection and signals |
| Quotes (`#/quotes`) | The latest snapshot for every symbol, filterable |
| Pipeline (`#/status`) | The latest intraday, end-of-day and backfill run |

Star a stock (☆) on its page or in Quotes to add it to your watchlist. The overview then shows your starred stocks' prices and signal counts, and Overview and Quotes can be filtered to the watchlist. Starred stocks are saved in the browser.

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
| `GET /api/analysis/symbols/NABIL` | Latest indicators, levels, forecast and signals for one symbol |

## Caveats

* NEPSE has no official public API. Both sources are public websites whose
  layout can change. The scrapers are tested against sample pages modelled on
  each site but haven't been run against the live sites yet. When a layout
  changes, runs fall back to the next source and the failure shows up in
  `IngestionRun`. The raw page is kept for 30 days so it can be re-parsed after a fix.
