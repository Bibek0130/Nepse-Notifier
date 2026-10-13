from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application import queries


class SignalQuery(serializers.Serializer):
    run = serializers.IntegerField(required=False)
    direction = serializers.ChoiceField(choices=["bullish", "bearish", "neutral"], required=False)
    min_strength = serializers.IntegerField(required=False, min_value=1, max_value=3)


class LatestSignalsView(APIView):
    """Signals from the latest finished analysis run (or ?run=<id>)."""

    def get(self, request):
        params = SignalQuery(data=request.query_params)
        params.is_valid(raise_exception=True)
        q = params.validated_data
        run_id = q.get("run") or getattr(queries.latest_run(), "pk", None)
        if run_id is None:
            return Response({"run_id": None, "signals": []})
        report = queries.run_report(run_id)
        signals = [
            s for s in report["signals"]
            if (not q.get("direction") or s["direction"] == q["direction"]) and s["strength"] >= q.get("min_strength", 1)
        ]
        return Response({**report, "signals": signals})


class SymbolAnalysisView(APIView):
    """Latest indicators, support/resistance, forecast and signals for one symbol."""

    def get(self, request, symbol):
        result = queries.latest_for_symbol(symbol)
        if result is None:
            raise NotFound(f"No analysis for {symbol.upper()} yet")
        return Response(result)
