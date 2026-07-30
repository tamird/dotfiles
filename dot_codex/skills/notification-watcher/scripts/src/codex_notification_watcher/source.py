"""Own verified source pages and claim each notification exactly once."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
import json
import sqlite3
from typing import cast

from .model import (
    MAXIMUM_LIMIT,
    MINIMUM_OVERLAP_SECONDS,
    NotificationEvent,
    compact_json,
    digest,
    object_mapping,
    required_string,
    utc_datetime,
    utc_text,
)
from .store import Store


def _scope_names(value: object, *, description: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{description} must be a list of scope names")
    names = tuple(
        required_string(name, description=description)
        for name in cast(list[object], value)
    )
    if len(names) != len(set(names)):
        raise ValueError(f"{description} contains duplicate scope names")
    return tuple(sorted(names))


def register_source(store: Store, value: object) -> dict[str, object]:
    record = object_mapping(value, description="source registration")
    if record.get("verified") is not True:
        raise ValueError("source registration lacks authenticated evidence")

    source_id = required_string(record.get("source_id"), description="source ID")
    owner = required_string(record.get("owner"), description="source owner")
    replay_value = record.get("replay_from")
    replay_from = (
        utc_text(utc_datetime(replay_value, description="source replay start"))
        if replay_value is not None
        else None
    )
    historical = record.get("historical")
    if historical is not None and not isinstance(historical, bool):
        raise ValueError("source historical state must be a boolean")
    if historical is True and replay_from is None:
        raise ValueError("historical source requires an authenticated replay start")
    overlap = record.get("overlap_seconds", MINIMUM_OVERLAP_SECONDS)
    if (
        isinstance(overlap, bool)
        or not isinstance(overlap, int)
        or overlap < MINIMUM_OVERLAP_SECONDS
    ):
        raise ValueError("source requires at least 300 seconds of replay overlap")

    evidence: dict[str, object] = {
        "source_id": source_id,
        "owner": owner,
        "replay_from": replay_from,
        "overlap_seconds": overlap,
        "verified": True,
    }
    if historical is not None:
        evidence["historical"] = historical
    receipt_id = f"source-registration:{digest(evidence)}"

    with store.transaction():
        existing = store.connection.execute(
            "SELECT owner, overlap_seconds FROM sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if existing is not None:
            if existing["owner"] != owner or existing["overlap_seconds"] != overlap:
                raise ValueError("source registration conflicts with its original owner")
            receipt = store.connection.execute(
                "SELECT receipt_id FROM receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
            if receipt is None:
                raise ValueError("source registration conflicts with its replay start")
            return {
                "source_id": source_id,
                "receipt_id": receipt_id,
                "already_registered": True,
            }

        _ = store.connection.execute(
            "INSERT INTO sources "
            "(source_id, owner, status, high_water_mark, overlap_floor, "
            "overlap_seconds, pagination_complete, raw_json) "
            "VALUES (?, ?, 'INITIALIZATION_REQUIRED', NULL, ?, ?, 0, ?)",
            (source_id, owner, replay_from, overlap, compact_json(evidence)),
        )
        _ = store.receipt(
            receipt_id=receipt_id,
            source_id=source_id,
            event_id="source-registration",
            cycle=None,
            status="REGISTERED",
            evidence=evidence,
        )
    return {
        "source_id": source_id,
        "receipt_id": receipt_id,
        "already_registered": False,
    }


def _registered_source(store: Store, source_id: str) -> sqlite3.Row:
    row = store.connection.execute(
        "SELECT source_id, owner, status, high_water_mark, overlap_floor, "
        "overlap_seconds, pagination_complete, raw_json "
        "FROM sources WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    if row is None:
        raise ValueError("observation has no registered source")
    if row["status"] == "HISTORICAL":
        raise ValueError("historical sources cannot receive new observations")
    return row


def _record_event(store: Store, event: NotificationEvent) -> bool:
    evidence = event.evidence()
    encoded = compact_json(evidence)
    row = store.connection.execute(
        "SELECT category, logical_cycle_id, subject_key, actor, actor_type, "
        "occurred_at, head, raw_json FROM notifications "
        "WHERE source_id = ? AND event_id = ?",
        (event.source_id, event.event_id),
    ).fetchone()
    expected = (
        event.category,
        event.logical_cycle_id,
        event.subject_key,
        event.actor,
        event.actor_type,
        event.occurred_at,
        event.head,
        encoded,
    )
    if row is not None:
        if tuple(row) != expected:
            raise ValueError("event ID conflicts with immutable notification evidence")
        return False

    prior = store.connection.execute(
        "SELECT category, subject_key FROM claims WHERE logical_cycle_id = ?",
        (event.logical_cycle_id,),
    ).fetchone()
    if prior is not None and (
        prior["category"] != event.category
        or prior["subject_key"] != event.subject_key
    ):
        raise ValueError("logical notification cycle conflicts with another subject")

    _ = store.connection.execute(
        "INSERT INTO notifications "
        "(source_id, event_id, category, logical_cycle_id, subject_key, "
        "actor, actor_type, occurred_at, head, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event.source_id,
            event.event_id,
            event.category,
            event.logical_cycle_id,
            event.subject_key,
            event.actor,
            event.actor_type,
            event.occurred_at,
            event.head,
            encoded,
        ),
    )
    if prior is None:
        _ = store.connection.execute(
            "INSERT INTO claims "
            "(logical_cycle_id, category, source_id, event_id, subject_key, "
            "status, owner, terminal_event_id) "
            "VALUES (?, ?, ?, ?, ?, 'pending', NULL, NULL)",
            (
                event.logical_cycle_id,
                event.category,
                event.source_id,
                event.event_id,
                event.subject_key,
            ),
        )
    _ = store.receipt(
        receipt_id=f"notification:{digest({'source_id': event.source_id, 'event_id': event.event_id})}",
        source_id=event.source_id,
        event_id=event.event_id,
        cycle=event.logical_cycle_id,
        status="DISCOVERED",
        evidence=evidence,
    )
    return True


def ingest(store: Store, value: object) -> dict[str, object]:
    batch = object_mapping(value, description="authenticated source observation")
    if batch.get("verified") is not True:
        raise ValueError("source observation lacks authenticated evidence")

    source_id = required_string(batch.get("source_id"), description="source ID")
    owner = required_string(batch.get("owner"), description="source owner")
    observed = utc_datetime(
        batch.get("observed_at"), description="physical observation time"
    )
    high = utc_datetime(
        batch.get("high_water_mark"), description="source high-water mark"
    )
    floor = utc_datetime(batch.get("overlap_floor"), description="source replay floor")
    overlap = batch.get("overlap_seconds", MINIMUM_OVERLAP_SECONDS)
    complete = batch.get("pagination_complete")
    records = batch.get("events")

    if (
        isinstance(overlap, bool)
        or not isinstance(overlap, int)
        or overlap < MINIMUM_OVERLAP_SECONDS
    ):
        raise ValueError("source observation requires at least 300 seconds of replay")
    if high - floor < timedelta(seconds=overlap):
        raise ValueError("source replay floor does not cover its required overlap")
    if not isinstance(complete, bool):
        raise ValueError("source observation must certify its pagination status")
    if not isinstance(records, list):
        raise ValueError("source observation must supply its observed event page")

    scope_coverage: tuple[tuple[str, ...], tuple[str, ...]] | None = None
    if ("required_scopes" in batch) != ("observed_scopes" in batch):
        raise ValueError("source scope coverage requires both scope lists")
    if "required_scopes" in batch:
        required_scopes = _scope_names(
            batch["required_scopes"], description="required source scopes"
        )
        observed_scopes = _scope_names(
            batch["observed_scopes"], description="observed source scopes"
        )
        if not set(observed_scopes).issubset(required_scopes):
            raise ValueError("source observation claims an unknown scope")
        if complete and set(required_scopes) != set(observed_scopes):
            raise ValueError("complete source observation omits a required scope")
        scope_coverage = (required_scopes, observed_scopes)

    events = [
        NotificationEvent.from_object(item, source_id=source_id)
        for item in cast(list[object], records)
    ]
    seen: set[str] = set()
    for event in events:
        if event.event_id in seen:
            raise ValueError("source observation repeats an event ID")
        seen.add(event.event_id)
        if utc_datetime(event.occurred_at, description="event time") > high:
            raise ValueError("notification occurs after its source high-water mark")

    candidate_ids: tuple[str, ...] | None = None
    if "observed_candidate_event_ids" in batch:
        supplied_candidates = batch["observed_candidate_event_ids"]
        if not isinstance(supplied_candidates, list):
            raise ValueError("observed candidate event IDs must be a list")
        candidates = tuple(
            required_string(item, description="observed candidate event ID")
            for item in cast(list[object], supplied_candidates)
        )
        if len(candidates) != len(set(candidates)):
            raise ValueError("observed candidate event IDs contain duplicates")
        if set(candidates) != seen:
            raise ValueError(
                "source observation omits an authenticated actionable event "
                "or contains an unreported event"
            )
        candidate_ids = tuple(sorted(candidates))

    with store.transaction():
        source = _registered_source(store, source_id)
        if source["owner"] != owner:
            raise ValueError("source observation does not belong to its owner")
        if source["overlap_seconds"] != overlap:
            raise ValueError("source observation changes its registered replay overlap")
        previous = source["high_water_mark"]
        if isinstance(previous, str):
            previous_high = utc_datetime(
                previous, description="previous high-water mark"
            )
            if high < previous_high:
                raise ValueError("source high-water mark cannot regress")
            if complete and floor > previous_high - timedelta(seconds=overlap):
                raise ValueError(
                    "source replay floor does not cover the previous checkpoint overlap"
                )
        elif complete:
            replay_start = source["overlap_floor"]
            if isinstance(replay_start, str) and floor > utc_datetime(
                replay_start, description="registered source replay start"
            ):
                raise ValueError(
                    "initial source replay floor skips the registered replay start"
                )

        discovered = sum(_record_event(store, event) for event in events)
        evidence: dict[str, object] = {
            "source_id": source_id,
            "owner": owner,
            "observed_at": utc_text(observed),
            "high_water_mark": utc_text(high),
            "overlap_floor": utc_text(floor),
            "overlap_seconds": overlap,
            "pagination_complete": complete,
            "event_count": len(events),
        }
        if scope_coverage is not None:
            evidence["required_scopes"] = list(scope_coverage[0])
            evidence["observed_scopes"] = list(scope_coverage[1])
        if candidate_ids is not None:
            evidence["observed_candidate_event_ids"] = list(candidate_ids)
        receipt_id = f"source-observation:{digest(evidence)}"
        status = "HEALTHY" if complete else "DEGRADED"
        _ = store.receipt(
            receipt_id=receipt_id,
            source_id=source_id,
            event_id="source-observation",
            cycle=None,
            status=status,
            evidence=evidence,
        )

        if complete:
            _ = store.connection.execute(
                "UPDATE sources SET status = ?, high_water_mark = ?, "
                "overlap_floor = ?, pagination_complete = 1 "
                "WHERE source_id = ? AND owner = ?",
                (status, utc_text(high), utc_text(floor), source_id, owner),
            )
        else:
            _ = store.connection.execute(
                "UPDATE sources SET status = ?, pagination_complete = 0 "
                "WHERE source_id = ? AND owner = ?",
                (status, source_id, owner),
            )

        heartbeat = store.connection.execute(
            "SELECT value_json FROM metadata WHERE key = ?",
            ("notification_heartbeat",),
        ).fetchone()
        if heartbeat is None:
            _ = store.heartbeat(owner=owner, observed_at=utc_text(observed))
        else:
            heartbeat_evidence = object_mapping(
                json.loads(cast(str, heartbeat["value_json"])),
                description="notification heartbeat",
            )
            previous_heartbeat = utc_datetime(
                heartbeat_evidence.get("observed_at"),
                description="heartbeat observation",
            )
            if observed >= previous_heartbeat:
                _ = store.heartbeat(owner=owner, observed_at=utc_text(observed))

    return {
        "source_id": source_id,
        "receipt_id": receipt_id,
        "discovered": discovered,
        "deduplicated": len(events) - discovered,
        "pagination_complete": complete,
        "checkpoint_advanced": complete,
    }


def record_failure(store: Store, value: object) -> dict[str, object]:
    failure = object_mapping(value, description="authenticated source failure")
    if failure.get("verified") is not True:
        raise ValueError("source failure lacks authenticated evidence")

    source_id = required_string(failure.get("source_id"), description="source ID")
    owner = required_string(failure.get("owner"), description="source owner")
    kind = required_string(failure.get("kind"), description="source failure kind")
    observed_at = utc_text(
        utc_datetime(failure.get("observed_at"), description="failure observation time")
    )
    evidence: dict[str, object] = {
        "source_id": source_id,
        "owner": owner,
        "kind": kind,
        "observed_at": observed_at,
        "verified": True,
    }
    receipt_id = f"source-failure:{digest(evidence)}"

    with store.transaction():
        source = _registered_source(store, source_id)
        if source["owner"] != owner:
            raise ValueError("source failure does not belong to its registered owner")
        created = store.receipt(
            receipt_id=receipt_id,
            source_id=source_id,
            event_id="source-failure",
            cycle=None,
            status="DEGRADED",
            evidence=evidence,
        )
        _ = store.connection.execute(
            "UPDATE sources SET status = 'DEGRADED', pagination_complete = 0 "
            "WHERE source_id = ? AND owner = ?",
            (source_id, owner),
        )

    return {
        "source_id": source_id,
        "receipt_id": receipt_id,
        "already_recorded": not created,
    }


def replay(store: Store, source_id: str) -> dict[str, object]:
    row = _registered_source(
        store, required_string(source_id, description="source ID")
    )
    return {
        "source_id": row["source_id"],
        "owner": row["owner"],
        "high_water_mark": row["high_water_mark"],
        "overlap_floor": row["overlap_floor"],
        "overlap_seconds": row["overlap_seconds"],
        "pagination_complete": row["pagination_complete"] == 1,
    }


def claim(store: Store, *, logical_cycle_id: str, owner: str) -> dict[str, object]:
    cycle = required_string(logical_cycle_id, description="notification cycle")
    claimant = required_string(owner, description="notification owner")

    with store.transaction():
        changed = store.connection.execute(
            "UPDATE claims SET owner = ?, status = 'claimed' "
            "WHERE logical_cycle_id = ? AND status = 'pending' AND owner IS NULL",
            (claimant, cycle),
        )
        if changed.rowcount == 0:
            row = store.connection.execute(
                "SELECT owner, status FROM claims WHERE logical_cycle_id = ?",
                (cycle,),
            ).fetchone()
            if row is None:
                raise ValueError("notification claim does not exist")
            if row["owner"] != claimant or row["status"] != "claimed":
                raise ValueError("notification is already claimed or resolved")
            return {
                "logical_cycle_id": cycle,
                "owner": claimant,
                "already_claimed": True,
            }

    return {"logical_cycle_id": cycle, "owner": claimant, "already_claimed": False}


def supersede(
    store: Store,
    *,
    logical_cycle_id: str,
    owner: str,
    evidence: Mapping[str, object],
) -> dict[str, object]:
    """Close a disproved claim without inventing a published review."""
    cycle = required_string(logical_cycle_id, description="notification cycle")
    claimant = required_string(owner, description="notification owner")
    record = object_mapping(evidence, description="supersession evidence")
    if record.get("verified") is not True:
        raise ValueError("supersession lacks authenticated provider evidence")
    source_id = required_string(
        record.get("source_id"), description="supersession evidence source"
    )
    evidence_event_id = required_string(
        record.get("event_id"), description="supersession evidence event"
    )
    reason = required_string(
        record.get("reason"), description="supersession reason"
    )
    if len(reason) > 1024:
        raise ValueError("supersession reason exceeds 1,024 characters")

    with store.transaction():
        row = store.connection.execute(
            "SELECT claims.source_id, claims.event_id, claims.owner, "
            "claims.status, claims.terminal_event_id, notifications.head, "
            "sources.owner AS source_owner, sources.status AS source_status "
            "FROM claims "
            "JOIN notifications ON "
            "notifications.source_id = claims.source_id "
            "AND notifications.event_id = claims.event_id "
            "JOIN sources ON sources.source_id = claims.source_id "
            "WHERE claims.logical_cycle_id = ?",
            (cycle,),
        ).fetchone()
        if row is None:
            raise ValueError("notification claim does not exist")
        if row["source_owner"] != claimant or row["source_status"] == "HISTORICAL":
            raise ValueError("supersession does not belong to the active source owner")
        if source_id != row["source_id"]:
            raise ValueError("supersession evidence does not match its source")
        if record.get("head") != row["head"]:
            raise ValueError("supersession evidence does not match the exact head")

        previous_owner = cast(str | None, row["owner"])
        existing: sqlite3.Row | None = None
        if row["status"] == "superseded":
            terminal_receipts = store.connection.execute(
                "SELECT receipt_id, source_id, event_id, logical_cycle_id, "
                "status, raw_json FROM receipts "
                "WHERE source_id = ? AND event_id = ? "
                "AND logical_cycle_id = ? AND status = 'SUPERSEDED' LIMIT 2",
                (row["source_id"], row["event_id"], cycle),
            ).fetchall()
            if len(terminal_receipts) != 1:
                raise ValueError(
                    "notification has no unique supersession evidence"
                )
            terminal_receipt = terminal_receipts[0]
            if terminal_receipt is None:
                raise ValueError(
                    "notification has no unique supersession evidence"
                )
            existing = terminal_receipt
            previous_proof = object_mapping(
                json.loads(cast(str, terminal_receipt["raw_json"])),
                description="recorded supersession evidence",
            )
            if "claim_owner" not in previous_proof:
                raise ValueError(
                    "supersession evidence omits the original claim owner"
                )
            recorded_owner = previous_proof["claim_owner"]
            if recorded_owner is not None and not isinstance(recorded_owner, str):
                raise ValueError("supersession has an invalid original claim owner")
            previous_owner = recorded_owner

        proof: dict[str, object] = {
            "logical_cycle_id": cycle,
            "owner": claimant,
            "claim_owner": previous_owner,
            "source_id": source_id,
            "event_id": evidence_event_id,
            "head": row["head"],
            "reason": reason,
            "verified": True,
        }
        receipt_id = f"notification-supersession:{digest(proof)}"
        if row["status"] == "superseded":
            if (
                existing is None
                or existing["receipt_id"] != receipt_id
                or tuple(existing)
                != (
                    receipt_id,
                    row["source_id"],
                    row["event_id"],
                    cycle,
                    "SUPERSEDED",
                    compact_json(proof),
                )
                or row["terminal_event_id"] != evidence_event_id
            ):
                raise ValueError("notification already has different supersession evidence")
            return {
                "logical_cycle_id": cycle,
                "owner": claimant,
                "receipt_id": receipt_id,
                "already_superseded": True,
            }
        if row["status"] not in {"pending", "claimed", "blocked"}:
            raise ValueError("resolved notifications cannot be superseded")

        _ = store.receipt(
            receipt_id=receipt_id,
            source_id=cast(str, row["source_id"]),
            event_id=cast(str, row["event_id"]),
            cycle=cycle,
            status="SUPERSEDED",
            evidence=proof,
        )
        changed = store.connection.execute(
            "UPDATE claims SET owner = ?, status = 'superseded', "
            "terminal_event_id = ? WHERE logical_cycle_id = ? "
            "AND status IN ('pending', 'claimed', 'blocked')",
            (claimant, evidence_event_id, cycle),
        )
        if changed.rowcount != 1:
            raise ValueError("notification supersession lost its ownership claim")

    return {
        "logical_cycle_id": cycle,
        "owner": claimant,
        "receipt_id": receipt_id,
        "already_superseded": False,
    }


def resolve(
    store: Store, *, logical_cycle_id: str, owner: str, review_id: str
) -> dict[str, object]:
    cycle = required_string(logical_cycle_id, description="notification cycle")
    claimant = required_string(owner, description="notification owner")
    terminal = required_string(review_id, description="terminal event ID")

    with store.transaction():
        row = store.connection.execute(
            "SELECT source_id, event_id, owner, status, terminal_event_id "
            "FROM claims WHERE logical_cycle_id = ?",
            (cycle,),
        ).fetchone()
        if row is None:
            raise ValueError("notification claim does not exist")
        if row["owner"] != claimant:
            raise ValueError("only the original notification owner may resolve it")
        if row["status"] == "resolved":
            if row["terminal_event_id"] != terminal:
                raise ValueError("notification already has a different terminal event")
            return {
                "logical_cycle_id": cycle,
                "review_id": terminal,
                "already_resolved": True,
            }
        if row["status"] != "claimed":
            raise ValueError("notification must be claimed before resolution")

        evidence: dict[str, object] = {
            "logical_cycle_id": cycle,
            "owner": claimant,
            "terminal_event_id": terminal,
        }
        _ = store.receipt(
            receipt_id=f"notification-resolution:{digest(evidence)}",
            source_id=cast(str, row["source_id"]),
            event_id=cast(str, row["event_id"]),
            cycle=cycle,
            status="RESOLVED",
            evidence=evidence,
        )
        changed = store.connection.execute(
            "UPDATE claims SET status = 'resolved', terminal_event_id = ? "
            "WHERE logical_cycle_id = ? AND owner = ? AND status = 'claimed'",
            (terminal, cycle, claimant),
        )
        if changed.rowcount != 1:
            raise ValueError("notification resolution lost its ownership claim")

    return {
        "logical_cycle_id": cycle,
        "review_id": terminal,
        "already_resolved": False,
    }


def resolve_batch(store: Store, value: object) -> dict[str, object]:
    """Resolve verified original-owner evidence in one atomic transaction."""
    if not isinstance(value, list) or not value:
        raise ValueError("notification resolution batch must be a nonempty JSON array")
    records = cast(list[object], value)
    if len(records) > MAXIMUM_LIMIT:
        raise ValueError(
            f"notification resolution batch cannot exceed {MAXIMUM_LIMIT} entries"
        )

    validated: list[tuple[str, str, str, str | None, str | None]] = []
    cycles: set[str] = set()
    for item in records:
        record = object_mapping(item, description="notification resolution")
        if record.get("verified") is not True:
            raise ValueError("notification resolution lacks authenticated evidence")
        cycle = required_string(
            record.get("logical_cycle_id"), description="notification cycle"
        )
        if cycle in cycles:
            raise ValueError("notification resolution batch repeats a cycle")
        cycles.add(cycle)
        replacement = record.get("replaces_review_id")
        reason = record.get("correction_reason")
        if (replacement is None) != (reason is None):
            raise ValueError("terminal correction requires its prior review and reason")
        validated.append(
            (
                cycle,
                required_string(record.get("owner"), description="notification owner"),
                required_string(record.get("review_id"), description="terminal event ID"),
                None
                if replacement is None
                else required_string(replacement, description="replaced terminal event ID"),
                None
                if reason is None
                else required_string(reason, description="terminal correction reason"),
            )
        )

    with store.transaction():
        results: list[dict[str, object]] = []
        for cycle, owner, review_id, replacement, reason in validated:
            row = store.connection.execute(
                "SELECT source_id, event_id, owner, status, terminal_event_id "
                "FROM claims WHERE logical_cycle_id = ?",
                (cycle,),
            ).fetchone()
            if row is None:
                raise ValueError("notification claim does not exist")
            if (
                row["status"] == "resolved"
                and row["terminal_event_id"] != review_id
                and replacement is not None
            ):
                if row["owner"] != owner:
                    raise ValueError("only the original notification owner may correct it")
                if row["terminal_event_id"] != replacement:
                    raise ValueError("terminal correction does not match the prior review")
                assert reason is not None
                evidence: dict[str, object] = {
                    "logical_cycle_id": cycle,
                    "owner": owner,
                    "previous_terminal_event_id": replacement,
                    "terminal_event_id": review_id,
                    "reason": reason,
                }
                _ = store.receipt(
                    receipt_id=f"notification-resolution-correction:{digest(evidence)}",
                    source_id=cast(str, row["source_id"]),
                    event_id=cast(str, row["event_id"]),
                    cycle=cycle,
                    status="CORRECTED",
                    evidence=evidence,
                )
                changed = store.connection.execute(
                    "UPDATE claims SET terminal_event_id = ? "
                    "WHERE logical_cycle_id = ? AND owner = ? "
                    "AND status = 'resolved' AND terminal_event_id = ?",
                    (review_id, cycle, owner, replacement),
                )
                if changed.rowcount != 1:
                    raise ValueError("terminal correction lost its original owner")
                results.append(
                    {
                        "logical_cycle_id": cycle,
                        "review_id": review_id,
                        "previous_review_id": replacement,
                        "corrected": True,
                    }
                )
                continue
            if row["status"] != "resolved":
                _ = claim(store, logical_cycle_id=cycle, owner=owner)
            results.append(
                resolve(
                    store,
                    logical_cycle_id=cycle,
                    owner=owner,
                    review_id=review_id,
                )
            )

    return {"resolution_count": len(results), "results": results}
