"""Admin "Quant" section: every strategy, and a page per strategy that checks its accuracy and speed."""
import threading

from django.conf import settings
from django.contrib import admin, messages
from django.db import connection
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from modules.analysis.application import quant
from modules.analysis.application.strategies import sync_settings
from modules.analysis.infrastructure.models import QuantEvaluation, QuantStrategy
from modules.analysis.tasks import evaluate_strategy

PERIODS = [(90, "3 months"), (180, "6 months"), (365, "1 year"), (730, "2 years")]


def dispatch(evaluation_id):
    """Run on a Celery worker; on a laptop without one (eager mode) run in a background thread instead."""
    if not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        evaluate_strategy.delay(evaluation_id)
        return

    def work():
        try:
            quant.run_evaluation(evaluation_id)
        finally:
            connection.close()

    threading.Thread(target=work, daemon=True).start()


def evaluate_all():
    """Start an evaluation for each strategy without one running. Returns the started evaluations."""
    started = quant.start_all()
    if started:
        dispatch_many([ev.pk for ev in started])
    return started


def dispatch_many(evaluation_ids):
    """Like ``dispatch``, but one background thread runs them in turn so a laptop isn't swamped."""
    if not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        for pk in evaluation_ids:
            evaluate_strategy.delay(pk)
        return

    def work():
        try:
            for pk in evaluation_ids:
                quant.run_evaluation(pk)
        finally:
            connection.close()

    threading.Thread(target=work, daemon=True).start()


def _num(value, suffix="", signed=False):
    if value is None:
        return "–"
    return f"{value:+g}{suffix}" if signed else f"{value:g}{suffix}"


def _p(value):
    return "–" if value is None else "< 0.0001" if value < 0.0001 else f"{value:g}"


