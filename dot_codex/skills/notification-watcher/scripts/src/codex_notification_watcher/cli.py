"""Bounded notification commands without provider-specific dependencies."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import sys
from typing import cast

from .ci import classify_ci_jobs
from .config import RuntimeConfig
from .manifest import bootstrap
from .model import (
    MAXIMUM_LIMIT,
    bounded_limit,
    compact_json,
    object_mapping,
    required_string,
)
from .receipt_server import serve_receipts, submit_receipts
from .slack_threads import classify_slack_pages
from .source import (
    claim,
    ingest,
    record_failure,
    register_source,
    replay,
    resolve,
    resolve_batch,
    supersede,
)
from .store import Store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-notification-watcher",
        description="Record authenticated notifications without calling providers.",
    )
    _ = parser.add_argument(
        "--database", type=Path, help="existing notification-state database"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name in ("health", "pending"):
        child = commands.add_parser(name)
        _ = child.add_argument("--limit", type=int, default=12)
        if name == "pending":
            _ = child.add_argument(
                "--category",
                choices=(
                    "review_request",
                    "control_task",
                    "owned_feedback",
                    "ci_update",
                ),
            )

    for name in (
        "classify-ci",
        "init",
        "stats",
        "source-register",
        "source-failure",
        "ingest",
        "ingest-batch",
        "resolve-batch",
        "heartbeat",
        "serve-receipts",
        "submit-batch",
        "slack-events",
    ):
        _ = commands.add_parser(name)

    bootstrap_parser = commands.add_parser("bootstrap")
    _ = bootstrap_parser.add_argument("--manifest", type=Path, required=True)

    synchronize_parser = commands.add_parser("sync-manifest")
    _ = synchronize_parser.add_argument("--manifest", type=Path, required=True)

    replay_parser = commands.add_parser("replay")
    _ = replay_parser.add_argument("source_id")

    claim_parser = commands.add_parser("claim")
    _ = claim_parser.add_argument("logical_cycle_id")
    _ = claim_parser.add_argument("--owner", required=True)

    resolve_parser = commands.add_parser("resolve")
    _ = resolve_parser.add_argument("logical_cycle_id")
    _ = resolve_parser.add_argument("--owner", required=True)
    _ = resolve_parser.add_argument("--review-id", required=True)

    supersede_parser = commands.add_parser("supersede")
    _ = supersede_parser.add_argument("logical_cycle_id")
    _ = supersede_parser.add_argument("--owner", required=True)
    return parser


def _input() -> object:
    try:
        return cast(object, json.load(sys.stdin))
    except json.JSONDecodeError as error:
        raise ValueError(
            "standard input must contain a complete JSON document"
        ) from error


def main(argv: list[str] | None = None) -> int:
    """Run one explicit, transaction-bounded intake operation."""
    args = _parser().parse_args(argv)
    command = cast(str, args.command)
    if command == "classify-ci":
        print(compact_json(asdict(classify_ci_jobs(_input()))))
        return 0
    if command == "slack-events":
        print(compact_json(classify_slack_pages(_input())))
        return 0
    config = RuntimeConfig.from_environment()
    supplied = cast(Path | None, args.database)
    database = supplied if supplied is not None else config.database

    if command == "serve-receipts":
        serve_receipts(database)
        return 0
    if command == "submit-batch":
        print(compact_json(submit_receipts(database, _input())))
        return 0

    with Store(database, initialize=command in {"init", "bootstrap"}) as store:
        result: object
        if command == "init":
            result = {"initialized": True}
        elif command in {"bootstrap", "sync-manifest"}:
            manifest = cast(Path, args.manifest)
            with manifest.open(encoding="utf-8") as file:
                value = cast(object, json.load(file))
            result = bootstrap(store, value)
        elif command == "health":
            result = store.health(
                limit=bounded_limit(cast(int, args.limit)),
                maximum_age_seconds=config.maximum_source_age_seconds,
            )
        elif command == "pending":
            result = store.pending(
                limit=bounded_limit(cast(int, args.limit)),
                category=cast(str | None, args.category),
            )
        elif command == "stats":
            result = store.stats()
        elif command == "source-register":
            result = register_source(store, _input())
        elif command == "source-failure":
            result = record_failure(store, _input())
        elif command == "ingest":
            result = ingest(store, _input())
        elif command == "ingest-batch":
            observations = _input()
            if not isinstance(observations, list) or not observations:
                raise ValueError("source observation batch must be a nonempty JSON array")
            source_observations = cast(list[object], observations)
            if len(source_observations) > MAXIMUM_LIMIT:
                raise ValueError(
                    f"source observation batch cannot exceed {MAXIMUM_LIMIT} sources"
                )
            with store.transaction():
                results = [
                    ingest(store, observation)
                    for observation in source_observations
                ]
            result = {"source_count": len(results), "results": results}
        elif command == "resolve-batch":
            result = resolve_batch(store, _input())
        elif command == "heartbeat":
            value = object_mapping(_input(), description="heartbeat")
            result = store.heartbeat(
                owner=required_string(value.get("owner"), description="heartbeat owner"),
                observed_at=required_string(
                    value.get("observed_at"), description="heartbeat observation"
                ),
            )
        elif command == "replay":
            result = replay(store, cast(str, args.source_id))
        elif command == "claim":
            result = claim(
                store,
                logical_cycle_id=cast(str, args.logical_cycle_id),
                owner=cast(str, args.owner),
            )
        elif command == "resolve":
            result = resolve(
                store,
                logical_cycle_id=cast(str, args.logical_cycle_id),
                owner=cast(str, args.owner),
                review_id=cast(str, args.review_id),
            )
        elif command == "supersede":
            result = supersede(
                store,
                logical_cycle_id=cast(str, args.logical_cycle_id),
                owner=cast(str, args.owner),
                evidence=object_mapping(_input(), description="supersession evidence"),
            )
        else:
            raise ValueError("unknown notification-watcher command")

    print(compact_json(result))
    return 0


def run() -> int:
    """Provide a quiet, actionable failure for invalid local operations."""
    try:
        return main()
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"notification watcher: {error}", file=sys.stderr)
        return 2
