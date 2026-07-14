"""Aggregates ViewSets from each app into one router.

This is the one place allowed to import from multiple domain apps at once —
apps themselves don't import each other's viewsets, keeping the modular
monolith's dependency graph one-directional (domain apps -> nothing;
this router -> domain apps).
"""

from rest_framework.routers import DefaultRouter

from apps.contacts.views import ContactViewSet
from apps.hunting.views import HuntProfileViewSet
from apps.opportunities.views import OpportunityViewSet
from apps.organizations.views import OrganizationViewSet
from apps.scoring.views import ScoreSnapshotViewSet

router = DefaultRouter()
router.register("organizations", OrganizationViewSet, basename="organization")
router.register("contacts", ContactViewSet, basename="contact")
router.register("opportunities", OpportunityViewSet, basename="opportunity")
router.register("scores", ScoreSnapshotViewSet, basename="scoresnapshot")
router.register("hunt-profiles", HuntProfileViewSet, basename="huntprofile")

urlpatterns = router.urls
