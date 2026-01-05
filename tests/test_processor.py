"""
Unit tests for event processor.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from efxlab.events import (
    ClientTradeEvent,
    ClockTickEvent,
    EventType,
    MarketUpdateEvent,
    Side,
)
from efxlab.processor import EventProcessor
from efxlab.state import EngineState


def test_processor_initialization():
    """Test processor initialization."""
    processor = EventProcessor()
    assert processor.state.event_count == 0
    assert len(processor.output_records) == 0

    # With initial state
    initial_state = EngineState(reporting_currency="EUR")
    processor = EventProcessor(initial_state)
    assert processor.state.reporting_currency == "EUR"


def test_process_single_event():
    """Test processing a single event."""
    processor = EventProcessor()

    event = MarketUpdateEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.MARKET_UPDATE,
        currency_pair="EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    processor.process_event(event)

    assert processor.state.event_count == 1
    assert len(processor.output_records) == 1
    assert processor.state.get_market_rate("EUR/USD") is not None


def test_process_multiple_events():
    """Test processing multiple events in sequence."""
    processor = EventProcessor()

    events = [
        MarketUpdateEvent(
            timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            sequence_id=1,
            event_type=EventType.MARKET_UPDATE,
            currency_pair="EUR/USD",
            bid=Decimal("1.0995"),
            ask=Decimal("1.1005"),
            mid=Decimal("1.1000"),
        ),
        ClientTradeEvent(
            timestamp=datetime(2025, 1, 1, 10, 0, 1, tzinfo=timezone.utc),
            sequence_id=2,
            event_type=EventType.CLIENT_TRADE,
            currency_pair="EUR/USD",
            side=Side.BUY,
            notional=Decimal("1000000"),
            price=Decimal("1.1000"),
            client_id="CLIENT_001",
            trade_id="TRADE_001",
        ),
        ClockTickEvent(
            timestamp=datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
            sequence_id=3,
            event_type=EventType.CLOCK_TICK,
            tick_label="T+1H",
        ),
    ]

    final_state = processor.process_events(events)

    assert final_state.event_count == 3
    assert len(processor.output_records) == 3
    assert final_state.get_position("EUR/USD") == Decimal("-1000000")


def test_deterministic_ordering():
    """Test that events are processed in deterministic order."""
    processor1 = EventProcessor()
    processor2 = EventProcessor()

    # Create events with same timestamps but different sequence IDs
    events = [
        ClientTradeEvent(
            timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            sequence_id=2,
            event_type=EventType.CLIENT_TRADE,
            currency_pair="EUR/USD",
            side=Side.BUY,
            notional=Decimal("1000000"),
            price=Decimal("1.1000"),
            client_id="CLIENT_001",
            trade_id="TRADE_002",
        ),
        ClientTradeEvent(
            timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            sequence_id=1,
            event_type=EventType.CLIENT_TRADE,
            currency_pair="EUR/USD",
            side=Side.SELL,
            notional=Decimal("500000"),
            price=Decimal("1.1000"),
            client_id="CLIENT_002",
            trade_id="TRADE_001",
        ),
    ]

    # Process in different orders
    processor1.process_events(events)
    processor2.process_events(sorted(events))  # Sort by timestamp, sequence_id

    # Results should be the same after sorting
    assert processor1.state.get_position("EUR/USD") == processor2.state.get_position("EUR/USD")
    assert processor1.state.get_cash_balance("EUR") == processor2.state.get_cash_balance("EUR")


def test_processor_state_isolation():
    """Test that processor state is properly isolated."""
    initial_state = EngineState()
    processor = EventProcessor(initial_state)

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

    processor.process_event(event)

    # Initial state should not be modified
    assert initial_state.event_count == 0
    assert len(initial_state.cash_balances) == 0

    # Processor state should be updated
    assert processor.state.event_count == 1
    assert processor.state.get_position("EUR/USD") == Decimal("-1000000")


def test_get_methods():
    """Test processor getter methods."""
    processor = EventProcessor()

    event = MarketUpdateEvent(
        timestamp=datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.MARKET_UPDATE,
        currency_pair="EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    processor.process_event(event)

    # Test get_state
    state = processor.get_state()
    assert state.event_count == 1

    # Test get_output_records
    records = processor.get_output_records()
    assert len(records) == 1
    assert records[0].record_type == "market_update"
