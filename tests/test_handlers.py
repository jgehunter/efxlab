"""
Unit tests for event handlers.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from efxlab.events import (
    ClientTradeEvent,
    ClockTickEvent,
    ConfigUpdateEvent,
    EventType,
    HedgeFillEvent,
    HedgeOrderEvent,
    MarketUpdateEvent,
    Side,
)
from efxlab.handlers import (
    handle_client_trade,
    handle_clock_tick,
    handle_config_update,
    handle_hedge_fill,
    handle_hedge_order,
    handle_market_update,
)
from efxlab.state import EngineState


def test_handle_client_trade():
    """Test client trade handler."""
    state = EngineState()
    event = ClientTradeEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.CLIENT_TRADE,
        currency_pair="EUR/USD",
        side=Side.BUY,
        notional=Decimal("1000000"),
        price=Decimal("1.1000"),
        client_id="CLIENT_001",
        trade_id="TRADE_001",
    )

    new_state, outputs = handle_client_trade(state, event)

    # Check state updates
    assert new_state.get_cash_balance("EUR") == Decimal("-1000000")
    assert new_state.get_cash_balance("USD") == Decimal("1100000")
    assert new_state.get_position("EUR/USD") == Decimal("-1000000")
    assert new_state.event_count == 1

    # Check outputs
    assert len(outputs) == 1
    assert outputs[0].record_type == "client_trade"
    assert outputs[0].data["trade_id"] == "TRADE_001"


def test_handle_market_update():
    """Test market update handler."""
    state = EngineState()
    event = MarketUpdateEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.MARKET_UPDATE,
        currency_pair="EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    new_state, outputs = handle_market_update(state, event)

    # Check state updates
    rate = new_state.get_market_rate("EUR/USD")
    assert rate is not None
    assert rate.mid == Decimal("1.1000")
    assert new_state.event_count == 1

    # Check outputs
    assert len(outputs) == 1
    assert outputs[0].record_type == "market_update"


def test_handle_config_update():
    """Test config update handler."""
    state = EngineState()
    event = ConfigUpdateEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.CONFIG_UPDATE,
        config_key="reporting_currency",
        config_value="EUR",
    )

    new_state, outputs = handle_config_update(state, event)

    # Check state updates
    assert new_state.reporting_currency == "EUR"
    assert new_state.event_count == 1

    # Check outputs
    assert len(outputs) == 1
    assert outputs[0].record_type == "config_update"


def test_handle_hedge_order():
    """Test hedge order handler."""
    state = EngineState()
    event = HedgeOrderEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.HEDGE_ORDER,
        order_id="ORDER_001",
        currency_pair="EUR/USD",
        side=Side.SELL,
        notional=Decimal("500000"),
        limit_price=Decimal("1.0950"),
    )

    new_state, outputs = handle_hedge_order(state, event)

    # Check that state is only updated for event count (no cash/position changes)
    assert len(new_state.cash_balances) == 0
    assert len(new_state.positions) == 0
    assert new_state.event_count == 1

    # Check outputs
    assert len(outputs) == 1
    assert outputs[0].record_type == "hedge_order"
    assert outputs[0].data["order_id"] == "ORDER_001"


def test_handle_hedge_fill():
    """Test hedge fill handler."""
    state = EngineState()
    event = HedgeFillEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 1, tzinfo=timezone.utc),
        sequence_id=2,
        event_type=EventType.HEDGE_FILL,
        order_id="ORDER_001",
        currency_pair="EUR/USD",
        side=Side.SELL,
        notional=Decimal("500000"),
        fill_price=Decimal("1.0955"),
        slippage=Decimal("250"),
    )

    new_state, outputs = handle_hedge_fill(state, event)

    # Check state updates
    # Sell 500K EUR at 1.0955: +500K EUR, -547,750 USD, then -250 USD slippage
    assert new_state.get_cash_balance("EUR") == Decimal("500000")
    assert new_state.get_cash_balance("USD") == Decimal("-548000")
    assert new_state.get_position("EUR/USD") == Decimal("500000")

    # Check outputs
    assert len(outputs) == 1
    assert outputs[0].record_type == "hedge_fill"


def test_handle_clock_tick():
    """Test clock tick handler."""
    # Setup state with some positions and market data
    state = EngineState(reporting_currency="USD")
    state = state.update_cash("USD", Decimal("1000"))
    state = state.update_cash("EUR", Decimal("500"))
    state = state.update_position("EUR/USD", Decimal("500000"))
    state = state.update_market_rate(
        "EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    event = ClockTickEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.CLOCK_TICK,
        tick_label="EOD",
    )

    new_state, outputs = handle_clock_tick(state, event)

    # Check state (should be mostly unchanged)
    assert new_state.event_count == 1

    # Check outputs
    assert len(outputs) == 1
    assert outputs[0].record_type == "clock_tick"
    assert outputs[0].data["tick_label"] == "EOD"
    assert "cash_balances" in outputs[0].data
    assert "positions" in outputs[0].data
    assert "exposures" in outputs[0].data
    assert "total_equity_reporting" in outputs[0].data
