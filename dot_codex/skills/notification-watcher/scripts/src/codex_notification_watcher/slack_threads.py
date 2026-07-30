"""Extract authenticated direct and watched-channel thread notifications."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import cast

from .model import MAXIMUM_LIMIT, NotificationEvent, object_mapping, required_string


_PULL_REQUEST = re.compile(
    r"https://github\.com/(?P<owner>[^/\s<>]+)/(?P<repository>[^/\s<>]+)"
    r"/pull/(?P<number>[0-9]+)"
)
_CODEX_MENTION = re.compile(r"(?<![\w-])@codex\b", re.IGNORECASE)
_ASSISTANT_FOOTER = re.compile(
    r"\*Sent using\*\s+<@U[A-Z0-9]+\|ChatGPT>", re.IGNORECASE
)
_CHANNEL = re.compile(
    r"^Channel:\s*(?:[^\n]*?)\((?:ID:\s*)?(?P<channel>[CD][A-Z0-9]+)\)\s*$",
    re.MULTILINE,
)
_CHANNEL_MESSAGE = re.compile(
    r"^=== Message from [^\n]*\((?P<user>U[A-Z0-9]+)\) "
    r"at [^\n]* ===\s*\nMessage TS:\s*(?P<ts>[0-9]+\.[0-9]+)\s*\n",
    re.MULTILINE,
)
_DETAILED_THREAD_MESSAGE = re.compile(
    r"^(?:=== (?:THREAD (?:PARENT MESSAGE|REPLY(?: MESSAGE)?(?: [0-9]+)?)"
    r"|REPLY(?: [0-9]+)?) ===|--- Reply[^\n]* ---)\s*\n"
    r"From:\s*[^\n]*\((?P<user>U[A-Z0-9]+)\)\s*\n"
    r"(?:Time:\s*[^\n]*\n)?"
    r"Message TS:\s*(?P<ts>[0-9]+\.[0-9]+)\s*\n",
    re.MULTILINE,
)
_FLOW_HUMAN = re.compile(
    r"<slack://user\?[^>|]*?(?:&amp;|&)id=(?P<user>U[A-Z0-9]+)\|[^>]+>"
)
_PERSONAL_REVIEW_REQUEST = re.compile(
    r"(?:\br\?|\bwants you to review\b|\brequested your review\b"
    r"|\breview requested\b|\brequest(?:ed|ing)?\s+(?:a\s+)?review\b"
    r"|\b(?:could|can) you review\b|\bplease review\b"
    r"|\breview (?:this|that|it|my)\b|\btake another look\b"
    r"|\b(?:can|could) (?:i|we) get (?:a )?stamp\b)",
    re.IGNORECASE,
)
_SEARCH_RESULT = re.compile(r"^### Result [0-9]+ of [0-9]+\s*$", re.MULTILINE)
_SEARCH_ACTOR = re.compile(r"^From:\s*[^\n]*\(ID:\s*(U[A-Z0-9]+)\)", re.MULTILINE)
_SEARCH_TIMESTAMP = re.compile(r"^Message_ts:\s*([0-9]+\.[0-9]+)", re.MULTILINE)
_SEARCH_ROOT = re.compile(r"[?&]thread_ts=([0-9]+\.[0-9]+)")
_OBJECT_ID = re.compile(r"[0-9a-f]{40}\Z")


def rendered_slack_messages(
    value: object, *, channel: str | None = None, root: str | None = None
) -> dict[str, object]:
    """Normalize complete connector-rendered channel, thread, and search pages."""
    page = object_mapping(value, description="rendered Slack provider page")
    pagination = page.get("pagination_info")
    if isinstance(pagination, str) and (
        "there are more messages" in pagination.casefold()
        or "use cursor:" in pagination.casefold()
    ):
        raise ValueError("Slack thread pagination is incomplete")

    payload = page.get("messages", page.get("results"))
    if isinstance(payload, list):
        _ = _complete_messages(page)
        return dict(page)
    if not isinstance(payload, str):
        raise ValueError("rendered Slack provider page must contain message text")

    records: list[dict[str, object]] = []
    starts = list(_CHANNEL_MESSAGE.finditer(payload))
    detailed = False
    if not starts:
        starts = list(_DETAILED_THREAD_MESSAGE.finditer(payload))
        detailed = bool(starts)
    if detailed and (
        not isinstance(pagination, str)
        or pagination.strip() != "There are no more messages in this thread."
    ):
        raise ValueError("Slack thread pagination is incomplete")
    channel_match = _CHANNEL.search(payload)
    if starts:
        if channel_match is None and channel is None:
            raise ValueError("rendered Slack channel lacks an authenticated ID")
        source_channel = (
            channel_match.group("channel")
            if channel_match is not None
            else required_string(channel, description="Slack provider channel")
        )
        for index, match in enumerate(starts):
            end = starts[index + 1].start() if index + 1 < len(starts) else len(payload)
            body = payload[match.end() : end]
            body = re.split(
                r"^Thread:\s|^Reactions:\s|^Forwarded message from\s",
                body,
                maxsplit=1,
                flags=re.MULTILINE,
            )[0].strip()
            message_record: dict[str, object] = {
                "channel": source_channel,
                "user": match.group("user"),
                "ts": match.group("ts"),
                "text": body,
            }
            if root is not None:
                message_record["thread_ts"] = required_string(
                    root, description="Slack provider thread root"
                )
            embedded = _FLOW_HUMAN.search(body)
            review_text = body.casefold()
            if embedded is not None and (
                "wants you to review" in review_text
                or "could you take another look" in review_text
            ):
                message_record["human_actor"] = embedded.group("user")
            records.append(message_record)
    else:
        starts = list(_SEARCH_RESULT.finditer(payload))
        if not starts and payload.strip():
            raise ValueError("rendered Slack page has no authenticated message records")
        for index, match in enumerate(starts):
            end = starts[index + 1].start() if index + 1 < len(starts) else len(payload)
            block = payload[match.end() : end]
            result_channel = _CHANNEL.search(block)
            actor = _SEARCH_ACTOR.search(block)
            timestamp = _SEARCH_TIMESTAMP.search(block)
            if result_channel is None or actor is None or timestamp is None:
                raise ValueError("rendered Slack search lacks authenticated message identity")
            result_root = _SEARCH_ROOT.search(block)
            body_match = re.search(r"^Text:\s*\n?", block, re.MULTILINE)
            if body_match is None:
                raise ValueError("rendered Slack search lacks its message text")
            body = re.split(
                r"^Context before:\s|^Context after:\s|^---\s*$",
                block[body_match.end() :],
                maxsplit=1,
                flags=re.MULTILINE,
            )[0].strip()
            result_record: dict[str, object] = {
                "channel": result_channel.group("channel"),
                "user": actor.group(1),
                "ts": timestamp.group(1),
                "text": body,
            }
            if result_root is not None:
                result_record["thread_ts"] = result_root.group(1)
            records.append(result_record)

    return {
        "messages": records,
        "has_more": False,
        "response_metadata": {"next_cursor": ""},
    }


def _message_timestamp(value: object) -> datetime:
    timestamp = required_string(value, description="Slack message timestamp")
    try:
        return datetime.fromtimestamp(float(timestamp), tz=UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError("Slack message timestamp is invalid") from error


def slack_control_events(
    *, channel: str, root: str, messages: object, principal: str
) -> list[dict[str, object]]:
    """Record only an authenticated principal's control roots and replies."""
    source_channel = required_string(channel, description="Slack control channel")
    source_root = required_string(root, description="Slack control thread root")
    owner = required_string(principal, description="Slack control principal")
    events: list[dict[str, object]] = []
    for value in _complete_messages(messages):
        message = object_mapping(value, description="Slack control message")
        if message.get("actor_is_bot") is True and "human_actor" not in message:
            continue
        if message.get("human_actor", message.get("user")) != owner:
            continue
        timestamp = required_string(
            message.get("ts"), description="Slack control timestamp"
        )
        text = required_string(
            message.get("text"), description="Slack control message text"
        )
        if _ASSISTANT_FOOTER.search(text) is not None:
            continue
        event_id = f"slack:{source_channel}:{source_root}:{timestamp}"
        events.append(
            {
                "verified": True,
                "event_id": event_id,
                "logical_cycle_id": event_id,
                "category": "control_task",
                "subject_key": f"slack:{source_channel}:{source_root}",
                "actor": owner,
                "actor_type": "User",
                "occurred_at": _message_timestamp(timestamp).isoformat(
                    timespec="microseconds"
                ),
                "event_type": "slack_principal_control_task",
                "body": text,
            }
        )
    return events


