"""
Unit tests for event schemas.
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


def test_client_trade_event_creation():
    """Test valid client trade event creation."""
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
    assert event.notional == Decimal("1000000")
    assert event.price == Decimal("1.1000")
    assert event.side == Side.BUY


def test_client_trade_event_validation():
    """Test client trade event validation."""
    # Negative notional
    with pytest.raises(ValueError, match="notional must be positive"):
        ClientTradeEvent(
            timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            sequence_id=1,
            event_type=EventType.CLIENT_TRADE,
            currency_pair="EUR/USD",
            side=Side.BUY,
            notional=Decimal("-1000"),
            price=Decimal("1.1000"),
            client_id="CLIENT_001",
            trade_id="TRADE_001",
        )

    # Invalid currency pair
    with pytest.raises(ValueError, match="currency_pair must contain"):
        ClientTradeEvent(
            timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            sequence_id=1,
            event_type=EventType.CLIENT_TRADE,
            currency_pair="EURUSD",
            side=Side.BUY,
            notional=Decimal("1000"),
            price=Decimal("1.1000"),
            client_id="CLIENT_001",
            trade_id="TRADE_001",
        )


def test_market_update_event_validation():
    """Test market update event validation."""
    # Valid event
    event = MarketUpdateEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.MARKET_UPDATE,
        currency_pair="EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )
    assert event.bid < event.ask

    # Bid >= Ask
    with pytest.raises(ValueError, match="bid .* must be < ask"):
        MarketUpdateEvent(
            timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            sequence_id=1,
            event_type=EventType.MARKET_UPDATE,
            currency_pair="EUR/USD",
            bid=Decimal("1.1005"),
            ask=Decimal("1.0995"),
            mid=Decimal("1.1000"),
        )

    # Mid outside bid/ask
    with pytest.raises(ValueError, match="mid .* must be between"):
        MarketUpdateEvent(
            timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            sequence_id=1,
            event_type=EventType.MARKET_UPDATE,
            currency_pair="EUR/USD",
            bid=Decimal("1.0995"),
            ask=Decimal("1.1005"),
            mid=Decimal("1.2000"),
        )


def test_event_ordering():
    """Test deterministic event ordering."""
    event1 = ClockTickEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.CLOCK_TICK,
        tick_label="T1",
    )
    event2 = ClockTickEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        sequence_id=2,
        event_type=EventType.CLOCK_TICK,
        tick_label="T2",
    )
    event3 = ClockTickEvent(
        timestamp=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.CLOCK_TICK,
        tick_label="T3",
    )

    events = [event3, event1, event2]
    events.sort()

    assert events[0] == event1
    assert events[1] == event2
    assert events[2] == event3


def test_config_update_event():
    """Test config update event."""
    event = ConfigUpdateEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.CONFIG_UPDATE,
        config_key="reporting_currency",
        config_value="EUR",
    )
    assert event.config_key == "reporting_currency"
    assert event.config_value == "EUR"


def test_hedge_order_and_fill():
    """Test hedge order and fill events."""
    order = HedgeOrderEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.HEDGE_ORDER,
        order_id="ORDER_001",
        currency_pair="EUR/USD",
        side=Side.SELL,
        notional=Decimal("500000"),
        limit_price=Decimal("1.0950"),
    )
    assert order.order_id == "ORDER_001"
    assert order.limit_price == Decimal("1.0950")

    fill = HedgeFillEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 1, tzinfo=timezone.utc),
        sequence_id=2,
        event_type=EventType.HEDGE_FILL,
        order_id="ORDER_001",
        currency_pair="EUR/USD",
        side=Side.SELL,
        notional=Decimal("500000"),
        fill_price=Decimal("1.0955"),
        slippage=Decimal("250"),  # 5 pips * 500k = $250
    )
    assert fill.order_id == order.order_id
    assert fill.slippage == Decimal("250")
