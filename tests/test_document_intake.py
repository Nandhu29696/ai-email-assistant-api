
from app.services.document_intake.file_policy_validator import validate_file_policy
from app.services.document_intake.autoreply_detector import is_autoreply
from app.services.document_intake.domain_validator import is_system_sender
from app.services.document_intake.attachment_extractor import has_attachments


def test_file_policy_validator_allows_valid_pdf():
    result = validate_file_policy("invoice.pdf", 1024 * 1024, "pdf,doc,docx,tiff,tif", 25)
    assert result.is_allowed is True
    assert result.extension == "pdf"


def test_file_policy_validator_rejects_disallowed_extension():
    result = validate_file_policy("malware.exe", 1024, "pdf,doc,docx,tiff,tif", 25)
    assert result.is_allowed is False
    assert "not supported" in result.reason.lower()


def test_file_policy_validator_rejects_oversized_file():
    oversized_bytes = 30 * 1024 * 1024
    result = validate_file_policy("big.pdf", oversized_bytes, "pdf", 25)
    assert result.is_allowed is False
    assert "exceeds" in result.reason.lower()


def test_autoreply_detector_flags_auto_submitted_header():
    headers = {"Auto-Submitted": "auto-replied", "Subject": "Re: hello"}
    assert is_autoreply(headers) is True


def test_autoreply_detector_flags_out_of_office_subject():
    headers = {"Subject": "Automatic reply: Out of Office"}
    assert is_autoreply(headers) is True


def test_autoreply_detector_normal_email_not_flagged():
    headers = {"Subject": "Please process my invoice", "From": "client@example.com"}
    assert is_autoreply(headers) is False


def test_is_system_sender_detects_noreply():
    assert is_system_sender("no-reply@example.com") is True
    assert is_system_sender("mailer-daemon@example.com") is True
    assert is_system_sender("client@example.com") is False


def test_has_attachments_true_and_false():
    payload_with_attachment = {"parts": [{"filename": "doc.pdf", "body": {"attachmentId": "x"}}]}
    payload_without_attachment = {"parts": [{"mimeType": "text/plain", "body": {"data": "aGVsbG8="}}]}
    assert has_attachments(payload_with_attachment) is True
    assert has_attachments(payload_without_attachment) is False