def metric_sections(m):
    """Label, value and a one-line explanation for each measure, grouped for the page."""
    if not m or not m.get("settled") and not m.get("calls"):
        return []
    a, f, r, k, s = m["accuracy"], m["forecast_error"], m["returns"], m["risk"], m["speed"]
    ci = a.get("hit_rate_ci95") or [None, None]
    mc = k.get("monte_carlo") or {}
    c = m.get("costs") or {}
    x = m.get("exit_warnings") or {}
    sections = [
        ("Accuracy: did buying on these calls make money?", [
            ("Buy calls", f"{m['calls']} ({m['settled']} settled, {m['open']} still open)",
             "Bought at the next session's open; NEPSE can't be sold short, so sell calls are scored below as exit warnings"),
            ("Hit rate", _num(a["hit_rate"], "%"), "Share of settled buys that made money after costs and tax"),
            ("95% range", f"{_num(ci[0], '%')} to {_num(ci[1], '%')}", "Where the true hit rate likely sits; narrow means enough calls to trust it"),
            ("Random buys", _num(a["chance_hit_rate"], "%"),
             "Hit rate of buying a random stock on the same days, with the same stop, target and holding period"),
            ("p-value", _p(a["p_value"]),
             f"Below 0.05: the average return is unlikely to be luck, compared with {a.get('random_runs', 0)} sets of random buys"),
            ("Target / stop / expired", f"{_num(a['targets_hit_pct'], '%')} / {_num(a['stops_hit_pct'], '%')} / {_num(a['expired_pct'], '%')}",
             "How buys ended: target touched first, stop touched first, or sold at the horizon"),
        ]),
        ("Forecast vs actual price", [
            ("Calls with a target", f"{f['calls_with_target']} (target reached {_num(f['target_reached_pct'], '%')})", "Buys that named a price target"),
            ("Mean absolute error", _num(f["mae_pct"], "%"), "Average gap between the target and the actual close at the horizon"),
            ("Root mean square error", _num(f["rmse_pct"], "%"), "Like MAE but punishes big misses more"),
            ("Bias", _num(f["bias_pct"], "%", signed=True), "Negative: targets were too optimistic on average; positive: too cautious"),
        ]),
        ("Returns per buy, after costs", [
            ("Average return", _num(r["avg_return_pct"], "%", signed=True),
             f"What an investor kept per buy, after about {_num(c.get('round_trip_pct'), '%')} round-trip fees and "
             f"{_num((c.get('capital_gains_tax') or 0) * 100, '%')} tax on gains (before costs: {_num(r.get('avg_gross_return_pct'), '%', True)})"),
            ("Median return", _num(r["median_return_pct"], "%", signed=True), "The typical buy, less swayed by a few big ones"),
            ("Average win / loss", f"{_num(r['avg_win_pct'], '%', True)} / {_num(r['avg_loss_pct'], '%', True)}", "Size of winning versus losing buys"),
            ("Profit factor", _num(r["profit_factor"]),
             f"Total gains divided by total losses after costs; above 1 makes money (before costs: {_num(r.get('gross_profit_factor'))})"),
            ("Edge vs random buys", _num(r.get("edge_vs_random_pct"), "%", signed=True),
             f"Average return minus random buys' ({_num(r.get('random_avg_return_pct'), '%', True)})"),
            ("Sharpe / Sortino", f"{_num(r['sharpe'])} / {_num(r['sortino'])}", "Yearly return per unit of risk; above 1 is good (Sortino counts only falls)"),
        ]),
        ("Risk", [
            ("Total return", _num(k["total_return_pct"], "%", signed=True), f"Staking {k['stake_per_trade_pct']}% of capital per call, in exit order"),
            ("Yearly growth (CAGR)", _num(k["cagr_pct"], "%", signed=True), "Total return spread evenly over the years tested"),
            ("Max drawdown", _num(k["max_drawdown_pct"], "%"), "Worst fall from a peak of that equity curve"),
            ("Longest losing streak", _num(k["longest_losing_streak"]), "Most losing calls in a row"),
            ("Monte Carlo return", f"median {_num(mc.get('median_return_pct'), '%', True)}, worst 5% {_num(mc.get('p5_return_pct'), '%', True)}"
             if mc else "–", f"{mc.get('runs', 0)} redraws of the same calls: the range of luck this strategy could have had"),
            ("Monte Carlo drawdown", f"median {_num(mc.get('median_max_drawdown_pct'), '%')}, worst {_num(mc.get('worst_max_drawdown_pct'), '%')}"
             if mc else "–", "Max drawdown across those redraws"),
        ]),
    ]
    if x.get("calls"):
        sections.append(("Sell calls (exit warnings)", [
            ("Sell calls", f"{x['calls']} ({x['settled']} settled)", "Calls to sell or stay out; not trades, since NEPSE has no short selling"),
            ("Price fell after", _num(x["fell_pct"], "%"), f"Share where the price was lower at the horizon (any day: {_num(x['chance_fell_pct'], '%')})"),
            ("Average move", _num(x["avg_move_pct"], "%", signed=True), "Price change over the horizon; negative means the warning helped"),
        ]))
    if s.get("bars_evaluated"):
        sections.append(("Speed", [
            ("Bars replayed", _num(s["bars_evaluated"]), "Symbol-days the strategy was run on"),
            ("Analysis time per bar", _num(s["analysis_ms_per_bar"], " ms"), "Indicators, levels and this strategy for one stock on one day"),
            ("Strategy time per bar", _num(s["strategy_ms_per_bar"], " ms"), "This strategy's own rules only"),
            ("Sessions to resolve", _num(s["avg_sessions_to_resolve"]), "Trading days until a call hit its target, its stop or the horizon"),
            ("Sessions to target", _num(s["avg_sessions_to_target"]), "How fast winning calls reached their target"),
        ]))
    else:
        sections.append(("Speed", [
            ("Sessions to resolve", _num(s["avg_sessions_to_resolve"]), "Trading days until a call hit its target, its stop or the horizon"),
        ]))
    return sections


