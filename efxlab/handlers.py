"""
Event handlers - pure functions that transform state.

Each handler takes (State, Event) and returns (State, OutputRecords).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

from efxlab.converter import CurrencyConverter
from efxlab.events import (
    ClientTradeEvent,
    ClockTickEvent,
    ConfigUpdateEvent,
    HedgeFillEvent,
    HedgeOrderEvent,
    MarketUpdateEvent,
    Side,
)
from efxlab.state import EngineState, apply_trade


@dataclass
class OutputRecord:
    """Generic output record for logging."""

    timestamp: datetime
    record_type: str
    data: Dict[str, Any]


def handle_client_trade(
    state: EngineState, event: ClientTradeEvent
) -> tuple[EngineState, List[OutputRecord]]:
    """
    Handle client trade event.

    Updates:
    - Cash balances (desk perspective)
    - Positions

    Outputs:
    - Trade log record
    """
    # Apply trade
    new_state = apply_trade(
        state,
        event.currency_pair,
        event.side,
        event.notional,
        event.price,
    )
    new_state = new_state.increment_event_count(event.timestamp.isoformat())

    # Create output record
    base_ccy, quote_ccy = event.currency_pair.split("/")
    quote_amount = event.notional * event.price

    output = OutputRecord(
        timestamp=event.timestamp,
        record_type="client_trade",
        data={
            "trade_id": event.trade_id,
            "client_id": event.client_id,
            "currency_pair": event.currency_pair,
            "side": event.side.value,
            "notional": str(event.notional),
            "price": str(event.price),
            "quote_amount": str(quote_amount),
            "base_currency": base_ccy,
            "quote_currency": quote_ccy,
        },
    )

    return new_state, [output]


def handle_market_update(
    state: EngineState, event: MarketUpdateEvent
) -> tuple[EngineState, List[OutputRecord]]:
    """
    Handle market update event.

    Updates:
    - Market rate cache

    Outputs:
    - Market data record (optional, can be verbose)
    """
    new_state = state.update_market_rate(
        event.currency_pair,
        event.bid,
        event.ask,
        event.mid,
    )
    new_state = new_state.increment_event_count(event.timestamp.isoformat())

    # Optionally log market updates (can be very verbose)
    output = OutputRecord(
        timestamp=event.timestamp,
        record_type="market_update",
        data={
            "currency_pair": event.currency_pair,
            "bid": str(event.bid),
            "ask": str(event.ask),
            "mid": str(event.mid),
        },
    )

    return new_state, [output]


def handle_config_update(
    state: EngineState, event: ConfigUpdateEvent
) -> tuple[EngineState, List[OutputRecord]]:
    """
    Handle configuration update event.

    Updates:
    - Configuration parameters

    Outputs:
    - Config change record
    """
    new_state = state.update_config(event.config_key, str(event.config_value))
    new_state = new_state.increment_event_count(event.timestamp.isoformat())

    output = OutputRecord(
        timestamp=event.timestamp,
        record_type="config_update",
        data={
            "config_key": event.config_key,
            "config_value": str(event.config_value),
        },
    )

    return new_state, [output]


def handle_hedge_order(
    state: EngineState, event: HedgeOrderEvent
) -> tuple[EngineState, List[OutputRecord]]:
    """
    Handle hedge order event.

    Note: Order placement does not affect state (no fill yet).

    Updates:
    - None (order intent only)

    Outputs:
    - Order log record
    """
    new_state = state.increment_event_count(event.timestamp.isoformat())

    output = OutputRecord(
        timestamp=event.timestamp,
        record_type="hedge_order",
        data={
            "order_id": event.order_id,
            "currency_pair": event.currency_pair,
            "side": event.side.value,
            "notional": str(event.notional),
            "limit_price": str(event.limit_price) if event.limit_price else None,
        },
    )

    return new_state, [output]


def handle_hedge_fill(
    state: EngineState, event: HedgeFillEvent
) -> tuple[EngineState, List[OutputRecord]]:
    """
    Handle hedge fill event.

    Updates:
    - Cash balances
    - Positions

    Outputs:
    - Fill log record
    """
    # Apply hedge trade (same as client trade from desk perspective)
    new_state = apply_trade(
        state,
        event.currency_pair,
        event.side,
        event.notional,
        event.fill_price,
    )

    # Apply slippage cost (reduce quote currency cash)
    if event.slippage != 0:
        _, quote_ccy = event.currency_pair.split("/")
        new_state = new_state.update_cash(quote_ccy, -event.slippage)

    new_state = new_state.increment_event_count(event.timestamp.isoformat())

    output = OutputRecord(
        timestamp=event.timestamp,
        record_type="hedge_fill",
        data={
            "order_id": event.order_id,
            "currency_pair": event.currency_pair,
            "side": event.side.value,
            "notional": str(event.notional),
            "fill_price": str(event.fill_price),
            "slippage": str(event.slippage),
        },
    )

    return new_state, [output]


def handle_clock_tick(
    state: EngineState, event: ClockTickEvent
) -> tuple[EngineState, List[OutputRecord]]:
    """
    Handle clock tick event.

    Triggers:
    - State snapshot
    - P&L calculation
    - Exposure calculation
    - Risk metrics

    Updates:
    - None (read-only snapshot)

    Outputs:
    - Snapshot record with all state and metrics
    """
    new_state = state.increment_event_count(event.timestamp.isoformat())

    # Compute metrics
    exposures = state.compute_exposures()

    # Calculate total equity in reporting currency
    converter = CurrencyConverter(state)
    total_equity = Decimal("0")

    # Sum all cash balances converted to reporting currency
    for currency, balance in state.cash_balances.items():
        try:
            converted = converter.convert_to_reporting(balance, currency)
            total_equity += converted
        except Exception:
            # If conversion fails, skip (or handle differently)
            pass

    output = OutputRecord(
        timestamp=event.timestamp,
        record_type="clock_tick",
        data={
            "tick_label": event.tick_label,
            "cash_balances": {k: str(v) for k, v in state.cash_balances.items()},
            "positions": {k: str(v) for k, v in state.positions.items()},
            "exposures": {k: str(v) for k, v in exposures.items()},
            "total_equity_reporting": str(total_equity),
            "reporting_currency": state.reporting_currency,
            "event_count": state.event_count,
        },
    )

    return new_state, [output]
