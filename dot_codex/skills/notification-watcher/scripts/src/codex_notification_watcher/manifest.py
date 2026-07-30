"""Bootstrap only the explicitly configured private notification sources."""

from __future__ import annotations

from typing import cast

from .model import compact_json, object_mapping, required_string, utc_datetime, utc_text
from .source import register_source
from .store import Store


def bootstrap(store: Store, value: object) -> dict[str, object]:
    """Initialize verified source definitions without faking an observation."""
    manifest = object_mapping(value, description="notification source manifest")
    owner = required_string(manifest.get("owner"), description="source owner")
    replay_value = manifest.get("replay_from")
    replay_from = (
        utc_text(utc_datetime(replay_value, description="emergency replay time"))
        if replay_value is not None
        else None
    )
    values = manifest.get("sources")
    if not isinstance(values, list) or not values:
        raise ValueError("source manifest must contain at least one source")

    sources = [
        required_string(item, description="configured source")
        for item in cast(list[object], values)
    ]
    if len(sources) != len(set(sources)):
        raise ValueError("source manifest contains duplicate sources")

    for source_id in sources:
        _ = register_source(
            store,
            {
                "source_id": source_id,
                "owner": owner,
                "replay_from": replay_from,
                "verified": True,
            },
        )

    with store.transaction():
        _ = store.connection.execute(
            "INSERT INTO metadata (key, value_json) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
            ("required_notification_sources", compact_json(sorted(sources))),
        )

    return {
        "source_count": len(sources),
        "owner": owner,
        "replay_from": replay_from,
        "status": "initialization_required",
    }
