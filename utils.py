"""
Shared utility functions used across the project.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, timedelta
from typing import Iterable, Sequence

import numpy as np

from config import KNOWN_INTERVALS, INTERVAL_TOLERANCE_DAYS


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

_STRIP_PATTERN = re.compile(r"[^a-z0-9\s]")


def normalise_merchant(name: str) -> str:
    """Lower-case, strip accents/punctuation, collapse whitespace."""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = _STRIP_PATTERN.sub("", name.lower())
    return " ".join(name.split())


def merchant_tokens(name: str) -> set[str]:
    """Return the token set of a normalised merchant name."""
    return set(normalise_merchant(name).split())


def jaccard_similarity(a: set, b: set) -> float:
    """Jaccard index of two sets."""
    if not a and not b:
        return 1.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union) if union else 0.0


# ---------------------------------------------------------------------------
# Date / interval helpers
# ---------------------------------------------------------------------------


def median_interval(dates: Sequence[date]) -> float | None:
    """Return the median interval (days) between sorted dates, or None."""
    if len(dates) < 2:
        return None
    sorted_dates = sorted(dates)
    deltas = [
        (sorted_dates[i + 1] - sorted_dates[i]).days
        for i in range(len(sorted_dates) - 1)
    ]
    return float(np.median(deltas))


def classify_interval(median_days: float) -> str | None:
    """Map a median interval to a human label (weekly, monthly, ...)."""
    for target, label in sorted(KNOWN_INTERVALS.items()):
        if abs(median_days - target) <= INTERVAL_TOLERANCE_DAYS:
            return label
    return None


def interval_regularity_score(dates: Sequence[date]) -> float:
    """
    Return a 0-1 score indicating how regular the intervals between
    *dates* are.  1.0 = perfectly periodic.
    """
    if len(dates) < 3:
        return 0.0
    sorted_dates = sorted(dates)
    deltas = np.array(
        [
            (sorted_dates[i + 1] - sorted_dates[i]).days
            for i in range(len(sorted_dates) - 1)
        ],
        dtype=float,
    )
    if deltas.mean() == 0:
        return 0.0
    cv = deltas.std() / deltas.mean()  # coefficient of variation
    return max(0.0, 1.0 - cv)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def transaction_fingerprint(
    merchant: str, amount: float, txn_date: date
) -> str:
    """Deterministic hash for deduplication during ingestion."""
    raw = f"{normalise_merchant(merchant)}|{amount:.2f}|{txn_date.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def fmt_currency(value: float, symbol: str = "$") -> str:
    return f"{symbol}{value:,.2f}"


def date_range_label(start: date, end: date) -> str:
    return f"{start:%Y-%m-%d} to {end:%Y-%m-%d}"
