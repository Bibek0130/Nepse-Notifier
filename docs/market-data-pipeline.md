# Market Data Pipeline Plan

**Stack:** Django + Django REST Framework (API), React (frontend), PostgreSQL (system of record), Redis (Celery broker, cache, locks), Celery workers + Celery Beat (scheduling and task execution).

Celery runs the tasks, and Redis is what carries them. One Redis instance plays three roles in separate logical databases: `0` = Celery broker, `1` = Celery results, `2` = application cache and locks. Nothing in Redis is the source of truth. If it is wiped, Postgres still has everything.

---

## 1. Module layout (domain-oriented modular monolith)

One Django deployable, split into domain modules with hard boundaries.

```
backend/
  config/                  settings (base/dev/prod), celery.py, root urls
  modules/
    shared/                kernel: market calendar, Decimal/price types, base models, event bus
    marketdata/            instruments, quotes, candles, ingestion   <- this plan
    analysis/              indicators, strategies, signals
    notifications/         subscribers, digests, email dispatch
    accounts/              users, watchlists, preferences
frontend/                  React (Vite) app talking to /api/*
docker-compose.yml         postgres, redis, api, worker-ingest, worker-analysis, worker-notify, beat, frontend
```

Each module has the same internal shape:

```
marketdata/
  domain/          pure Python: Candle, Quote, Instrument, validation rules (no Django imports)
  application/     use cases: ingest_market(), backfill_history(), get_latest_quotes()
  infrastructure/  ORM models, repositories, source adapters (sharesansar, merolagani, nepalstock), Redis cache
  api/             DRF serializers, viewsets, urls
  tasks.py         thin Celery entry points that call application/
  events.py        events this module publishes
  public.py        the ONLY thing other modules may import
```

**Boundary rules**
- Modules never import each other's models or internals, only `public.py`.
- Modules never join across each other's tables. `analysis` reads candles through `marketdata.public.get_candles()`.
- Cross-module reactions go through domain events (`CandlesIngested`), which are dispatched as Celery tasks after the DB transaction commits (`transaction.on_commit`).
- Enforced in CI with `import-linter` contracts, so a violation fails the build.

---

## 2. The pipeline, stage by stage

```
Beat ─▶ [1 Schedule] ─▶ [2 Fetch] ─▶ [3 Land raw] ─▶ [4 Normalise] ─▶ [5 Validate] ─▶ [6 Persist] ─▶ [7 Cache] ─▶ [8 Publish event]
                                                                          │
                                                                          └─▶ quarantine (bad candles, with reason)
```

| # | Stage | What happens | Where it lives |
|---|---|---|---|
| 1 | **Schedule** | Beat fires `marketdata.ingest_market` at 11:15, 14:15 (intraday) and 15:15 (end of day) NPT. The task first checks the **market calendar** (Sun–Thu, minus NEPSE holidays held in a `TradingHoliday` table) and exits if the market is closed. A **Redis lock** stops two runs overlapping. Schedules live in the DB (`django-celery-beat`) so you can change them in admin without deploying. | `shared/calendar`, `marketdata/tasks.py` |
| 2 | **Fetch** | Source adapters behind one `MarketDataSource` interface, tried in priority order: sharesansar → merolagani → nepalstock unofficial API. Each has a timeout, retries with backoff, and a **circuit breaker in Redis**: after 3 failures a source is skipped for 15 minutes. | `marketdata/infrastructure/sources/` |
| 3 | **Land raw** | The untouched response (HTML/JSON, gzipped) is saved in `RawPayload` with source, fetch time and content hash. If the hash matches the last fetch, the site hasn't updated, so the run is marked *stale* and stops. Raw data is kept 30 days so we can re-parse after fixing a scraper. | `marketdata/infrastructure` |
| 4 | **Normalise** | The parser turns the raw payload into canonical `Quote` objects (symbol, OHLC, LTP, prev close, volume, turnover, trades). Columns are matched by header name to survive layout tweaks. | `marketdata/infrastructure/sources/` |
| 5 | **Validate** | Domain rules on every candle (listed below). Good candles move on. Bad ones go to `CandleIssue` with the rule that failed, and do not block the rest of the run. | `marketdata/domain/validation.py` |
| 6 | **Persist** | Upsert into `Candle(instrument, timeframe, ts)` with a unique key, so re-runs are idempotent. Timeframes: `3H` snapshots and `1D` bars. Each run is recorded in `IngestionRun` with per-stage status and counts. | Postgres |
| 7 | **Cache** | Write latest quotes and the market summary (gainers, losers, turnover leaders) to Redis with a TTL. The React dashboard reads these through DRF without touching Postgres. | `marketdata/infrastructure/cache.py` |
| 8 | **Publish** | On commit, emit `CandlesIngested(run_id, timeframe, trading_date)`. `analysis` subscribes and fans out one task per symbol (Celery `chord`). When all finish, `notifications` builds the digest and queues emails. | `marketdata/events.py` |

