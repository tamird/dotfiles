"""Serialize authenticated provider receipts independently of model turns."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import socket
import socketserver
import sqlite3
from typing import cast

from .config import require_writer_leadership
from .model import MAXIMUM_LIMIT, compact_json
from .source import ingest
from .store import Store


MAXIMUM_REQUEST_BYTES = 4 * 1024 * 1024
PROVIDER_TIMEOUT_SECONDS = 65


class _ReceiptHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        server = cast(ReceiptServer, self.server)
        self.request.settimeout(server.provider_timeout_seconds)
        try:
            line = self.rfile.readline(MAXIMUM_REQUEST_BYTES + 1)
            if len(line) > MAXIMUM_REQUEST_BYTES:
                raise ValueError("provider receipt exceeds its size limit")
            value: object = json.loads(line)
            if not isinstance(value, list) or not value:
                raise ValueError("provider receipts must be a nonempty JSON array")
            observations = cast(list[object], value)
            if len(observations) > MAXIMUM_LIMIT:
                raise ValueError("provider receipt contains too many sources")
            results: list[dict[str, object]] = []
            errors: list[dict[str, str]] = []
            with Store(server.database) as store:
                for observation in observations:
                    try:
                        with store.transaction():
                            results.append(ingest(store, observation))
                    except (sqlite3.Error, UnicodeError, ValueError) as error:
                        source_id = "unknown"
                        if isinstance(observation, dict):
                            candidate = cast(dict[object, object], observation).get(
                                "source_id"
                            )
                            if isinstance(candidate, str) and candidate:
                                source_id = candidate
                        errors.append({"source_id": source_id, "error": str(error)})
            result: dict[str, object] = {
                "source_count": len(results),
                "results": results,
            }
            if errors:
                result["errors"] = errors
        except (OSError, sqlite3.Error, UnicodeError, ValueError) as error:
            result = {"error": str(error)}
        _ = self.wfile.write((compact_json(result) + "\n").encode())


class ReceiptServer(socketserver.UnixStreamServer):
    """One private, serial SQLite writer for existing provider readers."""

    request_queue_size = 128

    def __init__(
        self,
        socket_path: Path,
        database: Path,
        *,
        provider_timeout_seconds: float = PROVIDER_TIMEOUT_SECONDS,
    ) -> None:
        if (
            isinstance(provider_timeout_seconds, bool)
            or not math.isfinite(provider_timeout_seconds)
            or provider_timeout_seconds <= 0
            or provider_timeout_seconds > PROVIDER_TIMEOUT_SECONDS
        ):
            raise ValueError("provider timeout must be between zero and 65 seconds")
        self.database = database
        self.socket_path = socket_path
        self.provider_timeout_seconds = provider_timeout_seconds
        super().__init__(str(socket_path), _ReceiptHandler)
        os.chmod(socket_path, 0o600)


def socket_path(database: Path) -> Path:
    return database.with_name("notification-receipts.sock")


def serve_receipts(database: Path) -> None:
    """Run exactly one owner-private receipt writer until stopped."""
    require_writer_leadership(database)
    address = socket_path(database)
    if address.exists():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            try:
                probe.connect(str(address))
            except OSError:
                address.unlink()
            else:
                raise ValueError("notification receipt writer is already running")
    try:
        with ReceiptServer(address, database) as server:
            server.serve_forever(poll_interval=0.5)
    finally:
        if address.exists():
            address.unlink()


def submit_receipts(database: Path, value: object) -> dict[str, object]:
    """Deliver one actual provider observation to the sole canonical writer."""
    require_writer_leadership(database)
    if not isinstance(value, list) or not value:
        raise ValueError("provider receipts must be a nonempty JSON array")
    observations = cast(list[object], value)
    if len(observations) > MAXIMUM_LIMIT:
        raise ValueError("provider receipt contains too many sources")
    payload = (compact_json(observations) + "\n").encode()
    if len(payload) > MAXIMUM_REQUEST_BYTES:
        raise ValueError("provider receipt exceeds its size limit")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(PROVIDER_TIMEOUT_SECONDS)
        client.connect(str(socket_path(database)))
        client.sendall(payload)
        with client.makefile("rb") as response:
            line = response.readline(MAXIMUM_REQUEST_BYTES + 1)
    if not line or len(line) > MAXIMUM_REQUEST_BYTES:
        raise ValueError("receipt writer returned an invalid response")
    result: object = json.loads(line)
    if not isinstance(result, dict):
        raise ValueError("receipt writer returned an invalid response")
    response = cast(dict[str, object], result)
    error = response.get("error")
    if isinstance(error, str):
        raise ValueError(f"receipt writer rejected provider batch: {error}")
    source_count = response.get("source_count")
    if isinstance(source_count, bool) or not isinstance(source_count, int):
        raise ValueError("receipt writer returned an invalid response")
    errors = response.get("errors")
    if isinstance(errors, list) and errors:
        first = cast(list[object], errors)[0]
        if isinstance(first, dict):
            detail = cast(dict[object, object], first)
            source_id = detail.get("source_id")
            reason = detail.get("error")
            if isinstance(source_id, str) and isinstance(reason, str):
                raise ValueError(
                    f"receipt writer committed {source_count} independent "
                    f"observations and rejected {source_id}: {reason}"
                )
        raise ValueError("receipt writer returned an invalid provider error")
    return response
