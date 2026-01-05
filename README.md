# eFX Lab - Deterministic FX Simulation Engine

A production-grade, deterministic event-driven simulation engine for FX desk P&L and risk calculation.

## Overview

eFX Lab processes events (client trades, market updates, hedges, config changes) in strict deterministic order to compute:
- Cash balances by currency
- FX positions and exposures
- P&L and risk metrics
- Time-series snapshots for analytics

**Key Features:**
- ✅ **Deterministic**: Byte-identical outputs on every run with same inputs
- ✅ **Fast**: In-memory processing, optimized for millions of events
- ✅ **Correct**: Decimal arithmetic, immutable state, pure functions
- ✅ **Observable**: Structured JSON logging, Parquet outputs
- ✅ **Testable**: 100% pure handler functions, comprehensive test suite
- ✅ **Extensible**: Modular architecture, easy to add new event types

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI Entry Point                         │
│              (config loading, orchestration)                 │
└────────────────────┬────────────────────────────────────────┘
                     │
         ┌───────────▼──────────┐
         │   EventStreamLoader  │  (Parquet → Event objects)
         │  - Deterministic     │
         │  - Sorted by time    │
         └───────────┬──────────┘
                     │
         ┌───────────▼──────────────────────────────────────┐
         │          EventProcessor                          │
         │  - Dispatches to handlers                        │
         │  - Maintains strict ordering                     │
         │  - Drives state transitions                      │
         └───┬───────┬────────┬────────┬─────────┬─────────┘
             │       │        │        │         │
    ┌────────▼──┐ ┌─▼──────┐ ┌▼──────┐ ┌▼──────┐ ┌▼─────────┐
    │ClientTrade│ │Market  │ │Hedge  │ │Config │ │ClockTick │
    │ Handler   │ │Update  │ │Handler│ │Handler│ │Handler   │
    └────────┬──┘ └─┬──────┘ └┬──────┘ └┬──────┘ └┬─────────┘
             │      │         │         │         │
             └──────┴─────────┴─────────┴─────────┘
                              │
                    ┌─────────▼──────────┐
                    │   EngineState      │
                    │ - Cash balances    │
                    │ - Positions        │
                    │ - Exposures        │
                    │ - Market cache     │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Output Writers    │
                    │ - Audit log (JSONL)│
                    │ - Snapshots (Parquet)│
                    │ - State (JSON)     │
                    └────────────────────┘
```

### Core Modules

- **`events.py`**: Immutable event dataclasses with validation
- **`state.py`**: Immutable state model with accounting primitives
- **`handlers.py`**: Pure functions for state transitions
- **`processor.py`**: Event loop with deterministic ordering
- **`converter.py`**: Currency conversion using market rates- **`lot.py`**: Lot tracking data structures (FIFO matching)
- **`lot_manager.py`**: Multi-pair lot orchestration
- **`decomposition.py`**: Cross-pair trade decomposition to direct pairs- **`io_layer.py`**: Parquet/JSONL readers and writers
- **`logging_config.py`**: Structured logging setup
- **`main.py`**: CLI interface

---

## Installation

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Using uv (recommended)

```powershell
# Install uv if not already installed
# See: https://github.com/astral-sh/uv#installation

# Navigate to project directory
cd c:\Users\jgehu\QUANT\Projects\efxlab

# Create virtual environment and install dependencies
uv sync

# Activate virtual environment
.venv\Scripts\activate
```

### Using pip

```powershell
cd c:\Users\jgehu\QUANT\Projects\efxlab

# Create virtual environment
python -m venv .venv

# Activate
.venv\Scripts\activate

# Install dependencies
pip install -e .

# Install dev dependencies
pip install -e ".[dev]"
```

---

## Quick Start

### 1. Generate Sample Data

```powershell
python -m efxlab.main generate-sample-data --num-trades 100 --num-ticks 1000
```

This creates:
- `examples/data/market_updates.parquet` - Market tick data
- `examples/data/client_trades.parquet` - Client trades
- `examples/data/clock_ticks.parquet` - Periodic snapshots

### 2. Run Simulation

```powershell
python -m efxlab.main run --config config/default.yaml
```

### 3. Check Outputs

```powershell
# View final state
cat outputs/final_state.json

# View audit log (JSONL)
cat outputs/audit_log.jsonl

# Analyze snapshots with DuckDB
duckdb -c "SELECT * FROM 'outputs/snapshots.parquet'"
```

---

## Configuration

Configuration is in YAML format. See `config/default.yaml`:

```yaml
# Reporting currency for P&L calculation
reporting_currency: USD

