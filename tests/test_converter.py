"""
Unit tests for currency converter.
"""

from decimal import Decimal

import pytest

from efxlab.converter import ConversionError, CurrencyConverter
from efxlab.state import EngineState


def test_same_currency_conversion():
    """Test conversion when currencies are the same."""
    state = EngineState()
    converter = CurrencyConverter(state)

    result = converter.convert(Decimal("1000"), "USD", "USD")
    assert result == Decimal("1000")


def test_direct_pair_conversion():
    """Test conversion using direct currency pair."""
    state = EngineState()
    state = state.update_market_rate(
        "EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    converter = CurrencyConverter(state)

    # Convert 1000 EUR to USD using mid rate
    result = converter.convert(Decimal("1000"), "EUR", "USD", use_mid=True)
    assert result == Decimal("1100")


def test_inverse_pair_conversion():
    """Test conversion using inverse currency pair."""
    state = EngineState()
    state = state.update_market_rate(
        "EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    converter = CurrencyConverter(state)

    # Convert 1100 USD to EUR using mid rate (inverse of EUR/USD)
    result = converter.convert(Decimal("1100"), "USD", "EUR", use_mid=True)
    assert result == Decimal("1000")


def test_conversion_with_bid_ask():
    """Test conversion considering bid/ask spread."""
    state = EngineState()
    state = state.update_market_rate(
        "EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    converter = CurrencyConverter(state)

    # Positive amount uses bid for direct pair
    result = converter.convert(Decimal("1000"), "EUR", "USD", use_mid=False)
    assert result == Decimal("1099.5")  # 1000 * 1.0995

    # Negative amount uses ask for direct pair
    result = converter.convert(Decimal("-1000"), "EUR", "USD", use_mid=False)
    assert result == Decimal("-1100.5")  # -1000 * 1.1005


def test_missing_rate_conversion():
    """Test conversion when rate is not available."""
    state = EngineState()
    converter = CurrencyConverter(state)

    with pytest.raises(ConversionError, match="No market rate available"):
        converter.convert(Decimal("1000"), "EUR", "USD")


def test_convert_to_reporting():
    """Test conversion to reporting currency."""
    state = EngineState(reporting_currency="USD")
    state = state.update_market_rate(
        "EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    converter = CurrencyConverter(state)

    result = converter.convert_to_reporting(Decimal("1000"), "EUR")
    assert result == Decimal("1100")


def test_get_rate():
    """Test getting exchange rate between currencies."""
    state = EngineState()
    state = state.update_market_rate(
        "EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    converter = CurrencyConverter(state)

    # Direct rate
    rate = converter.get_rate("EUR", "USD")
    assert rate == Decimal("1.1000")

    # Inverse rate
    rate = converter.get_rate("USD", "EUR")
    assert abs(rate - Decimal("1") / Decimal("1.1000")) < Decimal("0.000001")

    # Same currency
    rate = converter.get_rate("USD", "USD")
    assert rate == Decimal("1")