def _complete_messages(value: object) -> list[object]:
    page = object_mapping(value, description="Slack thread page")
    if page.get("has_more") not in (None, False):
        raise ValueError("Slack thread pagination is incomplete")
    metadata = page.get("response_metadata")
    if metadata is not None:
        cursor = object_mapping(metadata, description="Slack response metadata")
        if cursor.get("next_cursor") not in (None, ""):
            raise ValueError("Slack thread pagination is incomplete")
    messages = page.get("messages")
    if not isinstance(messages, list):
        raise ValueError("Slack thread messages must be a list")
    return cast(list[object], messages)


def discover_owned_thread_scopes(
    messages: object, *, principal: str
) -> tuple[str, ...]:
    """Discover roots from real outbound messages, not static channel names."""
    owner = required_string(principal, description="Slack principal")
    scopes: set[str] = set()
    for value in _complete_messages(messages):
        message = object_mapping(value, description="Slack outbound message")
        if message.get("user") != owner:
            continue
        channel = required_string(message.get("channel"), description="Slack channel")
        root = message.get("thread_ts", message.get("ts"))
        timestamp = required_string(root, description="Slack thread timestamp")
        scopes.add(f"slack:{channel}:{timestamp}")
    return tuple(sorted(scopes))


def slack_thread_events(
    *,
    channel: str,
    root: str,
    messages: object,
    principal: str,
    subject_heads: dict[str, str],
    direct: bool = False,
) -> list[dict[str, object]]:
    """Keep genuine human root/reply requests independent of other reactions."""
    source_channel = required_string(channel, description="Slack channel")
    source_root = required_string(root, description="Slack thread root")
    owner = required_string(principal, description="Slack principal")
    events: list[dict[str, object]] = []
    inherited_subject: str | None = None
    for value in _complete_messages(messages):
        message = object_mapping(value, description="Slack thread message")
        if message.get("actor_is_bot") is True and "human_actor" not in message:
            continue
        if message.get("human_actor_is_bot") is True:
            continue
        actor = message.get("human_actor", message.get("user"))
        if not isinstance(actor, str) or not actor:
            continue
        text = required_string(message.get("text"), description="Slack message text")
        found = _PULL_REQUEST.search(text)
        subject: str | None = None
        if found is not None:
            subject = (
                f"{found.group('owner')}/{found.group('repository')}"
                f"#{found.group('number')}"
            )
            inherited_subject = subject
        else:
            subject = inherited_subject
        if actor == owner:
            continue
        if subject is None:
            if not direct:
                continue
            timestamp = required_string(
                message.get("ts"), description="Slack message timestamp"
            )
            event_id = f"slack:{source_channel}:{source_root}:{timestamp}"
            events.append(
                {
                    "verified": True,
                    "event_id": event_id,
                    "logical_cycle_id": event_id,
                    "category": "owned_feedback",
                    "subject_key": f"slack:{source_channel}:{source_root}",
                    "actor": actor,
                    "actor_type": "User",
                    "occurred_at": _message_timestamp(timestamp).isoformat(
                        timespec="microseconds"
                    ),
                    "event_type": "slack_direct_human_message",
                    "body": text,
                }
            )
            continue
        head = subject_heads.get(subject)
        if head is None:
            raise ValueError("Slack pull request lacks its authenticated exact head")
        timestamp = required_string(message.get("ts"), description="Slack message timestamp")
        created = _message_timestamp(timestamp)
        principal_mentioned = f"<@{owner}>" in text or f"@{owner}" in text
        automation_only = (
            _CODEX_MENTION.search(text) is not None and not principal_mentioned
        )
        review_request = not automation_only and (
            principal_mentioned or _PERSONAL_REVIEW_REQUEST.search(text) is not None
        )
        event_id = f"slack:{source_channel}:{source_root}:{timestamp}"
        event: dict[str, object] = {
            "verified": True,
            "event_id": event_id,
            "logical_cycle_id": event_id,
            "category": "review_request" if review_request else "owned_feedback",
            "subject_key": subject,
            "head": head,
            "actor": actor,
            "actor_type": "User",
            "body": text,
            "occurred_at": created.isoformat(timespec="microseconds"),
            "event_type": "slack_thread_review_request"
            if review_request
            else "slack_thread_human_reply",
        }
        if review_request:
            event["reviewer"] = owner
        events.append(event)
    return events


