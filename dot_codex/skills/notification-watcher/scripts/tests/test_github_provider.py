"""Regression coverage for durable personal-review obligations."""

from __future__ import annotations

import unittest

from codex_notification_watcher.github_provider import (
    comment_event_identity,
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

    def test_approval_with_human_comment_remains_actionable(self) -> None:
        self.assertTrue(
            has_actionable_feedback({"state": "APPROVED", "body": "One follow-up."})
        )

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


if __name__ == "__main__":
    unittest.main()
