import io
import asyncio

from app.services.document_intake.file_policy_validator import validate_file_policy
from app.services.document_intake.autoreply_detector import is_autoreply
from app.services.document_intake.domain_validator import is_system_sender
from app.services.document_intake.sensitive_data_detector import detect_sensitivity
from app.services.document_intake.attachment_extractor import has_attachments
from app.services.document_intake.client_callback_notifier import build_callback_payload
from app.models.document_intake import EmailBatch, EmailBatchAttachment


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


def test_sensitive_data_detector_flags_ssn():
    result = asyncio.run(detect_sensitivity("My SSN is 123-45-6789, please process this."))
    assert result.contains_pii is True
    assert "ssn" in result.pii_types
    assert result.sensitivity_level == "restricted"


def test_sensitive_data_detector_no_pii_found():
    result = asyncio.run(detect_sensitivity("Please find attached the quarterly report for review."))
    assert result.contains_pii is False


def test_build_callback_payload_matches_contract_shape():
    batch = EmailBatch(
        id=1,
        batch_no="CLM-PROD-20260905-000001",
        sender_email="client@example.com",
        recipient_email="intake@company.com",
        subject="Invoice Submission",
        status="SUCCESS",
        status_reason="Merged PDF generated and stored successfully",
        attachment_count=1,
    )
    from datetime import datetime, timezone
    batch.received_datetime = datetime(2026, 9, 5, tzinfo=timezone.utc)
    attachment = EmailBatchAttachment(
        batch_source_filename="invoice.pdf", doc_type="pdf", file_size_bytes=1024, status="MERGED",
    )

    payload = build_callback_payload(batch, [attachment])

    assert payload["processResultStatusCode"] == "SUCCESS"
    assert payload["emailInfo"]["fromEmail"] == "client@example.com"
    assert payload["emailInfo"]["toEmail"] == "intake@company.com"
    assert payload["emailInfo"]["noOfAttachments"] == 1
    assert payload["emailInfo"]["attachments"][0]["filename"] == "invoice.pdf"
