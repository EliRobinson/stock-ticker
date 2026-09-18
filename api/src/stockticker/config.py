"""Application configuration.

Every setting is optional at the type level because the app must start with
an empty `.env` (N4 in the system design): a job with no key records a
`config_missing` failure instead of the process failing to boot. Callers that
need a value should read it and handle `None`, or use `Settings.missing_keys`
to surface it in `/api/v1/status`.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import ClassVar

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

# Role names are part of the contract with the migration in
# api/alembic/versions/ — do not rename without updating both.
APP_OWNER_ROLE = "app_owner"
APP_WRITER_ROLE = "app_writer"
AI_READER_ROLE = "ai_reader"


class RequiredKey(StrEnum):
    """A `JobSpec.requires_keys` entry (`ingest/registry.py`). Values match
    the env var name exactly."""

    ALPACA_KEY_ID = "ALPACA_KEY_ID"
    ALPACA_SECRET_KEY = "ALPACA_SECRET_KEY"
    SEC_USER_AGENT = "SEC_USER_AGENT"
    ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"


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
    ai_spend_limit_usd: Decimal = Decimal("5.00")

    # --- Web / HTTP ------------------------------------------------------
    web_origin: str = "http://127.0.0.1:3000"
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]

    def _url(self, user: str, password: str | None, *, driver: str = "postgresql+asyncpg") -> URL:
        """`URL.create` builds and percent-encodes the DSN component by
        component, so a password containing `@`, `:`, `/`, or any other
        URL-special character round-trips correctly -- an f-string
        concatenation would silently produce a wrong (or unparseable) DSN
        for exactly those passwords."""
        return URL.create(
            drivername=driver,
            username=user,
            password=password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @staticmethod
    def _unwrap(secret: SecretStr | None) -> str | None:
        return secret.get_secret_value() if secret else None

    @property
    def app_writer_dsn(self) -> URL:
        return self._url(APP_WRITER_ROLE, self._unwrap(self.postgres_app_writer_password))

    @property
    def ai_reader_dsn(self) -> URL:
        return self._url(AI_READER_ROLE, self._unwrap(self.postgres_ai_reader_password))

    @property
    def superuser_dsn(self) -> URL:
        return self._url(self.postgres_superuser, self._unwrap(self.postgres_superuser_password))

    @property
    def superuser_dsn_sync(self) -> URL:
        """Used by Alembic (`api/alembic/env.py`), which runs synchronously."""
        return self._url(
            self.postgres_superuser,
            self._unwrap(self.postgres_superuser_password),
            driver="postgresql+psycopg",
        )

    _KEY_FIELDS: ClassVar[dict[RequiredKey, str]] = {
        RequiredKey.ALPACA_KEY_ID: "alpaca_key_id",
        RequiredKey.ALPACA_SECRET_KEY: "alpaca_secret_key",
        RequiredKey.SEC_USER_AGENT: "sec_user_agent",
        RequiredKey.ANTHROPIC_API_KEY: "anthropic_api_key",
    }

    def is_missing(self, key: RequiredKey) -> bool:
        return not getattr(self, self._KEY_FIELDS[key])

    def missing_keys(self, required: Iterable[RequiredKey] | None = None) -> list[str]:
        """Names of unset keys among `required` (default: every `RequiredKey`).
        `/api/v1/status` calls this with the union of `requires_keys` across
        `ingest.registry.JOBS`, so it reports only what's actually gating a
        registered job."""
        keys = required if required is not None else tuple(RequiredKey)
        return [key.value for key in keys if self.is_missing(key)]


@lru_cache
def get_settings() -> Settings:
    return Settings()
