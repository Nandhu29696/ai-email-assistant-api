"""Load the 20 test emails into the configured database for tracking in the UI.

The emails run through the real pipeline (real AI model, LibreOffice, storage)
against a dedicated, inactive test mailbox. Nothing is sent: replies and folder
moves go to a fake mailbox, but every step, reply decision, attachment status and
PDF is stored in the normal tables (email_batches, email_batch_events,
email_batch_attachments) exactly as for real mail.

    python -m scripts.load_test_emails            # load (skips emails already loaded)
    python -m scripts.load_test_emails --cleanup  # remove the test mailbox, its emails and PDFs
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401
from app.models.document_intake import EmailBatch, EmailBatchAttachment  # noqa: E402
from app.models.email import EmailIntegration  # noqa: E402
from app.services.document_intake import pipeline  # noqa: E402
from app.services.document_intake.storage.factory import get_adapter_for_path  # noqa: E402

TEST_MAILBOX = "intake-test@mailai.local"
MESSAGE_PREFIX = "<test-intake-"


def _test_mailbox(db) -> EmailIntegration:
    box = db.query(EmailIntegration).filter(EmailIntegration.email_address == TEST_MAILBOX).first()
    if box is None:
        box = EmailIntegration(
            provider="imap", email_address=TEST_MAILBOX, is_active=False,   # never polled
            batch_prefix="TEST", mailbox_type="UAT", health_status="unknown",
            health_message="Test mailbox for scripts/load_test_emails.py — not connected",
            allowed_sender_domains="client.com,partner.org", max_file_size_mb=1,
            process_since=datetime.now(timezone.utc) - timedelta(days=30),
        )
        db.add(box)
        db.commit()
        db.refresh(box)
    return box


async def load() -> None:
    from tests.test_intake_20_emails import received_at, scenarios
    from tests.test_intake_flow import FakeMailbox, att

    db = SessionLocal()
    try:
        box_id = _test_mailbox(db).id
        done = {m for (m,) in db.query(EmailBatch.message_id).filter(EmailBatch.integration_id == box_id)}
    finally:
        db.close()

    with tempfile.TemporaryDirectory() as tmp:
        for index, sc in enumerate(scenarios(tmp)):
            message_id = f"{MESSAGE_PREFIX}{index + 1:02d}@mailai.local>"
            if message_id in done:
                print(f"{index + 1:2}. already loaded — {sc.name}")
                continue
            service = FakeMailbox([att(name, factory()) for name, factory in sc.files])
            ctx = pipeline.IntakeEmailContext(
                gmail_message_id=f"test-{index + 1}", stored_message_id=message_id, thread_id=None,
                headers={"Subject": sc.name, "_body_plain": sc.body, **sc.headers},
                sender_name=sc.sender.split("@")[0].title(), sender_email=sc.sender,
                recipient_email=TEST_MAILBOX, subject=f"[TEST] {sc.name}",
                received_at=received_at(sc.days_ago, index), payload={},
            )
            status = await pipeline.process_document_intake_email(box_id, service, ctx)
            ok = "OK" if status == sc.status else f"EXPECTED {sc.status}"
            print(f"{index + 1:2}. {ctx.received_at:%d %b}  {status:<9} {ok:<3}  {sc.name}  "
                  f"(replies that would be sent: {len(service.sent)})")


def cleanup() -> None:
    db = SessionLocal()
    try:
        box = db.query(EmailIntegration).filter(EmailIntegration.email_address == TEST_MAILBOX).first()
        if box is None:
            print("Nothing to clean up.")
            return
        batches = db.query(EmailBatch).filter(EmailBatch.integration_id == box.id).all()
        paths = [p for b in batches for p in (b.merged_pdf_path, b.email_pdf_path) if p]
        paths += [p for (p,) in db.query(EmailBatchAttachment.converted_pdf_path).filter(
            EmailBatchAttachment.parent_batch_id.in_([b.id for b in batches] or [0])) if p]
        for path in paths:
            try:
                get_adapter_for_path(path).delete(path)
            except Exception as exc:
                print(f"could not delete {path}: {exc}")
        for batch in batches:
            db.delete(batch)            # events and attachments cascade
        db.delete(box)
        db.commit()
        print(f"Removed {len(batches)} test email(s), {len(paths)} PDF file(s) and the test mailbox.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    cleanup() if args.cleanup else asyncio.run(load())
