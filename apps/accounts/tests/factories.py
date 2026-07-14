import factory

from apps.accounts.models import AccessPermission, Membership, User
from apps.core.services import get_default_workspace


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        self.set_password(extracted or "temporary-pass-123")
        if create:
            self.save(update_fields=["password"])

    @factory.post_generation
    def workspace_membership(self, create, extracted, **kwargs):
        if create:
            membership, _ = Membership.objects.get_or_create(
                user=self, workspace=extracted or get_default_workspace()
            )
            permission, _ = AccessPermission.objects.get_or_create(
                key="prospects.access", defaults={"name": "Access prospects"}
            )
            membership.permission_grants.add(permission)
