from sqlalchemy.pool import QueuePool

from stockticker.config import get_settings
from stockticker.db import (
    dispose_engines,
    get_ai_reader_engine,
    get_api_app_writer_engine,
    get_quotes_engine,
    get_worker_app_writer_engine,
)


def test_each_purpose_gets_its_own_engine_with_the_right_pool_size() -> None:
    api_engine = get_api_app_writer_engine()
    worker_engine = get_worker_app_writer_engine()
    quotes_engine = get_quotes_engine()
    ai_engine = get_ai_reader_engine()

    engines = {api_engine, worker_engine, quotes_engine, ai_engine}
    assert len(engines) == 4  # four distinct engine objects, not one shared factory

    assert isinstance(api_engine.pool, QueuePool)
    assert isinstance(worker_engine.pool, QueuePool)
    assert isinstance(quotes_engine.pool, QueuePool)
    assert isinstance(ai_engine.pool, QueuePool)
    assert api_engine.pool.size() == 5
    assert worker_engine.pool.size() == 6
    assert quotes_engine.pool.size() == 1
    # Dev DB keeps pool_size=3 (role CONNECTION LIMIT); pytest DB uses 1 (#38).
    expected_ai_pool = 1 if get_settings().postgres_db.endswith("_test") else 3
    assert ai_engine.pool.size() == expected_ai_pool


def test_getters_are_singletons() -> None:
    assert get_api_app_writer_engine() is get_api_app_writer_engine()
    assert get_ai_reader_engine() is get_ai_reader_engine()


async def test_dispose_engines_is_safe_to_call_repeatedly() -> None:
    get_api_app_writer_engine()  # ensure at least one engine has been created
    await dispose_engines()
    await dispose_engines()  # second call: nothing cached, must not raise
