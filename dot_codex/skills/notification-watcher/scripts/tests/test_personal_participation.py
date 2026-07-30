"""Regression coverage for bounded third-party participation notifications."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from codex_notification_watcher.source import claim, ingest, register_source, replay, resolve
from codex_notification_watcher.store import Store


class PersonalParticipationTest(unittest.TestCase):
    source = "github_personal_participating_threads"
    owner = "notification-owner"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / "notifications.sqlite3", initialize=True)
        self.addCleanup(self.store.connection.close)
        self.now = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
        self.floor = self.now - timedelta(minutes=5)
        _ = register_source(
            self.store,
            {"source_id": self.source, "owner": self.owner,
             "replay_from": self.floor.isoformat(), "verified": True},
        )

    def event(self) -> dict[str, object]:
        return {
            "verified": True,
            "event_id": "external-issue-comment:5122954193",
            "logical_cycle_id": "participating-issue-comment:5122954193",
            "category": "owned_feedback",
            "subject_key": "example/external#1389",
            "actor": "external-maintainer",
            "actor_type": "User",
            "head": "c" * 40,
            "occurred_at": self.now.isoformat(),
            "author_association": "MEMBER",
            "notification_reason": "mention",
            "body": "@reviewer do you have concerns about this implementation?",
        }

    def observation(
        self, *, complete: bool = True, include_comment: bool = True
    ) -> dict[str, object]:
        scopes = ["personal-participating-notifications", "repository:example/external"]
        return {
            "source_id": self.source,
            "owner": self.owner,
            "verified": True,
            "observed_at": (self.now + timedelta(minutes=1)).isoformat(),
            "high_water_mark": (self.now + timedelta(minutes=1)).isoformat(),
            "overlap_floor": self.floor.isoformat(),
            "overlap_seconds": 300,
            "pagination_complete": complete,
            "required_scopes": scopes,
            "observed_scopes": scopes if complete else scopes[:1],
            "events": [self.event()] if include_comment else [],
        }

    def test_external_participating_maintainer_mention_is_discovered(self) -> None:
        result = ingest(self.store, self.observation())

        self.assertEqual(result["discovered"], 1)
        pending = self.store.pending(category="owned_feedback")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["source_id"], self.source)
        self.assertEqual(pending[0]["event_id"], "external-issue-comment:5122954193")

    def test_previously_unseen_author_does_not_hide_participating_mention(self) -> None:
        unseen = self.event()
        unseen.update(
            {
                "event_id": "external-issue-comment:previously-unseen-author",
                "logical_cycle_id": "participating-issue-comment:previously-unseen-author",
                "subject_key": "example/external#1125973",
                "actor": "previously-unseen-contributor",
            }
        )
        observation = self.observation()
        observation["events"] = [unseen, self.event()]

        result = ingest(self.store, observation)

        self.assertEqual(result["discovered"], 2)
        pending = self.store.pending(category="owned_feedback")
        self.assertEqual(
            {row["event_id"] for row in pending},
            {
                "external-issue-comment:previously-unseen-author",
                "external-issue-comment:5122954193",
            },
        )

    def test_native_review_accepts_a_previously_unseen_human_author(self) -> None:
        native = "github_org_review_requested_search"
        _ = register_source(
            self.store,
            {
                "source_id": native,
                "owner": self.owner,
                "replay_from": self.floor.isoformat(),
                "verified": True,
            },
        )
        event: dict[str, object] = {
            "verified": True,
            "event_id": "provider-native-review:previously-unseen-author",
            "logical_cycle_id": "provider-native-review:previously-unseen-author",
            "category": "review_request",
            "subject_key": "example/external#1125973",
            "actor": "previously-unseen-contributor",
            "actor_type": "User",
            "reviewer": "requested-reviewer",
            "head": "d" * 40,
            "occurred_at": self.now.isoformat(),
        }
        observation = self.observation()
        observation["source_id"] = native
        observation["events"] = [event]

        result = ingest(self.store, observation)

        self.assertTrue(result["checkpoint_advanced"])
        self.assertEqual(result["discovered"], 1)
        pending = self.store.pending(category="review_request")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["source_id"], native)
        self.assertEqual(
            pending[0]["event_id"],
            "provider-native-review:previously-unseen-author",
        )

    def test_same_head_rerequest_requires_a_distinct_provider_event(self) -> None:
        native = "github_org_review_requested_search"
        _ = register_source(
            self.store,
            {
                "source_id": native,
                "owner": self.owner,
                "replay_from": self.floor.isoformat(),
                "verified": True,
            },
        )
        original_cycle = "provider-native-review:initial"
        original: dict[str, object] = {
            "verified": True,
            "event_id": "provider-native-review:initial",
            "logical_cycle_id": original_cycle,
            "category": "review_request",
            "subject_key": "example/external#42",
            "actor": "request-author",
            "actor_type": "User",
            "reviewer": "requested-reviewer",
            "head": "d" * 40,
            "occurred_at": self.now.isoformat(),
        }
        observation = self.observation()
        observation["source_id"] = native
        observation["events"] = [original]
        _ = ingest(self.store, observation)
        _ = claim(self.store, logical_cycle_id=original_cycle, owner="original-reviewer")
        _ = resolve(
            self.store,
            logical_cycle_id=original_cycle,
            owner="original-reviewer",
            review_id="original-signed-review",
        )

        rerequest = dict(original)
        rerequest["event_id"] = "provider-native-review:new-request-event"
        rerequest["logical_cycle_id"] = "provider-native-review:new-request-event"
        rerequest["occurred_at"] = (
            self.now + timedelta(seconds=30)
        ).isoformat()
        observation["events"] = [rerequest]

        result = ingest(self.store, observation)

        self.assertEqual(result["discovered"], 1)
        pending = self.store.pending(category="review_request")
        self.assertEqual(len(pending), 1)
        self.assertEqual(
            pending[0]["event_id"], "provider-native-review:new-request-event"
        )
        original_row = self.store.connection.execute(
            "SELECT status, terminal_event_id FROM claims "
            "WHERE logical_cycle_id = ?",
            (original_cycle,),
        ).fetchone()
        assert original_row is not None
        self.assertEqual(tuple(original_row), ("resolved", "original-signed-review"))

    def test_complete_assignment_preserves_events_beyond_first_provider_page(
        self,
    ) -> None:
        assigned = "github_individually_assigned_pull_requests"
        scopes = [
            "individual-assignment-parent-pagination",
            "individual-assignment-terminal-cursor",
        ]
        _ = register_source(
            self.store,
            {
                "source_id": assigned,
                "owner": self.owner,
                "replay_from": self.floor.isoformat(),
                "verified": True,
            },
        )
        events: list[dict[str, object]] = [
            {
                "verified": True,
                "event_id": f"provider-native-assignment:{index}",
                "logical_cycle_id": f"provider-native-assignment:{index}",
                "category": "review_request",
                "subject_key": f"example/external#{index}",
                "actor": f"previously-unseen-author-{index}",
                "actor_type": "User",
                "reviewer": "requested-reviewer",
                "head": f"{index:040x}",
                "occurred_at": self.now.isoformat(),
            }
            for index in range(137)
        ]
        observation = self.observation()
        observation.update(
            {
                "source_id": assigned,
                "required_scopes": scopes,
                "observed_scopes": scopes,
                "events": events,
            }
        )

        result = ingest(self.store, observation)

        self.assertTrue(result["checkpoint_advanced"])
        self.assertEqual(result["discovered"], len(events))
        records = self.store.connection.execute(
            "SELECT event_id FROM notifications "
            "WHERE source_id = ? ORDER BY rowid",
            (assigned,),
        )
        self.assertEqual(
            [row["event_id"] for row in records],
            [event["event_id"] for event in events],
        )
        self.assertEqual(
            replay(self.store, assigned)["high_water_mark"],
            (self.now + timedelta(minutes=1)).isoformat(timespec="microseconds"),
        )

    def test_incomplete_assignment_cannot_freeze_four_independent_domains(
        self,
    ) -> None:
        assigned = "github_individually_assigned_pull_requests"
        independent_sources = (
            "github_org_review_requested_search",
            "github_owned_pr_feedback_all_repos",
            "github_tempest_current_head_findings_72h",
            "github_personal_participating_threads",
        )
        for source_id in (assigned, *independent_sources):
            _ = register_source(
                self.store,
                {
                    "source_id": source_id,
                    "owner": self.owner,
                    "replay_from": self.floor.isoformat(),
                    "verified": True,
                },
            )
        incomplete = self.observation(complete=False, include_comment=False)
        incomplete["source_id"] = assigned

        assigned_result = ingest(self.store, incomplete)

        self.assertFalse(assigned_result["checkpoint_advanced"])
        self.assertIsNone(replay(self.store, assigned)["high_water_mark"])
        for source_id in independent_sources:
            with self.subTest(source=source_id):
                observation = self.observation(include_comment=False)
                observation["source_id"] = source_id

                result = ingest(self.store, observation)

                self.assertTrue(result["checkpoint_advanced"])
                self.assertEqual(
                    replay(self.store, source_id)["high_water_mark"],
                    (self.now + timedelta(minutes=1)).isoformat(
                        timespec="microseconds"
                    ),
                )

        self.assertIsNone(replay(self.store, assigned)["high_water_mark"])

    def test_incomplete_source_does_not_freeze_independent_complete_source(self) -> None:
        independent = "independent-provider-domain"
        _ = register_source(
            self.store,
            {
                "source_id": independent,
                "owner": self.owner,
                "replay_from": self.floor.isoformat(),
                "verified": True,
            },
        )
        complete = self.observation()
        complete["source_id"] = independent
        complete["events"] = []

        incomplete_result = ingest(self.store, self.observation(complete=False))
        complete_result = ingest(self.store, complete)

        self.assertFalse(incomplete_result["checkpoint_advanced"])
        self.assertTrue(complete_result["checkpoint_advanced"])
        self.assertIsNone(replay(self.store, self.source)["high_water_mark"])
        self.assertEqual(
            replay(self.store, independent)["high_water_mark"],
            (self.now + timedelta(minutes=1)).isoformat(timespec="microseconds"),
        )

    def test_partial_participating_page_cannot_advance_checkpoint(self) -> None:
        result = ingest(self.store, self.observation(complete=False))

        self.assertFalse(result["checkpoint_advanced"])
        self.assertIsNone(replay(self.store, self.source)["high_water_mark"])

    def test_complete_page_cannot_omit_an_authorized_repository(self) -> None:
        observation = self.observation()
        observation["observed_scopes"] = ["personal-participating-notifications"]

        with self.assertRaisesRegex(ValueError, "omits a required scope"):
            _ = ingest(self.store, observation)

    def test_answered_comment_replay_does_not_redispatch_original_owner(self) -> None:
        observation = self.observation()
        _ = ingest(self.store, observation)
        cycle = "participating-issue-comment:5122954193"
        original_owner = "original-upstream-reviewer"
        _ = claim(self.store, logical_cycle_id=cycle, owner=original_owner)
        _ = resolve(
            self.store, logical_cycle_id=cycle, owner=original_owner,
            review_id="original-review-4812819907",
        )

        replayed = ingest(self.store, observation)

        self.assertEqual(replayed["discovered"], 0)
        self.assertEqual(self.store.pending(category="owned_feedback"), [])
        row = self.store.connection.execute(
            "SELECT owner, status, terminal_event_id FROM claims "
            "WHERE logical_cycle_id = ?", (cycle,),
        ).fetchone()
        assert row is not None
        self.assertEqual(
            tuple(row), (original_owner, "resolved", "original-review-4812819907")
        )
