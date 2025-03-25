"""
Duplicate subscription detection.

Two subscriptions are considered *potential duplicates* when:
  1. They share the same frequency bucket (e.g. both monthly).
  2. Their merchant names are similar (Jaccard similarity on token sets
     >= DUPLICATE_NAME_SIMILARITY), **or** they belong to the same spending
     category.
  3. Their median amounts are within DUPLICATE_AMOUNT_TOLERANCE of each other.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session as SASession

from config import DUPLICATE_NAME_SIMILARITY, DUPLICATE_AMOUNT_TOLERANCE
from db.models import Subscription
from db.queries import get_duplicate_candidates
from utils import merchant_tokens, jaccard_similarity

logger = logging.getLogger(__name__)


def _name_similar(merchant_a: str, merchant_b: str) -> bool:
    """Check if two merchant names are similar enough to be duplicates."""
    tokens_a = merchant_tokens(merchant_a)
    tokens_b = merchant_tokens(merchant_b)
    sim = jaccard_similarity(tokens_a, tokens_b)
    return sim >= DUPLICATE_NAME_SIMILARITY


def _same_category_bucket(merchant_a: str, merchant_b: str, session: SASession) -> bool:
    """
    Check whether two merchants' transactions share a category.
    Falls back to False if categories are not available.
    """
    from db.models import Transaction

    cat_a = (
        session.query(Transaction.category)
        .filter(Transaction.merchant_normalised == merchant_a)
        .filter(Transaction.category.isnot(None))
        .limit(1)
        .scalar()
    )
    cat_b = (
        session.query(Transaction.category)
        .filter(Transaction.merchant_normalised == merchant_b)
        .filter(Transaction.category.isnot(None))
        .limit(1)
        .scalar()
    )
    if cat_a and cat_b:
        return cat_a.strip().lower() == cat_b.strip().lower()
    return False


def detect_duplicate_subscriptions(
    session: SASession,
) -> list[dict[str, Any]]:
    """
    Compare all active subscription pairs and flag likely duplicates.

    Returns a list of dicts, each describing a duplicate pair.
    """
    # Start with SQL-level pre-filter (same frequency, similar amount)
    candidates = get_duplicate_candidates(session, DUPLICATE_AMOUNT_TOLERANCE)
    logger.info("SQL pre-filter returned %d candidate pairs", len(candidates))

    duplicates: list[dict[str, Any]] = []

    for pair in candidates:
        ma = pair["merchant_a"]
        mb = pair["merchant_b"]

        # Check name similarity OR category overlap
        name_sim = jaccard_similarity(merchant_tokens(ma), merchant_tokens(mb))
        same_cat = _same_category_bucket(ma, mb, session)

        is_dup = name_sim >= DUPLICATE_NAME_SIMILARITY or same_cat

        if is_dup:
            avg_amount = (pair["amount_a"] + pair["amount_b"]) / 2
            annual_multiplier = {
                "weekly": 52, "biweekly": 26, "monthly": 12,
                "quarterly": 4, "annual": 1,
            }.get(pair["freq_a"], 12)

            duplicates.append(
                {
                    "merchant_a": ma,
                    "merchant_b": mb,
                    "frequency": pair["freq_a"],
                    "amount_a": pair["amount_a"],
                    "amount_b": pair["amount_b"],
                    "name_similarity": round(name_sim, 3),
                    "same_category": same_cat,
                    "estimated_annual_waste": round(
                        min(pair["amount_a"], pair["amount_b"]) * annual_multiplier, 2
                    ),
                    "sub_id_a": pair["sub_id_a"],
                    "sub_id_b": pair["sub_id_b"],
                }
            )
            logger.debug(
                "Duplicate pair: %s <-> %s  (sim=%.2f, cat=%s)",
                ma, mb, name_sim, same_cat,
            )

    logger.info("Confirmed %d duplicate subscription pairs", len(duplicates))
    return duplicates
