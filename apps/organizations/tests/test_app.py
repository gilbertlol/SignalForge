from django.apps import apps


def test_organizations_app_is_installed():
    assert apps.is_installed("apps.organizations")
