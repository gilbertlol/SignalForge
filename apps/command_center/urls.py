from django.urls import path

from . import views

app_name = "command_center"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("crew/", views.crew, name="crew"),
    path("review/", views.review_queue, name="review-queue"),
    path("hunt-profiles/", views.hunt_profiles, name="hunt-profiles"),
    path("hunt-profiles/new/", views.create_hunt_profile, name="create-hunt-profile"),
    path("hunt-profiles/<uuid:pk>/action/", views.profile_action, name="profile-action"),
    path("hunt-profiles/<uuid:pk>/run/", views.start_discovery, name="start-discovery"),
    path("pipeline/", views.opportunity_pipeline, name="pipeline"),
    path("pipeline/<uuid:pk>/status/", views.opportunity_status, name="opportunity-status"),
    path("settings/providers/", views.provider_settings, name="provider-settings"),
    path("settings/providers/new/", views.create_provider, name="create-provider"),
    path("settings/credentials/new/", views.create_credential, name="create-credential"),
    path("settings/lead-sources/apollo/", views.configure_apollo, name="configure-apollo"),
    path("settings/lead-sources/searxng/", views.configure_searxng, name="configure-searxng"),
    path(
        "settings/lead-sources/searxng/test/",
        views.test_lead_source_connection,
        {"source_key": "searxng"},
        name="test-searxng",
    ),
    path(
        "settings/lead-sources/google-places/",
        views.configure_google_places,
        name="configure-google-places",
    ),
    path(
        "settings/lead-sources/apollo/test/",
        views.test_lead_source_connection,
        {"source_key": "apollo"},
        name="test-apollo",
    ),
    path(
        "settings/lead-sources/google-places/test/",
        views.test_lead_source_connection,
        {"source_key": "google_places"},
        name="test-google-places",
    ),
    path("settings/endpoints/new/", views.create_endpoint, name="create-endpoint"),
    path("settings/models/new/", views.create_model, name="create-model"),
    path(
        "settings/research-routes/",
        views.configure_research_route,
        name="configure-research-route",
    ),
    path(
        "settings/providers/<uuid:pk>/test/",
        views.test_provider_connection,
        name="test-provider",
    ),
    path("runs/", views.run_monitor, name="runs"),
    path("runs/status/", views.run_status_fragment, name="run-status-fragment"),
    path("runs/<uuid:pk>/cancel/", views.cancel_run, name="cancel-run"),
    path("runs/sources/<uuid:pk>/cancel/", views.cancel_source, name="cancel-source"),
    path("organizations/", views.organizations, name="organizations"),
    path("organizations/new/", views.create_organization_manual, name="create-organization"),
    path("organizations/<uuid:pk>/", views.organization_detail, name="organization-detail"),
    path("organizations/<uuid:pk>/claims/", views.add_manual_claim, name="add-manual-claim"),
    path("claims/<uuid:pk>/prefer/", views.prefer_claim, name="prefer-claim"),
    path("inbox/", views.inbox, name="inbox"),
    path("inbox/<uuid:pk>/approve/", views.approve_outbound, name="approve-message"),
    path("inbox/<uuid:pk>/send/", views.send_outbound, name="send-message"),
    path("search/", views.global_search, name="search"),
]
