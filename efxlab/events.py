"""
Event schema definitions for the simulation engine.

All events are immutable and must be deterministically ordered.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class EventType(Enum):
    """Event type enumeration for dispatch."""

    CLIENT_TRADE = "client_trade"
    MARKET_UPDATE = "market_update"
    CONFIG_UPDATE = "config_update"
    HEDGE_ORDER = "hedge_order"
    HEDGE_FILL = "hedge_fill"
    CLOCK_TICK = "clock_tick"


class Side(Enum):
    """Trade side: BUY means base currency bought, sold quote currency."""

    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class BaseEvent:
    """
    Base event with fields required for deterministic ordering.

    Events are ordered by (timestamp, sequence_id). The sequence_id ensures
    stable ordering when multiple events share the same timestamp.
    """

    timestamp: datetime
    sequence_id: int
    event_type: EventType

    def __post_init__(self) -> None:
        if self.sequence_id < 0:
            raise ValueError(f"sequence_id must be non-negative, got {self.sequence_id}")

    def __lt__(self, other: Any) -> bool:
        """Compare events for sorting by timestamp and sequence_id."""
        if not isinstance(other, BaseEvent):
            return NotImplemented
        return (self.timestamp, self.sequence_id) < (other.timestamp, other.sequence_id)

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, BaseEvent):
            return NotImplemented
        return (self.timestamp, self.sequence_id) <= (other.timestamp, other.sequence_id)

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, BaseEvent):
            return NotImplemented
        return (self.timestamp, self.sequence_id) > (other.timestamp, other.sequence_id)

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, BaseEvent):
            return NotImplemented
        return (self.timestamp, self.sequence_id) >= (other.timestamp, other.sequence_id)


@dataclass(frozen=True)
class ClientTradeEvent(BaseEvent):
    """
    Client trade execution event.

    Represents a trade with a client. Updates cash and positions.

    Example: Client buys 1M EUR/USD at 1.1000
        - currency_pair: "EUR/USD"
        - side: BUY (desk sells EUR to client, receives USD)
        - notional: 1_000_000 (base currency amount)
        - price: 1.1000
        - Desk perspective: -1M EUR, +1.1M USD
    """

    currency_pair: str
    side: Side
    notional: Decimal  # Amount in base currency
    price: Decimal  # Quote currency per unit base
    client_id: str
    trade_id: str

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.notional <= 0:
            raise ValueError(f"notional must be positive, got {self.notional}")
        if self.price <= 0:
            raise ValueError(f"price must be positive, got {self.price}")
        if "/" not in self.currency_pair:
            raise ValueError(f"currency_pair must contain '/', got {self.currency_pair}")


@dataclass(frozen=True)
class MarketUpdateEvent(BaseEvent):
    """
    Market data update event.

    Updates bid/ask prices for a currency pair. Used for:
    - Mark-to-market position valuation
    - Currency conversion
    - Realistic hedge execution simulation
    """

    currency_pair: str
    bid: Decimal  # Price we can sell at
    ask: Decimal  # Price we can buy at
    mid: Decimal  # Mid price for reporting

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.bid <= 0 or self.ask <= 0 or self.mid <= 0:
            raise ValueError("All prices must be positive")
        if self.bid >= self.ask:
            raise ValueError(f"bid {self.bid} must be < ask {self.ask}")
        if not (self.bid <= self.mid <= self.ask):
            raise ValueError(f"mid {self.mid} must be between bid {self.bid} and ask {self.ask}")


@dataclass(frozen=True)
class ConfigUpdateEvent(BaseEvent):
    """
    Configuration change event.

    Updates simulation parameters dynamically (e.g., reporting currency,
    hedging thresholds). Allows testing different strategies on same data.
    """

    config_key: str
    config_value: Any

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.config_key:
            raise ValueError("config_key cannot be empty")


@dataclass(frozen=True)
class HedgeOrderEvent(BaseEvent):
    """
    Hedge order placement event.

    Intent to hedge exposure. Does not affect state until corresponding
    HedgeFillEvent is processed.
    """

    order_id: str
    currency_pair: str
    side: Side
    notional: Decimal
    limit_price: Decimal | None  # None for market orders

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.notional <= 0:
            raise ValueError(f"notional must be positive, got {self.notional}")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError(f"limit_price must be positive, got {self.limit_price}")


@dataclass(frozen=True)
class HedgeFillEvent(BaseEvent):
    """
    Hedge execution event.

    Confirms hedge order execution. Updates cash and positions like client trade,
    but may include slippage/fees for realism.
    """

    order_id: str
    currency_pair: str
    side: Side
    notional: Decimal
    fill_price: Decimal
    slippage: Decimal = Decimal("0")  # Slippage cost in quote ccy

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.notional <= 0:
            raise ValueError(f"notional must be positive, got {self.notional}")
        if self.fill_price <= 0:
            raise ValueError(f"fill_price must be positive, got {self.fill_price}")


@dataclass(frozen=True)
class ClockTickEvent(BaseEvent):
    """
    Periodic clock tick for snapshots and metric calculation.

    Triggers:
    - State snapshot for time-series output
    - P&L calculation
    - Risk metric updates
    - Exposure calculations
    """

    tick_label: str  # e.g., "EOD", "HOURLY", "T+5min"

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.tick_label:
            raise ValueError("tick_label cannot be empty")
