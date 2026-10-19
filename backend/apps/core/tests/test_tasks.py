from apps.core.tasks import ping


def test_ping_task_returns_pong():
    assert ping.delay().get() == "pong"
