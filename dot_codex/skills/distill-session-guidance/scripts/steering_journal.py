#!/usr/bin/env python3
"""Keep sanitized steering for the current native Codex thread."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
import uuid


LOCK_TIMEOUT_SECONDS = 2.0
LOCK_RETRY_SECONDS = 0.05


class JournalError(Exception):
    """The journal cannot be accessed without weakening its invariants."""


def thread_id() -> str:
    value = os.environ.get("CODEX_THREAD_ID", "")
    try:
        canonical = str(uuid.UUID(value))
    except ValueError as error:
        raise JournalError("CODEX_THREAD_ID must be a canonical UUID") from error
    if value != canonical:
        raise JournalError("CODEX_THREAD_ID must be a canonical UUID")
    return canonical


def verified_directory(path: Path) -> None:
    try:
        status = path.lstat()
    except FileNotFoundError as error:
        raise JournalError(f"private directory does not exist: {path}") from error
    if not stat.S_ISDIR(status.st_mode) or stat.S_ISLNK(status.st_mode):
        raise JournalError(f"private path must be a real directory: {path}")
    if status.st_uid != os.getuid() or stat.S_IMODE(status.st_mode) != 0o700:
        raise JournalError(f"private directory must be owner-only (0700): {path}")


def journal_path(*, create: bool) -> tuple[str, Path | None]:
    identity = thread_id()
    home = os.environ.get("CODEX_HOME")
    if home and not Path(home).is_absolute():
        raise JournalError("CODEX_HOME must be an absolute path")
    runtime = Path.home() / "Google Drive" / "My Drive" / "Codex" / "runtime"
    try:
        status = runtime.lstat()
    except FileNotFoundError as error:
        raise JournalError(f"runtime directory does not exist: {runtime}") from error
    if (
        not stat.S_ISDIR(status.st_mode)
        or stat.S_ISLNK(status.st_mode)
        or status.st_uid != os.getuid()
    ):
        raise JournalError(f"runtime path must be an owner-owned directory: {runtime}")
    inbox = runtime / "guidance-inbox"
    try:
        verified_directory(inbox)
    except JournalError:
        if not create:
            try:
                inbox.lstat()
            except FileNotFoundError:
                return identity, None
            raise
        if inbox.exists() or inbox.is_symlink():
            raise
        try:
            inbox.mkdir(mode=0o700)
        except FileExistsError:
            pass
        verified_directory(inbox)
    path = inbox / f"{identity}.jsonl"
    if not create:
        try:
            path.lstat()
        except FileNotFoundError:
            return identity, None
    return identity, path


def open_journal(path: Path, *, create: bool, exclusive: bool) -> int:
    flags = os.O_RDWR if exclusive else os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if exclusive:
        flags |= os.O_APPEND
    if create:
        flags |= os.O_CREAT
    descriptor = os.open(path, flags, 0o600)
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_uid != os.getuid():
            raise JournalError("journal must be an owner-owned regular file")
        if stat.S_IMODE(status.st_mode) != 0o600:
            raise JournalError("journal permissions must be exactly 0600")
        visible = path.lstat()
        if (visible.st_dev, visible.st_ino) != (status.st_dev, status.st_ino):
            raise JournalError("journal changed while it was being opened")
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if time.monotonic() >= deadline:
                    raise JournalError("timed out waiting for the journal owner") from error
                time.sleep(min(LOCK_RETRY_SECONDS, max(0.0, deadline - time.monotonic())))
        locked = path.lstat()
        if (locked.st_dev, locked.st_ino) != (status.st_dev, status.st_ino):
            raise JournalError("journal changed while waiting for its lock")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def records(
    descriptor: int,
    identity: str,
    *,
    repair_incomplete: bool,
) -> tuple[list[dict[str, object]], bool]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 65_536):
        chunks.append(chunk)
        if sum(map(len, chunks)) > 4 * 1024 * 1024:
            raise JournalError("journal exceeds the bounded 4 MiB limit")
    data = b"".join(chunks)
    complete_length = data.rfind(b"\n") + 1
    incomplete = complete_length != len(data)
    complete_data = data[:complete_length] if incomplete else data
    result: list[dict[str, object]] = []
    for index, line in enumerate(complete_data.splitlines(), 1):
        try:
            item = json.loads(line)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise JournalError(f"invalid journal record at line {index}") from error
        if not isinstance(item, dict) or item.get("thread_id") != identity:
            raise JournalError(f"invalid or cross-thread journal record at line {index}")
        if item.get("version") != 1 or item.get("type") not in {"capture", "resolve"}:
            raise JournalError(f"unsupported journal record at line {index}")
        candidate = item.get("id")
        if (
            not isinstance(candidate, str)
            or len(candidate) != 64
            or any(character not in "0123456789abcdef" for character in candidate)
        ):
            raise JournalError(f"journal record has no candidate identity at line {index}")
        if item["type"] == "capture" and item.get("classification") not in {
            "durable",
            "uncertain",
        }:
            raise JournalError(f"invalid capture classification at line {index}")
        if item["type"] == "resolve" and item.get("disposition") not in {
            "promoted",
            "merged",
            "rejected",
        }:
            raise JournalError(f"invalid terminal disposition at line {index}")
        result.append(item)
    if incomplete and repair_incomplete:
        os.ftruncate(descriptor, complete_length)
        os.fsync(descriptor)
    return result, incomplete


def append_record(descriptor: int, item: dict[str, object]) -> None:
    payload = (json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    if len(payload) > 4096:
        raise JournalError("sanitized steering record exceeds 4096 bytes")
    os.lseek(descriptor, 0, os.SEEK_END)
    if os.write(descriptor, payload) != len(payload):
        os.fsync(descriptor)
        raise JournalError("journal record was incompletely written")
    os.fsync(descriptor)


def normalized(value: str, *, field: str, limit: int) -> str:
    compact = " ".join(value.split())
    if not compact:
        raise JournalError(f"{field} cannot be empty")
    if len(compact) > limit:
        raise JournalError(f"{field} exceeds {limit} characters")
    return compact


def capture(args: argparse.Namespace) -> int:
    identity = thread_id()
    summary = normalized(args.summary, field="summary", limit=500)
    if args.classification in {"one-off", "task-only"}:
        print(json.dumps({"status": "not-recorded", "classification": args.classification}))
        return 0
    scope = normalized(args.scope, field="scope", limit=120)
    owner = normalized(args.owner, field="owner", limit=160)
    source = normalized(args.source, field="source", limit=200)
    evidence = normalized(args.evidence, field="evidence", limit=500) if args.evidence else ""
    material = json.dumps([identity, args.classification, scope, owner, summary], separators=(",", ":"))
    candidate = hashlib.sha256(material.encode()).hexdigest()
    _, path = journal_path(create=True)
    assert path is not None
    descriptor = open_journal(path, create=True, exclusive=True)
    try:
        existing, _ = records(descriptor, identity, repair_incomplete=True)
        if any(item["type"] == "capture" and item["id"] == candidate for item in existing):
            print(json.dumps({"status": "already-recorded", "id": candidate}))
            return 0
        append_record(descriptor, {
            "version": 1,
            "type": "capture",
            "thread_id": identity,
            "id": candidate,
            "classification": args.classification,
            "scope": scope,
            "owner": owner,
            "summary": summary,
            "source": source,
            "evidence": evidence,
            "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
    finally:
        os.close(descriptor)
    print(json.dumps({"status": "recorded", "id": candidate}))
    return 0


def pending(args: argparse.Namespace) -> int:
    identity = thread_id()
    _, path = journal_path(create=False)
    if path is None:
        print(json.dumps({"thread_id": identity, "pending": []}))
        return 0
    descriptor = open_journal(path, create=False, exclusive=False)
    try:
        items, incomplete = records(descriptor, identity, repair_incomplete=False)
    finally:
        os.close(descriptor)
    resolved = {item["id"] for item in items if item["type"] == "resolve"}
    waiting = [item for item in items if item["type"] == "capture" and item["id"] not in resolved]
    response: dict[str, object] = {"thread_id": identity, "pending": waiting}
    if incomplete:
        response["incomplete_tail"] = True
    print(json.dumps(response, ensure_ascii=False))
    return 0


def resolve(args: argparse.Namespace) -> int:
    identity, path = journal_path(create=False)
    if path is None:
        raise JournalError("cannot resolve a candidate without its existing journal")
    owner = normalized(args.owner, field="owner", limit=160)
    evidence = normalized(args.evidence, field="evidence", limit=500)
    descriptor = open_journal(path, create=False, exclusive=True)
    try:
        items, _ = records(descriptor, identity, repair_incomplete=True)
        captures = {item["id"] for item in items if item["type"] == "capture"}
        resolved = {item["id"] for item in items if item["type"] == "resolve"}
        if args.id not in captures:
            raise JournalError("cannot resolve a nonexistent steering candidate")
        if args.id in resolved:
            raise JournalError("steering candidate is already resolved")
        append_record(descriptor, {
            "version": 1,
            "type": "resolve",
            "thread_id": identity,
            "id": args.id,
            "disposition": args.disposition,
            "owner": owner,
            "evidence": evidence,
            "resolved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
    finally:
        os.close(descriptor)
    print(json.dumps({"status": "resolved", "id": args.id, "disposition": args.disposition}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("capture")
    first.add_argument("--classification", choices=("durable", "uncertain", "task-only", "one-off"), required=True)
    first.add_argument("--summary", required=True)
    first.add_argument("--scope", default="cross-task")
    first.add_argument("--owner", default="unassigned")
    first.add_argument("--source", default="direct-user-steering")
    first.add_argument("--evidence")
    first.set_defaults(handler=capture)
    second = commands.add_parser("pending")
    second.set_defaults(handler=pending)
    third = commands.add_parser("resolve")
    third.add_argument("--id", required=True)
    third.add_argument("--disposition", choices=("promoted", "merged", "rejected"), required=True)
    third.add_argument("--owner", required=True)
    third.add_argument("--evidence", required=True)
    third.set_defaults(handler=resolve)
    args = parser.parse_args()
    try:
        return args.handler(args)
    except (JournalError, OSError, UnicodeError) as error:
        print(f"steering journal: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