# Lot tracking configuration (optional)
lot_tracking:
  enabled: true
  matching_rule: FIFO  # Future: LIFO, SpecificID
  
  # Risk pairs: Direct FX pairs where lots are tracked
  risk_pairs:
    - EUR/USD
    - GBP/USD
    - AUD/USD
    - JPY/USD
    - CHF/USD
  
  # Trade pairs: Pairs clients can trade (includes crosses)
  trade_pairs:
    - EUR/USD
    - GBP/USD
    - EUR/GBP  # Cross - decomposed into EUR/USD + GBP/USD
    - EUR/JPY
    - GBP/JPY
  
  # Hedge pairs: Pairs available for hedging
  hedge_pairs:
    - EUR/USD
    - GBP/USD

# Input event files
inputs:
  directory: examples/data
  files:
    market_update: market_updates.parquet
    client_trade: client_trades.parquet
    clock_tick: clock_ticks.parquet

# Output files
outputs:
  directory: outputs
  audit_log: audit_log.jsonl
  snapshots: snapshots.parquet
  final_state: final_state.json
```

---

## Lot Tracking System

### Overview

The lot tracking system provides **trade-level attribution** by tracking individual lots (positions) through their lifecycle: creation, matching (netting), and closure. This enables:

- **Internalization Analysis**: Which client trades offset each other?
- **Open/Hold/Close Attribution**: P&L breakdown by lot age and holding period
- **Cross-Pair Decomposition**: EUR/GBP trades automatically decompose into EUR/USD + GBP/USD legs
- **FIFO Matching**: First-in-first-out matching for deterministic attribution

### Key Concepts

**Lot**: A single-sided position with:
- Currency pair (e.g., EUR/USD)
- Side (BUY or SELL from desk perspective)
- Quantity (in base currency, always positive)
- Entry price and timestamp
- Unique ID for tracking

**Risk Pairs**: Direct FX pairs (base/USD) where lots are tracked. Cross pairs are decomposed into risk pairs.

**Trade Pairs**: Pairs clients can trade. May include crosses (EUR/GBP, EUR/JPY) which decompose into multiple risk pairs.

**FIFO Matching**: When offsetting trade arrives, matches oldest lots first. Lots are fully or partially closed.

### Architecture

```
ClientTradeEvent (EUR/GBP BUY)
        ↓
TradeDecomposer.decompose()
        ↓
[Leg(EUR/USD, BUY, 100k), Leg(GBP/USD, SELL, 80k)]
        ↓
For each leg:
  • Check if reduces existing position
  • If yes: match against opposite lots (FIFO)
  • If no: create new lot
        ↓
LotManager.match_lots() or .add_lot()
        ↓
Output: lot_match or lot_created records
```

### Configuration

```yaml
lot_tracking:
  enabled: true                # Toggle lot tracking on/off
  matching_rule: FIFO          # Matching strategy (only FIFO currently)
  
  risk_pairs:                  # Direct pairs for lot tracking
    - EUR/USD
    - GBP/USD
    - JPY/USD
  
  trade_pairs:                 # Pairs clients can trade
    - EUR/USD
    - GBP/USD
    - EUR/GBP                  # Cross - decomposes
    - EUR/JPY                  # Cross - decomposes
  
  hedge_pairs:                 # Pairs for hedging
    - EUR/USD
    - GBP/USD
```

### Output Records

Lot tracking emits additional record types to audit log:

**lot_created**: New lot opened
```json
{
  "timestamp": "2025-01-01T10:00:00Z",
  "record_type": "lot_created",
  "data": {
    "lot_id": "LOT_000001",
    "currency_pair": "EUR/USD",
    "side": "BUY",
    "quantity": "100000",
    "entry_price": "1.1000",
    "entry_time": "2025-01-01T10:00:00Z"
  }
}
```

**lot_match**: Lots matched and closed
```json
{
  "timestamp": "2025-01-01T10:05:00Z",
  "record_type": "lot_match",
  "data": {
    "matched_lot_id": "LOT_000001",
    "offsetting_side": "SELL",
    "matched_quantity": "100000",
    "realized_pnl": "500.00",
    "currency_pair": "EUR/USD"
  }
}
```

**lot_tracking_error**: Error during lot processing
```json
{
  "timestamp": "2025-01-01T10:10:00Z",
  "record_type": "lot_tracking_error",
  "data": {
    "error": "No market rate for GBP/USD",
    "trade_id": "TRADE_123"
  }
}
```

### Snapshot Metrics

Clock tick snapshots include lot tracking statistics:

```json
{
  "tick_label": "EOD",
  "lot_tracking_stats": {
    "total_open_lots": 5,
    "total_closed_lots": 12,
    "total_unrealized_pnl": "1250.50",
    "net_positions": {
      "EUR/USD": "200000",
      "GBP/USD": "-150000"
    }
  }
}
```

### Usage Examples

#### Enable Lot Tracking

1. Set `lot_tracking.enabled: true` in config
2. Define `risk_pairs`, `trade_pairs`, `hedge_pairs`
3. Run simulation normally

#### Query Lot Matches

```python
import json

