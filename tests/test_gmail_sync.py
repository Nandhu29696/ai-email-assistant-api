from app.services.document_intake.sender_checks import is_automated_message


def test_automated_messages_are_detected():
    assert is_automated_message({"Auto-Submitted": "auto-replied"}, "person@example.com")
    assert is_automated_message({"Precedence": "bulk"}, "person@example.com")
    assert is_automated_message({"List-Unsubscribe": "<mailto:x@example.com>"}, "news@example.com")
    assert is_automated_message({"Subject": "Out of Office: back Monday"}, "person@example.com")
    assert is_automated_message({}, "mailer-daemon@googlemail.com")
    assert is_automated_message({}, "no-reply@example.com")
    assert is_automated_message({}, "")


def test_regular_message_is_not_automated():
    assert not is_automated_message({"Subject": "Claim documents", "Auto-Submitted": "no"}, "client@example.com")
