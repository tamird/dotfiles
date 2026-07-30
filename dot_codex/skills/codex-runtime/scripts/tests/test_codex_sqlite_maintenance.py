"""Behavioral tests for bounded native Codex log compaction."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sqlite3
import sys
import tempfile
import unittest
from collections.abc import Callable
from importlib.machinery import SourceFileLoader
from pathlib import Path
from threading import Timer
from types import SimpleNamespace
from typing import Literal, Protocol, TextIO, final, runtime_checkable
from unittest.mock import patch


class MaintenanceResult(Protocol):
    @property
    def status(
        self,
    ) -> Literal["target", "exhausted", "timeout", "stalled", "busy", "error"]: ...

    @property
    def reclaimed_bytes(self) -> int: ...

    @property
    def remaining_pages(self) -> int: ...

    @property
    def batches(self) -> int: ...


class CheckpointResult(Protocol):
    @property
    def busy(self) -> int: ...

    @property
    def frames(self) -> int: ...

    @property
    def checkpointed(self) -> int: ...


@runtime_checkable
class Maintenance(Protocol):
    BUSY_RETRY_DELAY_SECONDS: float
    BUSY_TIMEOUT_SECONDS: float
    CHUNK_PAGES: int
    MAX_SECONDS: int
    MAX_BUSY_RETRIES: int
    STALL_BATCHES: int

    def pragma(self, connection: sqlite3.Connection, name: str) -> int: ...

    def allocated_bytes(self, path: Path) -> int: ...

    def passive_checkpoint(
        self, connection: sqlite3.Connection
    ) -> CheckpointResult: ...

    def compact(
        self,
        path: Path,
        *,
        target_free_bytes: int,
        free_space: Callable[[Path], int],
        output: TextIO,
        allocated_space: Callable[[Path], int] = ...,
        clock: Callable[[], float] = ...,
    ) -> MaintenanceResult: ...

    def main(self, arguments: list[str]) -> int: ...


def load_maintenance() -> Maintenance:
    script = Path(__file__).resolve().parents[1] / "codex-sqlite-maintenance"
    loader = SourceFileLoader("codex_sqlite_maintenance", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("Cannot load the SQLite maintenance script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    if not isinstance(module, Maintenance):
        raise RuntimeError("SQLite maintenance script has an invalid interface")
    return module


def no_free_space(_: Path) -> int:
    return 0


def one_free_byte(_: Path) -> int:
    return 1


def unchanged_allocated_space(_: Path) -> int:
    return 4096


maintenance = load_maintenance()


@final
class SQLiteMaintenanceTests(unittest.TestCase):
    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.directory: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database: Path = Path(self.directory.name) / "logs.sqlite"
        with sqlite3.connect(str(self.database)) as connection:
            _ = connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
            _ = connection.execute("PRAGMA journal_mode=WAL")
            _ = connection.execute("CREATE TABLE logs (body BLOB NOT NULL)")
            _ = connection.executemany(
                "INSERT INTO logs VALUES (zeroblob(8192))",
                [()] * 96,
            )
            connection.commit()
            _ = connection.execute("DELETE FROM logs")
            connection.commit()

    def test_reclaims_existing_free_pages_without_deleting_rows(self) -> None:
        with sqlite3.connect(str(self.database)) as connection:
            _ = connection.execute("INSERT INTO logs VALUES (?)", (b"keep me",))
            connection.commit()
            before = maintenance.pragma(connection, "freelist_count")
        self.assertGreater(before, 0)

        result = maintenance.compact(
            self.database,
            target_free_bytes=1,
            free_space=no_free_space,
            output=io.StringIO(),
        )

        self.assertEqual(result.status, "exhausted")
        self.assertGreater(result.reclaimed_bytes, 0)
        self.assertEqual(result.remaining_pages, 0)
        self.assertEqual(result.batches, 1)
        with sqlite3.connect(str(self.database)) as connection:
            body: object = connection.execute("SELECT body FROM logs").fetchone()
            self.assertEqual(body, (b"keep me",))
            self.assertEqual(maintenance.pragma(connection, "freelist_count"), 0)
            journal: object = connection.execute("PRAGMA journal_mode").fetchone()
            self.assertEqual(journal, ("wal",))

    def test_does_nothing_when_filesystem_target_is_already_met(self) -> None:
        with sqlite3.connect(str(self.database)) as connection:
            before = maintenance.pragma(connection, "freelist_count")

        result = maintenance.compact(
            self.database,
            target_free_bytes=1,
            free_space=one_free_byte,
            output=io.StringIO(),
        )

        self.assertEqual(result.status, "target")
        self.assertEqual(result.reclaimed_bytes, 0)
        self.assertEqual(result.remaining_pages, before)

    def test_rejects_nonincremental_database_without_changing_it(self) -> None:
        database = Path(self.directory.name) / "not-incremental.sqlite"
        with sqlite3.connect(str(database)) as connection:
            _ = connection.execute("PRAGMA journal_mode=WAL")
            _ = connection.execute("CREATE TABLE logs (body BLOB NOT NULL)")
            _ = connection.execute("INSERT INTO logs VALUES (?)", (b"keep me",))
            connection.commit()

        with contextlib.redirect_stderr(io.StringIO()):
            result = maintenance.compact(
                database,
                target_free_bytes=1,
                free_space=no_free_space,
                output=io.StringIO(),
            )

        self.assertEqual(result.status, "error")
        with sqlite3.connect(str(database)) as connection:
            body: object = connection.execute("SELECT body FROM logs").fetchone()
            self.assertEqual(body, (b"keep me",))
            self.assertEqual(maintenance.pragma(connection, "auto_vacuum"), 0)

    def test_stops_without_waiting_behind_an_active_writer(self) -> None:
        with sqlite3.connect(str(self.database)) as blocker:
            before = maintenance.pragma(blocker, "freelist_count")
            _ = blocker.execute("BEGIN IMMEDIATE")

            with (
                patch.object(maintenance, "MAX_BUSY_RETRIES", 2),
                patch.object(maintenance, "BUSY_RETRY_DELAY_SECONDS", 0),
                patch.object(maintenance, "BUSY_TIMEOUT_SECONDS", 0.01),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = maintenance.compact(
                    self.database,
                    target_free_bytes=1,
                    free_space=no_free_space,
                    output=io.StringIO(),
                )

            self.assertEqual(result.status, "busy")
            self.assertEqual(result.reclaimed_bytes, 0)
            self.assertEqual(result.remaining_pages, before)
            blocker.rollback()

    def test_retries_transient_writer_before_reclaiming_free_pages(self) -> None:
        blocker = sqlite3.connect(str(self.database), check_same_thread=False)
        self.addCleanup(blocker.close)
        _ = blocker.execute("BEGIN IMMEDIATE")
        release = Timer(0.04, blocker.rollback)
        release.start()
        self.addCleanup(release.join)

        with (
            patch.object(maintenance, "BUSY_TIMEOUT_SECONDS", 0.01),
            patch.object(maintenance, "BUSY_RETRY_DELAY_SECONDS", 0.005),
        ):
            result = maintenance.compact(
                self.database,
                target_free_bytes=1,
                free_space=no_free_space,
                output=io.StringIO(),
            )

        self.assertEqual(result.status, "exhausted")
        self.assertGreater(result.reclaimed_bytes, 0)
        self.assertEqual(result.remaining_pages, 0)

    def test_stops_when_reclaimed_pages_do_not_free_disk_space(self) -> None:
        with sqlite3.connect(str(self.database)) as connection:
            before = maintenance.pragma(connection, "freelist_count")
        self.assertGreater(before, 16)

        with (
            patch.object(maintenance, "CHUNK_PAGES", 8),
            patch.object(maintenance, "STALL_BATCHES", 2),
        ):
            result = maintenance.compact(
                self.database,
                target_free_bytes=1,
                free_space=no_free_space,
                allocated_space=unchanged_allocated_space,
                output=io.StringIO(),
            )

        self.assertEqual(result.status, "stalled")
        self.assertEqual(result.batches, 2)
        self.assertEqual(result.reclaimed_bytes, 16 * 4096)
        self.assertEqual(result.remaining_pages, before - 16)

    def test_allocated_bytes_includes_the_active_wal(self) -> None:
        with sqlite3.connect(str(self.database), isolation_level=None) as writer:
            _ = writer.execute("INSERT INTO logs VALUES (zeroblob(32768))")
            main_allocation = self.database.stat().st_blocks * 512

            self.assertGreater(
                maintenance.allocated_bytes(self.database), main_allocation
            )

    def test_passive_checkpoint_reclaims_wal_before_stall_decision(self) -> None:
        free_values = iter((0, 0, 0, 1))
        checkpoints: list[CheckpointResult] = []
        original_checkpoint = maintenance.passive_checkpoint

        def eventually_free(_: Path) -> int:
            return next(free_values)

        def record_checkpoint(connection: sqlite3.Connection) -> CheckpointResult:
            result = original_checkpoint(connection)
            checkpoints.append(result)
            return result

        with (
            patch.object(maintenance, "CHUNK_PAGES", 8),
            patch.object(maintenance, "STALL_BATCHES", 2),
            patch.object(maintenance, "passive_checkpoint", record_checkpoint),
        ):
            result = maintenance.compact(
                self.database,
                target_free_bytes=1,
                free_space=eventually_free,
                output=io.StringIO(),
            )

        self.assertEqual(result.status, "target")
        self.assertEqual(result.batches, 2)
        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(checkpoints[0].busy, 0)
        self.assertEqual(checkpoints[0].checkpointed, checkpoints[0].frames)

    def test_stops_when_an_active_reader_prevents_wal_reclamation(self) -> None:
        checkpoints: list[CheckpointResult] = []
        original_checkpoint = maintenance.passive_checkpoint

        def record_checkpoint(connection: sqlite3.Connection) -> CheckpointResult:
            result = original_checkpoint(connection)
            checkpoints.append(result)
            return result

        with sqlite3.connect(str(self.database), isolation_level=None) as reader:
            _ = reader.execute("BEGIN")
            _ = reader.execute("SELECT COUNT(*) FROM logs").fetchone()

            with (
                patch.object(maintenance, "CHUNK_PAGES", 8),
                patch.object(maintenance, "STALL_BATCHES", 2),
                patch.object(maintenance, "passive_checkpoint", record_checkpoint),
            ):
                result = maintenance.compact(
                    self.database,
                    target_free_bytes=1,
                    free_space=no_free_space,
                    allocated_space=unchanged_allocated_space,
                    output=io.StringIO(),
                )

            reader.rollback()

        self.assertEqual(result.status, "stalled")
        self.assertEqual(result.batches, 2)
        self.assertEqual(len(checkpoints), 1)
        self.assertGreater(checkpoints[0].frames, checkpoints[0].checkpointed)

    def test_tolerates_a_concurrent_writer_consuming_free_pages(self) -> None:
        with sqlite3.connect(str(self.database)) as connection:
            before = maintenance.pragma(connection, "freelist_count")
        self.assertGreater(before, 24)

        free_values = iter((0, 0, 0, 1))

        def gradually_available(_: Path) -> int:
            return next(free_values)

        original_pragma = maintenance.pragma
        freelist_reads = 0

        with sqlite3.connect(
            str(self.database), isolation_level=None
        ) as concurrent_writer:

            def consume_free_page(connection: sqlite3.Connection, name: str) -> int:
                nonlocal freelist_reads
                if name == "freelist_count":
                    if freelist_reads:
                        _ = concurrent_writer.execute(
                            "INSERT INTO logs VALUES (zeroblob(4096))"
                        )
                    freelist_reads += 1
                return original_pragma(connection, name)

            with (
                patch.object(maintenance, "CHUNK_PAGES", 8),
                patch.object(maintenance, "pragma", consume_free_page),
            ):
                result = maintenance.compact(
                    self.database,
                    target_free_bytes=1,
                    free_space=gradually_available,
                    output=io.StringIO(),
                )

        self.assertEqual(result.status, "target")
        self.assertEqual(result.batches, 3)
        self.assertGreater(result.reclaimed_bytes, 0)
        self.assertNotEqual(result.reclaimed_bytes, 24 * 4096)
        self.assertEqual(
            result.remaining_pages, before - result.reclaimed_bytes // 4096
        )
        with sqlite3.connect(str(self.database)) as connection:
            row: object = connection.execute("SELECT COUNT(*) FROM logs").fetchone()
            self.assertEqual(row, (3,))

    def test_stops_at_deadline_without_modifying_database(self) -> None:
        with sqlite3.connect(str(self.database)) as connection:
            before = maintenance.pragma(connection, "freelist_count")
        moments = iter((0.0, float(maintenance.MAX_SECONDS)))

        result = maintenance.compact(
            self.database,
            target_free_bytes=1,
            free_space=no_free_space,
            clock=moments.__next__,
            output=io.StringIO(),
        )

        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.reclaimed_bytes, 0)
        self.assertEqual(result.remaining_pages, before)

    def test_missing_database_is_never_created(self) -> None:
        missing = Path(self.directory.name) / "missing.sqlite"

        with contextlib.redirect_stderr(io.StringIO()):
            result = maintenance.compact(
                missing,
                target_free_bytes=1,
                free_space=no_free_space,
                output=io.StringIO(),
            )

        self.assertEqual(result.status, "error")
        self.assertFalse(missing.exists())

    def test_main_rejects_arguments_without_opening_database(self) -> None:
        with patch.object(maintenance, "compact") as compact:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(maintenance.main(["unexpected"]), 2)
        compact.assert_not_called()

    def test_main_preserves_default_fifty_gib_target(self) -> None:
        result = SimpleNamespace(
            status="target", reclaimed_bytes=0, remaining_pages=0, batches=0
        )
        with patch.object(maintenance, "compact", return_value=result) as compact:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(maintenance.main([]), 0)

        compact.assert_called_once_with(
            Path.home() / ".codex" / "logs_2.sqlite",
            target_free_bytes=50 * 1024**3,
        )

    def test_main_accepts_explicit_free_space_target(self) -> None:
        result = SimpleNamespace(
            status="target", reclaimed_bytes=0, remaining_pages=0, batches=0
        )
        with patch.object(maintenance, "compact", return_value=result) as compact:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(maintenance.main(["--target-free-gib", "70"]), 0)

        compact.assert_called_once_with(
            Path.home() / ".codex" / "logs_2.sqlite",
            target_free_bytes=70 * 1024**3,
        )

    def test_main_rejects_nonpositive_free_space_target(self) -> None:
        with patch.object(maintenance, "compact") as compact:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(maintenance.main(["--target-free-gib", "0"]), 2)

        compact.assert_not_called()

    def test_help_never_opens_or_compacts_database(self) -> None:
        with patch.object(maintenance, "compact") as compact:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(maintenance.main(["--help"]), 0)
        compact.assert_not_called()


if __name__ == "__main__":
    _ = unittest.main()
