"""Provider-independent behavioral coverage for durable notification intake."""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from codex_notification_watcher.cli import main
from codex_notification_watcher.config import RuntimeConfig
from codex_notification_watcher.manifest import bootstrap
from codex_notification_watcher.model import (
    MAXIMUM_LIMIT,
    NotificationEvent,
    bounded_limit,
    utc_datetime,
)
from codex_notification_watcher.source import (
    claim,
    ingest,
    record_failure,
    register_source,
    replay,
    resolve,
    resolve_batch,
    supersede,
)
from codex_notification_watcher.store import Store


class NotificationWatcherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "notifications.sqlite3"
        self.store = Store(self.path, initialize=True)
        self.addCleanup(self.store.connection.close)
        self.now = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
        self.cutoff = self.now - timedelta(minutes=5)

    def registration(
        self, source_id: str = "source-a", *, owner: str = "worker-a"
    ) -> dict[str, object]:
        return {
            "source_id": source_id,
            "owner": owner,
            "replay_from": self.cutoff.isoformat(),
            "overlap_seconds": 300,
            "verified": True,
        }

    def event(self, **overrides: object) -> dict[str, object]:
        value: dict[str, object] = {
            "event_id": "event-a",
            "category": "review_request",
            "subject_key": "example/project#42",
            "head": "a" * 40,
            "actor": "author",
            "actor_type": "User",
            "reviewer": "reviewer",
            "occurred_at": self.now.isoformat(),
            "verified": True,
        }
        value.update(overrides)
        return value

    def observation(
        self,
        *,
        source_id: str = "source-a",
        owner: str = "worker-a",
        events: list[dict[str, object]] | None = None,
        complete: bool = True,
    ) -> dict[str, object]:
        high = self.now + timedelta(minutes=1)
        return {
            "source_id": source_id,
            "owner": owner,
            "observed_at": high.isoformat(),
            "high_water_mark": high.isoformat(),
            "overlap_floor": self.cutoff.isoformat(),
            "overlap_seconds": 300,
            "pagination_complete": complete,
            "events": [] if events is None else events,
            "verified": True,
        }

    def continued_observation(
        self,
        *,
        high_water_mark: datetime,
        overlap_floor: datetime,
        source_id: str = "source-a",
        events: list[dict[str, object]] | None = None,
        complete: bool = True,
    ) -> dict[str, object]:
        value = self.observation(
            source_id=source_id,
            events=events,
            complete=complete,
        )
        value["observed_at"] = high_water_mark.isoformat()
        value["high_water_mark"] = high_water_mark.isoformat()
        value["overlap_floor"] = overlap_floor.isoformat()
        return value

    def register(self, source_id: str = "source-a") -> None:
        _ = register_source(self.store, self.registration(source_id))

    def batch(self, observations: object) -> dict[str, object]:
        output = StringIO()
        with (
            patch("sys.stdin", StringIO(json.dumps(observations))),
            redirect_stdout(output),
        ):
            result = main(["--database", str(self.path), "ingest-batch"])
        self.assertEqual(result, 0)
        decoded: object = json.loads(output.getvalue())
        assert isinstance(decoded, dict)
        return decoded

    def supersession_command(
        self,
        logical_cycle_id: str,
        evidence: object,
        *,
        owner: str = "worker-a",
    ) -> dict[str, object]:
        output = StringIO()
        with (
            patch("sys.stdin", StringIO(json.dumps(evidence))),
            redirect_stdout(output),
        ):
            result = main(
                [
                    "--database",
                    str(self.path),
                    "supersede",
                    logical_cycle_id,
                    "--owner",
                    owner,
                ]
            )
        self.assertEqual(result, 0)
        decoded: object = json.loads(output.getvalue())
        assert isinstance(decoded, dict)
        return decoded

    def supersession_evidence(self, **overrides: object) -> dict[str, object]:
        value: dict[str, object] = {
            "source_id": "source-a",
            "event_id": "provider-proof-a",
            "head": "a" * 40,
            "reason": "The verified current head already has its requested review.",
            "verified": True,
        }
        value.update(overrides)
        return value

    def pending_cycle(self) -> str:
        self.register()
        _ = ingest(self.store, self.observation(events=[self.event()]))
        cycle = self.store.pending()[0]["logical_cycle_id"]
        assert isinstance(cycle, str)
        return cycle

    def test_schema_contains_only_canonical_notification_tables(self) -> None:
        rows = self.store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
        self.assertEqual(
            [row["name"] for row in rows],
            ["claims", "metadata", "notifications", "receipts", "sources"],
        )

    def test_overlapping_sources_keep_evidence_but_share_one_review_claim(
        self,
    ) -> None:
        self.register("source-a")
        self.register("source-b")
        event = self.event(logical_cycle_id="one-provider-message")

        first = ingest(self.store, self.observation(events=[event]))
        second = ingest(
            self.store,
            self.observation(source_id="source-b", events=[event]),
        )

        self.assertEqual(first["discovered"], 1)
        self.assertEqual(second["discovered"], 1)
        self.assertEqual(len(self.store.pending()), 1)
        rows = self.store.connection.execute(
            "SELECT source_id FROM notifications "
            "WHERE logical_cycle_id = ? ORDER BY source_id",
            ("one-provider-message",),
        )
        self.assertEqual([row["source_id"] for row in rows], ["source-a", "source-b"])
        checkpoints = self.store.connection.execute(
            "SELECT source_id, pagination_complete FROM sources ORDER BY source_id"
        )
        self.assertEqual(
            [(row["source_id"], row["pagination_complete"]) for row in checkpoints],
            [("source-a", 1), ("source-b", 1)],
        )

    def test_notification_database_is_owner_private(self) -> None:
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_initialization_refuses_an_existing_database(self) -> None:
        with self.assertRaisesRegex(ValueError, "existing database"):
            _ = Store(self.path, initialize=True)

    def test_missing_database_requires_explicit_initialization(self) -> None:
        missing = Path(self.directory.name) / "missing.sqlite3"
        with self.assertRaisesRegex(ValueError, "explicitly initialized"):
            _ = Store(missing)
        self.assertFalse(missing.exists())

    def test_source_registration_records_an_immutable_receipt(self) -> None:
        result = register_source(self.store, self.registration())
        self.assertFalse(result["already_registered"])
        self.assertEqual(self.store.stats()["receipts"], 1)

    def test_manifest_registers_only_configured_sources(self) -> None:
        result = bootstrap(
            self.store,
            {
                "owner": "worker-a",
                "replay_from": self.cutoff.isoformat(),
                "sources": ["source-a", "source-b"],
            },
        )
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(self.store.stats()["sources"], 2)
        self.assertEqual(self.store.stats()["notifications"], 0)
        self.assertEqual(self.store.stats()["claims"], 0)

    def test_manifest_starts_unobserved_and_degraded(self) -> None:
        _ = bootstrap(
            self.store,
            {
                "owner": "worker-a",
                "replay_from": self.cutoff.isoformat(),
                "sources": ["source-a"],
            },
        )
        state = replay(self.store, "source-a")
        self.assertIsNone(state["high_water_mark"])
        self.assertFalse(state["pagination_complete"])
        self.assertEqual(self.store.health(now=self.now)["status"], "degraded")

    def test_manifest_saved_replay_start_cannot_be_skipped(self) -> None:
        archived_floor = self.cutoff - timedelta(hours=20)
        _ = bootstrap(
            self.store,
            {
                "owner": "worker-a",
                "replay_from": archived_floor.isoformat(),
                "sources": ["source-a"],
            },
        )
        before = self.store.stats()

        with self.assertRaisesRegex(ValueError, "registered replay start"):
            _ = ingest(self.store, self.observation(events=[self.event()]))

        self.assertEqual(self.store.stats(), before)
        self.assertIsNone(replay(self.store, "source-a")["high_water_mark"])

    def test_manifest_rejects_duplicate_sources_before_registration(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate sources"):
            _ = bootstrap(
                self.store,
                {
                    "owner": "worker-a",
                    "replay_from": self.cutoff.isoformat(),
                    "sources": ["source-a", "source-a"],
                },
            )
        self.assertEqual(self.store.stats()["sources"], 0)

    def test_manifest_rejects_missing_owner(self) -> None:
        with self.assertRaisesRegex(ValueError, "source owner"):
            _ = bootstrap(
                self.store,
                {
                    "replay_from": self.cutoff.isoformat(),
                    "sources": ["source-a"],
                },
            )

    def test_manifest_does_not_require_emergency_replay_cutoff(self) -> None:
        result = bootstrap(
            self.store,
            {"owner": "worker-a", "sources": ["source-a"]},
        )
        self.assertEqual(result["source_count"], 1)
        self.assertIsNone(replay(self.store, "source-a")["overlap_floor"])

    def test_source_registration_is_idempotent(self) -> None:
        first = register_source(self.store, self.registration())
        second = register_source(self.store, self.registration())
        self.assertEqual(first["receipt_id"], second["receipt_id"])
        self.assertTrue(second["already_registered"])
        self.assertEqual(self.store.stats()["receipts"], 1)

    def test_source_registration_rejects_another_owner(self) -> None:
        self.register()
        with self.assertRaisesRegex(ValueError, "original owner"):
            _ = register_source(
                self.store, self.registration(owner="another-worker")
            )

    def test_source_registration_requires_authentication(self) -> None:
        value = self.registration()
        value["verified"] = False
        with self.assertRaisesRegex(ValueError, "authenticated"):
            _ = register_source(self.store, value)

    def test_complete_source_cannot_omit_an_observed_actionable_event(self) -> None:
        self.register()
        observation = self.observation()
        observation["observed_candidate_event_ids"] = ["observed-review-a"]
        before = self.store.stats()

        with self.assertRaisesRegex(ValueError, "omits an authenticated actionable"):
            _ = ingest(self.store, observation)

        self.assertEqual(self.store.stats(), before)
        self.assertIsNone(replay(self.store, "source-a")["high_water_mark"])

    def test_source_persists_exact_observed_actionable_event_evidence(self) -> None:
        self.register()
        event = self.event(event_id="observed-review-a")
        observation = self.observation(events=[event])
        observation["observed_candidate_event_ids"] = ["observed-review-a"]

        result = ingest(self.store, observation)

        self.assertEqual(result["discovered"], 1)
        self.assertTrue(result["checkpoint_advanced"])
        row = self.store.connection.execute(
            "SELECT raw_json FROM receipts WHERE receipt_id = ?",
            (result["receipt_id"],),
        ).fetchone()
        assert row is not None
        evidence: object = json.loads(row["raw_json"])
        assert isinstance(evidence, dict)
        self.assertEqual(evidence["observed_candidate_event_ids"], ["observed-review-a"])

    def test_quiet_provider_page_advances_with_empty_candidate_evidence(self) -> None:
        self.register()
        observation = self.observation()
        observation["observed_candidate_event_ids"] = []

        result = ingest(self.store, observation)

        self.assertEqual(result["discovered"], 0)
        self.assertTrue(result["checkpoint_advanced"])

    def test_source_cannot_add_an_event_absent_from_provider_evidence(self) -> None:
        self.register()
        event = self.event(event_id="observed-review-a")
        observation = self.observation(events=[event])
        observation["observed_candidate_event_ids"] = []

        with self.assertRaisesRegex(ValueError, "contains an unreported event"):
            _ = ingest(self.store, observation)

        self.assertEqual(self.store.stats()["notifications"], 0)

    def test_source_rejects_duplicate_actionable_candidate_ids(self) -> None:
        self.register()
        event = self.event(event_id="observed-review-a")
        observation = self.observation(events=[event])
        observation["observed_candidate_event_ids"] = [
            "observed-review-a",
            "observed-review-a",
        ]

        with self.assertRaisesRegex(ValueError, "candidate event IDs contain duplicates"):
            _ = ingest(self.store, observation)

        self.assertEqual(self.store.stats()["notifications"], 0)

    def test_source_rejects_untyped_actionable_candidate_evidence(self) -> None:
        self.register()
        observation = self.observation()
        observation["observed_candidate_event_ids"] = "observed-review-a"

        with self.assertRaisesRegex(ValueError, "candidate event IDs must be a list"):
            _ = ingest(self.store, observation)

        self.assertEqual(self.store.stats()["notifications"], 0)

    def test_source_registration_persists_initial_replay_cutoff(self) -> None:
        self.register()
        state = replay(self.store, "source-a")
        self.assertEqual(
            utc_datetime(state["overlap_floor"], description="replay floor"),
            self.cutoff,
        )
        self.assertIsNone(state["high_water_mark"])

    def test_historical_registration_requires_authenticated_replay_start(
        self,
    ) -> None:
        registration = self.registration()
        _ = registration.pop("replay_from")
        registration["historical"] = True
        before = self.store.stats()

        with self.assertRaisesRegex(ValueError, "authenticated replay start"):
            _ = register_source(self.store, registration)

        self.assertEqual(self.store.stats(), before)

    def test_historical_registration_rejects_nonboolean_state(self) -> None:
        registration = self.registration()
        registration["historical"] = "yes"
        before = self.store.stats()

        with self.assertRaisesRegex(ValueError, "historical state must be a boolean"):
            _ = register_source(self.store, registration)

        self.assertEqual(self.store.stats(), before)

    def test_historical_registration_persists_actual_archived_replay_start(
        self,
    ) -> None:
        archived_floor = self.cutoff - timedelta(hours=20)
        registration = self.registration()
        registration["replay_from"] = archived_floor.isoformat()
        registration["historical"] = True

        result = register_source(self.store, registration)

        self.assertFalse(result["already_registered"])
        state = replay(self.store, "source-a")
        self.assertIsNone(state["high_water_mark"])
        self.assertFalse(state["pagination_complete"])
        self.assertEqual(
            utc_datetime(state["overlap_floor"], description="replay floor"),
            archived_floor,
        )
        row = self.store.connection.execute(
            "SELECT status, raw_json FROM sources WHERE source_id = ?",
            ("source-a",),
        ).fetchone()
        assert row is not None
        self.assertEqual(row["status"], "INITIALIZATION_REQUIRED")
        evidence = json.loads(row["raw_json"])
        self.assertTrue(evidence["historical"])
        self.assertEqual(
            utc_datetime(evidence["replay_from"], description="replay start"),
            archived_floor,
        )
        self.assertEqual(self.store.health(now=self.now)["status"], "degraded")

    def test_initial_historical_replay_rejects_recent_floor_jump(self) -> None:
        archived_floor = self.cutoff - timedelta(hours=20)
        registration = self.registration()
        registration["replay_from"] = archived_floor.isoformat()
        registration["historical"] = True
        _ = register_source(self.store, registration)
        before = self.store.stats()
        state = replay(self.store, "source-a")

        with self.assertRaisesRegex(ValueError, "registered replay start"):
            _ = ingest(
                self.store,
                self.observation(events=[self.event(event_id="skipped-history")]),
            )

        self.assertEqual(replay(self.store, "source-a"), state)
        self.assertEqual(self.store.stats(), before)

    def test_initial_historical_replay_recovers_archived_scoped_event(
        self,
    ) -> None:
        archived_floor = self.cutoff - timedelta(hours=20)
        registration = self.registration()
        registration["replay_from"] = archived_floor.isoformat()
        registration["historical"] = True
        _ = register_source(self.store, registration)
        archived = self.event(
            event_id="archived-thread-reply",
            category="control_task",
            subject_key="conversation/archived-parent",
            occurred_at=(archived_floor + timedelta(minutes=1)).isoformat(),
        )
        observation = self.observation(events=[archived])
        observation["overlap_floor"] = archived_floor.isoformat()
        observation["required_scopes"] = ["parent-discovery", "archived-parent"]
        observation["observed_scopes"] = ["archived-parent", "parent-discovery"]

        first = ingest(self.store, observation)
        repeated = ingest(self.store, observation)

        self.assertEqual(first["discovered"], 1)
        self.assertEqual(repeated["deduplicated"], 1)
        self.assertEqual(first["receipt_id"], repeated["receipt_id"])
        self.assertTrue(first["checkpoint_advanced"])
        state = replay(self.store, "source-a")
        self.assertTrue(state["pagination_complete"])
        pending = self.store.pending(category="control_task")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["event_id"], "archived-thread-reply")

    def test_partial_historical_page_cannot_satisfy_archived_replay(
        self,
    ) -> None:
        archived_floor = self.cutoff - timedelta(hours=20)
        registration = self.registration()
        registration["replay_from"] = archived_floor.isoformat()
        registration["historical"] = True
        _ = register_source(self.store, registration)

        partial = ingest(self.store, self.observation(complete=False))

        self.assertFalse(partial["checkpoint_advanced"])
        state = replay(self.store, "source-a")
        self.assertIsNone(state["high_water_mark"])
        self.assertFalse(state["pagination_complete"])
        self.assertEqual(
            utc_datetime(state["overlap_floor"], description="replay floor"),
            archived_floor,
        )

    def test_source_registration_requires_sufficient_overlap(self) -> None:
        value = self.registration()
        value["overlap_seconds"] = 299
        with self.assertRaisesRegex(ValueError, "300 seconds"):
            _ = register_source(self.store, value)

    def test_complete_observation_advances_watermark(self) -> None:
        self.register()
        result = ingest(self.store, self.observation(events=[self.event()]))
        self.assertTrue(result["checkpoint_advanced"])
        self.assertEqual(result["discovered"], 1)
        self.assertTrue(replay(self.store, "source-a")["pagination_complete"])

    def test_batch_ingests_each_authenticated_source_in_order(self) -> None:
        self.register("source-a")
        self.register("source-b")
        first = self.observation(
            source_id="source-a",
            events=[self.event(event_id="source-a-event")],
        )
        second = self.observation(
            source_id="source-b",
            events=[self.event(event_id="source-b-event")],
        )

        result = self.batch([first, second])

        self.assertEqual(result["source_count"], 2)
        results = result["results"]
        assert isinstance(results, list)
        self.assertEqual(
            [item["source_id"] for item in results],
            ["source-a", "source-b"],
        )
        self.assertTrue(replay(self.store, "source-a")["pagination_complete"])
        self.assertTrue(replay(self.store, "source-b")["pagination_complete"])

    def test_repeated_batch_preserves_each_immutable_source_receipt(self) -> None:
        self.register("source-a")
        self.register("source-b")
        observations = [
            self.observation(
                source_id=source_id,
                events=[self.event(event_id=f"{source_id}-event")],
            )
            for source_id in ("source-a", "source-b")
        ]

        first = self.batch(observations)
        repeated = self.batch(observations)

        first_results = first["results"]
        repeated_results = repeated["results"]
        assert isinstance(first_results, list)
        assert isinstance(repeated_results, list)
        self.assertEqual([item["discovered"] for item in first_results], [1, 1])
        self.assertEqual(
            [item["discovered"] for item in repeated_results], [0, 0]
        )
        self.assertEqual(
            [item["receipt_id"] for item in first_results],
            [item["receipt_id"] for item in repeated_results],
        )

    def test_batch_rejects_non_array_without_writing(self) -> None:
        self.register()
        before = self.store.stats()

        for value in (None, {}, "observation", 1, True):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "nonempty JSON array"):
                    _ = self.batch(value)

        self.assertEqual(self.store.stats(), before)

    def test_batch_rejects_empty_array_without_writing(self) -> None:
        self.register()
        before = self.store.stats()

        with self.assertRaisesRegex(ValueError, "nonempty JSON array"):
            _ = self.batch([])

        self.assertEqual(self.store.stats(), before)

    def test_batch_rejects_more_than_maximum_source_count(self) -> None:
        self.register()
        before = self.store.stats()
        observations = [self.observation() for _ in range(MAXIMUM_LIMIT + 1)]

        with self.assertRaisesRegex(ValueError, "cannot exceed 100 sources"):
            _ = self.batch(observations)

        self.assertEqual(self.store.stats(), before)

    def test_batch_rolls_back_prior_sources_when_later_source_fails(self) -> None:
        self.register("source-a")
        self.register("source-b")
        before = self.store.stats()
        first = self.observation(
            source_id="source-a",
            events=[self.event(event_id="committed-source-a-event")],
        )
        second = self.observation(
            source_id="source-b",
            events=[self.event(event_id="rejected-source-b-event")],
        )
        second["required_scopes"] = ["channel", "thread"]
        second["observed_scopes"] = ["channel"]

        with self.assertRaisesRegex(ValueError, "omits a required scope"):
            _ = self.batch([first, second])

        self.assertIsNone(replay(self.store, "source-a")["high_water_mark"])
        self.assertIsNone(replay(self.store, "source-b")["high_water_mark"])
        notifications = self.store.connection.execute(
            "SELECT source_id, event_id FROM notifications ORDER BY source_id"
        ).fetchall()
        self.assertEqual(notifications, [])
        self.assertEqual(self.store.stats(), before)

    def test_invalid_ninth_batch_item_rolls_back_all_eight_valid_sources(
        self,
    ) -> None:
        source_ids = [f"source-{index}" for index in range(9)]
        for source_id in source_ids:
            self.register(source_id)
        before = self.store.stats()
        observations: list[dict[str, object]] = []
        for index, source_id in enumerate(source_ids):
            event = self.event(event_id=f"{source_id}-authenticated-event")
            if index == 8:
                event["verified"] = False
            observations.append(
                self.observation(source_id=source_id, events=[event])
            )

        with self.assertRaisesRegex(ValueError, "authenticated provider evidence"):
            _ = self.batch(observations)

        self.assertEqual(self.store.stats(), before)
        for source_id in source_ids:
            with self.subTest(source_id=source_id):
                state = replay(self.store, source_id)
                self.assertIsNone(state["high_water_mark"])
                self.assertFalse(state["pagination_complete"])
        self.assertEqual(self.store.pending(), [])

    def test_batch_requires_one_complete_json_document(self) -> None:
        self.register()
        before = self.store.stats()
        with patch("sys.stdin", StringIO("[{")):
            with self.assertRaisesRegex(ValueError, "complete JSON document"):
                _ = main(["--database", str(self.path), "ingest-batch"])

        self.assertEqual(self.store.stats(), before)

    def test_partial_observation_does_not_advance_watermark(self) -> None:
        self.register()
        result = ingest(
            self.store, self.observation(events=[self.event()], complete=False)
        )
        state = replay(self.store, "source-a")
        self.assertFalse(result["checkpoint_advanced"])
        self.assertIsNone(state["high_water_mark"])
        self.assertFalse(state["pagination_complete"])

    def test_complete_observation_records_all_required_scope_coverage(
        self,
    ) -> None:
        self.register()
        observation = self.observation()
        observation["required_scopes"] = ["thread-b", "channel", "thread-a"]
        observation["observed_scopes"] = ["thread-a", "thread-b", "channel"]

        result = ingest(self.store, observation)

        self.assertTrue(result["checkpoint_advanced"])
        receipt = self.store.connection.execute(
            "SELECT raw_json FROM receipts WHERE receipt_id = ?",
            (result["receipt_id"],),
        ).fetchone()
        assert receipt is not None
        evidence = json.loads(receipt["raw_json"])
        self.assertEqual(
            evidence["required_scopes"], ["channel", "thread-a", "thread-b"]
        )
        self.assertEqual(
            evidence["observed_scopes"], ["channel", "thread-a", "thread-b"]
        )

    def test_root_only_scan_cannot_advance_a_checkpoint_past_thread_replies(
        self,
    ) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        previous_high = self.now + timedelta(minutes=1)
        state = replay(self.store, "source-a")
        before = self.store.stats()
        observation = self.continued_observation(
            high_water_mark=previous_high + timedelta(minutes=2),
            overlap_floor=previous_high - timedelta(minutes=5),
            events=[self.event(event_id="channel-root")],
        )
        observation["required_scopes"] = ["channel", "thread-a", "thread-b"]
        observation["observed_scopes"] = ["channel"]

        with self.assertRaisesRegex(ValueError, "omits a required scope"):
            _ = ingest(self.store, observation)

        self.assertEqual(replay(self.store, "source-a"), state)
        self.assertEqual(self.store.stats(), before)

    def test_incomplete_parent_discovery_cannot_advance_checkpoint(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        previous_high = self.now + timedelta(minutes=1)
        state = replay(self.store, "source-a")
        before = self.store.stats()
        observation = self.continued_observation(
            high_water_mark=previous_high + timedelta(minutes=2),
            overlap_floor=previous_high - timedelta(minutes=5),
        )
        observation["required_scopes"] = ["parent-discovery", "thread-a"]
        observation["observed_scopes"] = ["thread-a"]

        with self.assertRaisesRegex(ValueError, "omits a required scope"):
            _ = ingest(self.store, observation)

        self.assertEqual(replay(self.store, "source-a"), state)
        self.assertEqual(self.store.stats(), before)

    def test_incomplete_assignment_or_nested_history_cannot_checkpoint(
        self,
    ) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        previous_high = self.now + timedelta(minutes=1)
        state = replay(self.store, "source-a")
        before = self.store.stats()
        required = [
            "assignment-parent-pages",
            "assignment-timeline-pages",
            "author-comment-pages",
            "author-inline-pages",
            "principal-review-pages",
        ]

        for incomplete in required:
            with self.subTest(incomplete=incomplete):
                observation = self.continued_observation(
                    high_water_mark=previous_high + timedelta(minutes=2),
                    overlap_floor=previous_high - timedelta(minutes=5),
                    events=[self.event(event_id="incompletely-observed-request")],
                )
                observation["required_scopes"] = required
                observation["observed_scopes"] = [
                    scope for scope in required if scope != incomplete
                ]

                with self.assertRaisesRegex(ValueError, "omits a required scope"):
                    _ = ingest(self.store, observation)

                self.assertEqual(replay(self.store, "source-a"), state)
                self.assertEqual(self.store.stats(), before)

    def test_old_parent_scope_retains_recent_authenticated_reply(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        previous_high = self.now + timedelta(minutes=1)
        reply_time = previous_high + timedelta(seconds=30)
        reply = self.event(
            event_id="conversation:old-parent:recent-reply",
            category="control_task",
            subject_key="conversation/old-parent",
            occurred_at=reply_time.isoformat(),
            parent_occurred_at=(self.now - timedelta(days=30)).isoformat(),
        )
        observation = self.continued_observation(
            high_water_mark=previous_high + timedelta(minutes=1),
            overlap_floor=previous_high - timedelta(minutes=5),
            events=[reply],
        )
        observation["required_scopes"] = ["parent-discovery", "old-parent"]
        observation["observed_scopes"] = ["parent-discovery", "old-parent"]

        result = ingest(self.store, observation)

        self.assertEqual(result["discovered"], 1)
        self.assertTrue(result["checkpoint_advanced"])
        pending = self.store.pending(category="control_task")
        self.assertEqual(len(pending), 1)
        self.assertEqual(
            pending[0]["event_id"], "conversation:old-parent:recent-reply"
        )

    def test_incomplete_scope_coverage_cannot_advance_checkpoint(self) -> None:
        self.register()
        observation = self.observation(complete=False)
        observation["required_scopes"] = ["channel", "thread-a"]
        observation["observed_scopes"] = ["channel"]

        result = ingest(self.store, observation)

        self.assertFalse(result["checkpoint_advanced"])
        state = replay(self.store, "source-a")
        self.assertIsNone(state["high_water_mark"])
        self.assertFalse(state["pagination_complete"])

    def test_scope_coverage_rejects_duplicate_scope_names(self) -> None:
        self.register()
        before = self.store.stats()

        for field in ("required_scopes", "observed_scopes"):
            with self.subTest(field=field):
                observation = self.observation()
                observation["required_scopes"] = ["channel", "thread-a"]
                observation["observed_scopes"] = ["channel", "thread-a"]
                observation[field] = ["channel", "channel"]

                with self.assertRaisesRegex(ValueError, "duplicate scope"):
                    _ = ingest(self.store, observation)

        self.assertEqual(self.store.stats(), before)

    def test_scope_coverage_rejects_unregistered_observed_scope(self) -> None:
        self.register()
        before = self.store.stats()
        observation = self.observation()
        observation["required_scopes"] = ["channel", "thread-a"]
        observation["observed_scopes"] = ["channel", "unknown-thread"]

        with self.assertRaisesRegex(ValueError, "unknown scope"):
            _ = ingest(self.store, observation)

        self.assertEqual(self.store.stats(), before)

    def test_scope_coverage_requires_both_scope_lists(self) -> None:
        self.register()
        before = self.store.stats()

        for field in ("required_scopes", "observed_scopes"):
            with self.subTest(field=field):
                observation = self.observation()
                observation[field] = ["channel"]

                with self.assertRaisesRegex(ValueError, "both scope lists"):
                    _ = ingest(self.store, observation)

        self.assertEqual(self.store.stats(), before)

    def test_thread_replies_are_distinct_authenticated_control_events(
        self,
    ) -> None:
        self.register()
        events = [
            self.event(
                event_id="conversation:root-a:reply-a",
                category="control_task",
                subject_key="conversation/root-a",
                occurred_at=self.now.isoformat(),
            ),
            self.event(
                event_id="conversation:root-a:reply-b",
                category="control_task",
                subject_key="conversation/root-a",
                occurred_at=(self.now + timedelta(seconds=1)).isoformat(),
            ),
        ]
        observation = self.observation(events=events)
        observation["required_scopes"] = ["channel", "thread-a"]
        observation["observed_scopes"] = ["thread-a", "channel"]

        first = ingest(self.store, observation)
        repeated = ingest(self.store, observation)

        self.assertEqual(first["discovered"], 2)
        self.assertEqual(repeated["discovered"], 0)
        self.assertEqual(repeated["deduplicated"], 2)
        self.assertEqual(len(self.store.pending(category="control_task")), 2)
        self.assertEqual(self.store.pending(category="review_request"), [])

    def test_sequential_replay_covers_the_previous_checkpoint(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        previous_high = self.now + timedelta(minutes=1)
        high = previous_high + timedelta(minutes=1)
        floor = previous_high - timedelta(minutes=5)

        result = ingest(
            self.store,
            self.continued_observation(
                high_water_mark=high,
                overlap_floor=floor,
            ),
        )

        self.assertTrue(result["checkpoint_advanced"])
        state = replay(self.store, "source-a")
        self.assertEqual(
            utc_datetime(state["high_water_mark"], description="high watermark"),
            high,
        )
        self.assertEqual(
            utc_datetime(state["overlap_floor"], description="replay floor"),
            floor,
        )

    def test_replay_recovers_events_after_outage_longer_than_overlap(
        self,
    ) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        previous_high = self.now + timedelta(minutes=1)
        high = previous_high + timedelta(hours=2)
        floor = previous_high - timedelta(minutes=5)
        during_outage = self.event(
            event_id="event-during-outage",
            occurred_at=(previous_high + timedelta(minutes=30)).isoformat(),
        )

        result = ingest(
            self.store,
            self.continued_observation(
                high_water_mark=high,
                overlap_floor=floor,
                events=[during_outage],
            ),
        )

        self.assertEqual(result["discovered"], 1)
        self.assertTrue(result["checkpoint_advanced"])
        state = replay(self.store, "source-a")
        self.assertEqual(
            utc_datetime(state["high_water_mark"], description="high watermark"),
            high,
        )

    def test_widened_replay_recovers_missed_event_and_deduplicates_receipts(
        self,
    ) -> None:
        self.register()
        existing = self.event(event_id="previously-recorded-event")
        _ = ingest(self.store, self.observation(events=[existing]))
        original = self.store.connection.execute(
            "SELECT raw_json FROM notifications "
            "WHERE source_id = ? AND event_id = ?",
            ("source-a", "previously-recorded-event"),
        ).fetchone()
        assert original is not None
        missed = self.event(
            event_id="missed-earlier-reply",
            category="control_task",
            subject_key="conversation/old-parent",
            occurred_at=(self.cutoff - timedelta(minutes=10)).isoformat(),
        )
        widened_floor = self.cutoff - timedelta(minutes=20)
        high = self.now + timedelta(minutes=3)
        observation = self.continued_observation(
            high_water_mark=high,
            overlap_floor=widened_floor,
            events=[missed, existing],
        )
        observation["required_scopes"] = ["parent-discovery", "old-parent"]
        observation["observed_scopes"] = ["parent-discovery", "old-parent"]

        first = ingest(self.store, observation)
        repeated = ingest(self.store, observation)

        self.assertEqual(first["discovered"], 1)
        self.assertEqual(first["deduplicated"], 1)
        self.assertEqual(repeated["discovered"], 0)
        self.assertEqual(repeated["deduplicated"], 2)
        self.assertEqual(first["receipt_id"], repeated["receipt_id"])
        state = replay(self.store, "source-a")
        self.assertEqual(
            utc_datetime(state["high_water_mark"], description="high watermark"),
            high,
        )
        self.assertEqual(
            utc_datetime(state["overlap_floor"], description="replay floor"),
            widened_floor,
        )
        retained = self.store.connection.execute(
            "SELECT raw_json FROM notifications "
            "WHERE source_id = ? AND event_id = ?",
            ("source-a", "previously-recorded-event"),
        ).fetchone()
        assert retained is not None
        self.assertEqual(retained["raw_json"], original["raw_json"])
        receipts = self.store.connection.execute(
            "SELECT event_id FROM receipts "
            "WHERE source_id = ? AND status = 'DISCOVERED' ORDER BY event_id",
            ("source-a",),
        ).fetchall()
        self.assertEqual(
            [receipt["event_id"] for receipt in receipts],
            ["missed-earlier-reply", "previously-recorded-event"],
        )
        pending = self.store.pending(category="control_task")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["event_id"], "missed-earlier-reply")

    def test_widened_replay_cannot_regress_its_high_watermark(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        before = self.store.stats()
        state = replay(self.store, "source-a")
        observation = self.continued_observation(
            high_water_mark=self.now,
            overlap_floor=self.cutoff - timedelta(minutes=20),
            events=[self.event(event_id="missed-earlier-reply")],
        )

        with self.assertRaisesRegex(ValueError, "high-water mark cannot regress"):
            _ = ingest(self.store, observation)

        self.assertEqual(replay(self.store, "source-a"), state)
        self.assertEqual(self.store.stats(), before)

    def test_replay_accepts_exact_previous_overlap_boundary(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        previous_high = self.now + timedelta(minutes=1)
        floor = previous_high - timedelta(seconds=300)

        result = ingest(
            self.store,
            self.continued_observation(
                high_water_mark=previous_high + timedelta(hours=1),
                overlap_floor=floor,
            ),
        )

        self.assertTrue(result["checkpoint_advanced"])
        self.assertEqual(
            utc_datetime(
                replay(self.store, "source-a")["overlap_floor"],
                description="replay floor",
            ),
            floor,
        )

    def test_replay_rejects_one_microsecond_of_missing_previous_overlap(
        self,
    ) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        previous_high = self.now + timedelta(minutes=1)
        state = replay(self.store, "source-a")
        before = self.store.stats()
        floor = previous_high - timedelta(minutes=5) + timedelta(microseconds=1)
        skipped = self.event(event_id="event-after-replay-gap")

        with self.assertRaisesRegex(ValueError, "previous checkpoint"):
            _ = ingest(
                self.store,
                self.continued_observation(
                    high_water_mark=previous_high + timedelta(hours=1),
                    overlap_floor=floor,
                    events=[skipped],
                ),
            )

        self.assertEqual(replay(self.store, "source-a"), state)
        self.assertEqual(self.store.stats(), before)

    def test_incomplete_replay_never_advances_existing_checkpoint(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        previous_high = self.now + timedelta(minutes=1)
        state = replay(self.store, "source-a")

        result = ingest(
            self.store,
            self.continued_observation(
                high_water_mark=previous_high + timedelta(hours=1),
                overlap_floor=previous_high - timedelta(minutes=4),
                complete=False,
            ),
        )

        self.assertFalse(result["checkpoint_advanced"])
        after = replay(self.store, "source-a")
        self.assertEqual(after["high_water_mark"], state["high_water_mark"])
        self.assertEqual(after["overlap_floor"], state["overlap_floor"])
        self.assertFalse(after["pagination_complete"])

    def test_replay_gap_does_not_affect_an_independent_source(self) -> None:
        for source_id in ("source-a", "source-b"):
            self.register(source_id)
            _ = ingest(self.store, self.observation(source_id=source_id))
        previous_high = self.now + timedelta(minutes=1)
        first_state = replay(self.store, "source-a")

        with self.assertRaisesRegex(ValueError, "previous checkpoint"):
            _ = ingest(
                self.store,
                self.continued_observation(
                    source_id="source-a",
                    high_water_mark=previous_high + timedelta(hours=1),
                    overlap_floor=previous_high - timedelta(minutes=4),
                ),
            )

        result = ingest(
            self.store,
            self.continued_observation(
                source_id="source-b",
                high_water_mark=previous_high + timedelta(hours=1),
                overlap_floor=previous_high - timedelta(minutes=5),
            ),
        )

        self.assertEqual(replay(self.store, "source-a"), first_state)
        self.assertTrue(result["checkpoint_advanced"])
        self.assertEqual(result["source_id"], "source-b")

    def test_observation_rejects_another_source_owner(self) -> None:
        self.register()
        with self.assertRaisesRegex(ValueError, "does not belong to its owner"):
            _ = ingest(self.store, self.observation(owner="another-worker"))
        self.assertIsNone(replay(self.store, "source-a")["high_water_mark"])

    def test_observation_requires_authentication(self) -> None:
        self.register()
        value = self.observation()
        value["verified"] = False
        with self.assertRaisesRegex(ValueError, "authenticated"):
            _ = ingest(self.store, value)

    def test_observation_rejects_duplicate_event_identifiers(self) -> None:
        self.register()
        with self.assertRaisesRegex(ValueError, "repeats an event"):
            _ = ingest(
                self.store, self.observation(events=[self.event(), self.event()])
            )

    def test_observation_reuses_existing_immutable_events(self) -> None:
        self.register()
        page = self.observation(events=[self.event()])
        first = ingest(self.store, page)
        second = ingest(self.store, page)
        self.assertEqual(first["receipt_id"], second["receipt_id"])
        self.assertEqual(second["discovered"], 0)
        self.assertEqual(second["deduplicated"], 1)

    def test_observation_rejects_mutated_existing_event(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation(events=[self.event()]))
        with self.assertRaisesRegex(ValueError, "immutable notification"):
            _ = ingest(
                self.store,
                self.observation(events=[self.event(actor="another-author")]),
            )

    def test_observation_rejects_shortened_replay_window(self) -> None:
        self.register()
        value = self.observation()
        value["overlap_floor"] = self.now.isoformat()
        with self.assertRaisesRegex(ValueError, "required overlap"):
            _ = ingest(self.store, value)

    def test_observation_rejects_regressed_watermark(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        value = self.observation()
        value["high_water_mark"] = (
            self.now - timedelta(minutes=1)
        ).isoformat()
        value["overlap_floor"] = (
            self.now - timedelta(minutes=6)
        ).isoformat()
        with self.assertRaisesRegex(ValueError, "cannot regress"):
            _ = ingest(self.store, value)

    def test_observation_rejects_event_after_watermark(self) -> None:
        self.register()
        event = self.event(
            occurred_at=(self.now + timedelta(hours=1)).isoformat()
        )
        with self.assertRaisesRegex(ValueError, "high-water mark"):
            _ = ingest(self.store, self.observation(events=[event]))

    def test_observation_does_not_treat_emergency_cutoff_as_normal_policy(self) -> None:
        self.register()
        event = self.event(
            occurred_at=(self.cutoff - timedelta(seconds=1)).isoformat()
        )
        result = ingest(self.store, self.observation(events=[event]))
        self.assertEqual(result["discovered"], 1)

    def test_complete_reconciliation_preserves_review_before_replay_floor(
        self,
    ) -> None:
        self.register()
        actual_time = self.cutoff - timedelta(hours=1)
        event = self.event(
            event_id="outstanding-review",
            logical_cycle_id="outstanding-review-cycle",
            occurred_at=actual_time.isoformat(),
        )

        result = ingest(self.store, self.observation(events=[event]))

        self.assertEqual(result["discovered"], 1)
        self.assertTrue(result["pagination_complete"])
        notification = self.store.connection.execute(
            "SELECT occurred_at, raw_json FROM notifications "
            "WHERE source_id = ? AND event_id = ?",
            ("source-a", "outstanding-review"),
        ).fetchone()
        assert notification is not None
        expected_time = actual_time.isoformat(timespec="microseconds")
        self.assertEqual(notification["occurred_at"], expected_time)
        self.assertEqual(
            json.loads(notification["raw_json"])["occurred_at"],
            expected_time,
        )
        receipt = self.store.connection.execute(
            "SELECT raw_json FROM receipts "
            "WHERE source_id = ? AND event_id = ? AND status = 'DISCOVERED'",
            ("source-a", "outstanding-review"),
        ).fetchone()
        assert receipt is not None
        evidence = json.loads(receipt["raw_json"])
        self.assertEqual(evidence["occurred_at"], expected_time)
        self.assertEqual(
            evidence["payload"]["occurred_at"], actual_time.isoformat()
        )
        self.assertLess(actual_time, self.cutoff)
        self.assertEqual(len(self.store.pending(category="review_request")), 1)

    def test_observation_accepts_notification_at_initial_cutoff(self) -> None:
        self.register()
        result = ingest(
            self.store,
            self.observation(
                events=[self.event(occurred_at=self.cutoff.isoformat())]
            ),
        )
        self.assertEqual(result["discovered"], 1)

    def test_observation_accepts_notification_after_initial_cutoff(self) -> None:
        self.register()
        result = ingest(
            self.store,
            self.observation(
                events=[
                    self.event(
                        occurred_at=(self.cutoff + timedelta(seconds=1)).isoformat()
                    )
                ]
            ),
        )
        self.assertEqual(result["discovered"], 1)

    def test_invalid_page_does_not_partially_insert_notifications(self) -> None:
        self.register()
        bad = self.event(event_id="event-b", head="short")
        with self.assertRaisesRegex(ValueError, "complete lowercase"):
            _ = ingest(self.store, self.observation(events=[self.event(), bad]))
        self.assertFalse(self.store.pending())
        self.assertIsNone(replay(self.store, "source-a")["high_water_mark"])

    def test_review_requires_a_human(self) -> None:
        with self.assertRaisesRegex(ValueError, "originate from a human"):
            _ = NotificationEvent.from_object(
                self.event(actor_type="Bot"), source_id="source-a"
            )

    def test_native_bot_carrier_preserves_verified_human_review_request(
        self,
    ) -> None:
        for source_id in (
            "provider_review_requested_search",
            "provider_individually_assigned_pull_requests",
        ):
            with self.subTest(source_id=source_id):
                self.register(source_id)
                carrier = self.event(
                    event_id=f"{source_id}:native-request-42",
                    logical_cycle_id=f"{source_id}:review-cycle-42",
                    actor="native-carrier",
                    actor_type="Bot",
                    reviewer="actual-individual",
                    author="human-author",
                    author_type="User",
                )

                result = ingest(
                    self.store,
                    self.observation(source_id=source_id, events=[carrier]),
                )

                self.assertEqual(result["discovered"], 1)
                notification = self.store.connection.execute(
                    "SELECT actor, actor_type, occurred_at, raw_json "
                    "FROM notifications WHERE source_id = ? AND event_id = ?",
                    (source_id, carrier["event_id"]),
                ).fetchone()
                assert notification is not None
                self.assertEqual(notification["actor"], "native-carrier")
                self.assertEqual(notification["actor_type"], "Bot")
                self.assertEqual(
                    notification["occurred_at"],
                    self.now.isoformat(timespec="microseconds"),
                )
                payload = json.loads(notification["raw_json"])["payload"]
                self.assertEqual(payload["reviewer"], "actual-individual")
                self.assertEqual(payload["author"], "human-author")
                self.assertEqual(payload["author_type"], "User")
                self.assertTrue(payload["verified"])

    def test_bot_review_carrier_requires_native_individual_source(self) -> None:
        carrier = self.event(
            actor="native-carrier",
            actor_type="Bot",
            reviewer="actual-individual",
            author="human-author",
            author_type="User",
        )

        for source_id in ("source-a", "provider_team_requests", "provider_comments"):
            with self.subTest(source_id=source_id):
                with self.assertRaisesRegex(ValueError, "originate from a human"):
                    _ = NotificationEvent.from_object(carrier, source_id=source_id)

    def test_native_bot_review_carrier_requires_authenticated_human_author(
        self,
    ) -> None:
        base = self.event(
            actor="native-carrier",
            actor_type="Bot",
            reviewer="actual-individual",
            author="human-author",
            author_type="User",
        )
        cases: list[dict[str, object]] = [
            {"author_type": "Bot"},
            {"author_type": None},
            {"reviewer_type": "Team"},
            {"verified": False},
        ]

        for overrides in cases:
            with self.subTest(overrides=overrides):
                carrier = dict(base)
                carrier.update(overrides)
                with self.assertRaises(ValueError):
                    _ = NotificationEvent.from_object(
                        carrier,
                        source_id="provider_review_requested_search",
                    )

    def test_native_bot_carrier_rejects_self_requested_human_review(
        self,
    ) -> None:
        carrier = self.event(
            actor="native-carrier",
            actor_type="Bot",
            reviewer="human-author",
            author="human-author",
            author_type="User",
        )

        with self.assertRaisesRegex(ValueError, "self-requested"):
            _ = NotificationEvent.from_object(
                carrier,
                source_id="provider_review_requested_search",
            )

    def test_atomic_batch_accepts_authenticated_native_bot_review_carrier(
        self,
    ) -> None:
        source_ids = [f"source-{index}" for index in range(8)]
        native_source = "provider_review_requested_search"
        source_ids.append(native_source)
        for source_id in source_ids:
            self.register(source_id)
        observations = [
            self.observation(source_id=source_id)
            for source_id in source_ids[:-1]
        ]
        carrier = self.event(
            event_id="native-bot-review-event-42",
            actor="native-carrier",
            actor_type="Bot",
            reviewer="actual-individual",
            author="human-author",
            author_type="User",
        )
        observations.append(
            self.observation(source_id=native_source, events=[carrier])
        )

        result = self.batch(observations)

        self.assertEqual(result["source_count"], 9)
        self.assertTrue(replay(self.store, native_source)["pagination_complete"])
        pending = self.store.pending(category="review_request")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["event_id"], "native-bot-review-event-42")

    def test_review_rejects_self_requests(self) -> None:
        with self.assertRaisesRegex(ValueError, "self-requested"):
            _ = NotificationEvent.from_object(
                self.event(reviewer="author"), source_id="source-a"
            )

    def test_review_requires_complete_head(self) -> None:
        with self.assertRaisesRegex(ValueError, "complete lowercase"):
            _ = NotificationEvent.from_object(
                self.event(head="a" * 9), source_id="source-a"
            )

    def test_review_requires_authenticated_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "authenticated"):
            _ = NotificationEvent.from_object(
                self.event(verified=False), source_id="source-a"
            )

    def test_control_tasks_require_a_human(self) -> None:
        event = self.event(category="control_task", actor_type="Bot")
        with self.assertRaisesRegex(ValueError, "originate from a human"):
            _ = NotificationEvent.from_object(event, source_id="source-a")

    def test_owned_feedback_accepts_verified_automation(self) -> None:
        event = NotificationEvent.from_object(
            self.event(category="owned_feedback", actor_type="Bot"),
            source_id="source-a",
        )
        self.assertEqual(event.category, "owned_feedback")

    def test_unsigned_principal_feedback_remains_actionable_on_owned_change(
        self,
    ) -> None:
        self.register()
        actual_time = self.cutoff - timedelta(hours=1)
        event = self.event(
            event_id="inline-comment-42",
            category="owned_feedback",
            subject_key="example/project#42",
            actor="principal",
            actor_type="User",
            occurred_at=actual_time.isoformat(),
            comment="This test adds unnecessary coverage.",
            is_resolved=False,
            is_outdated=False,
        )

        result = ingest(self.store, self.observation(events=[event]))

        self.assertEqual(result["discovered"], 1)
        pending = self.store.pending(category="owned_feedback")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["event_id"], "inline-comment-42")
        notification = self.store.connection.execute(
            "SELECT actor, actor_type, occurred_at, raw_json "
            "FROM notifications WHERE source_id = ? AND event_id = ?",
            ("source-a", "inline-comment-42"),
        ).fetchone()
        assert notification is not None
        self.assertEqual(notification["actor"], "principal")
        self.assertEqual(notification["actor_type"], "User")
        self.assertEqual(
            notification["occurred_at"], actual_time.isoformat(timespec="microseconds")
        )
        payload = json.loads(notification["raw_json"])["payload"]
        self.assertFalse(payload["is_resolved"])
        self.assertFalse(payload["is_outdated"])
        self.assertNotIn("delegate_signature", payload)
        self.assertEqual(self.store.pending(category="review_request"), [])

    def test_ci_updates_are_not_review_requests(self) -> None:
        self.register()
        event = self.event(
            category="ci_update", actor="ci", actor_type="Bot"
        )
        _ = ingest(self.store, self.observation(events=[event]))
        self.assertEqual(len(self.store.pending(category="ci_update")), 1)
        self.assertEqual(self.store.pending(category="review_request"), [])

    def test_owned_full_head_ci_settlement_has_one_immutable_transition(
        self,
    ) -> None:
        self.register()
        head = "a" * 40
        event = self.event(
            event_id=f"check:check-42:{head}:run-7:attempt-1:failure",
            logical_cycle_id=f"ci:check-42:{head}:run-7:attempt-1:failure",
            category="ci_update",
            subject_key="example/project#42",
            actor="checks",
            actor_type="Bot",
            head=head,
            check_id="check-42",
            run_id="run-7",
            attempt=1,
            state="FAILURE",
        )
        observation = self.observation(events=[event])

        first = ingest(self.store, observation)
        repeated = ingest(self.store, observation)

        self.assertEqual(first["discovered"], 1)
        self.assertEqual(repeated["discovered"], 0)
        self.assertEqual(repeated["deduplicated"], 1)
        pending = self.store.pending(category="ci_update")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["event_id"], event["event_id"])
        row = self.store.connection.execute(
            "SELECT head, json_extract(raw_json, '$.payload.check_id'), "
            "json_extract(raw_json, '$.payload.run_id'), "
            "json_extract(raw_json, '$.payload.attempt'), "
            "json_extract(raw_json, '$.payload.state') "
            "FROM notifications WHERE source_id = ? AND event_id = ?",
            ("source-a", event["event_id"]),
        ).fetchone()
        assert row is not None
        self.assertEqual(tuple(row), (head, "check-42", "run-7", 1, "FAILURE"))
        self.assertEqual(self.store.pending(category="review_request"), [])

    def test_message_content_change_preserves_original_immutable_receipt(
        self,
    ) -> None:
        self.register()
        original = self.event(
            event_id="message-42",
            category="control_task",
            subject_key="conversation/root-42",
            provider_message_id="message-42",
            text="original message",
        )
        _ = ingest(self.store, self.observation(events=[original]))
        original_notification = self.store.connection.execute(
            "SELECT raw_json FROM notifications "
            "WHERE source_id = ? AND event_id = ?",
            ("source-a", "message-42"),
        ).fetchone()
        original_receipt = self.store.connection.execute(
            "SELECT raw_json FROM receipts "
            "WHERE source_id = ? AND event_id = ? AND status = 'DISCOVERED'",
            ("source-a", "message-42"),
        ).fetchone()
        assert original_notification is not None
        assert original_receipt is not None
        observed_at = self.now + timedelta(seconds=30)
        changed = self.event(
            event_id="message-42:observed-content:updated",
            category="control_task",
            subject_key="conversation/root-42",
            occurred_at=observed_at.isoformat(),
            provider_message_id="message-42",
            original_message_at=self.now.isoformat(),
            observed_at=observed_at.isoformat(),
            text="updated message",
        )
        observation = self.observation(events=[changed])

        first = ingest(self.store, observation)
        repeated = ingest(self.store, observation)

        self.assertEqual(first["discovered"], 1)
        self.assertEqual(repeated["discovered"], 0)
        self.assertEqual(repeated["deduplicated"], 1)
        retained_notification = self.store.connection.execute(
            "SELECT raw_json FROM notifications "
            "WHERE source_id = ? AND event_id = ?",
            ("source-a", "message-42"),
        ).fetchone()
        retained_receipt = self.store.connection.execute(
            "SELECT raw_json FROM receipts "
            "WHERE source_id = ? AND event_id = ? AND status = 'DISCOVERED'",
            ("source-a", "message-42"),
        ).fetchone()
        assert retained_notification is not None
        assert retained_receipt is not None
        self.assertEqual(
            retained_notification["raw_json"], original_notification["raw_json"]
        )
        self.assertEqual(retained_receipt["raw_json"], original_receipt["raw_json"])
        updated = self.store.connection.execute(
            "SELECT occurred_at, raw_json FROM notifications "
            "WHERE source_id = ? AND event_id = ?",
            ("source-a", "message-42:observed-content:updated"),
        ).fetchone()
        assert updated is not None
        self.assertEqual(
            updated["occurred_at"], observed_at.isoformat(timespec="microseconds")
        )
        payload = json.loads(updated["raw_json"])["payload"]
        self.assertEqual(payload["provider_message_id"], "message-42")
        self.assertEqual(payload["observed_at"], observed_at.isoformat())
        self.assertEqual(payload["text"], "updated message")
        self.assertNotIn("edited_at", payload)
        self.assertEqual(len(self.store.pending(category="control_task")), 2)

    def test_mutable_ci_comment_has_one_immutable_event_per_assessed_head(
        self,
    ) -> None:
        self.register()
        comment_id = "comment-42"
        heads = ("a" * 40, "b" * 40)

        for head in heads:
            event = self.event(
                event_id=f"{comment_id}@{head}",
                category="ci_update",
                actor="ci",
                actor_type="Bot",
                head=head,
                provider_comment_id=comment_id,
            )
            result = ingest(
                self.store,
                self.observation(events=[event]),
            )
            self.assertEqual(result["discovered"], 1)

        rows = self.store.connection.execute(
            "SELECT event_id, head, "
            "json_extract(raw_json, '$.payload.provider_comment_id') "
            "AS provider_comment_id "
            "FROM notifications WHERE source_id = ? AND category = 'ci_update' "
            "ORDER BY head",
            ("source-a",),
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in rows],
            [
                (f"{comment_id}@{head}", head, comment_id)
                for head in heads
            ],
        )
        self.assertEqual(len(self.store.pending(category="ci_update")), 2)
        self.assertEqual(self.store.pending(category="review_request"), [])
        receipt_count = self.store.connection.execute(
            "SELECT count(*) FROM receipts "
            "WHERE source_id = ? AND status = 'DISCOVERED'",
            ("source-a",),
        ).fetchone()
        assert receipt_count is not None
        self.assertEqual(receipt_count[0], 2)

    def test_mutable_merge_status_retains_distinct_current_head_states(
        self,
    ) -> None:
        self.register()
        comment_id = "comment-42"
        head = "a" * 40
        pull_request_base = "b" * 40
        observations = (
            ("build-1", "run-1", "running", "c" * 40),
            ("build-1", "run-1", "failed", "c" * 40),
            ("build-2", "run-2", "passed", "d" * 40),
        )

        for build_id, run_id, state, merge_validation_base in observations:
            self.assertNotEqual(merge_validation_base, pull_request_base)
            event_id = f"{comment_id}@{head}:{build_id}:{run_id}:{state}"
            event = self.event(
                event_id=event_id,
                category="ci_update",
                actor="ci",
                actor_type="Bot",
                head=head,
                logical_cycle_id=f"ci-update:{event_id}",
                provider_comment_id=comment_id,
                build_id=build_id,
                run_id=run_id,
                state=state,
                merge_validation_base=merge_validation_base,
                pull_request_base=pull_request_base,
            )
            result = ingest(self.store, self.observation(events=[event]))
            self.assertEqual(result["discovered"], 1)

        notifications = self.store.connection.execute(
            "SELECT event_id, head, "
            "json_extract(raw_json, '$.payload.provider_comment_id'), "
            "json_extract(raw_json, '$.payload.build_id'), "
            "json_extract(raw_json, '$.payload.run_id'), "
            "json_extract(raw_json, '$.payload.state'), "
            "json_extract(raw_json, '$.payload.merge_validation_base'), "
            "json_extract(raw_json, '$.payload.pull_request_base') "
            "FROM notifications WHERE source_id = ? AND category = 'ci_update' "
            "ORDER BY event_id",
            ("source-a",),
        ).fetchall()
        expected = [
            (
                f"{comment_id}@{head}:{build_id}:{run_id}:{state}",
                head,
                comment_id,
                build_id,
                run_id,
                state,
                merge_validation_base,
                pull_request_base,
            )
            for build_id, run_id, state, merge_validation_base in observations
        ]
        self.assertEqual([tuple(row) for row in notifications], sorted(expected))
        claims = self.store.pending(category="ci_update")
        self.assertEqual(
            sorted(claim["event_id"] for claim in claims),
            sorted(row[0] for row in expected),
        )
        receipts = self.store.connection.execute(
            "SELECT event_id FROM receipts "
            "WHERE source_id = ? AND status = 'DISCOVERED' ORDER BY event_id",
            ("source-a",),
        ).fetchall()
        self.assertEqual(
            [row["event_id"] for row in receipts],
            sorted(row[0] for row in expected),
        )
        self.assertEqual(self.store.pending(category="review_request"), [])

    def test_unsupported_notification_category_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported"):
            _ = NotificationEvent.from_object(
                self.event(category="unsupported"), source_id="source-a"
            )

    def test_claim_has_exactly_one_owner(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation(events=[self.event()]))
        cycle = self.store.pending()[0]["logical_cycle_id"]
        assert isinstance(cycle, str)
        self.assertFalse(
            claim(self.store, logical_cycle_id=cycle, owner="first")[
                "already_claimed"
            ]
        )
        with self.assertRaisesRegex(ValueError, "already claimed"):
            _ = claim(self.store, logical_cycle_id=cycle, owner="second")

    def test_claim_is_idempotent_for_owner(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation(events=[self.event()]))
        cycle = self.store.pending()[0]["logical_cycle_id"]
        assert isinstance(cycle, str)
        _ = claim(self.store, logical_cycle_id=cycle, owner="first")
        self.assertTrue(
            claim(self.store, logical_cycle_id=cycle, owner="first")[
                "already_claimed"
            ]
        )

    def test_native_and_message_review_requests_share_one_published_review(
        self,
    ) -> None:
        self.register("native-source")
        self.register("message-source")
        cycle = "human-review-cycle"
        head = "a" * 40
        native = self.event(
            event_id="native-review-request",
            logical_cycle_id=cycle,
            head=head,
            provider_kind="native",
        )
        message = self.event(
            event_id="direct-message-review-request",
            logical_cycle_id=cycle,
            head=head,
            provider_kind="direct_message",
        )

        first = ingest(
            self.store,
            self.observation(source_id="native-source", events=[native]),
        )
        second = ingest(
            self.store,
            self.observation(source_id="message-source", events=[message]),
        )

        self.assertEqual(first["discovered"], 1)
        self.assertEqual(second["discovered"], 1)
        notifications = self.store.connection.execute(
            "SELECT source_id, event_id, logical_cycle_id, head "
            "FROM notifications WHERE logical_cycle_id = ? "
            "ORDER BY source_id",
            (cycle,),
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in notifications],
            [
                ("message-source", "direct-message-review-request", cycle, head),
                ("native-source", "native-review-request", cycle, head),
            ],
        )
        discovered = self.store.connection.execute(
            "SELECT source_id, event_id FROM receipts "
            "WHERE logical_cycle_id = ? AND status = 'DISCOVERED' "
            "ORDER BY source_id",
            (cycle,),
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in discovered],
            [
                ("message-source", "direct-message-review-request"),
                ("native-source", "native-review-request"),
            ],
        )
        claims = self.store.connection.execute(
            "SELECT source_id, event_id, status FROM claims "
            "WHERE logical_cycle_id = ?",
            (cycle,),
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in claims],
            [("native-source", "native-review-request", "pending")],
        )

        _ = claim(self.store, logical_cycle_id=cycle, owner="worker-a")
        published = resolve(
            self.store,
            logical_cycle_id=cycle,
            owner="worker-a",
            review_id="published-review",
        )
        repeated = resolve(
            self.store,
            logical_cycle_id=cycle,
            owner="worker-a",
            review_id="published-review",
        )

        self.assertFalse(published["already_resolved"])
        self.assertTrue(repeated["already_resolved"])
        terminal = self.store.connection.execute(
            "SELECT event_id, status FROM receipts "
            "WHERE logical_cycle_id = ? AND status = 'RESOLVED'",
            (cycle,),
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in terminal],
            [("native-review-request", "RESOLVED")],
        )
        self.assertEqual(self.store.pending(category="review_request"), [])

    def test_only_claim_owner_can_resolve_notification(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation(events=[self.event()]))
        cycle = self.store.pending()[0]["logical_cycle_id"]
        assert isinstance(cycle, str)
        _ = claim(self.store, logical_cycle_id=cycle, owner="first")
        with self.assertRaisesRegex(ValueError, "original notification owner"):
            _ = resolve(
                self.store, logical_cycle_id=cycle, owner="second", review_id="1"
            )

    def test_resolution_is_idempotent(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation(events=[self.event()]))
        cycle = self.store.pending()[0]["logical_cycle_id"]
        assert isinstance(cycle, str)
        _ = claim(self.store, logical_cycle_id=cycle, owner="first")
        first = resolve(
            self.store, logical_cycle_id=cycle, owner="first", review_id="event-1"
        )
        repeated = resolve(
            self.store, logical_cycle_id=cycle, owner="first", review_id="event-1"
        )
        self.assertFalse(first["already_resolved"])
        self.assertTrue(repeated["already_resolved"])
        self.assertEqual(self.store.pending(), [])

    def test_resolution_rejects_changed_terminal_evidence(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation(events=[self.event()]))
        cycle = self.store.pending()[0]["logical_cycle_id"]
        assert isinstance(cycle, str)
        _ = claim(self.store, logical_cycle_id=cycle, owner="first")
        _ = resolve(
            self.store, logical_cycle_id=cycle, owner="first", review_id="first"
        )
        with self.assertRaisesRegex(ValueError, "different terminal"):
            _ = resolve(
                self.store, logical_cycle_id=cycle, owner="first", review_id="second"
            )

    def test_resolution_batch_resolves_original_owners_atomically(self) -> None:
        self.register()
        _ = ingest(
            self.store,
            self.observation(
                events=[
                    self.event(event_id="first-event", subject_key="example/project#1"),
                    self.event(event_id="second-event", subject_key="example/project#2"),
                ]
            ),
        )
        pending = self.store.pending()
        cycles = {
            row["subject_key"]: row["logical_cycle_id"] for row in pending
        }
        first = cycles["example/project#1"]
        second = cycles["example/project#2"]
        assert isinstance(first, str)
        assert isinstance(second, str)

        result = resolve_batch(
            self.store,
            [
                {
                    "verified": True,
                    "logical_cycle_id": first,
                    "owner": "original-first",
                    "review_id": "review-first",
                },
                {
                    "verified": True,
                    "logical_cycle_id": second,
                    "owner": "original-second",
                    "review_id": "review-second",
                },
            ],
        )

        self.assertEqual(result["resolution_count"], 2)
        self.assertEqual(self.store.pending(), [])
        rows = self.store.connection.execute(
            "SELECT owner, terminal_event_id FROM claims ORDER BY subject_key"
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in rows],
            [("original-first", "review-first"), ("original-second", "review-second")],
        )

    def test_resolution_batch_is_idempotent_with_matching_evidence(self) -> None:
        cycle = self.pending_cycle()
        evidence = [
            {
                "verified": True,
                "logical_cycle_id": cycle,
                "owner": "original-owner",
                "review_id": "published-review",
            }
        ]

        first = resolve_batch(self.store, evidence)
        second = resolve_batch(self.store, evidence)

        first_results = first["results"]
        second_results = second["results"]
        assert isinstance(first_results, list)
        assert isinstance(second_results, list)
        self.assertFalse(first_results[0]["already_resolved"])
        self.assertTrue(second_results[0]["already_resolved"])

    def test_resolution_batch_corrects_a_proven_original_terminal(self) -> None:
        cycle = self.pending_cycle()
        _ = resolve_batch(
            self.store,
            [
                {
                    "verified": True,
                    "logical_cycle_id": cycle,
                    "owner": "original-owner",
                    "review_id": "linked-source-review",
                }
            ],
        )

        result = resolve_batch(
            self.store,
            [
                {
                    "verified": True,
                    "logical_cycle_id": cycle,
                    "owner": "original-owner",
                    "review_id": "provider-visible-review",
                    "replaces_review_id": "linked-source-review",
                    "correction_reason": "The requested provider requires its own review.",
                }
            ],
        )

        self.assertEqual(result["resolution_count"], 1)
        row = self.store.connection.execute(
            "SELECT owner, status, terminal_event_id FROM claims "
            "WHERE logical_cycle_id = ?",
            (cycle,),
        ).fetchone()
        assert row is not None
        self.assertEqual(
            tuple(row),
            ("original-owner", "resolved", "provider-visible-review"),
        )
        receipts = self.store.connection.execute(
            "SELECT status FROM receipts "
            "WHERE logical_cycle_id = ? AND status IN ('RESOLVED', 'CORRECTED') "
            "ORDER BY rowid",
            (cycle,),
        ).fetchall()
        self.assertEqual([row["status"] for row in receipts], ["RESOLVED", "CORRECTED"])

    def test_resolution_correction_rejects_a_wrong_owner_or_prior_terminal(
        self,
    ) -> None:
        cycle = self.pending_cycle()
        _ = resolve_batch(
            self.store,
            [
                {
                    "verified": True,
                    "logical_cycle_id": cycle,
                    "owner": "original-owner",
                    "review_id": "linked-source-review",
                }
            ],
        )
        cases = (
            ("another-owner", "linked-source-review", "original notification owner"),
            ("original-owner", "unrelated-review", "does not match the prior review"),
        )

        for owner, previous, error in cases:
            with self.subTest(owner=owner, previous=previous):
                with self.assertRaisesRegex(ValueError, error):
                    _ = resolve_batch(
                        self.store,
                        [
                            {
                                "verified": True,
                                "logical_cycle_id": cycle,
                                "owner": owner,
                                "review_id": "provider-visible-review",
                                "replaces_review_id": previous,
                                "correction_reason": "Verified provider correction.",
                            }
                        ],
                    )

        row = self.store.connection.execute(
            "SELECT owner, terminal_event_id FROM claims "
            "WHERE logical_cycle_id = ?",
            (cycle,),
        ).fetchone()
        assert row is not None
        self.assertEqual(tuple(row), ("original-owner", "linked-source-review"))

    def test_resolution_batch_rolls_back_wrong_original_owner(self) -> None:
        self.register()
        _ = ingest(
            self.store,
            self.observation(
                events=[
                    self.event(event_id="first-event", subject_key="example/project#1"),
                    self.event(event_id="second-event", subject_key="example/project#2"),
                ]
            ),
        )
        cycles = {
            row["subject_key"]: row["logical_cycle_id"]
            for row in self.store.pending()
        }
        first = cycles["example/project#1"]
        second = cycles["example/project#2"]
        assert isinstance(first, str)
        assert isinstance(second, str)
        _ = claim(self.store, logical_cycle_id=second, owner="original-second")
        before = self.store.stats()

        with self.assertRaisesRegex(ValueError, "already claimed or resolved"):
            _ = resolve_batch(
                self.store,
                [
                    {
                        "verified": True,
                        "logical_cycle_id": first,
                        "owner": "original-first",
                        "review_id": "review-first",
                    },
                    {
                        "verified": True,
                        "logical_cycle_id": second,
                        "owner": "wrong-owner",
                        "review_id": "review-second",
                    },
                ],
            )

        self.assertEqual(self.store.stats(), before)
        row = self.store.connection.execute(
            "SELECT status, owner FROM claims WHERE logical_cycle_id = ?", (first,)
        ).fetchone()
        assert row is not None
        self.assertEqual(tuple(row), ("pending", None))

    def test_resolution_batch_rejects_invalid_and_duplicate_evidence(self) -> None:
        cycle = self.pending_cycle()
        valid = {
            "verified": True,
            "logical_cycle_id": cycle,
            "owner": "original-owner",
            "review_id": "published-review",
        }
        cases: tuple[tuple[object, str], ...] = (
            ([], "nonempty JSON array"),
            ({}, "nonempty JSON array"),
            ([None], "JSON object"),
            ([dict(valid, verified=False)], "authenticated evidence"),
            ([valid, valid], "repeats a cycle"),
            ([valid] * (MAXIMUM_LIMIT + 1), "cannot exceed"),
        )
        for value, error in cases:
            with self.subTest(error=error):
                with self.assertRaisesRegex(ValueError, error):
                    _ = resolve_batch(self.store, value)
        self.assertEqual(len(self.store.pending()), 1)

    def test_resolution_batch_rolls_back_changed_terminal_evidence(self) -> None:
        self.register()
        _ = ingest(
            self.store,
            self.observation(
                events=[
                    self.event(event_id="first-event", subject_key="example/project#1"),
                    self.event(event_id="second-event", subject_key="example/project#2"),
                ]
            ),
        )
        cycles = {
            row["subject_key"]: row["logical_cycle_id"]
            for row in self.store.pending()
        }
        first = cycles["example/project#1"]
        second = cycles["example/project#2"]
        assert isinstance(first, str)
        assert isinstance(second, str)
        _ = claim(self.store, logical_cycle_id=second, owner="original-second")
        _ = resolve(
            self.store,
            logical_cycle_id=second,
            owner="original-second",
            review_id="actual-second",
        )
        before = self.store.stats()

        with self.assertRaisesRegex(ValueError, "different terminal"):
            _ = resolve_batch(
                self.store,
                [
                    {
                        "verified": True,
                        "logical_cycle_id": first,
                        "owner": "original-first",
                        "review_id": "actual-first",
                    },
                    {
                        "verified": True,
                        "logical_cycle_id": second,
                        "owner": "original-second",
                        "review_id": "fabricated-second",
                    },
                ],
            )

        self.assertEqual(self.store.stats(), before)
        row = self.store.connection.execute(
            "SELECT status, owner FROM claims WHERE logical_cycle_id = ?", (first,)
        ).fetchone()
        assert row is not None
        self.assertEqual(tuple(row), ("pending", None))

    def test_resolution_batch_cli_reads_authenticated_json(self) -> None:
        cycle = self.pending_cycle()
        evidence = [
            {
                "verified": True,
                "logical_cycle_id": cycle,
                "owner": "original-owner",
                "review_id": "published-review",
            }
        ]
        output = StringIO()
        with (
            patch("sys.stdin", StringIO(json.dumps(evidence))),
            redirect_stdout(output),
        ):
            result = main(["--database", str(self.path), "resolve-batch"])

        self.assertEqual(result, 0)
        decoded: object = json.loads(output.getvalue())
        self.assertIsInstance(decoded, dict)
        assert isinstance(decoded, dict)
        self.assertEqual(decoded["resolution_count"], 1)
        self.assertEqual(self.store.pending(), [])

    def test_supersession_closes_pending_claim_without_forging_review(self) -> None:
        cycle = self.pending_cycle()
        original = self.store.connection.execute(
            "SELECT raw_json FROM notifications "
            "WHERE source_id = ? AND event_id = ?",
            ("source-a", "event-a"),
        ).fetchone()
        assert original is not None

        result = supersede(
            self.store,
            logical_cycle_id=cycle,
            owner="worker-a",
            evidence=self.supersession_evidence(),
        )

        self.assertFalse(result["already_superseded"])
        self.assertEqual(self.store.pending(), [])
        row = self.store.connection.execute(
            "SELECT owner, status, terminal_event_id FROM claims "
            "WHERE logical_cycle_id = ?",
            (cycle,),
        ).fetchone()
        assert row is not None
        self.assertEqual(
            tuple(row), ("worker-a", "superseded", "provider-proof-a")
        )
        notification = self.store.connection.execute(
            "SELECT raw_json FROM notifications "
            "WHERE source_id = ? AND event_id = ?",
            ("source-a", "event-a"),
        ).fetchone()
        assert notification is not None
        self.assertEqual(notification["raw_json"], original["raw_json"])

    def test_supersession_command_preserves_original_immutable_receipt(
        self,
    ) -> None:
        cycle = self.pending_cycle()
        original = self.store.connection.execute(
            "SELECT raw_json FROM receipts "
            "WHERE source_id = ? AND event_id = ? AND status = 'DISCOVERED'",
            ("source-a", "event-a"),
        ).fetchone()
        assert original is not None

        result = self.supersession_command(cycle, self.supersession_evidence())

        self.assertFalse(result["already_superseded"])
        self.assertEqual(result["logical_cycle_id"], cycle)
        self.assertEqual(self.store.pending(), [])
        retained = self.store.connection.execute(
            "SELECT raw_json FROM receipts "
            "WHERE source_id = ? AND event_id = ? AND status = 'DISCOVERED'",
            ("source-a", "event-a"),
        ).fetchone()
        assert retained is not None
        self.assertEqual(retained["raw_json"], original["raw_json"])
        terminal = self.store.connection.execute(
            "SELECT status, raw_json FROM receipts "
            "WHERE logical_cycle_id = ? AND status = 'SUPERSEDED'",
            (cycle,),
        ).fetchone()
        assert terminal is not None
        proof = json.loads(terminal["raw_json"])
        self.assertEqual(proof["event_id"], "provider-proof-a")
        self.assertEqual(proof["head"], "a" * 40)
        self.assertTrue(proof["verified"])

    def test_supersession_command_rejects_unauthenticated_evidence(self) -> None:
        cycle = self.pending_cycle()
        before = self.store.stats()

        with self.assertRaisesRegex(ValueError, "authenticated provider evidence"):
            _ = self.supersession_command(
                cycle,
                self.supersession_evidence(verified=False),
            )

        self.assertEqual(self.store.stats(), before)
        self.assertEqual(len(self.store.pending()), 1)

    def test_supersession_command_rejects_mismatched_head(self) -> None:
        cycle = self.pending_cycle()
        before = self.store.stats()

        with self.assertRaisesRegex(ValueError, "exact head"):
            _ = self.supersession_command(
                cycle,
                self.supersession_evidence(head="b" * 40),
            )

        self.assertEqual(self.store.stats(), before)
        self.assertEqual(len(self.store.pending()), 1)

    def test_supersession_command_reuses_immutable_terminal_evidence(
        self,
    ) -> None:
        cycle = self.pending_cycle()
        evidence = self.supersession_evidence()

        first = self.supersession_command(cycle, evidence)
        repeated = self.supersession_command(cycle, evidence)

        self.assertFalse(first["already_superseded"])
        self.assertTrue(repeated["already_superseded"])
        self.assertEqual(first["receipt_id"], repeated["receipt_id"])
        row = self.store.connection.execute(
            "SELECT count(*) FROM receipts "
            "WHERE logical_cycle_id = ? AND status = 'SUPERSEDED'",
            (cycle,),
        ).fetchone()
        assert row is not None
        self.assertEqual(row[0], 1)

    def test_supersession_is_idempotent_and_has_one_terminal_receipt(self) -> None:
        cycle = self.pending_cycle()
        evidence = self.supersession_evidence()
        first = supersede(
            self.store,
            logical_cycle_id=cycle,
            owner="worker-a",
            evidence=evidence,
        )
        repeated = supersede(
            self.store,
            logical_cycle_id=cycle,
            owner="worker-a",
            evidence=evidence,
        )

        self.assertFalse(first["already_superseded"])
        self.assertTrue(repeated["already_superseded"])
        self.assertEqual(first["receipt_id"], repeated["receipt_id"])
        row = self.store.connection.execute(
            "SELECT count(*) FROM receipts "
            "WHERE logical_cycle_id = ? AND status = 'SUPERSEDED'",
            (cycle,),
        ).fetchone()
        assert row is not None
        self.assertEqual(row[0], 1)

    def test_supersession_rejects_changed_terminal_evidence(self) -> None:
        cycle = self.pending_cycle()
        _ = supersede(
            self.store,
            logical_cycle_id=cycle,
            owner="worker-a",
            evidence=self.supersession_evidence(),
        )

        with self.assertRaisesRegex(ValueError, "different supersession evidence"):
            _ = supersede(
                self.store,
                logical_cycle_id=cycle,
                owner="worker-a",
                evidence=self.supersession_evidence(reason="A different claim."),
            )

    def test_supersession_requires_the_active_source_owner(self) -> None:
        cycle = self.pending_cycle()

        with self.assertRaisesRegex(ValueError, "active source owner"):
            _ = supersede(
                self.store,
                logical_cycle_id=cycle,
                owner="another-worker",
                evidence=self.supersession_evidence(),
            )
        self.assertEqual(len(self.store.pending()), 1)

    def test_source_owner_can_supersede_a_delegated_claim(self) -> None:
        cycle = self.pending_cycle()
        _ = claim(self.store, logical_cycle_id=cycle, owner="delegated-worker")

        first = supersede(
            self.store,
            logical_cycle_id=cycle,
            owner="worker-a",
            evidence=self.supersession_evidence(),
        )
        repeated = supersede(
            self.store,
            logical_cycle_id=cycle,
            owner="worker-a",
            evidence=self.supersession_evidence(),
        )

        self.assertFalse(first["already_superseded"])
        self.assertTrue(repeated["already_superseded"])
        self.assertEqual(first["receipt_id"], repeated["receipt_id"])
        receipt = self.store.connection.execute(
            "SELECT raw_json FROM receipts WHERE receipt_id = ?",
            (first["receipt_id"],),
        ).fetchone()
        assert receipt is not None
        proof = json.loads(receipt["raw_json"])
        self.assertEqual(proof["owner"], "worker-a")
        self.assertEqual(proof["claim_owner"], "delegated-worker")

    def test_supersession_accepts_the_claimed_source_owner(self) -> None:
        cycle = self.pending_cycle()
        _ = claim(self.store, logical_cycle_id=cycle, owner="worker-a")

        result = supersede(
            self.store,
            logical_cycle_id=cycle,
            owner="worker-a",
            evidence=self.supersession_evidence(),
        )

        self.assertFalse(result["already_superseded"])
        self.assertEqual(self.store.pending(), [])

    def test_supersession_closes_the_source_owners_blocked_claim(self) -> None:
        cycle = self.pending_cycle()
        _ = claim(self.store, logical_cycle_id=cycle, owner="delegated-worker")
        _ = self.store.connection.execute(
            "UPDATE claims SET status = 'blocked' "
            "WHERE logical_cycle_id = ? AND owner = ?",
            (cycle, "delegated-worker"),
        )

        result = supersede(
            self.store,
            logical_cycle_id=cycle,
            owner="worker-a",
            evidence=self.supersession_evidence(),
        )

        self.assertFalse(result["already_superseded"])
        row = self.store.connection.execute(
            "SELECT status FROM claims WHERE logical_cycle_id = ?",
            (cycle,),
        ).fetchone()
        assert row is not None
        self.assertEqual(row["status"], "superseded")

    def test_supersession_requires_authenticated_evidence(self) -> None:
        cycle = self.pending_cycle()

        with self.assertRaisesRegex(ValueError, "authenticated"):
            _ = supersede(
                self.store,
                logical_cycle_id=cycle,
                owner="worker-a",
                evidence=self.supersession_evidence(verified=False),
            )
        self.assertEqual(len(self.store.pending()), 1)

    def test_supersession_requires_the_exact_source(self) -> None:
        cycle = self.pending_cycle()

        with self.assertRaisesRegex(ValueError, "match its source"):
            _ = supersede(
                self.store,
                logical_cycle_id=cycle,
                owner="worker-a",
                evidence=self.supersession_evidence(source_id="another-source"),
            )

    def test_supersession_requires_the_exact_head(self) -> None:
        cycle = self.pending_cycle()

        with self.assertRaisesRegex(ValueError, "exact head"):
            _ = supersede(
                self.store,
                logical_cycle_id=cycle,
                owner="worker-a",
                evidence=self.supersession_evidence(head="b" * 40),
            )

    def test_supersession_requires_a_bounded_reason(self) -> None:
        cycle = self.pending_cycle()
        for invalid in ("", " ", "a" * 1025):
            with self.subTest(reason=invalid):
                with self.assertRaises(ValueError):
                    _ = supersede(
                        self.store,
                        logical_cycle_id=cycle,
                        owner="worker-a",
                        evidence=self.supersession_evidence(reason=invalid),
                    )
        self.assertEqual(len(self.store.pending()), 1)

    def test_supersession_requires_a_real_evidence_event(self) -> None:
        cycle = self.pending_cycle()

        with self.assertRaisesRegex(ValueError, "evidence event"):
            _ = supersede(
                self.store,
                logical_cycle_id=cycle,
                owner="worker-a",
                evidence=self.supersession_evidence(event_id=""),
            )

    def test_supersession_rejects_a_resolved_notification(self) -> None:
        cycle = self.pending_cycle()
        _ = claim(self.store, logical_cycle_id=cycle, owner="worker-a")
        _ = resolve(
            self.store,
            logical_cycle_id=cycle,
            owner="worker-a",
            review_id="actual-published-review",
        )

        with self.assertRaisesRegex(ValueError, "resolved"):
            _ = supersede(
                self.store,
                logical_cycle_id=cycle,
                owner="worker-a",
                evidence=self.supersession_evidence(),
            )

    def test_supersession_rejects_a_historical_source(self) -> None:
        cycle = self.pending_cycle()
        _ = self.store.connection.execute(
            "UPDATE sources SET status = 'HISTORICAL' WHERE source_id = ?",
            ("source-a",),
        )

        with self.assertRaisesRegex(ValueError, "active source owner"):
            _ = supersede(
                self.store,
                logical_cycle_id=cycle,
                owner="worker-a",
                evidence=self.supersession_evidence(),
            )

    def test_supersession_rejects_a_missing_claim(self) -> None:
        self.register()

        with self.assertRaisesRegex(ValueError, "does not exist"):
            _ = supersede(
                self.store,
                logical_cycle_id="missing-cycle",
                owner="worker-a",
                evidence=self.supersession_evidence(),
            )

    def test_receipts_cannot_be_modified(self) -> None:
        self.register()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            _ = self.store.connection.execute("UPDATE receipts SET status = 'bad'")

    def test_receipts_cannot_be_deleted(self) -> None:
        self.register()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            _ = self.store.connection.execute("DELETE FROM receipts")

    def test_failure_preserves_existing_watermark(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        before = replay(self.store, "source-a")["high_water_mark"]
        failure: dict[str, object] = {
            "source_id": "source-a",
            "owner": "worker-a",
            "kind": "timeout",
            "observed_at": (self.now + timedelta(minutes=2)).isoformat(),
            "verified": True,
        }
        _ = record_failure(self.store, failure)
        after = replay(self.store, "source-a")
        self.assertEqual(after["high_water_mark"], before)
        self.assertFalse(after["pagination_complete"])

    def test_failure_rejects_another_owner(self) -> None:
        self.register()
        with self.assertRaisesRegex(ValueError, "registered owner"):
            _ = record_failure(
                self.store,
                {
                    "source_id": "source-a",
                    "owner": "another-worker",
                    "kind": "timeout",
                    "observed_at": self.now.isoformat(),
                    "verified": True,
                },
            )

    def test_global_health_includes_sources_outside_display_limit(self) -> None:
        for index in range(13):
            source_id = f"source-{index:02}"
            self.register(source_id)
            if index != 12:
                _ = ingest(
                    self.store,
                    self.observation(source_id=source_id),
                )
        result = self.store.health(limit=12, now=self.now + timedelta(minutes=1))
        self.assertEqual(result["source_count"], 13)
        self.assertEqual(result["unhealthy_sources"], 1)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(len(result["sources"]), 12)

    def test_runtime_configuration_defaults_to_two_minute_source_health(
        self,
    ) -> None:
        self.assertEqual(RuntimeConfig(self.path).maximum_source_age_seconds, 120)

    def test_runtime_configuration_defaults_to_shared_google_drive(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            configuration = RuntimeConfig.from_environment()

        self.assertEqual(
            configuration.database,
            Path.home()
            / "Google Drive"
            / "My Drive"
            / "Codex"
            / "runtime"
            / "review-monitor"
            / "notifications.sqlite3",
        )

    def test_runtime_configuration_retains_explicit_source_health_override(
        self,
    ) -> None:
        with patch.dict(
            "os.environ",
            {
                "CODEX_NOTIFICATION_WATCHER_DATABASE": str(self.path),
                "CODEX_NOTIFICATION_WATCHER_MAXIMUM_SOURCE_AGE": "900",
            },
        ):
            configuration = RuntimeConfig.from_environment()

        self.assertEqual(configuration.database, self.path)
        self.assertEqual(configuration.maximum_source_age_seconds, 900)

    def test_health_accepts_source_at_exact_two_minute_boundary(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())

        result = self.store.health(now=self.now + timedelta(minutes=3))

        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["unhealthy_sources"], 0)

    def test_health_rejects_source_just_after_two_minute_boundary(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())

        result = self.store.health(
            now=self.now + timedelta(minutes=3, microseconds=1)
        )

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["unhealthy_sources"], 1)

    def test_health_honors_explicit_age_above_two_minute_default(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        observed_at = self.now + timedelta(minutes=3, seconds=1)

        default = self.store.health(now=observed_at)
        overridden = self.store.health(
            now=observed_at,
            maximum_age_seconds=900,
        )

        self.assertEqual(default["status"], "degraded")
        self.assertEqual(overridden["status"], "healthy")

    def test_provider_observation_persists_a_real_durable_heartbeat(self) -> None:
        self.register()

        _ = ingest(self.store, self.observation())

        row = self.store.connection.execute(
            "SELECT value_json FROM metadata WHERE key = ?",
            ("notification_heartbeat",),
        ).fetchone()
        assert row is not None
        heartbeat: object = json.loads(str(row["value_json"]))
        assert isinstance(heartbeat, dict)
        self.assertEqual(heartbeat["owner"], "worker-a")
        self.assertEqual(
            utc_datetime(heartbeat["observed_at"], description="heartbeat"),
            self.now + timedelta(minutes=1),
        )

    def test_stalled_reader_is_unhealthy_after_one_hundred_twenty_seconds(
        self,
    ) -> None:
        self.register()
        _ = ingest(self.store, self.observation())

        state = self.store.health(
            now=self.now + timedelta(minutes=3, microseconds=1)
        )

        self.assertEqual(state["status"], "degraded")
        self.assertFalse(state["heartbeat_healthy"])
        self.assertEqual(state["unhealthy_sources"], 1)

    def test_healthy_source_cannot_conceal_a_stalled_reader_heartbeat(
        self,
    ) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        stalled = self.now - timedelta(minutes=2, microseconds=1)
        _ = self.store.connection.execute(
            "UPDATE metadata SET value_json = ? WHERE key = ?",
            (
                json.dumps(
                    {"owner": "worker-a", "observed_at": stalled.isoformat()}
                ),
                "notification_heartbeat",
            ),
        )

        state = self.store.health(now=self.now + timedelta(minutes=1))

        self.assertEqual(state["unhealthy_sources"], 0)
        self.assertFalse(state["heartbeat_healthy"])
        self.assertEqual(state["status"], "degraded")

    def test_older_complete_source_cannot_regress_provider_heartbeat(self) -> None:
        self.register("source-a")
        self.register("source-b")
        newer = self.observation(source_id="source-a")
        older = self.observation(source_id="source-b")
        older["observed_at"] = self.now.isoformat()
        older["high_water_mark"] = self.now.isoformat()

        _ = ingest(self.store, newer)
        _ = ingest(self.store, older)

        row = self.store.connection.execute(
            "SELECT value_json FROM metadata WHERE key = ?",
            ("notification_heartbeat",),
        ).fetchone()
        assert row is not None
        heartbeat: object = json.loads(str(row["value_json"]))
        assert isinstance(heartbeat, dict)
        self.assertEqual(
            utc_datetime(heartbeat["observed_at"], description="heartbeat"),
            self.now + timedelta(minutes=1),
        )

    def test_health_detects_expired_required_source_outside_display_limit(
        self,
    ) -> None:
        _ = bootstrap(
            self.store,
            {"owner": "worker-a", "sources": ["source-a", "source-z"]},
        )
        fresh = self.observation(source_id="source-a")
        checkpoint = (self.now + timedelta(minutes=2)).isoformat()
        fresh["observed_at"] = checkpoint
        fresh["high_water_mark"] = checkpoint
        _ = ingest(self.store, fresh)
        _ = ingest(self.store, self.observation(source_id="source-z"))

        result = self.store.health(
            limit=1,
            now=self.now + timedelta(minutes=3, seconds=1),
        )

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["unhealthy_sources"], 1)
        self.assertEqual(result["missing_sources"], [])
        sources = result["sources"]
        assert isinstance(sources, list)
        self.assertEqual(len(sources), 1)
        displayed = sources[0]
        assert isinstance(displayed, dict)
        self.assertEqual(displayed["source_id"], "source-a")
        self.assertTrue(displayed["healthy"])

    def test_health_rejects_missing_configured_source(self) -> None:
        _ = bootstrap(
            self.store,
            {
                "owner": "worker-a",
                "sources": ["source-a", "source-b"],
            },
        )
        _ = ingest(self.store, self.observation())
        _ = self.store.connection.execute(
            "DELETE FROM sources WHERE source_id = ?", ("source-b",)
        )

        result = self.store.health(
            limit=1, now=self.now + timedelta(minutes=1)
        )

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["source_count"], 1)
        self.assertEqual(result["unhealthy_sources"], 1)
        self.assertEqual(result["missing_sources"], ["source-b"])

    def test_historical_source_does_not_make_manifest_unhealthy(self) -> None:
        _ = bootstrap(
            self.store,
            {"owner": "worker-a", "sources": ["source-a"]},
        )
        _ = ingest(self.store, self.observation())
        _ = self.store.connection.execute(
            "INSERT INTO sources "
            "(source_id, owner, status, high_water_mark, overlap_floor, "
            "overlap_seconds, pagination_complete, raw_json) "
            "VALUES (?, ?, 'HISTORICAL', NULL, NULL, 300, 0, '{}')",
            ("historical-source", "historical"),
        )

        result = self.store.health(now=self.now + timedelta(minutes=1))

        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["source_count"], 1)

    def test_historical_source_rejects_new_observations(self) -> None:
        self.register()
        _ = self.store.connection.execute(
            "UPDATE sources SET status = 'HISTORICAL' WHERE source_id = ?",
            ("source-a",),
        )
        with self.assertRaisesRegex(ValueError, "historical sources"):
            _ = ingest(self.store, self.observation())

    def test_health_rejects_unobserved_source(self) -> None:
        self.register()
        self.assertEqual(self.store.health(now=self.now)["status"], "degraded")

    def test_health_rejects_expired_source(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        self.assertEqual(
            self.store.health(now=self.now + timedelta(hours=2))["status"],
            "degraded",
        )

    def test_health_rejects_future_source_checkpoint(self) -> None:
        self.register()
        _ = ingest(self.store, self.observation())
        self.assertEqual(self.store.health(now=self.now)["status"], "degraded")

    def test_health_without_sources_is_degraded(self) -> None:
        self.assertEqual(self.store.health(now=self.now)["status"], "degraded")

    def test_heartbeat_cannot_regress(self) -> None:
        _ = self.store.heartbeat(owner="worker", observed_at=self.now.isoformat())
        with self.assertRaisesRegex(ValueError, "cannot regress"):
            _ = self.store.heartbeat(
                owner="worker",
                observed_at=(self.now - timedelta(minutes=1)).isoformat(),
            )

    def test_timestamp_requires_timezone_aware_iso(self) -> None:
        self.assertEqual(
            utc_datetime("2026-01-02T12:00:00Z", description="event"),
            self.now,
        )
        with self.assertRaisesRegex(ValueError, "include a timezone"):
            _ = utc_datetime("2026-01-02T12:00:00", description="event")

    def test_legacy_numeric_epoch_is_not_a_supported_format(self) -> None:
        with self.assertRaisesRegex(ValueError, "ISO-8601"):
            _ = utc_datetime("1767355200", description="event")

    def test_output_limits_are_bounded(self) -> None:
        self.assertEqual(bounded_limit(1), 1)
        self.assertEqual(bounded_limit(MAXIMUM_LIMIT), MAXIMUM_LIMIT)
        with self.assertRaisesRegex(ValueError, "between"):
            _ = bounded_limit(MAXIMUM_LIMIT + 1)

    def test_boolean_is_not_a_listing_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "between"):
            _ = bounded_limit(True)


if __name__ == "__main__":
    unittest.main()
