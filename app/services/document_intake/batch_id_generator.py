"""
Batch ID generator (§1: Requirement #1, §11.3 open question resolved).

Format: {batch_prefix}-{mailbox_type}-{YYYYMMDD}-{seq:06d}
Uses a DB-backed row-lock counter (batch_sequences) so numbering stays
unique and gap-free even when multiple pollers run concurrently.
"""
from __future__ import annotations
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.document_intake import BatchSequence


def generate_batch_no(db: Session, batch_prefix: str, mailbox_type: str) -> str:
    """
    Atomically increment and return the next batch number for today.
    Must be called within an active transaction; caller is responsible for db.commit().
    """
    prefix = (batch_prefix or "GEN").upper()
    mbx = (mailbox_type or "PROD").upper()
    day_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    sequence_key = f"{prefix}-{mbx}-{day_str}"

    # Row-level lock to guarantee atomicity under concurrent pollers.
    row = (
        db.query(BatchSequence)
        .filter(BatchSequence.sequence_key == sequence_key)
        .with_for_update()
        .first()
    )
    if row is None:
        # Two workers may try to create today's counter at once; the loser of
        # the unique-key race rolls back its savepoint and locks the winner's row.
        try:
            with db.begin_nested():
                db.add(BatchSequence(sequence_key=sequence_key, last_value=0))
        except IntegrityError:
            pass
        row = (
            db.query(BatchSequence)
            .filter(BatchSequence.sequence_key == sequence_key)
            .with_for_update()
            .first()
        )

    row.last_value += 1
    seq = row.last_value
    db.flush()

    return f"{sequence_key}-{seq:06d}"