matches = []
with open('outputs/audit_log.jsonl') as f:
    for line in f:
        record = json.loads(line)
        if record['record_type'] == 'lot_match':
            matches.append(record['data'])

print(f"Total matches: {len(matches)}")
print(f"Total realized P&L: {sum(float(m['realized_pnl']) for m in matches)}")
```

#### Analyze Lot Lifecycle

```python
import json
from collections import defaultdict

lots = defaultdict(dict)

with open('outputs/audit_log.jsonl') as f:
    for line in f:
        record = json.loads(line)
        
        if record['record_type'] == 'lot_created':
            lot_id = record['data']['lot_id']
            lots[lot_id]['created'] = record['timestamp']
            lots[lot_id]['quantity'] = record['data']['quantity']
        
        elif record['record_type'] == 'lot_match':
            lot_id = record['data']['matched_lot_id']
            lots[lot_id]['matched'] = record['timestamp']
            lots[lot_id]['pnl'] = record['data']['realized_pnl']

# Find longest-held lot
import datetime
for lot_id, data in lots.items():
    if 'matched' in data:
        created = datetime.datetime.fromisoformat(data['created'])
        matched = datetime.datetime.fromisoformat(data['matched'])
        data['hold_time'] = (matched - created).total_seconds()

longest = max(lots.items(), key=lambda x: x[1].get('hold_time', 0))
print(f"Longest held: {longest[0]} for {longest[1]['hold_time']/3600:.1f} hours")
```

### Disabling Lot Tracking

Set `lot_tracking.enabled: false` in config. The engine runs normally without lot tracking overhead.

### Performance Considerations

- **Memory**: ~100 bytes per open lot
- **CPU**: ~10μs per lot match operation
- **Impact**: Adds ~20% overhead to trade processing

For simulations with millions of trades and long holding periods, monitor memory usage.

---

## Event Types

### ClientTradeEvent

Represents a client trade execution.

**Fields:**
- `currency_pair`: e.g., "EUR/USD"
- `side`: BUY or SELL (client perspective)
- `notional`: Amount in base currency (Decimal)
- `price`: Quote currency per unit base (Decimal)
- `client_id`, `trade_id`: Identifiers

**Accounting (desk perspective):**
- Client BUY: Desk sells base, receives quote → negative base, positive quote
- Client SELL: Desk buys base, pays quote → positive base, negative quote

### MarketUpdateEvent

Market data update with bid/ask spreads.

**Fields:**
- `currency_pair`: e.g., "EUR/USD"
- `bid`, `ask`, `mid`: Prices (Decimal)

**Usage:**
- Mark-to-market valuation
- Currency conversion
- Hedge execution simulation

### HedgeOrderEvent / HedgeFillEvent

Hedge order placement and execution.

**Order Fields:**
- `order_id`, `currency_pair`, `side`, `notional`, `limit_price`

**Fill Fields:**
- Same as order, plus `fill_price` and `slippage`

### ConfigUpdateEvent

Dynamic configuration changes.

**Fields:**
- `config_key`: e.g., "reporting_currency"
- `config_value`: New value

### ClockTickEvent

Periodic snapshots and metric calculations.

**Fields:**
- `tick_label`: e.g., "EOD", "T+1H"

**Triggers:**
- State snapshot
- P&L calculation
- Exposure updates

---

## Input Data Format

All input files are Parquet with specific schemas.

### Client Trades Schema

```
timestamp: timestamp[us, tz=UTC]
sequence_id: int64
currency_pair: string
side: string (BUY/SELL)
notional: string (Decimal as string)
price: string
client_id: string
trade_id: string
```

### Market Updates Schema

```
timestamp: timestamp[us, tz=UTC]
sequence_id: int64
currency_pair: string
bid: string
ask: string
mid: string
```

### Clock Ticks Schema

```
timestamp: timestamp[us, tz=UTC]
sequence_id: int64
tick_label: string
```

**Important:** All financial amounts use Decimal (stored as strings in Parquet) for exact arithmetic.

---

## Output Formats

### 1. Audit Log (JSONL)

Append-only log of all events and state transitions.

**Location:** `outputs/audit_log.jsonl`

**Format:**
```json
{"timestamp": "2025-01-01T10:00:00+00:00", "record_type": "client_trade", "data": {...}}
{"timestamp": "2025-01-01T10:00:01+00:00", "record_type": "market_update", "data": {...}}
```

### 2. Snapshots (Parquet)

Periodic state snapshots from clock ticks, optimized for analytics.

**Location:** `outputs/snapshots.parquet`

**Columns:**
- `timestamp`, `tick_label`, `event_count`
- `cash_balances` (JSON), `positions` (JSON), `exposures` (JSON)
- `total_equity_reporting`, `reporting_currency`

### 3. Final State (JSON)

Complete final state for validation.

**Location:** `outputs/final_state.json`

**Structure:**
```json
{
  "cash_balances": {"USD": "1500000", "EUR": "-500000"},
  "positions": {"EUR/USD": "-500000"},
  "exposures": {"EUR": "-500000", "USD": "1050000"},
  "reporting_currency": "USD",
  "event_count": 1234
}
```

---

## Testing

### Run All Tests

```powershell
pytest
```

### Run With Coverage

```powershell
pytest --cov=efxlab --cov-report=html
```

### Run Specific Test

```powershell
pytest tests/test_integration.py::test_deterministic_rerun -v
```

### Test Structure

- `test_events.py` - Event validation and ordering
- `test_state.py` - State model and accounting
- `test_converter.py` - Currency conversion logic
- `test_handlers.py` - Handler correctness
- `test_processor.py` - Event processing
- `test_integration.py` - End-to-end scenarios

---

## Determinism Guarantees

The engine guarantees byte-identical outputs for the same inputs:

1. **Global Event Sorting:** All events sorted by `(timestamp, sequence_id)` before processing
2. **Stable Sort:** Python's Timsort is stable
3. **Decimal Arithmetic:** All financial calculations use `Decimal` (no floats)
4. **Immutable State:** State transitions are pure functions
5. **No External Randomness:** No `random`, no `time.time()`, no system state
6. **Deterministic I/O:** Parquet/JSON output order is stable

**Verification:**
```python
# Run twice, compare outputs
run1_state = simulate(events)
run2_state = simulate(events)
assert run1_state == run2_state  # Byte-identical
```

---

## Performance

### Design Targets

- **Throughput:** Process 1M events in < 10 seconds
- **Memory:** < 1GB for 1M events
- **Latency:** < 1μs per event (amortized)

### Optimizations

1. **In-Memory Processing:** All events loaded and sorted once
2. **Decimal Pooling:** Reuse Decimal objects where possible
3. **Minimal Copying:** Immutable state uses structural sharing
4. **Batch I/O:** Write outputs once at end
5. **PyArrow:** Efficient Parquet reading

### Scaling Strategy

For > 10M events or memory constraints:
1. Implement windowed processing with state checkpoints
2. Use DuckDB for out-of-core sorting
3. Parallelize across time windows
4. Stream outputs incrementally

---

## Validation & Debugging

### Validate Output Correctness

```powershell
# Check accounting invariants
duckdb -c "
SELECT 
  tick_label,
  SUM(cash_balance) as total_cash,
  SUM(position) as total_position
