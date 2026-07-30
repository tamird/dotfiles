"""Behavioral coverage of safe, explicitly allowlisted Codex backups."""

from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
from importlib.machinery import SourceFileLoader
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Timer
import time
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "codex-state-backup"
SPEC = importlib.util.spec_from_loader(
    "codex_state_backup", SourceFileLoader("codex_state_backup", str(SCRIPT))
)
assert SPEC is not None and SPEC.loader is not None
backup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backup
SPEC.loader.exec_module(backup)


class StateBackupTests(unittest.TestCase):
    temporary: tempfile.TemporaryDirectory[str]
    codex_home: Path
    destination: Path
    configuration: object

    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.codex_home = root / "codex"
        self.destination = root / "visible" / "runtime"
        self.configuration = backup.Configuration(
            codex_home=self.codex_home,
            destination=self.destination,
            large_database_bytes=1024,
            large_database_interval=3600,
            small_database_interval=300,
        )

    def setUp(self) -> None:
        self.addCleanup(self.temporary.cleanup)
        self.codex_home.mkdir()

    def elect_leader(self, hostname: str = "test-leader") -> None:
        with patch.object(backup.socket, "gethostname", return_value=hostname):
            backup._elect_leader(self.configuration)

    def test_default_configuration_uses_shared_google_drive(self) -> None:
        home = self.codex_home.parent
        with patch.object(backup.Path, "home", return_value=home):
            configuration = backup.default_configuration()

        self.assertEqual(configuration.codex_home, home / ".codex")
        self.assertEqual(
            configuration.destination,
            home / "Google Drive" / "My Drive" / "Codex" / "runtime",
        )

    def create_database(self, name: str, *, wal: bool = False) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.codex_home / name))
        if wal:
            connection.execute("PRAGMA journal_mode=WAL").fetchone()
        connection.execute("CREATE TABLE records(value TEXT NOT NULL)")
        connection.execute("INSERT INTO records VALUES ('original')")
        connection.commit()
        return connection

    def test_online_backup_includes_a_live_wal_transaction(self) -> None:
        connection = self.create_database("state_5.sqlite", wal=True)
        self.addCleanup(connection.close)
        connection.execute("INSERT INTO records VALUES ('wal-value')")
        connection.commit()

        result = backup.backup_database(
            backup.database_sources(self.configuration)[0], self.configuration
        )

        self.assertEqual(result["status"], "completed")
        with sqlite3.connect(
            str(self.destination / "database-snapshots" / "state.sqlite")
        ) as restored:
            self.assertEqual(restored.execute("PRAGMA journal_mode").fetchone(), ("delete",))
            self.assertEqual(
                restored.execute("SELECT value FROM records ORDER BY value").fetchall(),
                [("original",), ("wal-value",)],
            )
        self.assertFalse(
            (self.destination / "database-snapshots" / "state.sqlite-wal").exists()
        )
        self.assertFalse(
            (self.destination / "database-snapshots" / "state.sqlite-shm").exists()
        )

    def test_online_backup_bootstraps_missing_wal_sidecars(self) -> None:
        connection = self.create_database("memories_1.sqlite", wal=True)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        connection.close()
        source = backup.database_sources(self.configuration)[2]
        for suffix in ("-wal", "-shm"):
            Path(str(source.source) + suffix).unlink(missing_ok=True)

        self.assertFalse(Path(str(source.source) + "-wal").exists())
        self.assertFalse(Path(str(source.source) + "-shm").exists())

        with patch.object(backup.sqlite3, "connect", wraps=sqlite3.connect) as connect:
            result = backup.backup_database(source, self.configuration)

        self.assertEqual(result["status"], "completed")
        self.assertTrue(connect.call_args_list[0].args[0].endswith("?mode=rw"))
        with sqlite3.connect(str(source.destination)) as restored:
            self.assertEqual(
                restored.execute("SELECT value FROM records").fetchall(),
                [("original",)],
            )
        with sqlite3.connect(str(source.source)) as original:
            self.assertEqual(
                original.execute("SELECT value FROM records").fetchall(),
                [("original",)],
            )

    def test_online_backup_waits_for_a_transient_writer(self) -> None:
        connection = self.create_database("memories_1.sqlite")
        connection.close()
        source = backup.database_sources(self.configuration)[2]
        backup.backup_database(source, self.configuration)

        writer = sqlite3.connect(str(source.source), check_same_thread=False)
        self.addCleanup(writer.close)
        writer.execute("INSERT INTO records VALUES ('committed')")
        writer.commit()
        writer.execute("BEGIN EXCLUSIVE")
        release = Timer(0.05, writer.rollback)
        release.start()
        try:
            result = backup.backup_database(
                source,
                self.configuration,
                now=(
                    source.destination.stat().st_mtime
                    + self.configuration.large_database_interval
                    + 1
                ),
            )
        finally:
            release.join()

        self.assertEqual(result["status"], "completed")
        with sqlite3.connect(str(source.destination)) as restored:
            self.assertEqual(
                restored.execute("SELECT value FROM records ORDER BY value").fetchall(),
                [("committed",), ("original",)],
            )

    def test_unchanged_database_is_not_rewritten(self) -> None:
        connection = self.create_database("goals_1.sqlite")
        self.addCleanup(connection.close)
        source = backup.database_sources(self.configuration)[1]
        backup.backup_database(source, self.configuration)
        previous = source.destination.stat().st_mtime_ns

        result = backup.backup_database(source, self.configuration)

        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(source.destination.stat().st_mtime_ns, previous)

    def test_changed_large_database_is_throttled(self) -> None:
        connection = self.create_database("state_5.sqlite")
        self.addCleanup(connection.close)
        source = backup.database_sources(self.configuration)[0]
        backup.backup_database(source, self.configuration)
        connection.execute("INSERT INTO records VALUES ('later')")
        connection.commit()
        destination_modified = source.destination.stat().st_mtime
        source_modified = time.time_ns() + 1_000_000_000
        os.utime(source.source, ns=(source_modified, source_modified))

        result = backup.backup_database(
            source, self.configuration, now=destination_modified + 60
        )

        self.assertEqual(result["status"], "throttled")
        self.assertEqual(result["interval_seconds"], 3600)

    def test_missing_database_is_not_created(self) -> None:
        source = backup.database_sources(self.configuration)[2]

        result = backup.backup_database(source, self.configuration)

        self.assertEqual(result["status"], "missing")
        self.assertFalse(source.source.exists())
        self.assertFalse(source.destination.exists())

    def test_corrupt_database_never_replaces_existing_snapshot(self) -> None:
        source = backup.database_sources(self.configuration)[0]
        source.source.write_bytes(b"not a database")
        source.destination.parent.mkdir(parents=True)
        source.destination.write_bytes(b"prior-safe-snapshot")

        with self.assertRaises(sqlite3.DatabaseError):
            backup._backup_sqlite(source.source, source.destination)

        self.assertEqual(source.destination.read_bytes(), b"prior-safe-snapshot")
        self.assertEqual(
            list(source.destination.parent.glob(".state.sqlite.*.tmp")), []
        )

    def test_database_failure_records_safe_sqlite_diagnostics(self) -> None:
        self.elect_leader()
        connection = self.create_database("memories_1.sqlite")
        self.addCleanup(connection.close)
        source = backup.database_sources(self.configuration)[2]
        with sqlite3.connect(
            "file:" + str(source.source) + "?mode=ro", uri=True
        ) as readonly:
            with self.assertRaises(sqlite3.OperationalError) as failure:
                readonly.execute("INSERT INTO records VALUES ('rejected')")

        with patch.object(backup.socket, "gethostname", return_value="test-leader"):
            with patch.object(backup, "_backup_sqlite", side_effect=failure.exception):
                result = backup.run_backup(self.configuration)

        memory = next(
            item for item in result["sources"] if item["name"] == "memories"
        )
        self.assertEqual(memory["status"], "error")
        self.assertEqual(memory["error_type"], "OperationalError")
        for field in ("sqlite_errorcode", "sqlite_errorname"):
            with self.subTest(field=field):
                expected = getattr(failure.exception, field, None)
                if expected is None:
                    self.assertNotIn(field, memory)
                else:
                    self.assertEqual(memory[field], expected)
        self.assertNotIn("error", memory)

    def test_full_run_excludes_credentials_and_large_logs(self) -> None:
        self.elect_leader()
        for name in ("auth.json", "config.toml", "logs_2.sqlite"):
            (self.codex_home / name).write_text("must-not-copy", encoding="utf-8")
        (self.codex_home / "history.jsonl").write_text("history\n", encoding="utf-8")

        with patch.object(backup.socket, "gethostname", return_value="test-leader"):
            result = backup.run_backup(self.configuration)

        self.assertEqual(result["status"], "error")
        self.assertEqual(
            (self.destination / "history.jsonl").read_text(encoding="utf-8"),
            "history\n",
        )
        for name in ("auth.json", "config.toml", "logs_2.sqlite"):
            self.assertFalse((self.destination / name).exists())
        with (self.destination / "backup-status.json").open(encoding="utf-8") as f:
            recorded = json.load(f)
        self.assertEqual(recorded["status"], "error")

    def test_unchanged_files_are_not_rewritten(self) -> None:
        source = backup.file_sources(self.configuration)[0]
        source.source.write_text("history", encoding="utf-8")
        backup.backup_file(source)
        previous = source.destination.stat().st_mtime_ns

        result = backup.backup_file(source)

        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(source.destination.stat().st_mtime_ns, previous)

    def test_restore_missing_restores_only_absent_database(self) -> None:
        connection = self.create_database("goals_1.sqlite")
        connection.close()
        source = backup.database_sources(self.configuration)[1]
        backup.backup_database(source, self.configuration)
        source.source.unlink()

        result = backup.restore_missing(self.configuration)

        self.assertEqual(result["status"], "ok")
        with sqlite3.connect(str(source.source)) as restored:
            self.assertEqual(
                restored.execute("SELECT value FROM records").fetchall(),
                [("original",)],
            )

    def test_restore_never_overwrites_an_existing_database(self) -> None:
        connection = self.create_database("goals_1.sqlite")
        connection.close()
        source = backup.database_sources(self.configuration)[1]
        backup.backup_database(source, self.configuration)
        with sqlite3.connect(str(source.source)) as current:
            current.execute("INSERT INTO records VALUES ('keep-me')")
            current.commit()

        result = backup.restore_missing(self.configuration)

        self.assertEqual(result["status"], "ok")
        with sqlite3.connect(str(source.source)) as current:
            self.assertEqual(
                current.execute("SELECT value FROM records ORDER BY value").fetchall(),
                [("keep-me",), ("original",)],
            )

    def test_restore_refuses_an_orphaned_wal(self) -> None:
        source = backup.database_sources(self.configuration)[1]
        source.destination.parent.mkdir(parents=True)
        source.destination.write_bytes(b"snapshot")
        Path(str(source.source) + "-wal").write_bytes(b"live")

        result = backup.restore_missing(self.configuration)

        self.assertIn(
            {"name": source.name, "status": "existing"}, result["sources"]
        )
        self.assertFalse(source.source.exists())

    def test_status_reports_missing_backup_without_creating_state(self) -> None:
        result = backup.read_status(self.configuration)

        self.assertEqual(result, {"status": "not_started"})
        self.assertFalse(self.destination.exists())

    def test_notification_database_has_transactional_standalone_snapshot(self) -> None:
        sources = backup.database_sources(self.configuration)
        notification = next(source for source in sources if source.name == "notifications")
        notification.source.parent.mkdir(parents=True)
        with sqlite3.connect(str(notification.source)) as database:
            database.execute("PRAGMA journal_mode=WAL")
            database.execute("CREATE TABLE receipts(value TEXT NOT NULL)")
            database.execute("INSERT INTO receipts VALUES ('verified')")

        result = backup.backup_database(notification, self.configuration)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            notification.destination,
            self.destination / "database-snapshots" / "notifications.sqlite",
        )
        with sqlite3.connect(str(notification.destination)) as restored:
            self.assertEqual(restored.execute("PRAGMA journal_mode").fetchone(), ("delete",))
            self.assertEqual(
                restored.execute("SELECT value FROM receipts").fetchall(),
                [("verified",)],
            )
        self.assertFalse(Path(str(notification.destination) + "-wal").exists())
        self.assertFalse(Path(str(notification.destination) + "-shm").exists())

    def test_paginated_thread_history_is_backed_up_when_present(self) -> None:
        connection = self.create_database("thread_history_1.sqlite", wal=True)
        self.addCleanup(connection.close)

        sources = backup.database_sources(self.configuration)
        history = next(item for item in sources if item.name == "thread-history")
        result = backup.backup_database(history, self.configuration)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(history.destination.name, "thread-history.sqlite")
        with sqlite3.connect(str(history.destination)) as snapshot:
            self.assertEqual(
                snapshot.execute("SELECT value FROM records").fetchall(),
                [("original",)],
            )

    def test_paginated_thread_history_snapshot_is_restored_when_local_is_missing(
        self,
    ) -> None:
        destination = (
            self.destination / "database-snapshots" / "thread-history.sqlite"
        )
        destination.parent.mkdir(parents=True)
        with sqlite3.connect(str(destination)) as snapshot:
            snapshot.execute("CREATE TABLE records(value TEXT NOT NULL)")
            snapshot.execute("INSERT INTO records VALUES ('paginated')")

        result = backup.restore_missing(self.configuration)

        self.assertEqual(result["status"], "ok")
        self.assertIn(
            {"name": "thread-history", "status": "restored"}, result["sources"]
        )
        with sqlite3.connect(str(self.codex_home / "thread_history_1.sqlite")) as local:
            self.assertEqual(
                local.execute("SELECT value FROM records").fetchall(),
                [("paginated",)],
            )

    def test_visible_review_archives_are_not_self_copied(self) -> None:
        source = backup.file_sources(self.configuration)[1]
        source.source.parent.mkdir(parents=True)
        source.source.write_text("watermark", encoding="utf-8")
        before = source.source.stat().st_mtime_ns

        result = backup.backup_file(source)

        self.assertEqual(source.source, source.destination)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(source.source.stat().st_mtime_ns, before)

    def test_missing_required_database_degrades_the_backup(self) -> None:
        self.elect_leader()

        with patch.object(backup.socket, "gethostname", return_value="test-leader"):
            result = backup.run_backup(self.configuration)

        self.assertEqual(result["status"], "error")
        with (self.destination / "backup-status.json").open(encoding="utf-8") as f:
            self.assertEqual(json.load(f)["status"], "error")

    def test_launch_agent_is_generated_for_the_current_machine(self) -> None:
        import plistlib
        import subprocess
        from unittest.mock import patch

        with patch.object(backup.Path, "home", return_value=self.codex_home):
            with patch.object(
                backup.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess([], 1),
                    subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 0),
                ],
            ) as launch:
                with patch.object(backup.socket, "gethostname", return_value="test-leader"):
                    result = backup.install(self.configuration, role="leader")

        path = (
            self.codex_home
            / "Library"
            / "LaunchAgents"
            / (backup.LABEL + ".plist")
        )
        with path.open("rb") as handle:
            configuration = plistlib.load(handle)
        self.assertEqual(result["status"], "installed")
        self.assertEqual(result["role"], "leader")
        self.assertEqual(configuration["Label"], backup.LABEL)
        self.assertEqual(configuration["StartInterval"], 300)
        self.assertTrue(configuration["RunAtLoad"])
        self.assertEqual(
            configuration["ProgramArguments"],
            ["/usr/bin/python3", str(SCRIPT), "run"],
        )
        self.assertEqual(configuration["WorkingDirectory"], str(SCRIPT.parent))
        self.assertNotIn("KeepAlive", configuration)
        self.assertEqual(launch.call_count, 3)

    def test_run_without_leader_never_publishes_shared_state(self) -> None:
        connection = self.create_database("state_5.sqlite")
        self.addCleanup(connection.close)

        with patch.object(backup.socket, "gethostname", return_value="follower"):
            result = backup.run_backup(self.configuration)

        self.assertEqual(result["status"], "not_leader")
        self.assertIsNone(result["leader"])
        self.assertFalse(self.destination.exists())

    def test_follower_cannot_replace_leader_snapshot(self) -> None:
        self.elect_leader()
        connection = self.create_database("state_5.sqlite")
        self.addCleanup(connection.close)
        source = backup.database_sources(self.configuration)[0]
        source.destination.parent.mkdir(parents=True)
        source.destination.write_bytes(b"authoritative snapshot")

        with patch.object(backup.socket, "gethostname", return_value="follower"):
            result = backup.run_backup(self.configuration)

        self.assertEqual(result["status"], "not_leader")
        self.assertEqual(result["leader"], "test-leader")
        self.assertEqual(source.destination.read_bytes(), b"authoritative snapshot")
        self.assertFalse((self.destination / "backup-status.json").exists())

    def test_publication_rechecks_leadership_after_copy(self) -> None:
        connection = self.create_database("state_5.sqlite")
        self.addCleanup(connection.close)
        source = backup.database_sources(self.configuration)[0]
        source.destination.parent.mkdir(parents=True)
        source.destination.write_bytes(b"authoritative snapshot")

        def reject_publication() -> None:
            raise PermissionError

        with self.assertRaises(PermissionError):
            backup._backup_sqlite(
                source.source,
                source.destination,
                before_publish=reject_publication,
            )

        self.assertEqual(source.destination.read_bytes(), b"authoritative snapshot")

    def test_electing_different_leader_requires_explicit_takeover(self) -> None:
        self.elect_leader()

        with patch.object(backup.socket, "gethostname", return_value="other-host"):
            with self.assertRaises(PermissionError):
                backup._elect_leader(self.configuration)
            self.assertEqual(backup._elect_leader(self.configuration, takeover=True), "other-host")

        self.assertEqual(backup._leader(self.configuration), "other-host")

    def test_election_command_does_not_start_a_backup_writer(self) -> None:
        output = StringIO()

        with patch.object(backup, "default_configuration", return_value=self.configuration):
            with patch.object(backup.socket, "gethostname", return_value="test-leader"):
                with patch.object(backup.subprocess, "run") as launch:
                    with redirect_stdout(output):
                        result = backup.main(["elect", "--leader"])

        self.assertEqual(result, 0)
        self.assertEqual(backup._leader(self.configuration), "test-leader")
        self.assertEqual(json.loads(output.getvalue())["status"], "elected")
        launch.assert_not_called()

    def test_stop_command_does_not_clear_elected_leader(self) -> None:
        import subprocess

        self.elect_leader()
        output = StringIO()
        with patch.object(backup, "default_configuration", return_value=self.configuration):
            with patch.object(backup.Path, "home", return_value=self.codex_home):
                with patch.object(
                    backup.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 1),
                ):
                    with redirect_stdout(output):
                        result = backup.main(["stop"])

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "stopped")
        self.assertEqual(backup._leader(self.configuration), "test-leader")

    def test_follower_stops_existing_backup_writer(self) -> None:
        import subprocess

        home = self.codex_home
        agent = home / "Library" / "LaunchAgents" / (backup.LABEL + ".plist")
        agent.parent.mkdir(parents=True)
        agent.write_bytes(b"backup agent")

        with patch.object(backup.Path, "home", return_value=home):
            with patch.object(
                backup.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 0),
                ],
            ) as launch:
                result = backup.install(self.configuration, role="follower")

        self.assertEqual(result["status"], "follower")
        self.assertEqual(launch.call_count, 2)
        self.assertFalse(agent.exists())

    def test_restore_rejects_empty_state_snapshot_when_rollouts_exist(self) -> None:
        source = backup.database_sources(self.configuration)[0]
        source.destination.parent.mkdir(parents=True)
        with sqlite3.connect(str(source.destination)) as snapshot:
            snapshot.execute("CREATE TABLE threads(id TEXT PRIMARY KEY)")
        sessions = self.codex_home / "sessions"
        sessions.mkdir()
        (sessions / "2026").mkdir()

        result = backup.restore_missing(self.configuration)

        self.assertEqual(result["status"], "error")
        self.assertIn(
            {
                "name": "state",
                "status": "invalid_snapshot",
                "reason": "empty_thread_index",
            },
            result["sources"],
        )
        self.assertFalse(source.source.exists())

    def test_restore_opens_snapshot_without_shared_sqlite_sidecars(self) -> None:
        source = backup.database_sources(self.configuration)[1]
        source.destination.parent.mkdir(parents=True)
        with sqlite3.connect(str(source.destination)) as snapshot:
            snapshot.execute("CREATE TABLE records(value TEXT NOT NULL)")
            snapshot.execute("INSERT INTO records VALUES ('authoritative')")

        result = backup.restore_missing(self.configuration)

        self.assertEqual(result["status"], "ok")
        self.assertFalse(Path(str(source.destination) + "-wal").exists())
        self.assertFalse(Path(str(source.destination) + "-shm").exists())
        with sqlite3.connect(str(source.source)) as restored:
            self.assertEqual(
                restored.execute("SELECT value FROM records").fetchall(),
                [("authoritative",)],
            )

    def test_repair_replaces_unused_empty_state_with_nonempty_snapshot(self) -> None:
        import subprocess

        source = backup.database_sources(self.configuration)[0]
        source.destination.parent.mkdir(parents=True)
        with sqlite3.connect(str(source.source)) as existing:
            existing.execute("CREATE TABLE threads(id TEXT PRIMARY KEY)")
        with sqlite3.connect(str(source.destination)) as snapshot:
            snapshot.execute("CREATE TABLE threads(id TEXT PRIMARY KEY)")
            snapshot.execute("INSERT INTO threads VALUES ('authoritative')")

        with patch.object(
            backup.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1, stdout="", stderr=""),
        ) as handles:
            result = backup.restore_missing(self.configuration, repair_empty=True)

        self.assertEqual(result["status"], "ok")
        self.assertIn({"name": "state", "status": "repaired"}, result["sources"])
        self.assertEqual(handles.call_count, 2)
        with sqlite3.connect(str(source.source)) as repaired:
            self.assertEqual(
                repaired.execute("SELECT id FROM threads").fetchall(),
                [("authoritative",)],
            )

    def test_repair_preserves_healthy_existing_state(self) -> None:
        source = backup.database_sources(self.configuration)[0]
        source.destination.parent.mkdir(parents=True)
        with sqlite3.connect(str(source.source)) as existing:
            existing.execute("CREATE TABLE threads(id TEXT PRIMARY KEY)")
            existing.execute("INSERT INTO threads VALUES ('keep-me')")
        with sqlite3.connect(str(source.destination)) as snapshot:
            snapshot.execute("CREATE TABLE threads(id TEXT PRIMARY KEY)")
            snapshot.execute("INSERT INTO threads VALUES ('replacement')")

        with patch.object(backup.subprocess, "run") as handles:
            result = backup.restore_missing(self.configuration, repair_empty=True)

        self.assertIn({"name": "state", "status": "existing"}, result["sources"])
        handles.assert_not_called()
        with sqlite3.connect(str(source.source)) as existing:
            self.assertEqual(
                existing.execute("SELECT id FROM threads").fetchall(),
                [("keep-me",)],
            )

    def test_repair_refuses_state_database_with_open_handles(self) -> None:
        import subprocess

        source = backup.database_sources(self.configuration)[0]
        source.destination.parent.mkdir(parents=True)
        with sqlite3.connect(str(source.source)) as existing:
            existing.execute("CREATE TABLE threads(id TEXT PRIMARY KEY)")
        with sqlite3.connect(str(source.destination)) as snapshot:
            snapshot.execute("CREATE TABLE threads(id TEXT PRIMARY KEY)")
            snapshot.execute("INSERT INTO threads VALUES ('authoritative')")

        with patch.object(
            backup.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                [], 0, stdout="123\n", stderr=""
            ),
        ):
            result = backup.restore_missing(self.configuration, repair_empty=True)

        self.assertEqual(result["status"], "error")
        self.assertIn({"name": "state", "status": "in_use"}, result["sources"])
        with sqlite3.connect(str(source.source)) as existing:
            self.assertEqual(existing.execute("SELECT id FROM threads").fetchall(), [])

    def test_repair_rechecks_handles_before_atomic_replacement(self) -> None:
        import subprocess

        source = backup.database_sources(self.configuration)[0]
        source.destination.parent.mkdir(parents=True)
        with sqlite3.connect(str(source.source)) as existing:
            existing.execute("CREATE TABLE threads(id TEXT PRIMARY KEY)")
        with sqlite3.connect(str(source.destination)) as snapshot:
            snapshot.execute("CREATE TABLE threads(id TEXT PRIMARY KEY)")
            snapshot.execute("INSERT INTO threads VALUES ('authoritative')")

        with patch.object(
            backup.subprocess,
            "run",
            side_effect=[
                subprocess.CompletedProcess([], 1, stdout="", stderr=""),
                subprocess.CompletedProcess([], 0, stdout="456\n", stderr=""),
            ],
        ):
            result = backup.restore_missing(self.configuration, repair_empty=True)

        self.assertEqual(result["status"], "error")
        self.assertIn(
            {
                "name": "state",
                "status": "error",
                "error_type": "PermissionError",
            },
            result["sources"],
        )
        with sqlite3.connect(str(source.source)) as existing:
            self.assertEqual(existing.execute("SELECT id FROM threads").fetchall(), [])

if __name__ == "__main__":
    unittest.main()
