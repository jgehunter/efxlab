"""
Integration tests for lot tracking system with full event processing.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from efxlab.events import ClientTradeEvent, EventType, MarketUpdateEvent, Side
from efxlab.lot_manager import LotConfig, LotManager
from efxlab.processor import EventProcessor
from efxlab.state import EngineState


def test_lot_tracking_with_direct_pair():
    """Test lot tracking with direct pair trade (no decomposition)."""
    # Setup lot manager
    lot_config = LotConfig(
        enabled=True,
        matching_rule="FIFO",
        risk_pairs=["EUR/USD"],
        trade_pairs=["EUR/USD"],
        reporting_currency="USD",
    )
    lot_manager = LotManager(lot_config)

    # Initialize state with lot tracking
    initial_state = EngineState(
        reporting_currency="USD",
        lot_manager=lot_manager,
    )

    # Create processor
    processor = EventProcessor(initial_state)

    # Add market rate first
    market_update = MarketUpdateEvent(
        timestamp=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.MARKET_UPDATE,
        currency_pair="EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    # Client BUY EUR/USD (desk SELLS)
    trade1 = ClientTradeEvent(
        timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        sequence_id=2,
        event_type=EventType.CLIENT_TRADE,
        trade_id="T001",
        client_id="CLIENT1",
        currency_pair="EUR/USD",
        side=Side.BUY,
        notional=Decimal("100000"),
        price=Decimal("1.1000"),
    )

    # Process events
    events = [market_update, trade1]
    final_state = processor.process_events(events)

    # Verify lot was created
    assert final_state.lot_manager is not None
    assert final_state.lot_manager.get_net_position("EUR/USD") == Decimal("-100000")

    # Verify output records
    outputs = processor.get_output_records()
    lot_created_records = [o for o in outputs if o.record_type == "lot_created"]
    assert len(lot_created_records) == 1
    assert lot_created_records[0].data["risk_pair"] == "EUR/USD"
    assert lot_created_records[0].data["side"] == "SELL"  # Desk side


def test_lot_tracking_with_cross_pair():
    """Test lot tracking with cross pair decomposition."""
    # Setup lot manager
    lot_config = LotConfig(
        enabled=True,
        matching_rule="FIFO",
        risk_pairs=["EUR/USD", "GBP/USD"],
        trade_pairs=["EUR/USD", "GBP/USD", "EUR/GBP"],
        reporting_currency="USD",
    )
    lot_manager = LotManager(lot_config)

    initial_state = EngineState(
        reporting_currency="USD",
        lot_manager=lot_manager,
    )

    processor = EventProcessor(initial_state)

    # Add market rates
    eur_market = MarketUpdateEvent(
        timestamp=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.MARKET_UPDATE,
        currency_pair="EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    gbp_market = MarketUpdateEvent(
        timestamp=datetime(2024, 1, 1, 9, 1, tzinfo=timezone.utc),
        sequence_id=2,
        event_type=EventType.MARKET_UPDATE,
        currency_pair="GBP/USD",
        bid=Decimal("1.2936"),
        ask=Decimal("1.2946"),
        mid=Decimal("1.2941"),
    )

    # Client BUY EUR/GBP (cross trade)
    cross_trade = ClientTradeEvent(
        timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        sequence_id=3,
        event_type=EventType.CLIENT_TRADE,
        trade_id="T001",
        client_id="CLIENT1",
        currency_pair="EUR/GBP",
        side=Side.BUY,
        notional=Decimal("100000"),
        price=Decimal("0.8500"),
    )

    # Process events
    events = [eur_market, gbp_market, cross_trade]
    final_state = processor.process_events(events)

    # Verify lots created for both risk pairs
    assert final_state.lot_manager is not None
    assert final_state.lot_manager.get_net_position("EUR/USD") == Decimal("-100000")
    assert final_state.lot_manager.get_net_position("GBP/USD") == Decimal("85000")

    # Verify output records
    outputs = processor.get_output_records()
    lot_created_records = [o for o in outputs if o.record_type == "lot_created"]
    assert len(lot_created_records) == 2  # Two legs


def test_lot_matching_internalization():
    """Test lot matching when trades internalize."""
    lot_config = LotConfig(
        enabled=True,
        matching_rule="FIFO",
        risk_pairs=["EUR/USD"],
        trade_pairs=["EUR/USD"],
        reporting_currency="USD",
    )
    lot_manager = LotManager(lot_config)

    initial_state = EngineState(
        reporting_currency="USD",
        lot_manager=lot_manager,
    )

    processor = EventProcessor(initial_state)

    # Market rate
    market = MarketUpdateEvent(
        timestamp=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.MARKET_UPDATE,
        currency_pair="EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    # Trade 1: Client BUY (desk SELL)
    trade1 = ClientTradeEvent(
        timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        sequence_id=2,
        event_type=EventType.CLIENT_TRADE,
        trade_id="T001",
        client_id="CLIENT1",
        currency_pair="EUR/USD",
        side=Side.BUY,
        notional=Decimal("100000"),
        price=Decimal("1.1000"),
    )

    # Update market (price moved up)
    market2 = MarketUpdateEvent(
        timestamp=datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
        sequence_id=3,
        event_type=EventType.MARKET_UPDATE,
        currency_pair="EUR/USD",
        bid=Decimal("1.1495"),
        ask=Decimal("1.1505"),
        mid=Decimal("1.1500"),
    )

    # Trade 2: Client SELL (desk BUY) - should match against lot from trade1
    trade2 = ClientTradeEvent(
        timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
        sequence_id=4,
        event_type=EventType.CLIENT_TRADE,
        trade_id="T002",
        client_id="CLIENT2",
        currency_pair="EUR/USD",
        side=Side.SELL,
        notional=Decimal("100000"),
        price=Decimal("1.1500"),
    )

    # Process events
    events = [market, trade1, market2, trade2]
    final_state = processor.process_events(events)

    # Verify position is flat after internalization
    assert final_state.lot_manager is not None
    assert final_state.lot_manager.get_net_position("EUR/USD") == Decimal("0")

    # Verify lot was matched
    outputs = processor.get_output_records()
    lot_match_records = [o for o in outputs if o.record_type == "lot_match"]
    assert len(lot_match_records) == 1

    # Verify P&L from match
    match_record = lot_match_records[0]
    realized_pnl = Decimal(match_record.data["realized_pnl"])
    # Desk sold at 1.1000, bought back at 1.1500 -> loss of 5000
    assert realized_pnl == Decimal("-5000")


def test_partial_lot_matching():
    """Test partial lot matching."""
    lot_config = LotConfig(
        enabled=True,
        matching_rule="FIFO",
        risk_pairs=["EUR/USD"],
        trade_pairs=["EUR/USD"],
        reporting_currency="USD",
    )
    lot_manager = LotManager(lot_config)

    initial_state = EngineState(
        reporting_currency="USD",
        lot_manager=lot_manager,
    )

    processor = EventProcessor(initial_state)

    # Market rate
    market = MarketUpdateEvent(
        timestamp=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.MARKET_UPDATE,
        currency_pair="EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    # Trade 1: Client BUY 100k (desk SELL)
    trade1 = ClientTradeEvent(
        timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        sequence_id=2,
        event_type=EventType.CLIENT_TRADE,
        trade_id="T001",
        client_id="CLIENT1",
        currency_pair="EUR/USD",
        side=Side.BUY,
        notional=Decimal("100000"),
        price=Decimal("1.1000"),
    )

    # Trade 2: Client SELL 60k (partial match)
    trade2 = ClientTradeEvent(
        timestamp=datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
        sequence_id=3,
        event_type=EventType.CLIENT_TRADE,
        trade_id="T002",
        client_id="CLIENT2",
        currency_pair="EUR/USD",
        side=Side.SELL,
        notional=Decimal("60000"),
        price=Decimal("1.1500"),
    )

    # Process events
    events = [market, trade1, trade2]
    final_state = processor.process_events(events)

    # Verify partial match left 40k open
    assert final_state.lot_manager is not None
    assert final_state.lot_manager.get_net_position("EUR/USD") == Decimal("-40000")

    # Verify we have a match with remaining open lot (no fully closed lots in partial match)
    stats = final_state.lot_manager.get_lot_count_stats()
    assert stats["total_open_lots"] == 1  # One partial lot remains
    assert stats["total_closed_lots"] == 0  # No lots fully closed in partial match


def test_lot_tracking_disabled():
    """Test that simulation works correctly with lot tracking disabled."""
    # No lot manager
    initial_state = EngineState(reporting_currency="USD", lot_manager=None)

    processor = EventProcessor(initial_state)

    # Market rate
    market = MarketUpdateEvent(
        timestamp=datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc),
        sequence_id=1,
        event_type=EventType.MARKET_UPDATE,
        currency_pair="EUR/USD",
        bid=Decimal("1.0995"),
        ask=Decimal("1.1005"),
        mid=Decimal("1.1000"),
    )

    # Trade
    trade = ClientTradeEvent(
        timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
        sequence_id=2,
        event_type=EventType.CLIENT_TRADE,
        trade_id="T001",
        client_id="CLIENT1",
        currency_pair="EUR/USD",
        side=Side.BUY,
        notional=Decimal("100000"),
        price=Decimal("1.1000"),
    )

    # Process events
    events = [market, trade]
    final_state = processor.process_events(events)

    # Verify no lot tracking
    assert final_state.lot_manager is None

    # Verify no lot records
    outputs = processor.get_output_records()
    lot_records = [o for o in outputs if o.record_type.startswith("lot_")]
    assert len(lot_records) == 0

    # Verify regular accounting still works
    assert final_state.get_position("EUR/USD") == Decimal("-100000")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
