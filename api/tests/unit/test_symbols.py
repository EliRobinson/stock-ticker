import pytest

from stockticker.ingest.symbols import normalize_cik, normalize_symbol


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
