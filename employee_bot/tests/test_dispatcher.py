def test_dispatcher_handles_messages_and_callbacks(dp):
    used = dp.resolve_used_update_types()

    assert {"message", "callback_query", "my_chat_member"} <= set(used)
