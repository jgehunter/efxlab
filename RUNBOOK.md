# eFX Lab - Runbook

## Quick Reference

### Run Simulation
```powershell
# Activate environment
cd c:\Users\jgehu\QUANT\Projects\efxlab
.venv\Scripts\activate

# Run with default config
python -m efxlab.main run --config config/default.yaml

# Run with debug logging
python -m efxlab.main run --config config/default.yaml --log-level DEBUG
```

### Generate Sample Data
```powershell
python -m efxlab.main generate-sample-data --num-trades 100 --num-ticks 1000
```

### Run Tests
```powershell
# All tests
pytest

# With coverage
pytest --cov=efxlab --cov-report=html

# Specific test
pytest tests/test_integration.py::test_deterministic_rerun -v
```

---

## Installation

### 1. Install Dependencies

```powershell
# Using uv (recommended)
uv sync

# Using pip
pip install -e .
pip install -e ".[dev]"
```

### 2. Verify Installation

```powershell
# Run tests
pytest

# Generate sample data
python -m efxlab.main generate-sample-data
```

---

## Configuration

### Config File Structure

```yaml
# config/default.yaml
reporting_currency: USD

inputs:
  directory: examples/data
  files:
    market_update: market_updates.parquet
    client_trade: client_trades.parquet
    clock_tick: clock_ticks.parquet

outputs:
  directory: outputs
  audit_log: audit_log.jsonl
  snapshots: snapshots.parquet
  final_state: final_state.json
```

### Creating Custom Configs

1. Copy `config/default.yaml`
2. Modify paths and parameters
3. Run with: `python -m efxlab.main run --config config/my_config.yaml`

---

## Validating Outputs

### 1. Check Final State

```powershell
# View final state
type outputs\final_state.json

# Verify accounting balance
python -c "import json; data = json.load(open('outputs/final_state.json')); print('EUR balance:', data['cash_balances'].get('EUR', '0'))"
```

### 2. Analyze Audit Log

```powershell
# Count event types
python -c "import json; events = [json.loads(line) for line in open('outputs/audit_log.jsonl')]; from collections import Counter; print(Counter([e['record_type'] for e in events]))"

# View first 5 events
python -c "import json; [print(json.dumps(json.loads(line), indent=2)) for i, line in enumerate(open('outputs/audit_log.jsonl')) if i < 5]"
```

### 3. Query Snapshots with DuckDB

```powershell
# Install DuckDB if needed
uv pip install duckdb

# Query snapshots
python -c "import duckdb; print(duckdb.query('SELECT tick_label, event_count, reporting_currency FROM read_parquet(\"outputs/snapshots.parquet\")').df())"
```

### 4. Verify Determinism

```powershell
# Run twice and compare
python -m efxlab.main run --config config/default.yaml
copy outputs\final_state.json outputs\run1.json

python -m efxlab.main run --config config/default.yaml
copy outputs\final_state.json outputs\run2.json

# Compare (should be identical)
fc outputs\run1.json outputs\run2.json
```

---

## Common Operations

### Creating Input Data

#### From CSV Files

```python
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Read CSV
df = pd.read_csv('trades.csv')

# Convert to proper types
df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
df['notional'] = df['notional'].astype(str)  # Decimal as string
df['price'] = df['price'].astype(str)

# Write to Parquet
table = pa.Table.from_pandas(df)
pq.write_table(table, 'client_trades.parquet')
```

#### Programmatic Generation

```python
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pyarrow as pa
import pyarrow.parquet as pq

# Generate trades
trades = {
    'timestamp': [datetime(2025, 1, 1, 10, 0, i, tzinfo=timezone.utc) for i in range(10)],
    'sequence_id': list(range(10)),
    'currency_pair': ['EUR/USD'] * 10,
    'side': ['BUY', 'SELL'] * 5,
    'notional': ['1000000'] * 10,
    'price': [str(Decimal('1.1000') + Decimal('0.0001') * i) for i in range(10)],
    'client_id': [f'CLIENT_{i%3}' for i in range(10)],
    'trade_id': [f'TRADE_{i:06d}' for i in range(10)],
}

table = pa.table(trades)
pq.write_table(table, 'my_trades.parquet')
```

### Analyzing Results

#### Extract Cash Balance Time Series

```python
import duckdb
import pandas as pd

# Query snapshots
df = duckdb.query("""
    SELECT 
        timestamp,
        tick_label,
        json_extract(cash_balances, '$.USD') as usd_balance,
        json_extract(cash_balances, '$.EUR') as eur_balance
    FROM read_parquet('outputs/snapshots.parquet')
    ORDER BY timestamp
""").df()

print(df)
```

#### Calculate P&L by Client

```python
import json

trades = []
with open('outputs/audit_log.jsonl') as f:
    for line in f:
        record = json.loads(line)
        if record['record_type'] == 'client_trade':
            trades.append(record['data'])

# Group by client
from collections import defaultdict
by_client = defaultdict(list)
for trade in trades:
    by_client[trade['client_id']].append(trade)

for client, client_trades in by_client.items():
    print(f"{client}: {len(client_trades)} trades")
```

---

## Troubleshooting

### Problem: Simulation fails with "No market rate available"

**Cause:** Missing market data for currency conversion

