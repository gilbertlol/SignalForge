from django.apps import apps


def test_tasks_app_is_installed():
    assert apps.is_installed("apps.tasks")
