"""
Tests for lot tracking system (lot.py, lot_manager.py, decomposition.py).
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from efxlab.converter import CurrencyConverter
from efxlab.decomposition import TradeDecomposer
from efxlab.events import Side
from efxlab.lot import Lot, LotQueue
from efxlab.lot_manager import LotConfig, LotManager
from efxlab.state import EngineState, MarketRate


class TestLot:
    """Test Lot dataclass validation and operations."""

    def test_lot_creation(self):
        """Test creating a valid lot."""
        lot = Lot(
            lot_id="T001_EUR/USD",
            risk_pair="EUR/USD",
            side=Side.BUY,
            quantity=Decimal("100000"),
            original_quantity=Decimal("100000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T001",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.0995"),
            close_timestamp=None,
            close_mid=None,
        )
        assert lot.lot_id == "T001_EUR/USD"
        assert lot.quantity == Decimal("100000")

    def test_lot_validation_negative_quantity(self):
        """Test lot rejects negative quantity."""
        with pytest.raises(ValueError, match="cannot be negative"):
            Lot(
                lot_id="T001",
                risk_pair="EUR/USD",
                side=Side.BUY,
                quantity=Decimal("-100000"),
                original_quantity=Decimal("100000"),
                trade_price=Decimal("1.1000"),
                open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                originating_trade_id="T001",
                decomposition_path="EUR/USD",
                open_mid=Decimal("1.0995"),
                close_timestamp=None,
                close_mid=None,
            )

    def test_lot_unrealized_pnl_buy(self):
        """Test unrealized P&L calculation for BUY lot."""
        lot = Lot(
            lot_id="T001",
            risk_pair="EUR/USD",
            side=Side.BUY,
            quantity=Decimal("100000"),
            original_quantity=Decimal("100000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T001",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.0995"),
            close_timestamp=None,
            close_mid=None,
        )
        # Buy @ 1.1000, mark @ 1.1500 -> gain +5000 USD (0.05 * 100k)
        pnl = lot.get_unrealized_pnl(Decimal("1.1500"))
        assert pnl == Decimal("5000")

    def test_lot_unrealized_pnl_sell(self):
        """Test unrealized P&L calculation for SELL lot."""
        lot = Lot(
            lot_id="T002",
            risk_pair="EUR/USD",
            side=Side.SELL,
            quantity=Decimal("100000"),
            original_quantity=Decimal("100000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T002",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.1005"),
            close_timestamp=None,
            close_mid=None,
        )
        # Sell @ 1.1000, mark @ 1.0900 -> gain +1000 USD (0.01 * 100k)
        pnl = lot.get_unrealized_pnl(Decimal("1.0900"))
        assert pnl == Decimal("1000")


class TestLotQueue:
    """Test LotQueue FIFO matching logic."""

    def test_empty_queue(self):
        """Test operations on empty queue."""
        queue = LotQueue("EUR/USD")
        assert queue.get_net_position() == Decimal("0")
        assert len(queue.open_lots) == 0

    def test_add_buy_lot(self):
        """Test adding a BUY lot."""
        queue = LotQueue("EUR/USD")
        lot = Lot(
            lot_id="T001",
            risk_pair="EUR/USD",
            side=Side.BUY,
            quantity=Decimal("100000"),
            original_quantity=Decimal("100000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T001",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.0995"),
            close_timestamp=None,
            close_mid=None,
        )
        queue.add_lot(lot)
        assert queue.get_net_position() == Decimal("100000")
        assert len(queue.open_lots) == 1

    def test_add_sell_lot(self):
        """Test adding a SELL lot."""
        queue = LotQueue("EUR/USD")
        lot = Lot(
            lot_id="T002",
            risk_pair="EUR/USD",
            side=Side.SELL,
            quantity=Decimal("50000"),
            original_quantity=Decimal("50000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T002",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.1005"),
            close_timestamp=None,
            close_mid=None,
        )
        queue.add_lot(lot)
        assert queue.get_net_position() == Decimal("-50000")
        assert len(queue.open_lots) == 1

    def test_full_fifo_match(self):
        """Test full FIFO match closes entire lot."""
        queue = LotQueue("EUR/USD")

        # Add BUY lot
        buy_lot = Lot(
            lot_id="T001",
            risk_pair="EUR/USD",
            side=Side.BUY,
            quantity=Decimal("100000"),
            original_quantity=Decimal("100000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T001",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.0995"),
            close_timestamp=None,
            close_mid=None,
        )
        queue.add_lot(buy_lot)

        # Match with SELL (closes BUY)
        matches = queue.match(
            Decimal("100000"),
            Side.SELL,
            Decimal("1.1500"),
            datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
        )

        assert len(matches) == 1
        match = matches[0]
        assert match.matched_quantity == Decimal("100000")
        assert match.remaining_lot is None  # Fully closed
        assert match.realized_pnl == Decimal("5000")  # (1.1500 - 1.1000) * 100k = 5000

        # Queue should be empty
        assert queue.get_net_position() == Decimal("0")
        assert len(queue.open_lots) == 0
        assert len(queue.closed_lots) == 1

    def test_partial_fifo_match(self):
        """Test partial FIFO match reduces lot quantity."""
        queue = LotQueue("EUR/USD")

        # Add BUY lot
        buy_lot = Lot(
            lot_id="T001",
            risk_pair="EUR/USD",
            side=Side.BUY,
            quantity=Decimal("100000"),
            original_quantity=Decimal("100000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T001",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.0995"),
            close_timestamp=None,
            close_mid=None,
        )
        queue.add_lot(buy_lot)

        # Match with SELL of smaller amount
        matches = queue.match(
            Decimal("40000"),
            Side.SELL,
            Decimal("1.1500"),
            datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
        )

        assert len(matches) == 1
        match = matches[0]
        assert match.matched_quantity == Decimal("40000")
        assert match.remaining_lot is not None
        assert match.remaining_lot.quantity == Decimal("60000")
        assert match.realized_pnl == Decimal("2000")  # (1.1500 - 1.1000) * 40k = 2000

        # Queue should have reduced position
        assert queue.get_net_position() == Decimal("60000")
        assert len(queue.open_lots) == 1
        assert queue.open_lots[0].quantity == Decimal("60000")

    def test_multi_lot_fifo_match(self):
        """Test FIFO match across multiple lots."""
        queue = LotQueue("EUR/USD")

        # Add two BUY lots
        lot1 = Lot(
            lot_id="T001",
            risk_pair="EUR/USD",
            side=Side.BUY,
            quantity=Decimal("50000"),
            original_quantity=Decimal("50000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T001",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.0995"),
            close_timestamp=None,
            close_mid=None,
        )
        lot2 = Lot(
            lot_id="T002",
            risk_pair="EUR/USD",
            side=Side.BUY,
            quantity=Decimal("75000"),
            original_quantity=Decimal("75000"),
            trade_price=Decimal("1.1100"),
            open_timestamp=datetime(2024, 1, 1, 10, 5, tzinfo=timezone.utc),
            originating_trade_id="T002",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.1095"),
            close_timestamp=None,
            close_mid=None,
        )
        queue.add_lot(lot1)
        queue.add_lot(lot2)

        # Match with SELL that spans both lots
        matches = queue.match(
            Decimal("100000"),
            Side.SELL,
            Decimal("1.1500"),
            datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
        )

        assert len(matches) == 2

        # First match: lot1 fully closed
        match1 = matches[0]
        assert match1.matched_quantity == Decimal("50000")
        assert match1.remaining_lot is None
        assert match1.realized_pnl == Decimal("2500")  # (1.1500 - 1.1000) * 50k = 2500

        # Second match: lot2 partially closed
        match2 = matches[1]
        assert match2.matched_quantity == Decimal("50000")
        assert match2.remaining_lot is not None
        assert match2.remaining_lot.quantity == Decimal("25000")
        assert match2.realized_pnl == Decimal("2000")  # (1.1500 - 1.1100) * 50k = 2000

        # Queue should have reduced position
        assert queue.get_net_position() == Decimal("25000")
        assert len(queue.open_lots) == 1
        assert len(queue.closed_lots) == 1

    def test_no_match_same_side(self):
        """Test no match occurs when sides are the same."""
        queue = LotQueue("EUR/USD")

        buy_lot = Lot(
            lot_id="T001",
            risk_pair="EUR/USD",
            side=Side.BUY,
            quantity=Decimal("100000"),
            original_quantity=Decimal("100000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T001",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.0995"),
            close_timestamp=None,
            close_mid=None,
        )
        queue.add_lot(buy_lot)

        # Try to match with BUY (same side)
        matches = queue.match(
            Decimal("50000"),
            Side.BUY,
            Decimal("1.1500"),
            datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
        )

        assert len(matches) == 0  # No matches
        assert queue.get_net_position() == Decimal("100000")
        assert len(queue.open_lots) == 1

    def test_unrealized_pnl_calculation(self):
        """Test total unrealized P&L across multiple lots."""
        queue = LotQueue("EUR/USD")

        # Add BUY lot
        buy_lot = Lot(
            lot_id="T001",
            risk_pair="EUR/USD",
            side=Side.BUY,
            quantity=Decimal("100000"),
            original_quantity=Decimal("100000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T001",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.0995"),
            close_timestamp=None,
            close_mid=None,
        )
        # Add SELL lot
        sell_lot = Lot(
            lot_id="T002",
            risk_pair="EUR/USD",
            side=Side.SELL,
            quantity=Decimal("50000"),
            original_quantity=Decimal("50000"),
            trade_price=Decimal("1.1200"),
            open_timestamp=datetime(2024, 1, 1, 10, 5, tzinfo=timezone.utc),
            originating_trade_id="T002",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.1205"),
            close_timestamp=None,
            close_mid=None,
        )
        queue.add_lot(buy_lot)
        queue.add_lot(sell_lot)

        # Mark @ 1.1500
        # BUY lot: (1.1500 - 1.1000) * 100k = +5000
        # SELL lot: (1.1200 - 1.1500) * 50k = -1500 (direction * -1)
        # Total: +3500
        total_pnl = queue.get_total_unrealized_pnl(Decimal("1.1500"))
        assert total_pnl == Decimal("3500")


class TestLotConfig:
    """Test LotConfig validation."""

    def test_valid_config(self):
        """Test creating valid config."""
        config = LotConfig(
            enabled=True,
            matching_rule="FIFO",
            risk_pairs=["EUR/USD", "GBP/USD"],
            trade_pairs=["EUR/USD", "GBP/USD", "EUR/GBP"],
            hedge_pairs=["EUR/USD", "GBP/USD"],
            reporting_currency="USD",
        )
        assert config.is_risk_pair("EUR/USD")
        assert config.is_trade_pair("EUR/GBP")
        assert config.is_cross("EUR/GBP")
        assert not config.is_cross("EUR/USD")

    def test_invalid_risk_pair_format(self):
        """Test config rejects invalid risk pair format."""
        with pytest.raises(ValueError, match="Invalid risk pair format"):
            LotConfig(
                risk_pairs=["EURUSD"],  # Missing /
                reporting_currency="USD",
            )

    def test_invalid_risk_pair_currency(self):
        """Test config rejects risk pair not in reporting currency."""
        with pytest.raises(ValueError, match="must be quoted in reporting currency"):
            LotConfig(
                risk_pairs=["EUR/GBP"],  # Not quoted in USD
                reporting_currency="USD",
            )


class TestLotManager:
    """Test LotManager orchestration."""

    def test_manager_initialization(self):
        """Test manager initializes queues for risk pairs."""
        config = LotConfig(
            risk_pairs=["EUR/USD", "GBP/USD"],
            trade_pairs=["EUR/USD", "GBP/USD", "EUR/GBP"],
            reporting_currency="USD",
        )
        manager = LotManager(config)

        assert "EUR/USD" in manager.queues
        assert "GBP/USD" in manager.queues
        assert len(manager.queues) == 2

    def test_add_lot_to_manager(self):
        """Test adding lot through manager."""
        config = LotConfig(
            risk_pairs=["EUR/USD"],
            trade_pairs=["EUR/USD"],
            reporting_currency="USD",
        )
        manager = LotManager(config)

        lot = Lot(
            lot_id="T001",
            risk_pair="EUR/USD",
            side=Side.BUY,
            quantity=Decimal("100000"),
            original_quantity=Decimal("100000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T001",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.0995"),
            close_timestamp=None,
            close_mid=None,
        )
        manager.add_lot(lot)

        assert manager.get_net_position("EUR/USD") == Decimal("100000")

    def test_match_through_manager(self):
        """Test matching lots through manager."""
        config = LotConfig(
            risk_pairs=["EUR/USD"],
            trade_pairs=["EUR/USD"],
            reporting_currency="USD",
        )
        manager = LotManager(config)

        lot = Lot(
            lot_id="T001",
            risk_pair="EUR/USD",
            side=Side.BUY,
            quantity=Decimal("100000"),
            original_quantity=Decimal("100000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T001",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.0995"),
            close_timestamp=None,
            close_mid=None,
        )
        manager.add_lot(lot)

        matches = manager.match_lots(
            "EUR/USD",
            Decimal("100000"),
            Side.SELL,
            Decimal("1.1500"),
            datetime(2024, 1, 1, 11, 0, tzinfo=timezone.utc),
        )

        assert len(matches) == 1
        assert matches[0].realized_pnl == Decimal("5000")  # (1.1500 - 1.1000) * 100k = 5000
        assert manager.get_net_position("EUR/USD") == Decimal("0")

    def test_total_unrealized_pnl(self):
        """Test computing unrealized P&L across all pairs."""
        config = LotConfig(
            risk_pairs=["EUR/USD", "GBP/USD"],
            trade_pairs=["EUR/USD", "GBP/USD"],
            reporting_currency="USD",
        )
        manager = LotManager(config)

        # Add EUR/USD BUY lot
        eur_lot = Lot(
            lot_id="T001",
            risk_pair="EUR/USD",
            side=Side.BUY,
            quantity=Decimal("100000"),
            original_quantity=Decimal("100000"),
            trade_price=Decimal("1.1000"),
            open_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            originating_trade_id="T001",
            decomposition_path="EUR/USD",
            open_mid=Decimal("1.0995"),
            close_timestamp=None,
            close_mid=None,
        )
        # Add GBP/USD SELL lot
        gbp_lot = Lot(
            lot_id="T002",
            risk_pair="GBP/USD",
            side=Side.SELL,
            quantity=Decimal("50000"),
            original_quantity=Decimal("50000"),
            trade_price=Decimal("1.3000"),
            open_timestamp=datetime(2024, 1, 1, 10, 5, tzinfo=timezone.utc),
            originating_trade_id="T002",
            decomposition_path="GBP/USD",
            open_mid=Decimal("1.3005"),
            close_timestamp=None,
            close_mid=None,
        )
        manager.add_lot(eur_lot)
        manager.add_lot(gbp_lot)

        # Mark EUR/USD @ 1.1500, GBP/USD @ 1.2800
        market_mids = {
            "EUR/USD": Decimal("1.1500"),
            "GBP/USD": Decimal("1.2800"),
        }
        total_pnl = manager.compute_total_unrealized_pnl(market_mids)

        # EUR: (1.1500 - 1.1000) * 100k = +5000
        # GBP: (1.3000 - 1.2800) * 50k = +1000 (direction * -1)
        # Total: +6000
        assert total_pnl == Decimal("6000")


class TestTradeDecomposer:
    """Test trade decomposition logic."""

    def test_direct_pair_no_decomposition(self):
        """Test direct pair requires no decomposition."""
        # Create state with EUR/USD rate
        state = EngineState(
            cash_balances={},
            positions={},
            market_rates={
                "EUR/USD": MarketRate(Decimal("1.0995"), Decimal("1.1005"), Decimal("1.1000"))
            },
        )
        converter = CurrencyConverter(state)
        decomposer = TradeDecomposer(converter, "USD")

        legs = decomposer.decompose("EUR/USD", Side.BUY, Decimal("100000"), Decimal("1.1000"))

        assert len(legs) == 1
        leg = legs[0]
        assert leg.risk_pair == "EUR/USD"
        assert leg.side == Side.SELL  # Desk sells (opposite of client)
        assert leg.quantity == Decimal("100000")
        assert leg.trade_price == Decimal("1.1000")
        assert leg.decomposition_path == "EUR/USD"

    def test_cross_decomposition(self):
        """Test cross trade decomposes into two legs."""
        # Create state with EUR/USD and GBP/USD rates
        state = EngineState(
            cash_balances={},
            positions={},
            market_rates={
                "EUR/USD": MarketRate(Decimal("1.0995"), Decimal("1.1005"), Decimal("1.1000")),
                "GBP/USD": MarketRate(Decimal("1.2936"), Decimal("1.2946"), Decimal("1.2941")),
            },
        )
        converter = CurrencyConverter(state)
        decomposer = TradeDecomposer(converter, "USD")

        # Client BUY EUR/GBP 1M @ 0.8500
        legs = decomposer.decompose("EUR/GBP", Side.BUY, Decimal("1000000"), Decimal("0.8500"))

        assert len(legs) == 2

        # Leg 1: EUR/USD SELL (desk sells EUR)
        leg1 = legs[0]
        assert leg1.risk_pair == "EUR/USD"
        assert leg1.side == Side.SELL
        assert leg1.quantity == Decimal("1000000")
        assert leg1.trade_price == Decimal("1.1000")
        assert leg1.decomposition_path == "EUR/GBP->EUR/USD"

        # Leg 2: GBP/USD BUY (desk buys GBP)
        leg2 = legs[1]
        assert leg2.risk_pair == "GBP/USD"
        assert leg2.side == Side.BUY
        assert leg2.quantity == Decimal("850000")  # 1M * 0.8500
        assert leg2.trade_price == Decimal("1.2941")
        assert leg2.decomposition_path == "EUR/GBP->GBP/USD"

    def test_cross_sell_decomposition(self):
        """Test SELL cross trade decomposition."""
        # Create state with EUR/USD and GBP/USD rates
        state = EngineState(
            cash_balances={},
            positions={},
            market_rates={
                "EUR/USD": MarketRate(Decimal("1.0995"), Decimal("1.1005"), Decimal("1.1000")),
                "GBP/USD": MarketRate(Decimal("1.2936"), Decimal("1.2946"), Decimal("1.2941")),
            },
        )
        converter = CurrencyConverter(state)
        decomposer = TradeDecomposer(converter, "USD")

        # Client SELL EUR/GBP 500k @ 0.8500
        legs = decomposer.decompose("EUR/GBP", Side.SELL, Decimal("500000"), Decimal("0.8500"))

        assert len(legs) == 2

        # Leg 1: EUR/USD BUY (desk buys EUR)
        leg1 = legs[0]
        assert leg1.risk_pair == "EUR/USD"
        assert leg1.side == Side.BUY
        assert leg1.quantity == Decimal("500000")

        # Leg 2: GBP/USD SELL (desk sells GBP)
        leg2 = legs[1]
        assert leg2.risk_pair == "GBP/USD"
        assert leg2.side == Side.SELL
        assert leg2.quantity == Decimal("425000")  # 500k * 0.8500

    def test_legs_to_lots_conversion(self):
        """Test converting legs to lot objects."""
        # Create state with EUR/USD rate
        state = EngineState(
            cash_balances={},
            positions={},
            market_rates={
                "EUR/USD": MarketRate(Decimal("1.0995"), Decimal("1.1005"), Decimal("1.1000"))
            },
        )
        converter = CurrencyConverter(state)
        decomposer = TradeDecomposer(converter, "USD")

        legs = decomposer.decompose("EUR/USD", Side.BUY, Decimal("100000"), Decimal("1.1000"))

        open_mids = {"EUR/USD": Decimal("1.0995")}
        lots = decomposer.legs_to_lots(
            legs,
            "T001",
            datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            open_mids,
        )

        assert len(lots) == 1
        lot = lots[0]
        assert lot.lot_id == "T001_EUR/USD"
        assert lot.risk_pair == "EUR/USD"
        assert lot.side == Side.SELL
        assert lot.quantity == Decimal("100000")
        assert lot.originating_trade_id == "T001"
        assert lot.open_mid == Decimal("1.0995")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
