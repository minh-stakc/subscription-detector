"""
Subscription Leak Detector -- central configuration.

Every setting can be overridden with an environment variable prefixed ``SUBLEAK_``.
For example ``SUBLEAK_DB_URL=sqlite:///prod.db``.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SUBLEAK_DB_PATH", str(PROJECT_ROOT / "subscriptions.db")))
DB_URL = os.getenv("SUBLEAK_DB_URL", f"sqlite:///{DB_PATH}")

# ---------------------------------------------------------------------------
# Recurring-payment detection
# ---------------------------------------------------------------------------
# Minimum number of transactions from a merchant to consider it recurring
MIN_RECURRENCE_COUNT: int = int(os.getenv("SUBLEAK_MIN_RECURRENCE_COUNT", "3"))

# Tolerance (in days) when matching payment intervals
INTERVAL_TOLERANCE_DAYS: int = int(os.getenv("SUBLEAK_INTERVAL_TOLERANCE_DAYS", "5"))

# Expected recurring intervals (days) and their human labels
KNOWN_INTERVALS: dict[int, str] = {
    7: "weekly",
    14: "biweekly",
    30: "monthly",
    90: "quarterly",
    365: "annual",
}

# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------
# Merchant-name similarity threshold (0-1, Jaccard on token sets)
DUPLICATE_NAME_SIMILARITY: float = float(
    os.getenv("SUBLEAK_DUPLICATE_NAME_SIMILARITY", "0.6")
)

# Maximum amount-ratio difference to still consider two subscriptions duplicates
DUPLICATE_AMOUNT_TOLERANCE: float = float(
    os.getenv("SUBLEAK_DUPLICATE_AMOUNT_TOLERANCE", "0.25")
)

# ---------------------------------------------------------------------------
# Anomaly / charge-increase detection
# ---------------------------------------------------------------------------
# Flag a charge if it exceeds the historical median by this factor
ANOMALY_INCREASE_FACTOR: float = float(
    os.getenv("SUBLEAK_ANOMALY_INCREASE_FACTOR", "1.25")
)

# Minimum absolute increase (dollars) to bother alerting
ANOMALY_MIN_ABSOLUTE_INCREASE: float = float(
    os.getenv("SUBLEAK_ANOMALY_MIN_ABSOLUTE_INCREASE", "2.00")
)

# Z-score threshold for statistical outlier detection
ANOMALY_ZSCORE_THRESHOLD: float = float(
    os.getenv("SUBLEAK_ANOMALY_ZSCORE_THRESHOLD", "2.5")
)

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
BATCH_SIZE: int = int(os.getenv("SUBLEAK_BATCH_SIZE", "5000"))

# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
REPORT_OUTPUT_DIR = Path(
    os.getenv("SUBLEAK_REPORT_OUTPUT_DIR", str(PROJECT_ROOT / "reports"))
)
CURRENCY_SYMBOL: str = os.getenv("SUBLEAK_CURRENCY_SYMBOL", "$")
