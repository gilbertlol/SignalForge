from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace

from .models import DiscoveryRun, DiscoveryRunStatus
from .serializers import (
    DiscoveryRunSerializer,
    ManualSourceRecordSerializer,
    SourceRecordSerializer,
)
from .services import create_manual_source_record, import_csv
from .tasks import run_discovery_task

_TERMINAL_STATUSES = {
    DiscoveryRunStatus.SUCCEEDED,
    DiscoveryRunStatus.FAILED,
    DiscoveryRunStatus.PARTIAL,
    DiscoveryRunStatus.CANCELED,
}


class DiscoveryRunViewSet(viewsets.ModelViewSet):
    serializer_class = DiscoveryRunSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "prospects.access"
    filterset_fields = ["status", "trigger"]

    def get_queryset(self):
        return DiscoveryRun.objects.filter(workspace=get_request_workspace(self.request))

    def _get_run(self, pk) -> DiscoveryRun:
        """Fetches by pk without going through `filter_queryset()` — the
        outer viewset's `filterset_fields=["status", "trigger"]` would
        otherwise be (wrongly) applied to actions like `source_records`
        whose own `?status=` query param means something different
        (a SourceRecord status, not a DiscoveryRun status)."""
        return get_object_or_404(self.get_queryset(), pk=pk)

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk=None) -> Response:
        run = self._get_run(pk)
        if run.status in _TERMINAL_STATUSES:
            return Response({"detail": f"Run already {run.status}."}, status=400)
        run.status = DiscoveryRunStatus.CANCELED
        run.save(update_fields=["status", "updated_at"])
        return Response(DiscoveryRunSerializer(run).data)

    @action(detail=True, methods=["post"])
    def retry(self, request: Request, pk=None) -> Response:
        run = self._get_run(pk)
        run_discovery_task.delay(str(run.id))
        run.refresh_from_db()
        return Response(DiscoveryRunSerializer(run).data)

    @action(detail=True, methods=["get"], url_path="source-records")
    def source_records(self, request: Request, pk=None) -> Response:
        run = self._get_run(pk)
        queryset = run.source_records.all()
        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return Response(SourceRecordSerializer(queryset, many=True).data)

    @action(detail=True, methods=["post"], url_path="source-records/manual")
    def manual_source_record(self, request: Request, pk=None) -> Response:
        run = self._get_run(pk)
        payload = ManualSourceRecordSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        record = create_manual_source_record(run, **payload.validated_data)
        return Response(SourceRecordSerializer(record).data, status=201)

    @action(detail=True, methods=["post"], url_path="source-records/import-csv")
    def import_csv_action(self, request: Request, pk=None) -> Response:
        run = self._get_run(pk)
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Missing 'file' in multipart body."}, status=400)
        records = import_csv(run, upload)
        return Response(SourceRecordSerializer(records, many=True).data, status=201)
