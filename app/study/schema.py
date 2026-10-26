"""Additive, idempotent schema; paid file bytes never live in public static files."""

SQL = """
CREATE TABLE IF NOT EXISTS study_lessons (
    slug VARCHAR(80) PRIMARY KEY,
    title VARCHAR(160) NOT NULL,
    subject VARCHAR(24) NOT NULL CHECK (subject IN
        ('math','physics','chemistry','biology','english','computing')),
    description VARCHAR(1200) NOT NULL,
    pages INTEGER NOT NULL CHECK (pages BETWEEN 1 AND 40),
    pdf_data BYTEA NOT NULL,
    pdf_sha256 CHAR(64) NOT NULL UNIQUE,
    cover_data BYTEA NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS study_lessons_release ON study_lessons(published_at DESC);
CREATE TABLE IF NOT EXISTS study_purchases (
    transaction_id VARCHAR(160) NOT NULL,
    product_key VARCHAR(80) NOT NULL,
    buyer_email TEXT NOT NULL,
    paid_at TIMESTAMPTZ,
    refunded_at TIMESTAMPTZ,
    PRIMARY KEY (transaction_id, product_key)
);
CREATE INDEX IF NOT EXISTS study_purchase_access
    ON study_purchases(buyer_email, product_key) WHERE refunded_at IS NULL;
"""


async def init_study_schema(conn):
    await conn.execute(SQL)