FROM read_parquet('outputs/snapshots.parquet')
GROUP BY tick_label
"
```

### Determinism Check

```powershell
# Run twice
python -m efxlab.main run --config config/default.yaml
mv outputs/final_state.json outputs/run1.json

python -m efxlab.main run --config config/default.yaml
mv outputs/final_state.json outputs/run2.json

# Compare (should be identical)
diff outputs/run1.json outputs/run2.json
```

### Debug Event Processing

Set log level to DEBUG:

```powershell
python -m efxlab.main run --config config/default.yaml --log-level DEBUG
```

Logs include:
- Event processing details
- State transitions
- Handler dispatch
- Conversion calculations

---

## Common Failure Modes

### 1. Missing Market Data

**Symptom:** `ConversionError: No market rate available`

**Cause:** Currency conversion attempted before market update received

**Fix:** Ensure market updates are provided before trades requiring conversion

### 2. Accounting Imbalance

**Symptom:** Cash/position mismatches in output

**Cause:** Event ordering issue or handler bug

**Debug:**
```powershell
# Check event ordering
duckdb -c "SELECT timestamp, sequence_id, record_type FROM read_json('outputs/audit_log.jsonl')"
```

### 3. Non-Deterministic Results

**Symptom:** Different outputs on repeated runs

**Cause:** Missing sequence IDs or timestamp precision issues

**Fix:** Ensure all events have unique `(timestamp, sequence_id)` tuples

### 4. Memory Exhaustion

**Symptom:** Process killed or slow performance

**Cause:** Too many events for in-memory processing

**Mitigation:** Reduce event count or implement windowed processing (future work)

---

## Extending the Engine

### Adding New Event Types

1. **Define Event:** Add to `events.py`
   ```python
   @dataclass(frozen=True, order=True)
   class MyNewEvent(BaseEvent):
       my_field: str = field(compare=False)
   ```

2. **Create Handler:** Add to `handlers.py`
   ```python
   def handle_my_new_event(state: EngineState, event: MyNewEvent) -> tuple[EngineState, List[OutputRecord]]:
       # Pure function: transform state
       new_state = state.update_cash("USD", Decimal("100"))
       output = OutputRecord(timestamp=event.timestamp, record_type="my_event", data={})
       return new_state, [output]
   ```

3. **Register Handler:** Update `processor.py` dispatch
   ```python
   elif isinstance(event, MyNewEvent):
       new_state, outputs = handle_my_new_event(self.state, event)
   ```

4. **Add Tests:** Create test in `tests/test_handlers.py`

### Adding New State Fields

1. **Update State Model:** Modify `EngineState` in `state.py`
2. **Add Accessor Methods:** `get_*`, `update_*`
3. **Update Serialization:** Modify `to_dict()`
4. **Update Tests**

---

## Development Workflow

### Code Style

```powershell
# Format
black efxlab tests

