"""Minimal transaction-safe notification and source state."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
from typing import cast

from .config import DEFAULT_MAXIMUM_SOURCE_AGE_SECONDS
from .model import (
    MINIMUM_OVERLAP_SECONDS,
    bounded_limit,
    compact_json,
    utc_datetime,
)

SCHEMA = """
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    high_water_mark TEXT,
    overlap_floor TEXT,
    overlap_seconds INTEGER NOT NULL CHECK (overlap_seconds >= 300),
    pagination_complete INTEGER NOT NULL CHECK (pagination_complete IN (0, 1)),
    raw_json TEXT NOT NULL
);
CREATE TABLE notifications (
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    event_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (
        category IN ('review_request', 'control_task', 'owned_feedback', 'ci_update')
    ),
    logical_cycle_id TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    actor TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('User', 'Bot')),
    occurred_at TEXT NOT NULL,
    head TEXT,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (source_id, event_id)
);
CREATE TABLE claims (
    logical_cycle_id TEXT PRIMARY KEY,
    category TEXT NOT NULL CHECK (
        category IN ('review_request', 'control_task', 'owned_feedback', 'ci_update')
    ),
    source_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'claimed', 'resolved', 'blocked', 'superseded')
    ),
    owner TEXT,
    terminal_event_id TEXT,
    FOREIGN KEY (source_id, event_id) REFERENCES notifications(source_id, event_id)
);
CREATE TABLE receipts (
    receipt_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    logical_cycle_id TEXT,
    status TEXT NOT NULL,
    raw_json TEXT NOT NULL
);
CREATE INDEX notifications_category ON notifications(category, occurred_at);
CREATE INDEX claims_pending ON claims(status, category);
CREATE INDEX receipts_source ON receipts(source_id, event_id);
CREATE TRIGGER receipts_are_append_only_on_update
    BEFORE UPDATE ON receipts
    BEGIN
        SELECT RAISE(ABORT, 'notification receipts are append-only');
    END;
CREATE TRIGGER receipts_are_append_only_on_delete
    BEFORE DELETE ON receipts
    BEGIN
        SELECT RAISE(ABORT, 'notification receipts are append-only');
    END;
