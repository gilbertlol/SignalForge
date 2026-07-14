from django.contrib import admin

from .models import ScoreSnapshot, ScoreThreshold, ScoringRule


@admin.register(ScoringRule)
class ScoringRuleAdmin(admin.ModelAdmin):
    list_display = ("key", "family", "points", "is_hard_disqualifier", "version", "workspace")
    list_filter = ("family", "is_hard_disqualifier", "workspace")
    search_fields = ("key", "description")


@admin.register(ScoreThreshold)
class ScoreThresholdAdmin(admin.ModelAdmin):
    list_display = ("label", "family", "min_value", "workspace")
    list_filter = ("family", "workspace")


@admin.register(ScoreSnapshot)
class ScoreSnapshotAdmin(admin.ModelAdmin):
    list_display = ("subject", "family", "value", "is_hard_disqualified", "label", "created_at")
    list_filter = ("family", "is_hard_disqualified", "workspace")
    readonly_fields = [f.name for f in ScoreSnapshot._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
