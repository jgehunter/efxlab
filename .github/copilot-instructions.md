# eFX Lab - AI Coding Agent Instructions

## Project Overview
Deterministic FX simulation engine for P&L and risk calculation. Event-driven architecture with **absolute determinism** as the core requirement—byte-identical outputs on every run.

**Key Features:**
- Event-driven simulation with strict deterministic ordering
- Immutable state with pure handler functions
- Decimal-based financial arithmetic (no floats)
- **Lot tracking system**: FIFO matching, cross-pair decomposition, internalization analysis
- Parquet I/O for analytics integration

## Critical Architecture Principles

### 1. Determinism is Non-Negotiable
- **All events** sorted by `(timestamp, sequence_id)` before processing
- **Never use `float`** for financial data—only `Decimal` (from `decimal` module)
- **Immutable state**: All state transitions return new `EngineState` instances (use `replace()` from dataclasses)
- **Pure handler functions**: `(State, Event) -> (State, List[OutputRecord])`—no side effects, no mutations
- **No randomness**: No `random`, `time.time()`, or system state during processing

### 2. Event System Architecture
Event flow: `Parquet files → sorted events → EventProcessor → handlers → immutable state → outputs`

**Key files:**
- `efxlab/events.py` - Event schemas (frozen dataclasses with validation)
- `efxlab/handlers.py` - Pure handler functions (one per event type)
- `efxlab/processor.py` - Event loop and dispatch
- `efxlab/state.py` - Immutable state model
- `efxlab/lot.py` - Lot tracking data structures (Lot, LotQueue)
- `efxlab/lot_manager.py` - Multi-pair lot orchestration
- `efxlab/decomposition.py` - Cross-pair trade decomposition

**Adding a new event type:**
1. Define in `events.py` as frozen dataclass inheriting `BaseEvent`
2. Add handler function in `handlers.py`: `def handle_my_event(state: EngineState, event: MyEvent) -> tuple[EngineState, List[OutputRecord]]`
3. Update dispatch in `processor.py` (add elif branch)
4. Add Parquet schema in `io_layer.py` if loading from files

### 3. Financial Arithmetic Rules
```python
# ✅ ALWAYS use Decimal for money
from decimal import Decimal
notional = Decimal("1000000")
price = Decimal("1.1000")
amount = notional * price  # Still Decimal

# ❌ NEVER use float
amount = 1000000.0 * 1.1  # Will fail determinism tests
```

### 4. State Management Pattern
```python
# ✅ Correct: Return new state
new_state = state.update_cash("USD", Decimal("1000"))
new_state = new_state.update_position("EUR/USD", Decimal("500000"))
return new_state, outputs

# ❌ Wrong: Don't mutate
state.cash_balances["USD"] = ...  # frozen dataclass will error
```

## Developer Workflows

### Setup & Dependencies
```powershell
uv sync              # Install all dependencies (preferred)
.venv\Scripts\activate  # Windows activation
pytest               # Run all tests (must pass before commits)
```

### Testing Requirements
- **All 38 tests must pass** before committing
- Run `pytest` after any code change
- Integration test (`test_integration.py::test_deterministic_rerun`) verifies determinism
- For financial logic, add tests with known Decimal inputs/outputs

### Code Style (Enforced)
- Line length: 100 characters (Black formatter)
- Type hints required on all functions (mypy strict mode)
- Imports: sorted with ruff
- Run: `black efxlab tests && ruff check efxlab tests`

### Running Simulations
```powershell
# Generate test data
python -m efxlab.main generate-sample-data --num-trades 100 --num-ticks 1000

# Run simulation
python -m efxlab.main run --config config/default.yaml

# Verify determinism (critical after changes)
python -m efxlab.main run --config config/default.yaml
cp outputs\final_state.json outputs\run1.json
python -m efxlab.main run --config config/default.yaml
fc outputs\run1.json outputs\final_state.json  # Must be identical
```

## Project-Specific Conventions

### Event Ordering
Every event needs both `timestamp` (datetime with timezone) and `sequence_id` (int). The `sequence_id` breaks ties when events share the same timestamp. Events are sorted globally before processing—never process unsorted.

### FX Trade Accounting (Desk Perspective)
```python
# Client BUY EUR/USD: desk SELLS EUR, RECEIVES USD
# Client buys 1M EUR at 1.1000
# Desk: -1M EUR, +1.1M USD, position: -1M EUR/USD

# Client SELL EUR/USD: desk BUYS EUR, PAYS USD  
# Client sells 1M EUR at 1.1000
# Desk: +1M EUR, -1.1M USD, position: +1M EUR/USD
```

### Input/Output Formats
- **Input**: Parquet files with specific schemas (see `io_layer.py`)
  - Financial amounts stored as **strings** (for Decimal)
  - Timestamps: `timestamp[us, tz=UTC]`
- **Outputs**: 
  - Audit log: JSONL (append-only)
  - Snapshots: Parquet (for DuckDB analytics)
  - Final state: JSON

### Handler Pattern
All handlers follow this signature:
```python
def handle_event_type(
    state: EngineState, 
    event: EventType
) -> tuple[EngineState, List[OutputRecord]]:
    # 1. Transform state (pure function)
    new_state = state.update_cash(...)
    
    # 2. Create output record
    output = OutputRecord(
        timestamp=event.timestamp,
        record_type="event_type",
        data={...}
    )
    
    # 3. Return new state + outputs
    return new_state, [output]
```

## Common Pitfalls to Avoid

1. **Float contamination**: Never convert Decimal to float and back—precision loss breaks determinism
2. **Mutation**: State is immutable—use `replace()` or `.update_*()` methods
3. **Unsorted events**: Always verify events are sorted before processing
4. **Missing sequence IDs**: Every event must have unique `(timestamp, sequence_id)`
5. **Side effects in handlers**: Handlers must be pure—no logging, no I/O, just return new state
6. **Lot matching side confusion**: `match_lots()` takes the offsetting side and finds opposite lots internally—don't invert twice
7. **Cross-pair market rates**: When decomposing EUR/GBP, ensure EUR/USD and GBP/USD rates are available
8. **Partial lot matching**: Partially matched lots reduce quantity but stay open—only fully matched lots close

## Key Files to Reference
- `tests/test_integration.py` - Examples of correct event creation and determinism testing
- `tests/test_lot_integration.py` - Lot tracking integration tests with cross pairs
- `tests/test_lot_tracking.py` - 23 unit tests for lot system components
- `efxlab/state.py` - `apply_trade()` shows canonical FX accounting logic
- `efxlab/handlers.py` - `_handle_lot_tracking()` shows lot integration pattern
- `README.md` (Lot Tracking section) - Architecture and usage examples
- `README.md` (Appendix) - Design decisions: why Decimal, why immutable, why pure functions
- `CHECKLIST.md` - Review checklist before merging (run determinism test!)
- `RUNBOOK.md` (Lot Tracking Operations) - Operational procedures for lot tracking

## Performance Considerations
- In-memory processing: suitable for <10M events
- Parquet I/O is fast—don't optimize prematurely
- Decimal is slower than float but correctness > speed
- Profile before optimizing: `python -m cProfile -o profile.stats -m efxlab.main run ...`

---
**When uncertain**: Check existing tests for patterns. The test suite (38 tests) documents expected behavior.
