from django.db import migrations

# Django's week_day lookup: 1 = Sunday ... 6 = Friday, 7 = Saturday.
FRIDAY, SATURDAY = 6, 7


def drop_weekend_bars(apps, schema_editor):
    """NEPSE never trades on Friday or Saturday. Daily bars dated then were copies of Thursday's
    prices, saved by forced runs on a weekend before ingestion dated them to the last session."""
    Candle = apps.get_model("marketdata", "Candle")
    Candle.objects.filter(timeframe="1D", trading_date__week_day__in=[FRIDAY, SATURDAY]).delete()


class Migration(migrations.Migration):
    dependencies = [("marketdata", "0001_initial")]
    operations = [migrations.RunPython(drop_weekend_bars, migrations.RunPython.noop)]
