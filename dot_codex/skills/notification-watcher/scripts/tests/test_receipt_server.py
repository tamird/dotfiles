"""Exercise real private receipt transport and transactional source delivery."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import socket
import tempfile
from threading import Thread
import unittest

from codex_notification_watcher.receipt_server import (
    MAXIMUM_REQUEST_BYTES,
    ReceiptServer,
    socket_path,
    submit_receipts,
)
from codex_notification_watcher.source import register_source
from codex_notification_watcher.store import Store


class ReceiptServerTest(unittest.TestCase):
    owner = "authenticated-provider"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "notifications.sqlite3"
        self.store = Store(self.database, initialize=True)
        self.addCleanup(self.store.connection.close)
        self.now = datetime.now(UTC)
        self.floor = self.now - timedelta(seconds=300)
        self.register("provider-a")
        self.address = socket_path(self.database)
        self.server = ReceiptServer(
            self.address, self.database, provider_timeout_seconds=0.5
        )
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def register(self, source_id: str) -> None:
        _ = register_source(
            self.store,
            {
                "source_id": source_id,
                "owner": self.owner,
                "replay_from": self.floor.isoformat(),
                "overlap_seconds": 300,
                "verified": True,
            },
        )

    def observation(
        self, source_id: str = "provider-a", *, complete: bool = True
    ) -> dict[str, object]:
        required = ["provider-page-a", "provider-page-b"]
        return {
            "source_id": source_id,
            "owner": self.owner,
            "verified": True,
            "observed_at": self.now.isoformat(),
            "high_water_mark": self.now.isoformat(),
            "overlap_floor": self.floor.isoformat(),
            "overlap_seconds": 300,
            "pagination_complete": complete,
            "required_scopes": required,
            "observed_scopes": required if complete else required[:1],
            "events": [],
        }

    def stop_server(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.address.unlink(missing_ok=True)

    def test_real_socket_commits_source_and_provider_heartbeat(self) -> None:
        result = submit_receipts(self.database, [self.observation()])

        self.assertEqual(result["source_count"], 1)
        health = self.store.health(now=self.now + timedelta(seconds=1))
        self.assertEqual(health["status"], "healthy")
        self.assertTrue(health["heartbeat_healthy"])
        self.assertEqual(health["heartbeat_observed_at"], self.now.isoformat())

    def test_private_receipt_socket_is_owner_only(self) -> None:
        self.assertEqual(self.address.stat().st_mode & 0o777, 0o600)

    def test_stalled_provider_times_out_without_blocking_the_next_provider(
        self,
    ) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(str(self.address))
            client.sendall(b"[")
            with client.makefile("rb") as response:
                value: object = json.loads(response.readline())

        self.assertIsInstance(value, dict)
        assert isinstance(value, dict)
        self.assertIn("timed out", str(value.get("error")))
        result = submit_receipts(self.database, [self.observation()])
        self.assertEqual(result["source_count"], 1)
        self.assertEqual(self.store.health(now=self.now)["status"], "healthy")

    def test_concurrent_replay_has_one_immutable_observation(self) -> None:
        observation = self.observation()

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(
                executor.map(
                    lambda _: submit_receipts(self.database, [observation]),
                    range(8),
                )
            )

        self.assertTrue(all(result["source_count"] == 1 for result in results))
        self.assertEqual(self.store.stats()["receipts"], 2)
        self.assertEqual(self.store.health(now=self.now)["status"], "healthy")

    def test_partial_source_does_not_advance_or_hide_complete_source(self) -> None:
        self.register("provider-b")

        result = submit_receipts(
            self.database,
            [self.observation(), self.observation("provider-b", complete=False)],
        )

        self.assertEqual(result["source_count"], 2)
        health = self.store.health(now=self.now)
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["unhealthy_sources"], 1)
        sources = {
            source["source_id"]: source
            for source in health["sources"]
            if isinstance(source, dict)
        }
        self.assertTrue(sources["provider-a"]["healthy"])
        self.assertFalse(sources["provider-b"]["healthy"])
        self.assertIsNone(sources["provider-b"]["high_water_mark"])

    def test_empty_provider_batch_is_rejected_without_mutating_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "nonempty"):
            _ = submit_receipts(self.database, [])

        self.assertEqual(self.store.stats()["receipts"], 1)
        self.assertFalse(self.store.health(now=self.now)["heartbeat_healthy"])

    def test_rejected_source_does_not_block_an_independent_provider(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "committed 1 independent observations and rejected "
            "unregistered-provider: observation has no registered source",
        ):
            _ = submit_receipts(
                self.database,
                [self.observation(), self.observation("unregistered-provider")],
            )

        self.assertEqual(self.store.stats()["receipts"], 2)
        health = self.store.health(now=self.now)
        self.assertTrue(health["heartbeat_healthy"])
        self.assertEqual(health["unhealthy_sources"], 0)

    def test_rejected_only_source_cannot_fabricate_a_heartbeat(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "committed 0 independent observations and rejected "
            "unregistered-provider",
        ):
            _ = submit_receipts(
                self.database,
                [self.observation("unregistered-provider")],
            )

        self.assertEqual(self.store.stats()["receipts"], 1)
        self.assertFalse(self.store.health(now=self.now)["heartbeat_healthy"])

    def test_oversized_provider_batch_is_rejected_without_mutating_state(self) -> None:
        observation = self.observation()
        observation["padding"] = "x" * MAXIMUM_REQUEST_BYTES

        with self.assertRaisesRegex(ValueError, "size limit"):
            _ = submit_receipts(self.database, [observation])

        self.assertEqual(self.store.stats()["receipts"], 1)
        self.assertFalse(self.store.health(now=self.now)["heartbeat_healthy"])

    def test_unavailable_writer_cannot_fabricate_a_source_observation(self) -> None:
        missing = self.database.parent / "missing-runtime" / "notifications.sqlite3"

        with self.assertRaises(OSError):
            _ = submit_receipts(missing, [self.observation()])

        self.assertEqual(self.store.stats()["receipts"], 1)
        self.assertFalse(self.store.health(now=self.now)["heartbeat_healthy"])
