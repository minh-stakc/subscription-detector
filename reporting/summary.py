"""
Spending summary generation for terminal display and reports.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session as SASession

from db.models import Alert, Subscription, Transaction
from db.queries import get_subscription_cost_summary, get_monthly_spend
from utils import fmt_currency

logger = logging.getLogger(__name__)


def generate_summary(session: SASession) -> dict[str, Any]:
    """
    Build a comprehensive spending summary dict containing:
      - total_transactions
      - date_range (first, last)
      - active_subscriptions (list of dicts)
      - estimated_annual_cost
      - alerts_by_severity
      - top_subscriptions (by annual cost)
      - monthly_trend (list of {month, total})
    """
    # -- basic stats ------------------------------------------------------
    total_txns = session.query(Transaction).count()
    first_date = session.query(Transaction.txn_date).order_by(Transaction.txn_date).first()
    last_date = session.query(Transaction.txn_date).order_by(Transaction.txn_date.desc()).first()

    # -- subscriptions ----------------------------------------------------
    subs = (
        session.query(Subscription)
        .filter(Subscription.is_active == 1)
        .order_by(Subscription.median_amount.desc())
        .all()
    )

    multiplier_map = {
        "weekly": 52, "biweekly": 26, "monthly": 12,
        "quarterly": 4, "annual": 1,
    }

    sub_list = []
    for s in subs:
        mult = multiplier_map.get(s.frequency, 12)
        annual = s.median_amount * mult
        sub_list.append(
            {
                "merchant": s.merchant_normalised,
                "frequency": s.frequency,
                "median_amount": s.median_amount,
                "last_amount": s.last_amount,
                "annual_cost": round(annual, 2),
                "regularity": s.regularity_score,
                "first_seen": s.first_seen,
                "last_seen": s.last_seen,
                "txn_count": s.txn_count,
            }
        )

    cost_summary = get_subscription_cost_summary(session)

    # -- alerts -----------------------------------------------------------
    alerts_by_severity: dict[str, int] = {}
    for sev in ["high", "medium", "low"]:
        cnt = session.query(Alert).filter(Alert.severity == sev).count()
        alerts_by_severity[sev] = cnt

    alert_count_by_type: dict[str, int] = {}
    for atype in ["recurring", "forgotten", "duplicate", "anomaly"]:
        cnt = session.query(Alert).filter(Alert.alert_type == atype).count()
        if cnt:
            alert_count_by_type[atype] = cnt

    # -- monthly trend ----------------------------------------------------
    monthly_df = get_monthly_spend(session)
    monthly_trend: list[dict[str, Any]] = []
    if not monthly_df.empty:
        by_month = monthly_df.groupby("month")["total"].sum().reset_index()
        for _, row in by_month.iterrows():
            monthly_trend.append({"month": row["month"], "total": round(row["total"], 2)})

    return {
        "total_transactions": total_txns,
        "date_range": {
            "first": first_date[0] if first_date else None,
            "last": last_date[0] if last_date else None,
        },
        "active_subscriptions": sub_list,
        "subscription_count": len(sub_list),
        "estimated_annual_cost": round(cost_summary.get("estimated_annual_total") or 0, 2),
        "alerts_by_severity": alerts_by_severity,
        "alert_count_by_type": alert_count_by_type,
        "monthly_trend": monthly_trend,
    }
