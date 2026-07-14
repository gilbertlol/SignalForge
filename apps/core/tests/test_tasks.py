from apps.core.tasks import debug_task


def test_debug_task_runs_eagerly_under_test_settings():
    result = debug_task.delay()

    assert result.successful()
    assert result.result == "pong"
