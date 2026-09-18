"""Application configuration.

Every setting is optional at the type level because the app must start with
an empty `.env` (N4 in the system design): a job with no key records a
`config_missing` failure instead of the process failing to boot. Callers that
need a value should read it and handle `None`, or use `Settings.missing_keys`
to surface it in `/api/v1/status`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Role names are part of the contract with the migration in
# api/alembic/versions/ — do not rename without updating both.
APP_OWNER_ROLE = "app_owner"
APP_WRITER_ROLE = "app_writer"
AI_READER_ROLE = "ai_reader"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    environment: str = "development"

    # --- Postgres -----------------------------------------------------
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "stockticker"

    # Bootstrap connection used only by Alembic to create roles/grants.
    # Corresponds to the compose `db` service's POSTGRES_USER/PASSWORD.
    postgres_superuser: str = "postgres"
    postgres_superuser_password: SecretStr | None = None

    postgres_app_writer_password: SecretStr | None = None
    postgres_ai_reader_password: SecretStr | None = None

    # --- External providers --------------------------------------------
    alpaca_key_id: str | None = None
    alpaca_secret_key: str | None = None
    sec_user_agent: str | None = None
    anthropic_api_key: SecretStr | None = None
    ai_model: str = "claude-sonnet-5"
    ai_daily_token_budget: int = 2_000_000

    # --- Web / HTTP ------------------------------------------------------
    web_origin: str = "http://127.0.0.1:3000"
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]

    def _dsn(self, user: str, password: str | None, *, driver: str = "postgresql+asyncpg") -> str:
        auth = user if password is None else f"{user}:{password}"
        return f"{driver}://{auth}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def app_writer_dsn(self) -> str:
        password = (
            self.postgres_app_writer_password.get_secret_value()
            if self.postgres_app_writer_password
            else None
        )
        return self._dsn(APP_WRITER_ROLE, password)

    @property
    def ai_reader_dsn(self) -> str:
        password = (
            self.postgres_ai_reader_password.get_secret_value() if self.postgres_ai_reader_password else None
        )
        return self._dsn(AI_READER_ROLE, password)

    @property
    def superuser_dsn(self) -> str:
        password = (
            self.postgres_superuser_password.get_secret_value() if self.postgres_superuser_password else None
        )
        return self._dsn(self.postgres_superuser, password)

    @property
    def superuser_dsn_sync(self) -> str:
        """Used by Alembic (`api/alembic/env.py`), which runs synchronously."""
        password = (
            self.postgres_superuser_password.get_secret_value() if self.postgres_superuser_password else None
        )
        return self._dsn(self.postgres_superuser, password, driver="postgresql+psycopg")

    def missing_keys(self) -> list[str]:
        """Names of unset external-provider keys, for `/api/v1/status` and
        for `worker.JobSpec.requires_keys` (the names must match exactly)."""
        missing = []
        if not self.alpaca_key_id:
            missing.append("ALPACA_KEY_ID")
        if not self.alpaca_secret_key:
            missing.append("ALPACA_SECRET_KEY")
        if not self.sec_user_agent:
            missing.append("SEC_USER_AGENT")
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
