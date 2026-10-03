from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.types import DateTime, TypeDecorator
from app.config import settings

_db_type = settings.DB_TYPE.lower()

_engine_kwargs: dict = {
    "pool_pre_ping": True,
}

if not settings.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs.update({"pool_size": 10, "max_overflow": 20})

if _db_type == "mysql":
    # Recycle connections before MySQL's default 8-hour wait_timeout
    _engine_kwargs["pool_recycle"] = 3600

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Expose DB type so models can branch on dialect where needed
DB_TYPE: str = _db_type


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetime that behaves the same on every backend.

    MySQL (and SQLite) drop tzinfo, so values come back naive and comparing
    them with ``datetime.now(timezone.utc)`` raises ``TypeError``. Values are
    normalised to UTC on the way in and always returned as aware UTC.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        if dialect.name in ("mysql", "sqlite"):
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_db():
    """Dependency: yield a database session and close it after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
