# Hosted demo

A public, read-only copy of NEPSE Notifier for showing people: the dashboard, the API and a
view-only admin (including the Quant strategy metrics), with real NEPSE prices. It runs as one
container on Render's free plan. No Postgres, Redis or Celery, and nothing to pay.

## What the demo is

- **Real prices, loaded at build time.** The build downloads two years of daily prices for the
  98 stocks in `backend/demo/universe.csv` (with their sectors) from the public
  [Aabishkar2/nepse-data](https://github.com/Aabishkar2/nepse-data) archive. Hosted servers can't
  reach sharesansar or merolagani, so the live fetch is off. Prices are as NEPSE published
  them, not adjusted for bonus shares.
- **Everything computed the normal way.** `seed_demo` announces the latest 20 sessions one by
  one, so the usual analysis, predictions and their scoring run on them. Then
  `evaluate_strategies` and `backtest` run, and `verify_demo` stops the build if any page
  would be empty or any strategy is missing a hit rate, p-value or profit factor.
- **Read-only.** Every request that would change something gets a "read-only demo" page.
  That covers admin edits, "Evaluate all strategies" and email preferences. The only
  exception is logging in and out of the view-only admin account (`demo` / `nepse-demo`),
  which the login page shows.
- **No email.** Emails go to Django's in-memory backend, so nothing leaves the server, and the
  demo database has no subscribers.
- **Free plan limits.** Render's free plan sleeps after 15 idle minutes. The next visit takes
  about a minute to wake it, so open the link a minute before you present.

## Put it online (about 10 minutes, once)

1. Sign up at <https://dashboard.render.com/register> with **GitHub** (no card needed for the
   free plan).
2. In Render, choose **New → Blueprint**, connect GitHub when asked, and give Render access
   to the `Bibek0130/Nepse-Notifier` repository.
3. Pick the repository and branch `master`. Render reads `render.yaml` and shows one web
   service, `nepse-notifier-demo` (free). Click **Deploy Blueprint**.
4. The first build takes about 20 minutes: it downloads the prices and measures every
   strategy. When it says **Live**, open the `https://nepse-notifier-demo….onrender.com`
   link at the top of the service page.

Every push to `master` redeploys it with the latest prices.

### Optional: refresh prices twice a week

1. In Render, open the service, go to **Settings → Deploy Hook**, and copy the URL.
2. In GitHub, open the repository's **Settings → Secrets and variables → Actions → New
   repository secret**. Name it `RENDER_DEPLOY_HOOK` and paste the URL.

`.github/workflows/refresh-demo.yml` then redeploys on Wednesday and Friday mornings (Nepal time).
Each build takes about 20 minutes of the free plan's monthly build minutes, so twice a week
stays well inside them. Run it by hand from the repository's **Actions** tab before a demo.

## Try it on your own computer first

With Docker installed:

```
docker build -f Dockerfile.demo -t nepse-demo .
docker run -p 8000:8000 -e DJANGO_SECURE_COOKIES=false nepse-demo
```

Then open <http://localhost:8000>. `DJANGO_SECURE_COOKIES=false` lets the admin login work
over plain http. Leave it out on a host with https.

## Other hosts

`Dockerfile.demo` runs anywhere that runs a Docker image and gives it a `PORT`, for example
Koyeb, Fly.io or Railway. Set `DJANGO_ALLOWED_HOSTS` to the demo's hostname and
`DJANGO_SECRET_KEY` to a long random string. Render sets the hostname itself.

## Change what the demo shows

- **Stocks:** edit `backend/demo/universe.csv` (`symbol,sector`). Symbols must exist in the
  archive (`data/company-wise/SYMBOL.csv`).
- **Days of history and sessions analysed:** `seed_demo --days 730 --replay-sessions 20` in
  `Dockerfile.demo`.
- **Admin login:** set `DEMO_VIEWER_USERNAME` and `DEMO_VIEWER_PASSWORD` on the Render
  service. They are shown on the login page.
