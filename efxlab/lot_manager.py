"""
Lot manager for tracking positions across all risk pairs.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, List

from efxlab.events import Side
from efxlab.lot import Lot, LotMatch, LotQueue


@dataclass
class LotConfig:
    """
    Configuration for lot tracking system.

    Attributes:
        enabled: Whether lot tracking is active
        matching_rule: FIFO, LIFO, or OPTIMIZED
        risk_pairs: List of direct pairs for position tracking
        trade_pairs: List of allowed client trade pairs (includes crosses)
        hedge_pairs: List of pairs desk can hedge in
        reporting_currency: Base currency for P&L (usually USD)
    """

    enabled: bool = True
    matching_rule: str = "FIFO"
    risk_pairs: List[str] = None
    trade_pairs: List[str] = None
    hedge_pairs: List[str] = None
    reporting_currency: str = "USD"

    def __post_init__(self) -> None:
        if self.risk_pairs is None:
            self.risk_pairs = []
        if self.trade_pairs is None:
            self.trade_pairs = []
        if self.hedge_pairs is None:
            self.hedge_pairs = []

        # Validate risk pairs format
        for pair in self.risk_pairs:
            if "/" not in pair:
                raise ValueError(f"Invalid risk pair format: {pair}")
            base, quote = pair.split("/")
            if quote != self.reporting_currency:
                raise ValueError(
                    f"Risk pair {pair} must be quoted in reporting currency {self.reporting_currency}"
                )

    def is_risk_pair(self, pair: str) -> bool:
        """Check if pair is a risk pair."""
        return pair in self.risk_pairs

    def is_trade_pair(self, pair: str) -> bool:
        """Check if pair is allowed for client trades."""
        return pair in self.trade_pairs

    def is_cross(self, pair: str) -> bool:
        """Check if pair is a cross (not a risk/direct pair)."""
        return self.is_trade_pair(pair) and not self.is_risk_pair(pair)


class LotManager:
    """
    Manages lot queues for all risk pairs with FIFO matching.

    Provides centralized lot tracking, matching, and P&L calculation.
    """

    def __init__(self, config: LotConfig):
        self.config = config
        self.queues: Dict[str, LotQueue] = {}

        # Initialize queues for all risk pairs
        for risk_pair in config.risk_pairs:
            self.queues[risk_pair] = LotQueue(risk_pair)

    def add_lot(self, lot: Lot) -> None:
        """
        Add a new lot to the appropriate queue.

        Args:
            lot: Lot to add

        Raises:
            ValueError: If risk pair is not configured
        """
        if lot.risk_pair not in self.queues:
            raise ValueError(
                f"Risk pair {lot.risk_pair} not configured. "
                f"Available: {list(self.queues.keys())}"
            )

        self.queues[lot.risk_pair].add_lot(lot)

    def match_lots(
        self,
        risk_pair: str,
        quantity: Decimal,
        side: Side,
        close_price: Decimal,
        close_timestamp: datetime,
    ) -> List[LotMatch]:
        """
        Match offsetting quantity against open lots.

        Args:
            risk_pair: Which risk pair to match in
            quantity: Amount to match
            side: Side of the offsetting trade
            close_price: Price at which matching occurs
            close_timestamp: When matching occurs

        Returns:
            List of lot matches (may be empty if no matches)
        """
        if risk_pair not in self.queues:
            raise ValueError(f"Risk pair {risk_pair} not configured")

        return self.queues[risk_pair].match(quantity, side, close_price, close_timestamp)

    def get_net_position(self, risk_pair: str) -> Decimal:
        """Get net position for a risk pair."""
        if risk_pair not in self.queues:
            return Decimal("0")
        return self.queues[risk_pair].get_net_position()

    def get_all_net_positions(self) -> Dict[str, Decimal]:
        """Get net positions for all risk pairs."""
        return {pair: queue.get_net_position() for pair, queue in self.queues.items()}

    def get_open_lots(self, risk_pair: str) -> List[Lot]:
        """Get all open lots for a risk pair."""
        if risk_pair not in self.queues:
            return []
        return self.queues[risk_pair].open_lots.copy()

    def get_all_open_lots(self) -> Dict[str, List[Lot]]:
        """Get all open lots across all risk pairs."""
        return {pair: queue.open_lots.copy() for pair, queue in self.queues.items()}

    def compute_total_unrealized_pnl(self, market_mids: Dict[str, Decimal]) -> Decimal:
        """
        Compute total unrealized P&L across all risk pairs.

        Args:
            market_mids: Current mid prices for each risk pair

        Returns:
            Total unrealized P&L in reporting currency
        """
        total_pnl = Decimal("0")
        for risk_pair, queue in self.queues.items():
            if risk_pair in market_mids:
                total_pnl += queue.get_total_unrealized_pnl(market_mids[risk_pair])
        return total_pnl

    def get_lot_count_stats(self) -> Dict[str, int]:
        """Get statistics on lot counts."""
        return {
            "total_open_lots": sum(len(q.open_lots) for q in self.queues.values()),
            "total_closed_lots": sum(len(q.closed_lots) for q in self.queues.values()),
            "queues": {
                pair: {
                    "open": len(queue.open_lots),
                    "closed": len(queue.closed_lots),
                }
                for pair, queue in self.queues.items()
            },
        }

    def to_dict(self) -> dict:
        """Serialize manager state for output."""
        return {
            "config": {
                "enabled": self.config.enabled,
                "matching_rule": self.config.matching_rule,
                "risk_pairs": self.config.risk_pairs,
            },
            "queues": {pair: queue.to_dict() for pair, queue in self.queues.items()},
            "stats": self.get_lot_count_stats(),
            "net_positions": {pair: str(pos) for pair, pos in self.get_all_net_positions().items()},
        }
