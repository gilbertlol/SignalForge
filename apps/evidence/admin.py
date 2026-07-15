from django.contrib import admin

from .models import Evidence, OrganizationClaim, OrganizationFieldResolution


@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    list_display = (
        "subject",
        "source_type",
        "reliability",
        "verification_status",
        "observed_date",
        "workspace",
    )
    list_filter = ("source_type", "reliability", "verification_status", "workspace")
    search_fields = ("excerpt", "source_url")


@admin.register(OrganizationClaim)
class OrganizationClaimAdmin(admin.ModelAdmin):
    list_display = ("organization", "field_name", "source_key", "reliability", "observed_at")
    list_filter = ("source_key", "field_name", "reliability")
    readonly_fields = [field.name for field in OrganizationClaim._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrganizationFieldResolution)
class OrganizationFieldResolutionAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "field_name",
        "corroboration_count",
        "distinct_value_count",
        "has_conflict",
    )
    readonly_fields = [field.name for field in OrganizationFieldResolution._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
