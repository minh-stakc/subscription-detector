"""
Alert generation for detected issues.

Converts raw detection outputs (subscriptions, duplicates, anomalies) into
a uniform list of alert dicts ready for persistence and display.
"""

from __future__ import annotations

import logging
from typing import Any

from utils import fmt_currency

logger = logging.getLogger(__name__)


def _annual_multiplier(frequency: str) -> float:
    return {
        "weekly": 52,
        "biweekly": 26,
        "monthly": 12,
        "quarterly": 4,
        "annual": 1,
    }.get(frequency, 12)


# ---------------------------------------------------------------------------
# Forgotten / idle subscription alerts
# ---------------------------------------------------------------------------

def _forgotten_subscription_alerts(
    subs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flag subscriptions that are still active but may be forgotten."""
    from datetime import date, timedelta

    alerts: list[dict[str, Any]] = []
    today = date.today()

    for s in subs:
        last = s["last_seen"]
        freq = s["frequency"]
        interval = s["median_interval_days"]

        # Consider a subscription "forgotten" if the last charge was
        # more than 2 intervals ago (still active but user may have
        # forgotten about it).
        gap = (today - last).days
        if gap > interval * 2 and gap > 60:
            annual = s["median_amount"] * _annual_multiplier(freq)
            alerts.append(
                {
                    "alert_type": "forgotten",
                    "severity": "high" if annual > 200 else "medium",
                    "merchant": s["merchant_normalised"],
                    "title": f"Possibly forgotten subscription: {s['merchant_normalised']}",
                    "detail": (
                        f"Last charged {fmt_currency(s['last_amount'])} on {last}. "
                        f"Expected {freq} charges (~{int(interval)}d interval) but "
                        f"none seen for {gap} days. "
                        f"Estimated annual cost: {fmt_currency(annual)}."
                    ),
                    "estimated_annual_cost": round(annual, 2),
                }
            )
    return alerts


# ---------------------------------------------------------------------------
# Active subscription awareness alerts
# ---------------------------------------------------------------------------

def _active_subscription_alerts(
    subs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate informational alerts for all detected active subscriptions."""
    alerts: list[dict[str, Any]] = []
    for s in subs:
        annual = s["median_amount"] * _annual_multiplier(s["frequency"])
        alerts.append(
            {
                "alert_type": "recurring",
                "severity": "low",
                "merchant": s["merchant_normalised"],
                "title": f"Active subscription detected: {s['merchant_normalised']}",
                "detail": (
                    f"Frequency: {s['frequency']} | "
                    f"Typical charge: {fmt_currency(s['median_amount'])} | "
                    f"Last charge: {fmt_currency(s['last_amount'])} on {s['last_seen']} | "
                    f"Regularity score: {s['regularity_score']:.0%} | "
                    f"Est. annual cost: {fmt_currency(annual)}"
                ),
                "estimated_annual_cost": round(annual, 2),
            }
        )
    return alerts


# ---------------------------------------------------------------------------
# Duplicate alerts
# ---------------------------------------------------------------------------

def _duplicate_alerts(
    duplicates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for d in duplicates:
        alerts.append(
            {
                "alert_type": "duplicate",
                "severity": "high",
                "merchant": f"{d['merchant_a']} / {d['merchant_b']}",
                "title": (
                    f"Possible duplicate: {d['merchant_a']} and {d['merchant_b']}"
                ),
                "detail": (
                    f"Both are {d['frequency']} subscriptions. "
                    f"Amounts: {fmt_currency(d['amount_a'])} vs {fmt_currency(d['amount_b'])}. "
                    f"Name similarity: {d['name_similarity']:.0%}. "
                    f"Same category: {'yes' if d['same_category'] else 'no'}. "
                    f"Potential annual savings: {fmt_currency(d['estimated_annual_waste'])}."
                ),
                "estimated_annual_cost": d["estimated_annual_waste"],
            }
        )
    return alerts


# ---------------------------------------------------------------------------
# Anomaly alerts
# ---------------------------------------------------------------------------

def _anomaly_alerts(
    anomalies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # Collapse multiple anomaly flags per merchant into one alert
    by_merchant: dict[str, list[dict]] = {}
    for a in anomalies:
        by_merchant.setdefault(a["merchant"], []).append(a)

    alerts: list[dict[str, Any]] = []
    for merchant, flags in by_merchant.items():
        latest = flags[0]  # already sorted newest-first
        detail_lines = []
        for f in flags[:5]:  # show up to 5 events
            if f["strategy"] == "pct_jump":
                detail_lines.append(
                    f"  {f['txn_date']}: {fmt_currency(f['amount'])} "
                    f"(+{f['pct_increase']}% from {fmt_currency(f['prev_amount'])})"
                )
            elif f["strategy"] == "zscore":
                detail_lines.append(
                    f"  {f['txn_date']}: {fmt_currency(f['amount'])} "
                    f"(z-score {f['zscore']}, mean={fmt_currency(f['historical_mean'])})"
                )
            elif f["strategy"] == "trend_break":
                detail_lines.append(
                    f"  {f['txn_date']}: rolling-mean shifted +{f['shift_pct']}%"
                )

        alerts.append(
            {
                "alert_type": "anomaly",
                "severity": "high" if len(flags) > 2 else "medium",
                "merchant": merchant,
                "title": f"Abnormal charge increase: {merchant}",
                "detail": (
                    f"{len(flags)} anomalous charge(s) detected:\n"
                    + "\n".join(detail_lines)
                ),
                "estimated_annual_cost": None,
                "subscription_id": latest.get("subscription_id"),
            }
        )
    return alerts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_alerts(
    subscriptions: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
    anomalies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Combine all detection outputs into a single sorted alert list."""
    alerts: list[dict[str, Any]] = []
    alerts.extend(_active_subscription_alerts(subscriptions))
    alerts.extend(_forgotten_subscription_alerts(subscriptions))
    alerts.extend(_duplicate_alerts(duplicates))
    alerts.extend(_anomaly_alerts(anomalies))

    # Sort: high severity first, then by type
    severity_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: (severity_order.get(a["severity"], 9), a["alert_type"]))

    logger.info("Built %d total alerts", len(alerts))
    return alerts