"""

_TABLES = ("sources", "notifications", "claims", "receipts", "metadata")


class Store:
    """Own exactly one canonical, explicitly initialized notification cache."""

    def __init__(self, database: Path, *, initialize: bool = False) -> None:
        if initialize and database.exists():
            raise ValueError("refusing to initialize an existing database")
        if not initialize and not database.is_file():
            raise ValueError("notification database must be explicitly initialized")

        if initialize:
            descriptor = os.open(
                database, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600
            )
            os.close(descriptor)

        self.connection = sqlite3.connect(str(database), isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        _ = self.connection.execute("PRAGMA busy_timeout = 5000")
        _ = self.connection.execute("PRAGMA foreign_keys = ON")
        if initialize:
            _ = self.connection.executescript(SCHEMA)

        names = {
            cast(str, row["name"])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not set(_TABLES).issubset(names):
            self.connection.close()
            raise ValueError("database does not have the notification schema")

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_error: object) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        nested = self.connection.in_transaction
        _ = self.connection.execute(
            "SAVEPOINT notification_transaction" if nested else "BEGIN IMMEDIATE"
        )
        try:
            yield
        except BaseException:
            if nested:
                _ = self.connection.execute("ROLLBACK TO SAVEPOINT notification_transaction")
                _ = self.connection.execute("RELEASE SAVEPOINT notification_transaction")
            else:
                _ = self.connection.execute("ROLLBACK")
            raise
        else:
            _ = self.connection.execute(
                "RELEASE SAVEPOINT notification_transaction" if nested else "COMMIT"
            )

    def receipt(
        self,
        *,
        receipt_id: str,
        source_id: str,
        event_id: str,
        cycle: str | None,
        status: str,
        evidence: Mapping[str, object],
    ) -> bool:
        encoded = compact_json(evidence)
        row = self.connection.execute(
            "SELECT source_id, event_id, logical_cycle_id, status, raw_json "
            "FROM receipts WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        if row is not None:
            if tuple(row) != (source_id, event_id, cycle, status, encoded):
                raise ValueError("receipt ID conflicts with immutable evidence")
            return False

        _ = self.connection.execute(
            "INSERT INTO receipts "
            "(receipt_id, source_id, event_id, logical_cycle_id, status, raw_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (receipt_id, source_id, event_id, cycle, status, encoded),
        )
        return True

    def pending(
        self, *, limit: int = 12, category: str | None = None
    ) -> list[dict[str, object]]:
        if category is None:
            rows = self.connection.execute(
                "SELECT logical_cycle_id, category, source_id, event_id, "
                "subject_key, status, owner FROM claims "
                "WHERE status IN ('pending', 'claimed') "
                "ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, "
                "category, subject_key LIMIT ?",
                (bounded_limit(limit),),
            )
        else:
            rows = self.connection.execute(
                "SELECT logical_cycle_id, category, source_id, event_id, "
                "subject_key, status, owner FROM claims "
                "WHERE status IN ('pending', 'claimed') AND category = ? "
                "ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, "
                "subject_key LIMIT ?",
                (category, bounded_limit(limit)),
            )
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for name in _TABLES:
            row = self.connection.execute(
                f"SELECT count(*) AS total FROM {name}"
            ).fetchone()
            if row is None:
                raise ValueError("database did not return its table count")
            result[name] = row["total"]

        rows = self.connection.execute(
            "SELECT category, status, count(*) AS total "
            "FROM claims GROUP BY category, status ORDER BY category, status"
        )
        result["claim_categories"] = [dict(row) for row in rows]
        return result

    def health(
        self,
        *,
        limit: int = 12,
        maximum_age_seconds: int = DEFAULT_MAXIMUM_SOURCE_AGE_SECONDS,
        now: datetime | None = None,
    ) -> dict[str, object]:
        if isinstance(maximum_age_seconds, bool) or maximum_age_seconds < 1:
            raise ValueError("maximum source age must be positive")
        maximum = bounded_limit(limit)
        current = datetime.now(UTC) if now is None else now.astimezone(UTC)
        manifest = self.connection.execute(
            "SELECT value_json FROM metadata WHERE key = ?",
            ("required_notification_sources",),
        ).fetchone()
        expected: frozenset[str] | None = None
        if manifest is not None:
            value: object = json.loads(cast(str, manifest["value_json"]))
            if not isinstance(value, list):
                raise ValueError("configured notification sources are invalid")
            values = cast(list[object], value)
            if any(not isinstance(item, str) or not item for item in values):
                raise ValueError("configured notification sources are invalid")
            expected = frozenset(cast(list[str], values))
            if len(expected) != len(values):
                raise ValueError("configured notification sources are duplicated")

        columns = (
            "SELECT source_id, status, high_water_mark, overlap_floor, "
            "overlap_seconds, pagination_complete FROM sources"
        )
        if expected is None:
            rows = self.connection.execute(columns + " ORDER BY source_id")
        elif expected:
            placeholders = ", ".join("?" for _ in expected)
            rows = self.connection.execute(
                columns
                + f" WHERE source_id IN ({placeholders}) ORDER BY source_id",
                tuple(sorted(expected)),
            )
        else:
            rows = self.connection.execute(columns + " WHERE 0")

        examples: list[dict[str, object]] = []
        source_count = 0
        unhealthy_count = 0
        observed: set[str] = set()
        for row in rows:
            source_count += 1
            source = dict(row)
            observed.add(cast(str, source["source_id"]))
            checkpoint = source["high_water_mark"]
            fresh = isinstance(checkpoint, str) and (
                timedelta(0)
                <= current
                - utc_datetime(checkpoint, description="source checkpoint")
                <= timedelta(seconds=maximum_age_seconds)
            )
            overlap = source["overlap_seconds"]
            source["healthy"] = (
                source["status"] == "HEALTHY"
                and source["pagination_complete"] == 1
                and fresh
                and isinstance(overlap, int)
                and overlap >= MINIMUM_OVERLAP_SECONDS
            )
            if source["healthy"] is not True:
                unhealthy_count += 1
            if len(examples) < maximum:
                examples.append(source)

        missing = sorted(expected - observed) if expected is not None else []
        unhealthy_count += len(missing)

        row = self.connection.execute(
            "SELECT count(*) FROM claims WHERE status IN ('pending', 'claimed')"
        ).fetchone()
        if row is None:
            raise ValueError("database did not return pending notification count")

        heartbeat_row = self.connection.execute(
            "SELECT value_json FROM metadata WHERE key = ?",
            ("notification_heartbeat",),
        ).fetchone()
        heartbeat_observed_at: str | None = None
        heartbeat_healthy = False
        if heartbeat_row is not None:
            heartbeat_value: object = json.loads(
                cast(str, heartbeat_row["value_json"])
            )
            if not isinstance(heartbeat_value, dict):
                raise ValueError("notification heartbeat is invalid")
            heartbeat_timestamp = cast(dict[str, object], heartbeat_value).get(
                "observed_at"
            )
            if not isinstance(heartbeat_timestamp, str):
                raise ValueError("notification heartbeat lacks its observation time")
            heartbeat_observed_at = heartbeat_timestamp
            age = current - utc_datetime(
                heartbeat_observed_at, description="heartbeat observation"
            )
            heartbeat_healthy = timedelta(0) <= age <= timedelta(
                seconds=maximum_age_seconds
            )

        return {
            "status": (
                "healthy"
                if source_count and unhealthy_count == 0 and heartbeat_healthy
                else "degraded"
            ),
            "source_count": source_count,
            "unhealthy_sources": unhealthy_count,
            "missing_sources": missing,
            "sources": examples,
            "pending_notifications": row[0],
            "heartbeat_observed_at": heartbeat_observed_at,
            "heartbeat_healthy": heartbeat_healthy,
        }

    def heartbeat(self, *, owner: str, observed_at: str) -> dict[str, object]:
        timestamp = utc_datetime(observed_at, description="heartbeat observation")
        evidence: dict[str, object] = {
            "owner": owner,
            "observed_at": timestamp.isoformat(timespec="microseconds"),
        }
        with self.transaction():
            row = self.connection.execute(
                "SELECT value_json FROM metadata WHERE key = ?",
                ("notification_heartbeat",),
            ).fetchone()
            if row is not None:
                previous: object = json.loads(cast(str, row["value_json"]))
                if isinstance(previous, dict):
                    earlier = cast(dict[str, object], previous).get("observed_at")
                    if earlier is not None and timestamp < utc_datetime(
                        earlier, description="previous heartbeat"
                    ):
                        raise ValueError("heartbeat cannot regress")
            _ = self.connection.execute(
                "INSERT INTO metadata (key, value_json) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
                ("notification_heartbeat", compact_json(evidence)),
            )
        return evidence
