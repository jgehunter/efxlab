"""
Unit tests for state model.
"""

from decimal import Decimal

import pytest

from efxlab.events import Side
from efxlab.state import EngineState, MarketRate, apply_trade


def test_initial_state():
    """Test initial engine state."""
    state = EngineState()
    assert state.reporting_currency == "USD"
    assert state.event_count == 0
    assert len(state.cash_balances) == 0
    assert len(state.positions) == 0


def test_cash_balance_operations():
    """Test cash balance updates."""
    state = EngineState()

    # Add cash
    state = state.update_cash("USD", Decimal("1000"))
    assert state.get_cash_balance("USD") == Decimal("1000")

    # Add more cash
    state = state.update_cash("USD", Decimal("500"))
    assert state.get_cash_balance("USD") == Decimal("1500")

    # Subtract cash
    state = state.update_cash("USD", Decimal("-200"))
    assert state.get_cash_balance("USD") == Decimal("1300")

    # Multiple currencies
    state = state.update_cash("EUR", Decimal("2000"))
    assert state.get_cash_balance("EUR") == Decimal("2000")
    assert state.get_cash_balance("USD") == Decimal("1300")


def test_position_operations():
    """Test position updates."""
    state = EngineState()

    # Open position
    state = state.update_position("EUR/USD", Decimal("1000000"))
    assert state.get_position("EUR/USD") == Decimal("1000000")

    # Increase position
    state = state.update_position("EUR/USD", Decimal("500000"))
    assert state.get_position("EUR/USD") == Decimal("1500000")

    # Reduce position
    state = state.update_position("EUR/USD", Decimal("-1000000"))
    assert state.get_position("EUR/USD") == Decimal("500000")


def test_market_rate_operations():
    """Test market rate updates."""
    state = EngineState()

    # Add market rate
    state = state.update_market_rate(
        "EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    rate = state.get_market_rate("EUR/USD")
    assert rate is not None
    assert rate.bid == Decimal("1.0995")
    assert rate.ask == Decimal("1.1005")
    assert rate.mid == Decimal("1.1000")


def test_apply_trade_buy():
    """Test applying a BUY trade (client buys from desk)."""
    state = EngineState()

    # Client buys 1M EUR/USD at 1.1000
    # Desk perspective: sell 1M EUR, receive 1.1M USD
    state = apply_trade(
        state,
        currency_pair="EUR/USD",
        side=Side.BUY,
        notional=Decimal("1000000"),
        price=Decimal("1.1000"),
    )

    assert state.get_cash_balance("EUR") == Decimal("-1000000")
    assert state.get_cash_balance("USD") == Decimal("1100000")
    assert state.get_position("EUR/USD") == Decimal("-1000000")


def test_apply_trade_sell():
    """Test applying a SELL trade (client sells to desk)."""
    state = EngineState()

    # Client sells 1M EUR/USD at 1.1000
    # Desk perspective: buy 1M EUR, pay 1.1M USD
    state = apply_trade(
        state,
        currency_pair="EUR/USD",
        side=Side.SELL,
        notional=Decimal("1000000"),
        price=Decimal("1.1000"),
    )

    assert state.get_cash_balance("EUR") == Decimal("1000000")
    assert state.get_cash_balance("USD") == Decimal("-1100000")
    assert state.get_position("EUR/USD") == Decimal("1000000")


def test_apply_multiple_trades():
    """Test multiple trades."""
    state = EngineState()

    # Trade 1: Client buys 1M EUR/USD at 1.1000
    state = apply_trade(
        state,
        currency_pair="EUR/USD",
        side=Side.BUY,
        notional=Decimal("1000000"),
        price=Decimal("1.1000"),
    )

    # Trade 2: Client sells 500K EUR/USD at 1.1050
    state = apply_trade(
        state,
        currency_pair="EUR/USD",
        side=Side.SELL,
        notional=Decimal("500000"),
        price=Decimal("1.1050"),
    )

    # Net position: -1M + 500K = -500K EUR
    assert state.get_position("EUR/USD") == Decimal("-500000")

    # Net cash EUR: -1M + 500K = -500K
    assert state.get_cash_balance("EUR") == Decimal("-500000")

    # Net cash USD: +1.1M - 552.5K = +547.5K
    expected_usd = Decimal("1100000") - Decimal("552500")
    assert state.get_cash_balance("USD") == expected_usd


def test_compute_exposures():
    """Test exposure calculation."""
    state = EngineState()

    # Add market rate
    state = state.update_market_rate(
        "EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    # Long 1M EUR/USD
    state = state.update_position("EUR/USD", Decimal("1000000"))

    exposures = state.compute_exposures()

    # Should be long 1M EUR, short ~1.1M USD
    assert exposures["EUR"] == Decimal("1000000")
    assert exposures["USD"] == Decimal("-1100000")  # -1M * 1.1


def test_state_immutability():
    """Test that state updates return new instances."""
    state1 = EngineState()
    state2 = state1.update_cash("USD", Decimal("1000"))

    assert state1 is not state2
    assert state1.get_cash_balance("USD") == Decimal("0")
    assert state2.get_cash_balance("USD") == Decimal("1000")


def test_state_serialization():
    """Test state to_dict for serialization."""
    state = EngineState(reporting_currency="EUR")
    state = state.update_cash("USD", Decimal("1000"))
    state = state.update_position("EUR/USD", Decimal("500000"))

    data = state.to_dict()

    assert data["reporting_currency"] == "EUR"
    assert data["cash_balances"]["USD"] == "1000"
    assert data["positions"]["EUR/USD"] == "500000"
    assert "exposures" in data
