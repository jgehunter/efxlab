"""
CLI entry point for the eFX Lab simulation engine.
"""

from pathlib import Path
from typing import Dict

import click
import structlog
import yaml

from efxlab.events import EventType
from efxlab.io_layer import (
    load_and_merge_events,
    write_output_records_jsonl,
    write_snapshots_parquet,
    write_state_snapshot,
)
from efxlab.logging_config import configure_logging
from efxlab.lot_manager import LotConfig, LotManager
from efxlab.processor import EventProcessor
from efxlab.state import EngineState

logger = structlog.get_logger()


@click.group()
def cli() -> None:
    """eFX Lab - Deterministic FX Simulation Engine"""
    pass


@cli.command()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to configuration YAML file",
)
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Logging level",
)
def run(config: Path, log_level: str) -> None:
    """Run simulation with given configuration."""
    # Configure logging
    configure_logging(log_level=log_level)

    logger.info("simulation_started", config_file=str(config))

    # Load configuration
    with open(config) as f:
        config_data = yaml.safe_load(f)

    # Parse input files
    input_dir = Path(config_data["inputs"]["directory"])
    event_files: Dict[EventType, Path] = {}

    for event_type_str, filename in config_data["inputs"]["files"].items():
        event_type = EventType[event_type_str.upper()]
        event_files[event_type] = input_dir / filename

    # Load and merge events
    events = load_and_merge_events(event_files)

    if not events:
        logger.error("no_events_loaded")
        return

    # Initialize state
    reporting_currency = config_data.get("reporting_currency", "USD")

    # Initialize lot tracking if enabled
    lot_manager = None
    if config_data.get("lot_tracking", {}).get("enabled", False):
        lot_config_data = config_data["lot_tracking"]
        lot_config = LotConfig(
            enabled=lot_config_data.get("enabled", True),
            matching_rule=lot_config_data.get("matching_rule", "FIFO"),
            risk_pairs=lot_config_data.get("risk_pairs", []),
            trade_pairs=lot_config_data.get("trade_pairs", []),
            hedge_pairs=lot_config_data.get("hedge_pairs", []),
            reporting_currency=reporting_currency,
        )
        lot_manager = LotManager(lot_config)
        logger.info(
            "lot_tracking_enabled",
            risk_pairs=lot_config.risk_pairs,
            matching_rule=lot_config.matching_rule,
        )

    initial_state = EngineState(
        reporting_currency=reporting_currency,
        lot_manager=lot_manager,
    )

    # Process events
    processor = EventProcessor(initial_state)
    final_state = processor.process_events(events)

    # Write outputs
    output_dir = Path(config_data["outputs"]["directory"])
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write audit log (JSONL)
    audit_log_path = output_dir / config_data["outputs"]["audit_log"]
    write_output_records_jsonl(processor.get_output_records(), audit_log_path)

    # Write snapshots (Parquet)
    snapshots_path = output_dir / config_data["outputs"]["snapshots"]
    write_snapshots_parquet(processor.get_output_records(), snapshots_path)

    # Write final state (JSON)
    state_path = output_dir / config_data["outputs"]["final_state"]
    write_state_snapshot(final_state, state_path)

    logger.info(
        "simulation_completed",
        events_processed=final_state.event_count,
        final_state_path=str(state_path),
    )

    # Print summary to stdout
    click.echo("\n=== Simulation Summary ===")
    click.echo(f"Events processed: {final_state.event_count}")
    click.echo(f"Reporting currency: {final_state.reporting_currency}")
    click.echo(f"\nCash balances:")
    for currency, balance in sorted(final_state.cash_balances.items()):
        click.echo(f"  {currency}: {balance}")
    click.echo(f"\nPositions:")
    for pair, position in sorted(final_state.positions.items()):
        click.echo(f"  {pair}: {position}")

    # Lot tracking summary
    if final_state.lot_manager:
        stats = final_state.lot_manager.get_lot_count_stats()
        click.echo(f"\nLot Tracking:")
        click.echo(f"  Total open lots: {stats['total_open_lots']}")
        click.echo(f"  Total closed lots: {stats['total_closed_lots']}")
        for pair, counts in stats["queues"].items():
            if counts["open"] > 0 or counts["closed"] > 0:
                click.echo(f"  {pair}: {counts['open']} open, {counts['closed']} closed")

    click.echo(f"\nOutputs written to: {output_dir}")
    click.echo(f"  - Audit log: {audit_log_path.name}")
    click.echo(f"  - Snapshots: {snapshots_path.name}")
    click.echo(f"  - Final state: {state_path.name}")


