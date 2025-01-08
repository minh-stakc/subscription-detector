# Subscription Leak Detector

A Python + SQL pipeline for detecting forgotten, duplicate, or overcharged recurring
subscriptions from transaction history.

## Features

- **Recurring payment detection** -- frequency analysis and merchant-name matching to
  identify subscriptions hidden in your transaction data.
- **Duplicate subscription detection** -- finds cases where you pay two different
  services for the same category, or pay the same merchant twice.
- **Abnormal charge-increase detection** -- flags subscriptions whose amount has
  jumped beyond a configurable threshold.
- **HTML / CSV report export** -- generates a human-readable report of all findings.
- **CLI interface** -- powered by Click and Rich for a pleasant terminal experience.

## Quick start

```bash
pip install -r requirements.txt

# Seed the database with sample transactions
python main.py seed --rows 2000

# Run the full detection pipeline
python main.py run

# Export an HTML report
python main.py report --format html --output report.html

# Show a spending summary in the terminal
python main.py summary
```

## Project layout

```
subscription_detector/
  main.py              CLI entry point
  config.py            Configuration constants
  utils.py             Shared helpers
  requirements.txt
  db/
    models.py          SQLAlchemy ORM models
    schema.sql         Raw SQL DDL (indexes, views)
    queries.py         Optimized SQL queries for pattern detection
  pipeline/
    ingest.py          CSV / bank-API ingestion
    transform.py       Cleaning and normalisation
    processor.py       Pipeline orchestrator
  detection/
    recurring.py       Recurring-payment pattern detection
    duplicates.py      Duplicate subscription detection
    anomalies.py       Charge-increase anomaly detection
  reporting/
    alerts.py          Alert generation
    summary.py         Spending summary
    export.py          HTML / CSV export
```

## Configuration

Edit `config.py` or set environment variables (prefixed `SUBLEAK_`) to override
defaults such as detection thresholds and database path.

## License

MIT
