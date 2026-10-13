from rest_framework import serializers

from ..infrastructure.models import IngestionRun, Instrument


class InstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrument
        fields = ["symbol", "name", "sector", "instrument_type", "is_active"]


class CandleSerializer(serializers.Serializer):
    symbol = serializers.CharField()
    timeframe = serializers.CharField()
    ts = serializers.DateTimeField()
    trading_date = serializers.DateField()
    open = serializers.DecimalField(max_digits=12, decimal_places=2)
    high = serializers.DecimalField(max_digits=12, decimal_places=2)
    low = serializers.DecimalField(max_digits=12, decimal_places=2)
    close = serializers.DecimalField(max_digits=12, decimal_places=2)
    previous_close = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    volume = serializers.IntegerField()
    turnover = serializers.DecimalField(max_digits=18, decimal_places=2, allow_null=True)
    trades = serializers.IntegerField(allow_null=True)


class CandleQuerySerializer(serializers.Serializer):
    symbol = serializers.CharField()
    tf = serializers.ChoiceField(choices=["1D", "3H"], default="1D")
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)


class IngestionRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = IngestionRun
        fields = ["id", "kind", "status", "source", "trading_date", "started_at", "finished_at", "stages", "fetched", "accepted", "quarantined", "error"]
