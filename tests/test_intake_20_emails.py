"""Twenty different emails, received over two weeks, through the full intake flow.

Every rule and the main edge cases are covered once. For each email the test checks
the final status/outcome, the exact replies sent (and their order), the per-file
statuses and the stored PDFs. It then checks the day-by-day dashboard and the
"last N days" filter against the received dates.

The scenario list is also used by scripts/live_intake_check.py to run the same emails
against the real AI model and LibreOffice.
"""
import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest
from pypdf import PdfReader

from app.models.document_intake import EmailBatch, EmailBatchAttachment
from app.models.user import User
from app.services.document_intake import pipeline
from app.services.document_intake.conversion.doc_to_pdf import find_soffice
from tests.test_intake_flow import (  # noqa: F401  (env is a fixture)
    FakeMailbox, att, env, make_docx, make_encrypted_docx, make_encrypted_pdf, make_pdf, make_tiff,
)

ACK = "We have received your email"
DOMAIN = "Email domain not valid"
NO_ATT = "No attachment found"
UNSUPPORTED = "Unsupported attachment(s)"
UNREADABLE = "Attachment(s) could not be opened"
DONE = "Processed successfully"


@dataclass
class Scenario:
    name: str
    days_ago: int
    sender: str
    body: str
    files: list = field(default_factory=list)       # [(filename, factory)]
    headers: dict = field(default_factory=dict)
    status: str = "SUCCESS"
    outcome: str = "PROCESSED"
    replies: list = field(default_factory=list)     # expected reply subject endings, in order
    file_status: dict = field(default_factory=dict) # filename -> expected attachment status
    merged_pages: int | None = None


