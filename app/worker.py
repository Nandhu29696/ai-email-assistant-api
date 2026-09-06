"""Dedicated process for mailbox polling and retention work."""
from __future__ import annotations

import asyncio

from loguru import logger

from app.services.gmail_sync import start_email_poller
from app.services.document_intake.retention_service import start_retention_archiver


async def run_workers() -> None:
    await asyncio.gather(
        start_email_poller(),
        start_retention_archiver(),
    )


def main() -> None:
    logger.info("Starting dedicated background worker")
    try:
        asyncio.run(run_workers())
    except KeyboardInterrupt:
        logger.info("Background worker stopped")


if __name__ == "__main__":
    main()