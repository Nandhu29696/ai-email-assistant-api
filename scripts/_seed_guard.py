"""Safety guard shared by the development seed scripts."""
from __future__ import annotations

import sys

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres", "db", "mysql"}


def require_local_database(allow_remote: bool) -> None:
    """Refuse to seed (or drop!) a shared/remote database unless explicitly allowed."""
    from app.config import settings

    if settings.IS_PRODUCTION:
        sys.exit("Refusing to seed: ENVIRONMENT=production.")
    if settings.DATABASE_URL.startswith("sqlite"):
        return
    if settings.DB_HOST not in _LOCAL_HOSTS and not allow_remote:
        sys.exit(
            f"Refusing to seed remote database host '{settings.DB_HOST}'. "
            "Seed data (with demo passwords) is for local development only. "
            "Pass --allow-remote if you really mean it."
        )


def confirm_reset() -> None:
    from app.config import settings

    answer = input(
        f"This DROPS ALL TABLES in '{settings.DB_NAME}' on '{settings.DB_HOST}'. "
        f"Type the database name to continue: "
    )
    if answer.strip() != settings.DB_NAME:
        sys.exit("Aborted.")
