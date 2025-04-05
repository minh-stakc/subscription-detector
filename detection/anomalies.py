"""
Abnormal charge-increase detection.

Three complementary strategies:
  1. **Percentage jump** -- flag any charge that exceeds the prior charge by
     more than ANOMALY_INCREASE_FACTOR (default 25 %).
  2. **Statistical outlier** -- flag any charge whose z-score relative to
     the merchant's historical distribution exceeds ANOMALY_ZSCORE_THRESHOLD.
  3. **Trend break** -- detect a sustained upward shift (rolling-mean jump).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session as SASession

from config import (
    ANOMALY_INCREASE_FACTOR,
    ANOMALY_MIN_ABSOLUTE_INCREASE,
    ANOMALY_ZSCORE_THRESHOLD,
)
from db.models import Subscription
from db.queries import get_merchant_history

logger = logging.getLogger(__name__)


def _percentage_jump_flags(history: pd.DataFrame) -> list[dict[str, Any]]:
    """Strategy 1: flag charges that jumped > threshold vs. previous."""
    flags: list[dict[str, Any]] = []
    amounts = history["amount"].values
    dates = history["txn_date"].values

    for i in range(1, len(amounts)):
        prev = amounts[i - 1]
        curr = amounts[i]
        if prev <= 0:
            continue
        increase = curr - prev
        pct = increase / prev
        if pct >= (ANOMALY_INCREASE_FACTOR - 1) and increase >= ANOMALY_MIN_ABSOLUTE_INCREASE:
            flags.append(
                {
                    "strategy": "pct_jump",
                    "txn_date": dates[i],
                    "amount": float(curr),
                    "prev_amount": float(prev),
                    "increase": round(float(increase), 2),
                    "pct_increase": round(float(pct * 100), 1),
                }
            )
    return flags


def _zscore_flags(history: pd.DataFrame) -> list[dict[str, Any]]:
    """Strategy 2: flag statistical outliers by z-score."""
    flags: list[dict[str, Any]] = []
    amounts = history["amount"].values
    dates = history["txn_date"].values

    if len(amounts) < 5:
        return flags

    mean = np.mean(amounts)
    std = np.std(amounts)
    if std == 0:
        return flags

    for i, (amt, d) in enumerate(zip(amounts, dates)):
        z = (amt - mean) / std
        if z >= ANOMALY_ZSCORE_THRESHOLD:
            flags.append(
                {
                    "strategy": "zscore",
                    "txn_date": d,
                    "amount": float(amt),
                    "zscore": round(float(z), 2),
                    "historical_mean": round(float(mean), 2),
                    "historical_std": round(float(std), 2),
                }
            )
    return flags


def _trend_break_flags(history: pd.DataFrame, window: int = 3) -> list[dict[str, Any]]:
    """Strategy 3: detect a sustained upward shift via rolling mean."""
    flags: list[dict[str, Any]] = []
    if len(history) < window * 2:
        return flags

    amounts = history["amount"].values
    dates = history["txn_date"].values
    rolling = pd.Series(amounts).rolling(window=window).mean().values

    for i in range(window, len(rolling)):
        prev_window_mean = rolling[i - 1]
        curr_window_mean = rolling[i]
        if prev_window_mean is None or np.isnan(prev_window_mean):
            continue
        if prev_window_mean <= 0:
            continue
        shift = (curr_window_mean - prev_window_mean) / prev_window_mean
        if shift >= (ANOMALY_INCREASE_FACTOR - 1) and (
            curr_window_mean - prev_window_mean
        ) >= ANOMALY_MIN_ABSOLUTE_INCREASE:
            flags.append(
                {
                    "strategy": "trend_break",
                    "txn_date": dates[i],
                    "amount": float(amounts[i]),
                    "rolling_mean_before": round(float(prev_window_mean), 2),
                    "rolling_mean_after": round(float(curr_window_mean), 2),
                    "shift_pct": round(float(shift * 100), 1),
                }
            )
    return flags


def detect_anomalies(session: SASession) -> list[dict[str, Any]]:
    """
    Scan all detected subscriptions for abnormal charge increases.

    Returns a list of anomaly dicts, each containing at minimum:
      merchant, txn_date, amount, strategy, detail fields.
    """
    subs = session.query(Subscription).filter(Subscription.is_active == 1).all()
    logger.info("Checking %d active subscriptions for anomalies", len(subs))

    all_anomalies: list[dict[str, Any]] = []

    for sub in subs:
        history = get_merchant_history(session, sub.merchant_normalised)
        if history.empty or len(history) < 3:
            continue

        history = history.sort_values("txn_date").reset_index(drop=True)

        # Run all three strategies
        pct_flags = _percentage_jump_flags(history)
        z_flags = _zscore_flags(history)
        trend_flags = _trend_break_flags(history)

        # Merge and deduplicate on (date, strategy)
        seen: set[tuple] = set()
        for flag in pct_flags + z_flags + trend_flags:
            key = (str(flag["txn_date"]), flag["strategy"])
            if key in seen:
                continue
            seen.add(key)
            flag["merchant"] = sub.merchant_normalised
            flag["subscription_id"] = sub.id
            all_anomalies.append(flag)

    # Sort by date descending so the most recent anomalies appear first
    all_anomalies.sort(key=lambda a: str(a["txn_date"]), reverse=True)
    logger.info("Total anomalies detected: %d", len(all_anomalies))
    return all_anomalies
