"""PCA sector leaders: explain a sideways market with principal components, then buy its drivers.

From Piyush-Quant, "Explaining NEPSE Sideways Market using PCA + Stock Selection Strategy"
(github.com/Piyush-Quant/Trading-Strategies-Nepal-, 2023-12 to 2024-07). In that study the
index went sideways because its heaviest sectors (Banking, Life Insurance) were falling
while the rest rose. PCA on sector indices showed which sectors drive the market, PCA inside
those sectors showed which stocks drive each sector, and once the driver sectors turned up,
their high-loading stocks (LICN, NMB, Nabil) gained 50-80%.

Rules here:
1. The market (equal-weighted over all stocks) moved less than ``SIDEWAYS_PCT`` over the window.
2. PCA on the sectors' daily returns; the sectors weighing most on the first component are drivers.
3. A driver sector that fell over the window and today closes back above its 20-day average
   has reversed (a close above its 20-day high counts as a breakout, a stronger call).
4. PCA inside that sector; its highest-loading stocks get the buy call.

When fewer than ``MIN_SECTORS`` sectors are known, the most-traded stocks are treated as one
group and its first component (a loading-weighted index) plays the driver. NEPSE is long only,
so the strategy only makes buy calls. Pure Python.
"""
import math
from dataclasses import dataclass

from .entities import Direction, Signal

STRATEGY = "pca_leaders"
LOOKBACK = 120  # sessions the PCA and the sideways test look at
SIDEWAYS_PCT = 10.0  # market move over the window, either way, that still counts as sideways
REVERSAL_MA = 20  # a driver sector closing back above this average has turned up
DRIVERS = 2  # sectors taken from the top of the first component
LEADERS = 3  # stocks taken from the top of each driver sector's first component
MARKET_LEADERS = 5  # stocks taken when sectors are unknown
LEADER_SHARE = 0.5  # a leader's loading must be at least this share of the top one
MIN_SECTORS = 3
MIN_MEMBERS = 2
MIN_COVERAGE = 0.9  # share of the window's sessions a stock must actually have traded
STOP_SESSIONS = 10  # stop under the lowest close of this many sessions
MAX_STOP_PCT = 10.0
REWARD_RISK = 3.0
COMPONENTS = 3  # components whose explained variance is reported (the study's top 3 explained 84%)


@dataclass(frozen=True)
class Component:
    eigenvalue: float
    explained: float  # share of total variance, 0-1
    loadings: dict  # variable name -> loading, signed so they sum to a positive number


def _standardize(xs):
    n = len(xs)
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return [(x - mean) / sd for x in xs] if sd > 0 else None


def principal_components(returns_by_name, k=COMPONENTS, iterations=200):
    """Top ``k`` principal components of the correlation matrix of ``returns_by_name`` (name -> equal-length list).

    Power iteration with deflation; variables that never moved are left out.
    """
    z = {name: s for name, s in ((n, _standardize(r)) for n, r in returns_by_name.items()) if s}
    names = sorted(z)
    if len(names) < 2:
        return []
    t = len(z[names[0]])
    corr = [[sum(a * b for a, b in zip(z[i], z[j])) / (t - 1) for j in names] for i in names]
    n, total, out = len(names), float(len(names)), []
    for _ in range(min(k, n)):
        v = [1.0 / math.sqrt(n)] * n
        value = 0.0
        for _ in range(iterations):
            w = [sum(row[j] * v[j] for j in range(n)) for row in corr]
            norm = math.sqrt(sum(x * x for x in w))
            if norm < 1e-12:
                break
            nv = [x / norm for x in w]
            converged = sum(abs(a - b) for a, b in zip(nv, v)) < 1e-10
            v, value = nv, norm
            if converged:
                break
        if value < 1e-9:
            break
        if sum(v) < 0:
            v = [-x for x in v]
        out.append(Component(value, value / total, dict(zip(names, v))))
        corr = [[corr[i][j] - value * v[i] * v[j] for j in range(n)] for i in range(n)]
    return out


def calendar_closes(dates_by_symbol, closes_by_symbol, symbols, sessions):
    """Closes of ``symbols`` on the last ``sessions`` market dates, carried forward over days a stock didn't trade.

    Stocks that traded on fewer than ``MIN_COVERAGE`` of those days, or have no close at the start, are dropped.
    """
    calendar = sorted(set().union(*(dates_by_symbol[s] for s in symbols)))[-sessions:] if symbols else []
    if len(calendar) < sessions:
        return calendar, {}
    out = {}
    for s in symbols:
        by_date = dict(zip(dates_by_symbol[s], closes_by_symbol[s]))
        before = [c for d, c in zip(dates_by_symbol[s], closes_by_symbol[s]) if d < calendar[0]]
        last = before[-1] if before else None
        seen, row = 0, []
        for d in calendar:
            if d in by_date:
                last, seen = by_date[d], seen + 1
            row.append(last)
        if row[0] is not None and seen >= MIN_COVERAGE * sessions:
            out[s] = row
    return calendar, out


def log_returns(prices):
    return [math.log(b / a) for a, b in zip(prices[:-1], prices[1:])]


