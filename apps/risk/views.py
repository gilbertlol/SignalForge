from decimal import Decimal

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import HasWorkspacePermission
from apps.core.services import get_request_workspace

from .models import (
    AcceptancePolicy,
    ControlRecommendation,
    Mitigation,
    Override,
    RecommendationStatus,
    Review,
    RiskCategory,
    RiskFactor,
    RiskObservation,
    RiskProfile,
    RiskSnapshot,
)
from .serializers import (
    AcceptancePolicySerializer,
    ControlRecommendationSerializer,
    MitigationSerializer,
    OverrideSerializer,
    ReviewSerializer,
    RiskCategorySerializer,
    RiskFactorSerializer,
    RiskObservationSerializer,
    RiskProfileSerializer,
    RiskSnapshotSerializer,
)
from .services import calculate_risk, sync_finance_observations


def can_approve(request) -> bool:
    if request.user.is_superuser:
        return True
    workspace = get_request_workspace(request)
    membership = request.user.memberships.filter(workspace=workspace, is_active=True).first()
    return bool(membership and membership.has_permission("approvals.manage"))


class RiskViewSet(viewsets.ModelViewSet):
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "risk.access"

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["workspace"] = get_request_workspace(self.request)
        return context

    def get_queryset(self):
        return self.queryset.filter(workspace=get_request_workspace(self.request)).order_by(
            "created_at"
        )


class RiskProfileViewSet(RiskViewSet):
    queryset = RiskProfile.objects.all()
    serializer_class = RiskProfileSerializer

    @action(detail=True, methods=["post"])
    def calculate(self, request, pk=None):
        snapshot = calculate_risk(
            self.get_object(), triggered_by=request.data.get("triggered_by", "manual_api")
        )
        return Response(RiskSnapshotSerializer(snapshot).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="sync-finance")
    def sync_finance(self, request, pk=None):
        currency = request.data.get("currency", "USD").upper()
        if len(currency) != 3 or not currency.isalpha():
            raise serializers.ValidationError("Use a three-letter currency code.")
        count = sync_finance_observations(self.get_object(), currency=currency)
        return Response({"observations_created": count})


class RiskCategoryViewSet(RiskViewSet):
    queryset = RiskCategory.objects.all()
    serializer_class = RiskCategorySerializer


class RiskFactorViewSet(RiskViewSet):
    queryset = RiskFactor.objects.all()
    serializer_class = RiskFactorSerializer


class RiskObservationViewSet(RiskViewSet):
    queryset = RiskObservation.objects.all()
    serializer_class = RiskObservationSerializer


class RiskSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RiskSnapshotSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "risk.access"

    def get_queryset(self):
        return RiskSnapshot.objects.filter(workspace=get_request_workspace(self.request))


class ControlRecommendationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ControlRecommendationSerializer
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "risk.access"

    def get_queryset(self):
        return ControlRecommendation.objects.filter(workspace=get_request_workspace(self.request))

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        if not can_approve(request):
            return Response(
                {"detail": "Approval permission required"}, status=status.HTTP_403_FORBIDDEN
            )
        decision = request.data.get("decision")
        if decision not in [RecommendationStatus.ACCEPTED, RecommendationStatus.REJECTED]:
            raise serializers.ValidationError("decision must be accepted or rejected")
        recommendation = self.get_object()
        recommendation.status = decision
        recommendation.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(recommendation).data)


class MitigationViewSet(RiskViewSet):
    queryset = Mitigation.objects.all()
    serializer_class = MitigationSerializer


class OverrideViewSet(RiskViewSet):
    queryset = Override.objects.all()
    serializer_class = OverrideSerializer
    http_method_names = ["get", "post", "head", "options"]


class ReviewViewSet(RiskViewSet):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer


class AcceptancePolicyViewSet(RiskViewSet):
    queryset = AcceptancePolicy.objects.all()
    serializer_class = AcceptancePolicySerializer


class RiskPortfolioViewSet(viewsets.ViewSet):
    permission_classes = [HasWorkspacePermission]
    required_workspace_permission = "risk.access"

    def list(self, request):
        workspace = get_request_workspace(request)
        profiles = RiskProfile.objects.filter(workspace=workspace).select_related(
            "organization", "opportunity", "contract"
        )
        rows = []
        for profile in profiles:
            snapshot = profile.snapshots.first()
            rows.append(
                {
                    "profile_id": profile.pk,
                    "organization_id": profile.organization_id,
                    "organization": profile.organization.name,
                    "opportunity_id": profile.opportunity_id,
                    "contract_id": profile.contract_id,
                    "category_scores": snapshot.category_scores if snapshot else {},
                    "calculated_at": snapshot.calculated_at if snapshot else None,
                    "pending_controls": profile.recommendations.filter(
                        status=RecommendationStatus.PROPOSED
                    ).count(),
                }
            )
        category = request.query_params.get("category")
        minimum = request.query_params.get("minimum")
        if category and minimum:
            threshold = Decimal(minimum)
            rows = [
                row
                for row in rows
                if category in row["category_scores"]
                and Decimal(row["category_scores"][category]) >= threshold
            ]
        return Response(rows)
