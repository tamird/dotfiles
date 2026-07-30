"""Regression coverage for durable personal-review obligations."""

from __future__ import annotations

import asyncio
from typing import override
import unittest

from codex_notification_watcher.github_provider import (
    GithubReader,
    JsonObject,
    ReaderConfig,
    comment_event_identity,
    complete_previous_pages,
    has_actionable_feedback,
    immutable_event_payload,
    is_actionable_feedback_actor,
    review_request_is_outstanding,
)


class PersonalReviewChronologyTest(unittest.TestCase):
    principal = "repository-maintainer"

    def test_later_review_satisfies_request_after_head_moves(self) -> None:
        reviews: list[dict[str, object]] = [
            {
                "author": {"login": self.principal},
                "submittedAt": "2026-01-01T12:05:00Z",
                "commit": {"oid": "previous-head"},
            }
        ]

        self.assertFalse(
            review_request_is_outstanding(
                "2026-01-01T12:00:00Z", reviews, principal=self.principal
            )
        )

    def test_later_rerequest_reopens_obligation_on_same_head(self) -> None:
        reviews: list[dict[str, object]] = [
            {
                "author": {"login": self.principal},
                "submittedAt": "2026-01-01T12:05:00Z",
                "commit": {"oid": "unchanged-head"},
            }
        ]

        self.assertTrue(
            review_request_is_outstanding(
                "2026-01-01T12:10:00Z", reviews, principal=self.principal
            )
        )

    def test_someone_elses_review_does_not_satisfy_request(self) -> None:
        reviews: list[dict[str, object]] = [
            {
                "author": {"login": "another-maintainer"},
                "submittedAt": "2026-01-01T12:05:00Z",
            }
        ]

        self.assertTrue(
            review_request_is_outstanding(
                "2026-01-01T12:00:00Z", reviews, principal=self.principal
            )
        )

    def test_empty_approval_is_status_not_actionable_feedback(self) -> None:
        self.assertFalse(has_actionable_feedback({"state": "APPROVED", "body": ""}))

    def test_approval_prose_does_not_create_an_owner_task(self) -> None:
        self.assertFalse(has_actionable_feedback({"state": "APPROVED", "body": "nice!"}))

    def test_independent_human_comment_alongside_approval_remains_actionable(self) -> None:
        self.assertTrue(has_actionable_feedback({"body": "Please correct this boundary."}))

    def test_changed_comment_body_creates_distinct_authenticated_event(self) -> None:
        self.assertEqual(
            comment_event_identity(
                "comment-id",
                created_at="2026-01-01T12:00:00Z",
                updated_at="2026-01-01T12:05:00Z",
                body="corrected feedback",
                previous_body="original feedback",
            ),
            ("comment-id@2026-01-01T12:05:00Z", "2026-01-01T12:05:00Z"),
        )

    def test_unchanged_comment_body_does_not_create_event_from_metadata(self) -> None:
        self.assertEqual(
            comment_event_identity(
                "comment-id",
                created_at="2026-01-01T12:00:00Z",
                updated_at="2026-01-01T12:05:00Z",
                body="unchanged feedback",
                previous_body="unchanged feedback",
            ),
            ("comment-id", "2026-01-01T12:00:00Z"),
        )

    def test_unchanged_edited_comment_reuses_existing_versioned_identity(self) -> None:
        self.assertEqual(
            comment_event_identity(
                "comment-id",
                created_at="2026-01-01T12:00:00Z",
                updated_at="2026-01-01T12:05:00Z",
                body="edited feedback",
                previous_body="edited feedback",
                previous_event_id="comment-id@2026-01-01T12:05:00Z",
            ),
            ("comment-id@2026-01-01T12:05:00Z", "2026-01-01T12:05:00Z"),
        )

    def test_immutable_replay_retains_original_authenticated_content(self) -> None:
        self.assertEqual(
            immutable_event_payload(
                '{"payload":{"event_id":"comment-id","verified":true,'
                '"body":"original feedback","head":"original-head"}}',
                event_id="comment-id",
            ),
            {
                "event_id": "comment-id",
                "verified": True,
                "body": "original feedback",
                "head": "original-head",
            },
        )

    def test_exact_head_codex_finding_on_open_thread_is_actionable(self) -> None:
        self.assertTrue(
            is_actionable_feedback_actor(
                {
                    "author": {
                        "__typename": "Bot",
                        "login": "chatgpt-codex-connector",
                    },
                    "commit": {"oid": "current-head"},
                },
                current_head="current-head",
                unresolved_current_thread=True,
            )
        )

    def test_resolved_or_outdated_codex_finding_is_not_actionable(self) -> None:
        self.assertFalse(
            is_actionable_feedback_actor(
                {
                    "author": {
                        "__typename": "Bot",
                        "login": "chatgpt-codex-connector",
                    },
                    "commit": {"oid": "previous-head"},
                },
                current_head="current-head",
                unresolved_current_thread=True,
            )
        )
        self.assertFalse(
            is_actionable_feedback_actor(
                {
                    "author": {
                        "__typename": "Bot",
                        "login": "chatgpt-codex-connector",
                    },
                    "commit": {"oid": "current-head"},
                },
                current_head="current-head",
                unresolved_current_thread=False,
            )
        )

    def test_untrusted_bot_cannot_create_feedback(self) -> None:
        self.assertFalse(
            is_actionable_feedback_actor(
                {
                    "author": {"__typename": "Bot", "login": "untrusted-bot"},
                    "commit": {"oid": "current-head"},
                },
                current_head="current-head",
                unresolved_current_thread=True,
            )
        )


