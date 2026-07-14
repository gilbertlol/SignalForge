from django.contrib import admin

from .models import DiscoveryRun, EnrichmentRun, ProviderResult, SourceRecord, SuppressionEntry


@admin.register(DiscoveryRun)
class DiscoveryRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "hunt_profile_version",
        "status",
        "trigger",
        "records_discovered",
        "records_qualified",
        "created_at",
    )
    list_filter = ("status", "trigger", "workspace")


@admin.register(SourceRecord)
class SourceRecordAdmin(admin.ModelAdmin):
    list_display = ("source_key", "external_id", "status", "organization", "discovery_run")
    list_filter = ("status", "source_key")
    search_fields = ("external_id",)


@admin.register(EnrichmentRun)
class EnrichmentRunAdmin(admin.ModelAdmin):
    list_display = ("provider_key", "status", "source_record")
    list_filter = ("status", "provider_key")


@admin.register(ProviderResult)
class ProviderResultAdmin(admin.ModelAdmin):
    list_display = ("provider_key", "status", "records_returned", "cost_cents", "discovery_run")
    list_filter = ("status", "provider_key")


@admin.register(SuppressionEntry)
class SuppressionEntryAdmin(admin.ModelAdmin):
    list_display = ("domain", "is_active", "reason", "workspace")
    list_filter = ("is_active", "workspace")
    search_fields = ("domain",)
