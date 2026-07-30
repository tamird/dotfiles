"""Portable notification configuration without import-time private access."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

DEFAULT_MAXIMUM_SOURCE_AGE_SECONDS = 120


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Locate owner-private state separately from public intake source."""

    database: Path
    maximum_source_age_seconds: int = DEFAULT_MAXIMUM_SOURCE_AGE_SECONDS

    @classmethod
    def from_environment(cls) -> RuntimeConfig:
        configured = os.environ.get("CODEX_NOTIFICATION_WATCHER_DATABASE")
        database = (
            Path(configured).expanduser()
            if configured
            else Path.home()
            / "Google Drive"
            / "My Drive"
            / "Codex"
            / "runtime"
            / "review-monitor"
            / "notifications.sqlite3"
        )
        value = os.environ.get("CODEX_NOTIFICATION_WATCHER_MAXIMUM_SOURCE_AGE")
        if value is None:
            return cls(database)
        try:
            age = int(value)
        except ValueError as error:
            raise ValueError(
                "maximum source age must be a positive integer"
            ) from error
        if age < 1:
            raise ValueError("maximum source age must be a positive integer")
        return cls(database, age)