@cli.command()
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    default="examples/data",
    help="Output directory for sample data",
)
@click.option(
    "--num-trades",
    default=100,
    help="Number of client trades to generate",
)
@click.option(
    "--num-ticks",
    default=1000,
    help="Number of market ticks to generate",
)
def generate_sample_data(output_dir: Path, num_trades: int, num_ticks: int) -> None:
    """Generate sample input data for testing."""
    import random
    from datetime import timedelta
    from decimal import Decimal

    import pyarrow as pa
    import pyarrow.parquet as pq

    configure_logging(log_level="INFO")
    logger.info("generating_sample_data", output_dir=str(output_dir))

    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate market updates
    from datetime import datetime, timezone

    base_time = datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    pairs = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"]
    base_rates = {
        "EUR/USD": Decimal("1.1000"),
        "GBP/USD": Decimal("1.2700"),
        "USD/JPY": Decimal("110.00"),
        "AUD/USD": Decimal("0.7300"),
    }

    market_data = {
        "timestamp": [],
        "sequence_id": [],
        "currency_pair": [],
        "bid": [],
        "ask": [],
        "mid": [],
    }

    seq_id = 0
    for i in range(num_ticks):
        timestamp = base_time + timedelta(seconds=i * 10)
        pair = random.choice(pairs)
        base_rate = base_rates[pair]
        spread = base_rate * Decimal("0.0001")  # 1 pip spread
        mid = base_rate * (Decimal("1") + (Decimal(random.gauss(0, 0.001))))
        bid = mid - spread / 2
        ask = mid + spread / 2

        market_data["timestamp"].append(timestamp)
        market_data["sequence_id"].append(seq_id)
        market_data["currency_pair"].append(pair)
        market_data["bid"].append(str(bid))
        market_data["ask"].append(str(ask))
        market_data["mid"].append(str(mid))
        seq_id += 1

    market_table = pa.table(market_data)
    pq.write_table(market_table, output_dir / "market_updates.parquet")
    logger.info("generated_market_updates", count=num_ticks)

    # Generate client trades
    trade_data = {
        "timestamp": [],
        "sequence_id": [],
        "currency_pair": [],
        "side": [],
        "notional": [],
        "price": [],
        "client_id": [],
        "trade_id": [],
    }

    for i in range(num_trades):
        timestamp = base_time + timedelta(seconds=random.randint(0, num_ticks * 10))
        pair = random.choice(pairs)
        side = random.choice(["BUY", "SELL"])
        notional = Decimal(random.randint(100_000, 10_000_000))
        price = base_rates[pair] * (Decimal("1") + Decimal(random.gauss(0, 0.002)))

        trade_data["timestamp"].append(timestamp)
        trade_data["sequence_id"].append(seq_id)
        trade_data["currency_pair"].append(pair)
        trade_data["side"].append(side)
        trade_data["notional"].append(str(notional))
        trade_data["price"].append(str(price))
        trade_data["client_id"].append(f"CLIENT_{random.randint(1, 20)}")
        trade_data["trade_id"].append(f"TRADE_{i+1:06d}")
        seq_id += 1

    trade_table = pa.table(trade_data)
    pq.write_table(trade_table, output_dir / "client_trades.parquet")
    logger.info("generated_client_trades", count=num_trades)

    # Generate clock ticks
    tick_data = {
        "timestamp": [],
        "sequence_id": [],
        "tick_label": [],
    }

    for hour in range(0, 8):
        timestamp = base_time + timedelta(hours=hour)
        tick_data["timestamp"].append(timestamp)
        tick_data["sequence_id"].append(seq_id)
        tick_data["tick_label"].append(f"T+{hour}H")
        seq_id += 1

    tick_table = pa.table(tick_data)
    pq.write_table(tick_table, output_dir / "clock_ticks.parquet")
    logger.info("generated_clock_ticks", count=len(tick_data["timestamp"]))

    click.echo(f"\nSample data generated in: {output_dir}")
    click.echo(f"  - market_updates.parquet ({num_ticks} records)")
    click.echo(f"  - client_trades.parquet ({num_trades} records)")
    click.echo(f"  - clock_ticks.parquet ({len(tick_data['timestamp'])} records)")


if __name__ == "__main__":
    cli()
