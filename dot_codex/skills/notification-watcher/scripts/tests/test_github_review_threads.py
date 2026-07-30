"""Behavioral regressions for complete owned upstream review-thread intake."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from codex_notification_watcher.review_threads import owned_review_thread_events
from codex_notification_watcher.source import ingest, register_source
from codex_notification_watcher.store import Store


class OwnedReviewThreadsTest(unittest.TestCase):
    principal = "repository-owner"
    original_head = "7" * 40
    current_head = "c" * 40

    def connection(
        self, nodes: list[dict[str, object]], *, complete: bool = True
    ) -> dict[str, object]:
        return {"nodes": nodes, "pageInfo": {"hasNextPage": not complete}}

    def comment(
        self,
        identifier: int,
        *,
        actor: str = "upstream-maintainer",
        parent: int | None = None,
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "databaseId": identifier,
            "author": {"__typename": "User", "login": actor},
            "originalCommit": {"oid": self.original_head},
            "createdAt": "2026-01-01T10:00:00Z",
            "body": "Does the release entrypoint need this too?",
            "url": f"https://example.invalid/pull/4#discussion_r{identifier}",
        }
        if parent is not None:
            value["replyTo"] = {"databaseId": parent}
        return value

    def thread(
        self,
        identifier: int,
        comments: list[dict[str, object]],
        *,
        complete: bool = True,
    ) -> dict[str, object]:
        return {
            "id": f"review-thread-{identifier}",
            "comments": self.connection(comments, complete=complete),
        }

    def extract(
        self,
        threads: object,
        *,
        subject: str = "upstream/python-client#2657",
    ) -> list[dict[str, object]]:
        return owned_review_thread_events(
            subject_key=subject,
            current_head=self.current_head,
            principal=self.principal,
            threads=threads,
        )

    def test_first_upstream_root_without_mention_is_preserved(self) -> None:
        event = self.extract(
            self.connection([self.thread(1, [self.comment(3678012560)])])
        )

        self.assertEqual(len(event), 1)
        self.assertEqual(event[0]["event_id"], "3678012560")
        self.assertEqual(event[0]["head"], self.original_head)
        self.assertEqual(event[0]["current_head"], self.current_head)
        self.assertEqual(event[0]["actor"], "upstream-maintainer")
        self.assertNotIn("@", str(event[0]["body"]))

    def test_original_root_and_principal_reply_share_one_logical_cycle(self) -> None:
        root = self.comment(3678012560)
        reply = self.comment(
            3678878771, actor=self.principal, parent=3678012560
        )

        events = self.extract(self.connection([self.thread(1, [root, reply])]))

        self.assertEqual(
            [event["event_id"] for event in events],
            ["3678012560", "3678878771"],
        )
        self.assertEqual(events[0]["logical_cycle_id"], events[1]["logical_cycle_id"])
        self.assertEqual(events[1]["in_reply_to"], "3678012560")

    def test_all_nested_threads_are_preserved_beyond_twenty_five(self) -> None:
        threads = [
            self.thread(index, [self.comment(10_000 + index)])
            for index in range(30)
        ]

        events = self.extract(self.connection(threads))

        self.assertEqual(len(events), 30)
        self.assertEqual(events[-1]["event_id"], "10029")

    def test_incomplete_root_or_nested_cursor_is_rejected(self) -> None:
        root = self.comment(3678012560)
        cases = {
            "review threads": self.connection(
                [self.thread(1, [root])], complete=False
            ),
            "nested comments": self.connection(
                [self.thread(1, [root], complete=False)]
            ),
        }
        for name, threads in cases.items():
            with self.subTest(cursor=name):
                with self.assertRaisesRegex(ValueError, "pagination is incomplete"):
                    _ = self.extract(threads)

    def test_owned_roots_are_retained_across_unrelated_repositories(self) -> None:
        threads = self.connection([self.thread(1, [self.comment(3678012560)])])
        subjects = ("upstream/python-client#2657", "another/repository#30782")

        events = [self.extract(threads, subject=subject)[0] for subject in subjects]

        self.assertEqual(
            [event["subject_key"] for event in events], list(subjects)
        )
        self.assertNotEqual(events[0]["logical_cycle_id"], events[1]["logical_cycle_id"])

    def test_outage_replay_retains_root_older_than_the_replay_floor(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = Store(Path(directory.name) / "notifications.sqlite3", initialize=True)
        self.addCleanup(store.connection.close)
        now = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
        floor = now - timedelta(minutes=5)
        source = "github_owned_pr_feedback_all_repos"
        _ = register_source(
            store,
            {
                "source_id": source,
                "owner": self.principal,
                "replay_from": floor.isoformat(),
                "verified": True,
            },
        )
        events = self.extract(
            self.connection([self.thread(1, [self.comment(3678012560)])])
        )
        observation: dict[str, object] = {
            "source_id": source,
            "owner": self.principal,
            "verified": True,
            "observed_at": now.isoformat(),
            "high_water_mark": now.isoformat(),
            "overlap_floor": floor.isoformat(),
            "overlap_seconds": 300,
            "pagination_complete": True,
            "required_scopes": ["owned-review-threads", "nested-review-comments"],
            "observed_scopes": ["owned-review-threads", "nested-review-comments"],
            "events": events,
        }

        first = ingest(store, observation)
        replay = ingest(store, observation)

        self.assertEqual(first["discovered"], 1)
        self.assertEqual(replay["discovered"], 0)
        self.assertEqual(replay["deduplicated"], 1)
        pending = store.pending(category="owned_feedback")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["event_id"], "3678012560")


if __name__ == "__main__":
    unittest.main()
