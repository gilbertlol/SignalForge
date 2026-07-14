from rest_framework import serializers

from .models import ScoreSnapshot


class ScoreSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScoreSnapshot
        fields = [
            "id",
            "family",
            "value",
            "is_hard_disqualified",
            "label",
            "components",
            "created_at",
        ]
        read_only_fields = fields
