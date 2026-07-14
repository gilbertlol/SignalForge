from django.contrib import admin

from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "domain", "workspace", "created_at")
    search_fields = ("name", "domain", "dedupe_key")
    list_filter = ("workspace",)
