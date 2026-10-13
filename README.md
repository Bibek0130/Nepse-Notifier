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
| 3. Email digests | Planned |
| 4. React dashboard | Shell showing the latest quotes and market summary |

## Layout

```
backend/
  config/                  settings (base/dev/prod/test), Celery app, URLs
  modules/
    shared/                market calendar, domain event bus, Redis locks
    marketdata/            domain/ application/ infrastructure/ api/ + public.py
    analysis/              indicators, levels, strategies, signals; publishes SignalsGenerated
    notifications/         email digests (step 3)
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
| `GET /api/market/runs` (staff only) | Postgres |
| `GET /api/analysis/signals?direction=&min_strength=&run=` | Latest analysis run |
| `GET /api/analysis/symbols/NABIL` | Latest indicators, levels, forecast and signals for one symbol |

## Caveats

* NEPSE has no official public API. Both sources are public websites whose
  layout can change. The scrapers are tested against sample pages modelled on
  each site but haven't been run against the live sites yet. When a layout
  changes, runs fall back to the next source and the failure shows up in
  `IngestionRun`. The raw page is kept for 30 days so it can be re-parsed after a fix.
