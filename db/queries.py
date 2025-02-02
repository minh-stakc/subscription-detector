"""
Optimized SQL queries for pattern detection.

All functions accept a SQLAlchemy *Session* and return lists of dicts (or
DataFrames where noted).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session as SASession

from config import MIN_RECURRENCE_COUNT

# ---------------------------------------------------------------------------
# Recurring-candidate query
# ---------------------------------------------------------------------------

_RECURRING_CANDIDATES_SQL = text("""
SELECT
    merchant_normalised,
    COUNT(*)                            AS txn_count,
    MIN(txn_date)                       AS first_seen,
    MAX(txn_date)                       AS last_seen,
    AVG(amount)                         AS avg_amount,
    GROUP_CONCAT(amount, ',')           AS amounts_csv,
    GROUP_CONCAT(txn_date, ',')         AS dates_csv
FROM transactions
GROUP BY merchant_normalised
HAVING COUNT(*) >= :min_count
ORDER BY txn_count DESC
""")


def get_recurring_candidates(
    session: SASession,
    min_count: int = MIN_RECURRENCE_COUNT,
) -> list[dict[str, Any]]:
    """Return merchants with enough transactions to be potential subscriptions."""
    rows = session.execute(
        _RECURRING_CANDIDATES_SQL, {"min_count": min_count}
    ).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Transaction history for a single merchant
# ---------------------------------------------------------------------------

_MERCHANT_HISTORY_SQL = text("""
SELECT id, txn_date, amount
FROM transactions
WHERE merchant_normalised = :merchant
ORDER BY txn_date
""")


def get_merchant_history(
    session: SASession, merchant: str
) -> pd.DataFrame:
    """Return a DataFrame of (id, txn_date, amount) for a merchant."""
    rows = session.execute(
        _MERCHANT_HISTORY_SQL, {"merchant": merchant}
    ).mappings().all()
    if not rows:
        return pd.DataFrame(columns=["id", "txn_date", "amount"])
    df = pd.DataFrame(rows)
    df["txn_date"] = pd.to_datetime(df["txn_date"]).dt.date
    return df


# ---------------------------------------------------------------------------
# Monthly spend aggregation
# ---------------------------------------------------------------------------

_MONTHLY_SPEND_SQL = text("""
SELECT
    merchant_normalised,
    strftime('%Y-%m', txn_date) AS month,
    SUM(amount)                  AS total,
    COUNT(*)                     AS txn_count,
    AVG(amount)                  AS avg_amount
FROM transactions
GROUP BY merchant_normalised, strftime('%Y-%m', txn_date)
ORDER BY merchant_normalised, month
""")


def get_monthly_spend(session: SASession) -> pd.DataFrame:
    """Return monthly spend per merchant as a DataFrame."""
    rows = session.execute(_MONTHLY_SPEND_SQL).mappings().all()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ---------------------------------------------------------------------------
# Potential duplicate pairs (same-ish amount, overlapping date ranges)
# ---------------------------------------------------------------------------

_DUPLICATE_CANDIDATES_SQL = text("""
SELECT
    a.merchant_normalised AS merchant_a,
    b.merchant_normalised AS merchant_b,
    a.median_amount       AS amount_a,
    b.median_amount       AS amount_b,
    a.frequency           AS freq_a,
    b.frequency           AS freq_b,
    a.id                  AS sub_id_a,
    b.id                  AS sub_id_b
FROM subscriptions a
JOIN subscriptions b
  ON a.id < b.id
  AND a.frequency = b.frequency
  AND a.is_active = 1
  AND b.is_active = 1
  AND ABS(a.median_amount - b.median_amount)
      / MAX(a.median_amount, b.median_amount) <= :amount_tol
ORDER BY a.median_amount DESC
""")


def get_duplicate_candidates(
    session: SASession, amount_tolerance: float = 0.25
) -> list[dict[str, Any]]:
    """Return subscription pairs that look like duplicates."""
    rows = session.execute(
        _DUPLICATE_CANDIDATES_SQL, {"amount_tol": amount_tolerance}
    ).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Recent charge increases
# ---------------------------------------------------------------------------

_CHARGE_INCREASE_SQL = text("""
WITH ordered AS (
    SELECT
        merchant_normalised,
        amount,
        txn_date,
        LAG(amount) OVER (
            PARTITION BY merchant_normalised ORDER BY txn_date
        ) AS prev_amount
    FROM transactions
)
SELECT
    merchant_normalised,
    txn_date,
    amount,
    prev_amount,
    amount - prev_amount AS increase,
    CASE WHEN prev_amount > 0
         THEN (amount - prev_amount) / prev_amount
         ELSE NULL
    END AS pct_increase
FROM ordered
WHERE prev_amount IS NOT NULL
  AND amount > prev_amount
  AND (amount - prev_amount) >= :min_abs
ORDER BY pct_increase DESC
""")


def get_charge_increases(
    session: SASession, min_absolute: float = 2.0
) -> pd.DataFrame:
    """Return transactions where the charge was higher than the previous one."""
    rows = session.execute(
        _CHARGE_INCREASE_SQL, {"min_abs": min_absolute}
    ).mappings().all()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

_TOTAL_SUBSCRIPTION_COST_SQL = text("""
SELECT
    SUM(
        CASE frequency
            WHEN 'weekly'    THEN median_amount * 52
            WHEN 'biweekly'  THEN median_amount * 26
            WHEN 'monthly'   THEN median_amount * 12
            WHEN 'quarterly' THEN median_amount * 4
            WHEN 'annual'    THEN median_amount
            ELSE 0
        END
    ) AS estimated_annual_total,
    COUNT(*) AS active_subscriptions
FROM subscriptions
WHERE is_active = 1
""")


def get_subscription_cost_summary(session: SASession) -> dict[str, Any]:
    """Return estimated annual cost and count of active subscriptions."""
    row = session.execute(_TOTAL_SUBSCRIPTION_COST_SQL).mappings().first()
    return dict(row) if row else {"estimated_annual_total": 0, "active_subscriptions": 0}
