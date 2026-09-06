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
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ]

    # ── Database – individual fields (read from .env) ─────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "ai_email_db"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "1234"
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

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379"

    # ── Gmail OAuth ───────────────────────────────────────────
    GMAIL_CLIENT_ID: str = ""
    GMAIL_CLIENT_SECRET: str = ""
    GMAIL_REDIRECT_URI: str = "http://localhost:8000/api/integrations/gmail/callback"
    GMAIL_WEBHOOK_SECRET: str = ""

    # ── Outlook OAuth ─────────────────────────────────────────
    OUTLOOK_CLIENT_ID: str = ""
    OUTLOOK_CLIENT_SECRET: str = ""
    OUTLOOK_TENANT_ID: str = "common"
    OUTLOOK_REDIRECT_URI: str = "http://localhost:8000/api/integrations/outlook/callback"
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
    NOTIFY_ON_NEGATIVE: bool = True
    NOTIFY_ON_CRITICAL: bool = True
    AUTO_REPLY_ENABLED: bool = False
    AUTO_REPLY_CONFIDENCE_THRESHOLD: float = 0.80

    # ── Document Intake Pipeline ──────────────────────────────
    DOCUMENT_INTAKE_STORAGE_PROVIDER: str = "local"   # local | azure_blob
    DOCUMENT_INTAKE_LOCAL_PATH: str = "./storage/document_intake"
    AZURE_BLOB_CONNECTION_STRING: str = ""
    AZURE_BLOB_CONTAINER_NAME: str = "email-document-intake"
    LIBREOFFICE_BIN_PATH: str = "soffice"
    DOCUMENT_INTAKE_DEFAULT_MAX_FILE_SIZE_MB: int = 25
    DOCUMENT_INTAKE_DEFAULT_ALLOWED_EXTENSIONS: str = "pdf,doc,docx,tiff,tif"

    # ── AI Analysis & Sensitivity Scanning (reuses existing Ollama/OpenAI client) ──
    AI_SENSITIVITY_DEEP_SCAN: bool = False
    AI_SENSITIVITY_BLOCK_RESTRICTED: bool = False

    # ── Client Callback Notification ──────────────────────────
    CALLBACK_TIMEOUT_SECONDS: int = 10
    CALLBACK_MAX_RETRIES: int = 3
    CALLBACK_RETRY_BACKOFF_SECONDS: str = "1,5,15"
    OPS_ALERT_WEBHOOK_URL: str = ""   # Slack/Teams incoming webhook — open question #8

    # ── Retention & Archival (open question #5) ───────────────
    DOCUMENT_INTAKE_DEFAULT_RETENTION_DAYS: int = 90
    RETENTION_CHECK_INTERVAL_SECONDS: int = 86400   # daily
    # Run polling in the dedicated worker process, not inside the API by default.
    RUN_BACKGROUND_WORKERS: bool = False
    API_REQUEST_LOG_MIN_MS: int = 500

    class Config:
        env_file = Path(__file__).resolve().parents[1] / ".env"
        extra = "ignore"


settings = Settings()