def scenarios(tmp_path=None) -> list[Scenario]:
    big = lambda: make_pdf("Big") + b"0" * (2 * 1024 * 1024)  # noqa: E731  (over the 1 MB test limit)
    return [
        Scenario("Invoice from an unknown company", 13, "billing@unknownshop.net",
                 "Please find attached the invoice for your recent order.", [("invoice.pdf", make_pdf)],
                 status="REJECTED", outcome="DOMAIN_NOT_ALLOWED", replies=[DOMAIN]),
        Scenario("Look-alike domain", 12, "claims@evilclient.com",
                 "Urgent: submit these documents now.", [("claim.pdf", make_pdf)],
                 status="REJECTED", outcome="DOMAIN_NOT_ALLOWED", replies=[DOMAIN]),
        Scenario("Sub-domain of a client, no attachment", 12, "ops@mail.client.com",
                 "Hi, I would like to submit a claim. What do you need from me?",
                 status="REJECTED", outcome="NO_ATTACHMENT", replies=[ACK, NO_ATT]),
        Scenario("Forgot the attachment", 11, "alice@client.com",
                 "Hello team, attached is my claim form. Thanks!",
                 status="REJECTED", outcome="NO_ATTACHMENT", replies=[ACK, NO_ATT]),
        Scenario("Single PDF claim", 10, "bob@client.com",
                 "Dear team, please process the attached claim. Kind regards, Bob",
                 [("claim_form.pdf", lambda: make_pdf("Claim", 2))],
                 replies=[ACK, DONE], file_status={"claim_form.pdf": "MERGED"}, merged_pages=3),
        Scenario("PDF and scanned TIFF", 10, "carol@partner.org",
                 "Attached are the invoice and the scanned receipt.",
                 [("invoice.pdf", make_pdf), ("receipt.tiff", lambda: make_tiff(2))],
                 replies=[ACK, DONE], file_status={"invoice.pdf": "MERGED", "receipt.tiff": "MERGED"}, merged_pages=4),
        Scenario("Word claim form", 9, "dave@client.com",
                 "Here is the completed claim form in Word format.", [("claim_form.docx", make_docx)],
                 replies=[ACK, DONE], file_status={"claim_form.docx": "MERGED"}, merged_pages=2),
        Scenario("Three documents at once", 8, "erin@client.com",
                 "Sending all three documents for claim 5512: form, invoice and photo scan.",
                 [("form.docx", make_docx), ("invoice.pdf", lambda: make_pdf("Invoice", 3)), ("photo.tif", lambda: make_tiff(1))],
                 replies=[ACK, DONE], file_status={"form.docx": "MERGED", "invoice.pdf": "MERGED", "photo.tif": "MERGED"},
                 merged_pages=6),
        Scenario("Only a photo (PNG)", 7, "frank@client.com",
                 "Photo of the damage attached.", [("damage.png", lambda: b"\x89PNG\r\n\x1a\nfake")],
                 status="REJECTED", outcome="INVALID_FILE_TYPE", replies=[ACK, UNSUPPORTED],
                 file_status={"damage.png": "INVALID_TYPE"}),
        Scenario("PDF plus a spreadsheet", 7, "grace@partner.org",
                 "Claim attached plus the cost breakdown spreadsheet.",
                 [("claim.pdf", make_pdf), ("costs.xlsx", lambda: b"PK\x03\x04xlsx")],
                 status="REJECTED", outcome="INVALID_FILE_TYPE", replies=[ACK, UNSUPPORTED],
                 file_status={"claim.pdf": "NOT_PROCESSED", "costs.xlsx": "INVALID_TYPE"}),
        Scenario("File too large", 6, "heidi@client.com",
                 "Attached is the full medical report.", [("report.pdf", big)],
                 status="REJECTED", outcome="INVALID_FILE_TYPE", replies=[ACK, UNSUPPORTED],
                 file_status={"report.pdf": "INVALID_TYPE"}),
        Scenario("Password-protected bank statement", 5, "ivan@client.com",
                 "My bank statement is attached (password is my date of birth).", [("statement.pdf", make_encrypted_pdf)],
                 status="REJECTED", outcome="INVALID_ATTACHMENTS", replies=[ACK, UNREADABLE],
                 file_status={"statement.pdf": "PROTECTED"}),
        Scenario("Password-protected Word file", 5, "judy@partner.org",
                 "Protected form attached as requested.", [("form.docx", lambda: make_encrypted_docx(tmp_path))],
                 status="REJECTED", outcome="INVALID_ATTACHMENTS", replies=[ACK, UNREADABLE],
                 file_status={"form.docx": "PROTECTED"}),
        Scenario("Damaged PDF", 4, "ken@client.com",
                 "This is the third time I am sending this, very frustrating!",
                 [("claim.pdf", lambda: b"%PDF-1.4 truncated...")],
                 status="REJECTED", outcome="INVALID_ATTACHMENTS", replies=[ACK, UNREADABLE],
                 file_status={"claim.pdf": "UNREADABLE"}),
        Scenario("Good PDF with a damaged scan", 3, "laura@client.com",
                 "Invoice and scan attached.", [("invoice.pdf", make_pdf), ("scan.tiff", lambda: b"II*\x00broken")],
                 status="REJECTED", outcome="INVALID_ATTACHMENTS", replies=[ACK, UNREADABLE],
                 file_status={"invoice.pdf": "NOT_PROCESSED", "scan.tiff": "UNREADABLE"}),
        Scenario("Empty file", 3, "mike@client.com",
                 "Document attached.", [("document.pdf", lambda: b"")],
                 status="REJECTED", outcome="INVALID_ATTACHMENTS", replies=[ACK, UNREADABLE],
                 file_status={"document.pdf": "UNREADABLE"}),
        Scenario("Upper-case extension and accented name", 2, "nora@partner.org",
                 "Bonjour, veuillez trouver la facture ci-jointe. Merci beaucoup !",
                 [("Facture_été.PDF", make_pdf)],
                 replies=[ACK, DONE], file_status={"Facture_été.PDF": "MERGED"}, merged_pages=2),
        Scenario("Out-of-office auto reply", 1, "oscar@client.com",
                 "I am out of the office until Monday.", [("signature.pdf", make_pdf)],
                 headers={"Auto-Submitted": "auto-replied", "Subject": "Automatic reply: claim"},
                 status="IGNORED", outcome="AUTOMATED_MESSAGE"),
        Scenario("Forged sender", 1, "ceo@client.com",
                 "Please process this urgent payment request.", [("payment.pdf", make_pdf)],
                 headers={"Authentication-Results": "mx.google.com; spf=fail smtp.mailfrom=client.com; dmarc=fail"},
                 status="REJECTED", outcome="SENDER_NOT_VERIFIED"),
        Scenario("Same-day complete submission", 0, "paul@client.com",
                 "Thank you for the quick help last time! Attached are the final documents.",
                 [("final.pdf", lambda: make_pdf("Final", 1)), ("scan.tiff", lambda: make_tiff(1))],
                 replies=[ACK, DONE], file_status={"final.pdf": "MERGED", "scan.tiff": "MERGED"}, merged_pages=3),
    ]