def classify_slack_pages(value: object) -> dict[str, object]:
    """Classify one bounded batch of fully authenticated provider pages."""
    request = object_mapping(value, description="Slack page classification")
    principal = required_string(request.get("principal"), description="Slack principal")
    supplied = request.get("items")
    if not isinstance(supplied, list) or not supplied:
        raise ValueError("Slack page classification requires a nonempty item list")
    items = cast(list[object], supplied)
    if len(items) > MAXIMUM_LIMIT:
        raise ValueError("Slack page classification exceeds its item limit")

    results: list[dict[str, object]] = []
    for supplied_item in items:
        item = object_mapping(supplied_item, description="Slack provider item")
        source_id = required_string(item.get("source_id"), description="Slack source")
        if not source_id.startswith("slack_"):
            raise ValueError("Slack provider item does not belong to a Slack source")
        kind = required_string(item.get("kind"), description="Slack provider kind")
        channel = required_string(item.get("channel"), description="Slack channel")
        root = required_string(item.get("root"), description="Slack thread root")
        direct = item.get("direct", False)
        if not isinstance(direct, bool):
            raise ValueError("Slack direct-message classification must be a boolean")
        heads_value = item.get("subject_heads", {})
        heads_record = object_mapping(heads_value, description="Slack subject heads")
        subject_heads: dict[str, str] = {}
        for subject, candidate in heads_record.items():
            subject_key = required_string(subject, description="Slack pull request")
            head = required_string(candidate, description="Slack pull request head")
            if _OBJECT_ID.fullmatch(head) is None:
                raise ValueError("Slack pull request head must be a complete SHA")
            subject_heads[subject_key] = head
        page = rendered_slack_messages(
            item.get("provider_page"), channel=channel, root=root
        )

        events: list[dict[str, object]]
        owned_scopes: tuple[str, ...] = ()
        if kind == "thread":
            events = slack_thread_events(
                channel=channel,
                root=root,
                messages=page,
                principal=principal,
                subject_heads=subject_heads,
                direct=direct,
            )
        elif kind == "control":
            events = slack_control_events(
                channel=channel, root=root, messages=page, principal=principal
            )
        elif kind == "outbound":
            events = []
            owned_scopes = discover_owned_thread_scopes(page, principal=principal)
        else:
            raise ValueError("Slack provider kind must be thread, control, or outbound")
        for event in events:
            _ = NotificationEvent.from_object(event, source_id=source_id)
        results.append(
            {
                "source_id": source_id,
                "channel": channel,
                "root": root,
                "events": events,
                "candidate_event_ids": [event["event_id"] for event in events],
                "owned_scopes": list(owned_scopes),
            }
        )

    return {"results": results}
