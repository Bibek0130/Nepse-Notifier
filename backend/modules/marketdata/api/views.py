from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application import queries
from ..infrastructure.models import IngestionRun
from .serializers import CandleQuerySerializer, CandleSerializer, IngestionRunSerializer, InstrumentSerializer


class LatestQuotesView(APIView):
    """Latest snapshot for every symbol (served from Redis)."""

    def get(self, request):
        return Response(queries.latest_quotes())


class MarketSummaryView(APIView):
    """Advancers/decliners, top gainers, losers and turnover (served from Redis)."""

    def get(self, request):
        return Response(queries.market_summary() or {})


class InstrumentListView(generics.ListAPIView):
    serializer_class = InstrumentSerializer
    pagination_class = None

    def get_queryset(self):
        return queries.instruments()


class CandleListView(APIView):
    """GET ?symbol=NABIL&tf=1D&start=2026-01-01&end=2026-10-13"""

    def get(self, request):
        params = CandleQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        q = params.validated_data
        candles = queries.candles(q["symbol"], q["tf"], q.get("start"), q.get("end"))
        return Response(CandleSerializer(candles, many=True).data)


class IngestionRunListView(generics.ListAPIView):
    """Pipeline health, newest first. Staff only."""

    serializer_class = IngestionRunSerializer
    permission_classes = [permissions.IsAdminUser]
    queryset = IngestionRun.objects.all()
