import pytest

from stockticker.ingest.symbols import (
    is_valid_listing_ticker,
    normalize_cik,
    normalize_symbol,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("brk-b", "BRK.B"),
        (" BRK.B ", "BRK.B"),
        ("aapl", "AAPL"),
        ("BF-B", "BF.B"),
        ("GOOGL", "GOOGL"),
        ("googl", "GOOGL"),
    ],
)
def test_normalize_symbol(raw: str, expected: str) -> None:
    assert normalize_symbol(raw) == expected


def test_normalize_symbol_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        normalize_symbol("   ")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("320193", "0000320193"),
        ("1652044", "0001652044"),
        ("0000320193", "0000320193"),
    ],
)
def test_normalize_cik(raw: str, expected: str) -> None:
    assert normalize_cik(raw) == expected


@pytest.mark.parametrize(
    ("symbol", "valid"),
    [
        ("A", True),
        ("AAPL", True),
        ("GOOGL", True),
        ("BRK.B", True),
        ("BF.B", True),
        ("T131793", False),
        ("T137FB9", False),
        ("T3F04A1", False),
        ("BRK.BB", False),
        ("TOOLONG", False),
        ("AAPL1", False),
        ("brk.b", False),
    ],
)
def test_is_valid_listing_ticker(symbol: str, valid: bool) -> None:
    assert is_valid_listing_ticker(symbol) is valid