class OwnedPaginationReader(GithubReader):
    """Expose the real owned-node pagination against deterministic provider pages."""

    def __init__(self, node: JsonObject, pages: dict[str, JsonObject]) -> None:
        self.config = ReaderConfig(
            owner="source-owner",
            principal="repository-maintainer",
            interval_seconds=30,
            frozen_subjects=frozenset(),
        )
        self.owned_lock = asyncio.Lock()
        self.owned_at = None
        self.owned_nodes = []
        self.node = node
        self.pages = pages
        self.calls: list[str] = []

    @override
    async def _search(self, query: str, fields: str) -> list[JsonObject]:
        del query, fields
        return [self.node]

    @override
    async def _github(self, *arguments: str) -> object:
        document = next(value for value in arguments if value.startswith("query="))
        if "node(id:$id)" in document:
            key = "inline"
            self.calls.append(key)
            return {"data": {"node": {"comments": self.pages[key]}}}
        key = next(
            name
            for name in ("reviewThreads", "reviews", "comments")
            if f"{name}(last:50" in document
        )
        self.calls.append(key)
        return {
            "data": {"repository": {"pullRequest": {key: self.pages[key]}}}
        }


class OwnedPullRequestPaginationTest(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def connection(
        nodes: list[JsonObject], *, previous: bool = False
    ) -> JsonObject:
        page: JsonObject = {"hasPreviousPage": previous}
        if previous:
            page["startCursor"] = "older-page"
        return {"nodes": nodes, "pageInfo": page}

    @classmethod
    def thread(cls, identifier: int, *, previous_comments: bool = False) -> JsonObject:
        size = 15 if previous_comments else 1
        return {
            "id": f"thread-{identifier}",
            "isResolved": False,
            "isOutdated": False,
            "comments": cls.connection(
                [{"id": f"inline-{identifier}-{index}"} for index in range(size)],
                previous=previous_comments,
            ),
        }

    async def test_every_owned_connection_and_inline_reply_is_fully_paged(self) -> None:
        threads = [self.thread(index, previous_comments=index == 1) for index in range(1, 16)]
        node: JsonObject = {
            "number": 7,
            "repository": {"nameWithOwner": "example/project"},
            "comments": self.connection(
                [{"id": f"issue-{index}"} for index in range(20)], previous=True
            ),
            "reviews": self.connection(
                [{"id": f"review-{index}"} for index in range(20)], previous=True
            ),
            "reviewThreads": self.connection(threads, previous=True),
        }
        pages: dict[str, JsonObject] = {
            "comments": self.connection([{"id": "issue-oldest"}]),
            "reviews": self.connection([{"id": "review-oldest"}]),
            "reviewThreads": self.connection([self.thread(0)]),
            "inline": self.connection([{"id": "inline-oldest"}]),
        }
        reader = OwnedPaginationReader(node, pages)

        owned = await reader._owned()

        self.assertEqual(len(owned), 1)
        issue = owned[0]["comments"]
        reviews = owned[0]["reviews"]
        result_threads = owned[0]["reviewThreads"]
        self.assertIsInstance(issue, dict)
        self.assertIsInstance(reviews, dict)
        self.assertIsInstance(result_threads, dict)
        if not isinstance(issue, dict) or not isinstance(reviews, dict) or not isinstance(result_threads, dict):
            self.fail("owned connections must remain objects")
        issue_nodes = issue.get("nodes")
        review_nodes = reviews.get("nodes")
        thread_nodes = result_threads.get("nodes")
        self.assertIsInstance(issue_nodes, list)
        self.assertIsInstance(review_nodes, list)
        self.assertIsInstance(thread_nodes, list)
        if not isinstance(issue_nodes, list) or not isinstance(review_nodes, list) or not isinstance(thread_nodes, list):
            self.fail("owned connection nodes must remain lists")
        self.assertEqual(len(issue_nodes), 21)
        self.assertEqual(len(review_nodes), 21)
        self.assertEqual(len(thread_nodes), 16)
        oldest = thread_nodes[0]
        target = thread_nodes[1]
        self.assertIsInstance(oldest, dict)
        self.assertIsInstance(target, dict)
        if not isinstance(oldest, dict) or not isinstance(target, dict):
            self.fail("owned thread must remain an object")
        self.assertEqual(oldest.get("id"), "thread-0")
        target_comments = target.get("comments")
        self.assertIsInstance(target_comments, dict)
        if not isinstance(target_comments, dict):
            self.fail("nested comments must remain an object")
        inline_nodes = target_comments.get("nodes")
        self.assertIsInstance(inline_nodes, list)
        if not isinstance(inline_nodes, list):
            self.fail("nested comments must remain a list")
        self.assertEqual(len(inline_nodes), 16)
        first_inline = inline_nodes[0]
        self.assertIsInstance(first_inline, dict)
        if not isinstance(first_inline, dict):
            self.fail("nested comment must remain an object")
        self.assertEqual(first_inline.get("id"), "inline-oldest")
        self.assertCountEqual(reader.calls, ["comments", "reviews", "reviewThreads", "inline"])

    async def test_incomplete_earlier_page_fails_without_marking_complete(self) -> None:
        connection = self.connection([{"id": "recent"}], previous=True)

        async def incomplete(cursor: str) -> JsonObject:
            self.assertEqual(cursor, "older-page")
            return {"nodes": [{"id": "earlier"}], "pageInfo": {}}

        with self.assertRaisesRegex(ValueError, "pagination is incomplete"):
            _ = await complete_previous_pages(connection, incomplete, context="owned reviews")


if __name__ == "__main__":
    unittest.main()
