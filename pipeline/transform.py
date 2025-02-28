"""
Data cleaning and normalisation stage of the pipeline.

Responsibilities:
  - Normalise merchant names (strip punctuation, unify casing)
  - Deduplicate rows using fingerprinting
  - Coerce types and handle missing values
  - Enrich with computed columns (fingerprint, normalised name)
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from utils import normalise_merchant, transaction_fingerprint

logger = logging.getLogger(__name__)


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Accept a raw ingested DataFrame and return a cleaned copy ready for
    database insertion.

    Expected input columns:
        txn_date, merchant_raw, amount, currency, category, source

    Output adds:
        merchant_normalised, fingerprint
    """
    if df.empty:
        logger.warning("Received empty DataFrame -- nothing to clean")
        return df

    out = df.copy()

    # -- type coercion ----------------------------------------------------
    out["txn_date"] = pd.to_datetime(out["txn_date"], errors="coerce").dt.date
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")

    # Drop rows that could not be parsed
    before = len(out)
    out = out.dropna(subset=["txn_date", "merchant_raw", "amount"])
    dropped = before - len(out)
    if dropped:
        logger.warning("Dropped %d rows with unparseable date/merchant/amount", dropped)

    # -- filter out non-positive amounts ----------------------------------
    out = out[out["amount"] > 0].copy()

    # -- normalise merchant -----------------------------------------------
    out["merchant_normalised"] = out["merchant_raw"].apply(normalise_merchant)

    # -- fill optional columns --------------------------------------------
    out["currency"] = out.get("currency", pd.Series("USD", index=out.index))
    out["currency"] = out["currency"].fillna("USD").astype(str).str.upper()
    out["category"] = out.get("category", pd.Series(dtype=str))
    out["source"] = out.get("source", pd.Series("unknown", index=out.index))

    # -- compute fingerprint for dedup ------------------------------------
    out["fingerprint"] = out.apply(
        lambda r: transaction_fingerprint(r["merchant_raw"], r["amount"], r["txn_date"]),
        axis=1,
    )

    # -- deduplicate on fingerprint ---------------------------------------
    before = len(out)
    out = out.drop_duplicates(subset=["fingerprint"], keep="first")
    dupes = before - len(out)
    if dupes:
        logger.info("Removed %d duplicate rows by fingerprint", dupes)

    out = out.reset_index(drop=True)
    logger.info("Cleaned DataFrame: %d rows", len(out))
    return out


def validate_schema(df: pd.DataFrame) -> None:
    """Raise ValueError if required columns are missing after cleaning."""
    required = {
        "txn_date",
        "merchant_raw",
        "merchant_normalised",
        "amount",
        "currency",
        "fingerprint",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Cleaned DataFrame missing columns: {missing}")