# Lint
ruff check efxlab tests

# Type check
mypy efxlab
```

### Pre-Commit Checklist

- [ ] All tests pass (`pytest`)
- [ ] Code formatted (`black`)
- [ ] No lint errors (`ruff`)
- [ ] Type hints valid (`mypy`)
- [ ] Determinism test passes
- [ ] Documentation updated

---

## Project Structure

```
efxlab/
├── efxlab/              # Source code
│   ├── __init__.py
│   ├── events.py        # Event schemas
│   ├── state.py         # State model
│   ├── handlers.py      # Event handlers
│   ├── processor.py     # Event processor
│   ├── converter.py     # Currency converter
│   ├── lot.py           # Lot data structures
│   ├── lot_manager.py   # Lot orchestration
│   ├── decomposition.py # Cross-pair decomposition
│   ├── io_layer.py      # I/O operations
│   ├── logging_config.py # Logging setup
│   └── main.py          # CLI entry point
├── tests/               # Test suite
│   ├── test_events.py
│   ├── test_state.py
│   ├── test_converter.py
│   ├── test_handlers.py
│   ├── test_processor.py
│   ├── test_lot_tracking.py      # 23 lot tracking tests
│   ├── test_lot_integration.py    # 5 integration tests
│   └── test_integration.py
├── config/              # Configuration files
│   └── default.yaml
├── examples/            # Example data and scripts
│   └── data/            # Generated sample data
├── outputs/             # Simulation outputs (gitignored)
├── pyproject.toml       # Project configuration
├── README.md            # This file
└── .gitignore
```

---

## License

Proprietary - All Rights Reserved

---

## Support

For issues, questions, or contributions, contact the eFX Lab team.

---

## Appendix: Design Decisions

### Why Decimal Instead of Float?

Financial calculations require exact arithmetic. Floats have rounding errors:
```python
>>> 0.1 + 0.2
0.30000000000000004  # ❌

>>> Decimal("0.1") + Decimal("0.2")
Decimal('0.3')  # ✅
```

### Why Immutable State?

Immutability ensures:
- **Determinism:** No hidden mutations
- **Debugging:** Time-travel to any state
- **Testing:** Easy to reason about
- **Parallelism:** Safe for future optimizations

### Why Pure Handler Functions?

Pure functions `(State, Event) -> (State, Outputs)`:
- **Testability:** No mocks needed
- **Composability:** Easy to chain
- **Parallelism:** Can run in parallel (future)
- **Reasoning:** Input → Output, no surprises

### Why Parquet for I/O?

Parquet offers:
- **Columnar:** Fast analytics queries
- **Compression:** Small file sizes
- **Schema:** Type-safe with metadata
- **Ecosystem:** Works with DuckDB, Pandas, Polars

### Why In-Memory Processing?

For MVP scale (millions of events):
- **Simple:** No distributed coordination
- **Fast:** No I/O bottleneck
- **Correct:** Easier to guarantee determinism

Future: Windowed processing for larger scales.

---

**Built with ❤️ for deterministic FX simulation**
