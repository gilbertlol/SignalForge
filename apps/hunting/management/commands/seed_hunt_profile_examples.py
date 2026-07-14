from typing import Any

from django.core.management.base import BaseCommand

from apps.core.services import get_default_workspace
from apps.hunting.models import HuntProfile
from apps.hunting.services import create_version

EXAMPLES: list[dict[str, Any]] = [
    {
        "name": "Automation agencies",
        "description": "Agencies selling workflow/automation services to other businesses.",
        "criteria": {
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "criterion",
                    "category": "industry",
                    "field": "domain",
                    "op": "neq",
                    "value": "",
                    "weight": 10,
                    "is_required": True,
                },
                {
                    "type": "criterion",
                    "category": "growth_signal",
                    "field": "evidence_count",
                    "op": "gte",
                    "value": 1,
                    "weight": 5,
                },
            ],
        },
        "result_threshold": {"min_total_score": 10},
    },
    {
        "name": "Local professional services",
        "description": (
            "Regional service businesses (legal, accounting, consulting) "
            "with weak digital presence."
        ),
        "criteria": {
            "type": "group",
            "operator": "NOT",
            "children": [
                {
                    "type": "criterion",
                    "category": "custom_attribute",
                    "field": "domain",
                    "op": "eq",
                    "value": "",
                }
            ],
        },
        "result_threshold": {"min_total_score": 0},
    },
    {
        "name": "SaaS companies",
        "description": "Software-as-a-service companies with signs of active growth.",
        "criteria": {
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "criterion",
                    "category": "business_model",
                    "field": "domain",
                    "op": "neq",
                    "value": "",
                    "weight": 10,
                    "is_required": True,
                },
                {
                    "type": "criterion",
                    "category": "growth_signal",
                    "field": "max_age_days",
                    "op": "lte",
                    "value": 180,
                    "weight": 5,
                },
            ],
        },
        "result_threshold": {"min_total_score": 10, "min_evidence_confidence": 0},
    },
    {
        "name": "Businesses hiring CRM or automation roles",
        "description": "Companies with active hiring signals for CRM, RevOps, or automation roles.",
        "criteria": {
            "type": "group",
            "operator": "AND",
            "children": [
                {
                    "type": "criterion",
                    "category": "hiring_signal",
                    "field": "evidence_count",
                    "op": "gte",
                    "value": 1,
                    "weight": 15,
                    "is_hard_disqualifier": False,
                }
            ],
        },
        "result_threshold": {"min_total_score": 15},
    },
]


class Command(BaseCommand):
    help = (
        "Idempotently seed example Hunt Profiles (draft status) demonstrating the criteria engine."
    )

    def handle(self, *args, **options):
        workspace = get_default_workspace()
        for example in EXAMPLES:
            if HuntProfile.objects.filter(workspace=workspace, name=example["name"]).exists():
                self.stdout.write(f"Skipping existing profile: {example['name']}")
                continue

            profile = HuntProfile.objects.create(
                workspace=workspace,
                name=example["name"],
                description=example["description"],
            )
            version = create_version(
                profile,
                criteria=example["criteria"],
                result_threshold=example.get("result_threshold"),
            )
            profile.current_version = version
            profile.save(update_fields=["current_version", "updated_at"])
            self.stdout.write(self.style.SUCCESS(f"Created example profile: {profile.name}"))
