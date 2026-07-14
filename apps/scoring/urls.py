from django.urls import path

from . import views

app_name = "scoring"

urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/scores/<str:family>/explain/",
        views.OrganizationScoreExplainView.as_view(),
        name="organization-score-explain",
    ),
    path(
        "organizations/<uuid:organization_id>/scores/<str:family>/recompute/",
        views.OrganizationScoreRecomputeView.as_view(),
        name="organization-score-recompute",
    ),
    path(
        "opportunities/<uuid:opportunity_id>/scores/<str:family>/explain/",
        views.OpportunityScoreExplainView.as_view(),
        name="opportunity-score-explain",
    ),
    path(
        "opportunities/<uuid:opportunity_id>/scores/<str:family>/recompute/",
        views.OpportunityScoreRecomputeView.as_view(),
        name="opportunity-score-recompute",
    ),
]
