from django.contrib import admin
from django.urls import include, path

from config.api_router import router

urlpatterns = [
    path("", include("apps.command_center.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("admin/", admin.site.urls),
    path("health/", include("apps.core.health.urls")),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.core.api.urls")),
    path("api/v1/", include(router.urls)),
    path("api/v1/", include("apps.evidence.urls")),
    path("api/v1/", include("apps.scoring.urls")),
]
