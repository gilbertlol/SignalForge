from django.apps import apps


def test_opportunities_app_is_installed():
    assert apps.is_installed("apps.opportunities")
