"""Dimension entry has to accept what an estimator types, not a canonical form."""

from __future__ import annotations

import pytest

from coursework.model.units import UnitParseError, format_ft_in, parse_ft_in


@pytest.mark.parametrize(
    "text,expected",
    [
        ("20'-6\"", 20.5),
        ("20' 6\"", 20.5),
        ("20'6\"", 20.5),
        ("20-6", 20.5),
        ("20'", 20.0),
        ("20", 20.0),
        ("20.5", 20.5),
        ("6\"", 0.5),
        ("20' 6 1/2\"", 20 + 6.5 / 12),
        ("20'-1/2\"", 20 + 0.5 / 12),
        ("20ft 6in", 20.5),
        ("  20' - 6\"  ", 20.5),
        ("20’-6”", 20.5),
    ],
)
def test_parse(text, expected):
    assert parse_ft_in(text) == pytest.approx(expected)


@pytest.mark.parametrize("bad", ["", "   ", "abc", "20' x 6", "--"])
def test_bad_input_raises(bad):
    with pytest.raises(UnitParseError):
        parse_ft_in(bad)


@pytest.mark.parametrize(
    "value,expected",
    [
        (20.5, "20'-6\""),
        (20.0, "20'-0\""),
        (0.5, "0'-6\""),
        (20 + 6.5 / 12, "20'-6 1/2\""),
        (0.635417, "0'-7 5/8\""),
        (0.302083, "0'-3 5/8\""),
    ],
)
def test_format(value, expected):
    assert format_ft_in(value) == expected


@pytest.mark.parametrize("value", [0.1, 1.0, 12.3456, 99.9, 0.635417])
def test_round_trip_within_a_sixteenth(value):
    assert parse_ft_in(format_ft_in(value)) == pytest.approx(value, abs=1 / 12 / 16)


def test_nominal_block_reads_back_as_the_trade_name():
    """7-5/8" actual is what the catalog stores for 8" nominal block."""
    assert format_ft_in(7.625 / 12) == "0'-7 5/8\""
