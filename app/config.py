from pydantic_settings import BaseSettings
from pydantic import model_validator
from typing import Optional
from pathlib import Path
from urllib.parse import quote_plus


class Settings(BaseSettings):
    # ── App ───────────────────────────────────────────────────
    APP_NAME: str = "AI Email Assistant"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    FRONTEND_URL: str = "http://localhost:3000"
    # Override in .env as a JSON list, e.g. ALLOWED_ORIGINS=["https://app.example.com"]
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://187.127.166.46:3000",
    ]

    # ── Database – individual fields (read from .env) ─────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "ai_email_db"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""
    DB_TYPE: str = "postgresql"   # postgresql | mysql



    # Computed at startup – do not set manually; use DB_* fields instead
    DATABASE_URL: str = ""

    @model_validator(mode="after")
    def build_database_url(self) -> "Settings":
        """Build DATABASE_URL from individual DB_* env vars if not already set."""
        if not self.DATABASE_URL:
            pwd = quote_plus(self.DB_PASSWORD)
            if self.DB_TYPE.lower() == "mysql":
                self.DATABASE_URL = (
                    f"mysql+pymysql://{self.DB_USER}:{pwd}"
                    f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
                )
            else:
                self.DATABASE_URL = (
                    f"postgresql+psycopg2://{self.DB_USER}:{pwd}"
                    f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
                )
        return self

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.ENVIRONMENT.lower() == "production":
            if self.SECRET_KEY == "change-me-to-a-secure-random-secret" or len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must be a strong, unique value in production")
            if not self.ENCRYPTION_KEY or len(self.ENCRYPTION_KEY) < 32:
                raise ValueError("ENCRYPTION_KEY must be a strong, dedicated value in production")
            if self.ENCRYPTION_KEY == self.SECRET_KEY:
                raise ValueError("ENCRYPTION_KEY must be different from SECRET_KEY in production")
        return self

    # ── Security ──────────────────────────────────────────────
    SECRET_KEY: str = "change-me-to-a-secure-random-secret"
    ENCRYPTION_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ── Ollama (local LLM) ────────────────────────────────────
    OLLAMA_BASE_URL: str = ""
    OLLAMA_MODEL: str = "llama3.2"

    # ── OpenAI (used only when OLLAMA_BASE_URL is empty) ──────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT_SECONDS: float = 60.0
    # Concurrent LLM requests per process. A local Ollama answers one request at a
    # time, so parallel calls only queue up and time out; 0 = auto (1 for Ollama, 4 otherwise).
    LLM_MAX_CONCURRENCY: int = 0

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"

    # ── Gmail OAuth ───────────────────────────────────────────
    GMAIL_CLIENT_ID: str = ""
    GMAIL_CLIENT_SECRET: str = ""
    GMAIL_REDIRECT_URI: str = "http://localhost:5000/api/integrations/gmail/callback"
    GMAIL_WEBHOOK_SECRET: str = ""

    # ── Outlook OAuth ─────────────────────────────────────────
    OUTLOOK_CLIENT_ID: str = ""
    OUTLOOK_CLIENT_SECRET: str = ""
    OUTLOOK_TENANT_ID: str = "common"
    OUTLOOK_REDIRECT_URI: str = "http://localhost:5000/api/integrations/outlook/callback"
    OUTLOOK_WEBHOOK_URL: str = ""
    OUTLOOK_WEBHOOK_CLIENT_STATE: str = ""

    # ── IMAP ──────────────────────────────────────────────────
    IMAP_HOST: str = "imap.gmail.com"
    IMAP_PORT: int = 993
    IMAP_PASSWORD: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""

    # ── Email Processing ──────────────────────────────────────
    FETCH_INTERVAL_SECONDS: int = 60

    # ── Email intake pipeline ─────────────────────────────────
    DOCUMENT_INTAKE_STORAGE_PROVIDER: str = "local"   # local | azure_blob
    DOCUMENT_INTAKE_LOCAL_PATH: str = "./storage/document_intake"
    AZURE_BLOB_CONNECTION_STRING: str = ""
    AZURE_BLOB_CONTAINER_NAME: str = "email-document-intake"
    LIBREOFFICE_BIN_PATH: str = "soffice"
    DOCUMENT_INTAKE_DEFAULT_MAX_FILE_SIZE_MB: int = 25
    DOCUMENT_INTAKE_DEFAULT_ALLOWED_EXTENSIONS: str = "pdf,doc,docx,tiff,tif"
    # Stored PDFs are deleted this many days after an email finished (mailboxes may override).
    DOCUMENT_INTAKE_DEFAULT_RETENTION_DAYS: int = 90
    RETENTION_CHECK_INTERVAL_SECONDS: int = 86400   # daily
    # AI summary of each email (one extra LLM call per email).
    AI_SUMMARY_ENABLED: bool = True
    # Slack/Teams incoming-webhook URL for "needs attention" alerts (empty = off).
    OPS_ALERT_WEBHOOK_URL: str = ""

    # The API picks up new mail itself (no separate process to start). Set to false
    # only when a dedicated worker (python -m app.worker) runs alongside the API.
    RUN_BACKGROUND_WORKERS: bool = True
    API_REQUEST_LOG_MIN_MS: int = 500
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 20
    PASSWORD_MIN_LENGTH: int = 10

    # ── Background jobs (ARQ on Redis; falls back to in-process when Redis is down) ──
    JOB_QUEUE_ENABLED: bool = True
    JOB_MAX_TRIES: int = 5
    JOB_TIMEOUT_SECONDS: int = 600
    JOB_INLINE_CONCURRENCY: int = 3

    # ── Gmail incremental sync / push ──────────────────────────
    GMAIL_PUBSUB_TOPIC: str = ""               # projects/<project>/topics/<topic> — enables users.watch
    GMAIL_MARK_PROCESSED_READ: bool = True

    # ── Auth cookies / MFA ─────────────────────────────────────
    AUTH_COOKIE_SECURE: Optional[bool] = None  # default: True in production
    AUTH_COOKIE_SAMESITE: str = "lax"
    AUTH_COOKIE_DOMAIN: Optional[str] = None
    MFA_ISSUER: str = "AI Email Assistant"

    # ── Observability ──────────────────────────────────────────
    LOG_FORMAT: str = "text"                   # text | json
    LOG_LEVEL: str = "INFO"
    METRICS_ENABLED: bool = True
    METRICS_TOKEN: str = ""                    # if set, /metrics requires "Authorization: Bearer <token>"
    HEALTH_CHECK_LLM: bool = True
    ENABLE_API_DOCS: bool = True              # set false in production to hide /docs and /redoc

    @property
    def BACKEND_DIR(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def IS_PRODUCTION(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def COOKIE_SECURE(self) -> bool:
        return self.IS_PRODUCTION if self.AUTH_COOKIE_SECURE is None else self.AUTH_COOKIE_SECURE

    def resolve_path(self, value: str) -> Path:
        """Resolve a configured path relative to the backend dir, not the CWD."""
        path = Path(value)
        return path if path.is_absolute() else (self.BACKEND_DIR / path).resolve()

    class Config:
        env_file = Path(__file__).resolve().parents[1] / ".env"
        extra = "ignore"


settings = Settings()
