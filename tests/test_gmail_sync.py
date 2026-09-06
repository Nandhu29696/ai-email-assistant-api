from app.services.gmail_sync import _is_automated_or_self_message


def test_self_message_is_skipped_for_auto_reply():
    assert _is_automated_or_self_message({}, "Mailbox@Example.com", "mailbox@example.com")


def test_automated_message_is_skipped_for_auto_reply():
    assert _is_automated_or_self_message(
        {"Auto-Submitted": "auto-generated"},
        "sender@example.com",
        "mailbox@example.com",
    )
    assert _is_automated_or_self_message(
        {"Precedence": "junk"},
        "sender@example.com",
        "mailbox@example.com",
    )
    assert _is_automated_or_self_message(
        {"auto-submitted": "auto-generated"},
        "sender@example.com",
        "mailbox@example.com",
    )


def test_regular_message_can_receive_auto_reply():
    assert not _is_automated_or_self_message(
        {"Subject": "Hello"},
        "sender@example.com",
        "mailbox@example.com",
    )
