"""
Trade decomposition logic for converting crosses into direct risk pairs.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from efxlab.converter import CurrencyConverter
from efxlab.events import Side
from efxlab.lot import Lot


@dataclass
class DecomposedLeg:
    """
    A single leg from decomposing a cross trade.

    Attributes:
        risk_pair: The direct pair (e.g., EUR/USD)
        side: BUY or SELL from desk perspective
        quantity: Amount in base currency of risk pair
        trade_price: Execution price for this leg
        decomposition_path: How this leg was derived
    """

    risk_pair: str
    side: Side
    quantity: Decimal
    trade_price: Decimal
    decomposition_path: str


class TradeDecomposer:
    """
    Decomposes cross trades into legs in direct risk pairs.

    Examples:
        Client BUY EUR/GBP 1M @ 0.8500:
        - Desk SELLS EUR/USD: desk sells 1M EUR @ 1.1000 = -1M EUR, +1.1M USD
        - Desk BUYS GBP/USD: desk buys 0.85M GBP @ 1.2941 = +0.85M GBP, -1.1M USD

        Result:
        - Leg 1: EUR/USD SELL 1M @ 1.1000 (path: EUR/GBP->EUR/USD)
        - Leg 2: GBP/USD BUY 0.85M @ 1.2941 (path: EUR/GBP->GBP/USD)
    """

    def __init__(self, converter: CurrencyConverter, reporting_currency: str = "USD"):
        self.converter = converter
        self.reporting_currency = reporting_currency

    def decompose(
        self,
        trade_pair: str,
        client_side: Side,
        quantity: Decimal,
        execution_price: Decimal,
    ) -> List[DecomposedLeg]:
        """
        Decompose a trade into legs in direct risk pairs.

        Args:
            trade_pair: Client trade pair (e.g., EUR/GBP)
            client_side: Client's side (BUY or SELL)
            quantity: Trade quantity in base currency
            execution_price: Client execution price

        Returns:
            List of decomposed legs (1 leg if direct pair, 2 legs if cross)

        Raises:
            ValueError: If decomposition cannot be performed
        """
        base, quote = trade_pair.split("/")

        # If trade is already a direct pair, return single leg
        if quote == self.reporting_currency:
            return [self._direct_pair_leg(trade_pair, client_side, quantity, execution_price)]

        # Cross trade: decompose into two legs
        # Client BUY EUR/GBP means:
        # - Desk SELLS EUR (receives reporting currency)
        # - Desk BUYS GBP (pays reporting currency)

        # Desk's side is opposite of client's side
        desk_side_base = Side.SELL if client_side == Side.BUY else Side.BUY

        # Leg 1: Base currency risk pair
        base_risk_pair = f"{base}/{self.reporting_currency}"
        try:
            base_rate = self.converter.get_rate(base, self.reporting_currency)
        except ValueError as e:
            raise ValueError(f"Cannot get rate for {base_risk_pair}: {e}")

        leg1 = DecomposedLeg(
            risk_pair=base_risk_pair,
            side=desk_side_base,
            quantity=quantity,
            trade_price=base_rate,
            decomposition_path=f"{trade_pair}->{base_risk_pair}",
        )

        # Leg 2: Quote currency risk pair
        # Amount in quote currency = quantity * execution_price
        quote_amount = quantity * execution_price
        quote_risk_pair = f"{quote}/{self.reporting_currency}"

        # Desk's side for quote is opposite of base
        desk_side_quote = Side.BUY if desk_side_base == Side.SELL else Side.SELL

        try:
            quote_rate = self.converter.get_rate(quote, self.reporting_currency)
        except ValueError as e:
            raise ValueError(f"Cannot get rate for {quote_risk_pair}: {e}")

        leg2 = DecomposedLeg(
            risk_pair=quote_risk_pair,
            side=desk_side_quote,
            quantity=quote_amount,
            trade_price=quote_rate,
            decomposition_path=f"{trade_pair}->{quote_risk_pair}",
        )

        return [leg1, leg2]

    def _direct_pair_leg(
        self,
        risk_pair: str,
        client_side: Side,
        quantity: Decimal,
        execution_price: Decimal,
    ) -> DecomposedLeg:
        """Create leg for direct pair (no decomposition needed)."""
        # Desk's side is opposite of client's side
        desk_side = Side.SELL if client_side == Side.BUY else Side.BUY

        return DecomposedLeg(
            risk_pair=risk_pair,
            side=desk_side,
            quantity=quantity,
            trade_price=execution_price,
            decomposition_path=risk_pair,  # No decomposition for direct pairs
        )

    def legs_to_lots(
        self,
        legs: List[DecomposedLeg],
        originating_trade_id: str,
        timestamp: datetime,
        open_mids: dict[str, Decimal],
    ) -> List[Lot]:
        """
        Convert decomposed legs into Lot objects.

        Args:
            legs: Decomposed legs from a trade
            originating_trade_id: ID of the original client trade
            timestamp: Trade timestamp
            open_mids: Current mid prices for each risk pair

        Returns:
            List of Lot objects ready to add to lot queues
        """
        lots = []
        for leg in legs:
            open_mid = open_mids.get(leg.risk_pair)
            if open_mid is None:
                raise ValueError(f"Missing mid price for {leg.risk_pair} needed to create lot")

            lot = Lot(
                lot_id=f"{originating_trade_id}_{leg.risk_pair}",
                risk_pair=leg.risk_pair,
                side=leg.side,
                quantity=leg.quantity,
                original_quantity=leg.quantity,
                trade_price=leg.trade_price,
                open_timestamp=timestamp,
                originating_trade_id=originating_trade_id,
                decomposition_path=leg.decomposition_path,
                open_mid=open_mid,
                close_timestamp=None,
                close_mid=None,
            )
            lots.append(lot)

        return lots
