"""
Recurring payment pattern detection.

Algorithm overview:
  1. Group transactions by normalised merchant name.
  2. For merchants with >= MIN_RECURRENCE_COUNT transactions, compute
     the median inter-payment interval.
  3. Classify the interval into a known frequency bucket (weekly,
     monthly, quarterly, annual).
  4. Score regularity using coefficient-of-variation of intervals.
  5. Return a list of detected subscriptions.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session as SASession

from config import MIN_RECURRENCE_COUNT, INTERVAL_TOLERANCE_DAYS, KNOWN_INTERVALS
from db.queries import get_recurring_candidates, get_merchant_history
from utils import median_interval, classify_interval, interval_regularity_score

logger = logging.getLogger(__name__)


def _analyse_merchant(
    history: pd.DataFrame,
) -> dict[str, Any] | None:
    """
    Given a merchant's transaction history (sorted by date), decide
    whether it looks like a subscription.

    Returns a subscription dict or None.
    """
    if len(history) < MIN_RECURRENCE_COUNT:
        return None

    dates = sorted(history["txn_date"].tolist())
    amounts = history["amount"].values

    med_interval = median_interval(dates)
    if med_interval is None or med_interval < 3:
        # Transactions too close together -- probably not a subscription
        return None

    freq_label = classify_interval(med_interval)
    if freq_label is None:
        # Interval doesn't match any known subscription cadence
        # Still flag it if regularity is very high
        regularity = interval_regularity_score(dates)
        if regularity < 0.6:
            return None
        freq_label = f"~{int(med_interval)}d"

    regularity = interval_regularity_score(dates)
    if regularity < 0.35:
        return None

    merchant = history["merchant_normalised"].iloc[0] if "merchant_normalised" in history.columns else ""

    return {
        "merchant_normalised": merchant,
        "frequency": freq_label,
        "median_interval_days": round(med_interval, 1),
        "median_amount": round(float(np.median(amounts)), 2),
        "last_amount": round(float(amounts[-1]), 2),
        "first_seen": dates[0],
        "last_seen": dates[-1],
        "txn_count": len(dates),
        "regularity_score": round(regularity, 3),
    }


def detect_recurring_subscriptions(
    session: SASession,
) -> list[dict[str, Any]]:
    """
    Main entry point.  Scans all transactions in the database and returns
    a list of detected recurring subscriptions.
    """
    candidates = get_recurring_candidates(session)
    logger.info(
        "Evaluating %d merchant(s) with >= %d transactions",
        len(candidates),
        MIN_RECURRENCE_COUNT,
    )

    results: list[dict[str, Any]] = []
    for cand in candidates:
        merchant = cand["merchant_normalised"]
        history = get_merchant_history(session, merchant)
        if history.empty:
            continue

        # Add normalised name to history df for downstream use
        history["merchant_normalised"] = merchant

        sub = _analyse_merchant(history)
        if sub:
            results.append(sub)
            logger.debug(
                "Recurring: %s  freq=%s  regularity=%.2f",
                merchant,
                sub["frequency"],
                sub["regularity_score"],
            )

    results.sort(key=lambda s: s["median_amount"], reverse=True)
    logger.info("Detected %d recurring subscriptions", len(results))
    return results
