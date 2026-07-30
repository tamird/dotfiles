"""Behavioral checks for private, thread-scoped steering records."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("steering_journal.py")
SPEC = importlib.util.spec_from_file_location("steering_journal", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"Cannot load steering journal: {SCRIPT}")
JOURNAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(JOURNAL)

THREAD = "01234567-89ab-4def-8123-456789abcdef"


class SteeringJournalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.runtime = self.home / "Google Drive" / "My Drive" / "Codex" / "runtime"
        self.runtime.mkdir(parents=True)
        self.inbox = self.runtime / "guidance-inbox"
        self.home_patch = patch.object(Path, "home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.environment_patch = patch.dict(
            os.environ, {"CODEX_THREAD_ID": THREAD}, clear=False
        )
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)

    def test_pending_does_not_create_private_state(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(JOURNAL.pending(argparse.Namespace()), 0)
        self.assertEqual(
            json.loads(output.getvalue()), {"thread_id": THREAD, "pending": []}
        )
        self.assertFalse(self.inbox.exists())

    def test_capture_uses_owner_only_backed_up_inbox(self) -> None:
        arguments = argparse.Namespace(
            classification="durable",
            summary="Keep private data outside reusable skills.",
            scope="skill-boundaries",
            owner="distill-session-guidance",
            source="direct-user-steering",
            evidence=None,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(JOURNAL.capture(arguments), 0)
        record = json.loads(output.getvalue())
        journal = self.inbox / f"{THREAD}.jsonl"
        self.assertEqual(record["status"], "recorded")
        self.assertEqual(self.inbox.stat().st_mode & 0o777, 0o700)
        self.assertEqual(journal.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            json.loads(journal.read_text())["summary"], arguments.summary
        )

    def test_resolving_candidate_removes_it_from_pending(self) -> None:
        arguments = argparse.Namespace(
            classification="durable",
            summary="Keep reusable workflows independent.",
            scope="skill-architecture",
            owner="distill-session-guidance",
            source="direct-user-steering",
            evidence=None,
        )
        captured = io.StringIO()
        with redirect_stdout(captured):
            self.assertEqual(JOURNAL.capture(arguments), 0)
        candidate = json.loads(captured.getvalue())["id"]
        resolution = argparse.Namespace(
            id=candidate,
            disposition="merged",
            owner="maintainer-review",
            evidence="Verified the canonical skill and its metadata.",
        )
        with redirect_stdout(io.StringIO()):
            self.assertEqual(JOURNAL.resolve(resolution), 0)
        pending = io.StringIO()
        with redirect_stdout(pending):
            self.assertEqual(JOURNAL.pending(argparse.Namespace()), 0)
        self.assertEqual(json.loads(pending.getvalue())["pending"], [])

    def test_rejects_nonprivate_inbox(self) -> None:
        self.inbox.mkdir()
        self.inbox.chmod(0o755)
        with self.assertRaisesRegex(JOURNAL.JournalError, "0700"):
            JOURNAL.journal_path(create=False)

    def test_rejects_symbolic_link_inbox(self) -> None:
        destination = self.home / "other"
        destination.mkdir(mode=0o700)
        self.inbox.symlink_to(destination, target_is_directory=True)
        with self.assertRaisesRegex(JOURNAL.JournalError, "real directory"):
            JOURNAL.journal_path(create=False)

    def test_rejects_relative_codex_home(self) -> None:
        with patch.dict(os.environ, {"CODEX_HOME": "relative"}):
            with self.assertRaisesRegex(JOURNAL.JournalError, "absolute"):
                JOURNAL.journal_path(create=False)


if __name__ == "__main__":
    unittest.main()
