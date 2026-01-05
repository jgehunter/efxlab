"""
Currency converter for FX rate conversions.

Handles direct and inverse pair lookups with proper bid/ask spreads.
"""

from decimal import Decimal

from efxlab.state import EngineState, MarketRate


class ConversionError(Exception):
    """Raised when currency conversion is not possible."""

    pass


class CurrencyConverter:
    """
    Interface for converting between currencies using market rates.
    
    Handles:
    - Direct pairs (EUR/USD for EUR->USD)
    - Inverse pairs (EUR/USD for USD->EUR)
    - Bid/ask spreads
    """

    def __init__(self, state: EngineState):
        self.state = state

    def convert(
        self, amount: Decimal, from_currency: str, to_currency: str, use_mid: bool = True
    ) -> Decimal:
        """
        Convert amount from one currency to another.
        
        Args:
            amount: Amount to convert
            from_currency: Source currency
            to_currency: Target currency
            use_mid: Use mid rate (True) or consider bid/ask (False)
        
        Returns:
            Converted amount
        
        Raises:
            ConversionError: If conversion is not possible
        """
        if from_currency == to_currency:
            return amount

        # Try direct pair
        direct_pair = f"{from_currency}/{to_currency}"
        rate = self.state.get_market_rate(direct_pair)
        if rate:
            price = rate.mid if use_mid else (rate.bid if amount > 0 else rate.ask)
            return amount * price

        # Try inverse pair
        inverse_pair = f"{to_currency}/{from_currency}"
        rate = self.state.get_market_rate(inverse_pair)
        if rate:
            price = rate.mid if use_mid else (rate.ask if amount > 0 else rate.bid)
            if price == 0:
                raise ConversionError(f"Cannot divide by zero rate for {inverse_pair}")
            return amount / price

        # No rate available
        raise ConversionError(
            f"No market rate available for {from_currency}/{to_currency} "
            f"or {to_currency}/{from_currency}"
        )

    def convert_to_reporting(self, amount: Decimal, currency: str) -> Decimal:
        """Convert amount to reporting currency."""
        return self.convert(amount, currency, self.state.reporting_currency)

    def get_rate(self, from_currency: str, to_currency: str) -> Decimal:
        """Get mid rate between two currencies."""
        if from_currency == to_currency:
            return Decimal("1")

        direct_pair = f"{from_currency}/{to_currency}"
        rate = self.state.get_market_rate(direct_pair)
        if rate:
            return rate.mid

        inverse_pair = f"{to_currency}/{from_currency}"
        rate = self.state.get_market_rate(inverse_pair)
        if rate:
            if rate.mid == 0:
                raise ConversionError(f"Cannot divide by zero rate for {inverse_pair}")
            return Decimal("1") / rate.mid

        raise ConversionError(
            f"No market rate available for {from_currency}/{to_currency}"
        )
