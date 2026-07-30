"""Ensure only the elected machine mutates shared notification state."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from codex_notification_watcher.cli import main
from codex_notification_watcher.config import require_writer_leadership
from codex_notification_watcher.receipt_server import serve_receipts, submit_receipts
from codex_notification_watcher.store import Store


class RuntimeLeadershipTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.runtime = (
            self.home / "Google Drive" / "My Drive" / "Codex" / "runtime"
        )
        self.database = self.runtime / "review-monitor" / "notifications.sqlite3"
        self.database.parent.mkdir(parents=True)
        self.home_patch = patch(
            "codex_notification_watcher.config.Path.home", return_value=self.home
        )
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def elect(self, hostname: str = "leader") -> None:
        (self.runtime / "backup-leader.json").write_text(
            json.dumps({"hostname": hostname}), encoding="utf-8"
        )

    def initialize(self) -> None:
        self.elect()
        with patch("codex_notification_watcher.config.socket.gethostname", return_value="leader"):
            with Store(self.database, initialize=True):
                pass

    def test_shared_write_requires_an_elected_leader(self) -> None:
        with self.assertRaisesRegex(PermissionError, "no elected leader"):
            require_writer_leadership(self.database)

    def test_leader_can_initialize_shared_state(self) -> None:
        self.initialize()

        self.assertTrue(self.database.is_file())

    def test_follower_cannot_open_shared_writer(self) -> None:
        self.initialize()

        with patch("codex_notification_watcher.config.socket.gethostname", return_value="follower"):
            with self.assertRaisesRegex(PermissionError, "elected leader"):
                with Store(self.database):
                    pass

    def test_follower_can_read_shared_health_without_writing(self) -> None:
        self.initialize()

        with patch("codex_notification_watcher.config.socket.gethostname", return_value="follower"):
            with Store(self.database, read_only=True) as store:
                with self.assertRaises(sqlite3.OperationalError):
                    store.connection.execute(
                        "INSERT INTO metadata VALUES ('forbidden', '{}')"
                    )

    def test_follower_health_command_uses_read_only_connection(self) -> None:
        self.initialize()
        output = StringIO()

        with patch("codex_notification_watcher.config.socket.gethostname", return_value="follower"):
            with redirect_stdout(output):
                result = main(["--database", str(self.database), "health"])

        self.assertEqual(result, 0)
        self.assertIn("status", json.loads(output.getvalue()))

    def test_follower_cannot_start_receipt_writer(self) -> None:
        self.initialize()

        with patch("codex_notification_watcher.config.socket.gethostname", return_value="follower"):
            with self.assertRaisesRegex(PermissionError, "elected leader"):
                serve_receipts(self.database)

        self.assertFalse(self.database.with_name("notification-receipts.sock").exists())

    def test_follower_cannot_submit_mutating_receipts(self) -> None:
        self.initialize()

        with patch("codex_notification_watcher.config.socket.gethostname", return_value="follower"):
            with self.assertRaisesRegex(PermissionError, "elected leader"):
                submit_receipts(self.database, [])

    def test_unrelated_local_database_does_not_require_shared_leader(self) -> None:
        local = self.home / "local-notifications.sqlite3"

        with Store(local, initialize=True):
            pass

        self.assertTrue(local.is_file())


if __name__ == "__main__":
    unittest.main()
