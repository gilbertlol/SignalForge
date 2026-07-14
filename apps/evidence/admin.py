from django.contrib import admin

from .models import Evidence


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
