from django.core.management.base import BaseCommand

from modules.analysis.application import quant


class Command(BaseCommand):
    help = "Evaluate every strategy (hit rate, p-value, profit factor, ...) and print the results, as the admin Quant list shows them."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=quant.DEFAULT_DAYS, help=f"Period to replay (default {quant.DEFAULT_DAYS})")
        parser.add_argument("--stale-days", type=int, default=None,
                            help="Skip strategies already evaluated within this many days")

    def handle(self, *args, days, stale_days, **options):
        started = quant.start_all(days, only_stale_days=stale_days)
        if not started:
            self.stdout.write("Every strategy has a recent evaluation (or one running).")
            return
        self.stdout.write(f"{'strategy':18} {'calls':>6} {'settled':>8} {'hit rate':>9} {'p-value':>8} {'profit f.':>10}  note")
        for ev in started:
            self.stdout.write(f"{ev.strategy}: evaluating…", ending="\r")
            self.stdout.flush()
            ev = quant.run_evaluation(ev.pk)
            if ev.status != ev.Status.OK:
                self.stdout.write(f"{ev.strategy:18} failed: {ev.error}")
                continue
            m = quant.headline(ev)
            a, r = m.get("accuracy", {}), m.get("returns", {})
            self.stdout.write(
                f"{ev.strategy:18} {m.get('calls', 0):>6} {m.get('settled', 0):>8} {_v(a.get('hit_rate'), '%'):>9} "
                f"{_v(a.get('p_value')):>8} {_v(r.get('profit_factor')):>10}  {quant.missing_metrics(m)}"
            )


def _v(value, suffix=""):
    return "-" if value is None else f"{value:g}{suffix}"
