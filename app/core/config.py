from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3_dialect(cls, v: str) -> str:
        # Managed Postgres add-ons (Render, Heroku, ...) inject plain
        # postgresql:// / postgres:// URLs, which SQLAlchemy resolves to the
        # psycopg2 dialect. This project only installs psycopg3 (psycopg[binary]).
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 360
    refresh_token_expire_days: int = 1

    fernet_key: str
    totp_issuer_name: str = "Stradit Workforce"

    super_admin_email: str = "admin@emperp.local"
    super_admin_password: str = ""
    super_admin_name: str = "Super Admin"
    super_admin_company_name: str = "Default Company"

    cors_origins: str = "http://localhost:8000"

    login_max_attempts: int = 5
    login_lockout_window_minutes: int = 15

    # Secret required to call POST /api/v1/auth/bootstrap-reset-password.
    # Empty (default) disables the endpoint entirely. Set only when recovering
    # a locked-out super admin account, then unset/rotate it again.
    admin_bootstrap_token: str = ""

    email_backend: str = "console"  # "console" (log only) or "smtp"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_address: str = "noreply@emperp.dev"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
