from django.contrib import admin

from .models import Opportunity


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ("title", "organization", "status", "contacted", "created_at")
    search_fields = ("title", "organization__name")
    list_filter = ("status", "workspace")
