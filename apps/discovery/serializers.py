from typing import Any

from django.shortcuts import get_object_or_404
from rest_framework import serializers

from apps.core.services import get_request_workspace
from apps.hunting.models import HuntProfile

from .models import DiscoveryRun, DiscoveryRunTrigger, SourceRecord
from .services import start_run
from .tasks import run_discovery_task


class SourceRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceRecord
        fields = [
            "id",
            "source_key",
            "external_id",
            "raw_payload",
            "normalized_data",
            "status",
            "organization",
            "failure_reason",
            "created_at",
        ]
        read_only_fields = fields


class ManualSourceRecordSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    domain = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class DiscoveryRunSerializer(serializers.ModelSerializer):
    hunt_profile = serializers.UUIDField(write_only=True)

    class Meta:
        model = DiscoveryRun
        fields = [
            "id",
            "hunt_profile_version",
            "hunt_profile",
            "status",
            "trigger",
            "started_at",
            "finished_at",
            "records_discovered",
            "records_deduplicated",
            "records_enriched",
            "records_qualified",
            "records_failed",
            "cost_cents",
            "error_summary",
            "initiated_by",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "hunt_profile_version",
            "status",
            "trigger",
            "started_at",
            "finished_at",
            "records_discovered",
            "records_deduplicated",
            "records_enriched",
            "records_qualified",
            "records_failed",
            "cost_cents",
            "error_summary",
            "initiated_by",
            "created_at",
        ]

    def create(self, validated_data: dict[str, Any]) -> DiscoveryRun:
        workspace = get_request_workspace(self.context["request"])
        profile = get_object_or_404(
            HuntProfile, id=validated_data["hunt_profile"], workspace=workspace
        )
        version = profile.current_version
        if version is None:
            raise serializers.ValidationError({"hunt_profile": "Profile has no version yet."})

        run = start_run(
            version,
            trigger=DiscoveryRunTrigger.MANUAL,
            initiated_by=self.context["request"].user,
        )
        run_discovery_task.delay(str(run.id))
        run.refresh_from_db()
        return run
