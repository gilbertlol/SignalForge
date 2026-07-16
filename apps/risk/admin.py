from django.contrib import admin

from .models import (
    AcceptancePolicy,
    ControlRecommendation,
    Mitigation,
    Override,
    Review,
    RiskCategory,
    RiskFactor,
    RiskObservation,
    RiskProfile,
    RiskSnapshot,
)

admin.site.register(
    [
        RiskProfile,
        RiskCategory,
        RiskFactor,
        RiskObservation,
        RiskSnapshot,
        ControlRecommendation,
        Mitigation,
        Override,
        Review,
        AcceptancePolicy,
    ]
)
