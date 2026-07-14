from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class PingView(APIView):
    """Unauthenticated smoke-test endpoint proving DRF is wired end-to-end."""

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response({"service": "signalforge", "status": "ok"})
