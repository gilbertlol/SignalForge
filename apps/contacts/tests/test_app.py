from django.apps import apps


def test_contacts_app_is_installed():
    assert apps.is_installed("apps.contacts")
