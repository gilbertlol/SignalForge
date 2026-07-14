from django.urls import path

from . import views

app_name = "evidence"

urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/evidence/",
        views.OrganizationEvidenceListCreateView.as_view(),
        name="organization-evidence",
    ),
    path(
        "opportunities/<uuid:opportunity_id>/evidence/",
        views.OpportunityEvidenceListCreateView.as_view(),
        name="opportunity-evidence",
    ),
]