**Solution:**
1. Check that market_updates.parquet includes all needed currency pairs
2. Ensure market updates occur before trades requiring conversion
3. Verify sequence_id ordering is correct

### Problem: Non-deterministic outputs

**Cause:** Missing or duplicate sequence IDs

**Solution:**
```python
import duckdb

# Check for duplicate sequence IDs
duckdb.query("""
    SELECT sequence_id, COUNT(*) as count
    FROM (
        SELECT sequence_id FROM read_parquet('examples/data/market_updates.parquet')
        UNION ALL
        SELECT sequence_id FROM read_parquet('examples/data/client_trades.parquet')
        UNION ALL
        SELECT sequence_id FROM read_parquet('examples/data/clock_ticks.parquet')
    )
    GROUP BY sequence_id
    HAVING count > 1
""").show()
```

### Problem: Memory errors with large datasets

**Cause:** Too many events for in-memory processing

**Solution:**
1. Process data in smaller time windows
2. Reduce event density (e.g., sample market ticks)
3. Consider implementing windowed processing (future enhancement)

### Problem: Slow performance

**Symptoms:** Processing < 10k events/sec

**Debug:**
```powershell
# Profile with cProfile
python -m cProfile -o profile.stats -m efxlab.main run --config config/default.yaml

# View top functions
python -c "import pstats; p = pstats.Stats('profile.stats'); p.sort_stats('cumulative'); p.print_stats(20)"
```

**Common causes:**
- Excessive logging (use INFO instead of DEBUG)
- Many small Decimal operations (batch where possible)
- I/O bottleneck (check disk speed)

### Problem: Test failures

```powershell
# Run with verbose output
pytest -v -s

# Run specific failing test
pytest tests/test_integration.py::test_deterministic_rerun -v

# Check for environment issues
python -c "import sys; print(sys.version); import decimal; print(decimal.Decimal('1.1') + decimal.Decimal('2.2'))"
```

---

## Performance Tuning

### Current Performance Targets

- **Throughput:** ~100k events/sec on modern hardware
- **Memory:** ~1KB per event in memory
- **Latency:** <10μs per event (amortized)

### Optimization Techniques

1. **Batch I/O**
   - Load all data at start, write all at end
   - Use Parquet columnar format

2. **Minimize Allocations**
   - Reuse Decimal objects where safe
   - Immutable state uses structural sharing

3. **Efficient Sorting**
   - Single sort of all events upfront
   - Python's Timsort is fast for partially ordered data

4. **Vectorization (future)**
   - Use DuckDB for bulk calculations
   - Batch state updates

### Monitoring

```python
import time
import structlog

logger = structlog.get_logger()

start = time.perf_counter()
# ... run simulation ...
end = time.perf_counter()

events_per_sec = event_count / (end - start)
logger.info("performance", events_per_sec=events_per_sec, duration=end-start)
```

---

## Maintenance

### Regular Checks

- [ ] All tests pass: `pytest`
- [ ] Code formatted: `black efxlab tests`
- [ ] No lint errors: `ruff check efxlab tests`
- [ ] Determinism verified: run twice, compare outputs
- [ ] Performance acceptable: >10k events/sec

### Updating Dependencies

```powershell
# Update all dependencies
uv sync --upgrade

# Run tests after update
pytest
```

### Adding New Event Types

See README.md "Extending the Engine" section

---

## Backup and Recovery

### Backup Configuration

```powershell
# Backup config and outputs
tar -czf backup_$(date +%Y%m%d).tar.gz config/ outputs/
```

### Disaster Recovery

1. Restore from git: `git checkout <commit>`
2. Reinstall dependencies: `uv sync`
3. Re-run simulation: `python -m efxlab.main run --config config/default.yaml`

---

## Support Contacts

For issues or questions:
- Check README.md first
- Review this runbook
- Check test files for examples
- Contact: [Your contact info]

---

## Appendix: Example Workflows

### Workflow 1: Backtest Historical Data

```powershell
# 1. Export historical data to Parquet
python export_historical_data.py --start 2024-01-01 --end 2024-12-31

# 2. Create config
cp config/default.yaml config/backtest_2024.yaml
# Edit paths in backtest_2024.yaml

# 3. Run simulation
python -m efxlab.main run --config config/backtest_2024.yaml

# 4. Analyze results
python analyze_pnl.py --snapshots outputs/snapshots.parquet
```

### Workflow 2: Compare Strategies

```powershell
# Run with strategy A
python -m efxlab.main run --config config/strategy_a.yaml
mv outputs outputs_strategy_a

# Run with strategy B  
python -m efxlab.main run --config config/strategy_b.yaml
mv outputs outputs_strategy_b

# Compare
python compare_strategies.py outputs_strategy_a outputs_strategy_b
```

### Workflow 3: Daily Production Run

```powershell
# Automated daily script
$DATE = Get-Date -Format "yyyyMMdd"

# Run simulation
python -m efxlab.main run --config config/production.yaml --log-level INFO

# Archive outputs
mkdir -p archive/$DATE
cp -r outputs/* archive/$DATE/

# Generate report
python generate_report.py --date $DATE

# Send alert if issues
if ($LASTEXITCODE -ne 0) {
    # Send alert email
}
```

---

**Last Updated:** January 5, 2026
