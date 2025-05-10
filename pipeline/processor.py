"""
Main processing pipeline orchestrator.

Coordinates: ingest -> transform -> load -> detect -> report.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert
from sqlalchemy import text

from config import BATCH_SIZE
from db.models import Alert, Session, Subscription, Transaction, init_db
from pipeline.ingest import generate_seed_data, ingest_csv, ingest_json
from pipeline.transform import clean_dataframe, validate_schema
from detection.recurring import detect_recurring_subscriptions
from detection.duplicates import detect_duplicate_subscriptions
from detection.anomalies import detect_anomalies
from reporting.alerts import build_alerts

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Load stage -- bulk-insert into SQLite via batched upserts
# ---------------------------------------------------------------------------


def _load_transactions(df: pd.DataFrame) -> int:
    """Insert cleaned transactions into the database, skipping duplicates.
    Returns the number of newly inserted rows."""
    validate_schema(df)
    session = Session()
    inserted = 0
    try:
        for start in range(0, len(df), BATCH_SIZE):
            batch = df.iloc[start : start + BATCH_SIZE]
            for _, row in batch.iterrows():
                existing = (
                    session.query(Transaction.id)
                    .filter_by(fingerprint=row["fingerprint"])
                    .first()
                )
                if existing:
                    continue
                txn = Transaction(
                    txn_date=row["txn_date"],
                    merchant_raw=row["merchant_raw"],
                    merchant_normalised=row["merchant_normalised"],
                    amount=row["amount"],
                    currency=row["currency"],
                    category=row.get("category"),
                    fingerprint=row["fingerprint"],
                    source=row.get("source"),
                )
                session.add(txn)
                inserted += 1
            session.flush()
        session.commit()
        logger.info("Loaded %d new transactions", inserted)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return inserted


def _save_subscriptions(subs: list[dict[str, Any]]) -> int:
    """Upsert detected subscriptions. Returns count."""
    session = Session()
    count = 0
    try:
        # Clear previous run
        session.query(Subscription).delete()
        for s in subs:
            sub = Subscription(
                merchant_normalised=s["merchant_normalised"],
                frequency=s["frequency"],
                median_interval_days=s["median_interval_days"],
                median_amount=s["median_amount"],
                last_amount=s["last_amount"],
                first_seen=s["first_seen"],
                last_seen=s["last_seen"],
                txn_count=s["txn_count"],
                regularity_score=s["regularity_score"],
                is_active=1,
            )
            session.add(sub)
            count += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return count


def _save_alerts(alerts: list[dict[str, Any]]) -> int:
    """Persist alerts. Returns count."""
    session = Session()
    count = 0
    try:
        session.query(Alert).delete()
        for a in alerts:
            alert = Alert(
                alert_type=a["alert_type"],
                severity=a.get("severity", "medium"),
                merchant=a["merchant"],
                title=a["title"],
                detail=a.get("detail"),
                estimated_annual_cost=a.get("estimated_annual_cost"),
                subscription_id=a.get("subscription_id"),
            )
            session.add(alert)
            count += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_seed(n_rows: int = 2000) -> int:
    """Generate synthetic data and load it into the database."""
    init_db()
    df = generate_seed_data(n_rows=n_rows)
    df = clean_dataframe(df)
    return _load_transactions(df)


def run_ingest(path: str) -> int:
    """Ingest a file (CSV or JSON) and load into the database."""
    init_db()
    p = Path(path)
    if p.suffix.lower() == ".json":
        df = ingest_json(p)
    else:
        df = ingest_csv(p)
    df = clean_dataframe(df)
    return _load_transactions(df)


def run_detection() -> dict[str, Any]:
    """
    Execute the full detection pipeline:
      1. Detect recurring subscriptions
      2. Detect duplicates
      3. Detect anomalies
      4. Generate alerts
    Returns a summary dict.
    """
    init_db()
    session = Session()

    try:
        # Step 1 -- recurring
        subs = detect_recurring_subscriptions(session)
        n_subs = _save_subscriptions(subs)
        logger.info("Detected %d recurring subscriptions", n_subs)

        # Reload session for fresh subscription IDs
        session.close()
        session = Session()

        # Step 2 -- duplicates
        duplicates = detect_duplicate_subscriptions(session)
        logger.info("Found %d duplicate-subscription pairs", len(duplicates))

        # Step 3 -- anomalies
        anomalies = detect_anomalies(session)
        logger.info("Found %d charge anomalies", len(anomalies))

        # Step 4 -- alerts
        alerts = build_alerts(subs, duplicates, anomalies)
        n_alerts = _save_alerts(alerts)
        logger.info("Generated %d alerts", n_alerts)

        return {
            "subscriptions_detected": n_subs,
            "duplicate_pairs": len(duplicates),
            "anomalies": len(anomalies),
            "alerts_generated": n_alerts,
        }
    finally:
        session.close()


def run_full_pipeline(path: str | None = None, seed_rows: int = 0) -> dict[str, Any]:
    """
    Convenience method: optionally ingest data, then run detection.
    """
    result: dict[str, Any] = {}

    if seed_rows > 0:
        result["rows_loaded"] = run_seed(seed_rows)
    elif path:
        result["rows_loaded"] = run_ingest(path)

    detection_result = run_detection()
    result.update(detection_result)
    return result
