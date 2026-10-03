"""End-to-end tests of the intake rules with real files and a fake mailbox.

Each test feeds one email through ``process_document_intake_email`` and checks
the final status, which replies went out (and what they list), the per-file
statuses and the stored PDFs.
"""
import asyncio
import io
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter

from app.models.document_intake import EmailBatch, EmailBatchAttachment, EmailBatchEvent
from app.models.email import AllowedDomain, EmailIntegration
from app.services.document_intake import pipeline
from app.services.document_intake.attachment_extractor import ExtractedAttachment
from app.services.document_intake.attachment_validator import check_attachment


# ── Real file fixtures ────────────────────────────────────────
def make_pdf(text="Invoice page", pages=1) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for number in range(pages):
        c.drawString(72, 720, f"{text} {number + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


def make_encrypted_pdf() -> bytes:
    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(make_pdf("Secret"))).pages:
        writer.add_page(page)
    writer.encrypt("open-sesame")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def make_tiff(frames=2) -> bytes:
    from PIL import Image

    images = [Image.new("RGB", (120, 160), color) for color in ("white", "gray")[:frames]]
    out = io.BytesIO()
    images[0].save(out, format="TIFF", save_all=True, append_images=images[1:])
    return out.getvalue()


def make_docx() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("_rels/.rels",
                         '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr("word/document.xml",
                         '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                         '<w:body><w:p><w:r><w:t>Claim form</w:t></w:r></w:p></w:body></w:document>')
    return out.getvalue()


def make_encrypted_docx(tmp_path) -> bytes:
    from msoffcrypto.format.ooxml import OOXMLFile

    source = io.BytesIO(make_docx())
    out = io.BytesIO()
    OOXMLFile(source).encrypt("open-sesame", out)
    return out.getvalue()


def att(name: str, data: bytes) -> ExtractedAttachment:
    return ExtractedAttachment(filename=name, content_type="application/octet-stream", data=data, size_bytes=len(data))


# ── Fake mailbox (same contract as the Gmail/Outlook/IMAP adapters) ──
class FakeMailbox:
    def __init__(self, attachments=None):
        self.attachments = attachments or []
        self.sent: list[tuple[str, str]] = []      # (subject, html)
        self.moved: list[tuple[str, str]] = []     # (message id, folder)

    def has_attachments(self, ctx):
        return bool(self.attachments)

    def extract_attachments(self, ctx):
        return list(self.attachments)

    def send_reply(self, ctx, subject, html_body):
        self.sent.append((subject, html_body))
        return True

    def move_to_success(self, message_id, label):
        self.moved.append((message_id, label))
        return True

    def move_to_failed(self, message_id, label):
        self.moved.append((message_id, label))
        return True


@pytest.fixture()
def env(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(pipeline.settings, "DOCUMENT_INTAKE_LOCAL_PATH", str(tmp_path / "store"))
    monkeypatch.setattr(pipeline.settings, "DOCUMENT_INTAKE_STORAGE_PROVIDER", "local")
    db_session.add(AllowedDomain(domain="client.com", is_active=True))
    mailbox = EmailIntegration(provider="gmail", email_address="intake@ours.com", batch_prefix="CLM",
                               mailbox_type="UAT", is_active=True,
                               process_since=datetime.now(timezone.utc) - timedelta(hours=1))
    db_session.add(mailbox)
    db_session.commit()
    # Plain values: the pipeline closes the session, which detaches ORM instances.
    box = SimpleNamespace(id=mailbox.id, email_address=mailbox.email_address, orm=mailbox)
    return db_session, box, tmp_path


_counter = iter(range(1, 10_000))


def run(db, mailbox, service, sender="alice@client.com", headers=None, received=None, body="Please find my documents."):
    n = next(_counter)
    ctx = pipeline.IntakeEmailContext(
        gmail_message_id=f"gm-{n}", stored_message_id=f"<msg-{n}@client.com>", thread_id="t1",
        headers={"Subject": "Claim documents", "_body_plain": body, **(headers or {})},
        sender_name="Alice", sender_email=sender, recipient_email=mailbox.email_address,
        subject="Claim documents", received_at=received or datetime.now(timezone.utc), payload={},
    )
    status = asyncio.run(pipeline.process_document_intake_email(mailbox.id, service, ctx))
    batch = db.query(EmailBatch).filter(EmailBatch.message_id == ctx.stored_message_id).first()
    return status, batch


def subjects(service):
    return [subject for subject, _ in service.sent]


def file_statuses(db, batch):
    rows = db.query(EmailBatchAttachment).filter(EmailBatchAttachment.parent_batch_id == batch.id).all()
    return {r.batch_source_filename: r.status for r in rows}


# ── Rule 0: every email is categorised and analysed ───────────
def test_every_email_gets_category_and_sentiment(env):
    db, mailbox, _ = env
    service = FakeMailbox()
    _, batch = run(db, mailbox, service, sender="x@unknown.org",
                   body="This is unacceptable, I was charged twice and want a refund now!")
    assert batch.email_category and batch.sentiment == "negative" and batch.primary_emotion
    events = [e.event_type for e in db.query(EmailBatchEvent).filter(EmailBatchEvent.parent_batch_id == batch.id)]
    assert events[:2] == ["RECEIVED", "ANALYZED"]


# ── Rule 1: invalid domain ────────────────────────────────────
def test_invalid_domain_gets_domain_reply_only(env):
    db, mailbox, _ = env
    service = FakeMailbox([att("a.pdf", make_pdf())])
    status, batch = run(db, mailbox, service, sender="bob@unknown.org")
    assert status == "REJECTED" and batch.outcome == "DOMAIN_NOT_ALLOWED"
    assert len(service.sent) == 1 and "domain not valid" in service.sent[0][0].lower()
    assert "unknown.org" in service.sent[0][1]
    assert service.moved == [("gm-%s" % batch.conversation_id.split("-")[1], "Processed/Failed")]


def test_subdomain_of_allowed_domain_is_valid(env):
    db, mailbox, _ = env
    service = FakeMailbox()
    _, batch = run(db, mailbox, service, sender="ops@mail.client.com")
    assert batch.outcome == "NO_ATTACHMENT"


# ── Rules 2 + 3: acknowledgement, then no attachment ──────────
def test_valid_domain_without_attachment_gets_ack_then_upload_request(env):
    db, mailbox, _ = env
    service = FakeMailbox()
    status, batch = run(db, mailbox, service)
    assert status == "REJECTED" and batch.outcome == "NO_ATTACHMENT"
    assert len(service.sent) == 2
    assert "received your email" in service.sent[0][0] and "status shortly" in service.sent[0][1]
    assert "No attachment" in service.sent[1][0]
    assert "does not have any attachment" in service.sent[1][1] and ".pdf" in service.sent[1][1]


# ── Rule 3: unsupported types ─────────────────────────────────
def test_mixed_supported_and_unsupported_rejects_whole_email_and_lists_bad_files(env):
    db, mailbox, _ = env
    service = FakeMailbox([att("invoice.pdf", make_pdf()), att("photo.png", b"\x89PNG....")])
    status, batch = run(db, mailbox, service)
    assert status == "REJECTED" and batch.outcome == "INVALID_FILE_TYPE"
    assert subjects(service)[1].endswith("Unsupported attachment(s)")
    reply = service.sent[1][1]
    assert "photo.png" in reply and "invoice.pdf" not in reply
    assert file_statuses(db, batch) == {"invoice.pdf": "NOT_PROCESSED", "photo.png": "INVALID_TYPE"}
    assert batch.merged_pdf_path is None


def test_all_unsupported_types_get_unsupported_type_reply(env):
    db, mailbox, _ = env
    service = FakeMailbox([att("setup.exe", b"MZ"), att("notes.txt", b"hi")])
    _, batch = run(db, mailbox, service)
    assert batch.outcome == "INVALID_FILE_TYPE"
    assert "setup.exe" in service.sent[1][1] and "notes.txt" in service.sent[1][1]


def test_oversized_file_is_unsupported(env):
    db, mailbox, _ = env
    mailbox.orm.max_file_size_mb = 1
    db.commit()
    service = FakeMailbox([att("big.pdf", make_pdf() + b"0" * (1024 * 1024 + 1))])
    _, batch = run(db, mailbox, service)
    assert batch.outcome == "INVALID_FILE_TYPE" and "exceeds the 1MB limit" in service.sent[1][1]


# ── Rule 4.1: protected / unreadable files ────────────────────
def test_protected_and_unreadable_files_are_listed_with_reasons(env, tmp_path):
    db, mailbox, _ = env
    service = FakeMailbox([
        att("good.pdf", make_pdf()),
        att("locked.pdf", make_encrypted_pdf()),
        att("locked.docx", make_encrypted_docx(tmp_path)),
        att("broken.pdf", b"%PDF-1.4 not really a pdf"),
        att("broken.tiff", b"II*\x00garbage"),
    ])
    status, batch = run(db, mailbox, service)
    assert status == "REJECTED" and batch.outcome == "INVALID_ATTACHMENTS"
    reply = service.sent[1][1]
    for name in ("locked.pdf", "locked.docx", "broken.pdf", "broken.tiff"):
        assert name in reply
    assert "good.pdf" not in reply and "password-protected" in reply
    assert file_statuses(db, batch) == {
        "good.pdf": "NOT_PROCESSED", "locked.pdf": "PROTECTED", "locked.docx": "PROTECTED",
        "broken.pdf": "UNREADABLE", "broken.tiff": "UNREADABLE",
    }
    locked = db.query(EmailBatchAttachment).filter_by(parent_batch_id=batch.id, batch_source_filename="locked.pdf").one()
    assert locked.is_encrypted is True


def test_word_file_that_libreoffice_cannot_open_is_unreadable(env, monkeypatch):
    db, mailbox, _ = env
    from app.services.document_intake.conversion.doc_to_pdf import DocConversionError

    def fail(data, name):
        raise DocConversionError("The document could not be opened for conversion")
    monkeypatch.setattr(pipeline, "convert_doc_to_pdf", fail)
    service = FakeMailbox([att("form.docx", make_docx())])
    _, batch = run(db, mailbox, service)
    assert batch.outcome == "INVALID_ATTACHMENTS" and "form.docx" in service.sent[1][1]
    assert file_statuses(db, batch) == {"form.docx": "UNREADABLE"}


# ── Rule 5: convert, store, email PDF, merge, success ─────────
def test_valid_attachments_are_converted_stored_merged_and_confirmed(env, monkeypatch):
    db, mailbox, tmp_path = env
    monkeypatch.setattr(pipeline, "convert_doc_to_pdf", lambda data, name: make_pdf("Converted Word", pages=1))
    service = FakeMailbox([
        att("invoice.pdf", make_pdf("Invoice", pages=2)),
        att("scan.tiff", make_tiff(frames=2)),
        att("form.docx", make_docx()),
    ])
    status, batch = run(db, mailbox, service, body="Hello, attached are my claim documents.")

    assert status == "SUCCESS" and batch.outcome == "PROCESSED"
    # replies: acknowledgement, then success listing every attachment
    assert len(service.sent) == 2
    success_subject, success_html = service.sent[1]
    assert "Processed successfully" in success_subject
    assert "Below are the attachments as you shared" in success_html
    for name in ("invoice.pdf", "scan.tiff", "form.docx"):
        assert f"<strong>{name}</strong>" in success_html
    assert batch.batch_no in success_html
    assert service.moved[-1][1] == "Processed/Success"

    # 5.1 each attachment stored as its own PDF
    rows = db.query(EmailBatchAttachment).filter_by(parent_batch_id=batch.id).order_by(EmailBatchAttachment.id).all()
    assert [r.status for r in rows] == ["MERGED", "MERGED", "MERGED"]
    pages = []
    for row in rows:
        with open(row.converted_pdf_path, "rb") as fh:
            pages.append(len(PdfReader(fh).pages))
    assert pages == [2, 2, 1]
    assert "attachments" in rows[0].converted_pdf_path and rows[0].converted_pdf_path.endswith("01_invoice.pdf")

    # 5.2 email content PDF
    email_pdf = PdfReader(batch.email_pdf_path)
    email_text = "".join(p.extract_text() for p in email_pdf.pages)
    assert "Email content" in email_text and "attached are my claim documents" in email_text
    assert "invoice.pdf" in email_text

    # 5.3 / 5.4 merged PDF: attachments in order, email content last
    merged = PdfReader(batch.merged_pdf_path)
    assert len(merged.pages) == sum(pages) + len(email_pdf.pages)
    assert "Invoice 1" in merged.pages[0].extract_text()
    assert "Email content" in merged.pages[-len(email_pdf.pages)].extract_text()
    assert batch.merged_pdf_path.endswith(f"{batch.batch_no}_merged.pdf")
    assert str(tmp_path / "store") in batch.merged_pdf_path and "UAT" in batch.merged_pdf_path


def test_permission_only_pdf_is_accepted(env):
    db, mailbox, _ = env
    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(make_pdf())).pages:
        writer.add_page(page)
    writer.encrypt(user_password="", owner_password="owner-only")
    out = io.BytesIO()
    writer.write(out)
    service = FakeMailbox([att("restricted.pdf", out.getvalue())])
    status, _ = run(db, mailbox, service)
    assert status == "SUCCESS"


# ── System problems never blame the sender ────────────────────
def test_missing_converter_fails_without_blaming_sender(env, monkeypatch):
    db, mailbox, _ = env
    from app.services.document_intake.conversion.doc_to_pdf import ConverterUnavailableError

    def unavailable(data, name):
        raise ConverterUnavailableError("LibreOffice is not installed")
    monkeypatch.setattr(pipeline, "convert_doc_to_pdf", unavailable)
    service = FakeMailbox([att("form.docx", make_docx())])
    status, batch = run(db, mailbox, service)
    assert status == "FAILED" and batch.outcome == "SYSTEM_ERROR"
    assert len(service.sent) == 1 and "received your email" in service.sent[0][0]   # only the acknowledgement
    assert service.moved == []        # left in the Inbox for reprocessing
    assert "LibreOffice" in batch.status_reason


def test_storage_failure_is_a_system_error(env, monkeypatch):
    db, mailbox, _ = env

    class BrokenStorage:
        def save(self, path, data):
            raise OSError("disk full")
    monkeypatch.setattr(pipeline, "get_storage_adapter", lambda: BrokenStorage())
    service = FakeMailbox([att("a.pdf", make_pdf())])
    status, batch = run(db, mailbox, service)
    assert status == "FAILED" and batch.outcome == "SYSTEM_ERROR" and len(service.sent) == 1


# ── Senders that must not get replies ─────────────────────────
def test_automated_messages_are_ignored_without_reply(env):
    db, mailbox, _ = env
    service = FakeMailbox([att("a.pdf", make_pdf())])
    status, batch = run(db, mailbox, service, headers={"Auto-Submitted": "auto-replied"})
    assert status == "IGNORED" and batch.outcome == "AUTOMATED_MESSAGE" and service.sent == []


def test_forged_sender_is_rejected_without_reply(env):
    db, mailbox, _ = env
    service = FakeMailbox([att("a.pdf", make_pdf())])
    status, batch = run(db, mailbox, service,
                        headers={"Authentication-Results": "mx.google.com; spf=fail; dmarc=fail"})
    assert status == "REJECTED" and batch.outcome == "SENDER_NOT_VERIFIED" and service.sent == []


def test_emails_from_before_the_mailbox_was_connected_are_skipped(env):
    db, mailbox, _ = env
    service = FakeMailbox([att("a.pdf", make_pdf())])
    status, batch = run(db, mailbox, service, received=datetime.now(timezone.utc) - timedelta(days=3))
    assert status == "SKIPPED_OLD" and batch is None and service.sent == []


def test_duplicate_delivery_is_processed_once(env):
    db, mailbox, _ = env
    service = FakeMailbox()
    ctx = pipeline.IntakeEmailContext(
        gmail_message_id="dup", stored_message_id="<dup@client.com>", thread_id=None,
        headers={"_body_plain": "hi"}, sender_name="", sender_email="a@client.com",
        recipient_email=mailbox.email_address, subject="s", received_at=datetime.now(timezone.utc), payload={},
    )
    asyncio.run(pipeline.process_document_intake_email(mailbox.id, service, ctx))
    asyncio.run(pipeline.process_document_intake_email(mailbox.id, service, ctx))
    assert db.query(EmailBatch).filter_by(message_id="<dup@client.com>").count() == 1
    assert len(service.sent) == 2      # ack + no-attachment, not repeated


def test_reprocess_does_not_resend_the_acknowledgement(env, monkeypatch):
    db, mailbox, _ = env
    from app.services.document_intake.conversion.doc_to_pdf import ConverterUnavailableError

    def unavailable(data, name):
        raise ConverterUnavailableError("LibreOffice is not installed")
    monkeypatch.setattr(pipeline, "convert_doc_to_pdf", unavailable)
    service = FakeMailbox([att("form.docx", make_docx())])
    _, batch = run(db, mailbox, service)
    assert batch.status == "FAILED"

    monkeypatch.setattr(pipeline, "convert_doc_to_pdf", lambda data, name: make_pdf("Converted"))
    ctx = pipeline.IntakeEmailContext(
        gmail_message_id=batch.conversation_id, stored_message_id=batch.message_id, thread_id=None,
        headers={"_body_plain": "again"}, sender_name="Alice", sender_email="alice@client.com",
        recipient_email=mailbox.email_address, subject="Claim documents",
        received_at=batch.received_datetime, payload={},
    )
    status = asyncio.run(pipeline.process_document_intake_email(mailbox.id, service, ctx, reprocess_batch_id=batch.id))
    assert status == "SUCCESS"
    assert len([s for s in subjects(service) if "received your email" in s]) == 1
    assert subjects(service)[-1].endswith("Processed successfully")


# ── Attachment readability checks ─────────────────────────────
OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


def _empty_zip() -> bytes:
    buf = io.BytesIO()
    zipfile.ZipFile(buf, "w").close()
    return buf.getvalue()


@pytest.mark.parametrize("name,factory,expected", [
    ("ok.pdf", make_pdf, "OK"),
    ("ok.tiff", make_tiff, "OK"),
    ("ok.docx", make_docx, "OK"),
    ("legacy.doc", lambda: OLE_MAGIC + bytes(600), "OK"),
    ("empty.pdf", lambda: b"", "UNREADABLE"),
    ("fake.docx", lambda: b"just text", "UNREADABLE"),
    ("zip.docx", _empty_zip, "UNREADABLE"),
    ("locked.pdf", make_encrypted_pdf, "PROTECTED"),
], ids=lambda value: value if isinstance(value, str) else None)
def test_attachment_checks(name, factory, expected):
    assert check_attachment(name, factory()).status == expected


def test_encrypted_docx_is_protected(tmp_path):
    assert check_attachment("locked.docx", make_encrypted_docx(tmp_path)).status == "PROTECTED"
