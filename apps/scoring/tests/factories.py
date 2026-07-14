import factory

from apps.core.tests.factories import WorkspaceFactory

from ..models import ScoreFamily, ScoreThreshold, ScoringRule


class ScoringRuleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ScoringRule

    workspace = factory.SubFactory(WorkspaceFactory)
    family = ScoreFamily.PROSPECT_QUALITY
    key = factory.Sequence(lambda n: f"rule_{n}")
    points = 10
    is_hard_disqualifier = False
    conditions = factory.LazyFunction(dict)


class ScoreThresholdFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ScoreThreshold

    workspace = factory.SubFactory(WorkspaceFactory)
    family = ScoreFamily.PROSPECT_QUALITY
    label = factory.Sequence(lambda n: f"band_{n}")
    min_value = 0
