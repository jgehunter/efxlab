"""
Integration test for the complete simulation engine.

Tests end-to-end flow with realistic scenario.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

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


def test_complete_simulation_scenario():
    """
    Test a complete day of FX trading simulation.

    Scenario:
    1. Market opens with initial rates
    2. Multiple client trades throughout the day
    3. Market rates update
    4. Clock ticks for periodic snapshots
    5. Verify final state is consistent and deterministic
    """
    # Setup
    base_time = datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    events = []
    seq_id = 0

    # Initial market rates
    events.append(
        MarketUpdateEvent(
            timestamp=base_time,
            sequence_id=seq_id,
            event_type=EventType.MARKET_UPDATE,
            currency_pair="EUR/USD",
            bid=Decimal("1.0995"),
            ask=Decimal("1.1005"),
            mid=Decimal("1.1000"),
        )
    )
    seq_id += 1

    events.append(
        MarketUpdateEvent(
            timestamp=base_time,
            sequence_id=seq_id,
            event_type=EventType.MARKET_UPDATE,
            currency_pair="GBP/USD",
            bid=Decimal("1.2695"),
            ask=Decimal("1.2705"),
            mid=Decimal("1.2700"),
        )
    )
    seq_id += 1

    # Client trade 1: Buy EUR/USD
    events.append(
        ClientTradeEvent(
            timestamp=base_time + timedelta(minutes=10),
            sequence_id=seq_id,
            event_type=EventType.CLIENT_TRADE,
            currency_pair="EUR/USD",
            side=Side.BUY,
            notional=Decimal("1000000"),
            price=Decimal("1.1000"),
            client_id="CLIENT_001",
            trade_id="TRADE_001",
        )
    )
    seq_id += 1

    # Market moves
    events.append(
        MarketUpdateEvent(
            timestamp=base_time + timedelta(minutes=30),
            sequence_id=seq_id,
            event_type=EventType.MARKET_UPDATE,
            currency_pair="EUR/USD",
            bid=Decimal("1.1045"),
            ask=Decimal("1.1055"),
            mid=Decimal("1.1050"),
        )
    )
    seq_id += 1

    # Client trade 2: Sell EUR/USD (partial unwind)
    events.append(
        ClientTradeEvent(
            timestamp=base_time + timedelta(minutes=45),
            sequence_id=seq_id,
            event_type=EventType.CLIENT_TRADE,
            currency_pair="EUR/USD",
            side=Side.SELL,
            notional=Decimal("500000"),
            price=Decimal("1.1050"),
            client_id="CLIENT_002",
            trade_id="TRADE_002",
        )
    )
    seq_id += 1

    # Client trade 3: Buy GBP/USD
    events.append(
        ClientTradeEvent(
            timestamp=base_time + timedelta(hours=1),
            sequence_id=seq_id,
            event_type=EventType.CLIENT_TRADE,
            currency_pair="GBP/USD",
            side=Side.BUY,
            notional=Decimal("750000"),
            price=Decimal("1.2700"),
            client_id="CLIENT_003",
            trade_id="TRADE_003",
        )
    )
    seq_id += 1

    # Clock tick for snapshot
    events.append(
        ClockTickEvent(
            timestamp=base_time + timedelta(hours=2),
            sequence_id=seq_id,
            event_type=EventType.CLOCK_TICK,
            tick_label="T+2H",
        )
    )
    seq_id += 1

    # Process all events
    processor = EventProcessor(EngineState(reporting_currency="USD"))
    final_state = processor.process_events(events)

    # Verify final state
    assert final_state.event_count == len(events)

    # Check positions
    # EUR/USD: -1M (client buy) + 500K (client sell) = -500K
    assert final_state.get_position("EUR/USD") == Decimal("-500000")

    # GBP/USD: -750K (client buy)
    assert final_state.get_position("GBP/USD") == Decimal("-750000")

    # Check cash balances
    # EUR: -1M + 500K = -500K
    assert final_state.get_cash_balance("EUR") == Decimal("-500000")

    # USD: +1.1M (trade1) - 552.5K (trade2) + 952.5K (trade3)
    expected_usd = Decimal("1100000") - Decimal("552500") + Decimal("952500")
    assert final_state.get_cash_balance("USD") == expected_usd

    # GBP: -750K
    assert final_state.get_cash_balance("GBP") == Decimal("-750000")

    # Check output records
    records = processor.get_output_records()
    assert len(records) == len(events)

    # Verify we have expected record types
    record_types = [r.record_type for r in records]
    assert record_types.count("market_update") == 3
    assert record_types.count("client_trade") == 3
    assert record_types.count("clock_tick") == 1

    # Verify market rates are cached
    assert final_state.get_market_rate("EUR/USD") is not None
    assert final_state.get_market_rate("GBP/USD") is not None


def test_deterministic_rerun():
    """
    Test that running the same events twice produces identical results.

    This is critical for reproducibility.
    """
    base_time = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    events = [
        MarketUpdateEvent(
            timestamp=base_time,
            sequence_id=1,
            event_type=EventType.MARKET_UPDATE,
            currency_pair="EUR/USD",
            bid=Decimal("1.0995"),
            ask=Decimal("1.1005"),
            mid=Decimal("1.1000"),
        ),
        ClientTradeEvent(
            timestamp=base_time + timedelta(seconds=1),
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
            timestamp=base_time + timedelta(seconds=2),
            sequence_id=3,
            event_type=EventType.CLOCK_TICK,
            tick_label="EOD",
        ),
    ]

    # Run 1
    processor1 = EventProcessor(EngineState(reporting_currency="USD"))
    state1 = processor1.process_events(events)

    # Run 2
    processor2 = EventProcessor(EngineState(reporting_currency="USD"))
    state2 = processor2.process_events(events)

    # Compare states
    assert state1.event_count == state2.event_count
    assert state1.cash_balances == state2.cash_balances
    assert state1.positions == state2.positions
    assert state1.reporting_currency == state2.reporting_currency

    # Compare outputs (should be byte-identical)
    records1 = processor1.get_output_records()
    records2 = processor2.get_output_records()
    assert len(records1) == len(records2)

    for r1, r2 in zip(records1, records2):
        assert r1.timestamp == r2.timestamp
        assert r1.record_type == r2.record_type
        assert r1.data == r2.data


def test_exposure_calculation_integration():
    """Test exposure calculation in realistic scenario."""
    base_time = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    events = [
        # Set up market rates
        MarketUpdateEvent(
            timestamp=base_time,
            sequence_id=1,
            event_type=EventType.MARKET_UPDATE,
            currency_pair="EUR/USD",
            bid=Decimal("1.0995"),
            ask=Decimal("1.1005"),
            mid=Decimal("1.1000"),
        ),
        # Trade creates EUR/USD position
        ClientTradeEvent(
            timestamp=base_time + timedelta(seconds=1),
            sequence_id=2,
            event_type=EventType.CLIENT_TRADE,
            currency_pair="EUR/USD",
            side=Side.BUY,
            notional=Decimal("1000000"),
            price=Decimal("1.1000"),
            client_id="CLIENT_001",
            trade_id="TRADE_001",
        ),
        # Clock tick to calculate exposures
        ClockTickEvent(
            timestamp=base_time + timedelta(seconds=2),
            sequence_id=3,
            event_type=EventType.CLOCK_TICK,
            tick_label="SNAPSHOT",
        ),
    ]

    processor = EventProcessor(EngineState(reporting_currency="USD"))
    final_state = processor.process_events(events)

    # Compute exposures
    exposures = final_state.compute_exposures()

    # Desk sold 1M EUR to client, so desk is short 1M EUR
    assert exposures["EUR"] == Decimal("-1000000")

    # Desk received 1.1M USD, so desk is long 1.1M USD (from position perspective)
    assert exposures["USD"] == Decimal("1100000")

    # Verify clock tick output includes exposures
    records = processor.get_output_records()
    tick_record = [r for r in records if r.record_type == "clock_tick"][0]
    assert "exposures" in tick_record.data
    assert tick_record.data["exposures"]["EUR"] == "-1000000"