def received_at(days_ago: int, index: int) -> datetime:
    now = datetime.now(timezone.utc)
    day = now.replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    # Never in the future (e.g. today's email when the test runs before 09:00 + offset).
    return min(day + timedelta(minutes=17 * index), now - timedelta(minutes=20 - index))


@pytest.fixture()
def processed(env, monkeypatch, tmp_path):  # noqa: F811  (env is the imported fixture)
    """Run all 20 emails; returns (db, mailbox, [(scenario, service, status, batch_id)])."""
    db, mailbox, _ = env
    from app.models.email import AllowedDomain
    db.add(AllowedDomain(domain="partner.org", is_active=True))
    mailbox.orm.process_since = datetime.now(timezone.utc) - timedelta(days=30)
    mailbox.orm.max_file_size_mb = 1
    db.commit()
    if not find_soffice():   # CI has no LibreOffice: stand in a converter that returns a 1-page PDF
        monkeypatch.setattr(pipeline, "convert_doc_to_pdf", lambda data, name: make_pdf("Converted Word", 1))

    results = []
    for index, sc in enumerate(scenarios(tmp_path)):
        service = FakeMailbox([att(name, factory()) for name, factory in sc.files])
        ctx = pipeline.IntakeEmailContext(
            gmail_message_id=f"gm20-{index}", stored_message_id=f"<email20-{index}@test>", thread_id=f"t{index}",
            headers={"Subject": sc.name, "_body_plain": sc.body, **sc.headers},
            sender_name=sc.sender.split("@")[0].title(), sender_email=sc.sender,
            recipient_email=mailbox.email_address, subject=sc.name,
            received_at=received_at(sc.days_ago, index), payload={},
        )
        status = asyncio.run(pipeline.process_document_intake_email(mailbox.id, service, ctx))
        batch_id = db.query(EmailBatch.id).filter(EmailBatch.message_id == ctx.stored_message_id).scalar()
        results.append((sc, service, status, batch_id))
    return db, mailbox, results


def test_twenty_emails_each_follow_their_rule(processed):
    db, _mailbox, results = processed
    failures = []
    for sc, service, status, batch_id in results:
        batch = db.get(EmailBatch, batch_id)
        problems = []
        if status != sc.status or batch.status != sc.status:
            problems.append(f"status {status}/{batch.status} != {sc.status}")
        if batch.outcome != sc.outcome:
            problems.append(f"outcome {batch.outcome} != {sc.outcome}")
        sent = [subject for subject, _ in service.sent]
        if len(sent) != len(sc.replies) or not all(s.endswith(e) for s, e in zip(sent, sc.replies)):
            problems.append(f"replies {sent} != {sc.replies}")
        files = {r.batch_source_filename: r.status for r in
                 db.query(EmailBatchAttachment).filter_by(parent_batch_id=batch.id)}
        if sc.status not in ("IGNORED",) and sc.outcome != "SENDER_NOT_VERIFIED" and sc.file_status and files != sc.file_status:
            problems.append(f"files {files} != {sc.file_status}")
        analysed = bool(batch.email_category and batch.sentiment)
        if analysed != (sc.status == "SUCCESS"):
            problems.append("AI analysis should exist only for successful emails")
        if problems:
            failures.append(f"{sc.name}: " + "; ".join(problems))
    assert not failures, "\n".join(failures)


