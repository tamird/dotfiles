"""Preserve fully paginated first-party pull-request review-thread evidence."""

from __future__ import annotations

from typing import cast

from .model import object_mapping, required_string


def _complete_nodes(value: object, *, description: str) -> list[object]:
    connection = object_mapping(value, description=description)
    page = object_mapping(connection.get("pageInfo"), description=f"{description} page")
    if page.get("hasNextPage") is not False:
        raise ValueError(f"{description} pagination is incomplete")
    nodes = connection.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError(f"{description} nodes must be a list")
    return cast(list[object], nodes)


def owned_review_thread_events(
    *,
    subject_key: str,
    current_head: str,
    principal: str,
    threads: object,
) -> list[dict[str, object]]:
    """Extract root and nested human comments without notification assumptions."""
    subject = required_string(subject_key, description="pull request subject")
    current = required_string(current_head, description="pull request current head")
    reviewer = required_string(principal, description="pull request principal")
    events: list[dict[str, object]] = []
    for item in _complete_nodes(threads, description="owned review threads"):
        thread = object_mapping(item, description="owned review thread")
        thread_id = required_string(thread.get("id"), description="review thread ID")
        comments = _complete_nodes(
            thread.get("comments"), description="owned review thread comments"
        )
        for comment_item in comments:
            comment = object_mapping(comment_item, description="review thread comment")
            author = object_mapping(comment.get("author"), description="comment author")
            if author.get("__typename") != "User":
                continue
            actor = required_string(author.get("login"), description="comment author")
            raw_id = comment.get("databaseId")
            if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)):
                raise ValueError("review comment requires its immutable provider ID")
            event_id = required_string(str(raw_id), description="review comment ID")
            previous = comment.get("replyTo")
            if previous is None:
                root_id = event_id
            else:
                parent = object_mapping(previous, description="review comment parent")
                raw_parent = parent.get("databaseId")
                if isinstance(raw_parent, bool) or not isinstance(raw_parent, (int, str)):
                    raise ValueError("review reply requires its immutable root ID")
                root_id = required_string(str(raw_parent), description="review root ID")
            generation = (
                root_id if actor == reviewer else event_id
            )
            original = comment.get("originalCommit")
            reviewed_head = current
            if original is not None:
                reviewed_head = required_string(
                    object_mapping(
                        original, description="review comment original commit"
                    ).get("oid"),
                    description="review comment original head",
                )
            event: dict[str, object] = {
                "verified": True,
                "event_id": event_id,
                "logical_cycle_id": f"owned-inline:{subject}:{generation}",
                "category": "owned_feedback",
                "subject_key": subject,
                "head": reviewed_head,
                "current_head": current,
                "actor": actor,
                "actor_type": "User",
                "occurred_at": required_string(
                    comment.get("createdAt"), description="review comment creation"
                ),
                "thread_id": thread_id,
                "event_type": (
                    "principal_owned_review_thread_reply"
                    if actor == reviewer
                    else "human_owned_review_thread_comment"
                ),
                "body": required_string(comment.get("body"), description="comment body"),
                "url": required_string(comment.get("url"), description="comment URL"),
            }
            if previous is not None:
                event["in_reply_to"] = root_id
            events.append(event)
    return events
