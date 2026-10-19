from main import create_dispatcher


def test_dispatcher_handles_messages():
    dp = create_dispatcher()

    assert "message" in dp.resolve_used_update_types()