@admin.register(QuantStrategy)
class QuantStrategyAdmin(admin.ModelAdmin):
    list_display = ["strategy", "enabled", "method", "hit_rate", "p_value", "profit_factor", "max_drawdown", "speed", "evaluated", "note"]
    list_editable = ["enabled"]
    list_display_links = None
    ordering = ["name"]

    def get_queryset(self, request):
        sync_settings()
        return super().get_queryset(request)

    def get_urls(self):
        return [
            path("evaluate-all/", self.admin_site.admin_view(self.evaluate_all_view), name="quant_quantstrategy_evaluate_all"),
            *super().get_urls(),
        ]

    def evaluate_all_view(self, request):
        """Start an evaluation of every strategy that isn't already being evaluated."""
        if request.method == "POST" and self.has_change_permission(request):
            started = evaluate_all()
            messages.info(request, f"Evaluating {len(started)} strategies in the background; refresh this page in a few minutes."
                          if started else "Every strategy is already being evaluated.")
        return redirect("admin:quant_quantstrategy_changelist")

    def changelist_view(self, request, extra_context=None):
        extra_context = {"title": "Quant strategies: open one to check its accuracy and speed", **(extra_context or {})}
        self._latest, self._last = {}, {}
        for ev in QuantEvaluation.objects.order_by("strategy", "-started_at"):
            self._last.setdefault(ev.strategy, ev)
            if ev.status == QuantEvaluation.Status.OK:
                self._latest.setdefault(ev.strategy, ev)
        return super().changelist_view(request, extra_context)

    def _source(self, obj):
        """The measures the list shows: the replay's, or the live record's when only live calls have settled."""
        ev = getattr(self, "_latest", {}).get(obj.name)
        return quant.headline(ev) if ev else None

    def _metric(self, obj, *path):
        value = self._source(obj)
        for key in path:
            value = (value or {}).get(key)
        return value

    @admin.display(description="strategy", ordering="name")
    def strategy(self, obj):
        url = reverse("admin:quant_quantstrategy_change", args=[obj.pk])
        return format_html('<a href="{}"><strong>{}</strong></a><br><span style="color:var(--body-quiet-color)">{}</span>', url, obj.name, obj.description)

    @admin.display(description="tested on")
    def method(self, obj):
        return "history replay + live" if quant.can_replay(obj.name) else "live predictions"

    @admin.display(description="hit rate")
    def hit_rate(self, obj):
        return _num(self._metric(obj, "accuracy", "hit_rate"), "%")

    @admin.display(description="p-value")
    def p_value(self, obj):
        return _p(self._metric(obj, "accuracy", "p_value"))

    @admin.display(description="profit factor")
    def profit_factor(self, obj):
        return _num(self._metric(obj, "returns", "profit_factor"))

    @admin.display(description="max drawdown")
    def max_drawdown(self, obj):
        return _num(self._metric(obj, "risk", "max_drawdown_pct"), "%")

    @admin.display(description="ms / bar")
    def speed(self, obj):
        return _num(self._metric(obj, "speed", "analysis_ms_per_bar"))

    @admin.display(description="last evaluated")
    def evaluated(self, obj):
        ev = getattr(self, "_latest", {}).get(obj.name)
        return ev.finished_at.strftime("%Y-%m-%d %H:%M") if ev else "never"

    @admin.display(description="why blank")
    def note(self, obj):
        last = getattr(self, "_last", {}).get(obj.name)
        if last and last.status == QuantEvaluation.Status.RUNNING:
            return "evaluating…"
        if last and last.status == QuantEvaluation.Status.FAILED:
            return f"last evaluation failed: {last.error[:80]}"
        if obj.name not in getattr(self, "_latest", {}):
            return "not evaluated yet: press Evaluate all strategies"
        return quant.missing_metrics(self._source(obj))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def change_view(self, request, object_id, form_url="", extra_context=None):
        """The strategy's evaluation page, instead of an edit form."""
        obj = get_object_or_404(QuantStrategy, pk=object_id)
        if request.method == "POST":
            if not self.has_change_permission(request, obj):
                return redirect(request.path)
            try:
                days = int(request.POST.get("days", quant.DEFAULT_DAYS))
            except ValueError:
                days = quant.DEFAULT_DAYS
            symbols = [s for s in request.POST.get("symbols", "").replace(",", " ").split() if s]
            try:
                ev = quant.start_evaluation(obj.name, days=max(30, min(days, 3650)), symbols=symbols)
            except quant.EvaluationRunning:
                messages.warning(request, f"{obj.name} is already being evaluated. This page refreshes until the result is in.")
                return redirect(request.path)
            dispatch(ev.pk)
            messages.info(request, f"Evaluating {obj.name}. This page refreshes until the result is in.")
            return redirect(request.path)
        running = quant.running_evaluation(obj.name) is not None
        history = list(QuantEvaluation.objects.filter(strategy=obj.name)[:10])
        latest = next((ev for ev in history if ev.status == QuantEvaluation.Status.OK), None)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": f"Quant strategy: {obj.name}",
            "strategy": obj,
            "replayable": quant.can_replay(obj.name),
            "periods": PERIODS,
            "default_days": quant.DEFAULT_DAYS,
            "history": history,
            "running": running,
            "latest": latest,
            "replay_sections": metric_sections(latest.metrics) if latest else [],
            "replay_note": quant.missing_metrics(latest.metrics) if latest else "",
            "live_sections": metric_sections(latest.live) if latest else [],
            "pipeline": (latest.live or {}).get("pipeline") if latest else None,
            "trades": latest.trades[:25] if latest else [],
        }
        return TemplateResponse(request, "admin/quant/strategy.html", context)


@admin.register(QuantEvaluation)
class QuantEvaluationAdmin(admin.ModelAdmin):
    list_display = ["id", "strategy", "status", "start_date", "end_date", "symbols_tested", "duration_seconds", "finished_at"]
    list_filter = ["strategy", "status"]
    readonly_fields = [f.name for f in QuantEvaluation._meta.fields]

    def has_add_permission(self, request):
        return False  # start one from its strategy's page under Quant strategies
