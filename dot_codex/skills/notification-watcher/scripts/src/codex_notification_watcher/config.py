"""Portable notification configuration without import-time private access."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
from typing import cast

DEFAULT_MAXIMUM_SOURCE_AGE_SECONDS = 120


def require_writer_leadership(database: Path) -> None:
    """Permit canonical notification writes only on the elected machine."""
    home = Path.home()
    runtime = (home / "Google Drive" / "My Drive" / "Codex" / "runtime").resolve()
    local = (home / ".cache" / "codex" / "review-monitor").resolve()
    location = database.resolve()
    if not location.is_relative_to(runtime) and not location.is_relative_to(local):
        return

    marker = runtime / "backup-leader.json"
    if not marker.is_file() or marker.is_symlink():
        raise PermissionError("notification writer has no elected leader")
    with marker.open(encoding="utf-8") as source:
        value: object = json.load(source)
    if not isinstance(value, dict):
        raise ValueError("shared notification leader record is invalid")
    leader = cast(dict[object, object], value).get("hostname")
    if not isinstance(leader, str) or not leader:
        raise ValueError("shared notification leader record is invalid")
    if leader != socket.gethostname():
        raise PermissionError(
            "notification state can only be written by its elected leader"
        )


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
            / ".cache"
            / "codex"
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