### Candle validation rules (stage 5)

| Rule | Example of what it catches |
|---|---|
| OHLC consistency: `low ≤ open, close ≤ high`, all prices > 0 | Parser read the wrong column |
| Volume ≥ 0, turnover ≈ VWAP × volume (within tolerance) | Shifted or merged cells |
| Circuit band: close within NEPSE's ±10% of previous close | Typos, or a corporate action |
| Trading date is a market day and not in the future | Site still showing yesterday's table |
| No duplicate symbol in one fetch | Pagination or rendering glitch |
| Cross-source check: if a second source is available, close prices agree within 0.5% | One site is lagging or wrong |
| Gap check: a price jump >10% with a bonus or rights announcement is flagged *adjust*, not rejected | Bonus shares, rights issues |

Corporate actions get a `CorporateAction` table. Analysis reads **adjusted** prices so a bonus issue doesn't look like a crash.

---

## 3. Data model (marketdata, Postgres)

| Table | Purpose |
|---|---|
| `Instrument` | symbol, name, sector, instrument type, listed/active |
| `Candle` | instrument, timeframe (`3H`/`1D`), ts, OHLC, volume, turnover, trades, source. Unique on (instrument, timeframe, ts), indexed on (timeframe, ts) |
| `RawPayload` | source, fetched_at, content_hash, gzipped body (30-day retention) |
| `IngestionRun` | kind (intraday/eod/backfill), status per stage, source used, row counts, errors |
| `CandleIssue` | run, symbol, rule failed, offending values, resolved flag |
| `CorporateAction` | instrument, type (bonus/rights/split/dividend), ratio, book-close date |
| `TradingHoliday` | date, description |

Plain Postgres is enough at NEPSE's size (~350 symbols × a few rows a day). TimescaleDB is an optional later upgrade, not needed now.

---

## 4. Celery setup

| Queue | Worker | Tasks |
|---|---|---|
| `ingest` | `worker-ingest` (concurrency 2) | ingest_market, backfill_history (rate-limited per source) |
| `analysis` | `worker-analysis` (concurrency = CPU cores) | analyze_symbol, aggregate_signals |
| `notify` | `worker-notify` (concurrency 2, rate-limited) | build_digest, send_email |
| — | `beat` (exactly one instance) | the schedule |

- Tasks take IDs, not objects, and are idempotent (keyed by run_id), so retries are safe.
- `acks_late=True` + `task_reject_on_worker_lost=True` so a crashed worker's task is retried, not lost.
- Flower for monitoring tasks; an admin email when every source fails or a run is quarantined above a threshold.

---

## 5. API for React (DRF, read-only for this module)

| Endpoint | Backed by |
|---|---|
| `GET /api/market/quotes/latest` | Redis cache |
| `GET /api/market/summary` | Redis cache |
| `GET /api/market/instruments` | Postgres |
| `GET /api/market/candles?symbol=NABIL&tf=1D&from=…` | Postgres (paginated) |
| `GET /api/market/runs` (admin only) | Postgres: pipeline health |

---

## 6. How this changes the existing step 1 code

The scrapers, fallback logic and tests carry over. They move into `modules/marketdata/infrastructure/sources/`. What's new: the module layout and boundaries, raw landing, validation and quarantine, the Redis lock and circuit breaker, the calendar check, events, DRF endpoints, docker-compose, and the React shell.

## 7. Build order

1. Restructure into the modular layout, add docker-compose (Postgres, Redis, workers, Beat), and add the import-linter contracts.
2. Pipeline stages 1–6 with tests, then the first live run on your Mac.
3. Redis cache, events, and the DRF endpoints.
4. React shell showing latest quotes and pipeline health. (Analysis and email modules follow as their own steps.)
