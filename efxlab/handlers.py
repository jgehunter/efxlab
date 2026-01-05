"""
Event handlers - pure functions that transform state.

Each handler takes (State, Event) and returns (State, OutputRecords).
"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

from efxlab.converter import CurrencyConverter
from efxlab.decomposition import TradeDecomposer
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
    - Lot tracking (if enabled)

    Outputs:
    - Trade log record
    - Lot creation/matching records (if lot tracking enabled)
    """
    # Apply trade to cash and positions
    new_state = apply_trade(
        state,
        event.currency_pair,
        event.side,
        event.notional,
        event.price,
    )
    new_state = new_state.increment_event_count(event.timestamp.isoformat())

    # Base output record
    base_ccy, quote_ccy = event.currency_pair.split("/")
    quote_amount = event.notional * event.price

    outputs: List[OutputRecord] = []

    trade_output = OutputRecord(
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
    outputs.append(trade_output)

    # Lot tracking integration
    if new_state.lot_manager is not None:
        lot_outputs = _handle_lot_tracking(new_state, event)
        outputs.extend(lot_outputs)

    return new_state, outputs


def _handle_lot_tracking(state: EngineState, event: ClientTradeEvent) -> List[OutputRecord]:
    """
    Handle lot creation and matching for a client trade.

    Strategy:
    - Decompose trade into risk pair legs
    - For each leg, check if it reduces or increases net position
    - If reduces: match against existing opposite lots (internalization)
    - If increases: create new lot

    Returns list of output records for lot operations.
    """
    outputs: List[OutputRecord] = []

    if not state.lot_manager:
        return outputs

    # Decompose trade into risk pair legs
    converter = CurrencyConverter(state)
    decomposer = TradeDecomposer(converter, state.reporting_currency)

    try:
        legs = decomposer.decompose(
            event.currency_pair,
            event.side,
            event.notional,
            event.price,
        )
    except ValueError as e:
        # If decomposition fails (missing market rate), log and skip
        outputs.append(
            OutputRecord(
                timestamp=event.timestamp,
                record_type="lot_tracking_error",
                data={
                    "trade_id": event.trade_id,
                    "error": str(e),
                    "message": "Failed to decompose trade for lot tracking",
                },
            )
        )
        return outputs

    # Get current mid prices for lot creation
    open_mids = {}
    for leg in legs:
        rate = state.get_market_rate(leg.risk_pair)
        if rate:
            open_mids[leg.risk_pair] = rate.mid
        else:
            # Missing market rate, can't create lot
            outputs.append(
                OutputRecord(
                    timestamp=event.timestamp,
                    record_type="lot_tracking_error",
                    data={
                        "trade_id": event.trade_id,
                        "risk_pair": leg.risk_pair,
                        "error": f"Missing market rate for {leg.risk_pair}",
                    },
                )
            )
            return outputs

    # Process each leg
    for leg in legs:
        # Get current net position before this leg
        current_net = state.lot_manager.get_net_position(leg.risk_pair)

        # Determine if this leg increases or decreases net position
        leg_impact = leg.quantity if leg.side == Side.BUY else -leg.quantity
        new_net = current_net + leg_impact

        # Check if leg reduces position (opposite sign or moves toward zero)
        reduces_position = (current_net > 0 and leg_impact < 0) or (  # Long position, selling
            current_net < 0 and leg_impact > 0
        )  # Short position, buying

        if reduces_position:
            # Match against existing lots (internalization)
            # Pass the leg's side directly - match_lots will find opposite lots
            matches = state.lot_manager.match_lots(
                leg.risk_pair,
                leg.quantity,
                leg.side,  # Pass leg side directly
                leg.trade_price,
                event.timestamp,
            )

            # Create output records for matches
            for match in matches:
                outputs.append(
                    OutputRecord(
                        timestamp=event.timestamp,
                        record_type="lot_match",
                        data={
                            "trade_id": event.trade_id,
                            "lot_id": match.lot.lot_id,
                            "risk_pair": leg.risk_pair,
                            "matched_quantity": str(match.matched_quantity),
                            "realized_pnl": str(match.realized_pnl),
                            "close_price": str(match.close_price),
                            "original_lot_side": match.lot.side.value,
                            "original_trade_id": match.lot.originating_trade_id,
                            "decomposition_path": leg.decomposition_path,
                        },
                    )
                )

            # If not fully matched, create lot for remainder
            matched_total = sum(m.matched_quantity for m in matches)
            if matched_total < leg.quantity:
                remainder = leg.quantity - matched_total
                lots = decomposer.legs_to_lots(
                    [leg],
                    event.trade_id,
                    event.timestamp,
                    open_mids,
                )
                for lot in lots:
                    # Adjust quantity to remainder
                    adjusted_lot = replace(
                        lot,
                        quantity=remainder,
                        original_quantity=remainder,
                    )
                    state.lot_manager.add_lot(adjusted_lot)

                    outputs.append(
                        OutputRecord(
                            timestamp=event.timestamp,
                            record_type="lot_created",
                            data={
                                "trade_id": event.trade_id,
                                "lot_id": adjusted_lot.lot_id,
                                "risk_pair": adjusted_lot.risk_pair,
                                "side": adjusted_lot.side.value,
                                "quantity": str(adjusted_lot.quantity),
                                "trade_price": str(adjusted_lot.trade_price),
                                "open_mid": str(adjusted_lot.open_mid),
                                "decomposition_path": adjusted_lot.decomposition_path,
                            },
                        )
                    )
        else:
            # Increases position - create new lot
            lots = decomposer.legs_to_lots(
                [leg],
                event.trade_id,
                event.timestamp,
                open_mids,
            )

            for lot in lots:
                state.lot_manager.add_lot(lot)

                outputs.append(
                    OutputRecord(
                        timestamp=event.timestamp,
                        record_type="lot_created",
                        data={
                            "trade_id": event.trade_id,
                            "lot_id": lot.lot_id,
                            "risk_pair": lot.risk_pair,
                            "side": lot.side.value,
                            "quantity": str(lot.quantity),
                            "trade_price": str(lot.trade_price),
                            "open_mid": str(lot.open_mid),
                            "decomposition_path": lot.decomposition_path,
                        },
                    )
                )

    return outputs


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
    - Lot tracking metrics (if enabled)

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

    # Prepare output data
    output_data = {
        "tick_label": event.tick_label,
        "cash_balances": {k: str(v) for k, v in state.cash_balances.items()},
        "positions": {k: str(v) for k, v in state.positions.items()},
        "exposures": {k: str(v) for k, v in exposures.items()},
        "total_equity_reporting": str(total_equity),
        "reporting_currency": state.reporting_currency,
        "event_count": state.event_count,
    }

    # Add lot tracking metrics if enabled
    if state.lot_manager:
        market_mids = {
            pair: rate.mid for pair, rate in state.market_rates.items() if rate is not None
        }
        total_unrealized_pnl = state.lot_manager.compute_total_unrealized_pnl(market_mids)
        lot_stats = state.lot_manager.get_lot_count_stats()
        net_positions = state.lot_manager.get_all_net_positions()

        output_data["lot_tracking"] = {
            "total_unrealized_pnl": str(total_unrealized_pnl),
            "total_open_lots": lot_stats["total_open_lots"],
            "total_closed_lots": lot_stats["total_closed_lots"],
            "net_positions_by_risk_pair": {k: str(v) for k, v in net_positions.items()},
        }

    output = OutputRecord(
        timestamp=event.timestamp,
        record_type="clock_tick",
        data=output_data,
    )

    return new_state, [output]
