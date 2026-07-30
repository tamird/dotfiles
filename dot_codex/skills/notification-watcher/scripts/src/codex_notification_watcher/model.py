"""Validated, provider-independent source notifications."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import re
from typing import Literal, cast

MINIMUM_OVERLAP_SECONDS = 300
MAXIMUM_LIMIT = 100
type NotificationCategory = Literal[
    "review_request", "control_task", "owned_feedback", "ci_update"
]

_CATEGORIES: frozenset[str] = frozenset(
    {"review_request", "control_task", "owned_feedback", "ci_update"}
)
_FULL_HEAD = re.compile(r"[0-9a-f]{40}\Z")


def object_mapping(value: object, *, description: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object")
    mapping = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in mapping):
        raise ValueError(f"{description} contains a non-string key")
    return cast(Mapping[str, object], mapping)


def required_string(value: object, *, description: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{description} must be a nonempty string")
    return value


def utc_datetime(value: object, *, description: str) -> datetime:
    text = required_string(value, description=description)
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(
            f"{description} must be a timezone-aware ISO-8601 timestamp"
        ) from error
    if result.tzinfo is None:
        raise ValueError(f"{description} must include a timezone")
    return result.astimezone(UTC)


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def compact_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def digest(value: object) -> str:
    return sha256(compact_json(value).encode()).hexdigest()


def bounded_limit(value: int) -> int:
    if isinstance(value, bool) or not 1 <= value <= MAXIMUM_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAXIMUM_LIMIT}")
    return value


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    """One verified notification under a single replayable source."""

    source_id: str
    event_id: str
    category: NotificationCategory
    subject_key: str
    actor: str
    actor_type: str
    occurred_at: str
    head: str | None
    logical_cycle_id: str
    raw: Mapping[str, object]

    @classmethod
    def from_object(cls, value: object, *, source_id: str) -> NotificationEvent:
        record = object_mapping(value, description="notification")
        if record.get("verified") is not True:
            raise ValueError("notification lacks authenticated provider evidence")

        category_value = required_string(
            record.get("category"), description="notification category"
        )
        if category_value not in _CATEGORIES:
            raise ValueError("notification category is unsupported")
        category = cast(NotificationCategory, category_value)

        actor = required_string(record.get("actor"), description="event actor")
        actor_type = required_string(
            record.get("actor_type"), description="event actor type"
        )
        if actor_type not in {"User", "Bot"}:
            raise ValueError("event actor must be a verified human or bot")

        event_id = required_string(record.get("event_id"), description="event ID")
        subject = required_string(
            record.get("subject_key"), description="notification subject"
        )
        occurred_at = utc_text(
            utc_datetime(record.get("occurred_at"), description="event time")
        )

        head_value = record.get("head")
        head: str | None = None
        if head_value is not None:
            head = required_string(head_value, description="object ID")
            if _FULL_HEAD.fullmatch(head) is None:
                raise ValueError("object ID must be a complete lowercase SHA")

        if category == "review_request":
            reviewer = required_string(
                record.get("reviewer"), description="requested reviewer"
            )
            if actor_type != "User":
                if (
                    not source_id.endswith(
                        ("_review_requested_search", "_individually_assigned_pull_requests")
                    )
                    or record.get("author_type") != "User"
                    or record.get("reviewer_type") not in (None, "User")
                ):
                    raise ValueError("review requests must originate from a human")
                author = required_string(
                    record.get("author"), description="human review author"
                )
                if reviewer == author:
                    raise ValueError("self-requested review is not review intake")
            if reviewer == actor:
                raise ValueError("self-requested review is not review intake")
            if head is None:
                raise ValueError("review requests require a complete head")
        elif category == "control_task" and actor_type != "User":
            raise ValueError("control tasks must originate from a human")

        cycle = record.get("logical_cycle_id")
        if cycle is None:
            cycle = digest(
                {
                    "category": category,
                    "subject_key": subject,
                    "actor": actor,
                    "head": head,
                    "occurred_at": occurred_at,
                }
            )

        return cls(
            source_id=source_id,
            event_id=event_id,
            category=category,
            subject_key=subject,
            actor=actor,
            actor_type=actor_type,
            occurred_at=occurred_at,
            head=head,
            logical_cycle_id=required_string(
                cycle, description="logical notification cycle"
            ),
            raw=record,
        )

    def evidence(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "event_id": self.event_id,
            "category": self.category,
            "subject_key": self.subject_key,
            "actor": self.actor,
            "actor_type": self.actor_type,
            "occurred_at": self.occurred_at,
            "head": self.head,
            "logical_cycle_id": self.logical_cycle_id,
            "payload": dict(self.raw),
        }
