"""Verify durable Codex memory migration never breaks its native path."""

from __future__ import annotations

import contextlib
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "codex-migrate-memories"
SPEC = importlib.util.spec_from_loader(
    "codex_migrate_memories", SourceFileLoader("codex_migrate_memories", str(SCRIPT))
)
assert SPEC is not None and SPEC.loader is not None
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


class MigrateMemoriesTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "native" / "memories"
        self.source.mkdir(parents=True)
        (self.source / ".git" / "objects").mkdir(parents=True)
        (self.source / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (self.source / "rollout_summaries").mkdir()
        (self.source / "rollout_summaries" / "session.md").write_text("context\n")
        (self.source / "MEMORY.md").write_text("private memory\n")
        self.destination = self.root / "durable" / "memories"
        self.destination.parent.mkdir()

    def test_help_never_migrates_memories(self) -> None:
        with patch.object(migration, "migrate") as migrate:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(migration.main(["--help"]), 0)
        migrate.assert_not_called()

    def test_invalid_arguments_never_migrate_memories(self) -> None:
        with patch.object(migration, "migrate") as migrate:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(migration.main(["--unexpected"]), 2)
        migrate.assert_not_called()

    def test_main_migrates_memories_directly_into_shared_google_drive(self) -> None:
        with (
            patch.object(migration.Path, "home", return_value=self.root),
            patch.object(migration, "migrate", return_value={"status": "migrated"}) as migrate,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(migration.main([]), 0)

        migrate.assert_called_once_with(
            self.root / ".codex" / "memories",
            self.root / "Google Drive" / "My Drive" / "Codex" / "memories",
        )

    def test_migrates_complete_git_history_and_preserves_native_path(self) -> None:
        original, expected_bytes = migration.fingerprint(self.source)
        result = migration.migrate(self.source, self.destination)

        self.assertEqual(result["status"], "migrated")
        self.assertEqual(result["files"], len(original))
        self.assertEqual(result["bytes"], expected_bytes)
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(self.source.resolve(), self.destination.resolve())
        self.assertEqual(migration.fingerprint(self.destination)[0], original)
        self.assertEqual(
            (self.source / ".git" / "HEAD").read_text(), "ref: refs/heads/main\n"
        )
        self.assertFalse(any(self.source.parent.glob(".memories.migration.*")))

    def test_already_migrated_path_is_idempotent(self) -> None:
        migration.migrate(self.source, self.destination)
        result = migration.migrate(self.source, self.destination)
        self.assertEqual(result["status"], "already_migrated")

    def test_refuses_to_overwrite_existing_durable_memory(self) -> None:
        self.destination.mkdir()
        with self.assertRaises(FileExistsError):
            migration.migrate(self.source, self.destination)
        self.assertTrue(self.source.is_dir())
        self.assertFalse(self.source.is_symlink())

    def test_refuses_nonrepository_source(self) -> None:
        (self.source / ".git" / "HEAD").unlink()
        (self.source / ".git" / "objects").rmdir()
        (self.source / ".git").rmdir()
        with self.assertRaises(NotADirectoryError):
            migration.migrate(self.source, self.destination)

    def test_refuses_preexisting_temporary_link(self) -> None:
        temporary = self.source.with_name(".memories.migration." + str(os.getpid()))
        temporary.write_text("existing work\n")
        with self.assertRaises(FileExistsError):
            migration.migrate(self.source, self.destination)
        self.assertEqual(temporary.read_text(), "existing work\n")

    def test_rolls_back_if_exchange_does_not_install_symlink(self) -> None:
        calls = []

        def invalid_swap(left: Path, right: Path) -> None:
            calls.append((left, right))

        with self.assertRaises(RuntimeError):
            migration.migrate(self.source, self.destination, swap=invalid_swap)
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.source.is_dir())
        self.assertFalse(self.source.is_symlink())
        self.assertTrue((self.source / "MEMORY.md").is_file())

    def test_preserves_internal_symlinks_without_following_them(self) -> None:
        (self.source / "summary-link").symlink_to("MEMORY.md")
        migration.migrate(self.source, self.destination)
        self.assertTrue((self.destination / "summary-link").is_symlink())
        self.assertEqual(
            (self.destination / "summary-link").readlink(), Path("MEMORY.md")
        )


if __name__ == "__main__":
    unittest.main()
