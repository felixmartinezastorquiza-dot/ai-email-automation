"""Postgres storage for emails and their triage results."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.classifier import TriageResult, TriageStatus
from app.emails import IncomingEmail

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id             BIGSERIAL PRIMARY KEY,
    from_name      TEXT NOT NULL,
    from_email     TEXT NOT NULL,
    subject        TEXT NOT NULL,
    body           TEXT NOT NULL,
    received_at    TIMESTAMPTZ NOT NULL,
    source         TEXT NOT NULL,              -- 'sample' or 'form'
    status         TEXT NOT NULL DEFAULT 'new',-- new | processing | processed | needs_review
    category       TEXT,
    urgency        TEXT,
    contact_name   TEXT,
    phone          TEXT,
    property       TEXT,
    requested_date DATE,
    summary        TEXT,
    attempts       INTEGER NOT NULL DEFAULT 0,
    problems       JSONB NOT NULL DEFAULT '[]',
    processed_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS emails_status_idx ON emails (status);
"""

URGENCY_ORDER = "CASE urgency WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 3 END"


class EmailStatus(StrEnum):
    NEW = "new"
    PROCESSING = "processing"
    PROCESSED = "processed"
    NEEDS_REVIEW = "needs_review"


class EmailFilter(StrEnum):
    ALL = "all"
    HIGH = "high"
    VIEWING = "viewing_request"
    COMPLAINT = "complaint"
    INQUIRY = "inquiry"
    SPAM = "spam"
    REVIEW = "needs_review"


FILTER_SQL: dict[EmailFilter, str] = {
    EmailFilter.ALL: "status IN ('processed', 'needs_review')",
    EmailFilter.HIGH: "urgency = 'high'",
    EmailFilter.VIEWING: "category = 'viewing_request'",
    EmailFilter.COMPLAINT: "category = 'complaint'",
    EmailFilter.INQUIRY: "category = 'inquiry'",
    EmailFilter.SPAM: "category = 'spam'",
    EmailFilter.REVIEW: "status = 'needs_review'",
}


@dataclass(frozen=True)
class StoredEmail:
    id: int
    from_name: str
    from_email: str
    subject: str
    body: str
    received_at: datetime
    source: str
    status: str
    category: str | None
    urgency: str | None
    contact_name: str | None
    phone: str | None
    property: str | None
    requested_date: date | None
    summary: str | None
    attempts: int
    problems: list[str]
    processed_at: datetime | None


@dataclass(frozen=True)
class InboxStats:
    new: int
    processed: int
    needs_review: int
    high_urgency: int


def _row_to_email(row: dict[str, Any]) -> StoredEmail:
    return StoredEmail(**row)


class EmailStore:
    def __init__(self, database_url: str, max_connections: int = 5) -> None:
        # A pool reuses open connections: opening a new TLS connection per query is slow.
        self._pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=max_connections,
            kwargs={"row_factory": dict_row, "connect_timeout": 15},
            # Serverless Postgres drops idle connections; test each one before use.
            check=ConnectionPool.check_connection,
            max_idle=300,
            open=True,
        )

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        """Borrow a connection; the transaction commits on success, rolls back on error."""
        with self._pool.connection() as conn:
            yield conn

    def close(self) -> None:
        self._pool.close()

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(SCHEMA)

    def add(self, email: IncomingEmail, source: str) -> StoredEmail:
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO emails (from_name, from_email, subject, body, received_at, source) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
                (
                    email.from_name,
                    email.from_email,
                    email.subject,
                    email.body,
                    email.received_at,
                    source,
                ),
            ).fetchone()
        return _row_to_email(row)

    def reset(self, samples: list[IncomingEmail]) -> None:
        """Delete everything and load the sample inbox again, unprocessed."""
        with self._connect() as conn:
            conn.execute("DELETE FROM emails")
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO emails (from_name, from_email, subject, body, received_at, "
                    "source) VALUES (%s, %s, %s, %s, %s, 'sample')",
                    [
                        (e.from_name, e.from_email, e.subject, e.body, e.received_at)
                        for e in samples
                    ],
                )

    def is_empty(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT NOT EXISTS (SELECT 1 FROM emails) AS empty").fetchone()
        return bool(row and row["empty"])

    def claim_next(self) -> StoredEmail | None:
        """Take the oldest new email. SKIP LOCKED lets concurrent workers never share one."""
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE emails SET status = 'processing' WHERE id = ("
                "  SELECT id FROM emails WHERE status = 'new' "
                "  ORDER BY received_at, id LIMIT 1 FOR UPDATE SKIP LOCKED"
                ") RETURNING *"
            ).fetchone()
        return _row_to_email(row) if row else None

    def claim(self, email_id: int) -> StoredEmail | None:
        """Take one specific new email (used for form submissions)."""
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE emails SET status = 'processing' WHERE id = %s AND status = 'new' "
                "RETURNING *",
                (email_id,),
            ).fetchone()
        return _row_to_email(row) if row else None

    def release(self, email_id: int) -> None:
        """Put a claimed email back in the queue (e.g. the AI service was down)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE emails SET status = 'new' WHERE id = %s AND status = 'processing'",
                (email_id,),
            )

    def save_result(self, email_id: int, result: TriageResult) -> StoredEmail:
        analysis = result.analysis
        status = (
            EmailStatus.PROCESSED
            if result.status == TriageStatus.PROCESSED
            else EmailStatus.NEEDS_REVIEW
        )
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE emails SET status = %s, category = %s, urgency = %s, contact_name = %s, "
                "phone = %s, property = %s, requested_date = %s, summary = %s, attempts = %s, "
                "problems = %s, processed_at = now() WHERE id = %s RETURNING *",
                (
                    status,
                    analysis.category if analysis else None,
                    analysis.urgency if analysis else None,
                    analysis.contact_name if analysis else None,
                    analysis.phone if analysis else None,
                    analysis.property if analysis else None,
                    analysis.requested_date if analysis else None,
                    analysis.summary if analysis else None,
                    result.attempts,
                    json.dumps(result.problems),
                    email_id,
                ),
            ).fetchone()
        return _row_to_email(row)

    def get(self, email_id: int) -> StoredEmail | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM emails WHERE id = %s", (email_id,)).fetchone()
        return _row_to_email(row) if row else None

    def list_emails(self, email_filter: EmailFilter = EmailFilter.ALL) -> list[StoredEmail]:
        """Triaged emails: items for human review first, then by urgency, newest first."""
        where = FILTER_SQL[email_filter]  # fixed SQL from a whitelist, never user input
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM emails WHERE {where} "
                f"ORDER BY (status = 'needs_review') DESC, {URGENCY_ORDER}, received_at DESC"
            ).fetchall()
        return [_row_to_email(row) for row in rows]

    def triaged(self) -> list[StoredEmail]:
        """Every triaged email in the inbox, most urgent first.

        In the demo the inbox stands for one working day; in production this would filter
        by processed_at for the day being summarized.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM emails WHERE status IN ('processed', 'needs_review') "
                f"ORDER BY {URGENCY_ORDER}, received_at"
            ).fetchall()
        return [_row_to_email(row) for row in rows]

    def stats(self) -> InboxStats:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT "
                "count(*) FILTER (WHERE status IN ('new', 'processing')) AS new, "
                "count(*) FILTER (WHERE status = 'processed') AS processed, "
                "count(*) FILTER (WHERE status = 'needs_review') AS needs_review, "
                "count(*) FILTER (WHERE urgency = 'high') AS high_urgency "
                "FROM emails"
            ).fetchone()
        return InboxStats(**row) if row else InboxStats(0, 0, 0, 0)
