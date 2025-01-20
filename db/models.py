"""
SQLAlchemy ORM models for the Subscription Leak Detector.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DB_URL

Base = declarative_base()


# ---------------------------------------------------------------------------
# Transactions -- raw rows imported from CSV / bank feeds
# ---------------------------------------------------------------------------
class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    txn_date = Column(Date, nullable=False)
    merchant_raw = Column(String(255), nullable=False)
    merchant_normalised = Column(String(255), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    category = Column(String(100), nullable=True)
    fingerprint = Column(String(16), nullable=False, unique=True)
    source = Column(String(50), nullable=True)  # e.g. "csv", "api"
    created_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index("ix_txn_merchant_date", "merchant_normalised", "txn_date"),
        Index("ix_txn_date", "txn_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction(id={self.id}, merchant={self.merchant_normalised!r}, "
            f"amount={self.amount}, date={self.txn_date})>"
        )


# ---------------------------------------------------------------------------
# Subscriptions -- detected recurring payment patterns
# ---------------------------------------------------------------------------
class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_normalised = Column(String(255), nullable=False)
    frequency = Column(String(20), nullable=False)  # weekly / monthly / ...
    median_interval_days = Column(Float, nullable=False)
    median_amount = Column(Float, nullable=False)
    last_amount = Column(Float, nullable=False)
    first_seen = Column(Date, nullable=False)
    last_seen = Column(Date, nullable=False)
    txn_count = Column(Integer, nullable=False)
    regularity_score = Column(Float, nullable=False)  # 0-1
    is_active = Column(Integer, nullable=False, default=1)  # boolean
    created_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        UniqueConstraint("merchant_normalised", "frequency", name="uq_sub_merchant_freq"),
        Index("ix_sub_active", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<Subscription(merchant={self.merchant_normalised!r}, "
            f"freq={self.frequency}, amount={self.median_amount})>"
        )


# ---------------------------------------------------------------------------
# Alerts -- issues found by the detection modules
# ---------------------------------------------------------------------------
class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_type = Column(String(30), nullable=False)  # recurring / duplicate / anomaly
    severity = Column(String(10), nullable=False, default="medium")  # low / medium / high
    merchant = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    detail = Column(Text, nullable=True)
    estimated_annual_cost = Column(Float, nullable=True)
    subscription_id = Column(Integer, nullable=True)  # FK not enforced for flexibility
    created_at = Column(DateTime, nullable=False, default=func.now())

    __table_args__ = (
        Index("ix_alert_type", "alert_type"),
    )

    def __repr__(self) -> str:
        return f"<Alert(type={self.alert_type!r}, merchant={self.merchant!r})>"


# ---------------------------------------------------------------------------
# Engine / session factory
# ---------------------------------------------------------------------------
engine = create_engine(DB_URL, echo=False, future=True)
Session = sessionmaker(bind=engine)


def init_db() -> None:
    """Create all tables (idempotent)."""
    Base.metadata.create_all(engine)
