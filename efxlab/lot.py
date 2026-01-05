"""
Lot tracking for position management with FIFO matching.

Lots represent individual position entries that can be matched for internalization.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import List

from efxlab.events import Side


@dataclass(frozen=True)
class Lot:
    """
    A lot represents a single position entry in a risk pair.

    Lots are immutable. When partially matched, a new lot with reduced
    quantity is created.

    Attributes:
        lot_id: Unique identifier
        risk_pair: Direct currency pair (e.g., "EUR/USD")
        side: BUY or SELL from desk perspective
        quantity: Current remaining quantity
        original_quantity: Initial quantity
        trade_price: Price at which lot was opened
        open_timestamp: When lot was created
        originating_trade_id: Source trade ID
        decomposition_path: "DIRECT" or "EUR/GBP->EUR/USD"
        open_mid: Market mid at lot open
        close_timestamp: When fully matched (None if open)
        close_mid: Market mid at close (None if open)
    """

    lot_id: str
    risk_pair: str
    side: Side
    quantity: Decimal  # Remaining quantity
    original_quantity: Decimal
    trade_price: Decimal
    open_timestamp: datetime
    originating_trade_id: str
    decomposition_path: str
    open_mid: Decimal
    close_timestamp: datetime | None = None
    close_mid: Decimal | None = None

    def __post_init__(self) -> None:
        # Allow zero quantity only for closed lots
        if self.quantity < 0:
            raise ValueError(f"Lot quantity cannot be negative, got {self.quantity}")
        if self.quantity == 0 and self.close_timestamp is None:
            raise ValueError("Open lot cannot have zero quantity")
        if self.original_quantity <= 0:
            raise ValueError(f"Original quantity must be positive, got {self.original_quantity}")
        if self.quantity > self.original_quantity:
            raise ValueError(
                f"Quantity {self.quantity} cannot exceed original {self.original_quantity}"
            )

    @property
    def is_closed(self) -> bool:
        """Check if lot is fully closed."""
        return self.close_timestamp is not None

    @property
    def is_buy(self) -> bool:
        """Check if lot is a buy (desk bought base currency)."""
        return self.side == Side.BUY

    @property
    def is_sell(self) -> bool:
        """Check if lot is a sell (desk sold base currency)."""
        return self.side == Side.SELL

    def reduce_quantity(self, amount: Decimal) -> "Lot":
        """Return new lot with reduced quantity."""
        if amount <= 0:
            raise ValueError(f"Reduction amount must be positive, got {amount}")
        if amount > self.quantity:
            raise ValueError(f"Cannot reduce by {amount}, only {self.quantity} remaining")

        new_quantity = self.quantity - amount
        return replace(self, quantity=new_quantity)

    def close(self, close_timestamp: datetime, close_mid: Decimal) -> "Lot":
        """Return new closed lot. Quantity should be zero."""
        return replace(self, close_timestamp=close_timestamp, close_mid=close_mid)

    def compute_unrealized_pnl(self, current_mid: Decimal) -> Decimal:
        """
        Compute unrealized P&L for open lot.

        P&L = (current_mid - trade_price) * quantity * direction
        Direction: +1 for BUY, -1 for SELL
        """
        if self.is_closed:
            return Decimal("0")

        direction = Decimal("1") if self.is_buy else Decimal("-1")
        return (current_mid - self.trade_price) * self.quantity * direction

    def get_unrealized_pnl(self, current_mid: Decimal) -> Decimal:
        """Alias for compute_unrealized_pnl() for convenience."""
        return self.compute_unrealized_pnl(current_mid)

    def compute_realized_pnl(self, quantity_closed: Decimal, close_price: Decimal) -> Decimal:
        """
        Compute realized P&L for closed quantity.

        P&L = (close_price - open_price) * quantity * direction
        """
        if quantity_closed <= 0 or quantity_closed > self.original_quantity:
            raise ValueError(f"Invalid close quantity: {quantity_closed}")

        direction = Decimal("1") if self.is_buy else Decimal("-1")
        return (close_price - self.trade_price) * quantity_closed * direction


@dataclass
class LotMatch:
    """
    Result of matching a lot against an offsetting trade.

    Attributes:
        lot: The original lot being matched
        matched_quantity: How much of the lot was matched
        remaining_lot: Updated lot with reduced quantity (None if fully matched)
        realized_pnl: P&L from this match
        close_price: Price at which match occurred
        close_timestamp: When match occurred
    """

    lot: Lot
    matched_quantity: Decimal
    remaining_lot: Lot | None
    realized_pnl: Decimal
    close_price: Decimal
    close_timestamp: datetime


class LotQueue:
    """
    FIFO queue of lots for a single risk pair.

    Maintains open lots in order of arrival for matching.
    """

    def __init__(self, risk_pair: str):
        self.risk_pair = risk_pair
        self.open_lots: List[Lot] = []
        self.closed_lots: List[Lot] = []

    def add_lot(self, lot: Lot) -> None:
        """Add a new lot to the queue."""
        if lot.risk_pair != self.risk_pair:
            raise ValueError(f"Lot risk pair {lot.risk_pair} does not match queue {self.risk_pair}")
        self.open_lots.append(lot)

    def match(
        self,
        quantity: Decimal,
        side: Side,
        close_price: Decimal,
        close_timestamp: datetime,
    ) -> List[LotMatch]:
        """
        Match quantity against open lots using FIFO.

        Only matches lots with opposite side (BUY matches SELL and vice versa).

        Args:
            quantity: Amount to match
            side: Side of the offsetting trade
            close_price: Price at which matching occurs
            close_timestamp: When matching occurs

        Returns:
            List of LotMatch objects for matched lots
        """
        if quantity <= 0:
            raise ValueError(f"Match quantity must be positive, got {quantity}")

        # Determine opposite side for matching
        opposite_side = Side.SELL if side == Side.BUY else Side.BUY

        matches: List[LotMatch] = []
        remaining_to_match = quantity
        new_open_lots: List[Lot] = []

        for lot in self.open_lots:
            if remaining_to_match <= 0:
                # No more to match, keep remaining lots
                new_open_lots.append(lot)
                continue

            if lot.side != opposite_side:
                # Wrong side, can't match
                new_open_lots.append(lot)
                continue

            # Match this lot
            matched_qty = min(lot.quantity, remaining_to_match)
            realized_pnl = lot.compute_realized_pnl(matched_qty, close_price)

            if matched_qty == lot.quantity:
                # Fully matched - close the lot by setting quantity=0 directly
                closed_lot = replace(
                    lot,
                    quantity=Decimal("0"),
                    close_timestamp=close_timestamp,
                    close_mid=close_price,
                )
                self.closed_lots.append(closed_lot)
                remaining_lot = None
            else:
                # Partially matched
                remaining_lot = lot.reduce_quantity(matched_qty)
                new_open_lots.append(remaining_lot)

            matches.append(
                LotMatch(
                    lot=lot,
                    matched_quantity=matched_qty,
                    remaining_lot=remaining_lot,
                    realized_pnl=realized_pnl,
                    close_price=close_price,
                    close_timestamp=close_timestamp,
                )
            )

            remaining_to_match -= matched_qty

        self.open_lots = new_open_lots

        return matches

    def get_net_position(self) -> Decimal:
        """
        Calculate net position from open lots.

        Returns signed notional: positive for net long, negative for net short.
        """
        net = Decimal("0")
        for lot in self.open_lots:
            if lot.is_buy:
                net += lot.quantity
            else:
                net -= lot.quantity
        return net

    def get_total_unrealized_pnl(self, current_mid: Decimal) -> Decimal:
        """Calculate total unrealized P&L for all open lots."""
        return sum(lot.compute_unrealized_pnl(current_mid) for lot in self.open_lots)

    def to_dict(self) -> dict:
        """Serialize queue state for output."""
        return {
            "risk_pair": self.risk_pair,
            "open_lot_count": len(self.open_lots),
            "closed_lot_count": len(self.closed_lots),
            "net_position": str(self.get_net_position()),
            "open_lots": [
                {
                    "lot_id": lot.lot_id,
                    "side": lot.side.value,
                    "quantity": str(lot.quantity),
                    "trade_price": str(lot.trade_price),
                    "open_timestamp": lot.open_timestamp.isoformat(),
                }
                for lot in self.open_lots
            ],
        }
