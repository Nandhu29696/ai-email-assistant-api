from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

_db_type = settings.DB_TYPE.lower()

_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "pool_size": 10,
    "max_overflow": 20,
}

if _db_type == "mysql":
    # Recycle connections before MySQL's default 8-hour wait_timeout
    _engine_kwargs["pool_recycle"] = 3600

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Expose DB type so models can branch on dialect where needed
DB_TYPE: str = _db_type


def get_db():
    """Dependency: yield a database session and close it after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
