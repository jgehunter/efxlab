"""
State model for the simulation engine.

Maintains all simulation state with proper accounting primitives.
"""

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Dict

from efxlab.events import Side


@dataclass(frozen=True)
class MarketRate:
    """Market rates for a currency pair."""

    bid: Decimal
    ask: Decimal
    mid: Decimal


@dataclass(frozen=True)
class EngineState:
    """
    Complete simulation state.
    
    Immutable state object ensures determinism and enables time-travel debugging.
    All financial values use Decimal for exact arithmetic.
    
    Cash balances: {currency: amount}
        - Positive: we have that currency
        - Negative: we owe that currency (credit facility)
    
    Positions: {currency_pair: signed_notional}
        - Positive: long base currency (bought base, sold quote)
        - Negative: short base currency (sold base, bought quote)
        - Uses base currency notional amount
    
    Exposures: computed on-demand from positions
    
    Market cache: latest rates for each pair (for conversions and P&L)
    """

    # Core accounting state
    cash_balances: Dict[str, Decimal] = field(default_factory=dict)
    positions: Dict[str, Decimal] = field(default_factory=dict)

    # Market data cache
    market_rates: Dict[str, MarketRate] = field(default_factory=dict)

    # Configuration
    reporting_currency: str = "USD"

    # Event tracking
    last_timestamp: str = ""
    event_count: int = 0

    def get_cash_balance(self, currency: str) -> Decimal:
        """Get cash balance for a currency, defaulting to zero."""
        return self.cash_balances.get(currency, Decimal("0"))

    def get_position(self, currency_pair: str) -> Decimal:
        """Get position for a currency pair, defaulting to zero."""
        return self.positions.get(currency_pair, Decimal("0"))

    def get_market_rate(self, currency_pair: str) -> MarketRate | None:
        """Get market rate for a currency pair."""
        return self.market_rates.get(currency_pair)

    def update_cash(self, currency: str, delta: Decimal) -> "EngineState":
        """Return new state with updated cash balance."""
        new_balances = dict(self.cash_balances)
        new_balances[currency] = self.get_cash_balance(currency) + delta
        return replace(self, cash_balances=new_balances)

    def update_position(self, currency_pair: str, delta: Decimal) -> "EngineState":
        """Return new state with updated position."""
        new_positions = dict(self.positions)
        new_positions[currency_pair] = self.get_position(currency_pair) + delta
        return replace(self, positions=new_positions)

    def update_market_rate(
        self, currency_pair: str, bid: Decimal, ask: Decimal, mid: Decimal
    ) -> "EngineState":
        """Return new state with updated market rate."""
        new_rates = dict(self.market_rates)
        new_rates[currency_pair] = MarketRate(bid=bid, ask=ask, mid=mid)
        return replace(self, market_rates=new_rates)

    def update_config(self, key: str, value: str) -> "EngineState":
        """Return new state with updated configuration."""
        if key == "reporting_currency":
            return replace(self, reporting_currency=value)
        # Add more config options as needed
        return self

    def increment_event_count(self, timestamp: str) -> "EngineState":
        """Return new state with incremented event count."""
        return replace(
            self, event_count=self.event_count + 1, last_timestamp=timestamp
        )

    def compute_exposures(self) -> Dict[str, Decimal]:
        """
        Compute net exposure by currency from positions.
        
        For each position in a currency pair (e.g., EUR/USD):
        - Positive position = long base (EUR), short quote (USD)
        - Negative position = short base (EUR), long quote (USD)
        
        Returns: {currency: net_exposure_amount}
        """
        exposures: Dict[str, Decimal] = {}

        for pair, position_notional in self.positions.items():
            if position_notional == 0:
                continue

            # Parse currency pair (e.g., "EUR/USD" -> base="EUR", quote="USD")
            parts = pair.split("/")
            if len(parts) != 2:
                continue  # Skip malformed pairs
            base_ccy, quote_ccy = parts

            # Add base currency exposure
            exposures[base_ccy] = exposures.get(base_ccy, Decimal("0")) + position_notional

            # Add quote currency exposure (opposite sign)
            # If position is +1M EUR/USD, we're +1M EUR and need quote equivalent
            # This is simplified; proper implementation would use current market rate
            # For now, just track that we have opposite quote exposure
            rate = self.get_market_rate(pair)
            if rate:
                quote_exposure = -position_notional * rate.mid
                exposures[quote_ccy] = exposures.get(quote_ccy, Decimal("0")) + quote_exposure

        return exposures

    def to_dict(self) -> Dict:
        """Convert state to dictionary for serialization."""
        return {
            "cash_balances": {k: str(v) for k, v in self.cash_balances.items()},
            "positions": {k: str(v) for k, v in self.positions.items()},
            "exposures": {k: str(v) for k, v in self.compute_exposures().items()},
            "market_rates": {
                k: {"bid": str(v.bid), "ask": str(v.ask), "mid": str(v.mid)}
                for k, v in self.market_rates.items()
            },
            "reporting_currency": self.reporting_currency,
            "last_timestamp": self.last_timestamp,
            "event_count": self.event_count,
        }


def apply_trade(
    state: EngineState,
    currency_pair: str,
    side: Side,
    notional: Decimal,
    price: Decimal,
) -> EngineState:
    """
    Apply a trade to state (client or hedge).
    
    Desk perspective:
    - Client BUY: desk sells base, receives quote (negative base, positive quote)
    - Client SELL: desk buys base, pays quote (positive base, negative quote)
    
    Args:
        state: Current state
        currency_pair: e.g., "EUR/USD"
        side: BUY or SELL (client side)
        notional: Amount in base currency
        price: Quote per unit base
    
    Returns:
        New state with updated cash and positions
    """
    base_ccy, quote_ccy = currency_pair.split("/")
    quote_amount = notional * price

    if side == Side.BUY:
        # Client buys base from desk: desk loses base, gains quote
        state = state.update_cash(base_ccy, -notional)
        state = state.update_cash(quote_ccy, quote_amount)
        state = state.update_position(currency_pair, -notional)
    else:  # Side.SELL
        # Client sells base to desk: desk gains base, loses quote
        state = state.update_cash(base_ccy, notional)
        state = state.update_cash(quote_ccy, -quote_amount)
        state = state.update_position(currency_pair, notional)

    return state
