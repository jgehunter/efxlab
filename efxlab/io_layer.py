"""
I/O layer for reading/writing event data and outputs.

Handles Parquet and JSONL formats with schema validation.
"""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from efxlab.events import (
    BaseEvent,
    ClientTradeEvent,
    ClockTickEvent,
    ConfigUpdateEvent,
    EventType,
    HedgeFillEvent,
    HedgeOrderEvent,
    MarketUpdateEvent,
    Side,
)
from efxlab.handlers import OutputRecord

logger = structlog.get_logger()


# Parquet schemas for input events
CLIENT_TRADE_SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("sequence_id", pa.int64()),
        ("currency_pair", pa.string()),
        ("side", pa.string()),
        ("notional", pa.string()),  # Decimal as string
        ("price", pa.string()),
        ("client_id", pa.string()),
        ("trade_id", pa.string()),
    ]
)

MARKET_UPDATE_SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("sequence_id", pa.int64()),
        ("currency_pair", pa.string()),
        ("bid", pa.string()),
        ("ask", pa.string()),
        ("mid", pa.string()),
    ]
)

CONFIG_UPDATE_SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("sequence_id", pa.int64()),
        ("config_key", pa.string()),
        ("config_value", pa.string()),
    ]
)

HEDGE_ORDER_SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("sequence_id", pa.int64()),
        ("order_id", pa.string()),
        ("currency_pair", pa.string()),
        ("side", pa.string()),
        ("notional", pa.string()),
        ("limit_price", pa.string()),  # Nullable
    ]
)

HEDGE_FILL_SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("sequence_id", pa.int64()),
        ("order_id", pa.string()),
        ("currency_pair", pa.string()),
        ("side", pa.string()),
        ("notional", pa.string()),
        ("fill_price", pa.string()),
        ("slippage", pa.string()),
    ]
)

CLOCK_TICK_SCHEMA = pa.schema(
    [
        ("timestamp", pa.timestamp("us", tz="UTC")),
        ("sequence_id", pa.int64()),
        ("tick_label", pa.string()),
    ]
)