def test_problem_files_are_named_in_the_reply(processed):
    _db, _mailbox, results = processed
    for sc, service, _status, _batch_id in results:
        bad = [name for name, status in sc.file_status.items() if status in ("INVALID_TYPE", "PROTECTED", "UNREADABLE")]
        if bad:
            body = service.sent[-1][1]
            for name in bad:
                assert name.split(".")[0] in body, f"{sc.name}: {name} missing from the reply"
            for name, status in sc.file_status.items():
                if status == "NOT_PROCESSED":
                    assert f"<strong>{name}</strong>" not in body, f"{sc.name}: valid file {name} listed as a problem"


def test_successful_emails_have_stored_pdfs_with_email_last(processed):
    db, _mailbox, results = processed
    successes = [r for r in results if r[0].status == "SUCCESS"]
    assert len(successes) == 6
    for sc, service, _status, batch_id in successes:
        batch = db.get(EmailBatch, batch_id)
        merged = PdfReader(batch.merged_pdf_path)
        email_pages = len(PdfReader(batch.email_pdf_path).pages)
        assert len(merged.pages) == sc.merged_pages + email_pages - 1, sc.name
        assert "Email content" in merged.pages[-email_pages].extract_text(), sc.name
        # stored under the month the email was received
        received = batch.received_datetime
        assert f"{received:%Y}" in batch.merged_pdf_path and f"{received:%m}" in batch.merged_pdf_path
        rows = db.query(EmailBatchAttachment).filter_by(parent_batch_id=batch.id).all()
        assert all(r.converted_pdf_path and PdfReader(r.converted_pdf_path).pages for r in rows), sc.name
        success_html = service.sent[-1][1]
        for name, _factory in sc.files:
            assert name in success_html, f"{sc.name}: {name} not listed in the success reply"


def test_dashboard_and_day_filters_follow_received_dates(processed):
    from app.routers.dashboard import summary
    from app.routers.document_intake import list_batches

    db, _mailbox, results = processed
    admin = User(username="dash_admin", email="dash@example.com", hashed_password="x", role="admin", is_active=True)
    db.add(admin)
    db.commit()

    data = summary(days=30, months=None, integration_id=None, db=db, current_user=admin)
    assert data["total"] == 20
    assert data["by_status"] == {"SUCCESS": 6, "REJECTED": 13, "IGNORED": 1}
    expected_outcomes = Counter(sc.outcome for sc, *_ in results)
    assert {k: v for k, v in data["by_outcome"].items() if v} == dict(expected_outcomes)
    per_day = {row["date"]: row["SUCCESS"] + row["REJECTED"] + row["FAILED"] + row["IGNORED"] + row["IN_PROGRESS"] + row["OTHER"] for row in data["daily"]}
    expected_days = Counter(received_at(sc.days_ago, i).date().isoformat() for i, (sc, *_rest) in enumerate(results))
    assert per_day == dict(expected_days)
    assert len(per_day) == 14          # 20 emails over 14 distinct days (13 days ago .. today)

    last_week = list_batches(db=db, current_user=admin, status=None, outcome=None, category=None, sentiment=None, priority=None, integration_id=None, mailbox_type=None,
                             search=None, days=7, page=1, page_size=100)
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    assert last_week["total"] == sum(1 for i, (sc, *_rest) in enumerate(results) if received_at(sc.days_ago, i) >= cutoff)
    failed_rule = list_batches(db=db, current_user=admin, status=None, outcome="INVALID_ATTACHMENTS", category=None, priority=None, integration_id=None, mailbox_type=None,
                               sentiment=None, search=None, days=30, page=1, page_size=100)
    assert failed_rule["total"] == 5