def weighted_index(closes, weights):
    """Index (starts at 100) of ``closes`` (symbol -> prices) weighted by ``weights`` (symbol -> weight >= 0)."""
    total = sum(weights.values())
    if total <= 0:
        return None
    length = len(next(iter(closes.values())))
    return [sum(w * closes[s][i] / closes[s][0] for s, w in weights.items()) / total * 100 for i in range(length)]


def _equal_index(closes, members):
    return weighted_index(closes, {m: 1.0 for m in members})


def reversal(index, ma=REVERSAL_MA):
    """(turned_up, breakout, change_pct) for an index that fell over the window and today closed back above its average."""
    if len(index) < ma + 2:
        return False, False, 0.0
    avg_now = sum(index[-ma:]) / ma
    avg_before = sum(index[-ma - 1:-1]) / ma
    change = (index[-2] / index[0] - 1) * 100
    turned = change < 0 and index[-2] <= avg_before and index[-1] > avg_now
    return turned, turned and index[-1] > max(index[-ma - 1:-1]), change


def _levels(prices):
    close = prices[-1]
    stop = max(min(prices[-STOP_SESSIONS - 1:-1]), close * (1 - MAX_STOP_PCT / 100))
    if stop >= close:
        stop = close * 0.95
    return round(stop, 2), round(close + REWARD_RISK * (close - stop), 1)


def _top(loadings, n):
    return sorted(((s, w) for s, w in loadings.items() if w > 0), key=lambda x: -x[1])[:n]


def _first_component(closes, members):
    comps = principal_components({m: log_returns(closes[m]) for m in members}, k=1)
    return comps[0] if comps else None


def _leader_signals(group, closes, loadings, n, strength, context, group_weight):
    out, top = [], _top(loadings, n)
    for symbol, weight in top:
        if weight < LEADER_SHARE * top[0][1]:
            break
        stop, target = _levels(closes[symbol])
        out.append((symbol, Signal(
            STRATEGY, Direction.BULLISH, strength,
            f"PCA leader: {context}; {symbol} leads it (weight {weight:.2f}). Stop {stop:g}, 1:{REWARD_RISK:g} target {target:g}",
            {**group_weight, "group": group, "stock_loading": round(weight, 3), "stop": stop, "target": target},
        )))
    return out


def scan(dates_by_symbol, closes_by_symbol, groups, lookback=LOOKBACK):
    """Buy calls on the leaders of driver sectors that just turned up in a sideways market. Returns [(symbol, Signal)].

    ``groups`` maps a sector (or "market", for stocks whose sector is unknown) to its symbols.
    """
    symbols = sorted({s for members in groups.values() for s in members if closes_by_symbol.get(s)})
    _, closes = calendar_closes(dates_by_symbol, closes_by_symbol, symbols, lookback + 1)
    if len(closes) < MIN_MEMBERS:
        return []
    market = _equal_index(closes, list(closes))
    market_move = (market[-1] / market[0] - 1) * 100
    if abs(market_move) > SIDEWAYS_PCT:
        return []
    sideways = f"market {market_move:+.1f}% in {lookback} sessions"

    sectors = {
        name: [m for m in members if m in closes]
        for name, members in groups.items() if name != "market"
    }
    sectors = {name: members for name, members in sectors.items() if len(members) >= MIN_MEMBERS}

    if len(sectors) >= MIN_SECTORS:
        indices = {name: _equal_index(closes, members) for name, members in sectors.items()}
        comps = principal_components({name: log_returns(ix) for name, ix in indices.items()})
        if not comps:
            return []
        first_pct = round(comps[0].explained * 100, 1)
        explained = round(sum(c.explained for c in comps) * 100, 1)
        found = []
        for sector, loading in _top(comps[0].loadings, DRIVERS):
            turned, breakout, change = reversal(indices[sector])
            if not turned:
                continue
            context = (f"{sector} drives the sideways market (sector weight {loading:.2f}, {sideways}) and turned up "
                       f"after {change:+.1f}%" + (", breaking its 20-day high" if breakout else ""))
            weights = {"sector_loading": round(loading, 3), "first_component_pct": first_pct, "explained_pct": explained,
                       "sector_change_pct": round(change, 1), "market_change_pct": round(market_move, 1)}
            inside = _first_component(closes, sectors[sector])
            if inside:
                found += _leader_signals(sector, closes, inside.loadings, LEADERS, 3 if breakout else 2, context, weights)
        return found

    # Sectors unknown: the first component of the most-traded stocks is the market's driver.
    members = [m for m in groups.get("market", symbols) if m in closes]
    first = _first_component(closes, members)
    if not first:
        return []
    factor = weighted_index(closes, {s: max(w, 0.0) for s, w in first.loadings.items()})
    turned, breakout, change = reversal(factor)
    if not turned:
        return []
    context = (f"the sideways market's main PCA factor ({sideways}; sectors not set) turned up after "
               f"{change:+.1f}%" + (", breaking its 20-day high" if breakout else ""))
    weights = {"first_component_pct": round(first.explained * 100, 1), "sector_change_pct": round(change, 1),
               "market_change_pct": round(market_move, 1)}
    return _leader_signals("the market", closes, first.loadings, MARKET_LEADERS, 3 if breakout else 2, context, weights)
