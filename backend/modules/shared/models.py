from django.db import models


class TradingHoliday(models.Model):
    """A weekday on which NEPSE is closed (public holidays, special closures)."""

    date = models.DateField(unique=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.date} {self.description}".strip()
