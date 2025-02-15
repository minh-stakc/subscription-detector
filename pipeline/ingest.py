"""
Transaction data ingestion from CSV files and bank-API-style JSON.

Supports:
  - Standard CSV with columns: date, merchant/description, amount[, currency, category]
  - JSON array of transaction objects (simulated bank API response)
  - Automatic column-name mapping via heuristics
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column-name heuristics
# ---------------------------------------------------------------------------

_DATE_ALIASES = {"date", "txn_date", "transaction_date", "posting_date", "post_date"}
_MERCHANT_ALIASES = {
    "merchant",
    "description",
    "merchant_name",
    "payee",
    "name",
    "vendor",
}
_AMOUNT_ALIASES = {"amount", "txn_amount", "transaction_amount", "debit", "charge"}
_CURRENCY_ALIASES = {"currency", "ccy"}
_CATEGORY_ALIASES = {"category", "type", "txn_type", "mcc", "merchant_category"}


def _resolve_column(columns: list[str], aliases: set[str]) -> str | None:
    lower_map = {c.lower().strip(): c for c in columns}
    for alias in aliases:
        if alias in lower_map:
            return lower_map[alias]
    return None


# ---------------------------------------------------------------------------
# CSV ingestion
# ---------------------------------------------------------------------------


def ingest_csv(
    path: str | Path,
    *,
    encoding: str = "utf-8",
    delimiter: str = ",",
) -> pd.DataFrame:
    """
    Read a CSV file and return a normalised DataFrame with columns:
    ``txn_date``, ``merchant_raw``, ``amount``, ``currency``, ``category``.
    """
    path = Path(path)
    logger.info("Ingesting CSV: %s", path)
    df = pd.read_csv(path, encoding=encoding, delimiter=delimiter, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    date_col = _resolve_column(list(df.columns), _DATE_ALIASES)
    merchant_col = _resolve_column(list(df.columns), _MERCHANT_ALIASES)
    amount_col = _resolve_column(list(df.columns), _AMOUNT_ALIASES)
    currency_col = _resolve_column(list(df.columns), _CURRENCY_ALIASES)
    category_col = _resolve_column(list(df.columns), _CATEGORY_ALIASES)

    if not date_col or not merchant_col or not amount_col:
        raise ValueError(
            f"Cannot map required columns (date, merchant, amount) from {list(df.columns)}"
        )

    out = pd.DataFrame()
    out["txn_date"] = pd.to_datetime(df[date_col], dayfirst=False, infer_datetime_format=True).dt.date
    out["merchant_raw"] = df[merchant_col].astype(str).str.strip()
    out["amount"] = (
        df[amount_col]
        .str.replace(r"[^\d.\-]", "", regex=True)
        .astype(float)
        .abs()
    )
    out["currency"] = df[currency_col].str.strip().str.upper() if currency_col else "USD"
    out["category"] = df[category_col].str.strip() if category_col else None
    out["source"] = "csv"

    logger.info("Ingested %d rows from %s", len(out), path.name)
    return out


# ---------------------------------------------------------------------------
# JSON / bank-API ingestion
# ---------------------------------------------------------------------------


def ingest_json(path: str | Path) -> pd.DataFrame:
    """
    Read a JSON file containing an array of transaction objects.

    Expected keys per object (flexible):
      date / transaction_date, merchant / description, amount, currency?, category?
    """
    path = Path(path)
    logger.info("Ingesting JSON: %s", path)
    with open(path, "r", encoding="utf-8") as fh:
        data: list[dict[str, Any]] = json.load(fh)

    if not data:
        return pd.DataFrame(
            columns=["txn_date", "merchant_raw", "amount", "currency", "category", "source"]
        )

    df = pd.json_normalize(data)
    df.columns = [c.strip() for c in df.columns]

    date_col = _resolve_column(list(df.columns), _DATE_ALIASES)
    merchant_col = _resolve_column(list(df.columns), _MERCHANT_ALIASES)
    amount_col = _resolve_column(list(df.columns), _AMOUNT_ALIASES)
    currency_col = _resolve_column(list(df.columns), _CURRENCY_ALIASES)
    category_col = _resolve_column(list(df.columns), _CATEGORY_ALIASES)

    if not date_col or not merchant_col or not amount_col:
        raise ValueError(
            f"Cannot map required columns from JSON keys: {list(df.columns)}"
        )

    out = pd.DataFrame()
    out["txn_date"] = pd.to_datetime(df[date_col]).dt.date
    out["merchant_raw"] = df[merchant_col].astype(str).str.strip()
    out["amount"] = pd.to_numeric(df[amount_col], errors="coerce").abs()
    out["currency"] = df[currency_col].str.upper() if currency_col else "USD"
    out["category"] = df[category_col] if category_col else None
    out["source"] = "api"

    logger.info("Ingested %d rows from %s", len(out), path.name)
    return out


# ---------------------------------------------------------------------------
# Seed / synthetic data generation (for demo / testing)
# ---------------------------------------------------------------------------

import random
import numpy as np

_SAMPLE_MERCHANTS = [
    ("Netflix", 15.99, 30, "streaming"),
    ("Spotify Premium", 10.99, 30, "streaming"),
    ("Hulu", 14.99, 30, "streaming"),
    ("Adobe Creative Cloud", 54.99, 30, "software"),
    ("Microsoft 365", 9.99, 30, "software"),
    ("Dropbox Plus", 11.99, 30, "cloud_storage"),
    ("Google One", 2.99, 30, "cloud_storage"),
    ("iCloud+", 2.99, 30, "cloud_storage"),
    ("Amazon Prime", 14.99, 30, "shopping"),
    ("Gym Membership", 49.99, 30, "fitness"),
    ("Planet Fitness", 24.99, 30, "fitness"),
    ("NYT Digital", 17.00, 30, "news"),
    ("Wall Street Journal", 38.99, 30, "news"),
    ("NordVPN", 12.99, 30, "security"),
    ("1Password", 4.99, 30, "security"),
    ("Duolingo Plus", 6.99, 30, "education"),
    ("Coursera Plus", 59.00, 30, "education"),
    ("ChatGPT Plus", 20.00, 30, "software"),
    ("GitHub Copilot", 10.00, 30, "software"),
    ("AWS Lightsail", 5.00, 30, "cloud"),
]


def generate_seed_data(
    n_rows: int = 2000,
    start_date: date | None = None,
    end_date: date | None = None,
    rng_seed: int = 42,
) -> pd.DataFrame:
    """
    Generate realistic synthetic transaction data including recurring
    subscriptions, one-off purchases, and deliberate anomalies.
    """
    rng = random.Random(rng_seed)
    np_rng = np.random.default_rng(rng_seed)

    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = date(end_date.year - 2, end_date.month, end_date.day)

    total_days = (end_date - start_date).days
    records: list[dict[str, Any]] = []

    # -- recurring subscriptions ------------------------------------------
    chosen = rng.sample(_SAMPLE_MERCHANTS, k=min(len(_SAMPLE_MERCHANTS), 14))
    for merchant, base_amount, interval, category in chosen:
        d = start_date
        while d <= end_date:
            # Slight amount jitter (simulates tax / rounding changes)
            amount = round(base_amount + np_rng.normal(0, 0.3), 2)
            # Occasional price hike (anomaly)
            if rng.random() < 0.03:
                amount = round(base_amount * rng.uniform(1.3, 1.7), 2)
            records.append(
                {
                    "txn_date": d,
                    "merchant_raw": merchant,
                    "amount": max(amount, 0.99),
                    "currency": "USD",
                    "category": category,
                    "source": "seed",
                }
            )
            jitter = rng.randint(-2, 2)
            from datetime import timedelta
            d += timedelta(days=interval + jitter)

    # -- duplicate subscription (same category, similar merchant name) ----
    dup_merchant = "Spotify Family Plan"
    d = start_date
    while d <= end_date:
        records.append(
            {
                "txn_date": d,
                "merchant_raw": dup_merchant,
                "amount": round(16.99 + np_rng.normal(0, 0.2), 2),
                "currency": "USD",
                "category": "streaming",
                "source": "seed",
            }
        )
        from datetime import timedelta
        d += timedelta(days=30 + rng.randint(-2, 2))

    # -- one-off purchases to add noise -----------------------------------
    one_off_merchants = [
        "Whole Foods", "Shell Gas Station", "Target", "Costco",
        "Uber Eats", "DoorDash", "Starbucks", "Home Depot",
        "Walgreens", "Best Buy", "Trader Joes", "Chipotle",
    ]
    remaining = max(0, n_rows - len(records))
    for _ in range(remaining):
        records.append(
            {
                "txn_date": start_date + __import__("datetime").timedelta(
                    days=rng.randint(0, total_days)
                ),
                "merchant_raw": rng.choice(one_off_merchants),
                "amount": round(rng.uniform(3.0, 250.0), 2),
                "currency": "USD",
                "category": rng.choice(["groceries", "gas", "dining", "retail", "other"]),
                "source": "seed",
            }
        )

    df = pd.DataFrame(records)
    df = df.sort_values("txn_date").reset_index(drop=True)
    logger.info("Generated %d synthetic transactions", len(df))
    return df
