from pydantic import SecretStr
from sqlalchemy.engine import make_url

from stockticker.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg,arg-type]


def test_app_writer_dsn_round_trips_a_password_with_url_special_characters() -> None:
    """A naive f-string DSN (`f"{user}:{password}@{host}..."`) breaks
    silently on a password containing '@', ':', or '/': the parser reads
    part of the password as the host or path instead. URL.create builds
    the DSN component by component, so it can't happen."""
    settings = _settings(postgres_app_writer_password=SecretStr("p@ss:/"))
    url = settings.app_writer_dsn

    assert url.password == "p@ss:/"
    assert url.username == "app_writer"

    rendered = url.render_as_string(hide_password=False)
    reparsed = make_url(rendered)
    assert reparsed.password == "p@ss:/"
    assert reparsed.username == "app_writer"
    assert reparsed.host == settings.postgres_host
    assert reparsed.database == settings.postgres_db


def test_ai_reader_dsn_round_trips_a_password_with_url_special_characters() -> None:
    settings = _settings(postgres_ai_reader_password=SecretStr("p@ss:/"))
    url = settings.ai_reader_dsn
    reparsed = make_url(url.render_as_string(hide_password=False))
    assert reparsed.password == "p@ss:/"
    assert reparsed.username == "ai_reader"


def test_dsn_with_no_password_set_has_no_password() -> None:
    # Explicit None, not just an empty override dict: this test runs
    # inside `docker compose`, where POSTGRES_APP_WRITER_PASSWORD is a
    # real environment variable that pydantic-settings reads regardless
    # of _env_file -- only an explicit override beats it.
    settings = _settings(postgres_app_writer_password=None)
    assert settings.app_writer_dsn.password is None
