"""Regression coverage for genuine first-party Slack notification shapes."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from codex_notification_watcher.cli import main
from codex_notification_watcher.slack_threads import (
    classify_slack_pages,
    discover_owned_thread_scopes,
    rendered_slack_messages,
    slack_control_events,
    slack_thread_events,
)
from codex_notification_watcher.model import NotificationEvent


class SlackThreadIntakeTest(unittest.TestCase):
    owner = "principal"
    subject = "example/repository#42"
    head = "a" * 40

    def page(
        self,
        messages: list[dict[str, object]],
        *,
        cursor: str = "",
    ) -> dict[str, object]:
        return {
            "messages": messages,
            "response_metadata": {"next_cursor": cursor},
        }

    def events(
        self, messages: object, *, direct: bool = False
    ) -> list[dict[str, object]]:
        return slack_thread_events(
            channel="monitored-channel",
            root="1785231510.122969",
            messages=messages,
            principal=self.owner,
            subject_heads={self.subject: self.head},
            direct=direct,
        )

    def test_discovers_root_from_principal_authored_outbound_message(self) -> None:
        messages = self.page(
            [
                {
                    "channel": "previously-unlisted-channel",
                    "ts": "1785231510.122969",
                    "user": self.owner,
                }
            ]
        )

        result = discover_owned_thread_scopes(messages, principal=self.owner)

        self.assertEqual(
            result, ("slack:previously-unlisted-channel:1785231510.122969",)
        )

    def test_discovers_old_control_roots_from_current_principal_replies(self) -> None:
        channel = "C0BJWK4DPDY"
        principal = "U01OWNER"
        messages = self.page(
            [
                {
                    "channel": channel,
                    "user": principal,
                    "ts": "1785425356.719229",
                    "thread_ts": "1785422677.684279",
                },
                {
                    "channel": channel,
                    "user": principal,
                    "ts": "1785432259.446409",
                    "thread_ts": "1785421919.024249",
                },
                {
                    "channel": channel,
                    "user": "U02OTHER",
                    "ts": "1785432260.446409",
                    "thread_ts": "1785432000.000000",
                },
            ]
        )

        self.assertEqual(
            discover_owned_thread_scopes(messages, principal=principal),
            (
                "slack:C0BJWK4DPDY:1785421919.024249",
                "slack:C0BJWK4DPDY:1785422677.684279",
            ),
        )

    def test_watched_top_level_review_request_requires_no_mention(self) -> None:
        message = {
            "user": "actual-human",
            "ts": "1785370665.677089",
            "text": "r? https://github.com/example/repository/pull/42",
        }

        events = self.events(self.page([message]))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["category"], "review_request")
        self.assertEqual(events[0]["head"], self.head)

    def test_explicit_human_stamp_request_is_a_review_request(self) -> None:
        message = {
            "user": "actual-human",
            "ts": "1785377793.400199",
            "text": (
                "Hey team can i get a stamp on "
                "https://github.com/example/repository/pull/42?"
            ),
        }

        events = self.events(self.page([message]))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["category"], "review_request")
        self.assertEqual(events[0]["actor"], "actual-human")

    def test_direct_message_is_consumed_without_public_search(self) -> None:
        message = {
            "user": "direct-human",
            "ts": "1785357680.745119",
            "text": (
                "Could you review https://github.com/example/repository/pull/42?"
            ),
        }

        events = self.events(self.page([message]), direct=True)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "direct-human")
        self.assertEqual(events[0]["category"], "review_request")

    def test_informational_direct_pr_link_is_not_a_review_request(self) -> None:
        message = {
            "user": "direct-human",
            "ts": "1785357680.745119",
            "text": (
                "This rollout finished: "
                "https://github.com/example/repository/pull/42"
            ),
        }

        events = self.events(self.page([message]), direct=True)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["category"], "owned_feedback")
        self.assertEqual(events[0]["body"], message["text"])

    def test_verified_bot_message_cannot_become_human_review_request(self) -> None:
        message = {
            "user": "verified-delivery-bot",
            "actor_is_bot": True,
            "ts": "1785357680.745119",
            "text": "r? https://github.com/example/repository/pull/42",
        }

        self.assertEqual(self.events(self.page([message]), direct=True), [])

    def test_verified_bot_carrier_retains_authenticated_embedded_human(
        self,
    ) -> None:
        message = {
            "user": "verified-delivery-bot",
            "actor_is_bot": True,
            "human_actor": "actual-human",
            "human_actor_is_bot": False,
            "ts": "1785357680.745119",
            "text": "r? https://github.com/example/repository/pull/42",
        }

        events = self.events(self.page([message]), direct=True)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "actual-human")
        self.assertEqual(events[0]["category"], "review_request")

    def test_automation_review_mention_is_not_a_personal_review_request(self) -> None:
        message = {
            "user": "actual-human",
            "ts": "1785370665.677089",
            "text": "@codex review https://github.com/example/repository/pull/42",
        }

        events = self.events(self.page([message]))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["category"], "owned_feedback")
        self.assertNotIn("reviewer", events[0])

    def test_explicit_principal_with_automation_remains_personal_request(self) -> None:
        message = {
            "user": "actual-human",
            "ts": "1785370665.677089",
            "text": (
                "<@principal> review https://github.com/example/repository/pull/42 "
                "after @codex"
            ),
        }

        events = self.events(self.page([message]))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["category"], "review_request")
        self.assertEqual(events[0]["reviewer"], self.owner)

    def test_flow_wrapper_uses_the_authenticated_embedded_human(self) -> None:
        message = {
            "user": "delivery-bot",
            "human_actor": "actual-human",
            "ts": "1785370665.677089",
            "text": "r? https://github.com/example/repository/pull/42",
        }

        events = self.events(self.page([message]))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "actual-human")
        self.assertEqual(events[0]["actor_type"], "User")
        self.assertEqual(events[0]["category"], "review_request")

    def test_nested_owner_reply_inherits_its_principal_owned_root(self) -> None:
        root = {
            "user": "root-author",
            "ts": "1785231510.122969",
            "text": "https://github.com/example/repository/pull/42",
        }
        reply = {
            "user": "team-owner",
            "ts": "1785370383.378519",
            "thread_ts": "1785231510.122969",
            "text": "Can you share the exact failing-test duration?",
        }

        events = self.events(self.page([root, reply]))

        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["actor"], "team-owner")
        self.assertEqual(events[1]["category"], "owned_feedback")
        self.assertTrue(str(events[1]["event_id"]).endswith("1785370383.378519"))

    def test_human_reply_inherits_subject_from_principal_authored_root(self) -> None:
        root = {
            "user": self.owner,
            "ts": "1785231510.122969",
            "text": "https://github.com/example/repository/pull/42",
        }
        reply = {
            "user": "actual-team-owner",
            "ts": "1785370383.378519",
            "thread_ts": "1785231510.122969",
            "text": "Can you share the exact failing-test duration?",
        }

        events = self.events(self.page([root, reply]))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "actual-team-owner")
        self.assertEqual(events[0]["subject_key"], self.subject)
        self.assertEqual(events[0]["category"], "owned_feedback")

    def test_another_persons_check_mark_does_not_hide_review_request(self) -> None:
        message: dict[str, object] = {
            "user": "actual-human",
            "ts": "1785370665.677089",
            "text": "r? https://github.com/example/repository/pull/42",
            "reactions": [
                {"name": "white_check_mark", "users": ["different-reviewer"]}
            ],
        }

        events = self.events(self.page([message]))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["category"], "review_request")

    def test_nonterminal_nested_reply_page_cannot_be_marked_complete(self) -> None:
        message = {
            "user": "actual-human",
            "ts": "1785370665.677089",
            "text": "r? https://github.com/example/repository/pull/42",
        }

        with self.assertRaisesRegex(ValueError, "pagination is incomplete"):
            _ = self.events(self.page([message], cursor="next-reply-page"))

    def test_rendered_channel_retains_each_authenticated_human(self) -> None:
        page = rendered_slack_messages(
            {
                "messages": (
                    "Channel: #project-reviews (C01EXAMPLE)\n\n"
                    "=== Message from Project Owner (U01OWNER) "
                    "at 2026-01-02 12:00:00 UTC ===\n"
                    "Message TS: 1785231510.122969\n"
                    "https://github.com/example/repository/pull/42\n"
                    "Thread: 1 reply\n\n"
                    "=== Message from Team Reviewer (U02REVIEWER) "
                    "at 2026-01-02 12:01:00 UTC ===\n"
                    "Message TS: 1785370383.378519\n"
                    "Can you explain the changed runtime?\n"
                ),
                "pagination_info": "There are no more messages in this thread.\n",
            }
        )

        messages = page["messages"]
        self.assertIsInstance(messages, list)
        assert isinstance(messages, list)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["channel"], "C01EXAMPLE")
        self.assertEqual(messages[0]["user"], "U01OWNER")
        self.assertEqual(messages[1]["user"], "U02REVIEWER")

    def test_rendered_search_preserves_physical_dm_and_parent_root(self) -> None:
        page = rendered_slack_messages(
            {
                "results": (
                    "# Search Results\n\n"
                    "## Messages (1 result)\n"
                    "### Result 1 of 1\n"
                    "Channel: DM (ID: D01EXAMPLE)\n"
                    "Participants: Principal (ID: U01OWNER), "
                    "Reviewer (ID: U02REVIEWER)\n"
                    "From: Principal (ID: U01OWNER)\n"
                    "Message_ts: 1785371906.329819\n"
                    "Permalink: [message](https://example.invalid/archives/"
                    "D01EXAMPLE/p1785371906329819?"
                    "thread_ts=1785357680.745119&cid=D01EXAMPLE)\n"
                    "Text:\n"
                    "https://github.com/example/repository/pull/42\n"
                    "Context before:\n"
                    "- From: Reviewer (ID: U02REVIEWER)\n"
                ),
                "pagination_info": "There are no more messages.\n",
            }
        )

        self.assertEqual(
            discover_owned_thread_scopes(page, principal="U01OWNER"),
            ("slack:D01EXAMPLE:1785357680.745119",),
        )

    def test_rendered_page_refuses_nonterminal_provider_cursor(self) -> None:
        with self.assertRaisesRegex(ValueError, "pagination is incomplete"):
            _ = rendered_slack_messages(
                {
                    "messages": "Channel: #project (C01EXAMPLE)\n",
                    "pagination_info": (
                        "There are more messages available. "
                        "To view the next page, use cursor: `cursor-a`\n"
                    ),
                }
            )

    def test_rendered_search_requires_authenticated_message_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "authenticated message identity"):
            _ = rendered_slack_messages(
                {
                    "results": (
                        "### Result 1 of 1\n"
                        "Channel: DM (ID: D01EXAMPLE)\n"
                        "Message_ts: 1785371906.329819\n"
                        "Text:\nan unauthenticated message\n"
                    )
                }
            )

    def test_unknown_nonempty_rendered_thread_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "no authenticated message records"):
            _ = rendered_slack_messages(
                {
                    "messages": (
                        "THREAD: an unsupported provider representation\n"
                        "An apparent message without a verified actor or timestamp.\n"
                    ),
                    "pagination_info": "There are no more messages in this thread.\n",
                }
            )

    def test_principal_control_root_is_a_typed_subjectless_task(self) -> None:
        events = slack_control_events(
            channel="C01CONTROL",
            root="1785371472.202599",
            principal="U01OWNER",
            messages=self.page(
                [
                    {
                        "channel": "C01CONTROL",
                        "user": "U01OWNER",
                        "ts": "1785371472.202599",
                        "text": "Please investigate the reported regression.",
                    },
                    {
                        "channel": "C01CONTROL",
                        "user": "U02OTHER",
                        "ts": "1785371473.202599",
                        "text": "I can suggest a separate task.",
                    },
                ]
            ),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["category"], "control_task")
        self.assertEqual(events[0]["actor"], "U01OWNER")
        self.assertEqual(
            events[0]["event_id"],
            "slack:C01CONTROL:1785371472.202599:1785371472.202599",
        )
        validated = NotificationEvent.from_object(
            events[0], source_id="slack_user_work_log_tasks"
        )
        self.assertEqual(validated.category, "control_task")

    def test_control_excludes_assistant_footer_under_the_principal_identity(
        self,
    ) -> None:
        root = "1785371472.202599"
        page = self.page(
            [
                {
                    "user": "U01OWNER",
                    "ts": root,
                    "text": "Please investigate the reported regression.",
                },
                {
                    "user": "U01OWNER",
                    "ts": "1785374301.831999",
                    "text": (
                        "I posted the initial analysis.\n"
                        "*Sent using* <@U02ASSISTANT|ChatGPT>"
                    ),
                },
                {
                    "user": "U01OWNER",
                    "ts": "1785374311.831999",
                    "text": "Please reply in the original thread.",
                },
            ]
        )

        events = slack_control_events(
            channel="C01CONTROL", root=root, messages=page, principal="U01OWNER"
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(
            [event["event_id"] for event in events],
            [
                "slack:C01CONTROL:1785371472.202599:1785371472.202599",
                "slack:C01CONTROL:1785371472.202599:1785374311.831999",
            ],
        )

    def test_new_subjectless_principal_root_is_not_hidden_by_old_scopes(self) -> None:
        root = "1785374973.290459"
        events = slack_control_events(
            channel="C01CONTROL",
            root=root,
            principal="U01OWNER",
            messages=self.page(
                [
                    {
                        "channel": "C01CONTROL",
                        "user": "U01OWNER",
                        "ts": root,
                        "text": "Please follow up on the exact underlying cause.",
                    }
                ]
            ),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0]["event_id"],
            "slack:C01CONTROL:1785374973.290459:1785374973.290459",
        )
        self.assertEqual(events[0]["category"], "control_task")

    def test_subjectless_dm_is_context_not_personal_review_request(self) -> None:
        events = self.events(
            self.page(
                [
                    {
                        "user": "direct-human",
                        "ts": "1785357680.745119",
                        "text": "The production rollout finished successfully.",
                    }
                ]
            ),
            direct=True,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["category"], "owned_feedback")
        self.assertNotIn("reviewer", events[0])
        validated = NotificationEvent.from_object(
            events[0], source_id="slack_direct_messages_and_mentions"
        )
        self.assertEqual(validated.category, "owned_feedback")

    def test_rendered_thread_preserves_root_subject_for_nested_human_reply(
        self,
    ) -> None:
        page = rendered_slack_messages(
            {
                "messages": (
                    "Channel: #project-reviews (C01EXAMPLE)\n\n"
                    "=== Message from Root Author (U01AUTHOR) "
                    "at 2026-01-02 12:00:00 UTC ===\n"
                    "Message TS: 1785231510.122969\n"
                    "https://github.com/example/repository/pull/42\n\n"
                    "=== Message from Team Owner (U02REVIEWER) "
                    "at 2026-01-02 12:01:00 UTC ===\n"
                    "Message TS: 1785370383.378519\n"
                    "Can you explain the changed runtime?\n"
                ),
                "pagination_info": "There are no more messages in this thread.\n",
            }
        )

        events = slack_thread_events(
            channel="C01EXAMPLE",
            root="1785231510.122969",
            messages=page,
            principal="U03PRINCIPAL",
            subject_heads={self.subject: self.head},
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["actor"], "U02REVIEWER")
        self.assertEqual(events[1]["subject_key"], self.subject)
        self.assertEqual(events[1]["category"], "owned_feedback")

    def test_detailed_thread_extracts_actual_actor_and_message_timestamps(
        self,
    ) -> None:
        page = rendered_slack_messages(
            {
                "messages": (
                    "=== THREAD PARENT MESSAGE ===\n"
                    "From: Root Author <owner@example.invalid> (U01AUTHOR)\n"
                    "Time: 2026-01-02 12:00:00 UTC\n"
                    "Message TS: 1785231510.122969\n"
                    "https://github.com/example/repository/pull/42\n\n"
                    "--- Reply 1 ---\n"
                    "From: Team Owner <reviewer@example.invalid> (U02REVIEWER)\n"
                    "Time: 2026-01-02 12:01:00 UTC\n"
                    "Message TS: 1785370383.378519\n"
                    "Can you explain the changed runtime?\n"
                ),
                "pagination_info": "There are no more messages in this thread.\n",
            },
            channel="C01EXAMPLE",
            root="1785231510.122969",
        )

        events = slack_thread_events(
            channel="C01EXAMPLE",
            root="1785231510.122969",
            messages=page,
            principal="U03PRINCIPAL",
            subject_heads={self.subject: self.head},
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["actor"], "U02REVIEWER")
        self.assertEqual(
            events[1]["event_id"],
            "slack:C01EXAMPLE:1785231510.122969:1785370383.378519",
        )
        self.assertEqual(events[1]["category"], "owned_feedback")

    def test_detailed_thread_requires_literal_terminal_pagination(self) -> None:
        messages = (
            "=== THREAD PARENT MESSAGE ===\n"
            "From: Root Author <owner@example.invalid> (U01AUTHOR)\n"
            "Time: 2026-01-02 12:00:00 UTC\n"
            "Message TS: 1785231510.122969\n"
            "https://github.com/example/repository/pull/42\n"
        )

        for pagination in (
            "There are more messages in this thread. To view the next "
            "page, use cursor: `opaque-provider-cursor`\n",
            "",
            "No visible cursor.",
            None,
        ):
            with self.subTest(pagination=pagination):
                with self.assertRaisesRegex(ValueError, "pagination is incomplete"):
                    _ = rendered_slack_messages(
                        {"messages": messages, "pagination_info": pagination},
                        channel="C01EXAMPLE",
                        root="1785231510.122969",
                    )

    def test_detailed_flow_review_uses_verified_embedded_human(self) -> None:
        page = rendered_slack_messages(
            {
                "messages": (
                    "=== THREAD PARENT MESSAGE ===\n"
                    "From: Review Delivery <delivery@example.invalid> (U01CARRIER)\n"
                    "Time: 2026-01-02 12:00:00 UTC\n"
                    "Message TS: 1785360537.859209\n"
                    "<slack://user?team=T01EXAMPLE&amp;id=U02HUMAN|Reviewer> "
                    "wants you to review their PR "
                    "<https://github.com/example/repository/pull/42|change>\n"
                ),
                "pagination_info": "There are no more messages in this thread.\n",
            },
            channel="D01EXAMPLE",
            root="1785360537.859209",
        )

        events = slack_thread_events(
            channel="D01EXAMPLE",
            root="1785360537.859209",
            messages=page,
            principal="U03PRINCIPAL",
            subject_heads={self.subject: self.head},
            direct=True,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "U02HUMAN")
        self.assertEqual(events[0]["category"], "review_request")
        validated = NotificationEvent.from_object(
            events[0], source_id="slack_flow_app_review_notifications"
        )
        self.assertEqual(validated.actor, "U02HUMAN")

    def test_detailed_flow_rereview_keeps_the_embedded_requester(self) -> None:
        page = rendered_slack_messages(
            {
                "messages": (
                    "=== THREAD PARENT MESSAGE ===\n"
                    "From: Review Delivery <delivery@example.invalid> (U01CARRIER)\n"
                    "Time: 2026-01-02 12:00:00 UTC\n"
                    "Message TS: 1785374310.521859\n"
                    "<slack://user?team=T01EXAMPLE&amp;id=U02HUMAN|Reviewer> "
                    "Could you take another look? "
                    "<https://github.com/example/repository/pull/42|change>\n"
                ),
                "pagination_info": "There are no more messages in this thread.\n",
            },
            channel="D01EXAMPLE",
            root="1785374310.521859",
        )

        events = slack_thread_events(
            channel="D01EXAMPLE",
            root="1785374310.521859",
            messages=page,
            principal="U03PRINCIPAL",
            subject_heads={self.subject: self.head},
            direct=True,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "U02HUMAN")
        self.assertEqual(events[0]["category"], "review_request")

    def test_detailed_control_uses_actual_principal_not_rendered_name(self) -> None:
        page = rendered_slack_messages(
            {
                "messages": (
                    "=== THREAD PARENT MESSAGE ===\n"
                    "From: Principal <owner@example.invalid> (U01OWNER)\n"
                    "Time: 2026-01-02 12:00:00 UTC\n"
                    "Message TS: 1785371472.202599\n"
                    "Please investigate the reported regression.\n\n"
                    "=== THREAD REPLY 1 ===\n"
                    "From: Other Person <other@example.invalid> (U02OTHER)\n"
                    "Time: 2026-01-02 12:01:00 UTC\n"
                    "Message TS: 1785371473.202599\n"
                    "Here is my suggestion.\n"
                ),
                "pagination_info": "There are no more messages in this thread.\n",
            },
            channel="C01CONTROL",
            root="1785371472.202599",
        )

        events = slack_control_events(
            channel="C01CONTROL",
            root="1785371472.202599",
            messages=page,
            principal="U01OWNER",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "U01OWNER")
        self.assertEqual(events[0]["category"], "control_task")

    def provider_item(
        self,
        *,
        kind: str = "thread",
        source_id: str = "slack_monitored_channels",
        actor: str = "U02REVIEWER",
        text: str = "r? https://github.com/example/repository/pull/42",
    ) -> dict[str, object]:
        return {
            "source_id": source_id,
            "kind": kind,
            "channel": "C01EXAMPLE",
            "root": "1785231510.122969",
            "direct": False,
            "provider_page": {
                "messages": (
                    "=== THREAD PARENT MESSAGE ===\n"
                    f"From: Provider Human <human@example.invalid> ({actor})\n"
                    "Time: 2026-01-02 12:00:00 UTC\n"
                    "Message TS: 1785231510.122969\n"
                    f"{text}\n"
                ),
                "pagination_info": "There are no more messages in this thread.\n",
            },
            "subject_heads": {self.subject: self.head},
        }

    def test_batched_classifier_preserves_independent_thread_and_control(self) -> None:
        result = classify_slack_pages(
            {
                "principal": "U01OWNER",
                "items": [
                    self.provider_item(),
                    self.provider_item(
                        kind="control",
                        source_id="slack_user_work_log_tasks",
                        actor="U01OWNER",
                        text="Please investigate the regression.",
                    ),
                ],
            }
        )

        records = result["results"]
        self.assertIsInstance(records, list)
        assert isinstance(records, list)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["events"][0]["category"], "review_request")
        self.assertEqual(
            records[0]["candidate_event_ids"],
            [records[0]["events"][0]["event_id"]],
        )
        self.assertEqual(records[1]["events"][0]["category"], "control_task")

    def test_control_source_classifies_principal_replies_in_existing_threads(
        self,
    ) -> None:
        channel = "C0BJWK4DPDY"
        principal = "U01OWNER"
        examples = (
            ("1785422677.684279", "1785425356.719229"),
            ("1785421919.024249", "1785432259.446409"),
        )

        for root, reply in examples:
            with self.subTest(root=root, reply=reply):
                result = classify_slack_pages(
                    {
                        "principal": principal,
                        "items": [
                            {
                                "source_id": "slack_user_work_log_tasks",
                                "kind": "thread",
                                "channel": channel,
                                "root": root,
                                "provider_page": {
                                    "messages": (
                                        "=== THREAD PARENT MESSAGE ===\n"
                                        "From: Principal (U01OWNER)\n"
                                        f"Message TS: {root}\n"
                                        "Please investigate the original issue.\n\n"
                                        "=== THREAD REPLY 1 ===\n"
                                        "From: Principal (U01OWNER)\n"
                                        f"Message TS: {reply}\n"
                                        "Please also investigate this follow-up.\n"
                                    ),
                                    "pagination_info": (
                                        "There are no more messages in this thread."
                                    ),
                                },
                            }
                        ],
                    }
                )

                records = result["results"]
                self.assertIsInstance(records, list)
                assert isinstance(records, list)
                events = records[0]["events"]
                self.assertEqual(len(events), 2)
                self.assertEqual(events[1]["category"], "control_task")
                self.assertEqual(
                    events[1]["event_id"], f"slack:{channel}:{root}:{reply}"
                )
                self.assertEqual(events[1]["actor"], principal)

    def test_noncontrol_source_cannot_promote_messages_into_user_tasks(self) -> None:
        item = self.provider_item(
            kind="control",
            source_id="slack_monitored_channels",
            actor="U01OWNER",
        )

        with self.assertRaisesRegex(ValueError, "authenticated control source"):
            _ = classify_slack_pages({"principal": "U01OWNER", "items": [item]})

    def test_dedicated_review_channel_recognizes_plain_human_pull_request(
        self,
    ) -> None:
        channel = "C0BLVQDSKUG"
        timestamp = "1785431825.473329"
        item: dict[str, object] = {
            "source_id": "slack_eng_acceleration_reviews",
            "kind": "thread",
            "channel": channel,
            "root": timestamp,
            "provider_page": {
                "messages": [
                    {
                        "channel": channel,
                        "user": "U02REVIEWER",
                        "ts": timestamp,
                        "text": (
                            "cleanup some ci worker terraform, should be noop "
                            "https://github.com/openai/openai/pull/1210236"
                        ),
                    }
                ],
                "response_metadata": {"next_cursor": ""},
            },
            "subject_heads": {"openai/openai#1210236": self.head},
        }

        result = classify_slack_pages({"principal": "U01OWNER", "items": [item]})

        records = result["results"]
        self.assertIsInstance(records, list)
        assert isinstance(records, list)
        event = records[0]["events"][0]
        self.assertEqual(event["category"], "review_request")
        self.assertEqual(event["reviewer"], "U01OWNER")
        self.assertEqual(event["subject_key"], "openai/openai#1210236")
        self.assertEqual(
            event["event_id"], f"slack:{channel}:{timestamp}:{timestamp}"
        )

    def test_plain_pull_request_outside_review_channel_is_owned_feedback(
        self,
    ) -> None:
        item = self.provider_item(
            text="cleanup https://github.com/example/repository/pull/42"
        )

        result = classify_slack_pages({"principal": "U01OWNER", "items": [item]})

        records = result["results"]
        self.assertIsInstance(records, list)
        assert isinstance(records, list)
        self.assertEqual(records[0]["events"][0]["category"], "owned_feedback")

    def test_review_channel_keeps_same_category_across_overlapping_sources(
        self,
    ) -> None:
        channel = "C0BLVQDSKUG"
        timestamp = "1785431825.473329"
        item: dict[str, object] = {
            "source_id": "slack_monitored_channels",
            "kind": "thread",
            "channel": channel,
            "root": timestamp,
            "review_channel": True,
            "provider_page": {
                "messages": [
                    {
                        "channel": channel,
                        "user": "U02REVIEWER",
                        "ts": timestamp,
                        "text": (
                            "cleanup some ci worker terraform, should be noop "
                            "https://github.com/openai/openai/pull/1210236"
                        ),
                    }
                ],
                "response_metadata": {"next_cursor": ""},
            },
            "subject_heads": {"openai/openai#1210236": self.head},
        }

        result = classify_slack_pages({"principal": "U01OWNER", "items": [item]})

        records = result["results"]
        self.assertIsInstance(records, list)
        assert isinstance(records, list)
        event = records[0]["events"][0]
        self.assertEqual(event["category"], "review_request")
        self.assertEqual(event["reviewer"], "U01OWNER")
        self.assertEqual(event["event_id"], f"slack:{channel}:{timestamp}:{timestamp}")

    def test_review_channel_preserves_each_pull_request_in_one_message(self) -> None:
        channel = "C0643PZFT5E"
        timestamp = "1785437240.749679"
        item: dict[str, object] = {
            "source_id": "slack_monitored_channels",
            "kind": "thread",
            "channel": channel,
            "root": timestamp,
            "review_channel": True,
            "provider_page": {
                "messages": [
                    {
                        "channel": channel,
                        "user": "U02REVIEWER",
                        "ts": timestamp,
                        "text": (
                            "some easy reviews: "
                            "https://github.com/openai/openai/pull/1207484 "
                            "https://github.com/openai/openai/pull/1207597"
                        ),
                    }
                ],
                "response_metadata": {"next_cursor": ""},
            },
            "subject_heads": {
                "openai/openai#1207484": self.head,
                "openai/openai#1207597": "b" * 40,
            },
        }

        result = classify_slack_pages({"principal": "U01OWNER", "items": [item]})

        records = result["results"]
        self.assertIsInstance(records, list)
        assert isinstance(records, list)
        events = records[0]["events"]
        self.assertEqual(
            [(event["subject_key"], event["category"]) for event in events],
            [
                ("openai/openai#1207484", "review_request"),
                ("openai/openai#1207597", "review_request"),
            ],
        )
        self.assertEqual(
            [event["event_id"] for event in events],
            [
                f"slack:{channel}:{timestamp}:{timestamp}",
                f"slack:{channel}:{timestamp}:{timestamp}:openai/openai#1207597",
            ],
        )

    def test_review_channel_still_rejects_unauthenticated_bot_requests(self) -> None:
        item: dict[str, object] = {
            "source_id": "slack_eng_acceleration_reviews",
            "kind": "thread",
            "channel": "C0BLVQDSKUG",
            "root": "1785431825.473329",
            "provider_page": {
                "messages": [
                    {
                        "channel": "C0BLVQDSKUG",
                        "user": "U02BOT",
                        "actor_is_bot": True,
                        "ts": "1785431825.473329",
                        "text": "https://github.com/openai/openai/pull/1210236",
                    }
                ],
                "response_metadata": {"next_cursor": ""},
            },
            "subject_heads": {"openai/openai#1210236": self.head},
        }

        result = classify_slack_pages({"principal": "U01OWNER", "items": [item]})

        records = result["results"]
        self.assertIsInstance(records, list)
        assert isinstance(records, list)
        self.assertEqual(records[0]["events"], [])

    def test_batched_classifier_rejects_unauthenticated_truncated_head(self) -> None:
        item = self.provider_item()
        item["subject_heads"] = {self.subject: "a" * 39}

        with self.assertRaisesRegex(ValueError, "complete SHA"):
            _ = classify_slack_pages({"principal": "U01OWNER", "items": [item]})

    def test_batched_classifier_refuses_actual_incomplete_cursor(self) -> None:
        item = self.provider_item()
        page = item["provider_page"]
        assert isinstance(page, dict)
        page["pagination_info"] = (
            "There are more messages in this thread. To view the next page, "
            "use cursor: `opaque-first-party-provider-cursor`\n"
        )

        with self.assertRaisesRegex(ValueError, "pagination is incomplete"):
            _ = classify_slack_pages({"principal": "U01OWNER", "items": [item]})

    def test_batched_classifier_refuses_unknown_provider_kind(self) -> None:
        item = self.provider_item(kind="unverified")

        with self.assertRaisesRegex(ValueError, "thread, control, or outbound"):
            _ = classify_slack_pages({"principal": "U01OWNER", "items": [item]})

    def test_cli_classifies_provider_batch_without_opening_database(self) -> None:
        request = {
            "principal": "U01OWNER",
            "items": [self.provider_item()],
        }
        output = StringIO()

        with (
            patch("sys.stdin", StringIO(json.dumps(request))),
            redirect_stdout(output),
        ):
            status = main(["slack-events"])

        self.assertEqual(status, 0)
        decoded: object = json.loads(output.getvalue())
        self.assertIsInstance(decoded, dict)
        assert isinstance(decoded, dict)
        records = decoded["results"]
        self.assertIsInstance(records, list)
        assert isinstance(records, list)
        self.assertEqual(records[0]["events"][0]["category"], "review_request")


if __name__ == "__main__":
    unittest.main()
