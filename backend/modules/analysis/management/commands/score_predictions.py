from django.core.management.base import BaseCommand

from modules.analysis.application import predictions, queries


class Command(BaseCommand):
    help = "Settle open predictions against prices since, then print each strategy's track record."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=180, help="Track record window in days (default 180)")

    def handle(self, *args, days, **options):
        settled = predictions.settle_predictions()
        self.stdout.write(f"Settled {settled} predictions.\n")
        card = queries.scorecard(days)
        self.stdout.write(f"Track record since {card['since']}:")
        self.stdout.write(f"{'strategy':18} {'made':>5} {'open':>5} {'settled':>8} {'hit rate':>9} {'avg ret':>8}")
        for r in card["strategies"]:
            hit = f"{r['hit_rate']}%" if r["hit_rate"] is not None else "-"
            avg = f"{r['avg_return']:+.2f}%" if r["avg_return"] is not None else "-"
            self.stdout.write(f"{r['strategy']:18} {r['predictions']:>5} {r['open']:>5} {r['settled']:>8} {hit:>9} {avg:>8}")