def load_events_from_parquet(file_path: Path, event_type: EventType) -> List[BaseEvent]:
    """
    Load events from a Parquet file.
    
    Args:
        file_path: Path to Parquet file
        event_type: Type of events in the file
    
    Returns:
        List of event objects
    """
    logger.info("loading_events", file_path=str(file_path), event_type=event_type.value)

    table = pq.read_table(file_path)
    events: List[BaseEvent] = []

    for row in table.to_pylist():
        try:
            if event_type == EventType.CLIENT_TRADE:
                event = ClientTradeEvent(
                    timestamp=row["timestamp"],
                    sequence_id=row["sequence_id"],
                    event_type=EventType.CLIENT_TRADE,
                    currency_pair=row["currency_pair"],
                    side=Side[row["side"]],
                    notional=Decimal(row["notional"]),
                    price=Decimal(row["price"]),
                    client_id=row["client_id"],
                    trade_id=row["trade_id"],
                )
            elif event_type == EventType.MARKET_UPDATE:
                event = MarketUpdateEvent(
                    timestamp=row["timestamp"],
                    sequence_id=row["sequence_id"],
                    event_type=EventType.MARKET_UPDATE,
                    currency_pair=row["currency_pair"],
                    bid=Decimal(row["bid"]),
                    ask=Decimal(row["ask"]),
                    mid=Decimal(row["mid"]),
                )
            elif event_type == EventType.CONFIG_UPDATE:
                event = ConfigUpdateEvent(
                    timestamp=row["timestamp"],
                    sequence_id=row["sequence_id"],
                    event_type=EventType.CONFIG_UPDATE,
                    config_key=row["config_key"],
                    config_value=row["config_value"],
                )
            elif event_type == EventType.HEDGE_ORDER:
                limit_price = Decimal(row["limit_price"]) if row["limit_price"] else None
                event = HedgeOrderEvent(
                    timestamp=row["timestamp"],
                    sequence_id=row["sequence_id"],
                    event_type=EventType.HEDGE_ORDER,
                    order_id=row["order_id"],
                    currency_pair=row["currency_pair"],
                    side=Side[row["side"]],
                    notional=Decimal(row["notional"]),
                    limit_price=limit_price,
                )
            elif event_type == EventType.HEDGE_FILL:
                event = HedgeFillEvent(
                    timestamp=row["timestamp"],
                    sequence_id=row["sequence_id"],
                    event_type=EventType.HEDGE_FILL,
                    order_id=row["order_id"],
                    currency_pair=row["currency_pair"],
                    side=Side[row["side"]],
                    notional=Decimal(row["notional"]),
                    fill_price=Decimal(row["fill_price"]),
                    slippage=Decimal(row.get("slippage", "0")),
                )
            elif event_type == EventType.CLOCK_TICK:
                event = ClockTickEvent(
                    timestamp=row["timestamp"],
                    sequence_id=row["sequence_id"],
                    event_type=EventType.CLOCK_TICK,
                    tick_label=row["tick_label"],
                )
            else:
                raise ValueError(f"Unknown event type: {event_type}")

            events.append(event)

        except Exception as e:
            logger.error(
                "failed_to_parse_event",
                row=row,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    logger.info("events_loaded", count=len(events), event_type=event_type.value)
    return events


def load_and_merge_events(event_files: Dict[EventType, Path]) -> List[BaseEvent]:
    """
    Load events from multiple files and merge into single sorted list.
    
    Args:
        event_files: Mapping of event types to file paths
    
    Returns:
        Sorted list of all events
    """
    all_events: List[BaseEvent] = []

    for event_type, file_path in event_files.items():
        if file_path.exists():
            events = load_events_from_parquet(file_path, event_type)
            all_events.extend(events)
        else:
            logger.warning("event_file_not_found", event_type=event_type.value, file_path=str(file_path))

    # Sort events deterministically
    all_events.sort()  # Uses BaseEvent.__lt__ (timestamp, sequence_id)

    logger.info("events_merged_and_sorted", total_count=len(all_events))
    return all_events


def write_output_records_jsonl(records: List[OutputRecord], output_path: Path) -> None:
    """
    Write output records to JSONL file (append-only log).
    
    Args:
        records: List of output records
        output_path: Path to output file
    """
    logger.info("writing_output_records", path=str(output_path), count=len(records))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        for record in records:
            line = {
                "timestamp": record.timestamp.isoformat(),
                "record_type": record.record_type,
                "data": record.data,
            }
            f.write(json.dumps(line) + "\n")

    logger.info("output_records_written", path=str(output_path))


def write_snapshots_parquet(records: List[OutputRecord], output_path: Path) -> None:
    """
    Write clock tick snapshots to Parquet (for analytics).
    
    Only includes clock_tick records.
    
    Args:
        records: List of output records
        output_path: Path to output file
    """
    # Filter to clock tick records only
    snapshots = [r for r in records if r.record_type == "clock_tick"]

    if not snapshots:
        logger.warning("no_snapshots_to_write")
        return

    logger.info("writing_snapshots", path=str(output_path), count=len(snapshots))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to Arrow table
    data = {
        "timestamp": [s.timestamp for s in snapshots],
        "tick_label": [s.data["tick_label"] for s in snapshots],
        "event_count": [s.data["event_count"] for s in snapshots],
        "reporting_currency": [s.data["reporting_currency"] for s in snapshots],
        "total_equity_reporting": [s.data["total_equity_reporting"] for s in snapshots],
        "cash_balances": [json.dumps(s.data["cash_balances"]) for s in snapshots],
        "positions": [json.dumps(s.data["positions"]) for s in snapshots],
        "exposures": [json.dumps(s.data["exposures"]) for s in snapshots],
    }

    table = pa.table(data)
    pq.write_table(table, output_path)

    logger.info("snapshots_written", path=str(output_path))


def write_state_snapshot(state: Any, output_path: Path) -> None:
    """
    Write final state to JSON file.
    
    Args:
        state: Engine state (must have to_dict method)
        output_path: Path to output file
    """
    logger.info("writing_state_snapshot", path=str(output_path))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(state.to_dict(), f, indent=2)

    logger.info("state_snapshot_written", path=str(output_path))
