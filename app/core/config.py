from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    fernet_key: str
    totp_issuer_name: str = "Stradit Workforce"

    super_admin_email: str = "admin@emperp.local"
    super_admin_password: str = ""
    super_admin_name: str = "Super Admin"
    super_admin_company_name: str = "Default Company"

    cors_origins: str = "http://localhost:8000"

    login_max_attempts: int = 5
    login_lockout_window_minutes: int = 15

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
