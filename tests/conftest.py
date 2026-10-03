"""Shared pytest fixtures.

Tests never touch the database configured in ``backend/.env``. The database
under test comes from ``TEST_DATABASE_URLS`` (comma-separated SQLAlchemy URLs,
e.g. one PostgreSQL and one MySQL database — see ``.github/workflows/ci.yml``).
Every test using ``db_session`` runs once per URL. When the variable is unset,
a throwaway SQLite database is used for quick local runs.

The environment below is applied *before* any ``app`` module is imported, so
``settings`` and ``SessionLocal`` point at the test database too.
"""
import os
import tempfile

_TEST_URLS = [u.strip() for u in os.environ.get("TEST_DATABASE_URLS", "").split(",") if u.strip()]
_SQLITE_PATH = os.path.join(tempfile.gettempdir(), f"ai_email_test_{os.getpid()}.db")
_PRIMARY_URL = _TEST_URLS[0] if _TEST_URLS else f"sqlite:///{_SQLITE_PATH}"

os.environ["DATABASE_URL"] = _PRIMARY_URL
os.environ["DB_TYPE"] = "mysql" if _PRIMARY_URL.startswith("mysql") else ("sqlite" if _PRIMARY_URL.startswith("sqlite") else "postgresql")
os.environ["REDIS_URL"] = ""              # no Redis: jobs run in-process
os.environ["JOB_QUEUE_ENABLED"] = "false"
os.environ["OLLAMA_BASE_URL"] = ""        # no LLM calls from tests
os.environ["OPENAI_API_KEY"] = ""
os.environ["ENVIRONMENT"] = "test"
os.environ["GMAIL_PUBSUB_TOPIC"] = ""
os.environ["RUN_BACKGROUND_WORKERS"] = "false"  # tests drive the pipeline directly
os.environ["HEALTH_CHECK_LLM"] = "false"

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, engine as app_engine  # noqa: E402
import app.models  # noqa: E402,F401  (registers all models on Base.metadata)

_engines: dict[str, object] = {}


def _engine_for(url: str):
    if url not in _engines:
        if url.startswith("sqlite"):
            engine = app_engine if url == _PRIMARY_URL else create_engine(url)
        else:
            engine = app_engine if url == _PRIMARY_URL else create_engine(url, pool_pre_ping=True)
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        _engines[url] = engine
    return _engines[url]


# Schema for code paths that use app.database.SessionLocal directly.
_engine_for(_PRIMARY_URL)


def _backend_id(url: str) -> str:
    return url.split(":", 1)[0].split("+", 1)[0]


@pytest.fixture(params=_TEST_URLS or [None], ids=[_backend_id(u) for u in _TEST_URLS] or ["sqlite"])
def db_session(request):
    """A session whose work is rolled back after each test (commits become savepoints)."""
    url = request.param
    if url is None:
        # Local fallback: isolated in-memory SQLite per test.
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        session = Session(bind=engine, autoflush=False)
        try:
            yield session
        finally:
            session.close()
            engine.dispose()
        return

    engine = _engine_for(url)
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, autoflush=False, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        if outer.is_active:
            outer.rollback()
        connection.close()


def pytest_sessionfinish(session, exitstatus):
    for engine in _engines.values():
        try:
            engine.dispose()
        except Exception:
            pass
    try:
        app_engine.dispose()
        if os.path.exists(_SQLITE_PATH):
            os.remove(_SQLITE_PATH)
    except OSError:
        pass
