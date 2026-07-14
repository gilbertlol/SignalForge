from django.contrib import admin

from .models import (
    CriterionGroup,
    ExclusionRule,
    HuntCriterion,
    HuntProfile,
    HuntProfileVersion,
    KeywordSet,
    ResultThreshold,
    SchedulePolicy,
    SearchScope,
    SourcePolicy,
    ValueSignal,
)


@admin.register(HuntProfile)
class HuntProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "current_version", "workspace", "created_at")
    list_filter = ("status", "workspace")
    search_fields = ("name", "description")


@admin.register(HuntProfileVersion)
class HuntProfileVersionAdmin(admin.ModelAdmin):
    list_display = ("profile", "version_number", "created_at")
    list_filter = ("profile",)
    readonly_fields = [f.name for f in HuntProfileVersion._meta.fields]

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CriterionGroup)
class CriterionGroupAdmin(admin.ModelAdmin):
    list_display = ("operator", "parent")


@admin.register(HuntCriterion)
class HuntCriterionAdmin(admin.ModelAdmin):
    list_display = ("category", "field", "op", "weight", "is_required", "is_hard_disqualifier")
    list_filter = ("category", "is_required", "is_hard_disqualifier")


@admin.register(KeywordSet)
class KeywordSetAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace")


@admin.register(ValueSignal)
class ValueSignalAdmin(admin.ModelAdmin):
    list_display = ("key", "weight", "workspace")


@admin.register(SearchScope)
class SearchScopeAdmin(admin.ModelAdmin):
    list_display = ("version", "company_size_min", "company_size_max")


@admin.register(SourcePolicy)
class SourcePolicyAdmin(admin.ModelAdmin):
    list_display = ("source_key", "version", "is_enabled", "max_records", "budget_cents")


@admin.register(ExclusionRule)
class ExclusionRuleAdmin(admin.ModelAdmin):
    list_display = ("field", "op", "version", "reason")


@admin.register(SchedulePolicy)
class SchedulePolicyAdmin(admin.ModelAdmin):
    list_display = ("profile", "frequency", "is_enabled")


@admin.register(ResultThreshold)
class ResultThresholdAdmin(admin.ModelAdmin):
    list_display = ("version", "min_total_score", "min_evidence_confidence")
