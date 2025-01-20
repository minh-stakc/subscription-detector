-- ============================================================
-- Subscription Leak Detector -- raw DDL
-- This file mirrors the SQLAlchemy models and adds extra
-- indexes / views useful for ad-hoc analysis.
-- ============================================================

CREATE TABLE IF NOT EXISTS transactions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_date            DATE        NOT NULL,
    merchant_raw        VARCHAR(255) NOT NULL,
    merchant_normalised VARCHAR(255) NOT NULL,
    amount              REAL        NOT NULL,
    currency            VARCHAR(3)  NOT NULL DEFAULT 'USD',
    category            VARCHAR(100),
    fingerprint         VARCHAR(16) NOT NULL UNIQUE,
    source              VARCHAR(50),
    created_at          DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_txn_merchant_date
    ON transactions (merchant_normalised, txn_date);
CREATE INDEX IF NOT EXISTS ix_txn_date
    ON transactions (txn_date);


CREATE TABLE IF NOT EXISTS subscriptions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_normalised   VARCHAR(255) NOT NULL,
    frequency             VARCHAR(20)  NOT NULL,
    median_interval_days  REAL         NOT NULL,
    median_amount         REAL         NOT NULL,
    last_amount           REAL         NOT NULL,
    first_seen            DATE         NOT NULL,
    last_seen             DATE         NOT NULL,
    txn_count             INTEGER      NOT NULL,
    regularity_score      REAL         NOT NULL,
    is_active             INTEGER      NOT NULL DEFAULT 1,
    created_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (merchant_normalised, frequency)
);

CREATE INDEX IF NOT EXISTS ix_sub_active ON subscriptions (is_active);


CREATE TABLE IF NOT EXISTS alerts (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type            VARCHAR(30)  NOT NULL,
    severity              VARCHAR(10)  NOT NULL DEFAULT 'medium',
    merchant              VARCHAR(255) NOT NULL,
    title                 VARCHAR(255) NOT NULL,
    detail                TEXT,
    estimated_annual_cost REAL,
    subscription_id       INTEGER,
    created_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_alert_type ON alerts (alert_type);


-- ============================================================
-- Useful views
-- ============================================================

-- Monthly spend per merchant (for trend analysis)
CREATE VIEW IF NOT EXISTS v_monthly_merchant_spend AS
SELECT
    merchant_normalised,
    strftime('%Y-%m', txn_date) AS month,
    COUNT(*)                     AS txn_count,
    SUM(amount)                  AS total,
    AVG(amount)                  AS avg_amount,
    MIN(amount)                  AS min_amount,
    MAX(amount)                  AS max_amount
FROM transactions
GROUP BY merchant_normalised, strftime('%Y-%m', txn_date);


-- Merchants with potential recurring behaviour
CREATE VIEW IF NOT EXISTS v_recurring_candidates AS
SELECT
    merchant_normalised,
    COUNT(*)        AS txn_count,
    MIN(txn_date)   AS first_seen,
    MAX(txn_date)   AS last_seen,
    AVG(amount)      AS avg_amount,
    -- rough interval estimate
    CAST(
        (julianday(MAX(txn_date)) - julianday(MIN(txn_date)))
        / NULLIF(COUNT(*) - 1, 0) AS REAL
    ) AS est_interval_days
FROM transactions
GROUP BY merchant_normalised
HAVING COUNT(*) >= 3;


-- Alert summary by type
CREATE VIEW IF NOT EXISTS v_alert_summary AS
SELECT
    alert_type,
    severity,
    COUNT(*)                         AS cnt,
    SUM(estimated_annual_cost)       AS total_annual_cost
FROM alerts
GROUP BY alert_type, severity;
